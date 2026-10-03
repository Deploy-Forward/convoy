"""A launch writes every repo file only into a worktree Convoy minted.

`repo.mint_worktrees` writes `<worktree>/.convoy/minted.json` when it creates a worktree, and only
then. `repo.is_minted_worktree` is true for that marker inside a linked git worktree. Anywhere else
is the person's repo: a launch there writes only the files Convoy names and git excludes (the local
Claude settings, the root pointers, the Grok inbox hook, the convoy-end copies, the grok agent),
never `AGENTS.md` or `.codex/hooks.json` without `--write-repo-files`, and the card says a Codex
neuron there cannot receive until the person opts in. `terminals` is a listing and writes nothing.

Every repo is a scratch git repository in a temporary folder; the home and the Convoy home are
temporary folders; no harness is started.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import bring_up, ensure_first_run, terminals
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.lifecycle import join
from convoy.repo import mint_worktrees
from convoy.targeted_launch import launch_seat

CODEX_NOTE = "inbox hook not written: opt in with --write-repo-files"
PERSON_FILES = (".codex/hooks.json", "AGENTS.md")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _repo(prefix):
    repo = Path(tempfile.mkdtemp(prefix=prefix))
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "init")
    return repo


def _run(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = out.getvalue().strip()
    return rc, (json.loads(raw) if raw else None)


def _files(base):
    return {p.relative_to(base).as_posix() for p in Path(base).rglob("*") if p.is_file()}


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-marker-home-"))
        convoy_home = Path(tempfile.mkdtemp(prefix="convoy-marker-chome-"))
        env = mock.patch.dict(os.environ, {"USERPROFILE": str(self.home), "HOME": str(self.home),
                                           "CONVOY_HOME": str(convoy_home)})
        env.start()
        self.addCleanup(env.stop)

    def status(self, repo):
        """`git status` outside the thread's own `.convoy/` record."""
        lines = _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
        return [line[3:] for line in lines if not line[3:].startswith(".convoy/")]


class TheMarker(Sandbox):
    def test_a_worktree_the_mint_creates_carries_the_marker(self):
        from convoy.repo import is_minted_worktree
        main_repo = _repo("convoy-marker-main-")
        card = mint_worktrees(main_repo, 1, names=["neuron"])
        self.assertTrue(card["ok"], card)
        wt = Path(card["worktrees"][0]["path"])
        data = json.loads((wt / ".convoy" / "minted.json").read_text(encoding="utf-8"))
        self.assertEqual(data["minted_by"], "convoy")
        self.assertEqual(data["branch"], "convoy/neuron")
        self.assertEqual(Path(data["checkout"]), main_repo)
        self.assertTrue(data["minted_at"])
        self.assertTrue(is_minted_worktree(wt))
        self.assertEqual(self.status(wt), [])
        self.assertEqual(_git(wt, "status", "--porcelain", "--untracked-files=all"), "", "the marker is excluded")

    def test_a_folder_the_mint_reuses_gets_no_marker(self):
        from convoy.repo import is_minted_worktree
        main_repo = _repo("convoy-marker-main-")
        path = main_repo.parent / (main_repo.name + "-wt-neuron")
        _git(main_repo, "worktree", "add", "-q", "-b", "person/neuron", str(path))
        card = mint_worktrees(main_repo, 1, names=["neuron"])
        self.assertTrue(card["ok"], card)
        self.assertFalse(card["worktrees"][0]["created"])
        self.assertFalse((path / ".convoy" / "minted.json").exists())
        self.assertFalse(is_minted_worktree(path))

    def test_the_predicate_wants_a_parseable_marker_inside_a_linked_worktree(self):
        from convoy.repo import is_minted_worktree
        marker = {"minted_by": "convoy", "checkout": "x", "branch": "convoy/x", "minted_at": "2026-01-01T00:00:00Z"}

        def put(base, text):
            (base / ".convoy").mkdir(parents=True, exist_ok=True)
            (base / ".convoy" / "minted.json").write_text(text, encoding="utf-8")

        primary = _repo("convoy-marker-primary-")
        put(primary, json.dumps(marker))
        self.assertFalse(is_minted_worktree(primary), "a primary checkout is the person's repo")
        plain = Path(tempfile.mkdtemp(prefix="convoy-marker-plain-"))
        put(plain, json.dumps(marker))
        self.assertFalse(is_minted_worktree(plain), "a plain folder is not a worktree")
        main_repo = _repo("convoy-marker-main-")
        wt = Path(mint_worktrees(main_repo, 1, names=["neuron"])["worktrees"][0]["path"])
        written = json.loads((wt / ".convoy" / "minted.json").read_text(encoding="utf-8"))
        put(wt, "{not json")
        self.assertFalse(is_minted_worktree(wt), "an unparseable marker")
        put(wt, json.dumps({**written, "minted_by": "someone-else"}))
        self.assertFalse(is_minted_worktree(wt), "a marker Convoy did not write")
        put(wt, json.dumps(written))
        self.assertTrue(is_minted_worktree(wt))


