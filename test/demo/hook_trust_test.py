"""Pre-trust hook files at first run so the 'Hooks need review' dialog never shows.

Evidence (this machine, 2026-09-05, read-only):
  grok  ~/.grok/trusted_folders.toml   [folders.'<path>'] trusted = true / decided_at = <epoch>
        (named by ~/.grok/docs/user-guide/10-hooks.md as the unified folder-trust store)
  codex ~/.codex/config.toml           [projects.'<path>'] trust_level = "trusted"  (folder trust)
                                       [hooks.state.'<file>:<event>:<i>:<j>'] trusted_hash = "sha256:..."
                                       -> hash input NOT derivable from the file: never written
  claude ~/.claude.json                projects[<path>].hasTrustDialogAccepted = true
Every write goes to a temp HOME here; the real stores are byte-compared before/after.
"""
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import ensure_first_run, ensure_hook_trust

REAL_STORES = [
    Path(os.path.expanduser("~")) / ".grok" / "trusted_folders.toml",
    Path(os.path.expanduser("~")) / ".codex" / "config.toml",
    Path(os.path.expanduser("~")) / ".claude.json",
]


def _by(card, vendor, key=None):
    rows = [r for r in card["trust"] if r["vendor"] == vendor and (key is None or r.get("key") == key)]
    assert len(rows) == 1, (vendor, key, card["trust"])
    return rows[0]


