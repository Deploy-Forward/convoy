"""Anonymous callers on the public edge get the product surface, nothing of the record.

Read back live 2026-09-17 through convoy.bot with no Authorization header:
`threads` returned 99 rows with every thread's filesystem root under the
operator's home directory and thread names that are client and project names;
`card` and `roster` returned checkout, worktree and contract paths. Nothing in
those rows is a credential; all of it is a map of one person's machine, and
with the legacy write flag set the same anonymous caller could write.

Rule: identity is the arbiter on the public edge. A request that arrived
through a proxy (Cf-Connecting-Ip / X-Forwarded-For / Forwarded / X-Real-Ip)
or from a non-loopback peer, carrying no bearer, is anonymous-public. It may
call only the product surface (`card`, `choices`, `install` dry, `threads` as a
count), every card it receives has filesystem paths scrubbed, and `tools/list`
shows it exactly that surface. The legacy flag never opens anything to it. A
loopback caller with no proxy header is local and unchanged: the record is
already theirs on disk. A bearer holder through the edge is unchanged.
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

from convoy import bearer as _bearer
from convoy.convoy import bind, ensure_id, seat
from convoy.layer import hook
from convoy.mcp_http import TOOLS, make_server

EDGE = {"X-Forwarded-For": "203.0.113.9"}          # TEST-NET-3: a proxied public caller
PRODUCT_SURFACE = {"card", "choices", "install", "threads"}
SECRET_NOTE = "note-body-that-must-not-leak-7f3a"
NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


def _rpc(url, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _payload(resp):
    result = resp["result"]
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def _strings(obj):
    """Every string value in a parsed card, so path checks see real backslashes."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


