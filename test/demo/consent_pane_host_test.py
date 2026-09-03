import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.consent import consume_consent, grant_consent, request_consent
from convoy.convoy import bind, ensure_id, list_seats
from convoy.lifecycle import join
from convoy.pane_host import close_managed_pane, host_state_path, run_host
from convoy.targeted_launch import launch_seat


def _which(*present):
    names = {str(name).lower() for name in present}

    def lookup(name):
        key = str(name).lower()
        if key in names or key.removesuffix(".exe") in names:
            return "C:\\Tools\\" + str(name)
        return None

    return lookup


def _run(root, *argv):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = out.getvalue().strip()
    return rc, (json.loads(raw) if raw else None), err.getvalue()


class ConsentRail(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "consent-thread")
        self.worktree = Path(tempfile.mkdtemp())

    def test_consent_is_two_turn_scoped_and_one_time(self):
        waiting = request_consent(
            self.root,
            "trust-worktree",
            session_id="grok-chair",
            to="grok",
            worktree=str(self.worktree),
        )
        self.assertFalse(waiting["ok"])
        self.assertEqual(waiting["state"], "awaiting-user-consent")
        prompt = waiting["consent_request"]["prompt"]
        self.assertIn(str(self.worktree), prompt)
        self.assertIn("hooks", prompt.lower())
        self.assertNotIn("token", json.dumps(waiting).lower())

        granted = grant_consent(self.root, waiting["consent_request"]["request_id"])
        self.assertTrue(granted["ok"])
        token = granted["consent"]
        consumed = consume_consent(
            self.root,
            token,
            "trust-worktree",
            session_id="grok-chair",
            to="grok",
            worktree=str(self.worktree),
        )
        self.assertEqual(consumed["request_id"], waiting["consent_request"]["request_id"])
        with self.assertRaisesRegex(ValueError, "already consumed"):
            consume_consent(
                self.root,
                token,
                "trust-worktree",
                session_id="grok-chair",
                to="grok",
                worktree=str(self.worktree),
            )

    def test_scope_mismatch_does_not_consume_grant(self):
        waiting = request_consent(
            self.root,
            "close-chair",
            session_id="chair-one",
            to="codex",
            worktree=str(self.worktree),
        )
        token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            consume_consent(
                self.root,
                token,
                "close-chair",
                session_id="chair-two",
                to="codex",
                worktree=str(self.worktree),
            )
        consumed = consume_consent(
            self.root,
            token,
            "close-chair",
            session_id="chair-one",
            to="codex",
            worktree=str(self.worktree),
        )
        self.assertEqual(consumed["action"], "close-chair")

    @mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True})
    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\grok.exe")
    def test_untrusted_grok_pauses_then_scoped_consent_adds_vendor_trust_flag(
        self, _which_harness, _prepare
    ):
        row = join(
            self.root,
            "grok",
            session_id="grok-gated",
            worktree=str(self.worktree),
        )["seat"]
        calls = []
        common = {
            "runner": lambda argv: calls.append(argv) or {"ok": True, "pid": 44},
            "env": {"WT_SESSION": "window"},
            "which": _which("wt"),
            "platform_name": "nt",
            "trust_probe": lambda _seat: False,
        }
        waiting = launch_seat(self.root, row["session_id"], **common)
        self.assertFalse(waiting["ok"])
        self.assertEqual(waiting["state"], "awaiting-user-consent")
        self.assertEqual(calls, [])

        grant = grant_consent(self.root, waiting["consent_request"]["request_id"])
        launched = launch_seat(
            self.root, row["session_id"], consent=grant["consent"], **common
        )
        self.assertTrue(launched["ok"])
        self.assertEqual(len(calls), 1)
        self.assertIn("--trust", launched["harness_argv"])
        self.assertIn("convoy.pane_host", launched["argv"])
        self.assertNotIn("--trust", launched["argv"])
        latest = {s["session_id"]: s for s in list_seats(self.root)}["grok-gated"]
        self.assertTrue(latest["trust_worktree"])

    @mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True})
    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\grok.exe")
    def test_trusted_grok_launches_without_trust_flag_or_consent(
        self, _which_harness, _prepare
    ):
        """Live grok-to-grok: inspect-yes on a new worktree must not pause or pass --trust."""
        row = join(
            self.root,
            "grok",
            session_id="grok-trusted",
            worktree=str(self.worktree),
        )["seat"]
        calls = []
        launched = launch_seat(
            self.root,
            row["session_id"],
            runner=lambda argv: calls.append(argv) or {"ok": True, "pid": 45},
            env={"WT_SESSION": "window"},
            which=_which("wt"),
            platform_name="nt",
            trust_probe=lambda _seat: True,
        )
        self.assertTrue(launched["ok"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--trust", launched["harness_argv"])
        self.assertIn("convoy.pane_host", launched["argv"])
        latest = {s["session_id"]: s for s in list_seats(self.root)}["grok-trusted"]
        self.assertFalse(bool(latest.get("trust_worktree")))

    def test_consent_cli_grants_only_an_existing_request(self):
        waiting = request_consent(
            self.root,
            "close-chair",
            session_id="cli-chair",
            to="codex",
            worktree=str(self.worktree),
        )
        rc, card, _err = _run(
            self.root, "consent", "--grant", waiting["consent_request"]["request_id"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(card["ok"])
        self.assertTrue(card["consent"])


class ManagedPaneHost(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "host-thread")
        self.worktree = Path(tempfile.mkdtemp())
        self.row = join(
            self.root,
            "codex",
            session_id="managed-chair",
            worktree=str(self.worktree),
        )["seat"]

    def _close_consent(self):
        waiting = request_consent(
            self.root,
            "close-chair",
            session_id="managed-chair",
            to="codex",
            worktree=str(self.worktree),
        )
        return grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]

    def test_unmanaged_old_pane_returns_manual_remedy_before_consent(self):
        card = close_managed_pane(self.root, "managed-chair")
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "manual-close-required")
        self.assertIn("Ctrl+D", card["remedy"])
        self.assertNotIn("consent_request", card)

    def test_managed_close_pauses_for_consent_then_writes_exact_request(self):
        state_path = host_state_path(self.root, "managed-chair")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "session_id": "managed-chair",
                    "status": "running",
                    "host_pid": 101,
                    "child_pid": 202,
                }
            ),
            encoding="utf-8",
        )
        waiting = close_managed_pane(self.root, "managed-chair")
        self.assertFalse(waiting["ok"])
        self.assertEqual(waiting["state"], "awaiting-user-consent")
        token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
        closed = close_managed_pane(self.root, "managed-chair", consent=token)
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["state"], "close-requested")
        self.assertEqual(closed["host_pid"], 101)

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_host_terminates_its_owned_child_and_returns_zero_on_consented_close(
        self, _which_harness
    ):
        """The close request arrives AFTER the host is running (a consented
        close during the session). The host terminates its child, consumes the
        request file, releases the launch claim, and returns 0."""
        from convoy.targeted_launch import _claim, _claim_path

        close_path = host_state_path(self.root, "managed-chair").with_suffix(".close")
        close_path.parent.mkdir(parents=True, exist_ok=True)
        _claim(self.root, "managed-chair")

        class FakeProcess:
            pid = 303
            polls = 0

            def poll(self):
                self.polls += 1
                if self.polls == 2:
                    close_path.write_text("{}\n", encoding="utf-8")
                return None

        terminated = []
        rc = run_host(
            self.root,
            "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda proc: terminated.append(proc.pid),
            sleep=lambda _seconds: None,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(terminated, [303])
        state = json.loads(host_state_path(self.root, "managed-chair").read_text())
        self.assertEqual(state["status"], "close-request-acknowledged")
        self.assertFalse(close_path.is_file(), "close request must be consumed")
        self.assertFalse(_claim_path(self.root, "managed-chair").is_file(), "launch claim must be released")

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_stale_close_request_does_not_kill_a_fresh_host(self, _which_harness):
        """2026-09-03 live: a relaunched grok-lead was terminated two seconds
        after start by the .close file that had closed its predecessor. A
        request on disk before the host starts belongs to the past."""
        from convoy.targeted_launch import _claim, _claim_path

        close_path = host_state_path(self.root, "managed-chair").with_suffix(".close")
        close_path.parent.mkdir(parents=True, exist_ok=True)
        close_path.write_text('{"requested_at": "yesterday"}\n', encoding="utf-8")
        _claim(self.root, "managed-chair")

        class FakeProcess:
            pid = 404
            polls = 0

            def poll(self):
                self.polls += 1
                return 0 if self.polls >= 3 else None   # child exits normally later

        terminated = []
        rc = run_host(
            self.root,
            "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda proc: terminated.append(proc.pid),
            sleep=lambda _seconds: None,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(terminated, [])
        self.assertFalse(close_path.is_file(), "stale request is discarded at start")
        state = json.loads(host_state_path(self.root, "managed-chair").read_text())
        self.assertEqual(state["status"], "child-exited")
        self.assertFalse(_claim_path(self.root, "managed-chair").is_file(), "claim released when the child exits")


if __name__ == "__main__":
    unittest.main()
