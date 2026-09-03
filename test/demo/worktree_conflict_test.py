"""Why no neuron was found or pinged (Marco 2026-09-03 ~07:20 local).

Codex's chair on thread fable-opus had worktree convoy-wt-fable, but that
folder carried its own .convoy/id from an older thread (fable-luna). Without
--root the CLI answered for the wrong thread, so every addressed row on the
real thread went unread. Three guarantees follow:

1. seat/join refuse a worktree that is bound to a DIFFERENT thread.
2. whoami reports the thread the root names AND the thread the cwd walks up
   to, with conflict=true when they differ.
3. `convoy skills --worktree W` refreshes the identity skill copies so a
   long-lived pane is not left reading a stale sheet.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.identity import install_neuron_identity, skill_text
from convoy.lifecycle import join
from convoy.panes import identify


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class ForeignWorktreeRefused(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "opus")
        self.other = Path(tempfile.mkdtemp())      # a worktree bound to another thread
        ensure_id(self.other)
        bind(self.other, "luna")
        self.clean = Path(tempfile.mkdtemp())      # a worktree with no binding

    def test_seat_refuses_worktree_bound_to_another_thread(self):
        with self.assertRaises(ValueError) as cm:
            seat(self.root, "codex", "c-opus", worktree=str(self.other))
        msg = str(cm.exception)
        self.assertIn("luna", msg)
        self.assertIn("opus", msg)

    def test_join_refuses_too_and_clean_or_same_root_worktree_is_fine(self):
        with self.assertRaises(ValueError):
            join(self.root, "codex", session_id="j-opus", worktree=str(self.other))
        self.assertTrue(join(self.root, "codex", session_id="j2-opus", worktree=str(self.clean))["ok"])
        self.assertTrue(seat(self.root, "claude", "s-opus", worktree=str(self.root)))

    def test_whoami_reports_root_thread_vs_cwd_thread_conflict(self):
        seat(self.root, "codex", "c-opus", worktree=str(self.clean))
        procs = [{"pid": 12, "ppid": 1, "cmdline": "codex", "cwd": None},
                 {"pid": 30, "ppid": 12, "cmdline": "sh", "cwd": None}]
        me = identify(self.root, pid=30, procs=procs, cwd=str(self.other / "sub"))
        self.assertEqual(me["root_thread"], "opus")
        self.assertEqual(me["cwd_thread"], "luna")
        self.assertTrue(me["conflict"])
        self.assertIn("--root", me["ask"])
        ok = identify(self.root, pid=30, procs=procs, cwd=str(self.clean))
        self.assertEqual((ok["chair"], ok["conflict"]), ("c-opus", False))

    def test_seat_and_join_refuse_worktree_held_by_another_chair(self):
        wt = Path(tempfile.mkdtemp())
        seat(self.root, "claude", "chair-a", worktree=str(wt))
        with self.assertRaises(ValueError) as cm:
            seat(self.root, "codex", "chair-b", worktree=str(wt))
        self.assertIn("chair-a", str(cm.exception))
        self.assertIn("chair-b", str(cm.exception))
        self.assertIn(str(wt), str(cm.exception))
        with self.assertRaises(ValueError):
            join(self.root, "grok", session_id="chair-c", worktree=str(wt))
        other = Path(tempfile.mkdtemp())
        self.assertTrue(seat(self.root, "codex", "chair-b", worktree=str(other)))
        again = seat(self.root, "claude", "chair-a", worktree=str(wt))
        self.assertEqual(again["session_id"], "chair-a")


class SkillsRefresh(unittest.TestCase):
    def test_stale_copies_are_rewritten(self):
        wt = Path(tempfile.mkdtemp())
        first = install_neuron_identity(wt)
        self.assertTrue(first["written"])
        stale = wt / ".claude" / "skills" / "neuron-identity" / "SKILL.md"
        stale.write_text("old sheet: python -m convoy send\n", encoding="utf-8")
        rc, card = _run_cli(wt, "skills", "--worktree", str(wt))
        self.assertEqual(rc, 0)
        self.assertTrue(card["written"])
        self.assertEqual(stale.read_text(encoding="utf-8"), skill_text())
        rc, again = _run_cli(wt, "skills", "--worktree", str(wt))
        self.assertFalse(again["written"])


if __name__ == "__main__":
    unittest.main()