class AnonymousPublicSurface(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home), "CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        self._probe = mock.patch("convoy.mcp_http.probe", lambda _h: dict(NULL_PROBE))
        self._probe.start()
        self.addCleanup(self._probe.stop)
        self.root = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.root)
        bind(self.root, "leaky")
        self.worktree = Path(tempfile.mkdtemp())
        seat(self.root, "claude", "c-leaky", worktree=str(self.worktree))
        hook(self.root, "note", SECRET_NOTE, instance_id="c-leaky", author="c-leaky")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)

    def _bearer_headers(self):
        card = _bearer.mint(label="test")
        return {**EDGE, "Authorization": "Bearer " + card["bearer"]}

    def _assert_no_machine_paths(self, resp, label):
        temp = str(Path(tempfile.gettempdir()).resolve()).lower()
        for s in _strings(_payload(resp)):
            low = s.lower()
            self.assertNotIn(str(self.root).lower(), low, label + ": " + s[:80])
            self.assertNotIn(str(self.worktree).lower(), low, label + ": " + s[:80])
            self.assertNotIn(temp, low, label + ": " + s[:80])

    # --- what an anonymous public caller sees ---------------------------------

    def test_anonymous_public_tools_list_is_the_product_surface(self):
        names = {t["name"] for t in _rpc(self.mcp, "tools/list", headers=EDGE)["result"]["tools"]}
        self.assertEqual(names, PRODUCT_SURFACE)

    def test_anonymous_public_threads_is_a_count_without_names_or_roots(self):
        resp = _rpc(self.mcp, "tools/call", {"name": "threads", "arguments": {}}, headers=EDGE)
        card = _payload(resp)
        self.assertIsInstance(card.get("count"), int)
        for key in ("threads", "index", "bound_root", "bound"):
            self.assertNotIn(key, card)
        blob = " ".join(_strings(card))
        self.assertNotIn("leaky", blob)
        self.assertNotIn(self.cid, blob)
        self._assert_no_machine_paths(resp, "threads")

    def test_anonymous_public_record_tools_are_refused_by_name(self):
        for name in ("feed", "panes", "neurons", "glance", "rail", "graph", "context", "provenance",
                     "replies", "terminals", "inbox", "repos", "resume", "roster", "await_seated"):
            args = {"thread": "leaky", "seat": "c-leaky", "since": "1970-01-01T00:00:00Z", "chairs": ["c-leaky"]}
            resp = _rpc(self.mcp, "tools/call", {"name": name, "arguments": args}, headers=EDGE)
            card = _payload(resp)
            self.assertIs(card.get("ok"), False, name)
            self.assertIn(name, card.get("error", ""), name)
            self.assertIn("conductor mint", card.get("error", ""), name)
            self.assertTrue(resp["result"]["isError"], name)
            self.assertNotIn(SECRET_NOTE, " ".join(_strings(card)), name)
            self._assert_no_machine_paths(resp, name)

    def test_anonymous_public_card_and_choices_carry_no_filesystem_path(self):
        for name in ("card", "choices"):
            resp = _rpc(self.mcp, "tools/call", {"name": name, "arguments": {"thread": "leaky"}}, headers=EDGE)
            self._assert_no_machine_paths(resp, name)

    def test_anonymous_public_install_never_runs_live(self):
        resp = _rpc(self.mcp, "tools/call", {"name": "install", "arguments": {"to": "grok", "dry_run": False, "opt_in": True}}, headers=EDGE)
        card = _payload(resp)
        self.assertIsNot(card.get("dry_run"), False)
        self.assertIsNot(card.get("ran"), True)

    def test_legacy_flag_does_not_open_the_record_to_the_public(self):
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"}):
            resp = _rpc(self.mcp, "tools/call", {"name": "feed", "arguments": {"thread": "leaky"}}, headers=EDGE)
            self.assertIs(_payload(resp).get("ok"), False)
            self.assertNotIn(SECRET_NOTE, " ".join(_strings(_payload(resp))))
            write = _rpc(self.mcp, "tools/call", {"name": "note", "arguments": {"thread": "leaky", "text": "anonymous write", "seat": "c-leaky"}}, headers=EDGE)
            self.assertTrue(write["result"]["isError"])
            names = {t["name"] for t in _rpc(self.mcp, "tools/list", headers=EDGE)["result"]["tools"]}
            self.assertEqual(names, PRODUCT_SURFACE)

    def test_public_request_is_a_proxy_header_or_a_non_loopback_peer(self):
        from convoy.mcp_http import _is_public_request
        self.assertTrue(_is_public_request("198.51.100.4", {}))
        self.assertTrue(_is_public_request("127.0.0.1", {"Cf-Connecting-Ip": "198.51.100.4"}))
        self.assertTrue(_is_public_request("127.0.0.1", {"X-Forwarded-For": "198.51.100.4"}))
        self.assertFalse(_is_public_request("127.0.0.1", {}))
        self.assertFalse(_is_public_request("::1", {}))
        self.assertTrue(_is_public_request("not-an-address", {}))

    # --- who is unchanged --------------------------------------------------------

    def test_bearer_holder_through_the_edge_gets_the_whole_record(self):
        headers = self._bearer_headers()
        card = _payload(_rpc(self.mcp, "tools/call", {"name": "threads", "arguments": {}}, headers=headers))
        roots = [str(t.get("root")).lower() for t in card.get("threads", [])]
        self.assertTrue(any(str(self.root).lower() in r for r in roots), roots[:3])
        feed = _payload(_rpc(self.mcp, "tools/call", {"name": "feed", "arguments": {"thread": "leaky", "since": "1970-01-01T00:00:00Z"}}, headers=headers))
        self.assertIn(SECRET_NOTE, " ".join(_strings(feed)))
        names = {t["name"] for t in _rpc(self.mcp, "tools/list", headers=headers)["result"]["tools"]}
        self.assertEqual(names, {t["name"] for t in TOOLS})

    def test_loopback_caller_without_proxy_header_is_local_and_unchanged(self):
        card = _payload(_rpc(self.mcp, "tools/call", {"name": "threads", "arguments": {}}))
        self.assertIn("threads", card)
        feed = _payload(_rpc(self.mcp, "tools/call", {"name": "feed", "arguments": {"thread": "leaky", "since": "1970-01-01T00:00:00Z"}}))
        self.assertIn(SECRET_NOTE, " ".join(_strings(feed)))


if __name__ == "__main__":
    unittest.main()
