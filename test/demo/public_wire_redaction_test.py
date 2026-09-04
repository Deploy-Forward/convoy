"""Two secrets, every public tool, zero echoes. The gate is the arbiter.

Adversarial review of 17a7c65 (2026-09-04) reproduced two PRE-EXISTING leaks
on the ungated wire (CONVOY_MCP_WRITE_TOOLS unset), both siblings of the glance
leak fixed in 3b18a8e:

1. The vendor resume id (seat.resume) rode verbatim in terminals.windows[].resume,
   bring_up/open dry windows[].resume + windows[].argv (`--resume <id>`),
   hide/minimize/background dry windows[].resume, and `resume go=false` .argv.
2. The inbox token minted by join/swap (the receiver's proof of receipt) rode in
   the kind=join feed row (feed.events[].token) and inside the boot prompt that
   bring_up/open dry return as the last argv element.

graph.py:16 says tokens never leave seats.jsonl; SPEC.md:56 makes the id chip
front matter for the conductor. Both stay true the way glance already settled
it: behind the gate (conductor-local loopback) the id and the argv are whole;
on the public wire a row carries {available, for} in their place, and feed
rows carry no token key (the inbox precedent, mcp_http.py:621).

The probe is the test: seed one seat WITH a vendor id, one joined chair WITH a
minted token, then call every read-only tool through make_server and assert
neither string appears anywhere in any response. In-process callers
(bring_up, terminals, hide_windows, resume_neuron) are local by construction
and are unchanged; only the RPC layer redacts.
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

from convoy.bringup import bring_up, terminals
from convoy.convoy import bind, ensure_id, seat
from convoy.lifecycle import join
from convoy.mcp_http import make_server

RESUME_ID = "LEAK-RESUME-4f1c0e9a7b2d"


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


class PublicWireRedaction(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.root)
        bind(self.root, "leak")
        seat(self.root, "claude", "c-leak", worktree=str(Path(tempfile.mkdtemp())), resume=RESUME_ID)
        seat(self.root, "grok", "g-leak", worktree=str(Path(tempfile.mkdtemp())))   # no vendor id at all
        # join mints the inbox token and writes it to the kind=join feed row
        # and into the seat's one-shot boot_prompt (lifecycle.py:65-72).
        self.join_token = join(self.root, "codex", session_id="x-leak",
                               worktree=str(Path(tempfile.mkdtemp())))["token"]
        self.assertTrue(self.join_token)
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        # Keep the probe about redaction: no vendor CLI probes (they hang past
        # the RPC timeout on this machine), no first-run writes into the real
        # home, no process-table scans (terminals / panes / neurons).
        null_probe = {"usage_remaining": None, "limited": False, "raw": None}
        for target, kw in (("convoy.glance.probe", {"return_value": null_probe}),
                           ("convoy.glance.shutil.which", {"return_value": "/fake/bin"}),
                           ("convoy.mcp_http.probe", {"return_value": null_probe}),
                           ("convoy.bringup.Path.home", {"return_value": Path(tempfile.mkdtemp())}),
                           ("convoy.bringup._iter_processes", {"return_value": []}),
                           ("convoy.panes.enumerate_processes", {"return_value": []})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _call(self, name, **args):
        return _payload(_rpc(self.mcp, "tools/call", {"name": name, "arguments": args}))

    # Every read-only tool a public process lists, with the arguments that
    # reach a seat row. send uses the fake runner (live unset): no spawn.
    PUBLIC_CALLS = (
        ("roster", {}),
        ("glance", {"thread": "leak"}),
        ("terminals", {}),
        ("terminals", {"thread": "leak"}),
        ("context", {}),
        ("context", {"instance_id": "c-leak"}),
        ("send", {"to": "claude", "body": "ping", "session_id": "c-leak"}),
        ("graph", {}),
        ("graph", {"neuron": "c-leak"}),
        ("graph", {"neuron": "x-leak"}),
        ("threads", {}),
        ("panes", {}),
        ("resume", {"neuron": "c-leak"}),
        ("resume", {"neuron": "x-leak"}),
        ("feed", {"since": "1970-01-01T00:00:00.000000Z"}),
        ("bring_up", {}),
        ("bring_up", {"dry_run": True}),
        ("open", {"dry_run": True}),
        ("hide", {"dry_run": True}),
        ("minimize", {"dry_run": True}),
        ("background", {"dry_run": True, "mode": "hide"}),
        ("install", {"to": "claude", "dry_run": True}),
        ("choices", {}),
        ("neurons", {}),
        ("inbox", {"seat": "c-leak"}),
        ("inbox", {"seat": "x-leak"}),
    )

    def test_no_public_tool_echoes_the_vendor_id_or_the_join_token(self):
        for name, args in self.PUBLIC_CALLS:
            blob = json.dumps(self._call(name, **args))
            self.assertNotIn(RESUME_ID, blob, (name, args))
            self.assertNotIn(self.join_token, blob, (name, args))

    def test_public_windows_carry_the_glance_shape_not_the_id(self):
        for name in ("bring_up", "open", "terminals", "hide", "minimize", "background"):
            card = self._call(name, dry_run=True) if name != "terminals" else self._call(name)
            rows = {w["to"]: w for w in card["windows"]}
            # the chair WITH a vendor id says one exists and for which harness
            self.assertEqual(rows["claude"]["resume"], {"available": True, "for": "claude"}, name)
            # the chair WITHOUT one says so, rather than omitting the key
            self.assertEqual(rows["grok"]["resume"], {"available": False, "for": "grok"}, name)
            # bring_up/open windows would exec argv that carries the id AND the
            # boot token; on the public wire the argv is a fact, not a payload
            if name in ("bring_up", "open"):
                self.assertEqual(rows["claude"]["argv"], {"available": True, "for": "claude"}, name)
                self.assertEqual(rows["codex"]["argv"], {"available": True, "for": "codex"}, name)
            else:
                self.assertNotIn("argv", rows["claude"], name)

    def test_public_resume_dry_read_says_argv_exists_not_what_it_is(self):
        card = self._call("resume", neuron="c-leak")
        self.assertTrue(card["ok"])
        self.assertFalse(card["spawned"])
        self.assertEqual(card["argv"], {"available": True, "for": "claude"})

    def test_public_feed_rows_carry_no_token_key(self):
        rows = self._call("feed", since="1970-01-01T00:00:00.000000Z")["events"]
        kinds = {r["kind"] for r in rows}
        self.assertIn("join", kinds)                       # the row is still visible
        self.assertFalse(any("token" in r for r in rows))  # its proof is not

    def test_gated_wire_keeps_the_conductor_contract(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        up = {w["to"]: w for w in self._call("bring_up", dry_run=True)["windows"]}
        self.assertEqual(up["claude"]["resume"], RESUME_ID)
        self.assertEqual(up["claude"]["argv"][-2:], ["--resume", RESUME_ID])
        self.assertIn(self.join_token, up["codex"]["argv"][-1])
        self.assertEqual(self._call("resume", neuron="c-leak")["argv"][-1], RESUME_ID)
        joined = [r for r in self._call("feed", since="1970-01-01T00:00:00.000000Z")["events"] if r["kind"] == "join"]
        self.assertEqual(joined[0]["token"], self.join_token)

    def test_in_process_callers_are_unchanged(self):
        # CLI and in-process readers are local by construction; only the RPC
        # layer redacts (the same line glance_public_redaction_test draws).
        up = {w["to"]: w for w in bring_up(self.root)["windows"]}
        self.assertEqual(up["claude"]["resume"], RESUME_ID)
        term = {w["to"]: w for w in terminals(self.root)["windows"]}
        self.assertEqual(term["claude"]["resume"], RESUME_ID)


if __name__ == "__main__":
    unittest.main()
