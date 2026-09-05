import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, seat
from convoy.layer import hook
from convoy.provenance import REBASE_NOTE, _git, rebase_check


def git(repo, *args):
    run = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stderr)
    return (run.stdout or "").strip()


def cli(root, *args):
    output = io.StringIO()
    with redirect_stdout(output):
        rc = main(["--root", str(root), *args])
    return rc, json.loads(output.getvalue())


class RebaseChecks(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": tempfile.mkdtemp()})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def diverged(self):
        repo = Path(tempfile.mkdtemp())
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "convoy@example.test")
        git(repo, "config", "user.name", "Convoy Test")
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        git(repo, "add", "base.txt")
        git(repo, "commit", "-q", "-m", "base")
        base0 = git(repo, "rev-parse", "HEAD")
        git(repo, "branch", "feat/happy-path-proof")

        git(repo, "switch", "-q", "-c", "convoy/luna1")
        (repo / "shared.txt").write_text("mine\n", encoding="utf-8")
        git(repo, "add", "shared.txt")
        git(repo, "commit", "-q", "-m", "mine one")
        mine_one = git(repo, "rev-parse", "HEAD")
        (repo / "mine.txt").write_text("mine two\n", encoding="utf-8")
        git(repo, "add", "mine.txt")
        git(repo, "commit", "-q", "-m", "mine two")

        g2 = Path(tempfile.mkdtemp())
        git(repo, "worktree", "add", "-q", "-b", "convoy/g2", str(g2), base0)
        (g2 / "shared.txt").write_text("g2\n", encoding="utf-8")
        (g2 / "dirty.txt").write_text("g2 dirty\n", encoding="utf-8")
        git(g2, "add", "shared.txt", "dirty.txt")
        git(g2, "commit", "-q", "-m", "g2")

        g3 = Path(tempfile.mkdtemp())
        git(repo, "worktree", "add", "-q", "-b", "convoy/g3", str(g3), mine_one)
        (g3 / "g3.txt").write_text("g3\n", encoding="utf-8")
        git(g3, "add", "g3.txt")
        git(g3, "commit", "-q", "-m", "g3")

        remote = Path(tempfile.mkdtemp())
        git(repo, "worktree", "add", "-q", "-b", "feed-only", str(remote), base0)
        (remote / "remote.txt").write_text("remote\n", encoding="utf-8")
        git(remote, "add", "remote.txt")
        git(remote, "commit", "-q", "-m", "remote")
        remote_sha = git(remote, "rev-parse", "HEAD")
        git(repo, "worktree", "remove", "-f", str(remote))
        git(repo, "branch", "-D", "feed-only")

        base_worktree = Path(tempfile.mkdtemp())
        git(repo, "worktree", "add", "-q", str(base_worktree), "feat/happy-path-proof")
        (base_worktree / "advanced.txt").write_text("advance\n", encoding="utf-8")
        git(base_worktree, "add", "advanced.txt")
        git(base_worktree, "commit", "-q", "-m", "base advance")

        (repo / "dirty.txt").write_text("mine dirty\n", encoding="utf-8")
        root = Path(tempfile.mkdtemp())
        bind(root, "test-thread")
        seat(root, "codex", "luna1-happy-path", worktree=str(repo))
        seat(root, "grok", "g2-happy-path", worktree=str(g2))
        return repo, root, base0, mine_one, remote_sha

    def test_report_uses_each_git_merge_base_and_feed_union(self):
        repo, root, base0, mine_one, remote_sha = self.diverged()
        hook(root, "commit", "already present", instance_id="remote-chair", author="remote-chair", extra={
            "branch": "convoy/remote", "sha": mine_one, "parent": base0,
            "files": ["already.txt"], "worktree": None,
        })
        hook(root, "commit", "unknown one", instance_id="remote-chair", author="remote-chair", extra={
            "branch": "convoy/remote", "sha": remote_sha, "parent": base0,
            "files": ["remote.txt"], "worktree": None,
        })
        hook(root, "commit", "unknown two", instance_id="remote-chair", author="remote-chair", extra={
            "branch": "convoy/remote", "sha": "f" * 40, "parent": None,
            "files": ["remote-two.txt"], "worktree": None,
        })
        before_status = git(repo, "status", "--porcelain=v1", "--branch")
        before_refs = git(repo, "show-ref")

        calls = []

        def recording(args, cwd):
            calls.append(tuple(args))
            return _git(args, cwd)

        with mock.patch("convoy.provenance._git", side_effect=recording):
            card = rebase_check(repo, root=root)

        self.assertTrue(card["ok"])
        self.assertEqual(card["merge_base"], base0)
        self.assertEqual(card["behind"], 1)
        self.assertEqual(card["my_files"], ["mine.txt", "shared.txt"])
        self.assertEqual(card["uncommitted"], ["dirty.txt"])
        self.assertEqual(card["note"], REBASE_NOTE)
        self.assertEqual(card["action"], "rebase")
        by_branch = {row["branch"]: row for row in card["siblings"]}
        self.assertEqual(by_branch["convoy/g2"]["chair"], "g2-happy-path")
        self.assertEqual(by_branch["convoy/g2"]["source"], "git")
        self.assertEqual(by_branch["convoy/g2"]["files"], ["dirty.txt", "shared.txt"])
        self.assertEqual(by_branch["convoy/g2"]["overlapping_files"], ["dirty.txt", "shared.txt"])
        self.assertIsNone(by_branch["convoy/g3"]["chair"])
        self.assertEqual(by_branch["convoy/g3"]["files"], ["g3.txt"])
        self.assertEqual(by_branch["convoy/g3"]["overlapping_files"], [])
        self.assertEqual(by_branch["convoy/remote"]["source"], "feed")
        self.assertEqual(by_branch["convoy/remote"]["files"], ["remote-two.txt", "remote.txt"])
        self.assertNotIn("already.txt", by_branch["convoy/remote"]["files"])
        self.assertEqual(git(repo, "status", "--porcelain=v1", "--branch"), before_status)
        self.assertEqual(git(repo, "show-ref"), before_refs)

        allowed = {"rev-parse", "merge-base", "rev-list", "diff", "status", "branch", "for-each-ref"}
        self.assertTrue(calls)
        self.assertLessEqual({args[0] for args in calls}, allowed)

    def test_missing_base_is_card_not_exception(self):
        repo, root, _, _, _ = self.diverged()
        card = rebase_check(repo, base="missing-base", root=root)
        self.assertFalse(card["ok"])
        self.assertIn("base ref absent", card["error"])
        self.assertIsNone(card["base_sha"])

    def test_cli_refuses_without_check_and_preserves_state(self):
        repo, root, _, _, _ = self.diverged()
        before = git(repo, "status", "--porcelain=v1", "--branch")
        rc, card = cli(root, "rebase", "--worktree", str(repo))
        self.assertEqual(rc, 1)
        self.assertEqual(card["error"], "this verb only reports; run git rebase yourself")
        rc, card = cli(root, "rebase", "--check", "--worktree", str(repo))
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["ok"])
        self.assertEqual(git(repo, "status", "--porcelain=v1", "--branch"), before)


if __name__ == "__main__":
    unittest.main()
