"""A recorded trust consent is read before the Grok trust probe runs.

A Grok chair whose worktree the person already approved (trust_worktree on the seat) was
still probed with `grok inspect` first, and a probe that failed (a timeout, or output with
no trust line) refused the launch outright. The recorded consent now answers first, and a
probe that fails asks for consent, carrying the probe's error, instead of refusing.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, update_seat
from convoy.lifecycle import join
from convoy.targeted_launch import launch_seat


def _which(name):
    return "C:\\Tools\\" + str(name)


class GrokTrustOrder(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "trust-order")
        self.worktree = Path(tempfile.mkdtemp())
        self.sid = join(self.root, "grok", session_id="grok-chair", worktree=str(self.worktree))["seat"]["session_id"]
        self.calls = []

    def probe(self, result):
        def run(_row):
            self.calls.append(_row)
            if isinstance(result, Exception):
                raise result
            return result
        return run

    def launch(self, probe):
        return launch_seat(self.root, self.sid, env={"WT_SESSION": "window"}, which=_which,
                           platform_name="nt", trust_probe=probe)

    def test_grok_launch_with_trust_worktree_skips_probe(self):
        update_seat(self.root, self.sid, trust_worktree=True)
        card = self.launch(self.probe(ValueError("Grok trust preflight failed: synthetic probe failure")))
        self.assertEqual(self.calls, [], "a recorded consent answers before the probe")
        self.assertTrue(card["ok"], card)

    def test_grok_probe_error_routes_to_consent_request(self):
        card = self.launch(self.probe(ValueError("Grok trust preflight failed: synthetic probe failure")))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(card["ok"], card)
        self.assertEqual(card.get("state"), "awaiting-user-consent", card)
        self.assertIn("synthetic probe failure", card.get("probe_error", ""))

    def test_untrusted_grok_still_asks_for_consent(self):
        card = self.launch(self.probe(False))
        self.assertEqual(card.get("state"), "awaiting-user-consent", card)
        self.assertNotIn("probe_error", card)


if __name__ == "__main__":
    unittest.main()
