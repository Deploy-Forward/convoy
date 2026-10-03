"""Behavioral regressions for project discovery and bounded, non-clobbering refresh."""
import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test.demo.start_resolve_test import StartResolve


class ResolveEdges(StartResolve):
    # Do not inherit the earlier contracts a second time in discovery.
    def config(self, root, url):
        (root / ".git").mkdir(parents=True, exist_ok=True)
        (root / ".git" / "config").write_text('[remote "origin"]\n url = ' + url + '\n', encoding="utf-8")

    def test_300_repositories_resolve_with_file_reads_within_budget(self):
        self.config(self.local, "https://github.com/synthetic-owner/synthetic-project.git")
        for i in range(300):
            self.config(self.base / ("repo-%03d" % i), "https://github.com/synthetic-owner/repo-%03d.git" % i)
        def no_remote_process(argv, cwd=None, **kw):
            if argv[1:3] == ["remote", "-v"]:
                return subprocess.CompletedProcess(argv, 1, "", "must read config")
            return self.tools.git(argv, cwd, **kw)
        from convoy.project_resolve import resolve_target
        began = time.monotonic()
        r = resolve_target("synthetic-owner/repo-299", search_roots=[self.base],
                           git_runner=no_remote_process, gh_runner=self.tools.gh, scan_budget=5)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checkout"], str((self.base / "repo-299").resolve()))
        self.assertLess(time.monotonic() - began, 5)
        self.assertLessEqual(sum(c[0][1] == "log" for c in self.tools.calls), 1)

    def test_found_match_exposes_unrelated_read_failure_without_auto_resolution(self):
        self.config(self.local, "https://github.com/synthetic-owner/synthetic-project.git")
        broken = self.base / "broken"
        (broken / ".git").mkdir(parents=True)
        def runner(argv, cwd=None, **kw):
            if Path(cwd) == broken:
                raise subprocess.TimeoutExpired(argv, .01)
            return self.tools.git(argv, cwd, **kw)
        from convoy.project_resolve import resolve_target
        r = resolve_target("synthetic-owner/synthetic-project", search_roots=[self.base], git_runner=runner)
        self.assertFalse(r["ok"], r)
        self.assertIn("incomplete", json.dumps(r).lower())

    def test_per_repo_time_budget_is_bounded(self):
        self.config(self.local, "https://github.com/synthetic-owner/synthetic-project.git")
        fallback = self.base / "fallback"
        self.config(fallback, "https://github.com/synthetic-owner/unrelated.git")
        with (fallback / ".git" / "config").open("a") as f:
            f.write('[includeIf "gitdir:*"]\n path = included\n')
        def runner(argv, cwd=None, **kw):
            if Path(cwd) == fallback:
                self.assertLessEqual(kw["timeout"], .5)
                raise subprocess.TimeoutExpired(argv, kw["timeout"])
            return self.tools.git(argv, cwd, **kw)
        from convoy.project_resolve import resolve_target
        self.assertEqual(resolve_target("synthetic-owner/synthetic-project", search_roots=[self.base], git_runner=runner).get("ask"), "pick")

    def test_worktree_config_and_include_fallback(self):
        from convoy.project_resolve import _remotes
        common = self.base / "common"
        common.mkdir()
        (common / "config").write_text('[remote "origin"]\n url = https://github.com/synthetic-owner/worktree.GIT\n')
        admin = common / "worktrees" / "one"
        admin.mkdir(parents=True)
        (admin / "commondir").write_text("../..")
        tree = self.base / "worktree"
        tree.mkdir()
        (tree / ".git").write_text("gitdir: " + str(admin))
        self.assertEqual(_remotes(tree, self.tools.git), ["github.com/synthetic-owner/worktree"])
        self.assertFalse(self.tools.calls)
        (common / "config").write_text('[includeIf "gitdir:*"]\n path = included\n')
        self.tools.remotes[str(tree)] = "origin https://github.com/synthetic-owner/included.git (fetch)"
        self.assertEqual(_remotes(tree, self.tools.git), ["github.com/synthetic-owner/included"])
        self.assertEqual(self.tools.calls[-1][0], ["git", "remote", "-v"])

    def test_offline_auth_hint_is_unknown_never_new(self):
        def offline(argv, cwd=None, **kw):
            return subprocess.CompletedProcess(argv, 1, "", "Failed to log in; To re-authenticate, run: gh auth login -h github.com")
        from convoy.project_resolve import resolve_target
        r = resolve_target("unknown", search_roots=[self.base], git_runner=self.tools.git, gh_runner=offline)
        self.assertEqual(r["ask"], "unknown", r)
        self.assertIn("github unknown:", r["error"].lower())
        self.assertNotIn("choices", r)

    def test_offline_exact_local_match_still_resolves_without_refresh(self):
        self.tools.gh_state = "offline"
        r = self.resolve("synthetic-project")
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["refresh"])
        self.assertIn("github unknown:", r["note"].lower())

    def test_authenticated_api_failure_is_not_an_auth_decision(self):
        def gh(argv, cwd=None, **kw):
            if argv[1:3] == ["auth", "status"]:
                self.assertLessEqual(kw["timeout"], 5)
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "not logged; gh auth login")
        from convoy.project_resolve import resolve_target
        r = resolve_target("unknown", search_roots=[self.base], git_runner=self.tools.git, gh_runner=gh)
        self.assertEqual(r["ask"], "unknown")
        self.assertIn("github unknown:", r["error"].lower())

    def test_substring_or_punctuation_only_match_always_asks_pick(self):
        for name in ("project", "synthetic project"):
            with self.subTest(name=name):
                r = self.resolve(name)
                self.assertEqual(r.get("ask"), "pick", r)
                self.assertFalse(r["ok"])
        self.tools.repos = ["synthetic-owner/rapid-capital"]
        self.assertEqual(self.resolve("api").get("ask"), "pick")

    def test_exact_case_insensitive_match_is_allowed(self):
        self.assertTrue(self.resolve("SYNTHETIC-PROJECT")["ok"])

    def test_ignored_or_untracked_incoming_file_is_never_overwritten(self):
        for ignored in (False, True):
            with self.subTest(ignored=ignored):
                def git(argv, cwd=None, **kw):
                    if argv[1] == "diff":
                        return subprocess.CompletedProcess(argv, 0, "secret.env\x00", "")
                    if argv[1] == "ls-files":
                        out = "secret.env\x00" if ("--ignored" in argv) == ignored else ""
                        return subprocess.CompletedProcess(argv, 0, out, "")
                    return self.tools.git(argv, cwd, **kw)
                from convoy.project_resolve import update_checkout
                r = update_checkout(self.local, runner=git)
                self.assertEqual(r["pulled"], "kept: would overwrite local file secret.env")
                self.assertFalse(any(c[0][1] == "pull" for c in self.tools.calls))

    def test_real_git_ignored_secret_survives_fast_forward(self):
        from convoy.repo import run_argv
        from convoy.project_resolve import update_checkout
        seed = self.base / "seed"
        seed.mkdir()
        def git(*args, cwd=seed):
            r = run_argv(["git", *args], str(cwd), timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r
        git("init", "--initial-branch=main")
        git("config", "user.name", "Synthetic")
        git("config", "user.email", "synthetic@example.test")
        (seed / ".gitignore").write_text("secret.env\n")
        git("add", ".gitignore")
        git("commit", "-m", "synthetic base")
        checkout = self.base / "clone"
        git("clone", "--", str(seed), str(checkout), cwd=self.base)
        (checkout / "secret.env").write_text("LOCAL-PRECIOUS")
        (seed / "secret.env").write_text("UPSTREAM")
        git("add", "-f", "secret.env")
        git("commit", "-m", "synthetic incoming")
        r = update_checkout(checkout)
        self.assertEqual(r["pulled"], "kept: would overwrite local file secret.env")
        self.assertEqual((checkout / "secret.env").read_text(), "LOCAL-PRECIOUS")

    def test_url_credentials_and_tokens_never_appear_in_start_card_or_cli(self):
        from convoy.start import start
        from convoy.cli import main
        secret = "synthetic-password"
        token = "ghp_" + "a" * 36
        url = "https://user:" + secret + "@github.com/other-owner/new.git"
        def invoke():
            with patch("convoy.start.onboard", return_value={"ok": False, "url": url, "error": token,
                       "nested": [url, "https://github.com/other-owner/new.git?token=" + token]}):
                return start(self.base, url, harnesses=["claude"], search_roots=[],
                             git_runner=self.tools.git, gh_runner=self.tools.gh)
        card = invoke()
        text = json.dumps(card)
        self.assertNotIn(secret, text)
        self.assertNotIn(token, text)
        stream = io.StringIO()
        with patch("convoy.cli.run_start", side_effect=lambda *a, **kw: invoke()), redirect_stdout(stream):
            main(["--root", str(self.base), "start", url])
        self.assertNotIn(secret, stream.getvalue())
        self.assertNotIn(token, stream.getvalue())

    def test_lowercase_suffix(self):
        from convoy.project_resolve import normalized_remote
        self.assertEqual(normalized_remote("https://github.com/Owner/Repo.GIT"), "github.com/owner/repo")

    def test_repo_relative_remote(self):
        from convoy.project_resolve import _remotes
        self.tools.remotes[str(self.local)] = "origin ../up.git (fetch)"
        expected = "file/" + str((self.local / "../up.git").resolve()).replace("\\", "/")
        self.assertEqual(_remotes(self.local, self.tools.git), [expected])

    def test_option_shaped_github_owner_is_refused_before_listing(self):
        def gh(argv, cwd=None, **kw):
            if argv[1:3] == ["api", "user"]:
                return subprocess.CompletedProcess(argv, 0, '{"login":"--help"}', "")
            return self.tools.gh(argv, cwd, **kw)
        from convoy.project_resolve import resolve_target
        r = resolve_target("unknown", search_roots=[self.base], git_runner=self.tools.git, gh_runner=gh)
        self.assertEqual(r["ask"], "unknown")
        self.assertFalse(any(c[0][1:3] == ["repo", "list"] for c in self.tools.calls))

    def test_plain_folder_collision_requires_pick_not_clone(self):
        (self.base / "plainfolder").mkdir()
        self.tools.repos = ["synthetic-owner/plainfolder"]
        r = self.resolve("plainfolder")
        self.assertEqual(r.get("ask"), "pick", r)
        self.assertEqual({row["kind"] for row in r["candidates"]}, {"local", "github"})

    def test_github_pick_rows_have_last_commit_dates(self):
        def gh(argv, cwd=None, **kw):
            if argv[1] == "api" and argv[2].startswith("repos/"):
                return subprocess.CompletedProcess(argv, 0, "2026-01-02T00:00:00Z", "")
            if argv[1:3] == ["repo", "list"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps([
                    {"nameWithOwner": "synthetic-owner/synthetic-project", "updatedAt": "2026-01-01T00:00:00Z"},
                    {"nameWithOwner": "other-owner/synthetic-project", "updatedAt": "2026-01-02T00:00:00Z"}]), "")
            return self.tools.gh(argv, cwd, **kw)
        from convoy.project_resolve import resolve_target
        r = resolve_target("synthetic-project", search_roots=[self.base], git_runner=self.tools.git, gh_runner=gh)
        self.assertEqual(r["ask"], "pick")
        self.assertEqual([row["last_commit"] for row in r["candidates"] if row["kind"] == "github"], ["2026-01-02T00:00:00Z"])


# Only the edge-case contracts belong to this class; helper methods are inherited.
for _name in StartResolve.__dict__:
    if _name.startswith("test_") and _name not in ResolveEdges.__dict__:
        setattr(ResolveEdges, _name, None)
del StartResolve


class BoundedRunner(unittest.TestCase):
    def test_git_refresh_runs_without_interactive_credentials(self):
        from convoy.repo import run_argv
        original = subprocess.Popen
        with patch("convoy.repo.subprocess.Popen", side_effect=lambda argv, **kw:
                   original([sys.executable, "-c", "print('synthetic git helper')"], **kw)) as popen:
            r = run_argv(["git", "fetch"], timeout=3)
        self.assertEqual(r.returncode, 0)
        env = popen.call_args.kwargs.get("env") or {}
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
        self.assertEqual(env.get("GCM_INTERACTIVE"), "never")
        self.assertEqual(env.get("GIT_ASKPASS"), "")
        if os.name == "nt":
            flags = popen.call_args.kwargs.get("creationflags", 0)
            self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)

    def test_timeout_bounds_lingering_child_with_inherited_output(self):
        from convoy.repo import run_argv
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(4)']); print('started',flush=True); time.sleep(4)"
        began = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_argv([sys.executable, "-c", code], timeout=.5)
        self.assertLess(time.monotonic() - began, 1.5)


if __name__ == "__main__":
    unittest.main()
