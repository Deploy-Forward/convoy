"""Grok ACP session-message client. Fake agent; no live TUI, no grok -p/-c."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.grok_acp import (
    ACP_PONG,
    AcpClient,
    _agent_text_chunks,
    looks_like_grok_vendor_id,
    probe_session_prompt,
    try_grok_acp,
    vendor_session_for_cwd,
)
from convoy.identity import ensure_grok_inbox_hook
from convoy.inbox import pending
from convoy.synapse import send_one

FAKE = Path(__file__).resolve().parents[1] / "fakes" / "grok_acp_agent.py"
VENDOR = "01234567-89ab-cdef-0123-456789abcdef"


class GrokAcpClient(unittest.TestCase):
    def test_agent_text_chunks_once_from_nested_update(self):
        msg = {
            "method": "session/update",
            "params": {
                "sessionId": VENDOR,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "ACP_PONG"},
                },
            },
        }
        self.assertEqual(_agent_text_chunks(msg), ["ACP_PONG"])

    def test_vendor_id_shape(self):
        self.assertTrue(looks_like_grok_vendor_id(VENDOR))
        self.assertTrue(looks_like_grok_vendor_id("01a0670d-f4ac-71e2-b048-fe2a12cf27d3"))
        self.assertFalse(looks_like_grok_vendor_id("grok-lead-fable-opus"))
        self.assertFalse(looks_like_grok_vendor_id("01codex"))
        self.assertFalse(looks_like_grok_vendor_id(""))

    def test_fake_agent_session_prompt_streams_pong(self):
        cwd = Path(tempfile.mkdtemp())
        with AcpClient([sys.executable, str(FAKE)], cwd=cwd) as client:
            init = client.initialize()
            self.assertTrue((init.get("agentCapabilities") or {}).get("loadSession"))
            created = client.session_new(cwd)
            self.assertEqual(created.get("sessionId"), VENDOR)
            prompted = client.session_prompt(VENDOR, "ping")
            self.assertEqual(prompted.get("stop_reason"), "end_turn")
            self.assertIn(ACP_PONG, prompted.get("text") or "")

    def test_probe_uses_injected_argv(self):
        cwd = Path(tempfile.mkdtemp())
        with mock.patch("convoy.grok_acp.agent_argv", return_value=[sys.executable, str(FAKE)]):
            card = probe_session_prompt(cwd=cwd, exe=sys.executable)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["pong"])
        self.assertEqual(card["session_id"], VENDOR)
        self.assertTrue(card["capabilities"]["loadSession"])
        self.assertTrue(card["capabilities"]["resume"])

    def test_try_grok_acp_none_without_leader(self):
        with mock.patch("convoy.grok_acp.leader_status", return_value={"ok": True, "available": False}):
            self.assertIsNone(try_grok_acp(VENDOR, "hi", cwd="."))

    def test_try_grok_acp_leader_path_prompts(self):
        cwd = Path(tempfile.mkdtemp())
        with mock.patch("convoy.grok_acp.grok_bin", return_value=sys.executable), \
             mock.patch("convoy.grok_acp.leader_status", return_value={"ok": True, "available": True}), \
             mock.patch("convoy.grok_acp.active_tui_sessions", return_value=[]), \
             mock.patch("convoy.grok_acp.agent_argv", return_value=[sys.executable, str(FAKE)]):
            card = try_grok_acp(VENDOR, "hi from convoy", cwd=cwd)
        self.assertIsNotNone(card)
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(card["runner"], "grok-acp")
        self.assertFalse(card.get("delivered", False))
        self.assertEqual(card["via"], "session/resume")

    def test_vendor_session_for_cwd_reads_active_sessions(self):
        dest = Path(tempfile.mkdtemp()) / "active_sessions.json"
        wt = Path(tempfile.mkdtemp())
        dest.write_text(json.dumps([
            {"session_id": VENDOR, "pid": 1, "cwd": str(wt)},
        ]), encoding="utf-8")
        with mock.patch("convoy.grok_acp.Path.home", return_value=dest.parent):
            # function takes explicit path
            pass
        self.assertEqual(vendor_session_for_cwd(wt), None)  # default path is ~/.grok
        from convoy import grok_acp
        rows = grok_acp.active_tui_sessions(dest)
        self.assertEqual(rows[0]["session_id"], VENDOR)


class GrokAcpSendPath(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "acp-thread")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt), resume=VENDOR)

    def test_live_send_uses_grok_acp_when_leader_attaches(self):
        native = {
            "ok": True,
            "runner": "grok-acp",
            "delivery": "native-queued",
            "exit_code": 0,
            "session_id": VENDOR,
            "via": "session/resume",
            "leader": True,
        }
        with mock.patch("convoy.synapse.try_grok_acp", return_value=native) as pushed:
            card = send_one(
                self.root, "grok", "design review body",
                instance_id="sess-grok",
                allow_interactive_resume=False,
            )
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(card["path"], "grok-acp")
        self.assertFalse(card["delivered"])
        self.assertTrue(card.get("token"))
        waiting = pending(self.root, "sess-grok")
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["path"], "grok-acp")
        self.assertEqual(pushed.call_count, 1)
        framed = pushed.call_args[0][1]
        self.assertIn(card["token"], framed)
        self.assertIn("design review body", framed)
        self.assertIn("session/prompt", framed)

    def test_live_send_falls_back_to_inbox_without_acp(self):
        with mock.patch("convoy.synapse.try_grok_acp", return_value=None):
            card = send_one(
                self.root, "grok", "still queued",
                instance_id="sess-grok",
                allow_interactive_resume=False,
            )
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(card["path"], "inbox")
        self.assertFalse(card["delivered"])


class ForeignWorktreeHook(unittest.TestCase):
    def test_foreign_convoy_wt_venv_is_rewritten(self):
        """Live 2026-09-03: grok-lead kept convoy-wt-inbox's venv because it
        still probed ok. A keep of another worktree's interpreter is a
        delivery bug the moment that worktree is gc'd."""
        from convoy import cmd
        cmd._RESOLVED = None
        wt = Path(tempfile.mkdtemp())
        dest = wt / ".grok" / "hooks" / "convoy-inbox.json"
        dest.parent.mkdir(parents=True)
        prior_cmd = "C:/Users/marco/ola/convoy-wt-inbox/.venv/Scripts/python.exe -m convoy inbox --hook-pretooluse"
        dest.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": prior_cmd, "timeout": 8}]}]}
        }, indent=2) + "\n", encoding="utf-8")
        py = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: command in {prior_cmd, py}):
            card = ensure_grok_inbox_hook(wt)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["written"])
        self.assertNotEqual(card.get("kept_existing"), prior_cmd)
        doc = json.loads(dest.read_text(encoding="utf-8"))
        written = doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertNotIn("convoy-wt-inbox", written)
        self.assertEqual(written, py)


if __name__ == "__main__":
    unittest.main()
