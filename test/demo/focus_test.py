"""focus --seat: tmux adapter is injectable; WT stays focused:false until evidenced."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.focus import WT_FOCUS_EVIDENCE, focus_seat
from convoy.mcp_http import _WRITE_TOOLS


class FocusSeat(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "grok", "g1", worktree=str(self.root))

    def test_unknown_seat_is_not_focused(self):
        card = focus_seat(self.root, "nope")
        self.assertFalse(card["ok"])
        self.assertFalse(card["focused"])
        self.assertIn("unknown seat", card["reason"])

    def test_tmux_select_pane_with_fake_runner(self):
        calls = []

        def runner(argv):
            calls.append(list(argv))
            return {"ok": True, "returncode": 0, "argv": argv}

        with mock.patch.dict(os.environ, {"TMUX": "1,2,3"}):
            card = focus_seat(self.root, "g1", runner=runner, target="%5")
        self.assertTrue(card["ok"])
        self.assertTrue(card["focused"])
        self.assertEqual(card["host"], "tmux")
        self.assertEqual(calls, [["tmux", "select-pane", "-t", "%5"]])
        self.assertIsNone(card["reason"])

    def test_tmux_without_target_is_not_focused(self):
        def boom(argv):
            raise AssertionError("runner must not run without a target")

        with mock.patch.dict(os.environ, {"TMUX": "1"}):
            card = focus_seat(self.root, "g1", runner=boom)
        self.assertFalse(card["focused"])
        self.assertIn("no pane target", card["reason"])

    def test_windows_terminal_is_evidence_gated(self):
        with mock.patch.dict(os.environ, {"TMUX": ""}, clear=False):
            os.environ.pop("TMUX", None)
            with mock.patch("convoy.focus.shutil.which", return_value=r"C:\WindowsApps\wt.exe"):
                with mock.patch("convoy.focus.os.name", "nt"):
                    card = focus_seat(self.root, "g1")
        self.assertTrue(card["ok"])
        self.assertFalse(card["focused"])
        self.assertEqual(card["host"], "windows-terminal")
        self.assertIn("no evidenced", card["reason"])
        self.assertFalse(card["evidence"]["evidenced"])
        self.assertFalse(WT_FOCUS_EVIDENCE["evidenced"])

    def test_focus_is_a_write_gated_host_action(self):
        self.assertIn("focus", _WRITE_TOOLS)


if __name__ == "__main__":
    unittest.main()
