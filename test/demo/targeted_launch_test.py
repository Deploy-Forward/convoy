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
from convoy.convoy import bind, ensure_id, seat
from convoy.lifecycle import join
from convoy.targeted_launch import (
    active_pane_argv,
    launch_choices,
    launch_seat,
    terminal_capability,
)


def _which(*present):
    names = {str(name).lower() for name in present}

    def lookup(name):
        key = str(name).lower()
        if key in names or key.removesuffix(".exe") in names:
            return "C:\\Tools\\" + str(name)
        return None

    return lookup


def _base_name_portable(value: object) -> str:
    return str(value).replace("\\", "/").split("/")[-1].lower()


def _run(root, *argv):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = out.getvalue().strip()
    return rc, (json.loads(raw) if raw else None), err.getvalue()


class TargetedLaunch(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "launch-thread")
        self.worktree = Path(tempfile.mkdtemp())

    def test_windows_terminal_requires_an_active_windows_terminal_session(self):
        absent = terminal_capability(
            env={}, which=_which("wt"), platform_name="nt"
        )
        self.assertFalse(absent["can_split"])
        self.assertEqual(absent["reason"], "no-supported-active-terminal")

        present = terminal_capability(
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt"),
            platform_name="nt",
        )
        self.assertTrue(present["can_split"])
        self.assertEqual(present["adapter"], "windows-terminal")
        self.assertEqual(present["target"], "most-recent-window")
        self.assertFalse(present["can_close_exact"])
        self.assertIn("no-close-pane", present["close_reason"])

    def test_tmux_targets_the_callers_pane_and_wins_over_outer_terminal(self):
        cap = terminal_capability(
            env={
                "TMUX": "/tmp/tmux-1000/default,1,0",
                "TMUX_PANE": "%7",
                "WT_SESSION": "outer-window",
            },
            which=_which("tmux", "wt"),
            platform_name="posix",
        )
        self.assertTrue(cap["can_split"])
        self.assertEqual(cap["adapter"], "tmux")
        self.assertEqual(cap["target"], "%7")
        self.assertFalse(cap["can_close_exact"])
        self.assertEqual(cap["close_reason"], "created-pane-id-not-yet-captured")

    def test_unsupported_terminal_fails_closed(self):
        cap = terminal_capability(
            env={"TERM": "xterm-256color"}, which=_which(), platform_name="posix"
        )
        self.assertFalse(cap["can_split"])
        self.assertNotIn("argv", cap)

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_windows_argv_splits_one_pane_not_a_new_window(self, _which_harness):
        row = join(
            self.root,
            "codex",
            session_id="pane-proof",
            worktree=str(self.worktree),
            title="proof",
        )["seat"]
        cap = terminal_capability(
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt"),
            platform_name="nt",
        )
        argv = active_pane_argv(row, cap)
        self.assertEqual(argv[:4], ["C:\\Tools\\wt", "-w", "0", "split-pane"])
        self.assertIn("-d", argv)
        self.assertIn(str(self.worktree), argv)
        self.assertEqual(sum(_base_name_portable(a) == "codex.exe" for a in argv), 1)
        self.assertNotIn("--window", argv)
        self.assertNotIn("new", argv[:4])
        self.assertNotIn("resume", argv)

    @mock.patch("convoy.bringup.shutil.which", return_value="/usr/local/bin/codex")
    def test_tmux_argv_explicitly_targets_callers_pane(self, _which_harness):
        row = join(
            self.root,
            "codex",
            session_id="tmux-proof",
            worktree=str(self.worktree),
        )["seat"]
        cap = terminal_capability(
            env={"TMUX": "/tmp/tmux/default,1,0", "TMUX_PANE": "%9"},
            which=_which("tmux"),
            platform_name="posix",
        )
        argv = active_pane_argv(row, cap)
        self.assertEqual(argv[:4], ["C:\\Tools\\tmux", "split-window", "-t", "%9"])
        self.assertIn("-c", argv)
        self.assertIn(str(self.worktree), argv)
        self.assertEqual(argv.count("split-window"), 1)

    @mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True})
    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_launch_seat_invokes_runner_once_for_only_requested_fresh_chair(
        self, _which_harness, _prepare
    ):
        one = join(
            self.root,
            "codex",
            session_id="chair-one",
            worktree=str(self.worktree),
        )["seat"]
        join(
            self.root,
            "codex",
            session_id="chair-two",
            worktree=str(Path(tempfile.mkdtemp())),
        )
        calls = []

        def runner(argv):
            calls.append(argv)
            return {"ok": True, "pid": 42}

        card = launch_seat(
            self.root,
            one["session_id"],
            runner=runner,
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt"),
            platform_name="nt",
        )
        self.assertTrue(card["ok"])
        self.assertEqual(card["session_id"], "chair-one")
        self.assertEqual(len(calls), 1)
        self.assertIn("chair-one", " ".join(calls[0]))
        self.assertNotIn("chair-two", " ".join(calls[0]))

        duplicate = launch_seat(
            self.root,
            one["session_id"],
            runner=runner,
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt"),
            platform_name="nt",
        )
        self.assertFalse(duplicate["ok"])
        self.assertIn("already claimed", duplicate["error"])
        self.assertEqual(len(calls), 1)

    @mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True})
    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_failed_terminal_spawn_releases_claim_for_explicit_retry(
        self, _which_harness, _prepare
    ):
        row = join(
            self.root,
            "codex",
            session_id="retry-chair",
            worktree=str(self.worktree),
        )["seat"]
        attempts = []

        def runner(argv):
            attempts.append(argv)
            if len(attempts) == 1:
                return {"ok": False, "error": "adapter refused"}
            return {"ok": True, "pid": 99}

        kwargs = {
            "runner": runner,
            "env": {"WT_SESSION": "vendor-window"},
            "which": _which("wt"),
            "platform_name": "nt",
        }
        first = launch_seat(self.root, row["session_id"], **kwargs)
        second = launch_seat(self.root, row["session_id"], **kwargs)
        self.assertFalse(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(len(attempts), 2)

    def test_launch_refuses_a_resume_token_or_non_joined_seat(self):
        seat(
            self.root,
            "codex",
            "already-running",
            worktree=str(self.worktree),
            resume="real-vendor-id",
        )
        card = launch_seat(
            self.root,
            "already-running",
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt"),
            platform_name="nt",
        )
        self.assertFalse(card["ok"])
        self.assertIn("fresh join/swap", card["error"])
        self.assertNotIn("argv", card)

    def test_choices_lists_safe_harness_worktree_and_terminal_facts(self):
        seat(
            self.root,
            "codex",
            "known-seat",
            worktree=str(self.worktree),
            resume="DO-NOT-EXPOSE",
        )
        card = launch_choices(
            self.root,
            cwd=self.worktree,
            env={"WT_SESSION": "vendor-window"},
            which=_which("wt", "codex", "claude"),
            platform_name="nt",
            git_worktrees=lambda _paths: [str(self.worktree)],
        )
        encoded = json.dumps(card)
        self.assertTrue(card["ok"])
        self.assertIn("codex", [h["id"] for h in card["harnesses"] if h["installed"]])
        self.assertIn(str(self.worktree), card["worktrees"])
        self.assertIn("known-seat", [s["session_id"] for s in card["seats"]])
        self.assertNotIn("DO-NOT-EXPOSE", encoded)
        # harnesses[].effort.evidence quotes live --help text, which names
        # --resume flags (agy/hermes/pi, 2026-09-01). That prose must be the
        # contract's own bytes, and nothing else on the card may say resume.
        from convoy.harness_contract import load_harness_contract

        # Same rule for where.cloud.evidence (2026-09-04): grok's quotes
        # `--restore-code ... when resuming` and `--resume of a remote session`.
        contract = {h["id"]: (h.get("effort") or {}).get("evidence") for h in load_harness_contract()["harnesses"]}
        cloud = {h["id"]: (h.get("cloud") or {}).get("evidence") for h in load_harness_contract()["harnesses"]}
        for h in card["harnesses"]:
            self.assertEqual(h["effort"]["evidence"], contract[h["id"]])
            self.assertEqual(h["where"]["cloud"]["evidence"], cloud[h["id"]])
        scrubbed = {**card, "harnesses": [
            {**h, "effort": {**h["effort"], "evidence": None},
             "where": {**h["where"], "cloud": {**h["where"]["cloud"], "evidence": None}}}
            for h in card["harnesses"]]}
        self.assertNotIn("resume", json.dumps(scrubbed).lower())

    @mock.patch("convoy.cli.active_pane_runner")
    @mock.patch("convoy.cli.launch_seat")
    def test_join_launch_routes_only_the_newly_minted_chair(self, launch_mock, runner_mock):
        launch_mock.return_value = {
            "ok": True,
            "session_id": "new-chair-launch-thread",
            "adapter": "windows-terminal",
        }
        rc, card, _err = _run(
            self.root,
            "join",
            "--to",
            "codex",
            "--worktree",
            str(self.worktree),
            "--title",
            "new-chair",
            "--launch",
        )
        self.assertEqual(rc, 0)
        self.assertTrue(card["ok"])
        self.assertEqual(card["seat"]["session_id"], "new-chair-launch-thread")
        self.assertEqual(card["launch"]["session_id"], "new-chair-launch-thread")
        launch_mock.assert_called_once()
        self.assertEqual(launch_mock.call_args.args[1], "new-chair-launch-thread")
        self.assertIs(launch_mock.call_args.kwargs["runner"], runner_mock)

    def test_choices_cli_is_the_memory_free_discovery_command(self):
        with mock.patch(
            "convoy.cli.launch_choices",
            return_value={"ok": True, "harnesses": [], "worktrees": [], "seats": []},
        ):
            rc, card, _err = _run(self.root, "choices")
        self.assertEqual(rc, 0)
        self.assertTrue(card["ok"])

    def test_join_boot_prompt_points_to_shared_thread_root_not_new_worktree(self):
        card = join(
            self.root,
            "codex",
            session_id="absolute-pointer-chair",
            worktree=str(self.worktree),
        )
        prompt = card["seat"]["boot_prompt"]
        self.assertIn(str(self.root / "thread.md"), prompt)
        self.assertNotIn("Read thread.md", prompt)

    def test_join_refuses_to_overwrite_an_existing_chair(self):
        join(
            self.root,
            "codex",
            session_id="stable-chair",
            worktree=str(self.worktree),
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            join(
                self.root,
                "claude",
                session_id="stable-chair",
                worktree=str(Path(tempfile.mkdtemp())),
            )


if __name__ == "__main__":
    unittest.main()
