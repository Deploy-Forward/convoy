import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.convoy import bind, ensure_id, seat
from convoy.layer import hook
from convoy.mcp_http import HOME_LINE, make_server

def _rpc(url, method, params=None, rpc_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _tool_payload(resp):
    result = resp["result"]
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    if isinstance(result, dict) and result.get("content"):
        return json.loads(result["content"][0]["text"])
    return result


class PhaseMcpHttp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("brief-pointer")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())
        self.thread = "customer1"
        self.cid = ensure_id(self.root)
        bind(self.root, self.thread)
        self.g = seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok")
        self.c = seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="Fable 5")
        self.fake_home = Path(tempfile.mkdtemp())
        self._home_patcher = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home_patcher.start()
        self.addCleanup(self._home_patcher.stop)
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%s" % self.port
        self.mcp = self.base + "/mcp"
        self.thread_obj = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread_obj.start()

    def tearDown(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass

    def test_initialize_and_tools_list(self):
        init = _rpc(self.mcp, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "convoy")
        self.assertIn(init["result"]["protocolVersion"], ("2025-03-26", "2024-11-05"))
        listed = _rpc(self.mcp, "tools/list")
        names = [t["name"] for t in listed["result"]["tools"]]
        for want in ("roster", "glance", "terminals", "context", "send", "feed", "bring_up"):
            self.assertIn(want, names)

    def test_roster_present_bools_usage_remaining_null_not_zero(self):
        resp = _rpc(self.mcp, "tools/call", {"name": "roster", "arguments": {}})
        payload = _tool_payload(resp)
        agents = payload.get("agents") if isinstance(payload, dict) else payload
        self.assertTrue(agents)
        blob = json.dumps(payload)
        self.assertNotIn("unknown", blob)
        ids = {a["id"] for a in agents}
        for hid in ("grok", "claude", "codex", "agy", "cursor-agent"):
            self.assertIn(hid, ids)
        for a in agents:
            self.assertIsInstance(a["present"], bool)
            self.assertNotEqual(a["usage_remaining"], 0)
            if not a["present"]:
                self.assertIsNone(a["usage_remaining"])
                self.assertFalse(a["wired"])
                self.assertIsNone(a["auth"])
                self.assertIsNone(a["models"])
        self.assertIn("path", payload)
        self.assertTrue(payload["path"]["path_ok"])
        self.assertEqual(payload["path"]["path_host"], "bash-interactive")
        desc = None
        for tool in _rpc(self.mcp, "tools/list")["result"]["tools"]:
            if tool["name"] == "roster":
                desc = tool["description"]
        self.assertIsNotNone(desc)
        self.assertIn(".profile", desc)
        self.assertIn("claude", desc.lower())

    def test_feed_after_hook_returns_that_row(self):
        row = hook(self.root, "note", "mcp-feed-row", instance_id="i-mcp")
        resp = _rpc(self.mcp, "tools/call", {"name": "feed", "arguments": {"since": row["ts"]}})
        payload = _tool_payload(resp)
        events = payload.get("events") if isinstance(payload, dict) else payload
        summaries = [e.get("summary") for e in events]
        self.assertIn("mcp-feed-row", summaries)
        ids = [e.get("instance_id") for e in events]
        self.assertIn("i-mcp", ids)

    def test_bring_up_dry_run_uses_seated_session_does_not_mint_or_spawn(self):
        from unittest import mock
        with mock.patch("convoy.mcp_http.live_runner") as spawned:
            spawned.side_effect = AssertionError("live_runner must not run when dry_run true")
            resp = _rpc(self.mcp, "tools/call", {"name": "bring_up", "arguments": {"dry_run": True}})
        payload = _tool_payload(resp)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload.get("dry_run", True))
        self.assertEqual(payload["convoy_id"], self.cid)
        windows = payload["windows"]
        self.assertEqual(len(windows), 2)
        by = {w["to"]: w for w in windows}
        self.assertEqual(by["grok"]["resume"], "sess-grok")
        self.assertEqual(by["grok"]["session_id"], "sess-grok")
        self.assertEqual(by["claude"]["resume"], "sess-claude")
        before = {"sess-grok", "sess-claude"}
        after = {w["session_id"] for w in windows}
        self.assertTrue(after.issubset(before))
        self.assertNotIn("spawned-grok", after)
        spawned.assert_not_called()

    def test_get_root_contains_convoy_bot(self):
        req = urllib.request.Request(self.base + "/", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8")
            ctype = r.headers.get("Content-Type", "")
        self.assertIn("convoy.bot", body)
        self.assertIn("grok-bot native mcp", body)
        self.assertTrue(ctype.startswith("text/html") or ctype.startswith("text/plain"))

    def test_open_alias_dry(self):
        resp = _rpc(self.mcp, "tools/call", {"name": "open", "arguments": {"dry_run": True}})
        payload = _tool_payload(resp)
        self.assertTrue(payload["ok"])
        resumes = {w["to"]: w["resume"] for w in payload["windows"]}
        self.assertEqual(resumes["grok"], "sess-grok")

    def test_glance_includes_conductor_contract_and_keeps_harness_rows(self):
        payload = _tool_payload(_rpc(self.mcp, "tools/call", {"name": "glance", "arguments": {}}))
        conductor = payload["conductor"]
        self.assertEqual(conductor["to"], "grok-bot")
        self.assertEqual(conductor["badge"], "Live")
        self.assertIsNone(conductor["week_pct"])
        self.assertIsNone(conductor["usage_remaining"])
        self.assertIsNone(conductor["resets_at"])
        self.assertIsNone(conductor["on_demand_spent"])
        self.assertIsNone(conductor["on_demand_limit"])
        self.assertEqual(list(payload["overall"].keys()), ["grok", "claude", "codex", "cursor-agent", "agy"])
        self.assertNotIn("grok-bot", payload["overall"])

    def test_roster_claude_blob_usage_normalized_to_null(self):
        def fake_probe(harness):
            if harness == "claude":
                return {
                    "usage_remaining": "Current session: 7% used\nCurrent week (all models): 69% used",
                    "limited": False,
                    "raw": "Current session: 7% used\nCurrent week (all models): 69% used",
                }
            return {"usage_remaining": None, "limited": False, "raw": None}

        def fake_which(name):
            return "/usr/bin/claude" if name == "claude" else None

        with mock.patch("convoy.mcp_http.shutil.which", side_effect=fake_which):
            with mock.patch("convoy.mcp_http.probe", side_effect=fake_probe):
                payload = _tool_payload(_rpc(self.mcp, "tools/call", {"name": "roster", "arguments": {}}))
        by = {a["id"]: a for a in payload["agents"]}
        self.assertIsNone(by["claude"]["usage_remaining"])

    def test_send_live_can_resume_existing_seat_with_session_id(self):
        attempts: list[dict[str, str | None]] = []

        def native_stub(to, body, instance_id=None, resume=None, **k):
            attempts.append({"to": to, "instance_id": instance_id, "resume": resume, "cwd": k.get("cwd")})
            return {
                "ok": True,
                "to": to,
                "session_id": instance_id,
                "model": None,
                "usage_remaining": None,
                "body": "ACK",
                "argv": [to, "--resume", resume or instance_id],
            }

        without_sid = _tool_payload(_rpc(self.mcp, "tools/call", {"name": "send", "arguments": {"to": "grok", "body": "ping", "live": True}}))
        self.assertFalse(without_sid["ok"])
        self.assertIn("seat exists", without_sid["error"])
        with mock.patch("convoy.mcp_http.native_runner", side_effect=native_stub):
            resumed = _tool_payload(
                _rpc(
                    self.mcp,
                    "tools/call",
                    {"name": "send", "arguments": {"to": "grok", "body": "ping", "live": True, "session_id": "sess-grok"}},
                )
            )
        self.assertTrue(resumed["ok"])
        self.assertEqual(resumed["session_id"], "sess-grok")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["instance_id"], "sess-grok")
        self.assertEqual(attempts[0]["resume"], "sess-grok")

    def test_send_live_session_id_uses_seat_vendor_resume(self):
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), resume="vendor-resume-01")
        attempts: list[dict[str, str | None]] = []

        def native_stub(to, body, instance_id=None, resume=None, **k):
            attempts.append({"to": to, "instance_id": instance_id, "resume": resume, "cwd": k.get("cwd")})
            return {
                "ok": True,
                "to": to,
                "session_id": instance_id,
                "model": None,
                "usage_remaining": None,
                "body": "ACK",
                "argv": [to, "--resume", resume or instance_id],
            }

        with mock.patch("convoy.mcp_http.native_runner", side_effect=native_stub):
            resumed = _tool_payload(
                _rpc(
                    self.mcp,
                    "tools/call",
                    {"name": "send", "arguments": {"to": "grok", "body": "ping", "live": True, "session_id": "sess-grok"}},
                )
            )
        self.assertTrue(resumed["ok"])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["instance_id"], "sess-grok")
        self.assertEqual(attempts[0]["resume"], "vendor-resume-01")

    def test_send_live_resume_arg_is_vendor_resume_not_instance_id_alias(self):
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), resume="vendor-resume-02")
        attempts: list[dict[str, str | None]] = []

        def native_stub(to, body, instance_id=None, resume=None, **k):
            attempts.append({"to": to, "instance_id": instance_id, "resume": resume, "cwd": k.get("cwd")})
            return {
                "ok": True,
                "to": to,
                "session_id": instance_id,
                "model": None,
                "usage_remaining": None,
                "body": "ACK",
                "argv": [to, "--resume", resume or instance_id],
            }

        with mock.patch("convoy.mcp_http.native_runner", side_effect=native_stub):
            resumed = _tool_payload(
                _rpc(
                    self.mcp,
                    "tools/call",
                    {"name": "send", "arguments": {"to": "grok", "body": "ping", "live": True, "resume": "vendor-resume-02"}},
                )
            )
        self.assertTrue(resumed["ok"])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["instance_id"], "sess-grok")
        self.assertEqual(attempts[0]["resume"], "vendor-resume-02")

    def test_send_live_session_id_accepts_vendor_resume_token(self):
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), resume="vendor-resume-03")
        attempts: list[dict[str, str | None]] = []

        def native_stub(to, body, instance_id=None, resume=None, **k):
            attempts.append({"to": to, "instance_id": instance_id, "resume": resume, "cwd": k.get("cwd")})
            return {
                "ok": True,
                "to": to,
                "session_id": instance_id,
                "model": None,
                "usage_remaining": None,
                "body": "ACK",
                "argv": [to, "--resume", resume or instance_id],
            }

        with mock.patch("convoy.mcp_http.native_runner", side_effect=native_stub):
            resumed = _tool_payload(
                _rpc(
                    self.mcp,
                    "tools/call",
                    {"name": "send", "arguments": {"to": "grok", "body": "ping", "live": True, "session_id": "vendor-resume-03"}},
                )
            )
        self.assertTrue(resumed["ok"])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["instance_id"], "sess-grok")
        self.assertEqual(attempts[0]["resume"], "vendor-resume-03")

    def test_send_to_ola_brain_refused_by_name(self):
        with mock.patch("convoy.mcp_http.native_runner") as spawned:
            payload = _tool_payload(
                _rpc(
                    self.mcp,
                    "tools/call",
                    {"name": "send", "arguments": {"to": "ola-brain", "body": "ping", "live": True, "worktree": str(self.wt_g)}},
                )
            )
        self.assertFalse(payload["ok"])
        self.assertIn("refuse wrapper target", payload["error"])
        spawned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