class HookTrust(unittest.TestCase):
    def setUp(self):
        self.before = {p: (p.read_bytes() if p.is_file() else None) for p in REAL_STORES}
        self.addCleanup(self._real_untouched)
        self.home = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp()) / "convoy-wt-x"
        self.wt.mkdir()
        # a mkdtemp worktree is test residue: the guard refuses it unless told otherwise
        self._tmp = mock.patch("convoy.bringup.is_temp_root", return_value=False)
        self._tmp.start()
        self.addCleanup(self._tmp.stop)

    def _real_untouched(self):
        for p, raw in self.before.items():
            now = p.read_bytes() if p.is_file() else None
            self.assertEqual(now, raw, "real store touched: " + str(p))

    def _seat(self, to):
        return {"to": to, "worktree": str(self.wt), "session_id": to + "-1"}

    # grok -------------------------------------------------------------
    def test_grok_writes_folder_block_in_evidenced_format(self):
        card = ensure_hook_trust(self._seat("grok"), home=self.home, now_fn=lambda: 1700000000)
        row = _by(card, "grok")
        store = self.home / ".grok" / "trusted_folders.toml"
        self.assertEqual(row["store"], str(store))
        self.assertTrue(row["written"])
        data = tomllib.loads(store.read_text(encoding="utf-8"))
        node = data["folders"][str(self.wt.resolve())]
        self.assertIs(node["trusted"], True)
        self.assertEqual(node["decided_at"], 1700000000)

    def test_grok_already_listed_is_not_rewritten(self):
        store = self.home / ".grok" / "trusted_folders.toml"
        store.parent.mkdir(parents=True)
        other = "[folders.'C:\\\\elsewhere']\ntrusted = true\ndecided_at = 1\n"
        store.write_text(other, encoding="utf-8")
        first = ensure_hook_trust(self._seat("grok"), home=self.home, now_fn=lambda: 5)
        self.assertTrue(_by(first, "grok")["written"])
        text1 = store.read_text(encoding="utf-8")
        self.assertTrue(text1.startswith(other), "existing entries are kept verbatim")
        again = ensure_hook_trust(self._seat("grok"), home=self.home, now_fn=lambda: 6)
        row = _by(again, "grok")
        self.assertFalse(row["written"])
        self.assertEqual(row["reason"], "already trusted")
        self.assertEqual(store.read_text(encoding="utf-8"), text1)

    def test_grok_unparseable_store_is_left_alone(self):
        store = self.home / ".grok" / "trusted_folders.toml"
        store.parent.mkdir(parents=True)
        store.write_text("this is = not [toml\n", encoding="utf-8")
        card = ensure_hook_trust(self._seat("grok"), home=self.home)
        row = _by(card, "grok")
        self.assertFalse(row["written"])
        self.assertIn("unparseable", row["reason"])
        self.assertEqual(store.read_text(encoding="utf-8"), "this is = not [toml\n")

    # codex ------------------------------------------------------------
    def test_codex_folder_trust_written_hooks_state_refused_as_unverified(self):
        card = ensure_hook_trust(self._seat("codex"), home=self.home)
        store = self.home / ".codex" / "config.toml"
        folder = _by(card, "codex", "projects")
        self.assertEqual(folder["store"], str(store))
        self.assertTrue(folder["written"])
        data = tomllib.loads(store.read_text(encoding="utf-8"))
        self.assertEqual(data["projects"][str(self.wt.resolve())]["trust_level"], "trusted")
        hooks = _by(card, "codex", "hooks.state")
        self.assertEqual(hooks["store"], str(store))
        self.assertFalse(hooks["written"])
        self.assertEqual(hooks["reason"], "format unverified")
        self.assertNotIn("hooks.state", store.read_text(encoding="utf-8"))

    def test_codex_existing_config_is_appended_not_rewritten(self):
        store = self.home / ".codex" / "config.toml"
        store.parent.mkdir(parents=True)
        base = 'model = "gpt-6-astra"\napproval_policy = "never"\n\n[projects.\'D:\\x\']\ntrust_level = "trusted"\n'
        store.write_text(base, encoding="utf-8")
        card = ensure_hook_trust(self._seat("codex"), home=self.home)
        self.assertTrue(_by(card, "codex", "projects")["written"])
        text = store.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(base))
        data = tomllib.loads(text)
        self.assertEqual(data["model"], "gpt-6-astra")
        self.assertEqual(data["projects"]["D:\\x"]["trust_level"], "trusted")
        again = ensure_hook_trust(self._seat("codex"), home=self.home)
        self.assertFalse(_by(again, "codex", "projects")["written"])
        self.assertEqual(_by(again, "codex", "projects")["reason"], "already trusted")

    # claude -----------------------------------------------------------
    def test_claude_trust_dialog_accepted_in_home_state(self):
        import json
        card = ensure_hook_trust(self._seat("claude"), home=self.home)
        row = _by(card, "claude")
        state = self.home / ".claude.json"
        self.assertEqual(row["store"], str(state))
        self.assertTrue(row["written"])
        data = json.loads(state.read_text(encoding="utf-8"))
        self.assertIs(data["projects"][str(self.wt.resolve())]["hasTrustDialogAccepted"], True)
        again = ensure_hook_trust(self._seat("claude"), home=self.home)
        self.assertFalse(_by(again, "claude")["written"])
        self.assertEqual(_by(again, "claude")["reason"], "already trusted")

    # guards -----------------------------------------------------------
    def test_unknown_vendor_records_null_store(self):
        card = ensure_hook_trust(self._seat("cursor-agent"), home=self.home)
        row = _by(card, "cursor-agent")
        self.assertIsNone(row["store"])
        self.assertFalse(row["written"])
        self.assertIn("no evidenced trust store", row["reason"])

    def test_temp_worktree_is_never_trusted_machine_wide(self):
        self._tmp.stop()
        try:
            card = ensure_hook_trust(self._seat("grok"), home=self.home)
        finally:
            self._tmp.start()
        row = _by(card, "grok")
        self.assertFalse(row["written"])
        self.assertIn("temp worktree", row["reason"])
        self.assertFalse((self.home / ".grok").exists())

    def test_no_worktree_writes_nothing(self):
        card = ensure_hook_trust({"to": "grok"}, home=self.home)
        self.assertFalse(card["ok"])
        self.assertEqual(card["trust"], [])
        self.assertFalse((self.home / ".grok").exists())

    def test_claude_slash_spelling_already_trusted_is_not_rewritten(self):
        import json
        state = self.home / ".claude.json"
        slash = str(self.wt.resolve()).replace("\\", "/")
        state.write_text(json.dumps({"projects": {slash: {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
        before = state.read_bytes()
        card = ensure_hook_trust(self._seat("claude"), home=self.home)
        row = _by(card, "claude")
        self.assertFalse(row["written"])
        self.assertEqual(row["reason"], "already trusted")
        self.assertEqual(state.read_bytes(), before)

    def test_claude_first_run_writes_home_state_once(self):
        """hook trust and the prepare step share ONE writer: a claude first run rewrites ~/.claude.json once."""
        import convoy.bringup as b
        real = b._write_json_dict
        writes = []

        def counting(path, data):
            writes.append(Path(path))
            real(path, data)

        hook_card = {"ok": True, "written": True, "command": None, "kinds": None}
        with mock.patch("convoy.bringup.Path.home", return_value=self.home), \
                mock.patch("convoy.bringup.ensure_inbox_hooks", return_value=hook_card), \
                mock.patch("convoy.bringup._write_json_dict", counting):
            out = ensure_first_run(self._seat("claude"), root=None, live=True)
        self.assertTrue(out["trust_written"])
        self.assertTrue(_by({"trust": out["hook_trust"]}, "claude")["written"])
        self.assertEqual([p for p in writes if p.name == ".claude.json"], [self.home / ".claude.json"])
        self.assertFalse(out["trust_rewritten"], "prepare step read the key hook trust already wrote")

    def test_dry_first_run_writes_no_vendor_store(self):
        """relaunch --dry-run / crew without --launch: machine-wide stores are never touched."""
        with mock.patch("convoy.bringup.Path.home", return_value=self.home):
            out = ensure_first_run(self._seat("grok"), root=None, live=False)
        self.assertEqual(out["hook_trust"], [])
        self.assertEqual(out["hook_trust_skipped"], "dry-run")
        self.assertFalse((self.home / ".grok").exists())

    def test_live_first_run_carries_hook_trust_per_seat(self):
        hook_card = {"ok": True, "written": True, "command": None, "kinds": None}
        with mock.patch("convoy.bringup.Path.home", return_value=self.home), \
                mock.patch("convoy.bringup.ensure_inbox_hooks", return_value=hook_card):
            out = ensure_first_run(self._seat("grok"), root=None, live=True)
        rows = out["hook_trust"]
        self.assertEqual([r["vendor"] for r in rows], ["grok"])
        self.assertTrue(rows[0]["written"])
        self.assertTrue((self.home / ".grok" / "trusted_folders.toml").is_file())

if __name__ == "__main__":
    unittest.main()
