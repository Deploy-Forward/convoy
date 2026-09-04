"""The repository step is executable, not prose. The wizard's 'GitHub? -> which
repository -> selected repository' walk (convoy-wizard/SKILL.md steps 1-2)
had no code behind it (reader 1, 2026-09-04): nothing listed repos, onboard
rejected the URL its own prose promised, and no one ran `git worktree add`,
so N>1 neurons dead-ended on C8 with the human hand-making worktrees.

Three guarantees:

1. Every shell call goes through an injected runner, so this suite never
   reaches GitHub. A missing `gh` is ok=false with an install hint, never a
   guessed list; a non-zero exit carries git's/gh's own words, never a guess.
2. The worktree is DERIVED from the checkout, one per seat, a sibling named
   the way this very checkout is (convoy-wt-fable): the caller does not
   supply it. Proven with real, local, fast git.
3. On the wire, `repos` runs `gh repo list` as whoever is logged in on the
   MCP HOST - the conductor's inventory, private names included - so it is
   gated with `clone`, `mint` and `onboard` (review 2026-09-04: a public
   deploy could only disclose the operator's repos and spend their quota).
   All four are HIDDEN from a public tools/list, not listed-and-refusing.
   The cloned repo never gets .convoy/ or thread.md as tracked files: clone
   writes them into .git/info/exclude.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import read_github, read_id, read_thread
from convoy.mcp_http import _WRITE_TOOLS, TOOLS, make_server
from convoy.onboard import onboard
from convoy.repo import checkout_path_for, clone, is_repo_url, list_repos, mint_worktrees

ROOT = Path(__file__).resolve().parents[2]
FAKES = (ROOT / "test" / "fakes").resolve()
LIST_ARGV = ["gh", "repo", "list", "--json", "nameWithOwner,url,isPrivate,updatedAt", "--limit", "30"]
GH_ROWS = [
    {"nameWithOwner": "acme/api", "url": "https://github.com/acme/api", "isPrivate": True,
     "updatedAt": "2026-09-01T10:00:00Z"},
    {"nameWithOwner": "acme/site", "url": "https://github.com/acme/site", "isPrivate": False,
     "updatedAt": "2026-08-30T09:00:00Z"},
]


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    """A real local repo with one commit. Fast; no remote."""
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _norm(p) -> str:
    return os.path.normcase(str(Path(p).resolve()))


class Recorder:
    """An injected runner: records argv, answers with a scripted result."""

    def __init__(self, returncode=0, stdout="", stderr="", side_effect=None):
        self.calls: list[tuple[list[str], str | None]] = []
        self.returncode, self.stdout, self.stderr, self.side_effect = returncode, stdout, stderr, side_effect

    def __call__(self, argv, cwd=None, **_k):
        self.calls.append((list(argv), cwd))
        if self.side_effect is not None:
            self.side_effect(argv)
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


class ListRepos(unittest.TestCase):
    def test_fake_runner_rows_are_name_url_private_updated_and_nothing_else(self):
        runner = Recorder(stdout=json.dumps(GH_ROWS))
        card = list_repos(runner=runner)
        self.assertEqual(runner.calls, [(LIST_ARGV, None)])
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["gh_present"])
        self.assertEqual(card["count"], 2)
        self.assertEqual(card["repos"], [
            {"name": "acme/api", "url": "https://github.com/acme/api", "private": True, "updated_at": "2026-09-01T10:00:00Z"},
            {"name": "acme/site", "url": "https://github.com/acme/site", "private": False, "updated_at": "2026-08-30T09:00:00Z"},
        ])
        self.assertNotIn("token", json.dumps(card).lower())

    def test_missing_gh_is_ok_false_with_an_install_hint_never_a_guess(self):
        def boom(_argv):
            raise FileNotFoundError("gh")
        card = list_repos(runner=Recorder(side_effect=boom))
        self.assertFalse(card["ok"])
        self.assertFalse(card["gh_present"])
        self.assertIsNone(card["repos"])
        self.assertIn("cli.github.com", card["hint"])
        self.assertIn("gh", card["error"])

    def test_nonzero_exit_carries_gh_words_and_no_rows(self):
        stderr = "To get started with GitHub CLI, please run:  gh auth login"
        card = list_repos(runner=Recorder(returncode=4, stderr=stderr))
        self.assertFalse(card["ok"])
        self.assertTrue(card["gh_present"])
        self.assertIsNone(card["repos"])
        self.assertIn("gh auth login", card["error"])

    def test_limit_reaches_argv(self):
        runner = Recorder(stdout="[]")
        card = list_repos(runner=runner, limit=5)
        self.assertEqual(runner.calls[0][0][-2:], ["--limit", "5"])
        self.assertEqual(card["repos"], [])


class Clone(unittest.TestCase):
    def test_clone_is_one_git_clone_with_url_and_dest(self):
        dest = Path(tempfile.mkdtemp()) / "acme" / "api"
        runner = Recorder(side_effect=lambda argv: (dest / ".git" / "info").mkdir(parents=True))
        card = clone("https://github.com/acme/api.git", dest, runner=runner)
        # `--` ends git's option parsing: the url is a positional, never a flag
        self.assertEqual(runner.calls, [(["git", "clone", "--", "https://github.com/acme/api.git", str(dest)], None)])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["url"], "https://github.com/acme/api.git")
        self.assertEqual(_norm(card["dest"]), _norm(dest))
        self.assertTrue(card["cloned"])

    def test_an_option_shaped_url_is_refused_before_git_runs(self):
        # review 2026-09-04: '--upload-pack=calc x://h/o/r' has '://' so it
        # read as a URL, and without '--' git parsed it as the upload-pack
        # option. Convoy refuses it as a url at all, and clone refuses it too.
        evil = "--upload-pack=calc x://h/o/r"
        self.assertFalse(is_repo_url(evil))
        self.assertTrue(is_repo_url("https://github.com/acme/api.git"))
        runner = Recorder()
        card = clone(evil, Path(tempfile.mkdtemp()) / "x", runner=runner)
        self.assertFalse(card["ok"])
        self.assertFalse(card["cloned"])
        self.assertEqual(runner.calls, [], "a refusal never spawns")
        self.assertIn("-", card["error"])
        with self.assertRaises(ValueError):
            checkout_path_for(evil)

    def test_clone_refuses_a_nonempty_dest_without_running_git(self):
        dest = Path(tempfile.mkdtemp())
        (dest / "keep.txt").write_text("x", encoding="utf-8")
        runner = Recorder()
        card = clone("https://github.com/acme/api.git", dest, runner=runner)
        self.assertFalse(card["ok"])
        self.assertEqual(runner.calls, [])
        self.assertIn("not empty", card["error"])

    def test_git_failure_is_git_words_not_a_guess(self):
        dest = Path(tempfile.mkdtemp()) / "x"
        card = clone("https://github.com/acme/api.git", dest, runner=Recorder(returncode=128, stderr="fatal: repository not found"))
        self.assertFalse(card["ok"])
        self.assertIn("repository not found", card["error"])
        self.assertFalse(card["cloned"])

    def test_real_local_clone_keeps_convoy_files_out_of_the_repo(self):
        # git clone of a LOCAL path: no network, and the exclude rule is proven
        # by git status itself, not by reading the file back.
        src = _git_repo()
        dest = Path(tempfile.mkdtemp()) / "acme" / "api"
        card = clone(str(src), dest)
        self.assertTrue(card["ok"], card)
        self.assertTrue((dest / ".git").is_dir())
        (dest / ".convoy").mkdir()
        (dest / ".convoy" / "id").write_text("cvy_x\n", encoding="utf-8")
        (dest / "thread.md").write_text("cvy_x\ndemo\n", encoding="utf-8")
        status = _git("status", "--porcelain", cwd=dest).stdout
        self.assertEqual(status.strip(), "", status)

    def test_checkout_path_is_owner_repo_under_the_convoy_home(self):
        home = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(home)}):
            for url in ("https://github.com/acme/api.git", "https://github.com/acme/api", "git@github.com:acme/api.git"):
                self.assertEqual(_norm(checkout_path_for(url)), _norm(home / "checkouts" / "acme" / "api"), url)
            with self.assertRaises(ValueError):
                checkout_path_for("https://github.com/acme")
            with self.assertRaises(ValueError):
                checkout_path_for("https://github.com/../etc/passwd")


class MintWorktrees(unittest.TestCase):
    def test_three_seats_get_three_sibling_worktrees_git_reports(self):
        checkout = _git_repo()
        card = mint_worktrees(checkout, 3)
        self.assertTrue(card["ok"], card)
        rows = card["worktrees"]
        self.assertEqual(len(rows), 3)
        paths = {_norm(r["path"]) for r in rows}
        self.assertEqual(len(paths), 3)
        for r in rows:
            p = Path(r["path"])
            self.assertTrue(p.is_dir(), r)
            self.assertEqual(p.parent.resolve(), checkout.resolve().parent, "a worktree is a SIBLING of the checkout")
            self.assertTrue(p.name.startswith(checkout.name + "-wt-"), p.name)
            self.assertEqual(r["branch"], "convoy/" + r["name"])
            self.assertTrue(r["created"])
        listed = _git("worktree", "list", "--porcelain", cwd=checkout).stdout
        reported = {_norm(l.removeprefix("worktree ")) for l in listed.splitlines() if l.startswith("worktree ")}
        self.assertTrue(paths <= reported, (paths, reported))

    def test_names_are_the_seat_names_and_must_match_n(self):
        checkout = _git_repo()
        card = mint_worktrees(checkout, 2, names=["grok", "claude"])
        self.assertTrue(card["ok"], card)
        self.assertEqual([r["name"] for r in card["worktrees"]], ["grok", "claude"])
        self.assertEqual([Path(r["path"]).name for r in card["worktrees"]],
                         [checkout.name + "-wt-grok", checkout.name + "-wt-claude"])
        runner = Recorder()
        bad = mint_worktrees(checkout, 3, names=["a", "b"], runner=runner)
        self.assertFalse(bad["ok"])
        self.assertEqual(runner.calls, [])

    def test_git_failure_stops_and_reports_what_was_minted(self):
        checkout = _git_repo()
        calls = []

        def runner(argv, cwd=None, **_k):
            calls.append(argv)
            if len(calls) == 2:
                return subprocess.CompletedProcess(argv, 128, "", "fatal: a branch named 'convoy/neuron-2' already exists")
            return subprocess.CompletedProcess(argv, 0, "", "")
        card = mint_worktrees(checkout, 3, runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("already exists", card["error"])
        self.assertEqual(len(card["worktrees"]), 1)
        self.assertEqual(len(calls), 2, "stop at the first failure")
        self.assertEqual(calls[0][:5], ["git", "-C", str(checkout), "worktree", "add"])

    def test_not_a_git_checkout_is_refused_before_git_runs(self):
        runner = Recorder()
        card = mint_worktrees(Path(tempfile.mkdtemp()), 1, runner=runner)
        self.assertFalse(card["ok"])
        self.assertEqual(runner.calls, [])

    def test_a_name_that_leaves_the_sibling_convention_or_an_absurd_n_is_refused_by_convoy_not_git(self):
        # review 2026-09-04: names=['../../escape'] derived a path outside the
        # checkout's parent and a ref git happened to refuse. Convoy refuses
        # first, before any git runs, and caps n.
        checkout = _git_repo()
        runner = Recorder()
        for bad in (["../../escape"], ["a b"], [""], ["x/y"]):
            card = mint_worktrees(checkout, len(bad), names=bad, runner=runner)
            self.assertFalse(card["ok"], bad)
            self.assertIn("name", card["error"], bad)
        card = mint_worktrees(checkout, 10 ** 6, runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("n", card["error"])
        self.assertEqual(runner.calls, [], "a refusal never spawns")
        ok = mint_worktrees(checkout, 2, names=["grok-1", "claude.v2_x"], runner=Recorder())
        self.assertTrue(ok["ok"], ok)


class OnboardRepository(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        for target, kw in (("convoy.bringup.Path.home", {"return_value": Path(tempfile.mkdtemp())}),):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home), "PATH": str(FAKES)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_a_url_is_cloned_into_the_convoy_checkout_root_and_bound_with_github_yes(self):
        url = "https://github.com/acme/api.git"
        expected = self.home / "checkouts" / "acme" / "api"
        runner = Recorder(side_effect=lambda argv: (Path(argv[-1]) / ".git" / "info").mkdir(parents=True))
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=url, clone_runner=runner)
        self.assertTrue(card["ok"], card)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0][:4], ["git", "clone", "--", url])
        self.assertEqual(_norm(runner.calls[0][0][4]), _norm(expected))
        self.assertEqual(_norm(card["root"]), _norm(expected))
        self.assertEqual(read_thread(expected), "demo")
        self.assertEqual(read_id(expected), card["convoy_id"])
        self.assertEqual(card["github"], "yes")
        self.assertEqual(read_github(expected), "yes")
        self.assertEqual(card["repo"]["url"], url)
        self.assertTrue(card["repo"]["cloned"])

    def test_a_second_onboard_on_the_same_url_reuses_the_checkout(self):
        url = "https://github.com/acme/api.git"
        runner = Recorder(side_effect=lambda argv: (Path(argv[-1]) / ".git" / "info").mkdir(parents=True))
        onboard(self.root, ["grok"], thread="demo", checkout_root=url, clone_runner=runner)
        again = Recorder()
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=url, clone_runner=again)
        self.assertTrue(card["ok"], card)
        self.assertEqual(again.calls, [], "an existing checkout is reused, not re-cloned")
        self.assertFalse(card["repo"]["cloned"])
        self.assertEqual(card["thread"], "demo")

    def test_a_failed_clone_binds_nothing(self):
        url = "https://github.com/acme/api.git"
        runner = Recorder(returncode=128, stderr="fatal: repository not found")
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=url, clone_runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("repository not found", card["error"])
        self.assertFalse((self.home / "checkouts" / "acme" / "api" / ".convoy").exists())

    def test_a_refused_bind_records_no_github_answer(self):
        # review 2026-09-04: set_github ran before the bind_status check, so a
        # REFUSED onboard (checkout bound to another thread) still wrote
        # .convoy/github onto that other thread's root. A refusal never mutates.
        local = Path(tempfile.mkdtemp())
        first = onboard(self.root, ["grok"], thread="other-thread", checkout_root=str(local))
        self.assertTrue(first["ok"], first)
        self.assertIsNone(read_github(local))
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=str(local), github=True)
        self.assertFalse(card["ok"])
        self.assertIn("already bound to other-thread", card["error"])
        self.assertIsNone(read_github(local), "a refused onboard wrote the GitHub answer")
        self.assertEqual(read_thread(local), "other-thread")
        # the same refusal through a URL whose checkout already exists and is bound elsewhere
        url = "https://github.com/acme/api.git"
        runner = Recorder(side_effect=lambda argv: (Path(argv[-1]) / ".git" / "info").mkdir(parents=True))
        expected = self.home / "checkouts" / "acme" / "api"
        self.assertTrue(onboard(self.root, ["grok"], thread="other-thread", checkout_root=url, clone_runner=runner)["ok"])
        (expected / ".convoy" / "github").unlink()
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=url, clone_runner=Recorder())
        self.assertFalse(card["ok"])
        self.assertIsNone(read_github(expected), "a refused onboard wrote the GitHub answer")

    def test_github_no_is_recorded_on_a_local_checkout_and_unknown_stays_null(self):
        local = Path(tempfile.mkdtemp())
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=str(local))
        self.assertTrue(card["ok"], card)
        self.assertIsNone(card["github"], "never asked, never invented")
        self.assertIsNone(read_github(local))
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=str(local), github=False)
        self.assertEqual(card["github"], "no")
        self.assertEqual(read_github(local), "no")
        # a later call that does not mention github keeps the recorded answer
        card = onboard(self.root, ["grok"], thread="demo", checkout_root=str(local))
        self.assertEqual(card["github"], "no")

    def test_cli_records_github(self):
        local = Path(tempfile.mkdtemp())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), "onboard", "--to", "grok", "--thread", "demo",
                       "--checkout-root", str(local), "--github", "yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["github"], "yes")
        self.assertEqual(read_github(local), "yes")


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class RepoWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "", "CONVOY_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)
        # the wire has no runner argument; the module's real runner is the seam
        self.run_argv = mock.patch("convoy.repo.run_argv", Recorder(stdout=json.dumps(GH_ROWS)))
        self.run_argv.start()
        self.addCleanup(self.run_argv.stop)

    def _call(self, name, **arguments):
        r = _rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments})["result"]
        return r["structuredContent"]

    def _names(self):
        return {t["name"] for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}

    def test_public_list_hides_repos_clone_mint_onboard(self):
        names = self._names()
        for hidden in ("repos", "clone", "mint", "onboard"):
            self.assertNotIn(hidden, names, hidden + " runs gh/git as the host or binds the thread: hidden, not listed-and-refusing")
            self.assertIn(hidden, _WRITE_TOOLS)
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        gated = self._names()
        for name in ("repos", "clone", "mint", "onboard"):
            self.assertIn(name, gated)
        self.assertEqual({t["name"] for t in TOOLS}, gated)

    def test_repos_answers_gated_with_names_and_no_token_and_says_whose_account(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        card = self._call("repos")
        self.assertTrue(card["ok"], card)
        self.assertEqual([r["name"] for r in card["repos"]], ["acme/api", "acme/site"])
        self.assertNotIn("token", json.dumps(card).lower())
        desc = next(t["description"] for t in TOOLS if t["name"] == "repos")
        self.assertNotIn("the user's", desc, "on the wire gh is the MCP host's login, not the caller's")
        self.assertIn("host", desc)

    def test_public_repos_clone_and_mint_refuse_before_gh_or_git_runs(self):
        runner = Recorder()
        with mock.patch("convoy.repo.run_argv", runner):
            for name, args in (("repos", {}),
                               ("clone", {"url": "https://github.com/acme/api.git"}),
                               ("mint", {"checkout": str(self.root), "n": 2})):
                card = self._call(name, **args)
                self.assertFalse(card["ok"], (name, card))
                self.assertIn("CONVOY_MCP_WRITE_TOOLS", card["error"], name)
                self.assertNotIn("acme", json.dumps(card), name)
            refused = self._call("repos")
            self.assertIsNone(refused.get("repos"), "a refused repos never carries rows, not even []")
            self.assertIsNone(refused.get("count"), "a refused repos never counts, not even 0")
        self.assertEqual(runner.calls, [], "a refusal never spawns")

    def test_gated_clone_refuses_an_option_shaped_url_without_spawning(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        runner = Recorder()
        with mock.patch("convoy.repo.run_argv", runner):
            card = self._call("clone", url="--upload-pack=calc x://h/o/r")
        self.assertFalse(card["ok"], card)
        self.assertFalse(card["cloned"])
        self.assertEqual(runner.calls, [])

    def test_gated_clone_lands_under_the_convoy_home_and_mint_derives_worktrees(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        expected = self.home / "checkouts" / "acme" / "api"
        runner = Recorder(side_effect=lambda argv: (Path(argv[-1]) / ".git" / "info").mkdir(parents=True))
        with mock.patch("convoy.repo.run_argv", runner):
            card = self._call("clone", url="https://github.com/acme/api.git")
        self.assertTrue(card["ok"], card)
        self.assertEqual(_norm(card["dest"]), _norm(expected))
        self.assertEqual(runner.calls[0][0][:2], ["git", "clone"])
        # mint on a REAL checkout with the real runner: two derived siblings
        checkout = _git_repo()
        self.run_argv.stop()
        try:
            card = self._call("mint", checkout=str(checkout), n=2, names=["grok", "claude"])
        finally:
            self.run_argv.start()
        self.assertTrue(card["ok"], card)
        self.assertEqual([Path(r["path"]).name for r in card["worktrees"]],
                         [checkout.name + "-wt-grok", checkout.name + "-wt-claude"])
        self.assertNotIn("token", json.dumps(card).lower())


if __name__ == "__main__":
    unittest.main()
