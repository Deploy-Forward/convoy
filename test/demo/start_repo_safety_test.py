"""`convoy start` on a real repo writes nothing into it outside `.convoy/`, and never a permission.

A permission mode in a project `.claude/settings.json` is honoured by Claude Code, so every Claude
session in that repo, Convoy-launched or not, would run without prompts. Convoy-launched neurons get
their mode from the launch argv, and nothing else does:

  - no settings file Convoy writes carries `permissions` or `skipDangerousModePermissionPrompt`;
  - hooks and auto-compact go to `.claude/settings.local.json`, never the tracked settings file;
  - `start` on a repo root leaves `git status` clean except `.convoy/`, and lists what it would
    write as `would_write`; it writes those files only with `write_repo_files`;
  - the home `~/.claude/settings.json` gets one key, only when that key is missing, and an
    unchanged file is never rewritten; `home_written` and `home_key` say what happened.

The repo is a scratch git repository in a temporary folder, the home and the Convoy home are
temporary folders, and no harness is probed or started.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import convoy.onboard as onboard_module
from convoy.bringup import ensure_first_run
from convoy.start import start

HOME_KEY = "skipDangerousModePermissionPrompt"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class RepoRoot(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-safety-home-"))
        convoy_home = Path(tempfile.mkdtemp(prefix="convoy-safety-chome-"))
        env = mock.patch.dict(os.environ, {"USERPROFILE": str(self.home), "HOME": str(self.home),
                                           "CONVOY_HOME": str(convoy_home)})
        env.start()
        self.addCleanup(env.stop)
        for patch in (mock.patch.object(onboard_module, "probe", return_value={}),
                      mock.patch.object(onboard_module, "_which", side_effect=lambda h: "C:/synthetic/" + h)):
            patch.start()
            self.addCleanup(patch.stop)
        self.repo = Path(tempfile.mkdtemp(prefix="convoy-safety-repo-"))
        _git(self.repo, "init", "-q")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text('{\n  "hooks": {}\n}\n', encoding="utf-8")
        (self.repo / "README.md").write_text("synthetic\n", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test",
             "commit", "-qm", "init")
        self.tracked = (self.repo / ".claude" / "settings.json").read_bytes()
        self.before = self.files()

    def files(self):
        return {p.relative_to(self.repo).as_posix() for p in self.repo.rglob("*")
                if p.is_file() and p.relative_to(self.repo).parts[0] != ".git"}

    def start(self, **kwargs):
        return start(self.repo, str(self.repo), harnesses=["claude", "codex", "grok"],
                     identify_fn=lambda r: {}, bodies_fn=lambda r: {"chairs": []}, **kwargs)

    def home_settings(self):
        return self.home / ".claude" / "settings.json"

    def json_files(self, base):
        out = {}
        for p in Path(base).rglob("*.json"):
            if ".git" in p.parts:
                continue
            try:
                out[p] = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
        return out


class StartOnARepoRoot(RepoRoot):
    def test_git_status_is_clean_and_the_tracked_settings_are_byte_identical(self):
        card = self.start()
        self.assertTrue(card["ok"], card)
        status = _git(self.repo, "status", "--porcelain", "--untracked-files=all").splitlines()
        self.assertEqual([line for line in status if not line[3:].startswith(".convoy/")], [])
        self.assertEqual((self.repo / ".claude" / "settings.json").read_bytes(), self.tracked)
        new = self.files() - self.before
        self.assertEqual(sorted(f for f in new if not f.startswith(".convoy/")), [],
                         "nothing is written into the repo except under .convoy/")

    def test_it_lists_what_it_would_write_and_writes_it_only_when_asked(self):
        card = self.start()
        would = set(card["would_write"])
        for path in ("AGENTS.md", ".claude/settings.local.json", ".codex/hooks.json",
                     ".grok/hooks/convoy-inbox.json"):
            self.assertIn(path, would)
        self.assertNotIn(".claude/settings.json", would)
        self.assertFalse(card["write_repo_files"])
        written = self.start(write_repo_files=True)
        self.assertTrue(written["ok"], written)
        self.assertTrue(written["write_repo_files"])
        self.assertTrue((self.repo / "AGENTS.md").is_file())
        local = json.loads((self.repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        self.assertIn("UserPromptSubmit", local["hooks"])
        self.assertIs(local["autoCompactEnabled"], True)
        self.assertEqual((self.repo / ".claude" / "settings.json").read_bytes(), self.tracked)

    def test_no_settings_file_anywhere_gets_permissions(self):
        self.start(write_repo_files=True)
        wt = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
        ensure_first_run({"to": "claude", "worktree": str(wt)}, root=self.repo, live=False)
        for base in (self.repo, wt, self.home):
            for path, data in self.json_files(base).items():
                if isinstance(data, dict):
                    self.assertNotIn("permissions", data, str(path))
                    if path != self.home_settings():
                        self.assertNotIn(HOME_KEY, data, str(path))


class TheHomeFile(RepoRoot):
    def claude_first_run(self, card):
        [claude] = [h for h in card["harnesses"] if h["to"] == "claude"]
        return claude["first_run"]

    def test_the_home_file_is_untouched_when_its_key_is_present(self):
        self.home_settings().parent.mkdir(parents=True)
        self.home_settings().write_text('{"skipDangerousModePermissionPrompt": true,   "other": 1}', encoding="utf-8")
        before = self.home_settings().read_bytes()
        stamp = self.home_settings().stat().st_mtime_ns
        card = self.start(write_repo_files=True)
        first = self.claude_first_run(card)
        self.assertFalse(first["home_written"])
        self.assertEqual(first["home_key"], HOME_KEY)
        self.assertEqual(self.home_settings().read_bytes(), before)
        self.assertEqual(self.home_settings().stat().st_mtime_ns, stamp)

    def test_the_home_key_is_written_once_when_missing_and_alone(self):
        self.home_settings().parent.mkdir(parents=True)
        self.home_settings().write_text('{"other": 1}', encoding="utf-8")
        first = self.claude_first_run(self.start())
        self.assertTrue(first["home_written"])
        self.assertEqual(first["home_key"], HOME_KEY)
        self.assertEqual(json.loads(self.home_settings().read_text(encoding="utf-8")), {"other": 1, HOME_KEY: True})
        before = self.home_settings().read_bytes()
        again = self.claude_first_run(self.start())
        self.assertFalse(again["home_written"])
        self.assertEqual(self.home_settings().read_bytes(), before)


    def test_an_unparseable_home_settings_file_is_left_alone(self):
        self.home_settings().parent.mkdir(parents=True)
        self.home_settings().write_text('{"other": 1,}', encoding="utf-8")
        before = self.home_settings().read_bytes()
        first = self.claude_first_run(self.start())
        self.assertFalse(first["home_written"])
        self.assertEqual(first["home_error"], "unparseable")
        self.assertEqual(self.home_settings().read_bytes(), before)

    def test_an_unparseable_claude_state_file_is_left_alone(self):
        state = self.home / ".claude.json"
        state.write_text('{"projects": {},}', encoding="utf-8")
        before = state.read_bytes()
        wt = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
        card = ensure_first_run({"to": "claude", "worktree": str(wt)}, root=wt, live=False)
        self.assertFalse(card["trust_written"])
        self.assertEqual(card["trust_error"], "unparseable")
        self.assertEqual(state.read_bytes(), before)


class WhatAFirstRunWrites(RepoRoot):
    def test_would_write_equals_what_a_real_write_produces(self):
        for to in ("claude", "codex", "grok"):
            listed = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
            written = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
            said = ensure_first_run({"to": to, "worktree": str(listed)}, root=listed, write_repo_files=False)
            ensure_first_run({"to": to, "worktree": str(written)}, root=written, write_repo_files=True)
            real = {p.relative_to(written).as_posix() for p in written.rglob("*") if p.is_file()}
            self.assertEqual(set(said["would_write"]), real, to)
            self.assertEqual(list(listed.iterdir()), [], to + ": listing writes nothing")

    def test_a_minted_worktree_stays_clean_in_git_after_its_first_run(self):
        for to in ("claude", "codex", "grok"):
            wt = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
            _git(wt, "init", "-q")
            (wt / "README.md").write_text("synthetic\n", encoding="utf-8")
            _git(wt, "add", ".")
            _git(wt, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "init")
            card = ensure_first_run({"to": to, "worktree": str(wt)}, root=wt, write_repo_files=True)
            self.assertTrue(card["ok"], card)
            status = {line[3:] for line in _git(wt, "status", "--porcelain", "--untracked-files=all").splitlines()}
            # Only Convoy-named paths are hidden; a file the person could own stays visible and is named.
            self.assertEqual(status, set(card["left_visible"]), to)
            self.assertIn("AGENTS.md", card["left_visible"], to)
            for line in status:
                self.assertNotIn("convoy", line.lower(), to)

    def test_the_exclude_never_hides_a_file_the_person_owns(self):
        from convoy.repo import mint_worktrees
        main = Path(tempfile.mkdtemp(prefix="convoy-safety-main-"))
        _git(main, "init", "-q")
        (main / "README.md").write_text("synthetic\n", encoding="utf-8")
        _git(main, "add", ".")
        _git(main, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "init")
        (main / "AGENTS.md").write_text("the person's own\n", encoding="utf-8")
        (main / "docs").mkdir()
        (main / "docs" / "AGENTS.md").write_text("the person's own\n", encoding="utf-8")
        minted = mint_worktrees(main, 1, names=["neuron"])
        self.assertTrue(minted["ok"], minted)
        wt = Path(minted["worktrees"][0]["path"])
        card = ensure_first_run({"to": "claude", "worktree": str(wt)}, root=wt, write_repo_files=True)
        self.assertTrue(card["ok"], card)
        status = {line[3:] for line in _git(main, "status", "--porcelain", "--untracked-files=all").splitlines()}
        self.assertIn("AGENTS.md", status)
        self.assertIn("docs/AGENTS.md", status)
        exclude = Path(_git(main, "rev-parse", "--git-common-dir").strip())
        exclude = (exclude if exclude.is_absolute() else main / exclude) / "info" / "exclude"
        added = [l for l in exclude.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
        for line in added:
            self.assertTrue(line.startswith("/"), "every entry is anchored: " + line)
            self.assertNotIn("AGENTS.md", line)

    def test_an_exclude_that_cannot_be_written_is_a_note_not_a_failure(self):
        with mock.patch("convoy.repo.exclude_paths", side_effect=OSError("exclude locked")):
            card = self.start(write_repo_files=True)
        self.assertTrue(card["ok"], card)
        self.assertTrue(any("exclude locked" in n for n in card["start_card"]["notes"]), card["start_card"]["notes"])

    def test_the_start_card_warns_about_convoy_hooks_left_in_the_tracked_settings(self):
        hook = lambda command: [{"hooks": [{"type": "command", "command": command}]}]
        tracked = {"hooks": {"UserPromptSubmit": hook("convoy inbox --hook-pretooluse"),
                             "Stop": hook("convoy end --hook"), "PreToolUse": hook("echo person-hook")}}
        (self.repo / ".claude" / "settings.json").write_text(json.dumps(tracked), encoding="utf-8")
        _git(self.repo, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test",
             "commit", "-qam", "tracked hooks")
        card = self.start()
        warning = ("tracked .claude/settings.json has 2 Convoy hooks; they now live in settings.local.json; "
                   "remove them from the tracked file")
        self.assertIn(warning, card["start_card"]["notes"])
        self.assertIn(warning, card["start_card"]["lines"])
        self.assertEqual(json.loads((self.repo / ".claude" / "settings.json").read_text(encoding="utf-8")), tracked)


class TheTrustStores(unittest.TestCase):
    """A vendor's TOML trust store is the person's: a table for the path is never added twice, a
    store that does not parse is never written, and what is written still parses."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-safety-home-"))
        # Not a temp path: ensure_hook_trust never trusts a temp worktree machine-wide, so the
        # stores' own writers are driven directly. The folder need not exist.
        self.wt = os.path.normpath("C:/synthetic/convoy-trust-wt" if os.name == "nt" else "/synthetic/convoy-trust-wt")

    def trust(self, to):
        from convoy.bringup import _trust_codex, _trust_grok
        return _trust_codex(self.wt, self.home) if to == "codex" else _trust_grok(self.wt, self.home, 1)

    def assert_left_alone(self, store, text, to, vendor):
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(text, encoding="utf-8")
        before = store.read_bytes()
        rows = [r for r in self.trust(to) if r["vendor"] == vendor and r.get("key", "projects") == "projects"]
        self.assertEqual(store.read_bytes(), before)
        self.assertFalse(rows[0]["written"])
        import tomllib
        tomllib.loads(store.read_text(encoding="utf-8"))
        return rows[0]

    def test_a_codex_project_table_with_another_trust_is_never_added_twice(self):
        store = self.home / ".codex" / "config.toml"
        row = self.assert_left_alone(store, "[projects.'" + self.wt + "']\ntrust_level = \"untrusted\"\n", "codex", "codex")
        self.assertIn("exists", row["reason"])

    def test_a_grok_folder_table_with_another_trust_is_never_added_twice(self):
        store = self.home / ".grok" / "trusted_folders.toml"
        row = self.assert_left_alone(store, "[folders.'" + self.wt + "']\ntrusted = false\ndecided_at = 1\n", "grok", "grok")
        self.assertIn("exists", row["reason"])

    def test_a_trusted_table_is_left_byte_identical(self):
        store = self.home / ".codex" / "config.toml"
        self.assert_left_alone(store, "[projects.'" + self.wt + "']\ntrust_level = \"trusted\"\n", "codex", "codex")

    def test_an_appended_store_keeps_its_byte_order_mark_and_parses(self):
        import tomllib
        store = self.home / ".codex" / "config.toml"
        store.parent.mkdir(parents=True)
        store.write_bytes(b"\xef\xbb\xbfmodel = \"synthetic\"\n")
        [row] = [r for r in self.trust("codex") if r.get("key") == "projects"]
        self.assertTrue(row["written"], row)
        data = store.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        parsed = tomllib.loads(data.decode("utf-8-sig"))
        self.assertEqual(parsed["projects"][self.wt]["trust_level"], "trusted")


