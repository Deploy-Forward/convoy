"""Two findings from the codex/grok sleuthing (2026-09-02 23:39Z):

1. A send card must say what happened to the message. `delivery` is one of
   recorded (feed row only, nothing reached a neuron), executed (a fresh
   headless vendor session ran the body — not the open pane), refused, queued
   (named live seat inbox). Only an ack row authored by the target proves
   delivered; the card never claims it.
2. Convoy verbs must be eligible via tool calls, so neurons attached over MCP
   can summon them: graph / threads / resume join the tool list read-only;
   resume --go stays behind the same gate as the bus writers.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.mcp_http import TOOLS, _WRITE_TOOLS, call_tool
from convoy.synapse import fake_runner, send_one


class DeliveryLabel(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")

    def test_fake_send_is_recorded_not_delivered(self):
        card = send_one(self.root, "grok", "hi", runner=fake_runner)
        self.assertTrue(card["ok"])
        self.assertEqual(card["delivery"], "recorded")
        self.assertFalse(card["delivered"])

    def test_dry_run_is_recorded(self):
        card = send_one(self.root, "grok", "hi", runner=fake_runner, dry_run=True)
        self.assertEqual(card["delivery"], "recorded")
        self.assertFalse(card["delivered"])

    def test_live_named_seat_is_queued_not_stolen(self):
        seat(self.root, "grok", "g-t1", resume="grok-uuid")
        card = send_one(self.root, "grok", "hi", runner=fake_runner, instance_id="g-t1", allow_interactive_resume=False)
        self.assertTrue(card["ok"])
        self.assertEqual(card["delivery"], "queued")
        self.assertFalse(card["delivered"])
        self.assertFalse(card.get("resume_stolen"))

    def test_live_unknown_resume_is_refused(self):
        card = send_one(self.root, "grok", "hi", runner=fake_runner, instance_id="nobody", allow_interactive_resume=False)
        self.assertTrue(card["refused"])
        self.assertEqual(card["delivery"], "refused")
        self.assertFalse(card["delivered"])

    def test_native_style_runner_is_executed_never_delivered(self):
        def runner(to, body, **_k):
            return {"ok": True, "to": to, "session_id": "fresh", "model": None, "usage_remaining": None, "body": "reply"}
        card = send_one(self.root, "grok", "hi", runner=runner)
        self.assertEqual(card["delivery"], "executed")
        self.assertFalse(card["delivered"])


class ToolEligibility(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="codex-uuid")
        os.environ.pop("CONVOY_MCP_WRITE_TOOLS", None)

    def test_graph_threads_resume_are_listed_tools(self):
        names = {t["name"] for t in TOOLS}
        self.assertTrue({"graph", "threads", "resume"} <= names)
        self.assertNotIn("graph", _WRITE_TOOLS)
        self.assertNotIn("threads", _WRITE_TOOLS)

    def test_graph_tool_and_neuron(self):
        g = call_tool(self.root, "graph", {})
        self.assertEqual(g["graph_version"], 1)
        n = call_tool(self.root, "graph", {"neuron": "c-t1"})
        self.assertEqual(n["chair"]["id"], "chair:c-t1")
        bad = call_tool(self.root, "graph", {"neuron": "nobody"})
        self.assertFalse(bad["ok"])

    def test_threads_tool(self):
        t = call_tool(self.root, "threads", {})
        self.assertTrue(t["ok"])
        self.assertIsInstance(t["threads"], list)

    def test_resume_tool_is_dry_and_go_is_gated(self):
        # The vendor id in argv reads behind the gate (public_wire_redaction_test
        # owns the ungated shape); the go refusal below stays ungated.
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"}):
            dry = call_tool(self.root, "resume", {"neuron": "c-t1"})
        self.assertTrue(dry["ok"])
        self.assertFalse(dry["spawned"])
        self.assertEqual(dry["argv"][1:], ["resume", "codex-uuid"])
        go = call_tool(self.root, "resume", {"neuron": "c-t1", "go": True})
        self.assertFalse(go["ok"])
        self.assertIn("gate", go["error"])


if __name__ == "__main__":
    unittest.main()
