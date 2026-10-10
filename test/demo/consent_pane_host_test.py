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
from convoy.pane_host import close_managed_pane, host_state_path, nudge_request_path, request_nudge, run_host
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
            "allow_unverified_launch": True,  # Grok eligibility is independent of trust consent.
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
        self.assertTrue(any(a == "convoy.pane_host" or Path(str(a)).name.lower().startswith("convoy-pane-host") for a in launched["argv"]), launched["argv"])  # the pane runs the Convoy pane host: console script, or python -m on an uninstalled checkout
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
            allow_unverified_launch=True,
        )
        self.assertTrue(launched["ok"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--trust", launched["harness_argv"])
        self.assertTrue(any(a == "convoy.pane_host" or Path(str(a)).name.lower().startswith("convoy-pane-host") for a in launched["argv"]), launched["argv"])  # the pane runs the Convoy pane host: console script, or python -m on an uninstalled checkout
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
                    "incarnation": 4,
                }
            ),
            encoding="utf-8",
        )
        with mock.patch("convoy.pane_host.pid_alive", return_value=True):  # the recorded host is running
            waiting = close_managed_pane(self.root, "managed-chair")
            self.assertFalse(waiting["ok"])
            self.assertEqual(waiting["state"], "awaiting-user-consent")
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            closed = close_managed_pane(self.root, "managed-chair", consent=token)
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["state"], "close-requested")
        self.assertEqual(closed["host_pid"], 101)
        # The request names the life it is for, so a later body can tell it
        # was not addressed to itself.
        written = json.loads(host_state_path(self.root, "managed-chair").with_suffix(".close").read_text(encoding="utf-8-sig"))
        self.assertEqual(written["incarnation"], 4)
        self.assertEqual(written["session_id"], "managed-chair")
        self.assertTrue(written["requested_at"])

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
                    # A consented close during the session cites the life it
                    # closes; this is the only body, so incarnation 1.
                    close_path.write_text(
                        json.dumps({"session_id": "managed-chair", "incarnation": 1}) + "\n",
                        encoding="utf-8",
                    )
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
    def test_stale_close_citing_older_incarnation_never_kills_fresh_host(self, _which_harness):
        """A relaunched agent could be terminated two seconds after start by
        the request that had closed its predecessor. Discarding whatever sat
        on disk before the host started covers only that one race; a request
        that lands a moment AFTER a fresh body
        starts is indistinguishable by time. The incarnation is the
        difference, so the request cites one and the host checks it."""
        from convoy.layer import feed_since

        close_path = host_state_path(self.root, "managed-chair").with_suffix(".close")
        close_path.parent.mkdir(parents=True, exist_ok=True)

        class FakeProcess:
            pid = 808
            polls = 0

            def poll(self):
                self.polls += 1
                if self.polls == 2:
                    close_path.write_text(
                        json.dumps({"session_id": "managed-chair", "incarnation": 0,
                                    "requested_at": "yesterday"}) + "\n",
                        encoding="utf-8",
                    )
                return 0 if self.polls >= 5 else None

        terminated = []
        rc = run_host(
            self.root,
            "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda proc: terminated.append(proc.pid),
            sleep=lambda _seconds: None,
        )
        self.assertEqual(terminated, [], "a request from an older life must never kill this one")
        self.assertEqual(rc, 0)
        self.assertFalse(close_path.is_file(), "the stale request is consumed, not left to fire again")
        rows = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "close-ignored"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["chair"], "managed-chair")
        self.assertEqual(rows[0]["incarnation"], 1)
        self.assertEqual(rows[0]["cited"], 0)

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_child_exit_stamps_pane_row_with_returncode(self, _which_harness):
        """Death is a row. A body that died at boot left nothing behind:
        the pane scrolled its error away and closed, and the feed showed a
        chair that simply never acked. The host owns the child, so it is the
        only place that can record the exit code."""
        from convoy.layer import feed_since

        class FakeProcess:
            pid = 707
            polls = 0

            def poll(self):
                self.polls += 1
                return 3 if self.polls >= 2 else None

        def fake_popen(argv, cwd=None, stderr=None, **_kwargs):
            return FakeProcess()

        rc = run_host(
            self.root,
            "managed-chair",
            popen=fake_popen,
            terminate=lambda _proc: None,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(rc, 3)
        rows = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "pane"]
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["chair"], "managed-chair")
        self.assertEqual(row["exit"], 3)
        self.assertEqual(row["incarnation"], 1)
        # The origin loop beats on a local transition instead of waiting out
        # its idle backoff; the exit of a body is one.
        self.assertTrue((self.root / ".convoy" / "beat-request").exists())

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\grok.exe")
    def test_the_childs_stderr_is_inherited_not_sunk_to_a_file(self, _which_harness):
        """Root cause of the black pane: sinking the child's stderr to a file this
        host alone read silenced a TUI that draws there instead of on stdout
        (Grok 1.0.50 does), leaving the pane black while the neuron worked.
        stderr is now inherited exactly like stdout and stdin already were -
        this test pins the call shape so a regression is a failing assertion,
        not a black pane somebody notices days later."""
        seen = {}

        class FakeProcess:
            pid = 808
            polls = 0

            def poll(self):
                self.polls += 1
                return 0 if self.polls >= 2 else None

        def fake_popen(argv, cwd=None, stderr=None, **_kwargs):
            seen["stderr"] = stderr
            return FakeProcess()

        run_host(self.root, "managed-chair", popen=fake_popen,
                 terminate=lambda _proc: None, sleep=lambda _seconds: None)
        self.assertIsNone(seen["stderr"], "inherited (same as stdout/stdin), never redirected to a sink")
        self.assertFalse(host_state_path(self.root, "managed-chair").with_suffix(".stderr").exists(),
                         "no sink file is created at all")

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_host_pulses_while_the_body_is_up(self, _which_harness):
        """The host is the only voice on a chair's pulse while the body is
        mid-turn. Stop pulses at a turn end and the waiter pulses between
        turns; both go quiet during a long one, and a chair working hard used
        to look exactly like a chair that had died."""
        from convoy.pulse import read_pulse

        ticks = iter([0.0, 10.0, 61.0, 200.0])

        class FakeProcess:
            pid = 808
            polls = 0

            def __init__(self, sink):
                pass

            def poll(self):
                self.polls += 1
                return 0 if self.polls >= 3 else None

        written = []
        real_write = __import__("convoy.pulse", fromlist=["write_pulse"]).write_pulse

        def spy(root, chair, **kw):
            written.append(kw.get("pulse_source"))
            return real_write(root, chair, **kw)

        with mock.patch("convoy.pane_host.write_pulse", side_effect=spy):
            run_host(self.root, "managed-chair", popen=lambda argv, cwd=None, stderr=None, **k: FakeProcess(stderr),
                     terminate=lambda _p: None, sleep=lambda _s: None, clock=lambda: next(ticks))
        # t=0 and t=61 only: 10 s after the first is not a second minute.
        self.assertEqual(written, ["host", "host"], written)
        self.assertEqual(read_pulse(self.root, "managed-chair")["pulse_source"], "host")
        self.assertEqual(read_pulse(self.root, "managed-chair")["incarnation"], 1)

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_stale_close_request_does_not_kill_a_fresh_host(self, _which_harness):
        """A relaunched agent could be terminated two seconds after start by
        the .close file that had closed its predecessor. A
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

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_host_types_a_pending_nudge_request_and_records_typed_at(self, _which_harness):
        """A live nudge arriving mid-session is typed through the console
        the host already shares with its child, then the request is consumed
        and the state row carries proof (nudge_id, typed_at) for the caller
        to read back -- never a byte of the typed text stays in the record
        beyond what the caller already sent."""
        from convoy.layer import feed_since

        root = self.root

        class FakeProcess:
            pid = 909
            polls = 0

            def poll(self):
                self.polls += 1
                if self.polls == 2:
                    request_nudge(root, "managed-chair", text="wake nudge=abc123",
                                  nudge_id="abc123", consent="tok-1")
                return 0 if self.polls >= 5 else None

        typed = []
        rc = run_host(
            self.root, "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda _p: None,
            sleep=lambda _s: None,
            console_writer=lambda text: typed.append(text) or {"ok": True, "count": len(text) + 1},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(typed, ["wake nudge=abc123"])
        state = json.loads(host_state_path(self.root, "managed-chair").read_text())
        self.assertEqual(state["last_nudge"]["nudge_id"], "abc123")
        self.assertTrue(state["last_nudge"]["ok"])
        self.assertTrue(state["last_nudge"]["typed_at"])
        self.assertFalse(nudge_request_path(self.root, "managed-chair").is_file(), "the request is consumed")
        rows = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "nudge-typed"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["nudge_id"], "abc123")

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_host_records_a_failed_type_without_crashing_the_loop(self, _which_harness):
        root = self.root

        class FakeProcess:
            pid = 910
            polls = 0

            def poll(self):
                self.polls += 1
                if self.polls == 2:
                    request_nudge(root, "managed-chair", text="wake nudge=def456",
                                  nudge_id="def456", consent="tok-2")
                return 0 if self.polls >= 5 else None

        rc = run_host(
            self.root, "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda _p: None,
            sleep=lambda _s: None,
            console_writer=lambda _text: {"ok": False, "error": "WriteConsoleInputW failed: GetLastError=6"},
        )
        self.assertEqual(rc, 0)
        state = json.loads(host_state_path(self.root, "managed-chair").read_text())
        self.assertEqual(state["last_nudge"]["nudge_id"], "def456")
        self.assertFalse(state["last_nudge"]["ok"])
        self.assertIsNone(state["last_nudge"]["typed_at"])
        self.assertIn("GetLastError", state["last_nudge"]["error"])
        self.assertFalse(nudge_request_path(self.root, "managed-chair").is_file())

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_stale_nudge_request_from_a_previous_body_is_discarded_at_start(self, _which_harness):
        """Same rule as the stale close request: anything on disk before this
        host started belongs to a body that is already gone."""
        request_nudge(self.root, "managed-chair", text="stale", nudge_id="old-id", consent="tok-0")

        class FakeProcess:
            pid = 911
            polls = 0

            def poll(self):
                self.polls += 1
                return 0 if self.polls >= 3 else None

        typed = []
        rc = run_host(
            self.root, "managed-chair",
            popen=lambda *_a, **_k: FakeProcess(),
            terminate=lambda _p: None,
            sleep=lambda _s: None,
            console_writer=lambda text: typed.append(text) or {"ok": True},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(typed, [], "a request written before this body started must never fire")
        self.assertFalse(nudge_request_path(self.root, "managed-chair").is_file())


if __name__ == "__main__":
    unittest.main()
