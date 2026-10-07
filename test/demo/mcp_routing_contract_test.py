"""The MCP surface routes the calls its own refusals ask for, and serves the contract it cites.

An origin that serves every thread (no --root) refused onboard and crew whatever they were
given: `thread` was stripped from both before routing, and onboard's checkout_root was never
read, so no argument combination could onboard a new checkout there. initialize told the
conductor to read conductor.md, and no tool returned it. `python -m convoy.mcp_http` with no
--root crashed on Path(None). A ValueError inside a tool became a bare -32603.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import mcp_http, onboard as onboard_module
from convoy.conductor import CONTRACT_RELATIVE, contract_pointer, contract_sha, contract_text
from convoy.convoy import bind, ensure_id, read_id
try:
    from test.demo.write_gate_fixture import closed_write_gate, open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import closed_write_gate, open_write_gate, write_gate, write_gate_if  # noqa: F401

UNROUTED = "this origin serves every thread"


class UnboundOriginRoutes(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        for p in (mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}),
                  write_gate(),
                  mock.patch("convoy.bringup.Path.home", return_value=self.home),
                  mock.patch("convoy.index.is_temp_root", return_value=False),
                  mock.patch.object(onboard_module, "probe", return_value={}),
                  mock.patch.object(onboard_module, "_which", return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def test_unbound_onboard_routes_by_checkout_root(self):
        checkout = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(checkout)], check=True, capture_output=True)
        card = mcp_http.call_tool(None, "onboard", {"thread": "fresh", "checkout_root": str(checkout), "to": ["codex"]})
        self.assertTrue(card["ok"], card)
        self.assertTrue((checkout / ".convoy" / "id").is_file())
        self.assertEqual(Path(card["root"]).resolve(), checkout.resolve())

    def test_unbound_crew_routes_by_thread_key(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "crew-route")
        card = mcp_http.call_tool(None, "crew", {"thread": "crew-route", "seats": [{"harness": "codex"}]})
        self.assertNotIn(UNROUTED, str(card.get("error")), card)
        self.assertEqual(Path(card["root"]).resolve(), root.resolve())

    def test_unroutable_refusal_names_an_argument_the_tool_accepts(self):
        card = mcp_http.call_tool(None, "onboard", {"to": ["codex"]})
        self.assertFalse(card["ok"])
        self.assertIn("checkout_root=", card["error"])
        accepted = set(next(t for t in mcp_http.TOOLS if t["name"] == "onboard")["inputSchema"]["properties"])
        self.assertIn("checkout_root", accepted)


class ContractAndErrors(unittest.TestCase):
    def test_mcp_serves_conductor_contract_body(self):
        self.assertIn("contract", {t["name"] for t in mcp_http.TOOLS})
        card = mcp_http.call_tool(None, "contract", {})
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["sha"], contract_sha())
        self.assertEqual(card["text"], contract_text())

    def test_mcp_main_without_root_serves_all_threads(self):
        with mock.patch.object(mcp_http, "serve", return_value=0) as serve:
            self.assertEqual(mcp_http.main(["--port", "1"]), 0)
        self.assertIsNone(serve.call_args.args[0])

    def test_wrapped_verb_value_error_returns_tool_error_text(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "errors")
        with mock.patch.object(mcp_http, "build_roster", side_effect=ValueError("synthetic refusal")):
            card = mcp_http.call_tool(root, "roster", {})
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], "synthetic refusal")

    def test_contract_sha_ignores_line_endings(self):
        root = Path(tempfile.mkdtemp())
        dest = root / CONTRACT_RELATIVE
        dest.parent.mkdir(parents=True)
        dest.write_bytes(contract_text().replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
        self.assertTrue(contract_pointer(root)["current"])

    def test_gate_texts_name_the_bearer(self):
        with closed_write_gate():  # no bearer on these calls
            pruned = mcp_http.call_tool(None, "threads", {"prune": True})
            root = Path(tempfile.mkdtemp())
            ensure_id(root)
            resumed = mcp_http.call_tool(root, "resume", {"neuron": "x", "go": True})
        for card in (pruned, resumed):
            self.assertIn("Authorization: Bearer", card["error"], card)


if __name__ == "__main__":
    unittest.main()