class ARealRepo(Sandbox):
    """A seat on the thread root, which is often the person's own repo."""

    def setUp(self):
        super().setUp()
        self.repo = _repo("convoy-marker-repo-")
        ensure_id(self.repo)
        bind(self.repo, "demo")

    def test_a_first_run_writes_only_the_files_convoy_names(self):
        for to in ("claude", "codex", "grok"):
            card = ensure_first_run({"to": to, "worktree": str(self.repo)}, root=self.repo)
            self.assertTrue(card["ok"], card)
            for rel in PERSON_FILES:
                self.assertFalse((self.repo / rel).exists(), to + ": " + rel)
            self.assertTrue((self.repo / ".claude" / "settings.local.json").is_file(), to)
            self.assertTrue((self.repo / ".grok" / "hooks" / "convoy-inbox.json").is_file(), to)
            self.assertTrue((self.repo / ".codex" / "convoy-root").is_file(), to)
            self.assertEqual(sorted(card["would_write"]), list(PERSON_FILES), to)
            self.assertEqual(self.status(self.repo), [], to + ": every file written is excluded")

    def test_the_card_says_a_codex_neuron_cannot_receive_until_the_person_opts_in(self):
        codex = ensure_first_run({"to": "codex", "worktree": str(self.repo)}, root=self.repo)
        self.assertEqual(len([n for n in codex["notes"] if CODEX_NOTE in n]), 1, codex["notes"])
        claude = ensure_first_run({"to": "claude", "worktree": str(self.repo)}, root=self.repo)
        self.assertFalse(any(CODEX_NOTE in n for n in claude["notes"]), claude["notes"])

    def test_the_opt_in_writes_every_file(self):
        card = ensure_first_run({"to": "codex", "worktree": str(self.repo)}, root=self.repo, write_repo_files=True)
        self.assertTrue(card["ok"], card)
        for rel in PERSON_FILES:
            self.assertTrue((self.repo / rel).is_file(), rel)
        self.assertFalse(any(CODEX_NOTE in n for n in card.get("notes") or []))

    def test_bring_up_on_a_root_seat_leaves_git_status_clean_and_names_would_write(self):
        seat(self.repo, "codex", "sess-codex", worktree=str(self.repo), resume="sess-codex")
        card = bring_up(self.repo)
        [win] = card["windows"]
        for rel in PERSON_FILES:
            self.assertFalse((self.repo / rel).exists(), rel)
            self.assertIn(rel, win["first_run"]["would_write"])
        self.assertTrue(any(CODEX_NOTE in n for n in win["first_run"]["notes"]), win["first_run"])
        self.assertEqual(self.status(self.repo), [])

    def test_bring_up_with_the_opt_in_writes_every_file(self):
        seat(self.repo, "codex", "sess-codex", worktree=str(self.repo), resume="sess-codex")
        # A dry run writes nothing anywhere: the opt-in is refused, in the CLI's own words.
        for verb in ("bring-up", "open", "relaunch"):
            rc, card = _run(self.repo, verb, "--dry-run", "--write-repo-files")
            self.assertEqual(rc, 1, card)
            self.assertFalse(card["ok"], card)
            self.assertEqual(card["error"], "--write-repo-files needs a live run, not --dry-run: a dry " + verb +
                             " writes no person file")
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / ".convoy" / "repo-files.json").exists())
        self.assertEqual(self.status(self.repo), [])
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        with mock.patch("convoy.cli.live_runner", runner), \
                mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            rc, card = _run(self.repo, "bring-up", "--write-repo-files")
        self.assertEqual(rc, 0, card)
        self.assertEqual(runner.call_count, 1)
        self.assertTrue((self.repo / "AGENTS.md").is_file())

    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_launch_on_a_root_seat_leaves_git_status_clean(self, _which):
        join(self.repo, "codex", session_id="chair-root", worktree=str(self.repo))
        calls = []
        card = launch_seat(self.repo, "chair-root", runner=lambda argv: calls.append(argv) or {"ok": True, "pid": 7},
                           env={"WT_SESSION": "synthetic-window"}, which=lambda name: "C:\\Tools\\" + str(name),
                           platform_name="nt", trust_probe=lambda row: True, allow_unverified_launch=True)
        self.assertTrue(card["ok"], card)
        self.assertEqual(len(calls), 1)
        for rel in PERSON_FILES:
            self.assertFalse((self.repo / rel).exists(), rel)
        self.assertTrue(any(CODEX_NOTE in n for n in card["first_run"]["notes"]), card)
        self.assertEqual(self.status(self.repo), [])


