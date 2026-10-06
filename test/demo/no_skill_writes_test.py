"""The CLI writes no skill text and deletes nothing.

Skills ship from Deploy-Forward/plugins. A launch or `convoy skills` writes the AGENTS.md pointer,
the hook files and the root pointers, and nothing else: no convoy-end copy, no Grok agent file, no
Codex prompt, no end command. What an earlier Convoy wrote stays where it is, byte for byte,
whatever its name or text; cleaning it up is the person's call.
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import convoy
from convoy import identity
from convoy.bringup import ensure_first_run, repo_files_for, resume_argv
from convoy.cli import main
from minted_helper import mark_minted

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HARNESSES = ("grok", "claude", "codex", "cursor-agent", "agy", "hermes", "pi")
SKILL_DIRS = (".grok/skills", ".claude/skills", ".agents/skills", ".codex/skills")


def _tree(root: Path) -> dict[str, str]:
    """Every file under root (git internals aside), relative path -> sha256 of its bytes."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith(".git/") and rel != ".git":
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _plant(wt: Path) -> dict[str, bytes]:
    """The files earlier Convoy versions wrote into a worktree, at their old paths."""
    planted = {
        ".grok/skills/convoy-end/SKILL.md": b"---\nname: convoy-end\ndescription: old\n---\nold\n",
        ".claude/skills/convoy-end/SKILL.md": b"---\nname: convoy-end\ndescription: old\n---\nold\n",
        ".agents/skills/convoy-end/SKILL.md": b"---\nname: convoy-end\ndescription: old\n---\nold\n",
        ".claude/skills/neuron-receive/SKILL.md": b"---\nname: neuron-receive\ndescription: canonical\n---\nbody\n",
        ".grok/skills/neuron-receive/SKILL.md": b"---\nname: neuron-receive\ndescription: canonical\n---\nbody\n",
        ".claude/skills/neuron-identity/SKILL.md": b"---\nname: neuron-identity\ndescription: old\n---\nbody\n",
        ".grok/skills/neuron-identity/SKILL.md": b"---\nname: neuron-identity\ndescription: old\n---\nbody\n",
        ".grok/agents/convoy-neuron.md": b"---\nname: convoy-neuron\n---\nold agent\n",
        ".claude/commands/end.md": (FIXTURES / "legacy_end_command.md").read_bytes(),
    }
    for rel, data in planted.items():
        dest = wt / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return planted


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.fake_home = Path(tempfile.mkdtemp())
        self.codex_home = Path(tempfile.mkdtemp())
        for target in ("convoy.bringup.Path.home",):
            p = mock.patch(target, return_value=self.fake_home)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.codex_home)})
        env.start()
        self.addCleanup(env.stop)


class NoSkillTextIsWritten(Sandbox):
    def test_install_writes_no_skill_file_anywhere(self):
        wt = Path(tempfile.mkdtemp())
        card = identity.install_neuron_identity(wt)
        self.assertTrue(card["ok"], card)
        for d in SKILL_DIRS:
            self.assertFalse((wt / d).exists(), d)
        self.assertEqual(sorted(_tree(wt)), ["AGENTS.md"])

    def test_first_run_on_every_harness_writes_no_skill_agent_prompt_or_command(self):
        for hid in HARNESSES:
            with self.subTest(harness=hid):
                wt = Path(tempfile.mkdtemp())
                mark_minted(wt)
                card = ensure_first_run({"to": hid, "worktree": str(wt)}, live=False)
                self.assertTrue(card.get("ok"), card)
                for d in SKILL_DIRS + (".grok/agents", ".claude/commands"):
                    self.assertFalse((wt / d).exists(), (hid, d))
                self.assertNotIn("agent_path", card)
                self.assertFalse((self.codex_home / "prompts").exists(), hid)

    def test_repo_files_name_no_skill_or_agent_file(self):
        for hid in HARNESSES:
            files = repo_files_for(hid)
            self.assertFalse([f for f in files if "/skills/" in f or "/agents/" in f], (hid, files))

    def test_the_writers_are_gone_from_the_module(self):
        for name in ("ensure_grok_agent", "install_codex_prompt", "remove_retired_skills", "end_skill_text",
                     "end_skill_source_path", "codex_prompt_source_path", "_GROK_AGENT_TEXT",
                     "_CODEX_PROMPT_TEXT", "RETIRED_SKILL_NAMES", "END_SKILL_RELATIVE"):
            self.assertFalse(hasattr(identity, name), name)

    def test_the_package_ships_no_skill_text(self):
        pkg = Path(convoy.__file__).resolve().parent
        self.assertFalse((pkg / "harness_skills").exists())


class NothingIsDeleted(Sandbox):
    def test_first_run_leaves_every_earlier_file_byte_for_byte(self):
        wt = Path(tempfile.mkdtemp())
        mark_minted(wt)
        planted = _plant(wt)
        card = ensure_first_run({"to": "grok", "worktree": str(wt)}, live=False)
        self.assertTrue(card.get("ok"), card)
        self.assertEqual(card.get("identity_removed"), [])
        for rel, data in planted.items():
            self.assertEqual((wt / rel).read_bytes(), data, rel)

    def test_convoy_skills_changes_only_the_pointer_and_hook_files(self):
        root = Path(tempfile.mkdtemp())
        wt = Path(tempfile.mkdtemp())
        mark_minted(wt)
        planted = _plant(wt)
        before = _tree(wt)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(root), "skills", "--worktree", str(wt)])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0, card)
        self.assertEqual(card.get("removed"), [])
        after = _tree(wt)
        self.assertEqual([p for p in before if p not in after], [], "a file was deleted")
        changed = sorted(p for p in after if before.get(p) != after[p])
        allowed = {"AGENTS.md", ".claude/settings.local.json", ".grok/hooks/convoy-inbox.json",
                   ".grok/convoy-root", ".claude/convoy-root", ".codex/convoy-root", ".convoy-root",
                   ".convoy/repo-files.json", ".cursor/convoy-root", ".agents/convoy-root"}
        self.assertEqual([p for p in changed if p not in allowed], [], changed)
        for rel, data in planted.items():
            self.assertEqual((wt / rel).read_bytes(), data, rel)


class GrokAgentArgument(unittest.TestCase):
    def test_the_agent_file_an_earlier_convoy_wrote_is_not_passed(self):
        wt = Path(tempfile.mkdtemp())
        old = str(wt / ".grok" / "agents" / "convoy-neuron.md")
        argv = resume_argv({"to": "grok", "worktree": str(wt), "agent": old, "resume": "vendor-1"})
        self.assertNotIn("--agent", argv)

    def test_an_agent_the_person_chose_is_still_passed(self):
        argv = resume_argv({"to": "grok", "worktree": "w", "agent": "agents/cloud-lead.md", "resume": "vendor-1"})
        self.assertEqual(argv[argv.index("--agent") + 1], "agents/cloud-lead.md")


if __name__ == "__main__":
    unittest.main()
