import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id
from convoy.synapse import send_one


def _probe_ok(_to):
    return {"usage_remaining": None, "limited": False, "raw": None}


class SeatWorktreePack(unittest.TestCase):
    """Issue #14: seat worktrees have no .convoy; --root owns thread identity."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.root)
        bind(self.root, "cloud-prove")
        self.wt = Path(tempfile.mkdtemp())
        (self.wt / "role.md").write_text("seat persona\n", encoding="utf-8")

    def test_seat_worktree_pack_overlays_home_convoy_id(self):
        card = send_one(self.root, "grok", "ping", dry_run=True, worktree=str(self.wt))
        pointers = card["pointers"]
        self.assertEqual(pointers["convoy_id"], self.cid)
        self.assertEqual(pointers["thread_key"], "cloud-prove")
        # seat pointers stay from the seat checkout, not the home layer
        self.assertEqual(pointers["role"], str(self.wt / "role.md"))
        self.assertIsNone(pointers["thread"])
        self.assertEqual(pointers["worktree"], str(self.wt))
        self.assertIn(self.cid, card["stdin"])
        self.assertIn("cloud-prove", card["stdin"])

    def test_live_card_stdin_carries_home_convoy_id(self):
        def runner(to, body, **_k):
            return {"ok": True, "to": to, "session_id": "sess-" + to, "model": None, "usage_remaining": None, "body": "ACK"}

        card = send_one(self.root, "grok", "ping", runner=runner, worktree=str(self.wt), probe_fn=_probe_ok)
        self.assertTrue(card["ok"])
        self.assertEqual(card["convoy_id"], self.cid)
        self.assertEqual(card["pointers"]["convoy_id"], self.cid)
        self.assertEqual(card["pointers"]["thread_key"], "cloud-prove")
        blob = json.loads(card["stdin"].splitlines()[1])
        self.assertEqual(blob["convoy_id"], self.cid)
        self.assertEqual(blob["thread_key"], "cloud-prove")

    def test_missing_home_layer_keeps_seat_values_never_invents(self):
        bare_root = Path(tempfile.mkdtemp())
        card = send_one(bare_root, "grok", "ping", dry_run=True, worktree=str(self.wt))
        self.assertIsNone(card["pointers"]["convoy_id"])
        self.assertIsNone(card["pointers"]["thread_key"])
        # a seat checkout with its own .convoy id stays; overlay never blanks it
        convoy = self.wt / ".convoy"
        convoy.mkdir()
        (convoy / "id").write_text("cvy_seatlocal\n", encoding="utf-8")
        card2 = send_one(bare_root, "grok", "ping", dry_run=True, worktree=str(self.wt))
        self.assertEqual(card2["pointers"]["convoy_id"], "cvy_seatlocal")

    def test_home_layer_wins_over_seat_layer_id(self):
        convoy = self.wt / ".convoy"
        convoy.mkdir()
        (convoy / "id").write_text("cvy_stale_seat_copy\n", encoding="utf-8")
        card = send_one(self.root, "grok", "ping", dry_run=True, worktree=str(self.wt))
        self.assertEqual(card["pointers"]["convoy_id"], self.cid)


if __name__ == "__main__":
    unittest.main()