class AMintedWorktree(Sandbox):
    def test_a_first_run_in_a_minted_worktree_writes_every_file(self):
        main_repo = _repo("convoy-marker-main-")
        wt = Path(mint_worktrees(main_repo, 1, names=["neuron"])["worktrees"][0]["path"])
        card = ensure_first_run({"to": "codex", "worktree": str(wt)}, root=wt)
        self.assertTrue(card["ok"], card)
        for rel in PERSON_FILES:
            self.assertTrue((wt / rel).is_file(), rel)
        self.assertEqual(card["would_write"], [])


class Terminals(Sandbox):
    def test_terminals_is_a_listing_and_writes_nothing(self):
        root = _repo("convoy-marker-root-")
        ensure_id(root)
        bind(root, "demo")
        wt = Path(tempfile.mkdtemp(prefix="convoy-marker-wt-"))
        for to in ("claude", "codex", "grok"):
            seat(root, to, "sess-" + to, worktree=str(wt / to), resume="sess-" + to)
            (wt / to).mkdir()
        before_root, before_home = _files(root), _files(self.home)
        card = terminals(root)
        self.assertEqual(len(card["windows"]), 3, card)
        self.assertEqual(_files(wt), set(), "no worktree file")
        self.assertEqual(_files(root), before_root, "no thread file")
        self.assertEqual(_files(self.home), before_home, "no home file")


