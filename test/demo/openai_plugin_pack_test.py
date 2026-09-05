import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "convoy"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"


class OpenAIPluginPackContract(unittest.TestCase):
    def test_openai_manifest_is_publishable_and_portable(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], PLUGIN.name)
        self.assertEqual(data["author"]["name"], "Deploy Forward")
        self.assertEqual(data["repository"], "https://github.com/Deploy-Forward/convoy")
        self.assertEqual(data["license"], "MIT")
        self.assertEqual(data["skills"], "./skills/")
        self.assertEqual(data["mcpServers"], "./.mcp.json")
        self.assertNotIn("hooks", data, "hooks/hooks.json is auto-discovered; current validator rejects a manifest field")
        self.assertEqual(data["interface"]["category"], "Developer Tools")
        self.assertEqual(data["interface"]["capabilities"], ["Interactive", "Read"])
        self.assertLessEqual(len(data["interface"]["defaultPrompt"]), 3)
        for prompt in data["interface"]["defaultPrompt"]:
            self.assertLessEqual(len(prompt), 128)
        for field in ("composerIcon", "logo"):
            asset = PLUGIN / data["interface"][field]
            self.assertTrue(asset.is_file(), field)
            self.assertTrue(asset.resolve().is_relative_to(PLUGIN.resolve()))

    def test_stop_hook_and_explicit_end_skill_have_separate_authority(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(command, "convoy end --hook")
        skill = (PLUGIN / "skills" / "convoy-end" / "SKILL.md").read_text(encoding="utf-8")
        agent = (PLUGIN / "skills" / "convoy-end" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("That automatic path", skill)
        self.assertIn("can never push", skill)
        self.assertIn("allow_implicit_invocation: false", agent)

    def test_end_skill_is_identical_in_plugin_package_cli_package_and_project(self):
        packaged_paths = (
            REPO / "skills" / "convoy-end" / "SKILL.md",
            REPO / "src" / "convoy" / "harness_skills" / "convoy-end" / "SKILL.md",
            PLUGIN / "skills" / "convoy-end" / "SKILL.md",
        )
        expected = packaged_paths[0].read_bytes()
        for path in packaged_paths:
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.read_bytes(), expected, str(path))
        project = REPO / ".agents" / "skills" / "convoy-end" / "SKILL.md"
        self.assertEqual(project.read_text(encoding="utf-8"), expected.decode("utf-8"))

    def test_remote_mcp_uses_official_http_shape(self):
        data = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
        server = data["mcpServers"]["convoy"]
        self.assertEqual(server, {"type": "http", "url": "https://convoy.bot/mcp"})
        self.assertFalse((PLUGIN / ".app.json").exists(), "do not invent a registered app id")

    def test_bundled_skill_has_install_and_runtime_safety_contracts(self):
        text = (PLUGIN / "skills" / "convoy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("installation-consent:", text)
        self.assertIn("configured `convoy` MCP server", text)
        self.assertIn("Live-capability gate", text)
        self.assertIn("mutation_attempted: false", text)
        self.assertIn("target-authored acknowledgement", text)
        self.assertIn("Never collapse unknown liveness into inactive", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertNotIn("C:\\Users", text)

    def test_openai_and_existing_plugin_share_canonical_logo(self):
        existing = REPO / "plugin" / "convoy" / "assets" / "logo.svg"
        current = PLUGIN / "assets" / "logo.svg"
        # The Windows checkout may materialize tracked files as CRLF. Compare
        # the SVG text so the package retains the canonical mark without
        # making the contract depend on checkout newline settings.
        self.assertEqual(
            current.read_text(encoding="utf-8"),
            existing.read_text(encoding="utf-8"),
        )

    def test_repo_marketplace_points_to_openai_package(self):
        market = json.loads(
            (REPO / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(market["name"], "convoy")
        entry = next(item for item in market["plugins"] if item["name"] == "convoy")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/convoy"})
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Developer Tools")

    def test_happy_path_is_command_true_and_cloud_honest(self):
        text = (REPO / "docs" / "convoy-happy-path.md").read_text(encoding="utf-8")
        prose = " ".join(text.split())
        self.assertIn("--instance-id codex-1-demo", text)
        self.assertIn("--since 2026-09-04T00:00:00Z", text)
        self.assertNotIn("--since 10m", text)
        self.assertIn("does not silently record \"first process wins\"", prose)
        self.assertIn("isolates roots per user/team", text)
        self.assertIn("queued` alone is not counted as delivered", text)

    def test_publication_runbook_keeps_external_gates_explicit(self):
        text = (REPO / "docs" / "openai-plugin-publication.md").read_text(encoding="utf-8")
        prose = " ".join(text.split())
        self.assertIn("OAuth 2.1", text)
        self.assertIn("never accept a filesystem root", text)
        self.assertIn("https://convoy.bot/privacy", text)
        self.assertIn("Apps Management: Write", prose)
        self.assertIn("five positive and three negative", text)
        self.assertIn("NOT APPLICABLE", text)


if __name__ == "__main__":
    unittest.main()
