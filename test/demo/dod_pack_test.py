"""DoD pack (redeploy / E2E / marketplace) stays honest with the wire.

Docs and scripts only. Counts are derived from mcp_http, never a remembered
25. This test does not probe convoy.bot (that lag is a dated runbook snapshot)
and does not spawn wt / bring_up.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.mcp_http import TOOLS, _WRITE_TOOLS
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mcp_redeploy_verify.py"
REDEPLOY = REPO / "docs" / "redeploy.md"
E2E = REPO / "docs" / "e2e-harness.md"
MARKET = REPO / "docs" / "marketplace-submit.md"
XAI = REPO / "docs" / "xai-plugin-marketplace.md"


class DodPack(unittest.TestCase):
    def test_derived_catalog_matches_mcp_http(self):
        names = [t["name"] for t in TOOLS]
        public = [n for n in names if n not in _WRITE_TOOLS]
        self.assertEqual(len(public), 20, public)
        self.assertEqual(len(_WRITE_TOOLS), 13)
        self.assertEqual(len(names), 33)
        self.assertEqual(len(REQUIRED_WIZARD_VERBS), 11)

    def test_verify_script_catalog_json(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--catalog"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        card = json.loads(proc.stdout)
        self.assertEqual(card["public_count"], 20)
        self.assertEqual(card["packaged_total"], 33)
        self.assertEqual(card["gate0_count"], 11)
        self.assertEqual(card["placeholder_mcp_origin_in_tree"], "https://mcp-origin.example")

    def test_verify_script_loopback_public_and_gated(self):
        env = {**__import__("os").environ, "PYTHONPATH": str(REPO / "src")}
        pub = subprocess.run(
            [sys.executable, str(SCRIPT), "--loopback", "--expect", "public"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(pub.returncode, 0, pub.stderr + pub.stdout[-1500:])
        pub_card = json.loads(pub.stdout)
        self.assertEqual(pub_card["status"], "GREEN")
        self.assertEqual(pub_card["listed_count"], 20)
        self.assertEqual(pub_card["preflight"]["status"], "RED")
        gated = subprocess.run(
            [sys.executable, str(SCRIPT), "--loopback", "--expect", "gated"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(gated.returncode, 0, gated.stderr + gated.stdout[-1500:])
        gated_card = json.loads(gated.stdout)
        self.assertEqual(gated_card["status"], "GREEN")
        self.assertEqual(gated_card["listed_count"], 33)
        self.assertEqual(gated_card["preflight"]["status"], "GREEN")

    def test_runbook_names_live_truth_and_does_not_claim_restart(self):
        text = REDEPLOY.read_text(encoding="utf-8")
        self.assertIn("https://mcp-origin.example", text)
        self.assertIn("CONVOY_MCP_WRITE_TOOLS", text)
        self.assertIn("38.66.81.135", text)
        self.assertIn("127.0.0.1:8788", text)
        self.assertIn("dc70d65f-b7a8-45d6-9eb9-5c676e8c894c", text)
        self.assertIn("does **not** record a live origin restart", text)
        self.assertIn("same 13", text)
        self.assertNotIn("wrangler deploy succeeded", text.lower())

    def test_e2e_outline_has_green_red_for_required_steps(self):
        text = E2E.read_text(encoding="utf-8")
        for step in ("Local plugin symlink", "Gate 0", "GitHub?", "`choices`", "C8", "cvy_*", "`bring_up`"):
            self.assertIn(step, text, step)
        self.assertIn("| GREEN | RED |", text)
        self.assertIn("does **not** run `wt`", text)

    def test_marketplace_checklist_targets_official_form(self):
        text = MARKET.read_text(encoding="utf-8")
        self.assertIn("https://cursor.com/marketplace/publish", text)
        self.assertIn("plugin/convoy", text)
        self.assertIn(".cursor-plugin/marketplace.json", text)
        self.assertIn("does **not** record that a submission was sent", text)

    def test_xai_catalog_entry_is_remote_url_sha_and_nested_path(self):
        text = XAI.read_text(encoding="utf-8")
        self.assertIn('"source": "url"', text)
        self.assertIn("https://github.com/Deploy-Forward/convoy.git", text)
        self.assertIn("d5c711d51827dab214f5372ad5b6124429dee44a", text)
        self.assertIn('"path": "plugin/convoy"', text)
        self.assertIn("xai-org/plugin-marketplace", text)
        self.assertIn("generate-plugin-index.py", text)
        self.assertIn("validate-catalog.py", text)
        self.assertIn("does **not** mean a PR was opened", text)
        grok = REPO / "plugin" / "convoy" / ".grok-plugin" / "plugin.json"
        data = json.loads(grok.read_text(encoding="utf-8"))
        self.assertEqual(data["mcpServers"], "mcp.json")


if __name__ == "__main__":
    unittest.main()
