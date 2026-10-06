"""Printed commands run as printed, and every refusal's next step is a command the CLI accepts.

Two ways a printed command failed the person who copied it:

1. Backslashes. `convoy --root C:\\x\\y` reaches Git Bash as `C:xy`. Every command Convoy
   prints for a person or a neuron uses forward slashes, the interpreter path included.
2. Refusals that name a parameter instead of a flag ("opt_in required"), or give no next
   step at all ("chair already exists"). A refusal's next step is registered in
   convoy.refusal and each one is parsed with the CLI's own parser here.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cmd
from convoy.convoy import bind, ensure_id, seat


class PrintedCommandsUseForwardSlashes(unittest.TestCase):
    def setUp(self):
        cmd._CONVOY_COMMAND = None
        self.addCleanup(setattr, cmd, "_CONVOY_COMMAND", None)

    def test_convoy_root_command_uses_forward_slashes(self):
        with mock.patch.object(cmd.shutil, "which", return_value=None), \
             mock.patch.object(cmd.sys, "executable", "C:\\Python314\\python.exe"):
            out = cmd.convoy_root_command(Path("C:/x/y"))
        self.assertNotIn("\\", out)
        self.assertEqual(out, "C:/Python314/python.exe -m convoy --root C:/x/y")

    def test_relaunch_note_built_with_convoy_root_command(self):
        from convoy.inbox import pending
        from convoy.relaunch import relaunch
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "printed")
        wt = Path(tempfile.mkdtemp())
        seat(root, "codex", "chair", worktree=str(wt))
        runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            card = relaunch(root, runner=runner, alive=lambda _pid: False)
        self.assertTrue(card["launched"], card)
        [note] = [m for m in pending(root, "chair") if m.get("label") == "relaunch"]
        body = str(note.get("body"))
        self.assertIn(cmd.convoy_root_command(root) + " feed --since", body)
        self.assertNotIn("\\", body)


class RefusalNextStepsParse(unittest.TestCase):
    def test_every_refusal_next_step_parses_under_cli_argparse(self):
        from convoy import crew, install, lifecycle, nudge, targeted_launch, thread_list  # noqa: F401 (register)
        from convoy.cli import build_parser
        from convoy.refusal import NEXT_STEPS, parseable
        self.assertGreaterEqual(len(NEXT_STEPS), 5, NEXT_STEPS)
        parser = build_parser()
        for argv in NEXT_STEPS:
            with self.subTest(argv=argv):
                self.assertTrue(parseable(parser, argv), argv)

    def test_join_duplicate_names_title_or_session_id(self):
        from convoy.lifecycle import join
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "dup")
        seat(root, "codex", "codex-dup", worktree=str(Path(tempfile.mkdtemp())))
        with self.assertRaises(ValueError) as ctx:
            join(root, "codex", worktree=str(Path(tempfile.mkdtemp())))
        text = str(ctx.exception)
        self.assertIn("chair already exists: codex-dup", text)
        self.assertIn("--title <name>", text)
        self.assertIn("--session-id <id>", text)

    def test_install_live_names_opt_in_flag(self):
        from convoy.install import install
        card = install("codex", dry_run=False, opt_in=False, installer=mock.Mock())
        self.assertFalse(card["ok"], card)
        self.assertIn("--opt-in", card["error"])
        self.assertIn("opt_in", card["error"])


if __name__ == "__main__":
    unittest.main()