class TheThreadIndex(unittest.TestCase):
    def test_an_empty_index_is_unparseable_to_writers_and_never_rewritten(self):
        from convoy.index import index_path, record
        chome = Path(tempfile.mkdtemp(prefix="convoy-safety-chome-"))
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(chome)}):
            path = index_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
            row = record(Path(tempfile.mkdtemp(prefix="convoy-safety-root-")), "cvy_synthetic", "t")
            self.assertEqual(row["index_error"], "unparseable")
            self.assertEqual(path.read_bytes(), b"")

    def test_the_index_is_saved_by_an_atomic_replace(self):
        import convoy.index as index
        chome = Path(tempfile.mkdtemp(prefix="convoy-safety-chome-"))
        seen = []
        real = index.os.replace

        def replacing(src, dst):
            seen.append(Path(dst))
            return real(src, dst)

        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(chome)}), mock.patch.object(index.os, "replace", replacing):
            index.record(Path(tempfile.mkdtemp(prefix="convoy-safety-root-")), "cvy_synthetic", "t")
            self.assertEqual(seen, [index.index_path()])
            self.assertEqual(json.loads(index.index_path().read_text(encoding="utf-8"))[0]["convoy_id"], "cvy_synthetic")

    def test_an_unparseable_index_is_never_rewritten_and_the_card_says_so(self):
        from convoy.convoy import bind, ensure_id
        from convoy.index import index_path
        from convoy.start_card import build_start_card
        chome = Path(tempfile.mkdtemp(prefix="convoy-safety-chome-"))
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(chome)}):
            path = index_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('[{"convoy_id": "cvy_other", "root": "elsewhere"},', encoding="utf-8")
            before = path.read_bytes()
            root = Path(tempfile.mkdtemp(prefix="convoy-safety-root-"))
            ensure_id(root)
            bind(root, "synthetic-thread")
            self.assertEqual(path.read_bytes(), before, "every other thread's row is kept")
            card = build_start_card(root, neurons_fn=lambda r: {"neurons": []})
        self.assertEqual(card["index_error"], "unparseable")
        self.assertTrue(any("index" in n and "unparseable" in n for n in card["notes"]), card["notes"])


