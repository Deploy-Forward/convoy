"""This repository ships no second copy of Convoy's skills or plugin packs.

Skills and plugin packs ship from Deploy-Forward/plugins. A skill tree here would be a second
canonical source that drifts from that one, so git tracks no SKILL.md outside the test fixtures,
no skills/, plugin/ or plugins/ tree, and no marketplace file pointing at one.
"""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tracked() -> list[str]:
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise unittest.SkipTest("not a git checkout")
    return [p for p in r.stdout.split("\0") if p]


class OneSkillSource(unittest.TestCase):
    def test_no_skill_file_outside_the_test_fixtures(self):
        stray = [p for p in _tracked() if p.rsplit("/", 1)[-1] == "SKILL.md" and not p.startswith("test/")]
        self.assertEqual(stray, [])

    def test_no_skill_or_plugin_tree_and_no_marketplace_file(self):
        tops = ("skills/", "plugin/", "plugins/", ".agents/plugins/", ".cursor-plugin/", ".claude-plugin/")
        stray = [p for p in _tracked() if p.startswith(tops) or p.endswith("marketplace.json")]
        self.assertEqual(stray, [])
        for d in ("skills", "plugin", "plugins"):
            self.assertFalse((REPO / d).exists(), d)

    def test_the_readme_says_where_skills_ship_from(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("Skills ship from Deploy-Forward/plugins", text)
        self.assertNotIn("](plugin/convoy)", text)
        self.assertNotIn("](plugins/convoy)", text)


if __name__ == "__main__":
    unittest.main()
