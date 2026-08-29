import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.synapse import send_many

def runner(to, body, **_k):
    return {"ok": True, "to": to, "session_id": "sess-" + to, "model": None, "usage_remaining": None, "body": "ACK " + to}

class ParallelAgents(unittest.TestCase):
    def test_two_synapses_own_session_ids(self):
        root = Path(tempfile.mkdtemp())
        cards = send_many(root, ["grok", "claude"], "ping C1", runner=runner)
        self.assertEqual(len(cards), 2)
        ids = {c["session_id"] for c in cards}
        self.assertEqual(ids, {"sess-grok", "sess-claude"})
        self.assertTrue(all(c["ok"] for c in cards))
        rc = main(["--root", str(root), "send", "--to", "grok", "--to", "claude", "ping C1"])
        self.assertEqual(rc, 0)

if __name__ == "__main__":
    unittest.main()
