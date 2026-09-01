import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.synapse import send_one


def _limited_probe(_to):
    return {"usage_remaining": {"session_pct": 100}, "limited": True, "raw": "session 100%"}


class LimitedSendAsk(unittest.TestCase):
    """Issue #16: the limited refuse card asks for bring_up/handoff instead of
    a bare "<to> limited" error. No TUI steal, no sibling, no quota guess."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_limited_refuse_card_asks_bring_up_or_handoff(self):
        spawned = {"n": 0}

        def runner(*_a, **_k):
            spawned["n"] += 1
            return {"ok": True, "to": "claude", "session_id": "no", "model": None, "usage_remaining": None, "body": "no"}

        card = send_one(self.root, "claude", "hi", runner=runner, probe_fn=_limited_probe)
        self.assertFalse(card["ok"])
        self.assertTrue(card.get("refused"))
        self.assertEqual(card["error"], "claude limited")
        self.assertEqual(spawned["n"], 0)
        ask = card.get("ask")
        self.assertIsInstance(ask, dict)
        self.assertEqual(ask["action"], "bring_up")
        self.assertEqual(ask["handoff"], ".ola/*handoff*")
        low = ask["text"].lower()
        self.assertIn("ask the user", low)
        self.assertIn("bring_up", low)
        self.assertIn("open a pane", low)
        self.assertIn("handoff", low)
        self.assertIn("do not steal", low)
        self.assertIn("sibling", low)
        self.assertIn("quota", low)

    def test_limited_grok_remaining_stays_json_null(self):
        def probe(_to):
            # even a lying probe must not surface a grok meter
            return {"usage_remaining": {"session_pct": 100}, "limited": True, "raw": "x"}

        card = send_one(self.root, "grok", "hi", probe_fn=probe)
        self.assertTrue(card.get("refused"))
        self.assertIsNone(card["usage_remaining"])
        self.assertIsInstance(card.get("ask"), dict)

    def test_ok_send_card_has_no_ask(self):
        def runner(to, body, **_k):
            return {"ok": True, "to": to, "session_id": "sess-x", "model": None, "usage_remaining": None, "body": "ACK"}

        def probe(_to):
            return {"usage_remaining": None, "limited": False, "raw": None}

        card = send_one(self.root, "claude", "hi", runner=runner, probe_fn=probe)
        self.assertTrue(card["ok"])
        self.assertNotIn("ask", card)


if __name__ == "__main__":
    unittest.main()
