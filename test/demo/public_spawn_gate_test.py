"""Nothing spawns, shows a window, or runs an installer on a PUBLIC process.

The item A verifier (2026-09-04) probed every tool with dry_run=false on an
ungated server and found three pre-existing holes of the same class as the
PR 50 `launch` gap: bring_up/open reached live_runner (wt.exe on the host),
hide/minimize/background reached live_applier (ShowWindow on the host's
desktop), and install with opt_in=true reached the vendor installer. The
responses were already redacted; the side effect still happened.

The DRY read of each stays public - that is the card's data. Only the live
mode is gated, refused BEFORE the runner is reached, and the refusal says so
without claiming to have acted. Behind the gate nothing changes.
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


class PublicSpawnGate(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "gate")
        seat(self.root, "grok", "g-gate", worktree=str(Path(tempfile.mkdtemp())), resume="g-resume")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        # First-run home writes are not what is measured here. bring_up reads
        # the returned card, so the stand-in must be a dict, not None.
        p = mock.patch("convoy.bringup.ensure_first_run",
                       return_value={"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None})
        p.start()
        self.addCleanup(p.stop)

    def _call(self, name, **arguments):
        return _payload(_rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments}))

    def test_public_bring_up_and_open_never_reach_the_live_runner(self):
        with mock.patch("convoy.mcp_http.live_runner") as live:
            for name in ("bring_up", "open"):
                card = self._call(name, thread="gate", dry_run=False)
                self.assertFalse(card.get("ok"), (name, card))
                self.assertFalse(card.get("spawned"), (name, card))
                self.assertIn("CONVOY_MCP_WRITE_TOOLS", card.get("error", ""), name)
            live.assert_not_called()
            # The dry read is the card's data and stays public.
            dry = self._call("bring_up", thread="gate")
            self.assertTrue(dry.get("dry_run"), dry)
            self.assertIsInstance(dry.get("windows"), list)

    def test_public_hide_family_never_reaches_the_live_applier(self):
        with mock.patch("convoy.mcp_http.live_applier") as applier:
            for name in ("hide", "minimize", "background"):
                card = self._call(name, thread="gate", dry_run=False)
                self.assertFalse(card.get("ok"), (name, card))
                self.assertFalse(card.get("applied"), (name, card))
                self.assertIn("CONVOY_MCP_WRITE_TOOLS", card.get("error", ""), name)
            applier.assert_not_called()

    def test_public_install_never_runs_an_installer(self):
        with mock.patch("convoy.mcp_http.install_harness") as run:
            card = self._call("install", to="grok", dry_run=False, opt_in=True)
            self.assertFalse(card.get("ok"))
            self.assertFalse(card.get("ran"))
            self.assertIn("CONVOY_MCP_WRITE_TOOLS", card.get("error", ""))
            run.assert_not_called()
            # The catalog read stays public.
            self._call("install", to="grok")
            run.assert_called_once()
            self.assertTrue(run.call_args.kwargs.get("dry_run"))

    def test_install_opt_in_refusal_reads_the_same_on_every_process(self):
        # Pre-existing contract (phase_install_test): live without opt_in is
        # refused with "opt_in required". The gate sits BEHIND that check so
        # the user-facing reason does not change with the deploy.
        card = self._call("install", to="grok", dry_run=False)
        self.assertFalse(card.get("ok"))
        self.assertEqual(card.get("error"), "opt_in required")

    def test_behind_the_gate_the_live_modes_run(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        with mock.patch("convoy.mcp_http.live_runner") as live, \
             mock.patch("convoy.mcp_http.bring_up", return_value={"ok": True, "windows": []}) as bu:
            self._call("bring_up", thread="gate", dry_run=False)
            self.assertIs(bu.call_args.kwargs.get("runner"), live)
        with mock.patch("convoy.mcp_http.install_harness", return_value={"ok": True, "ran": True}) as run:
            self._call("install", to="grok", dry_run=False, opt_in=True)
            self.assertFalse(run.call_args.kwargs.get("dry_run"))
            self.assertTrue(run.call_args.kwargs.get("opt_in"))


if __name__ == "__main__":
    unittest.main()
