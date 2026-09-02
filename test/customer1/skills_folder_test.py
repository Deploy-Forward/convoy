import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

REPO = Path(__file__).resolve().parents[2]


class SkillsFolderContract(unittest.TestCase):
    """Top-level skills/ is the canonical public home; the packaged copy under
    src/convoy/harness_skills stays where package-data and identity.py already
    reach it (a top-level dir cannot be an importlib resource without claiming
    the generic `skills` package name — opus-2 design, Option B). Byte-equality
    is the invariant: editing one copy without the other goes red loudly."""

    def test_neuron_identity_canonical_matches_packaged(self):
        canonical = REPO / "skills" / "neuron-identity" / "SKILL.md"
        packaged = REPO / "src" / "convoy" / "harness_skills" / "neuron-identity" / "SKILL.md"
        self.assertTrue(canonical.is_file(), "skills/neuron-identity/SKILL.md missing")
        self.assertTrue(packaged.is_file())
        self.assertEqual(canonical.read_bytes(), packaged.read_bytes(),
                         "canonical and packaged neuron-identity skills diverged")

    def test_convoy_sheet_exists_with_honest_front_matter(self):
        sheet = REPO / "skills" / "convoy" / "SKILL.md"
        self.assertTrue(sheet.is_file(), "skills/convoy/SKILL.md missing")
        text = sheet.read_text(encoding="utf-8")
        self.assertIn("name: convoy", text)
        # the sheet is a snapshot unless it says when it was rendered
        self.assertIn("rendered from live tools/list", text)
        # the single most confusing public fact must be stated
        self.assertIn("one root", text.lower())

    def test_skills_readme_exists(self):
        readme = REPO / "skills" / "README.md"
        self.assertTrue(readme.is_file(), "skills/README.md missing")
        text = readme.read_text(encoding="utf-8")
        self.assertIn(".claude/skills", text)
        self.assertIn(".grok/skills", text)


if __name__ == "__main__":
    unittest.main()
