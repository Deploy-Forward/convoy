import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "plugin" / "convoy"


class PluginMarketplacePackContract(unittest.TestCase):
    def test_agent_plugin_manifest_contract(self):
        manifest = PLUGIN_ROOT / "plugin.json"
        self.assertTrue(manifest.is_file(), "plugin/convoy/plugin.json missing")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            data.get("$schema"),
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(data.get("name"), "convoy")
        self.assertIn("description", data)
        self.assertIn("author", data)

    def test_mcp_manifest_contract(self):
        mcp = PLUGIN_ROOT / "mcp.json"
        self.assertTrue(mcp.is_file(), "plugin/convoy/mcp.json missing")
        data = json.loads(mcp.read_text(encoding="utf-8"))
        self.assertEqual(
            data.get("$schema"),
            "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        )
        server = data.get("mcpServers", {}).get("convoy", {})
        self.assertEqual(server.get("type"), "streamable-http")
        self.assertEqual(server.get("url"), "https://convoy.bot/mcp")

    def test_cursor_discovery_manifests_exist(self):
        wrapper = PLUGIN_ROOT / ".cursor-plugin" / "plugin.json"
        self.assertTrue(wrapper.is_file(), "plugin/convoy/.cursor-plugin/plugin.json missing")
        wrapper_json = json.loads(wrapper.read_text(encoding="utf-8"))
        self.assertEqual(wrapper_json.get("name"), "convoy")
        self.assertEqual(wrapper_json.get("skills"), "skills")
        self.assertEqual(wrapper_json.get("mcpServers"), "mcp.json")

        marketplace = REPO / ".cursor-plugin" / "marketplace.json"
        self.assertTrue(marketplace.is_file(), ".cursor-plugin/marketplace.json missing")
        marketplace_json = json.loads(marketplace.read_text(encoding="utf-8"))
        self.assertEqual(marketplace_json.get("metadata", {}).get("pluginRoot"), "plugin")
        plugin_entries = marketplace_json.get("plugins", [])
        convoy_entry = next((p for p in plugin_entries if p.get("name") == "convoy"), None)
        self.assertIsNotNone(convoy_entry, "marketplace entry for convoy missing")
        self.assertEqual(convoy_entry.get("source"), "convoy")

    def test_convoy_skill_live_catalog_contract(self):
        skill = PLUGIN_ROOT / "skills" / "convoy" / "SKILL.md"
        self.assertTrue(skill.is_file(), "plugin convoy skill missing")
        text = skill.read_text(encoding="utf-8")
        self.assertIn("tools/list", text)
        self.assertIn("Never hardcode", text)
        self.assertIn("PR23 lock", text)
        self.assertIn("where", text)
        self.assertIn("harness", text)
        self.assertIn("model", text)
        self.assertIn("effort", text)

    def test_convoy_wizard_skill_flow_contract(self):
        skill = PLUGIN_ROOT / "skills" / "convoy-wizard" / "SKILL.md"
        self.assertTrue(skill.is_file(), "plugin convoy-wizard skill missing")
        text = skill.read_text(encoding="utf-8")
        self.assertIn("GitHub?", text)
        self.assertIn("tools/list", text)
        self.assertIn("never freeze a static tool menu", text)
        self.assertIn("choices", text)
        self.assertIn("join --launch", text)
        self.assertIn("bring_up", text)
        self.assertIn("graph", text)
        self.assertIn("onboard", text)
        self.assertIn("seat", text)
        self.assertIn("send", text)
        self.assertIn("inbox", text)
        self.assertIn("harness_effort.json", text)
        self.assertIn("cvy_*", text)


if __name__ == "__main__":
    unittest.main()
