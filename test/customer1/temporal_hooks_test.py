import json, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.layer import feed_since, hook
from convoy.synapse import send_one
from convoy.cli import main

class TemporalHooks(unittest.TestCase):
    def test_hook_stamps_and_since_windows(self):
        root = Path(tempfile.mkdtemp())
        early = hook(root, "note", "old", instance_id="i-old")
        later = hook(root, "synapse", "new synapse", instance_id="i-new")
        self.assertIn("ts", later)
        self.assertEqual(later["kind"], "synapse")
        self.assertEqual(later["instance_id"], "i-new")
        self.assertEqual(later["summary"], "new synapse")
        window = feed_since(root, later["ts"])
        ids = [r["instance_id"] for r in window]
        self.assertIn("i-new", ids)
        # CLI
        rc = main(["--root", str(root), "hook", "ping", "cli stamp", "--instance-id", "i-cli"])
        self.assertEqual(rc, 0)
        rc = main(["--root", str(root), "feed", "--since", early["ts"]])
        self.assertEqual(rc, 0)

    def test_send_stamps_feed(self):
        root = Path(tempfile.mkdtemp())
        (root / ".ola").mkdir()
        (root / ".ola" / "brief.md").write_text("b")
        card = send_one(root, "grok", "T1", label="p1")
        rows = feed_since(root, "1970-01-01T00:00:00.000000Z")
        self.assertTrue(rows)
        self.assertEqual(rows[-1]["kind"], "synapse")
        self.assertEqual(rows[-1]["instance_id"], card["session_id"])
        dry = send_one(root, "grok", "ping", dry_run=True)
        self.assertIsNone(dry["session_id"])
        after = feed_since(root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(len(after), len(rows))

    def test_feed_reads_utf8_bom(self):
        root = Path(tempfile.mkdtemp())
        hook(root, "synapse", "bom synapse", instance_id="i-bom")
        path = root / ".convoy" / "feed.jsonl"
        raw = path.read_bytes()
        path.write_bytes(b"\xef\xbb\xbf" + raw)
        rows = feed_since(root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["instance_id"], "i-bom")
        rc = main(["--root", str(root), "feed", "--since", "1970-01-01T00:00:00.000000Z"])
        self.assertEqual(rc, 0)

if __name__ == "__main__":
    unittest.main()
