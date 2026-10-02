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
from convoy.identity import GROK_AGENT_RELATIVE, SKILL_BEGIN, ensure_grok_agent, install_neuron_identity
from convoy.onboard import onboard

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
        for name in ("convoy-operate", "convoy-listen", "convoy-send"):
            self.assertIn(name, body)
        self.assertIn("convoy@deploy-forward", body)
        self.assertIn("`convoy --root <root> whoami`", body)
        # Install is true for every harness, not only Claude Code.
        self.assertIn("Claude Code and Codex install the convoy plugin from the deploy-forward "
                      "marketplace (Claude Code: `claude plugin install convoy@deploy-forward`)", body)
        self.assertIn("Grok and Cursor get rendered copies when the person runs the plugin's installer "
                      "(`node plugin/install.mjs --apply`).", body)
        self.assertIn("agy, hermes and pi have none yet: run `convoy --root <root> whoami` "
                      "and the receive loop in convoy-listen.", body)
        self.assertNotIn("Every other harness", body)
        for name in RETIRED:
            self.assertNotIn(name, body)
        codex_prompt = self.fake_home / ".codex" / "prompts" / "convoy.md"
        self.assertTrue(codex_prompt.is_file())
        self.assertIn("Raw slash-command arguments", codex_prompt.read_text(encoding="utf-8"))
        self.assertEqual(card["codex_prompt"]["path"], str(codex_prompt))
        # convoy-end is not part of the retirement: still copied as before.
        for d in (".grok", ".claude", ".agents"):
            self.assertTrue((self.wt / d / "skills" / "convoy-end" / "SKILL.md").is_file(), d)
        # The plugin's convoy-end skill carries the end command; no copy is written into the worktree.
        self.assertFalse((self.wt / ".claude" / "commands" / "end.md").exists())
        self.assertIn("Convoy files: don't commit .codex/hooks.json changes Convoy made",
                      (self.wt / "AGENTS.md").read_text(encoding="utf-8"))

    def test_grok_agent_points_at_the_plugin_not_a_retired_skill(self):
        ensure_grok_agent(self.wt)
        text = (self.wt / GROK_AGENT_RELATIVE).read_text(encoding="utf-8")
        self.assertIn("convoy-operate", text)
        self.assertIn("convoy@deploy-forward", text)
        for name in RETIRED:
            self.assertNotIn(name, text)

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

    def test_first_run_removes_only_convoys_own_retired_copies(self):
        ours = []
        for d in (".claude", ".grok"):
            for name in RETIRED:
                f = self.wt / d / "skills" / name / "SKILL.md"
                f.parent.mkdir(parents=True)
                f.write_text("---\nname: " + name + "\ndescription: old\n---\nbody\n", encoding="utf-8")
                ours.append(str(f))
        # A user's own file at a retired path (different name:) stays, and so
        # does anything else beside a Convoy copy.
        users = self.wt / ".claude" / "skills" / "neuron-receive" / "SKILL.md"
        mine = "---\nname: my-receive\n---\nmine\n"
        users.write_text(mine, encoding="utf-8")
        ours.remove(str(users))
        extra = self.wt / ".grok" / "skills" / "neuron-identity" / "notes.md"
        extra.write_text("keep\n", encoding="utf-8")
        card = ensure_first_run({"to": "grok", "worktree": str(self.wt)}, live=False)
        self.assertTrue(card.get("ok"), card)
        self.assertEqual(sorted(card.get("identity_removed") or []), sorted(ours))
        for f in ours:
            self.assertFalse(Path(f).exists(), f)
        self.assertFalse((self.wt / ".claude" / "skills" / "neuron-identity").exists())
        self.assertFalse((self.wt / ".grok" / "skills" / "neuron-receive").exists())
        self.assertEqual(users.read_text(encoding="utf-8"), mine)
        self.assertTrue(extra.is_file())
        again = ensure_first_run({"to": "grok", "worktree": str(self.wt)}, live=False)
        self.assertEqual(again.get("identity_removed"), [])

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
