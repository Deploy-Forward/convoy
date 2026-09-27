"""The declared id must survive to the argv that is EXECUTED.

The failure this pins: a claude seat (claude-sonnet-5) got `resume=<minted
id>`, `resume_for=claude`, `resume_minted=True` within seconds of the join -
the mint worked. But the child's real command line was

    claude.EXE --model claude-sonnet-5 <boot prompt> --permission-mode ...

with no `--session-id`, so Claude created its own session under another id
and the row named a conversation that does not exist.

The cause is an ordering in `pane_host.run_host`:

    child_argv = pane_child_argv(row, root=root)   # mints, and DECLARES the id
    launch = read_launch_argv(root, session_id)
    if launch and launch.get("argv"):
        child_argv = [str(a) for a in launch["argv"]]   # ... and discards it

The launch record wins, by design (it holds the boot prompt with the
seated token and the live flags). But `isolated_wt_argv` writes that record
from `resume_argv(seat)` on a seat that has not been minted yet, so the
record cannot carry the flag. The mint's row write survives; its argv does
not. Every launch through the crew path was affected.

The fix is to mint BEFORE the record is built, which is what the design
always said - "writes it on the neuron row BEFORE the body starts". Then the
record already carries the flag and the precedence is harmless.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import isolated_wt_argv
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.pane_host import read_launch_argv, run_host


def _row(root, session_id):
    for r in list_seats(root):
        if r.get("session_id") == session_id:
            return r
    raise AssertionError("no seat row for " + session_id)


class TheDeclaredIdReachesTheExecutedArgv(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        self.worktree = self.root / "wt"
        self.worktree.mkdir()
        seat(self.root, "claude", "mint-live", worktree=str(self.worktree), model="claude-sonnet-5")

    def _build(self):
        isolated_wt_argv("t1", [_row(self.root, "mint-live")], wt="wt.exe", root=self.root)

    def test_the_launch_record_carries_the_id_the_row_was_minted_with(self):
        self._build()
        record = read_launch_argv(self.root, "mint-live")
        self.assertIsNotNone(record, "bring_up wrote no launch record")
        argv = [str(a) for a in record["argv"]]
        minted = _row(self.root, "mint-live")["resume"]
        self.assertTrue(minted, "no id was minted before the record was written")
        self.assertIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], minted)

    def test_the_child_the_host_actually_spawns_carries_it(self):
        """The assertion that matters: the CHILD argv, not the argv some
        builder returned and something else then replaced."""
        self._build()
        spawned = []

        class FakeProcess:
            pid = 4242

            def poll(self):
                return 0

        def fake_popen(argv, **_kwargs):
            spawned.append([str(a) for a in argv])
            return FakeProcess()

        run_host(self.root, "mint-live", popen=fake_popen,
                 terminate=lambda _p: None, sleep=lambda _s: None)
        self.assertEqual(len(spawned), 1, spawned)
        argv = spawned[0]
        row = _row(self.root, "mint-live")
        self.assertIs(row["resume_minted"], True)
        self.assertIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], row["resume"])

    def test_the_id_is_declared_once_not_once_per_builder(self):
        self._build()
        argv = [str(a) for a in read_launch_argv(self.root, "mint-live")["argv"]]
        self.assertEqual(argv.count("--session-id"), 1)
        self.assertNotIn("--resume", argv)


if __name__ == "__main__":
    unittest.main()
