import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

REPO = Path(__file__).resolve().parents[2]


class SkillsFolderContract(unittest.TestCase):
    """Top-level skills/ is the canonical public home; the packaged copy under
    src/convoy/harness_skills stays where package-data and identity.py already
    reach it (a top-level dir cannot be an importlib resource without claiming
    the generic `skills` package name — design option B). Byte-equality
    is the invariant: editing one copy without the other goes red loudly."""

    def test_retired_neuron_skills_are_gone_from_both_homes(self):
        # Retired 2026-09-28: the Convoy plugin's skills (convoy-operate,
        # convoy-listen, convoy-send) replace neuron-identity and neuron-receive.
        for name in ("neuron-identity", "neuron-receive"):
            for home in (REPO / "skills", REPO / "src" / "convoy" / "harness_skills"):
                self.assertFalse((home / name).exists(), str(home / name))

    def test_convoy_end_canonical_matches_packaged(self):
        canonical = REPO / "skills" / "convoy-end" / "SKILL.md"
        packaged = REPO / "src" / "convoy" / "harness_skills" / "convoy-end" / "SKILL.md"
        self.assertTrue(canonical.is_file(), "skills/convoy-end/SKILL.md missing")
        self.assertEqual(canonical.read_bytes(), packaged.read_bytes(),
                         "canonical and packaged convoy-end skills diverged")

    def test_convoy_sheet_exists_with_honest_front_matter(self):
        sheet = REPO / "skills" / "convoy" / "SKILL.md"
        self.assertTrue(sheet.is_file(), "skills/convoy/SKILL.md missing")
        text = sheet.read_text(encoding="utf-8")
        self.assertIn("name: convoy", text)
        self.assertIn("install_binding: temporary", text)
        self.assertIn("vendor_prompt_policy: auto-accept-within-scope", text)
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
        self.assertIn("/prompts:convoy", text)


if __name__ == "__main__":
    unittest.main()


class ConvoyNudgeSkillIsReplicable(unittest.TestCase):
    """The deaf-pane recovery that worked live (2026-09-05) ships as a skill
    plus the script it runs; both must exist, agree, and carry the refusals."""

    def test_skill_and_script_exist_and_agree(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        skill = (repo / "skills" / "convoy-nudge" / "SKILL.md").read_text(encoding="utf-8")
        script = (repo / "scripts" / "wt-nudge.ps1").read_text(encoding="utf-8")
        self.assertIn("scripts\wt-nudge.ps1", skill)
        for step in ("relaunch", "--seat", "inbox --wait", "seated", "whoami"):
            self.assertIn(step, skill, step)
        for guard in ("-List", "-DryRun", "IdleTitle", "Waiting for response", "CASCADIA_HOSTING_WINDOW_CLASS", "AttachThreadInput"):
            self.assertIn(guard, script, guard)
        # refuses: busy pane, several windows, no root; never -p / --resume
        self.assertIn("nothing typed", script)
        self.assertIn("-Root <thread root> is required", script)
        for banned in ("--resume", " -p "):
            self.assertNotIn(banned, script.split("# Only on the machine")[1] if "# Only on the machine" in script else script, banned)
        self.assertIn("## Refuse", skill)
