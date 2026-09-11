"""The conductor contract (Marco 2026-09-11, step 2 of the grok-bot rebase).

Seats get an AGENTS block, skills, hooks and a boot prompt; the conductor got
nothing and drifted (handoffs under .ola/, typed into panes, polled the feed).
The package now ships conductor.md, copies it under <root>/.convoy/, exposes it
through context / glance / roster / MCP initialize, and gives the conductor
`replies`: its own mail, read by cursor or by token, without polling the feed.
Tests written before the code."""
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from convoy.convoy import bind, ensure_id, seat
from convoy.layer import conductor_stamp, feed_since, hook, neuron_note

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


class ContractShipsAndCopies(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "cc")

    def test_packaged_contract_exists_and_carries_the_load_bearing_rules(self):
        from convoy.conductor import contract_text, contract_sha, CONTRACT_PATH
        text = contract_text()
        self.assertTrue(CONTRACT_PATH.is_file())
        self.assertEqual(contract_sha(), hashlib.sha256(text.encode("utf-8")).hexdigest())
        for rule in (".convoy/", ".ola/", "never type into a pane", "hook note", "--to grok-bot", "replies", "token",
                     "delivered", "Marco 2026-09-10", "not built yet"):
            self.assertIn(rule, text, rule)
        self.assertNotIn("\U0001f600", text)  # no emoji anywhere in a contract

    def test_copy_lands_under_convoy_and_refreshes_only_on_change(self):
        from convoy import conductor
        r1 = conductor.ensure_contract_copy(self.root)
        dest = self.root / ".convoy" / "conductor.md"
        self.assertTrue(r1["written"]); self.assertEqual(Path(r1["path"]), dest)
        self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(), conductor.contract_sha())
        m1 = dest.stat().st_mtime_ns
        r2 = conductor.ensure_contract_copy(self.root)
        self.assertFalse(r2["written"]); self.assertEqual(dest.stat().st_mtime_ns, m1, "identical text never rewrites")
        with mock.patch.object(conductor, "contract_text", return_value="# changed\n"):
            r3 = conductor.ensure_contract_copy(self.root)
        self.assertTrue(r3["written"]); self.assertEqual(dest.read_text(encoding="utf-8"), "# changed\n")
        self.assertFalse((self.root / ".ola").exists())

    def test_context_glance_roster_and_initialize_expose_the_contract(self):
        from convoy import conductor
        from convoy.context import pack
        from convoy.glance import build_glance
        from convoy import mcp_http
        conductor.ensure_contract_copy(self.root)
        c = pack(self.root)
        self.assertEqual(Path(c["canonical"]["contract"]), self.root / ".convoy" / "conductor.md")
        self.assertEqual(c["contract_sha"], conductor.contract_sha())
        g = build_glance(self.root, probe_fn=lambda h: dict(NULL_PROBE), which_fn=lambda n: None)
        self.assertEqual(g["conductor"]["contract"]["sha"], conductor.contract_sha())
        self.assertEqual(Path(g["conductor"]["contract"]["path"]), self.root / ".convoy" / "conductor.md")
        with mock.patch.object(mcp_http, "probe", lambda h: dict(NULL_PROBE)):
            ro = mcp_http.build_roster(self.root)
        self.assertEqual(ro["conductor"]["contract"]["sha"], conductor.contract_sha())
        init = mcp_http.handle_rpc(self.root, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                               "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        ins = init["result"]["instructions"]
        self.assertIn("conductor", ins.lower()); self.assertIn(conductor.contract_sha()[:12], ins)
        self.assertIn(".convoy/conductor.md", ins)
        self.assertLess(len(ins), 2500, "initialize carries the load-bearing rules and the pointer, not the whole file")


class Replies(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "rp")
        seat(self.root, "claude", "opus-1", worktree=str(self.root))

    def test_replies_are_only_rows_addressed_to_the_conductor(self):
        from convoy.conductor import replies
        neuron_note(self.root, "for the conductor", instance_id="opus-1", to="grok-bot")
        neuron_note(self.root, "for a peer", instance_id="opus-1", to="luna-1")
        neuron_note(self.root, "Grok_Bot spelled oddly", instance_id="opus-1", to="Grok_Bot")
        conductor_stamp(self.root, "my own stamp")
        hook(self.root, "synapse", "send claude", instance_id="opus-1")
        r = replies(self.root, "grok-bot", since="1970-01-01T00:00:00.000000Z")
        self.assertEqual([x["summary"] for x in r["rows"]], ["for the conductor", "Grok_Bot spelled oddly"])
        self.assertEqual(r["cursor"], r["rows"][-1]["ts"])
        again = replies(self.root, "grok-bot", since=r["cursor"])
        self.assertEqual(again["rows"], []); self.assertEqual(again["cursor"], r["cursor"], "an empty read holds the cursor")

    def test_replies_by_token_is_empty_until_the_chair_cites_it(self):
        from convoy.conductor import replies
        tok = "ab12cd34ef56"
        self.assertEqual(replies(self.root, "grok-bot", token=tok)["rows"], [])
        neuron_note(self.root, "ack " + tok + " done", instance_id="opus-1", to="grok-bot")
        neuron_note(self.root, "unrelated", instance_id="opus-1", to="grok-bot")
        r = replies(self.root, "grok-bot", token=tok)
        self.assertEqual([x["summary"] for x in r["rows"]], ["ack " + tok + " done"])
        self.assertTrue(r["delivered"])

    def test_replies_wait_returns_on_the_first_landing_row(self):
        from convoy.conductor import replies
        since = "1970-01-01T00:00:00.000000Z"
        out: dict = {}
        def worker():
            out["r"] = replies(self.root, "grok-bot", since=since, wait=20.0, poll_s=0.1)
        t = threading.Thread(target=worker); t.start()
        time.sleep(0.5)
        neuron_note(self.root, "late reply", instance_id="opus-1", to="grok-bot")
        t.join(10)
        self.assertFalse(t.is_alive()); self.assertEqual([x["summary"] for x in out["r"]["rows"]], ["late reply"])
        self.assertLess(out["r"]["waited_s"], 8)
        empty = replies(self.root, "grok-bot", since=out["r"]["cursor"], wait=0.3, poll_s=0.1)
        self.assertEqual(empty["rows"], []); self.assertGreaterEqual(empty["waited_s"], 0.3)

    def test_replies_tool_is_public_read_and_wait_is_gated(self):
        from convoy import mcp_http
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""}):
            listed = mcp_http.handle_rpc(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            names = {t["name"]: t for t in listed["result"]["tools"]}
            self.assertIn("replies", names)
            self.assertTrue(names["replies"]["annotations"]["readOnlyHint"])
            neuron_note(self.root, "hi", instance_id="opus-1", to="grok-bot")
            ok = mcp_http.handle_rpc(self.root, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                  "params": {"name": "replies", "arguments": {"since": "1970-01-01T00:00:00.000000Z"}}})
            body = json.loads(ok["result"]["content"][0]["text"])
            self.assertEqual([x["summary"] for x in body["rows"]], ["hi"])
            self.assertNotIn("token", json.dumps(body["rows"]), "public reads never carry a seat token field")
            gated = mcp_http.handle_rpc(self.root, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                     "params": {"name": "replies", "arguments": {"since": "1970-01-01T00:00:00.000000Z", "wait": 5}}})
            gb = json.loads(gated["result"]["content"][0]["text"])
            self.assertFalse(gb["ok"]); self.assertIn("write gate", gb["error"])

    def test_agents_block_tells_seats_how_to_answer_the_conductor(self):
        from convoy.identity import install_neuron_identity
        wt = Path(tempfile.mkdtemp())
        install_neuron_identity(wt)
        text = (wt / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("--to grok-bot", text); self.assertIn("token", text)
        self.assertIn("conductor", text.lower())
