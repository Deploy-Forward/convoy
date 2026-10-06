import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import bring_up, ensure_first_run, resume_argv
from convoy.convoy import bind, ensure_id, list_seats, seat

CONVOY_AGENT = Path(".grok") / "agents" / "convoy-neuron.md"


class GrokAgentArgument(unittest.TestCase):
    """Convoy writes no grok agent file. A grok seat runs with --agent only when the
    person gave it one; the file an earlier Convoy wrote is not passed."""

    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home.start()
        self.addCleanup(self._home.stop)

    def test_first_run_writes_no_agent_file_for_any_harness(self):
        for hid in ("grok", "codex"):
            wt = Path(tempfile.mkdtemp())
            card = ensure_first_run({"to": hid, "worktree": str(wt)})
            self.assertTrue(card.get("ok"), card)
            self.assertNotIn("agent_written", card)
            self.assertNotIn("agent_path", card)
            self.assertFalse((wt / CONVOY_AGENT).exists(), hid)

    def test_bring_up_passes_no_agent_and_stores_none(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "cloud-prove")
        seat(root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1")
        # A live bring-up (stub runner) writes no agent file and stores no agent.
        def live_bring_up(root):
            with mock.patch("convoy.bringup.ensure_inbox_hooks", return_value={"ok": True, "written": False}), \
                 mock.patch("convoy.bringup.ensure_hook_trust", return_value={"trust": []}):
                return bring_up(root, runner=lambda *a, **k: {"ok": True, "pid": 4242},
                                 allow_unverified_launch=True)
        d = live_bring_up(root)
        self.assertTrue(d["ok"], d)
        self.assertNotIn("--agent", d["windows"][0]["argv"])
        self.assertFalse(list_seats(root)[0].get("agent"))
        self.assertFalse((self.wt / CONVOY_AGENT).exists())
        # idempotent: a second live bring_up appends no new seat row
        seats_file = root / ".convoy" / "seats.jsonl"
        lines_before = seats_file.read_text(encoding="utf-8").strip().splitlines()
        d2 = live_bring_up(root)
        self.assertTrue(d2["ok"])
        lines_after = seats_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines_after), len(lines_before))

    def test_bring_up_keeps_explicit_seat_agent(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "cloud-prove")
        seat(root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1", agent="agents/cloud-lead.md")
        d = bring_up(root)
        self.assertTrue(d["ok"], d)
        argv = d["windows"][0]["argv"]
        self.assertEqual(argv[argv.index("--agent") + 1], "agents/cloud-lead.md")
        self.assertLess(argv.index("--agent"), argv.index("--resume"))
        self.assertEqual(list_seats(root)[0]["agent"], "agents/cloud-lead.md")

    def test_a_seat_row_naming_the_old_convoy_agent_file_gets_no_agent(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "cloud-prove")
        old = str(self.wt / CONVOY_AGENT)
        seat(root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1", agent=old)
        d = bring_up(root)
        self.assertTrue(d["ok"], d)
        self.assertNotIn("--agent", d["windows"][0]["argv"])

    def test_first_run_seat_without_vendor_uuid_gets_no_agent_and_no_resume(self):
        ensure_first_run({"to": "grok", "worktree": str(self.wt)})
        argv = resume_argv({"to": "grok", "worktree": str(self.wt)})
        self.assertNotIn("--agent", argv)
        self.assertNotIn("--resume", argv)


if __name__ == "__main__":
    unittest.main()
