"""A card says ok only when the thing it reports happened.

Three cards reported success for a non-outcome: a relaunch in which every chair was refused
(ok true, exit 0), a start card read outside any thread (ok true, "who: 0 neurons"), and a
nudge that never identified its pane (ok true, identified false). Each is ok false now, and
the CLI exits 1. A relaunch whose window failed carries that failure in its top-level error.
"""
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
from convoy.convoy import bind, ensure_id, seat, update_seat
from convoy.nudge import nudge_seat
from convoy.relaunch import relaunch
from convoy.start_card import build_start_card


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(list(argv))
    return rc, out.getvalue()


class TruthfulCards(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "truthful")
        self.worktree = Path(tempfile.mkdtemp())
        seat(self.root, "codex", "chair", worktree=str(self.worktree))

    def test_relaunch_all_refused_is_not_ok(self):
        update_seat(self.root, "chair", incarnation=1, harness_pid=999,
                    launched_at="2026-09-17T10:00:00.000000Z", process_state="running")
        card = relaunch(self.root, runner=None, alive=lambda pid: int(pid) == 999)
        self.assertFalse(card["ok"], card)
        self.assertFalse(card["launched"])
        self.assertEqual(card["next"], ["relaunch --seat chair --take-over"])
        self.assertIn("refused", card.get("error", ""))

    def test_relaunch_window_failure_reaches_the_top_level_error(self):
        runner = mock.Mock(return_value={"ok": False, "error": "synthetic spawn failure"})
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            card = relaunch(self.root, runner=runner, alive=lambda _pid: False)
        self.assertFalse(card["launched"], card)
        self.assertFalse(card["ok"], card)
        self.assertIn("synthetic spawn failure", str(card.get("error")))

    def test_start_card_outside_thread_reports_unknown(self):
        neutral = Path(tempfile.mkdtemp())
        card = build_start_card(neutral)
        self.assertFalse(card["ok"], card)
        self.assertIsNone(card["who"])
        self.assertTrue(any("unknown" in line for line in card["lines"]), card["lines"])
        rc, out = _run("--root", str(neutral), "start-card", "--json")
        self.assertNotEqual(rc, 0, out)
        self.assertFalse(json.loads(out)["ok"])

    def test_start_card_inside_thread_is_ok(self):
        card = build_start_card(self.root, neurons_fn=lambda _r: {"neurons": []})
        self.assertTrue(card["ok"], card)

    def test_nudge_unidentified_is_not_ok(self):
        for dry in (True, False):
            card = nudge_seat(self.root, "chair", dry_run=dry, panes_fn=lambda _r: {"chairs": []},
                              host_records_fn=lambda _r: [])
            self.assertFalse(card["identified"], card)
            self.assertFalse(card["ok"], (dry, card))
            self.assertEqual(card["reason"], "seat not in panes view")


if __name__ == "__main__":
    unittest.main()
