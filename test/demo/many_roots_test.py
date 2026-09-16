"""Move 3 of the productize amendment (Marco 2026-09-14): the origin serves every
thread on the machine. Every tool call names its thread; nothing is pointed at
startup. Binding a root at launch stays possible as a pin, not a requirement.
"You know what thread you are writing to, and a launched grok-bot can identify
this." Tests written before the code."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from convoy.convoy import bind, ensure_id, read_id, seat
from convoy.index import record, set_hidden


def _rpc(url, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _payload(resp):
    return resp["result"]["structuredContent"]


def _feed(root):
    p = Path(root) / ".convoy" / "feed.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


class _Threads(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home), "CONVOY_MCP_WRITE_TOOLS": "1"}); p.start(); self.addCleanup(p.stop)
        self.alpha = Path(tempfile.mkdtemp()); ensure_id(self.alpha); bind(self.alpha, "alpha")
        seat(self.alpha, "claude", "c-alpha", worktree=str(self.alpha)); record(self.alpha, read_id(self.alpha), "alpha")
        self.beta = Path(tempfile.mkdtemp()); ensure_id(self.beta); bind(self.beta, "beta")
        seat(self.beta, "codex", "x-beta", worktree=str(self.beta)); record(self.beta, read_id(self.beta), "beta")
        self.gamma = Path(tempfile.mkdtemp()); ensure_id(self.gamma); bind(self.gamma, "gamma")
        record(self.gamma, read_id(self.gamma), "gamma"); set_hidden(read_id(self.gamma), True)

    def _serve(self, root):
        from convoy.mcp_http import make_server
        httpd = make_server(root, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return "http://127.0.0.1:%d/mcp" % httpd.server_address[1]


class UnboundOriginServesEveryThread(_Threads):
    def test_threads_tool_lists_what_the_machine_knows_and_hides_the_hidden(self):
        url = self._serve(None)
        card = _payload(_rpc(url, "tools/call", {"name": "threads"}))
        self.assertTrue(card["ok"]); self.assertIsNone(card["bound"])
        rows = {r["thread"]: r for r in card["threads"] if r.get("present") and not r.get("hidden")}
        self.assertIn("alpha", rows); self.assertIn("beta", rows); self.assertNotIn("gamma", rows)
        self.assertEqual(Path(rows["beta"]["root"]), self.beta.resolve()); self.assertEqual(rows["beta"]["convoy_id"], read_id(self.beta))

    def test_a_call_without_a_thread_is_refused_with_the_choices_and_writes_nothing(self):
        url = self._serve(None)
        r = _rpc(url, "tools/call", {"name": "stamp", "arguments": {"summary": "where"}})
        self.assertTrue(r["result"]["isError"])
        card = _payload(r)
        self.assertIn("thread", card["error"]); self.assertIn("alpha", json.dumps(card["threads"]))
        self.assertEqual(_feed(self.alpha) + _feed(self.beta), [])

    def test_naming_the_thread_routes_the_write_to_that_record(self):
        url = self._serve(None)
        r = _rpc(url, "tools/call", {"name": "stamp", "arguments": {"thread": "beta", "summary": "to beta"}})
        self.assertFalse(r["result"]["isError"], r)
        self.assertEqual([x["summary"] for x in _feed(self.beta) if x["kind"] == "conductor"], ["to beta"])
        self.assertEqual(_feed(self.alpha), [])
        r2 = _rpc(url, "tools/call", {"name": "stamp", "arguments": {"convoy_id": read_id(self.alpha), "summary": "by id"}})
        self.assertFalse(r2["result"]["isError"], r2)
        self.assertEqual([x["summary"] for x in _feed(self.alpha) if x["kind"] == "conductor"], ["by id"])

    def test_every_card_says_which_thread_it_touched(self):
        url = self._serve(None)
        card = _payload(_rpc(url, "tools/call", {"name": "roster", "arguments": {"thread": "alpha"}}))
        self.assertEqual(card["thread"], "alpha"); self.assertEqual(Path(card["root"]), self.alpha.resolve())
        card2 = _payload(_rpc(url, "tools/call", {"name": "replies", "arguments": {"thread": "beta"}}))
        self.assertEqual(card2["thread"], "beta")

    def test_unknown_and_hidden_threads_are_refused_by_name(self):
        url = self._serve(None)
        for name in ("nope", "gamma"):
            r = _rpc(url, "tools/call", {"name": "feed", "arguments": {"thread": name}})
            self.assertTrue(r["result"]["isError"], name)
            self.assertIn(name, _payload(r)["error"])

    def test_every_tool_schema_carries_thread_and_convoy_id(self):
        from convoy.mcp_http import TOOLS
        for t in TOOLS:
            props = t["inputSchema"]["properties"]
            self.assertIn("thread", props, t["name"]); self.assertIn("convoy_id", props, t["name"])

    def test_initialize_and_contract_tell_the_conductor_to_name_the_thread(self):
        url = self._serve(None)
        init = _rpc(url, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
        self.assertIn("thread", init.lower())
        from convoy.conductor import contract_text
        text = contract_text()
        self.assertIn("`threads`", text)
        self.assertNotIn("bound to one root", text)


class BoundOriginIsAPin(_Threads):
    def test_a_bound_origin_defaults_to_its_root_and_still_honours_a_named_thread(self):
        url = self._serve(self.alpha)
        card = _payload(_rpc(url, "tools/call", {"name": "threads"}))
        self.assertEqual(card["bound"], "alpha")
        r = _rpc(url, "tools/call", {"name": "stamp", "arguments": {"summary": "default"}})
        self.assertFalse(r["result"]["isError"], r)
        self.assertEqual([x["summary"] for x in _feed(self.alpha) if x["kind"] == "conductor"], ["default"])
        r2 = _rpc(url, "tools/call", {"name": "stamp", "arguments": {"thread": "beta", "summary": "elsewhere"}})
        self.assertFalse(r2["result"]["isError"], r2)
        self.assertEqual([x["summary"] for x in _feed(self.beta) if x["kind"] == "conductor"], ["elsewhere"])


class InstallServesAllThreadsByDefault(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)

    def test_default_plan_starts_an_unbound_origin_from_any_directory(self):
        from convoy.local_install import install_local
        try:
            from test.demo.local_install_test import FakeRunner
        except ModuleNotFoundError:  # the repo runner discovers test/demo as top level
            from local_install_test import FakeRunner
        bare = Path(tempfile.mkdtemp())
        card = install_local(bare, runner=FakeRunner(), windows=True)
        self.assertTrue(card["ok"], card)
        origin = card["plan"][0]
        self.assertNotIn("--root", origin["arguments"], "nothing is pointed: the origin serves every thread")
        self.assertEqual(origin["serves"], "all threads")

    def test_bound_pin_still_requires_a_thread(self):
        from convoy.local_install import install_local
        try:
            from test.demo.local_install_test import FakeRunner
        except ModuleNotFoundError:  # the repo runner discovers test/demo as top level
            from local_install_test import FakeRunner
        bare = Path(tempfile.mkdtemp())
        card = install_local(bare, runner=FakeRunner(), windows=True, bound=True)
        self.assertFalse(card["ok"]); self.assertIn("not a Convoy thread", card["error"])
        t = Path(tempfile.mkdtemp()); ensure_id(t); bind(t, "pin")
        card2 = install_local(t, runner=FakeRunner(), windows=True, bound=True)
        self.assertTrue(card2["ok"]); self.assertIn("--root", card2["plan"][0]["arguments"]); self.assertEqual(card2["plan"][0]["serves"], "pin")


if __name__ == "__main__":
    unittest.main()


class OriginSurvivesWithoutStdio(unittest.TestCase):
    """2026-09-15: the supervised origin moved to pythonw (no console) in #101 and
    every request then died with EOF: the request-line logger wrote to
    sys.stderr, which is None under a windowless interpreter, so the handler
    raised before sending a response and cloudflared reported the origin
    unreachable (public 502 overnight). The origin must answer with no stdio."""
    def test_a_request_is_answered_when_stderr_and_stdout_are_none(self):
        import sys
        from convoy.mcp_http import make_server
        httpd = make_server(None, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        url = "http://127.0.0.1:%d/mcp" % httpd.server_address[1]
        with mock.patch.object(sys, "stderr", None), mock.patch.object(sys, "stdout", None):
            r = _rpc(url, "initialize", {"protocolVersion": "2025-06-18"})
        self.assertIn("serverInfo", r["result"])

    def test_serve_banner_and_request_log_go_to_a_file_when_there_is_no_console(self):
        import sys
        from convoy import mcp_http
        home = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(home)}), mock.patch.object(sys, "stderr", None), mock.patch.object(sys, "stdout", None):
            mcp_http._log_line("hello from a windowless origin")
        log = home / "origin.log"
        self.assertTrue(log.is_file()); self.assertIn("hello from a windowless origin", log.read_text(encoding="utf-8"))
