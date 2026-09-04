"""Black-box install: copy the pack somewhere with no src/ and no repo around
it, then resolve it the way a marketplace installer would: marketplace.json ->
pluginRoot/source -> manifests -> mcp.json -> skills/*/SKILL.md."""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.harness_contract import load_harness_contract

REPO = Path(__file__).resolve().parents[2]


def _front_matter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md has no front matter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


class PluginInstallBlackBox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="convoy-plugin-bb-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(REPO / "plugin", self.tmp / "plugin")
        shutil.copytree(REPO / ".cursor-plugin", self.tmp / ".cursor-plugin")
        self.assertFalse((self.tmp / "src").exists())

    def _pack(self) -> Path:
        market = json.loads((self.tmp / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        root = self.tmp / market["metadata"]["pluginRoot"]
        entry = next(p for p in market["plugins"] if p["name"] == "convoy")
        pack = root / entry["source"]
        self.assertTrue(pack.is_dir(), "marketplace source does not resolve to a directory: " + str(pack))
        return pack

    def test_marketplace_resolves_to_installable_pack(self):
        pack = self._pack()
        plugin = json.loads((pack / "plugin.json").read_text(encoding="utf-8"))
        wrapper = json.loads((pack / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], wrapper["name"], "manifests disagree on the plugin name")
        self.assertEqual(plugin["version"], wrapper["version"], "manifests disagree on the version")
        mcp = json.loads((pack / wrapper["mcpServers"]).read_text(encoding="utf-8"))
        server = mcp["mcpServers"]["convoy"]
        self.assertEqual(server["type"], "streamable-http")
        self.assertTrue(server["url"].startswith("https://"))

    def test_every_skill_dir_has_front_matter_matching_its_name(self):
        pack = self._pack()
        wrapper = json.loads((pack / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
        skills = pack / wrapper["skills"]
        dirs = sorted(p for p in skills.iterdir() if p.is_dir())
        self.assertEqual([d.name for d in dirs], ["convoy", "convoy-wizard"])
        for d in dirs:
            sk = d / "SKILL.md"
            self.assertTrue(sk.is_file(), str(sk))
            fm = _front_matter(sk.read_text(encoding="utf-8"))
            self.assertEqual(fm.get("name"), d.name)
            self.assertTrue(fm.get("description"))

    def test_effort_contract_is_bundled_and_loads_without_src(self):
        pack = self._pack()
        bundled = pack / "harness_effort.json"
        self.assertTrue(bundled.is_file(), "pack must carry harness_effort.json: a marketplace install has no src/")
        data = json.loads(bundled.read_text(encoding="utf-8-sig"))
        self.assertTrue(data.get("harnesses"), "bundled contract lists no harnesses")
        ids = {h["id"] for h in data["harnesses"]}
        self.assertTrue({"grok", "claude", "codex"} <= ids, sorted(ids))
        for h in data["harnesses"]:
            self.assertIn("effort", h, h["id"])

    def test_bundled_contract_is_byte_identical_to_packaged(self):
        bundled = REPO / "plugin" / "convoy" / "harness_effort.json"
        packaged = REPO / "src" / "convoy" / "harness_effort.json"
        self.assertEqual(bundled.read_bytes(), packaged.read_bytes(),
                         "plugin/convoy/harness_effort.json diverged from src/convoy/harness_effort.json; copy it over")
        self.assertTrue(load_harness_contract().get("harnesses"))

    def test_pack_reads_effort_from_the_pack_copy(self):
        pack = self._pack()
        wizard = (pack / "skills" / "convoy-wizard" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("plugin/convoy/harness_effort.json", wizard)
        self.assertNotIn("Read `src/convoy/harness_effort.json`", wizard)


if __name__ == "__main__":
    unittest.main()
