import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.layer import feed_since
from convoy.synapse import send_one
from convoy.usage import _parse_claude, probe

class Phase5Usage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("b")

    def test_grok_probe_is_null_not_zero(self):
        p = probe("grok")
        self.assertIsNone(p["usage_remaining"])
        self.assertFalse(p["limited"])
        self.assertNotEqual(p["usage_remaining"], 0)

    def test_claude_session_line(self):
        rem, limited = _parse_claude("Current session: 0% used\nCurrent week (all models): 69% used")
        self.assertFalse(limited)
        rem100, lim100 = _parse_claude("Current session: 100% used")
        self.assertTrue(lim100)

    def test_claude_100_refuses_without_spawn(self):
        def stub(_to):
            return {"usage_remaining": {"session_pct": 100}, "limited": True, "raw": "session 100%"}
        spawned = {"n": 0}
        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "to": "claude", "session_id": "should-not", "model": None, "usage_remaining": None, "body": "nope"}
        card = send_one(self.root, "claude", "hi", runner=runner, probe_fn=stub)
        self.assertFalse(card["ok"])
        self.assertTrue(card.get("refused"))
        self.assertIsNone(card["session_id"])
        self.assertEqual(spawned["n"], 0)
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(rows[-1]["kind"], "refuse")

    def test_codex_out_of_credits_refuses(self):
        def stub(_to):
            return {"usage_remaining": None, "limited": True, "raw": "Your workspace is out of credits."}
        spawned = {"n": 0}
        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "session_id": "nope", "to": "codex", "model": None, "usage_remaining": None, "body": "nope"}
        card = send_one(self.root, "codex", "hi", runner=runner, probe_fn=stub)
        self.assertFalse(card["ok"])
        self.assertTrue(card.get("refused"))
        self.assertEqual(spawned["n"], 0)

    def test_codex_probe_timeout_refuses(self):
        def stub(_to):
            return {"usage_remaining": None, "limited": True, "raw": "probe timeout", "exit_code": 124}
        spawned = {"n": 0}
        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "session_id": "nope", "to": "codex", "model": None, "usage_remaining": None, "body": "nope"}
        card = send_one(self.root, "codex", "hi", runner=runner, probe_fn=stub)
        self.assertTrue(card.get("refused"))
        self.assertEqual(spawned["n"], 0)

    def test_invented_zero_is_not_remaining(self):
        p = probe("agy")
        self.assertIsNone(p["usage_remaining"])
        self.assertNotEqual(p["usage_remaining"], 0)

if __name__ == "__main__":
    unittest.main()
