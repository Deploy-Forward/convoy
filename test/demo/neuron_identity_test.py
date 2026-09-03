import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import ensure_first_run
from convoy.context import pack, stdin_for
from convoy.identity import SKILL_BEGIN, install_neuron_identity, skill_text
from convoy.onboard import onboard


class NeuronIdentity(unittest.TestCase):
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home.start()
        self.addCleanup(self._home.stop)

    def test_skill_text_is_neuron_not_conductor(self):
        text = skill_text()
        low = text.lower()
        self.assertIn("name: neuron-identity", text)
        self.assertIn("you are one **neuron**", low)
        self.assertIn("not grok bot", low)
        self.assertIn("cvy_", low)
        self.assertIn("convoy send --to", low)
        self.assertIn("bring_up", low)
        self.assertIn("grok-bot-cloud", low)
        self.assertIn("ask the user", low)
        self.assertIn("never", low)
        self.assertIn("ola-brain", low)
        self.assertNotIn("side-chat send", low)
        never = text.split("## Never", 1)[-1].lower()
        self.assertIn("ola-brain", never)
        before_never = text.split("## Never", 1)[0].lower()
        self.assertNotIn("ola-brain side-chat", before_never)

    def test_install_writes_grok_claude_and_agents(self):
        card = install_neuron_identity(self.wt)
        self.assertTrue(card["ok"])
        self.assertTrue(card["written"])
        grok = self.wt / ".grok" / "skills" / "neuron-identity" / "SKILL.md"
        claude = self.wt / ".claude" / "skills" / "neuron-identity" / "SKILL.md"
        agents = self.wt / "AGENTS.md"
        self.assertTrue(grok.is_file())
        self.assertTrue(claude.is_file())
        self.assertTrue(agents.is_file())
        src = skill_text()
        self.assertEqual(grok.read_text(encoding="utf-8"), src)
        self.assertEqual(claude.read_text(encoding="utf-8"), src)
        self.assertIn(SKILL_BEGIN, agents.read_text(encoding="utf-8"))
        self.assertEqual(card["paths"], [str(grok), str(claude)])
        self.assertEqual(card["agents"], str(agents))
        codex_prompt = self.fake_home / ".codex" / "prompts" / "convoy.md"
        self.assertTrue(codex_prompt.is_file())
        self.assertIn("Raw slash-command arguments", codex_prompt.read_text(encoding="utf-8"))
        self.assertEqual(card["codex_prompt"]["path"], str(codex_prompt))

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
        card = ensure_first_run({"to": "claude", "worktree": str(self.wt)})
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("wrote"))
        self.assertTrue(card.get("identity_written"))
        self.assertTrue((self.wt / ".claude" / "settings.json").is_file())
        self.assertTrue((self.wt / ".grok" / "skills" / "neuron-identity" / "SKILL.md").is_file())

    def test_first_run_skips_identity_when_worktree_is_home(self):
        card = ensure_first_run({"to": "grok", "worktree": str(self.fake_home)})
        self.assertTrue(card.get("ok"))
        self.assertFalse(card.get("identity_written"))
        self.assertFalse((self.fake_home / ".grok" / "skills").exists())
        self.assertFalse((self.fake_home / "AGENTS.md").exists())

    def test_onboard_checkout_installs_identity(self):
        root = Path(tempfile.mkdtemp())
        fakes = Path(__file__).resolve().parents[2] / "test" / "fakes"
        with mock.patch.dict(os.environ, {"PATH": str(fakes)}):
            card = onboard(root, ["grok"], thread="cloud-prove", checkout_root=str(self.wt))
        self.assertTrue(card["ok"], card)
        grok = {h["to"]: h for h in card["harnesses"]}["grok"]
        self.assertTrue(grok["first_run"]["identity_written"])
        self.assertTrue((self.wt / ".grok" / "skills" / "neuron-identity" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
