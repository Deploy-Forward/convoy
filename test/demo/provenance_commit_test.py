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
from convoy.layer import feed_since
from convoy.provenance import COMMIT_ROW_KEYS, _git, commit_row


def git(repo, *args):
    run = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stderr)
    return (run.stdout or "").strip()


def repo():
    path = Path(tempfile.mkdtemp())
    git(path, "init", "-q")
    git(path, "config", "user.email", "convoy@example.test")
    git(path, "config", "user.name", "Convoy Test")
    (path / "one.txt").write_text("one\n", encoding="utf-8")
    git(path, "add", "one.txt")
    git(path, "commit", "-q", "-m", "first")
    return path


def root_for(worktree, chair="luna1-happy-path"):
    root = Path(tempfile.mkdtemp())
    bind(root, "test-thread")
    seat(root, "codex", chair, worktree=str(worktree))
    return root


def cli(root, *args):
    output = io.StringIO()
    with redirect_stdout(output):
        rc = main(["--root", str(root), *args])
    return rc, json.loads(output.getvalue())


class CommitRows(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": tempfile.mkdtemp()})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_git_retains_rc_and_empty_stdout(self):
        worktree = repo()
        self.assertEqual(_git(["diff", "--name-only", "HEAD", "HEAD"], worktree), (0, ""))
        rc, out = _git(["rev-parse", "missing"], worktree)
        self.assertNotEqual(rc, 0)
        self.assertIsInstance(out, str)
        with mock.patch("convoy.provenance.subprocess.run", side_effect=OSError("git missing")):
            self.assertEqual(_git(["status"], worktree), (None, ""))

    def test_root_commit_row_has_exact_shape_and_no_token(self):
        worktree = repo()
        root = root_for(worktree)
        card = commit_row(root, "luna1-happy-path")
        row = card["row"]
        self.assertEqual(set(row), set(COMMIT_ROW_KEYS))
        self.assertEqual(row["kind"], "commit")
        self.assertEqual(row["from"], row["instance_id"])
        self.assertEqual(row["sha"], git(worktree, "rev-parse", "HEAD"))
        self.assertIsNone(row["parent"])
        self.assertEqual(row["files"], ["one.txt"])
        self.assertIn("commit " + row["sha"][:7] + " on ", row["summary"])
        self.assertNotIn("token", row)

    def test_empty_diff_is_list_and_failed_diff_tree_is_null(self):
        worktree = repo()
        root = root_for(worktree)
        git(worktree, "commit", "--allow-empty", "-q", "-m", "empty")
        self.assertEqual(commit_row(root, "luna1-happy-path")["row"]["files"], [])

        real = _git

        def fail_diff(args, cwd):
            if args and args[0] == "diff-tree":
                return 2, ""
            return real(args, cwd)

        git(worktree, "commit", "--allow-empty", "-q", "-m", "another")
        with mock.patch("convoy.provenance._git", side_effect=fail_diff):
            row = commit_row(root, "luna1-happy-path")["row"]
        self.assertIsNone(row["files"])

    def test_refusals_write_no_commit_row(self):
        worktree = repo()
        root = root_for(worktree)
        before = len(feed_since(root, "1970-01-01T00:00:00.000000Z"))
        with self.assertRaisesRegex(ValueError, "without a sha"):
            commit_row(root, "luna1-happy-path", rev="missing")
        with self.assertRaisesRegex(ValueError, "unknown chair"):
            commit_row(root, "not-seated")
        nongit = Path(tempfile.mkdtemp())
        seat(root, "grok", "g1-happy-path", worktree=str(nongit))
        with self.assertRaisesRegex(ValueError, "without a sha"):
            commit_row(root, "g1-happy-path")
        after = len(feed_since(root, "1970-01-01T00:00:00.000000Z"))
        self.assertEqual(after, before)

    def test_duplicate_does_not_append_a_second_line(self):
        worktree = repo()
        root = root_for(worktree)
        first = commit_row(root, "luna1-happy-path")
        lines = (root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines()
        second = commit_row(root, "luna1-happy-path")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual((root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines(), lines)

    def test_cli_as_defaults_to_seat_worktree_and_as_me_can_refuse(self):
        worktree = repo()
        root = root_for(worktree)
        rc, card = cli(root, "committed", "--as", "luna1-happy-path")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["row"]["worktree"], str(worktree.resolve()))

        git(worktree, "commit", "--allow-empty", "-q", "-m", "second")
        with mock.patch("convoy.cli.identify", return_value={"ok": False, "chair": None}):
            rc, card = cli(root, "committed", "--as-me")
        self.assertEqual(rc, 1)
        self.assertIn("no chair", card["error"])
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": "luna1-happy-path"}):
            rc, card = cli(root, "committed", "--as-me")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["row"]["from"], "luna1-happy-path")


if __name__ == "__main__":
    unittest.main()
