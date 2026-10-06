import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from convoy.bringup import ensure_first_run
from convoy.context import pack, stdin_for
from convoy.identity import SKILL_BEGIN, install_neuron_identity
from convoy.onboard import onboard
from minted_helper import mark_minted

RETIRED = ("neuron-identity", "neuron-receive")
HARNESSES = ("grok", "claude", "codex", "cursor-agent", "agy", "hermes", "pi")


class NeuronIdentity(unittest.TestCase):
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home.start()
        self.addCleanup(self._home.stop)

    def _neuron_skill_files(self, root):
        return sorted(str(p) for p in Path(root).rglob("SKILL.md")
                      if p.parent.name in RETIRED)

    def test_install_writes_no_retired_skill_and_points_at_the_plugin(self):
        card = install_neuron_identity(self.wt)
        self.assertTrue(card["ok"])
        self.assertTrue(card["written"])
        self.assertEqual(self._neuron_skill_files(self.wt), [])
        agents = self.wt / "AGENTS.md"
        self.assertEqual(card["agents"], str(agents))
        body = agents.read_text(encoding="utf-8")
        self.assertIn(SKILL_BEGIN, body)
        # The block is a pointer: the plugins carry the guidance, convoy-dictionary the words.
        for name in ("convoy-operate", "convoy-dictionary", "Deploy-Forward/plugins"):
            self.assertIn(name, body)
        self.assertIn("`convoy --root <root> whoami`", body)
        self.assertNotIn("install.mjs", body)
        for name in RETIRED:
            self.assertNotIn(name, body)
        # Skills ship from the plugin: no Codex prompt, no convoy-end copy, no end command.
        self.assertNotIn("codex_prompt", card)
        self.assertFalse((self.fake_home / ".codex" / "prompts").exists())
        for d in (".grok", ".claude", ".agents"):
            self.assertFalse((self.wt / d / "skills").exists(), d)
        self.assertFalse((self.wt / ".claude" / "commands" / "end.md").exists())
        agents = (self.wt / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn(".codex/hooks.json", agents)

    def test_install_idempotent_and_preserves_agents_body(self):
        (self.wt / "AGENTS.md").write_text("# keep me\n\nuser rules stay\n", encoding="utf-8")
        first = install_neuron_identity(self.wt)
        second = install_neuron_identity(self.wt)
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        body = (self.wt / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith("# keep me"))
        self.assertIn("user rules stay", body)
        self.assertEqual(body.count(SKILL_BEGIN), 1)

    def test_pack_convoy_id_from_disk_not_invented(self):
        p = pack(self.wt)
        self.assertIsNone(p["convoy_id"])
        self.assertIsNone(p["thread_key"])
        convoy = self.wt / ".convoy"
        convoy.mkdir()
        (convoy / "id").write_text("cvy_testid\n", encoding="utf-8")
        (convoy / "thread").write_text("cloud-prove\n", encoding="utf-8")
        p2 = pack(self.wt)
        self.assertEqual(p2["convoy_id"], "cvy_testid")
        self.assertEqual(p2["thread_key"], "cloud-prove")
        msg = stdin_for(p2, "ping")
        self.assertIn("cvy_testid", msg)
        self.assertIn("cloud-prove", msg)

    def test_first_run_claude_still_writes_settings_and_identity(self):
        mark_minted(self.wt)
        card = ensure_first_run({"to": "claude", "worktree": str(self.wt)})
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("wrote"))
        self.assertTrue(card.get("identity_written"))
        self.assertTrue((self.wt / ".claude" / "settings.local.json").is_file())
        self.assertIn("convoy-operate", (self.wt / "AGENTS.md").read_text(encoding="utf-8"))

    def test_first_run_on_every_harness_writes_no_retired_skill(self):
        for hid in HARNESSES:
            with self.subTest(harness=hid):
                wt = Path(tempfile.mkdtemp())
                card = ensure_first_run({"to": hid, "worktree": str(wt)}, live=False)
                self.assertTrue(card.get("ok"), card)
                self.assertEqual(self._neuron_skill_files(wt), [])
                self.assertEqual(self._neuron_skill_files(self.fake_home), [])
                self.assertEqual(card.get("identity_removed"), [])

    def test_first_run_leaves_retired_copies_where_they_are(self):
        """The CLI removes no skill by name: a neuron-receive in a worktree may be the
        plugin's own canonical copy, and an earlier copy is the person's to clean up."""
        mark_minted(self.wt)
        planted = {}
        for d in (".claude", ".grok"):
            for name in RETIRED:
                f = self.wt / d / "skills" / name / "SKILL.md"
                f.parent.mkdir(parents=True)
                f.write_text("---\nname: " + name + "\ndescription: old\n---\nbody\n", encoding="utf-8")
                planted[f] = f.read_bytes()
        # Neither a dry nor a live first run removes them.
        dry = ensure_first_run({"to": "grok", "worktree": str(self.wt)}, live=False)
        self.assertTrue(dry.get("ok"), dry)
        self.assertEqual(dry.get("identity_removed"), [])
        with mock.patch("convoy.bringup.ensure_inbox_hooks", return_value={"ok": True, "written": False}), \
             mock.patch("convoy.bringup.ensure_hook_trust", return_value={"trust": []}):
            card = ensure_first_run({"to": "grok", "worktree": str(self.wt)}, live=True)
        self.assertTrue(card.get("ok"), card)
        self.assertEqual(card.get("identity_removed"), [])
        for f, data in planted.items():
            self.assertEqual(f.read_bytes(), data, f)

    def test_first_run_skips_identity_when_worktree_is_home(self):
        card = ensure_first_run({"to": "grok", "worktree": str(self.fake_home)})
        self.assertTrue(card.get("ok"))
        self.assertFalse(card.get("identity_written"))
        self.assertFalse((self.fake_home / ".grok" / "skills").exists())
        self.assertFalse((self.fake_home / "AGENTS.md").exists())

    def test_onboard_on_a_checkout_lists_the_pointer_and_writes_nothing_by_default(self):
        root = Path(tempfile.mkdtemp())
        fakes = Path(__file__).resolve().parents[2] / "test" / "fakes"
        with mock.patch.dict(os.environ, {"PATH": str(fakes)}):
            card = onboard(root, ["grok"], thread="cloud-prove", checkout_root=str(self.wt))
        self.assertTrue(card["ok"], card)
        grok = {h["to"]: h for h in card["harnesses"]}["grok"]
        self.assertFalse(grok["first_run"]["identity_written"])
        self.assertIn("AGENTS.md", card["would_write"])
        self.assertFalse((self.wt / "AGENTS.md").exists())

    def test_onboard_checkout_installs_identity_when_asked(self):
        root = Path(tempfile.mkdtemp())
        fakes = Path(__file__).resolve().parents[2] / "test" / "fakes"
        with mock.patch.dict(os.environ, {"PATH": str(fakes)}):
            card = onboard(root, ["grok"], thread="cloud-prove", checkout_root=str(self.wt), write_repo_files=True)
        self.assertTrue(card["ok"], card)
        grok = {h["to"]: h for h in card["harnesses"]}["grok"]
        self.assertTrue(grok["first_run"]["identity_written"])
        self.assertIn("convoy-operate", (self.wt / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(self._neuron_skill_files(self.wt), [])


if __name__ == "__main__":
    unittest.main()
