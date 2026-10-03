"""Checkout priority and honest incomplete discovery, with synthetic records."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CheckoutPreference(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        self.base = Path(self.owner.name)
        self.patch = patch.dict(os.environ, {"CONVOY_HOME": str(self.base / "convoy-home"),
                    "GIT_CONFIG_GLOBAL": str(self.base / "global-config")})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calls = []

    def repo(self, name, *, linked_to=None):
        root = self.base / name
        root.mkdir()
        if linked_to is None:
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text('[remote "origin"]\n url = https://github.com/synthetic-owner/project.git\n')
        else:
            admin = linked_to / ".git" / "worktrees" / name
            admin.mkdir(parents=True)
            (admin / "commondir").write_text("../..")
            (root / ".git").write_text("gitdir: " + str(admin))
        return root.resolve()

    def git(self, argv, cwd=None, **kw):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "2026-01-01T00:00:00Z" if argv[1] == "log" else "", "")

    def resolve(self, **kw):
        from convoy.project_resolve import resolve_target
        return resolve_target("synthetic-owner/project", search_roots=[self.base], git_runner=self.git, **kw)

    def test_one_main_and_ten_linked_worktrees_resolve_without_picker(self):
        main = self.repo("main")
        for i in range(10):
            self.repo("linked-%02d" % i, linked_to=main)
        r = self.resolve()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checkout"], str(main))

    def test_indexed_thread_root_wins_by_most_recent_update(self):
        main = self.repo("main")
        older = self.repo("older", linked_to=main)
        newer = self.repo("newer", linked_to=main)
        with patch("convoy.project_resolve.time.time", return_value=1767398400), \
             patch("convoy.project_resolve.list_threads", return_value=[
             {"present": True, "root": str(older), "updated_at": "2026-01-01T00:00:00Z"},
             {"present": True, "root": str(newer), "updated_at": "2026-01-02T00:00:00Z"}]):
            r = self.resolve()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checkout"], str(newer))

    def test_ambiguous_main_checkouts_collapse_worktrees_unless_all(self):
        main = self.repo("main-a")
        self.repo("main-b")
        for i in range(10):
            self.repo("linked-%02d" % i, linked_to=main)
        r = self.resolve()
        self.assertEqual(r["ask"], "pick")
        self.assertEqual(len(r["candidates"]), 2)
        self.assertEqual(r["linked_worktrees"]["summary"], "+10 worktrees")
        r = self.resolve(all_worktrees=True)
        self.assertEqual(len(r["candidates"]), 12)
        self.assertEqual([Path(c["path"]).name for c in r["candidates"][:2]], ["main-a", "main-b"])

    def test_timed_out_scan_with_unread_second_copy_never_auto_resolves(self):
        first = self.repo("first")
        unrelated = self.repo("middle")
        (unrelated / ".git" / "config").write_text('[remote "origin"]\n url = https://github.com/synthetic-owner/unrelated.git\n')
        self.repo("zz-second")
        original = Path.read_text
        current = [0.0]
        read_roots = []
        def read(path, *args, **kw):
            if path.name == "config":
                current[0] += .1
                read_roots.append(path.parent.parent.name)
            return original(path, *args, **kw)
        with patch("convoy.project_resolve.list_threads", return_value=[{"present": True, "root": str(first)}]), \
             patch.object(Path, "read_text", read):
            r = self.resolve(scan_budget=.15, clock=lambda: current[0])
        self.assertFalse(r["ok"], r)
        self.assertIn(r["ask"], ("pick", "unknown"))
        self.assertIn("timed out", json.dumps(r).lower())
        self.assertIn("incomplete", json.dumps(r).lower())
        self.assertNotIn("zz-second", read_roots)

    def test_local_date_reads_are_charged_to_scan_budget(self):
        self.repo("main-a")
        self.repo("main-b")
        ticks = iter([0, 0, .2, .4, .6, .8, 1, 1.2, 1.4, 1.6, 1.8, 2, 3, 4, 5, 6, 7, 8])
        r = self.resolve(scan_budget=2, clock=lambda: next(ticks, 10))
        self.assertFalse(r["ok"], r)
        self.assertIn("incomplete", json.dumps(r).lower())

    def test_internal_convoy_home_and_dot_convoy_are_not_projects(self):
        from convoy.project_resolve import resolve_target
        state = self.base / "convoy-home"
        (state / "logs").mkdir(parents=True)
        (self.base / ".convoy" / "logs").mkdir(parents=True)
        def missing(*a, **kw):
            raise FileNotFoundError()
        r = resolve_target("logs", search_roots=[state, self.base / ".convoy"],
                           git_runner=self.git, gh_runner=missing)
        self.assertEqual(r["ask"], "new", r)
        self.assertFalse(r["candidates"])

    def test_global_insteadof_rewrite_is_read_once(self):
        main = self.repo("main")
        (main / ".git" / "config").write_text('[remote "origin"]\n url = synthetic:project.git\n')
        global_config = self.base / "global-config"
        global_config.write_text('[url "https://github.com/synthetic-owner/"]\n insteadOf = synthetic:\n')
        original = Path.read_text
        reads = []
        def read(path, *args, **kwargs):
            if path == global_config:
                reads.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            r = self.resolve()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checkout"], str(main))
        self.assertEqual(len(reads), 1)

    def test_github_dates_use_single_list_metadata_not_per_candidate_api(self):
        from convoy.project_resolve import resolve_target
        calls = []
        def gh(argv, cwd=None, **kw):
            calls.append(argv)
            if argv[1:3] == ["auth", "status"]:
                out = ""
            elif argv[1:3] == ["api", "user"]:
                out = '{"login":"synthetic-owner"}'
            elif argv[1:3] == ["api", "user/orgs"]:
                out = ""
            elif argv[1:3] == ["repo", "list"]:
                out = json.dumps([{"nameWithOwner": "owner-a/project", "updatedAt": "2026-01-01T00:00:00Z"},
                                  {"nameWithOwner": "owner-b/project", "updatedAt": "2026-01-02T00:00:00Z"}])
            else:
                out = ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        r = resolve_target("project", search_roots=[], git_runner=self.git, gh_runner=gh)
        self.assertEqual(r["ask"], "pick")
        self.assertEqual([c["last_commit"] for c in r["candidates"]], ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"])
        self.assertFalse(any(c[1] == "api" and c[2].startswith("repos/") for c in calls))

    def test_synapse_feed_tokens_are_not_credentials(self):
        from convoy.repo import redact_credentials
        token = "0" * 31 + "1"
        row = {"kind": "synapse", "token": token, "summary": "send " + token}
        self.assertEqual(redact_credentials(row), row)

    def test_clone_env_unchanged_and_output_crlf_normalized(self):
        from convoy.repo import run_argv
        popen = subprocess.Popen
        with patch.dict(os.environ, {"GIT_TERMINAL_PROMPT": "synthetic-default"}):
            with patch("convoy.repo.subprocess.Popen", side_effect=lambda argv, **kw:
                       popen([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'a\\r\\nb\\r\\n')"], **kw)) as call:
                r = run_argv(["git", "clone", "synthetic"], timeout=2)
        self.assertEqual(call.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "synthetic-default")
        self.assertEqual(r.stdout, "a\nb\n")


if __name__ == "__main__":
    unittest.main()
