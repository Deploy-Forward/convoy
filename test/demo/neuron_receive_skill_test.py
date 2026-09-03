"""neuron-receive: the harness-agnostic receive skill (Marco 2026-09-03:
"agent skills, not just a Claude-specific skill"). Installed beside
neuron-identity for grok and claude, pointed at from AGENTS.md for the rest,
byte-identical between the public folder and the package."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.identity import install_neuron_identity

REPO = Path(__file__).resolve().parents[2]


class NeuronReceiveSkill(unittest.TestCase):
    def test_canonical_matches_packaged(self):
        canonical = REPO / "skills" / "neuron-receive" / "SKILL.md"
        packaged = REPO / "src" / "convoy" / "harness_skills" / "neuron-receive" / "SKILL.md"
        self.assertTrue(canonical.is_file())
        self.assertEqual(canonical.read_bytes(), packaged.read_bytes())

    def test_names_every_harness_and_the_ack_rule(self):
        text = (REPO / "skills" / "neuron-receive" / "SKILL.md").read_text(encoding="utf-8")
        for h in ("grok", "claude", "codex", "cursor-agent", "agy", "hermes", "pi"):
            self.assertIn(h, text)
        self.assertIn("inbox --drain", text)
        self.assertIn("--as-me", text)
        self.assertIn("delivered", text)
        self.assertNotIn("python -m convoy send", text)

    def test_installed_into_worktree_for_grok_and_claude_and_named_in_agents(self):
        wt = Path(tempfile.mkdtemp())
        out = install_neuron_identity(wt)
        self.assertTrue(out["ok"])
        for rel in (".grok/skills/neuron-receive/SKILL.md", ".claude/skills/neuron-receive/SKILL.md"):
            self.assertTrue((wt / rel).is_file(), rel)
        agents = (wt / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("neuron-receive", agents)
        self.assertIn("inbox --drain", agents)


if __name__ == "__main__":
    unittest.main()
