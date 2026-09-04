import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "plugin" / "convoy"


class PluginMarketplacePackContract(unittest.TestCase):
    def test_xai_grok_plugin_manifest_contract(self):
        manifest = PLUGIN_ROOT / ".grok-plugin" / "plugin.json"
        self.assertTrue(manifest.is_file(), "xAI .grok-plugin/plugin.json missing")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data.get("name"), "convoy")
        self.assertEqual(data.get("license"), "MIT")
        self.assertEqual(data.get("repository"), "https://github.com/Deploy-Forward/convoy")
        self.assertTrue(data.get("version"))
        self.assertTrue(data.get("description"))

    def test_xai_grok_mcp_contract(self):
        mcp = PLUGIN_ROOT / ".mcp.json"
        self.assertTrue(mcp.is_file(), "xAI .mcp.json missing")
        data = json.loads(mcp.read_text(encoding="utf-8"))
        server = data.get("mcpServers", {}).get("convoy", {})
        self.assertEqual(server.get("type"), "http")
        self.assertEqual(server.get("url"), "https://convoy.bot/mcp")
        note = server.get("note", "")
        self.assertIn("tools/list", note)
        self.assertIn("fails closed", note)
        self.assertIn("hide write", note)

    def test_grok_catalog_discovers_like_exa(self):
        """xai-org/plugin-marketplace plugin_catalog.py load_manifest reads
        .grok-plugin/plugin.json (not .cursor-plugin). scan_mcp_servers
        defaults to .mcp.json unless the grok manifest sets mcpServers to a
        path string. Exa's pack has no mcpServers key; ours must match or the
        catalog indexes mcp.json and Grok Build never attaches the endpoint.
        """
        grok = json.loads((PLUGIN_ROOT / ".grok-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("mcpServers", grok, "a path here would hide .mcp.json from the xAI indexer")
        self.assertNotIn("$schema", grok)
        # Brand-scoped CTA terms only (CONTRIBUTING.md rejects generic mcp/cli/deploy).
        for kw in grok.get("keywords") or []:
            self.assertNotIn(kw.lower(), {"mcp", "cli", "deploy", "api", "skills", "database"})
        self.assertIn("convoy wizard", grok.get("keywords") or [])

        compat = json.loads((PLUGIN_ROOT / "mcp.json").read_text(encoding="utf-8"))
        grok_mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            grok_mcp["mcpServers"]["convoy"]["url"],
            compat["mcpServers"]["convoy"]["url"],
        )

        skills = []
        for child in sorted((PLUGIN_ROOT / "skills").iterdir()):
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            text = skill_md.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), child.name)
            name_line = next(line for line in text.splitlines()[1:] if line.startswith("name:"))
            skills.append(name_line.split(":", 1)[1].strip())
        self.assertEqual(skills, ["convoy", "convoy-wizard"])

    def test_pack_readme_names_official_marketplace_not_cursor_publish(self):
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/xai-org/plugin-marketplace", readme)
        self.assertIn(".mcp.json", readme)
        self.assertIn('path": "plugin/convoy"', readme)
        self.assertNotIn("cursor.com/marketplace/publish", readme)
        self.assertIn("/marketplace", readme)
        self.assertIn("unverified", readme.lower())

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
        # #51 classifier is three-way; a two-class "redeploy or not-registered"
        # card would send a marketplace host looking for a CLI that is not there.
        self.assertIn("write-gated", text)
        self.assertIn("redeploy", text)
        self.assertIn("not-registered", text)
        self.assertIn("`card`", text)

    def test_convoy_wizard_skill_flow_contract(self):
        skill = PLUGIN_ROOT / "skills" / "convoy-wizard" / "SKILL.md"
        self.assertTrue(skill.is_file(), "plugin convoy-wizard skill missing")
        text = skill.read_text(encoding="utf-8")
        self.assertIn("GitHub?", text)
        self.assertIn("tools/list", text)
        self.assertIn("never freeze a static tool menu", text)
        self.assertIn("graph", text)
        self.assertIn("onboard", text)
        self.assertIn("send", text)
        self.assertIn("inbox", text)
        self.assertIn("harness_effort.json", text)
        self.assertIn("cvy_*", text)
        # Gate 0 walk after item F: card + crew, not per-chair join/launch/seat.
        for verb in ("card", "repos", "clone", "crew", "consent", "await_seated"):
            self.assertIn("`" + verb + "`", text, "wizard skill must name Gate 0 verb " + verb)


if __name__ == "__main__":
    unittest.main()
