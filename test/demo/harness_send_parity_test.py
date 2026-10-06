"""A send addressed to a harness says the same thing dry and live, and the board hears the truth.

`send --to claude` while a claude chair is seated is refused on purpose (naming a vendor is
not naming a neuron). The dry run skipped that check and reported ok, the refusal carried
no reason, so the board was told "harness_absent" while a chair sat there, and with no chair
at all the board's brief went to the fake runner and the board was told "active". The dry
run now refuses the same way, the refusal says "occupied", and the board's delivery resolves
the harness to its one seated chair, or refuses with a reason.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat, update_seat
from convoy.inbox import pending
from convoy.layer import feed_since
from convoy.origin_loop import _deliver_via_synapse
from convoy.synapse import send_one

EPOCH = "1970-01-01T00:00:00.000000Z"


class HarnessSendParity(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "parity")

    def chair(self, sid, harness="claude"):
        seat(self.root, harness, sid, worktree=str(Path(tempfile.mkdtemp())))

    def synapse_rows(self):
        return [r for r in feed_since(self.root, EPOCH) if r.get("kind") == "synapse"]

    def test_send_dry_run_runs_seat_exists_check(self):
        self.chair("claude-a")
        dry = send_one(self.root, "claude", "hello", dry_run=True)
        live = send_one(self.root, "claude", "hello")
        self.assertFalse(dry["ok"], dry)
        self.assertEqual(dry["error"], live["error"])
        self.assertIn("seat exists", dry["error"])

    def test_harness_send_refusal_carries_refused_reason_occupied(self):
        self.chair("claude-a")
        card = send_one(self.root, "claude", "hello")
        self.assertFalse(card["ok"])
        self.assertEqual(card["refused"], "occupied")
        self.assertEqual(card["delivery"], "refused")

    def test_origin_loop_delivers_to_unique_seated_chair_by_id(self):
        self.chair("claude-a")
        sent = _deliver_via_synapse(root=self.root, link={"harness": "claude"}, body="the brief")
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(sent["session_id"], "claude-a")
        self.assertEqual(sent["delivery"], "queued")
        self.assertEqual(pending(self.root, "claude-a")[0]["body"], "the brief")

    def test_origin_loop_never_uses_fake_runner(self):
        sent = _deliver_via_synapse(root=self.root, link={"harness": "claude"}, body="the brief")
        self.assertFalse(sent["ok"], sent)
        self.assertEqual(sent["refused"], "harness_absent")
        self.assertEqual(self.synapse_rows(), [])

    def test_origin_loop_refuses_two_chairs_and_names_them(self):
        self.chair("claude-a")
        self.chair("claude-b")
        sent = _deliver_via_synapse(root=self.root, link={"harness": "claude"}, body="the brief")
        self.assertFalse(sent["ok"], sent)
        self.assertEqual(sent["refused"], "no_resume_target")
        self.assertIn("claude-a", sent["detail"])
        self.assertIn("claude-b", sent["detail"])
        self.assertEqual(self.synapse_rows(), [])

    def test_origin_loop_detached_only_chair_has_no_resume_target(self):
        self.chair("claude-a")
        update_seat(self.root, "claude-a", detached=True)
        sent = _deliver_via_synapse(root=self.root, link={"harness": "claude"}, body="the brief")
        self.assertFalse(sent["ok"], sent)
        self.assertEqual(sent["refused"], "no_resume_target")


if __name__ == "__main__":
    unittest.main()