class TheVisibleFilesNote(RepoRoot):
    NOTE = "written and left visible to git: "

    def test_one_note_names_what_every_harness_left_visible(self):
        card = self.start(write_repo_files=True)
        notes = [n for n in card["start_card"]["notes"] if n.startswith(self.NOTE)]
        self.assertEqual(len(notes), 1, card["start_card"]["notes"])
        self.assertIn("AGENTS.md", notes[0])
        self.assertIn(".codex/hooks.json", notes[0])

    def test_the_note_is_on_the_attached_return_too(self):
        card = start(self.repo, str(self.repo), harnesses=["claude", "codex"], identify_fn=lambda r: {},
                     bodies_fn=lambda r: {"chairs": [{"live": True}]}, write_repo_files=True)
        self.assertTrue(card.get("attached"), card)
        notes = [n for n in card["start_card"]["notes"] if n.startswith(self.NOTE)]
        self.assertEqual(len(notes), 1, card["start_card"]["notes"])


class TheLiveHookWriters(unittest.TestCase):
    def test_a_live_first_run_never_replaces_an_unparseable_hook_file(self):
        home = Path(tempfile.mkdtemp(prefix="convoy-safety-home-"))
        wt = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
        broken = {wt / ".claude" / "settings.local.json": '{"permissions": {"allow": ["Read"]},}',
                  wt / ".codex" / "hooks.json": '{"hooks": {},}'}
        for path, text in broken.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}), \
                mock.patch("convoy.bringup.Path.home", return_value=home):
            card = ensure_first_run({"to": "claude", "worktree": str(wt)}, root=wt, live=True)
        for path, text in broken.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, str(path))
        self.assertIn("unparseable", json.dumps(card))


class TheHooks(unittest.TestCase):
    def test_hooks_land_in_the_local_settings_file(self):
        home = Path(tempfile.mkdtemp(prefix="convoy-safety-home-"))
        wt = Path(tempfile.mkdtemp(prefix="convoy-safety-wt-"))
        with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}), \
                mock.patch("convoy.bringup.Path.home", return_value=home):
            card = ensure_first_run({"to": "claude", "worktree": str(wt)}, root=wt, live=True)
        self.assertTrue(card["ok"], card)
        local = json.loads((wt / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        for event in ("UserPromptSubmit", "PreToolUse", "Stop"):
            self.assertIn(event, local["hooks"])
        self.assertNotIn("permissions", local)
        self.assertNotIn(HOME_KEY, local)
        self.assertFalse((wt / ".claude" / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
