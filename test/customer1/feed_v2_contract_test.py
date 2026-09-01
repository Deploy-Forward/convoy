import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import attach, bind, ensure_id
from convoy.layer import SCHEMA_VERSION, conductor_stamp, feed_since, hook
from convoy.mcp_http import TOOLS, call_tool
from convoy.synapse import send_one


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class FeedV2Contract(unittest.TestCase):
    """One MCP endpoint; what is versioned is the feed contract: additive kinds
    (conductor stamps, synapse, refuse+ask) under schema_version 2. Compact
    stamps only — never the conductor bubble history, never a sibling session."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_schema_version_is_two(self):
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_conductor_stamp_compact_row_front_matter_shape(self):
        row = conductor_stamp(
            self.root,
            "ship feed contract v2: conductor stamps + refuse/ask on the bus",
            agent="Orchestrator",
            effort="x-high",
            instance_id="a487bca8-4a8e-41b8-81b0-5a1182368cc2",
            transcript="/home/box/agent-data/agent-transcripts/a487bca8-4a8e-41b8-81b0-5a1182368cc2/a487bca8-4a8e-41b8-81b0-5a1182368cc2.jsonl",
            usage_remaining="Current session: 7% used",
        )
        self.assertEqual(row["kind"], "conductor")
        self.assertEqual(row["from"], "grok-bot")
        self.assertEqual(row["agent"], "Orchestrator")
        self.assertIsNone(row["model"])
        self.assertEqual(row["effort"], "x-high")
        self.assertEqual(row["instance_id"], "a487bca8-4a8e-41b8-81b0-5a1182368cc2")
        self.assertTrue(str(row["transcript"]).endswith(".jsonl"))
        # blob strings clamp to null — never a promoted meter
        self.assertIsNone(row["usage_remaining"])
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(rows[-1]["kind"], "conductor")
        self.assertEqual(rows[-1]["summary"], row["summary"])

    def test_conductor_stamp_is_one_compact_line_never_a_transcript(self):
        big = "line one\nline two\r\n" + ("x" * 5000)
        row = conductor_stamp(self.root, big)
        self.assertNotIn("\n", row["summary"])
        self.assertNotIn("\r", row["summary"])
        self.assertLessEqual(len(row["summary"]), 500)
        self.assertIs(row["truncated"], True)
        small = conductor_stamp(self.root, "small decision")
        self.assertNotIn("truncated", small)
        with self.assertRaises(ValueError):
            conductor_stamp(self.root, "   ")

    def test_mcp_stamp_tool_writes_conductor_row(self):
        names = [t["name"] for t in TOOLS]
        self.assertIn("stamp", names)
        desc = next(t for t in TOOLS if t["name"] == "stamp")["description"].lower()
        self.assertIn("conductor", desc)
        self.assertIn("compact", desc)
        self.assertNotIn("transcript mirror", desc.replace("not a transcript mirror", ""))
        card = call_tool(self.root, "stamp", {"summary": "decision: open synapse to claude", "agent": "Orchestrator"})
        self.assertTrue(card["ok"])
        self.assertEqual(card["kind"], "conductor")
        payload = call_tool(self.root, "feed", {"since": "1970-01-01T00:00:00.000000Z"})
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["events"][-1]["kind"], "conductor")

    def test_mcp_stamp_refuses_empty_summary(self):
        card = call_tool(self.root, "stamp", {"summary": "  "})
        self.assertFalse(card["ok"])
        self.assertIn("summary", str(card.get("error") or "").lower())

    def test_cli_stamp_and_feed_envelope(self):
        rc, row = _run_cli(self.root, "stamp", "conductor said: pull the thread", "--agent", "Orchestrator")
        self.assertEqual(rc, 0)
        self.assertEqual(row["kind"], "conductor")
        rc, envelope = _run_cli(self.root, "feed", "--since", "1970-01-01T00:00:00.000000Z")
        self.assertEqual(rc, 0)
        self.assertEqual(envelope["schema_version"], SCHEMA_VERSION)
        kinds = [e["kind"] for e in envelope["events"]]
        self.assertIn("conductor", kinds)

    def test_limited_refuse_feed_row_carries_full_ask(self):
        def probe(_to):
            return {"usage_remaining": None, "limited": True, "raw": "session 100%"}

        card = send_one(self.root, "claude", "hi", probe_fn=probe)
        self.assertTrue(card.get("refused"))
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        refuse = rows[-1]
        self.assertEqual(refuse["kind"], "refuse")
        ask = refuse.get("ask")
        self.assertIsInstance(ask, dict)
        self.assertEqual(ask["action"], "bring_up")
        self.assertIn("handoff", ask)
        self.assertIn("ask the user", ask["text"].lower())

    def test_attach_card_carries_schema_version(self):
        ensure_id(self.root)
        bind(self.root, "v2-thread")
        card = attach(self.root)
        self.assertTrue(card["ok"])
        self.assertEqual(card["schema_version"], SCHEMA_VERSION)

    def test_v1_rows_and_unknown_kinds_still_flow(self):
        hook(self.root, "note", "v1 row, no extras")
        hook(self.root, "weird-future-kind", "additive means skip, not crash")
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        kinds = [r["kind"] for r in rows]
        self.assertIn("note", kinds)
        self.assertIn("weird-future-kind", kinds)


if __name__ == "__main__":
    unittest.main()
