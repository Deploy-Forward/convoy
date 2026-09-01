import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import bring_up, ensure_first_run, resume_argv
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.identity import GROK_AGENT_RELATIVE, ensure_grok_agent


def _agent_path(wt: Path) -> Path:
    return Path(wt) / GROK_AGENT_RELATIVE


class GrokAgentFirstRun(unittest.TestCase):
    """Issue #15: first-run writes a Convoy-owned grok agent file and
    bring_up/resume_argv pass --agent for grok seats that have none."""

    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home.start()
        self.addCleanup(self._home.stop)

    def test_ensure_grok_agent_writes_convoy_owned_file_idempotent(self):
        first = ensure_grok_agent(self.wt)
        self.assertTrue(first["ok"])
        self.assertTrue(first["written"])
        path = _agent_path(self.wt)
        self.assertTrue(path.is_file())
        self.assertEqual(first["agent"], str(path))
        low = path.read_text(encoding="utf-8").lower()
        self.assertIn("neuron", low)
        self.assertIn("not grok bot", low)
        self.assertIn("role.md", low)
        self.assertIn("never invent", low)
        self.assertNotIn("ola-brain side-chat", low)
        second = ensure_grok_agent(self.wt)
        self.assertTrue(second["ok"])
        self.assertFalse(second["written"])
        self.assertEqual(second["agent"], str(path))

    def test_first_run_grok_returns_agent_card_codex_does_not(self):
        card = ensure_first_run({"to": "grok", "worktree": str(self.wt)})
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("agent_written"))
        self.assertEqual(card.get("agent_path"), str(_agent_path(self.wt)))
        self.assertTrue(_agent_path(self.wt).is_file())
        other = Path(tempfile.mkdtemp())
        codex = ensure_first_run({"to": "codex", "worktree": str(other)})
        self.assertTrue(codex.get("ok"))
        self.assertFalse(codex.get("agent_written"))
        self.assertIsNone(codex.get("agent_path"))
        self.assertFalse(_agent_path(other).exists())

    def test_first_run_skips_agent_when_worktree_is_home(self):
        card = ensure_first_run({"to": "grok", "worktree": str(self.fake_home)})
        self.assertTrue(card.get("ok"))
        self.assertFalse(card.get("agent_written"))
        self.assertFalse(_agent_path(self.fake_home).exists())

    def test_bring_up_passes_agent_and_stores_it_on_the_seat(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "cloud-prove")
        seat(root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1")
        d = bring_up(root)
        self.assertTrue(d["ok"], d)
        win = d["windows"][0]
        agent = str(_agent_path(self.wt))
        argv = win["argv"]
        self.assertIn("--agent", argv)
        self.assertEqual(argv[argv.index("--agent") + 1], agent)
        self.assertLess(argv.index("--agent"), argv.index("--resume"))
        rows = list_seats(root)
        self.assertEqual(rows[0]["agent"], agent)
        # idempotent: a second bring_up appends no new seat row
        seats_file = root / ".convoy" / "seats.jsonl"
        lines_before = seats_file.read_text(encoding="utf-8").strip().splitlines()
        d2 = bring_up(root)
        self.assertTrue(d2["ok"])
        lines_after = seats_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines_after), len(lines_before))

    def test_bring_up_keeps_explicit_seat_agent(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "cloud-prove")
        seat(root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1", agent="agents/cloud-g1.md")
        d = bring_up(root)
        self.assertTrue(d["ok"], d)
        argv = d["windows"][0]["argv"]
        self.assertEqual(argv[argv.index("--agent") + 1], "agents/cloud-g1.md")
        rows = list_seats(root)
        self.assertEqual(rows[0]["agent"], "agents/cloud-g1.md")

    def test_first_run_seat_without_vendor_uuid_gets_agent_but_no_resume(self):
        card = ensure_first_run({"to": "grok", "worktree": str(self.wt)})
        argv = resume_argv({"to": "grok", "worktree": str(self.wt), "agent": card.get("agent_path")})
        self.assertIn("--agent", argv)
        self.assertNotIn("--resume", argv)


if __name__ == "__main__":
    unittest.main()
