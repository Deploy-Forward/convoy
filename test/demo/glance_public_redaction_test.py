"""A vendor resume id is a token, and glance put it on the public wire.

Found by the vision readers 2026-09-04 and reproduced: `glance {thread: X}` on
an UNGATED process echoed seat.resume verbatim (glance.py:218-220). Two locked
contracts collide here. SPEC.md:56 makes `resume` chip front matter on the
glance by-thread card (the conductor's render contract); graph.py:16-17 says
tokens never leave seats.jsonl and a chair reports only resume.available +
resume.for. The write gate is the arbiter, so both stay true:

- gate CLOSED (public wire): every seat row carries resume as
  {"available": bool, "for": harness} and never the id. Same shape graph uses.
- gate OPEN (conductor-local loopback): the full id, as SPEC.md:56 renders it.

This is a wire-layer redaction in mcp_http, not a change to build_glance, so
the CLI and in-process callers (which are local by construction) are unchanged.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.mcp_http import make_server

TOKEN = "VENDOR-SESSION-UUID-SECRET-01a0699f"


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _payload(resp):
    result = resp["result"]
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


class GlancePublicRedaction(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.root)
        bind(self.root, "leak")
        seat(self.root, "claude", "c-leak", worktree=str(Path(tempfile.mkdtemp())), resume=TOKEN)
        seat(self.root, "grok", "g-leak", worktree=str(Path(tempfile.mkdtemp())))   # no resume at all
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        # glance runs a live usage probe per harness (claude -p /usage, codex
        # exec /status). On this machine the codex probe hangs to its 15s
        # timeout, which is longer than the RPC client waits, so the first
        # draft of this test failed on TimeoutError rather than on the
        # assertion. Patch what glance_test patches: a null probe and a fake
        # which, so present=True and the test measures redaction only.
        for target, kw in (("convoy.glance.probe", {"return_value": {"usage_remaining": None, "limited": False, "raw": None}}),
                           ("convoy.glance.shutil.which", {"return_value": "/fake/bin"})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _glance(self, **args):
        return _payload(_rpc(self.mcp, "tools/call", {"name": "glance", "arguments": args}))

    def _rows(self, card):
        by_thread = card.get("by_thread") or card
        return by_thread.get("seats") or []

    def test_public_glance_never_carries_the_resume_id(self):
        for args in ({"thread": "leak"}, {"convoy_id": self.cid}, {"thread": "leak", "convoy_id": self.cid}):
            card = self._glance(**args)
            self.assertNotIn(TOKEN, json.dumps(card), args)
            rows = {r["session_id"]: r for r in self._rows(card)}
            self.assertEqual(set(rows), {"c-leak", "g-leak"})
            # The chair WITH a token reports that one exists and for which
            # harness - enough for a chip to say "resumable" - never the id.
            self.assertEqual(rows["c-leak"]["resume"], {"available": True, "for": "claude"})
            # The chair WITHOUT one says so honestly rather than omitting the key
            # (omission would be indistinguishable from redaction).
            self.assertEqual(rows["g-leak"]["resume"], {"available": False, "for": "grok"})

    def test_gated_glance_keeps_the_conductor_chip_contract(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        card = self._glance(thread="leak")
        rows = {r["session_id"]: r for r in self._rows(card)}
        self.assertEqual(rows["c-leak"]["resume"], TOKEN)          # SPEC.md:56, unchanged behind the gate
        self.assertNotIn("resume", rows["g-leak"])                 # unknown stays omitted, never "unknown"

    def test_in_process_build_glance_is_unchanged(self):
        # Local callers (CLI, tests) are not the public wire; the spec contract
        # is untouched there. Only the RPC layer redacts.
        from convoy.glance import build_glance
        card = build_glance(self.root, thread="leak")
        rows = {r["session_id"]: r for r in self._rows(card)}
        self.assertEqual(rows["c-leak"]["resume"], TOKEN)


if __name__ == "__main__":
    unittest.main()
