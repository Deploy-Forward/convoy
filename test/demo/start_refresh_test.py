"""Refresh, stale-root and worktree-only contracts."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from test.demo.start_resolve_test import FakeTools


class StartRefresh(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        self.base = Path(self.owner.name)
        env = patch.dict(os.environ, {"CONVOY_HOME": str(self.base / "state"),
                         "GIT_CONFIG_GLOBAL": str(self.base / "global-config")})
        env.start()
        self.addCleanup(env.stop)
        self.main = self.base / "outside" / "main"
        (self.main / ".git").mkdir(parents=True)
        (self.main / ".git" / "config").write_text('[remote "origin"]\n url = https://github.com/synthetic-owner/project.git\n')
        self.catalog = self.base / "catalog"
        self.catalog.mkdir()

    def linked(self, name):
        root = self.catalog / name
        root.mkdir()
        admin = self.main / ".git" / "worktrees" / name
        admin.mkdir(parents=True)
        (admin / "commondir").write_text("../..")
        (root / ".git").write_text("gitdir: " + str(admin))
        return root.resolve()

    def test_refresh_uses_only_one_fetch_then_local_ff_only_merge(self):
        from convoy.project_resolve import update_checkout
        tools = FakeTools()
        r = update_checkout(self.main, runner=tools.git)
        self.assertEqual(r["pulled"], "fast-forwarded 2")
        commands = [row[0] for row in tools.calls]
        self.assertEqual(sum(argv[1] == "fetch" for argv in commands), 1)
        self.assertFalse(any(argv[1] == "pull" for argv in commands))
        self.assertIn(["git", "merge", "--ff-only", "@{upstream}"], commands)

    def test_worktree_only_picker_is_not_empty_and_is_newest_first(self):
        from convoy.project_resolve import resolve_target
        paths = [self.linked("older"), self.linked("newer"), self.linked("newest")]
        dates = {str(path): "2026-01-0%dT00:00:00Z" % (i + 1) for i, path in enumerate(paths)}
        def git(argv, cwd=None, **kw):
            return subprocess.CompletedProcess(argv, 0, dates.get(str(cwd), ""), "")
        with patch("convoy.project_resolve.list_threads", return_value=[]):
            r = resolve_target("synthetic-owner/project", search_roots=[self.catalog], git_runner=git)
        self.assertEqual(r["ask"], "pick")
        self.assertEqual([c["path"] for c in r["candidates"]], [str(p) for p in reversed(paths)])
        self.assertEqual([c["pick"] for c in r["candidates"]], [1, 2, 3])

    def test_indexed_root_freshness_is_fourteen_days_under_fake_wall_clock(self):
        from convoy.project_resolve import resolve_target
        root = self.linked("indexed")
        record = {"present": True, "root": str(root), "updated_at": "2026-01-01T00:00:00Z"}
        def git(argv, cwd=None, **kw):
            return subprocess.CompletedProcess(argv, 0, "2026-01-01T00:00:00Z", "")
        for date, expected in (("2026-01-03", root), ("2026-01-15", root), ("2026-01-16", self.main)):
            now = datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()
            with self.subTest(date=date), patch("convoy.project_resolve.list_threads", return_value=[record]), \
                 patch("convoy.project_resolve.time.time", return_value=now):
                r = resolve_target("synthetic-owner/project", search_roots=[self.catalog, self.main], git_runner=git)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["checkout"], str(expected.resolve()))

    def test_runner_normalizes_crlf_but_preserves_lone_carriage_return(self):
        from convoy.repo import run_argv
        r = run_argv([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'a\\r\\nb\\r')"], timeout=2)
        self.assertEqual(r.stdout, "a\nb\r")


if __name__ == "__main__":
    unittest.main()
