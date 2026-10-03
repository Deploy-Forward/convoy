"""Project resolution and safe pull: fake gh, synthetic remotes, isolated homes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class FakeTools:
    def __init__(self):
        self.calls = []
        self.remotes = {}
        self.repos = []
        self.dirty = False
        self.branch = "main"
        self.upstream = "origin/main"
        self.counts = "0 2"
        self.fetch_code = 0
        self.gh_state = "ok"

    def git(self, argv, cwd=None, **kw):
        self.calls.append((argv, str(cwd)))
        args = argv[1:]
        code, out = 0, ""
        if args == ["remote", "-v"]:
            out = self.remotes.get(str(cwd), "")
        elif args[0] == "log":
            out = "2026-01-01T00:00:00Z"
        elif args[:2] == ["status", "--porcelain"]:
            out = " M user.txt" if self.dirty else ""
        elif args[0] == "symbolic-ref":
            code, out = (0, self.branch) if self.branch else (1, "")
        elif args[:2] == ["rev-parse", "--abbrev-ref"]:
            code, out = (0, self.upstream) if self.upstream else (1, "")
        elif args[0] == "rev-list":
            out = self.counts
        elif args[0] == "fetch":
            code = self.fetch_code
        elif args[0] in ("pull", "merge"):
            self.counts = "0 0"
        elif args[0] in ("diff", "ls-files"):
            out = ""
        else:
            raise AssertionError("unexpected git call " + repr(args))
        return subprocess.CompletedProcess(argv, code, out, "synthetic network failure" if code else "")

    def gh(self, argv, cwd=None, **kw):
        self.calls.append((argv, str(cwd)))
        if self.gh_state == "missing":
            raise FileNotFoundError("synthetic missing gh")
        if self.gh_state == "offline":
            return subprocess.CompletedProcess(argv, 1, "", "connection failed")
        if argv[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:3] == ["api", "user"]:
            out = json.dumps({"login": "synthetic-owner"})
        elif argv[1:3] == ["api", "user/orgs"]:
            out = ""
        elif argv[1] == "api" and argv[2].startswith("repos/"):
            out = "2026-01-01T00:00:00Z"
        elif argv[1:3] == ["repo", "list"]:
            out = json.dumps([{"nameWithOwner": r} for r in self.repos])
        elif argv[1:3] == ["repo", "create"]:
            out = ""
        else:
            raise AssertionError("unexpected gh call " + repr(argv))
        return subprocess.CompletedProcess(argv, 0, out, "")


class StartResolve(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        self.base = Path(self.owner.name)
        self.local = self.base / "synthetic-project"
        (self.local / ".git").mkdir(parents=True)
        p = patch.dict(os.environ, {"CONVOY_HOME": str(self.base / "convoy-home"),
                                   "GIT_CONFIG_GLOBAL": str(self.base / "synthetic-global-config")})
        p.start()
        self.addCleanup(p.stop)
        self.tools = FakeTools()
        self.tools.remotes[str(self.local.resolve())] = "origin git@github.com:synthetic-owner/synthetic-project.git (fetch)"

    def resolve(self, target, **kw):
        from convoy.project_resolve import resolve_target
        return resolve_target(target, search_roots=[self.base], git_runner=self.tools.git,
                              gh_runner=self.tools.gh, **kw)

    def update(self):
        from convoy.project_resolve import update_checkout
        return update_checkout(self.local, runner=self.tools.git)

    def test_existing_path_makes_no_network_calls(self):
        r = self.resolve(str(self.local))
        self.assertTrue(r["ok"])
        self.assertFalse(r["refresh"])
        self.assertFalse(any(c[0][0] == "gh" or c[0][1] in ("fetch", "pull") for c in self.tools.calls))

    def test_url_reuses_existing_checkout_by_remote_not_folder(self):
        r = self.resolve("https://github.com/synthetic-owner/synthetic-project")
        self.assertEqual(r["checkout"], str(self.local.resolve()))
        self.assertTrue(r["refresh"])

    def test_slug_is_cloud_when_no_matching_remote(self):
        r = self.resolve("synthetic-owner/other")
        self.assertEqual(r["checkout"], "https://github.com/synthetic-owner/other.git")
        self.assertTrue(r["github"])

    def test_same_basename_wrong_remote_does_not_reuse(self):
        r = self.resolve("another-owner/synthetic-project")
        self.assertNotEqual(r["checkout"], str(self.local.resolve()))

    def test_bare_name_local_and_linked_github_are_one_candidate(self):
        self.tools.repos = ["synthetic-owner/synthetic-project"]
        r = self.resolve("synthetic-project")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checkout"], str(self.local.resolve()))

    def test_bare_name_github_only(self):
        self.tools.repos = ["synthetic-owner/cloud-only"]
        r = self.resolve("cloud-only")
        self.assertEqual(r["checkout"], "https://github.com/synthetic-owner/cloud-only.git")

    def test_multiple_matches_require_numbered_pick(self):
        self.tools.repos = ["synthetic-owner/synthetic-project", "another-owner/synthetic-project"]
        r = self.resolve("synthetic-project")
        self.assertFalse(r["ok"])
        self.assertEqual(r["ask"], "pick")
        self.assertEqual([c["pick"] for c in r["candidates"]], [1, 2])

    def test_unknown_name_asks_new_without_creating(self):
        r = self.resolve("synthetic-unknown")
        self.assertEqual(r["ask"], "new")
        self.assertEqual(len(r["choices"]), 2)
        self.assertFalse(any(c[0][1:3] == ["repo", "create"] for c in self.tools.calls))

    def test_missing_gh_keeps_local(self):
        self.tools.gh_state = "missing"
        r = self.resolve("synthetic-project")
        self.assertTrue(r["ok"])
        self.assertIn("local only:", r["note"])
        self.assertFalse(r["refresh"])

    def test_logged_out_gh_keeps_local_without_fetch(self):
        from convoy.project_resolve import resolve_target
        def logged_out(argv, cwd=None, **kw):
            return subprocess.CompletedProcess(argv, 1, "", "not logged into any GitHub hosts; gh auth login")
        result = resolve_target("synthetic-project", search_roots=[self.base],
                                git_runner=self.tools.git, gh_runner=logged_out)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["refresh"])
        self.assertEqual(result["note"], "local only: gh not authenticated")

    def test_network_failure_is_unknown_not_no_repo(self):
        self.tools.gh_state = "offline"
        r = self.resolve("synthetic-unknown")
        self.assertEqual(r["ask"], "unknown")
        self.assertNotIn("choices", r)

    def test_scan_timeout_is_unknown_not_no_repo(self):
        r = self.resolve("synthetic-unknown", scan_budget=0)
        self.assertEqual(r["ask"], "unknown")

    def test_dirty_is_kept(self):
        self.tools.dirty = True
        self.assertEqual(self.update()["pulled"], "kept: dirty")

    def test_ahead_is_kept(self):
        self.tools.counts = "2 0"
        self.assertEqual(self.update()["pulled"], "kept: ahead 2")

    def test_diverged_is_kept(self):
        self.tools.counts = "2 3"
        self.assertEqual(self.update()["pulled"], "kept: diverged 2/3")

    def test_detached_and_no_upstream_are_kept(self):
        self.tools.branch = None
        self.assertEqual(self.update()["pulled"], "kept: detached")
        self.tools.branch, self.tools.upstream = "main", None
        self.assertEqual(self.update()["pulled"], "kept: no upstream")

    def test_clean_behind_fast_forwards_with_only_ff_merge_no_stash(self):
        self.assertEqual(self.update()["pulled"], "fast-forwarded 2")
        calls = [c[0] for c in self.tools.calls]
        self.assertIn(["git", "merge", "--ff-only", "@{upstream}"], calls)
        self.assertFalse(any(c[1] in ("pull", "stash", "reset", "rebase") for c in calls))

    def test_fetch_failure_is_explicit(self):
        self.tools.fetch_code = 1
        self.assertIn("fetch failed:", self.update()["pulled"])

    def test_create_is_explicit_and_private(self):
        r = self.resolve("synthetic-new", create=True)
        self.assertTrue(r["ok"], r)
        self.assertIn((["gh", "repo", "create", "synthetic-owner/synthetic-new", "--private"], "None"), self.tools.calls)

    def test_no_remote_stays_local(self):
        self.tools.remotes = {}
        r = self.resolve("synthetic-project")
        self.assertTrue(r["ok"])
        self.assertFalse(r["refresh"])
        self.assertEqual(r["note"], "local only: checkout has no remote")

    def test_owned_checkout_is_found_without_index(self):
        owned = self.base / "convoy-home" / "checkouts" / "synthetic-owner" / "stored-repo"
        (owned / ".git").mkdir(parents=True)
        self.tools.remotes[str(owned.resolve())] = "other https://github.com/synthetic-owner/stored-repo.git (fetch)"
        self.tools.repos = ["synthetic-owner/stored-repo"]
        r = self.resolve("stored-repo")
        self.assertEqual(r["checkout"], str(owned.resolve()))

    def test_read_unknown_counts_never_pulls(self):
        self.tools.counts = ""
        self.assertEqual(self.update()["pulled"], "kept: ahead/behind unknown")
        self.assertFalse(any(c[0][1] == "pull" for c in self.tools.calls))

    def test_multiple_local_copies_are_not_collapsed(self):
        other = self.base / "copy"
        (other / ".git").mkdir(parents=True)
        self.tools.remotes[str(other.resolve())] = self.tools.remotes[str(self.local.resolve())]
        r = self.resolve("synthetic-owner/synthetic-project")
        self.assertEqual(r["ask"], "pick")

    def test_gh_cap_is_incomplete_not_absence(self):
        self.tools.repos = ["synthetic-owner/other-" + str(i) for i in range(200)]
        r = self.resolve("unknown")
        self.assertEqual(r["ask"], "unknown")

    def test_start_composes_resolution_and_keeps_safe_writes(self):
        from convoy.start import start
        with patch("convoy.start.onboard", return_value={"ok": True, "root": str(self.local)}) as onboard:
            card = start(self.base, "synthetic-owner/synthetic-project", harnesses=["claude"],
                         search_roots=[self.base], git_runner=self.tools.git, gh_runner=self.tools.gh)
        self.assertEqual(card["pulled"], "fast-forwarded 2")
        self.assertFalse(onboard.call_args.kwargs["write_repo_files"])
        self.assertEqual(onboard.call_args.kwargs["checkout_root"], str(self.local.resolve()))

    def test_cli_forwards_discovery_options_without_implicit_create(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        with patch("convoy.cli.run_start", return_value={"ok": True}) as call, redirect_stdout(io.StringIO()):
            result = main(["--root", str(self.base), "start", "synthetic-project", "--search-root", str(self.base), "--scan-budget", "9"])
        self.assertEqual(result, 0)
        self.assertEqual(call.call_args.kwargs["search_roots"], [str(self.base)])
        self.assertEqual(call.call_args.kwargs["scan_budget"], 9)
        self.assertFalse(call.call_args.kwargs["create"])


if __name__ == "__main__":
    unittest.main()