class Skills(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = _repo("convoy-marker-repo-")
        ensure_id(self.repo)
        bind(self.repo, "demo")

    def test_skills_on_a_real_repo_writes_no_file_the_person_could_own(self):
        rc, card = _run(self.repo, "skills", "--worktree", str(self.repo))
        self.assertEqual(rc, 0, card)
        for rel in PERSON_FILES:
            self.assertFalse((self.repo / rel).exists(), rel)
        self.assertEqual(self.status(self.repo), [])

    def test_skills_with_the_opt_in_writes_every_file(self):
        rc, card = _run(self.repo, "skills", "--worktree", str(self.repo), "--write-repo-files")
        self.assertEqual(rc, 0, card)
        for rel in PERSON_FILES:
            self.assertTrue((self.repo / rel).is_file(), rel)

    def test_skills_in_a_minted_worktree_writes_every_file(self):
        main_repo = _repo("convoy-marker-main-")
        wt = Path(mint_worktrees(main_repo, 1, names=["neuron"])["worktrees"][0]["path"])
        rc, card = _run(self.repo, "skills", "--worktree", str(wt))
        self.assertEqual(rc, 0, card)
        for rel in PERSON_FILES:
            self.assertTrue((wt / rel).is_file(), rel)


MCP_NOTE = "inbox hook not written: opt in with write_repo_files=true"
ASK_NOTE = "ask the person to run convoy"
CODEX_EXE = "C:\\Tools\\codex.exe"


class AForgedMarker(Sandbox):
    """A marker copied out of a minted worktree makes nothing else minted."""

    def setUp(self):
        super().setUp()
        main_repo = _repo("convoy-marker-main-")
        self.minted = Path(mint_worktrees(main_repo, 1, names=["neuron"])["worktrees"][0]["path"])
        self.marker = (self.minted / ".convoy" / "minted.json").read_text(encoding="utf-8")

    def copy_marker(self, into):
        (Path(into) / ".convoy").mkdir(parents=True, exist_ok=True)
        (Path(into) / ".convoy" / "minted.json").write_text(self.marker, encoding="utf-8")

    def test_the_marker_records_the_worktree_and_the_checkouts_common_dir(self):
        data = json.loads(self.marker)
        self.assertEqual(Path(data["worktree"]).resolve(), self.minted.resolve())
        common = _git(self.minted, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        self.assertEqual(Path(data["common_dir"]).resolve(), Path(common).resolve())

    def test_another_repos_linked_worktree_is_refused(self):
        from convoy.repo import is_minted_worktree
        other = _repo("convoy-marker-other-")
        wt = other.parent / (other.name + "-wt-person")
        _git(other, "worktree", "add", "-q", "-b", "person/wt", str(wt))
        self.copy_marker(wt)
        self.assertFalse(is_minted_worktree(wt))

    def test_a_submodule_is_refused(self):
        from convoy.repo import is_minted_worktree
        sub = _repo("convoy-marker-sub-")
        sup = _repo("convoy-marker-super-")
        _git(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "child")
        self.assertTrue((sup / "child" / ".git").is_file())
        self.copy_marker(sup / "child")
        self.assertFalse(is_minted_worktree(sup / "child"))

    def test_a_junk_git_file_is_refused(self):
        from convoy.repo import is_minted_worktree
        junk = Path(tempfile.mkdtemp(prefix="convoy-marker-junk-"))
        (junk / ".git").write_text("gitdir: " + str(junk / "nowhere") + "\n", encoding="utf-8")
        self.copy_marker(junk)
        self.assertFalse(is_minted_worktree(junk))

    def test_a_worktree_its_checkout_no_longer_lists_is_refused(self):
        from convoy.repo import is_minted_worktree
        checkout = json.loads(self.marker)["checkout"]
        gitdir = (self.minted / ".git").read_text(encoding="utf-8")
        _git(checkout, "worktree", "remove", "--force", str(self.minted))
        self.minted.mkdir(parents=True)
        (self.minted / ".git").write_text(gitdir, encoding="utf-8")
        self.copy_marker(self.minted)
        self.assertFalse(is_minted_worktree(self.minted))


class TheCardReadsTheDisk(Sandbox):
    """The note and would_write say what is on disk, and an opt-in is remembered."""

    def setUp(self):
        super().setUp()
        self.repo = _repo("convoy-marker-repo-")
        ensure_id(self.repo)
        bind(self.repo, "demo")
        seat(self.repo, "codex", "chair", worktree=str(self.repo))
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def relaunch(self, **kw):
        from convoy.relaunch import relaunch
        with mock.patch("convoy.bringup.shutil.which", return_value=CODEX_EXE):
            return relaunch(self.repo, runner=self.runner, alive=lambda _pid: False, **kw)

    def notes(self, card):
        return [n for w in card["windows"] for n in (w.get("first_run") or {}).get("notes") or []]

    def test_a_relaunch_after_the_opt_in_has_no_false_note_and_refreshes_the_hooks(self):
        first = self.relaunch(write_repo_files=True)
        self.assertTrue(first["launched"], first)
        hooks = self.repo / ".codex" / "hooks.json"
        self.assertTrue(hooks.is_file())
        self.assertTrue((self.repo / ".convoy" / "repo-files.json").is_file(), "the opt-in is recorded")
        hooks.unlink()
        again = self.relaunch()
        self.assertTrue(again["launched"], again)
        self.assertTrue(hooks.is_file(), "the recorded opt-in refreshes hooks.json")
        self.assertFalse(any("inbox hook not written" in n for n in self.notes(again)), self.notes(again))
        [win] = again["windows"]
        self.assertEqual(win["first_run"]["would_write"], [])

    def test_a_hook_already_on_disk_is_not_reported_missing(self):
        from convoy.identity import ensure_codex_end_hook
        ensure_codex_end_hook(self.repo, root=self.repo)
        card = self.relaunch()
        self.assertFalse(any("inbox hook not written" in n for n in self.notes(card)), self.notes(card))
        [win] = card["windows"]
        self.assertNotIn(".codex/hooks.json", win["first_run"]["would_write"])
        self.assertIn("AGENTS.md", win["first_run"]["would_write"])


class ATrackedLocalSettingsFile(Sandbox):
    def test_a_tracked_settings_local_json_is_never_written(self):
        repo = _repo("convoy-marker-repo-")
        local = repo / ".claude" / "settings.local.json"
        local.parent.mkdir()
        local.write_text('{"person": 1}\n', encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "local")
        before = local.read_bytes()
        for opt_in in (None, True):
            card = ensure_first_run({"to": "claude", "worktree": str(repo)}, root=repo, write_repo_files=opt_in)
            self.assertEqual(local.read_bytes(), before, opt_in)
            self.assertIn(".claude/settings.local.json", card["would_write"], opt_in)
            self.assertTrue(any("settings.local.json" in n and "tracked" in n for n in card["notes"]), card["notes"])
        self.assertNotIn(".claude/settings.local.json", self.status(repo))


class TheCardNamesTheTrustStores(Sandbox):
    def test_every_home_trust_store_written_is_named(self):
        repo = _repo("convoy-marker-repo-")
        with mock.patch("convoy.bringup.is_temp_root", return_value=False):
            codex = ensure_first_run({"to": "codex", "worktree": str(repo)}, root=repo)
            claude = ensure_first_run({"to": "claude", "worktree": str(repo)}, root=repo)
        self.assertIn(str(self.home / ".codex" / "config.toml"), codex["trust_stores_written"])
        self.assertIn(str(self.home / ".claude.json"), claude["trust_stores_written"])


class EveryLaunchVerbOnARealRepo(Sandbox):
    """crew, relaunch, CLI join --launch and the MCP verbs leave the person's repo clean."""

    def setUp(self):
        super().setUp()
        self.repo = _repo("convoy-marker-repo-")
        ensure_id(self.repo)
        bind(self.repo, "demo")

    def assert_clean(self):
        for rel in PERSON_FILES:
            self.assertFalse((self.repo / rel).exists(), rel)
        self.assertEqual(self.status(self.repo), [])

    def pane(self):
        from convoy.targeted_launch import terminal_capability
        cap = terminal_capability(env={"WT_SESSION": "synthetic-window"}, which=lambda n: "C:\\Tools\\" + str(n),
                                  platform_name="nt")
        return mock.patch("convoy.targeted_launch.terminal_capability", return_value=cap)

    def test_crew_mints_and_leaves_the_root_clean(self):
        rc, card = _run(self.repo, "crew", "--seat", "codex,title=one")
        self.assertEqual(rc, 0, card)
        wt = Path(card["mint"]["worktrees"][0]["path"])
        self.assertTrue((wt / "AGENTS.md").is_file())
        self.assert_clean()

    def test_relaunch_on_a_root_seat(self):
        from convoy.relaunch import relaunch
        seat(self.repo, "codex", "chair", worktree=str(self.repo))
        with mock.patch("convoy.bringup.shutil.which", return_value=CODEX_EXE):
            card = relaunch(self.repo, runner=mock.Mock(return_value={"ok": True, "pid": 1}), alive=lambda _p: False)
        self.assertTrue(card["launched"], card)
        self.assert_clean()

    def test_cli_join_launch_on_a_root_seat(self):
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        with self.pane(), mock.patch("convoy.cli.active_pane_runner", runner), \
                mock.patch("convoy.bringup.shutil.which", return_value=CODEX_EXE):
            rc, card = _run(self.repo, "join", "--to", "codex", "--worktree", str(self.repo), "--launch")
        self.assertEqual(rc, 0, card)
        self.assertEqual(runner.call_count, 1)
        self.assertTrue(any(CODEX_NOTE in n for n in card["launch"]["first_run"]["notes"]), card)
        self.assert_clean()

    def mcp(self, name, args, gated):
        from convoy.mcp_http import call_tool
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1" if gated else ""}):
            return call_tool(self.repo, name, args)

    def test_mcp_bring_up_names_the_route_that_works_on_its_surface(self):
        seat(self.repo, "codex", "chair", worktree=str(self.repo), resume="chair")
        gated = self.mcp("bring_up", {}, gated=True)
        self.assertTrue(any(MCP_NOTE in n for w in gated["windows"] for n in w["first_run"]["notes"]), gated)
        public = self.mcp("bring_up", {}, gated=False)
        self.assertTrue(any(ASK_NOTE in n for w in public["windows"] for n in w["first_run"]["notes"]), public)
        self.assert_clean()

    def test_mcp_write_repo_files_is_a_strict_boolean_behind_the_write_gate(self):
        seat(self.repo, "codex", "chair", worktree=str(self.repo), resume="chair")
        self.assertFalse(self.mcp("bring_up", {"write_repo_files": "yes"}, gated=True)["ok"])
        refused = self.mcp("bring_up", {"write_repo_files": True}, gated=False)
        self.assertFalse(refused["ok"], refused)
        self.assert_clean()
        # A dry call (the default) never writes a person file or records an opt-in.
        for name in ("bring_up", "open"):
            card = self.mcp(name, {"write_repo_files": True}, gated=True)
            self.assertFalse(card["ok"], card)
            self.assertEqual(card["error"], "write_repo_files=true needs dry_run=false: a dry " + name +
                             " writes no person file")
        self.assert_clean()
        self.assertFalse((self.repo / ".convoy" / "repo-files.json").exists())

    def test_mcp_launch_and_crew_on_a_real_repo(self):
        join(self.repo, "codex", session_id="chair-root", worktree=str(self.repo))
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        with self.pane(), mock.patch("convoy.mcp_http.active_pane_runner", runner), \
                mock.patch("convoy.bringup.shutil.which", return_value=CODEX_EXE):
            card = self.mcp("launch", {"seat": "chair-root"}, gated=True)
        self.assertTrue(card["ok"], card)
        self.assertTrue(any(MCP_NOTE in n for n in card["first_run"]["notes"]), card)
        self.assert_clean()
        crew_card = self.mcp("crew", {"seats": [{"harness": "codex", "title": "two"}]}, gated=True)
        self.assertTrue(crew_card["ok"], crew_card)
        self.assert_clean()
        self.assertFalse(self.mcp("crew", {"seats": [{"harness": "codex", "title": "three"}],
                                           "write_repo_files": 1}, gated=True)["ok"])


class TheOptInRecord(Sandbox):
    """.convoy/repo-files.json is the person's opt-in for one folder: kept out of git, bound to
    that folder, and withdrawn with --no-write-repo-files."""

    def setUp(self):
        super().setUp()
        self.root = _repo("convoy-marker-root-")
        ensure_id(self.root)
        bind(self.root, "demo")
        # A seat worktree that was never bound or minted: /.convoy/ is not in its info/exclude.
        self.wt = _repo("convoy-marker-seat-")

    def test_the_command_the_ask_note_gives_leaves_git_status_clean(self):
        card = ensure_first_run({"to": "codex", "worktree": str(self.wt)}, root=self.root, opt_in_route="ask")
        [note] = [n for n in card["notes"] if ASK_NOTE in n]
        command = note.split("ask the person to run ", 1)[1].split()
        self.assertEqual(command[:3], ["convoy", "--root", str(self.root)])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(command[1:])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertTrue((self.wt / ".codex" / "hooks.json").is_file())
        self.assertTrue((self.wt / ".convoy" / "repo-files.json").is_file())
        self.assertNotIn(".convoy/repo-files.json", self.status(self.wt))
        self.assertEqual(_git(self.wt, "status", "--porcelain", "--untracked-files=all", "--", ".convoy"), "")

    def test_a_record_copied_into_another_folder_is_refused(self):
        ensure_first_run({"to": "codex", "worktree": str(self.wt)}, root=self.root, write_repo_files=True)
        record = (self.wt / ".convoy" / "repo-files.json").read_text(encoding="utf-8")
        other = _repo("convoy-marker-other-")
        plain = Path(tempfile.mkdtemp(prefix="convoy-marker-plain-"))
        for into in (other, plain):
            (into / ".convoy").mkdir()
            (into / ".convoy" / "repo-files.json").write_text(record, encoding="utf-8")
            card = ensure_first_run({"to": "codex", "worktree": str(into)}, root=self.root)
            for rel in PERSON_FILES:
                self.assertFalse((into / rel).exists(), str(into) + ": " + rel)
            self.assertTrue(any(CODEX_NOTE in n for n in card["notes"]), card["notes"])

    def test_the_opt_in_is_withdrawn_with_no_write_repo_files(self):
        rc, _ = _run(self.root, "skills", "--worktree", str(self.wt), "--write-repo-files")
        self.assertEqual(rc, 0)
        rc, card = _run(self.root, "skills", "--worktree", str(self.wt), "--no-write-repo-files")
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["withdrawn"], card)
        self.assertFalse((self.wt / ".convoy" / "repo-files.json").exists())
        (self.wt / ".codex" / "hooks.json").unlink()
        card = ensure_first_run({"to": "codex", "worktree": str(self.wt)}, root=self.root)
        self.assertFalse((self.wt / ".codex" / "hooks.json").exists(), "a withdrawn opt-in writes no person file")
        self.assertTrue(any(CODEX_NOTE in n for n in card["notes"]), card["notes"])

    def test_both_flags_at_once_are_refused(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _run(self.root, "skills", "--worktree", str(self.wt), "--write-repo-files", "--no-write-repo-files")


class TheWidget(Sandbox):
    def test_the_widget_crew_start_asks_the_person_to_opt_in(self):
        import convoy.onboard as onboard_module
        from convoy.widget_web import WidgetApi
        root = _repo("convoy-marker-root-")
        ensure_id(root)
        bind(root, "demo")
        # The person's own worktree at the path the mint would use: reused, so not minted.
        reused = root.parent / (root.name + "-wt-w")
        _git(root, "worktree", "add", "-q", "-b", "person/w", str(reused))
        api = WidgetApi([root], probe_fn=lambda h: {}, refresh_s=3600)
        with mock.patch.object(onboard_module, "probe", return_value={}), \
                mock.patch.object(onboard_module, "_which", side_effect=lambda h: "C:/synthetic/" + h):
            out = api.start(None, ["codex"], "demo", False, [{"harness": "codex", "title": "w"}], False)
        self.assertTrue(out.get("crew"), out)
        self.assertIn("windows", out["crew"], out["crew"])
        notes = [n for w in out["crew"]["windows"] for n in (w.get("first_run") or {}).get("notes") or []]
        self.assertTrue(any(ASK_NOTE in n for n in notes), out["crew"])
        self.assertFalse(any("--write-repo-files" in n and ASK_NOTE not in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
