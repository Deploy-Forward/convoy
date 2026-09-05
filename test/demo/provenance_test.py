import io
import json
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
from convoy.provenance import COMMIT_ROW_KEYS, _git, build_provenance, record_commit


def _run(*args, cwd):
    run = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stderr)
    return (run.stdout or "").strip()


def _repo():
    repo = Path(tempfile.mkdtemp())
    _run("init", "-q", cwd=repo)
    _run("config", "user.email", "convoy@example.test", cwd=repo)
    _run("config", "user.name", "Convoy Test", cwd=repo)
    (repo / "one.txt").write_text("one\n", encoding="utf-8")
    _run("add", "one.txt", cwd=repo)
    _run("commit", "-q", "-m", "first", cwd=repo)
    return repo


def _root(repo, chair="luna1-happy-path"):
    root = Path(tempfile.mkdtemp())
    bind(root, "test-thread")
    seat(root, "codex", chair, worktree=str(repo))
    return root


def _cli(root, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *args])
    return rc, json.loads(buf.getvalue())


class CommitRows(unittest.TestCase):
    def test_git_wrapper_distinguishes_empty_stdout_from_failure(self):
        repo = _repo()
        rc, out = _git(repo, "diff", "--name-only", "HEAD", "HEAD")
        self.assertEqual((rc, out), (0, ""))
        rc, out = _git(repo, "rev-parse", "not-a-revision")
        self.assertNotEqual(rc, 0)
        self.assertIsInstance(out, str)

    def test_record_commit_writes_exact_shape_and_deduplicates(self):
        repo = _repo()
        root = _root(repo)
        first = record_commit(root, "luna1-happy-path", worktree=repo)
        row = first["row"]
        self.assertFalse(first["duplicate"])
        self.assertEqual(set(row), set(COMMIT_ROW_KEYS))
        self.assertEqual(row["kind"], "commit")
        self.assertEqual(row["instance_id"], "luna1-happy-path")
        self.assertEqual(row["from"], "luna1-happy-path")
        self.assertEqual(row["sha"], _run("rev-parse", "HEAD", cwd=repo))
        self.assertIsNone(row["parent"])
        self.assertEqual(row["files"], ["one.txt"])
        self.assertNotIn("token", row)

        second = record_commit(root, "luna1-happy-path", worktree=repo)
        self.assertTrue(second["duplicate"])
        commits = [r for r in feed_since(root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "commit"]
        self.assertEqual(len(commits), 1)

    def test_empty_commit_has_empty_files_and_diff_tree_failure_is_null(self):
        repo = _repo()
        root = _root(repo)
        _run("commit", "--allow-empty", "-q", "-m", "empty", cwd=repo)
        row = record_commit(root, "luna1-happy-path", worktree=repo)["row"]
        self.assertEqual(row["files"], [])

        from convoy import provenance

        real = provenance._git

        def fail_diff(worktree, *args):
            if args and args[0] == "diff-tree":
                return 2, ""
            return real(worktree, *args)

        _run("commit", "--allow-empty", "-q", "-m", "another", cwd=repo)
        with mock.patch.object(provenance, "_git", fail_diff):
            row = record_commit(root, "luna1-happy-path", worktree=repo)["row"]
        self.assertIsNone(row["files"])

    def test_refuses_missing_sha_and_unknown_chair(self):
        repo = _repo()
        root = _root(repo)
        with self.assertRaisesRegex(ValueError, "without a sha"):
            record_commit(root, "luna1-happy-path", rev="missing", worktree=repo)
        with self.assertRaisesRegex(ValueError, "unknown chair"):
            record_commit(root, "not-seated", worktree=repo)

    def test_cli_supports_as_and_as_me(self):
        repo = _repo()
        root = _root(repo)
        rc, card = _cli(root, "committed", "--as", "luna1-happy-path", "--worktree", str(repo))
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["row"]["from"], "luna1-happy-path")

        (repo / "two.txt").write_text("two\n", encoding="utf-8")
        _run("add", "two.txt", cwd=repo)
        _run("commit", "-q", "-m", "second", cwd=repo)
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": "luna1-happy-path"}):
            rc, card = _cli(root, "committed", "--as-me", "--worktree", str(repo))
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["row"]["files"], ["two.txt"])


class ProvenanceReads(unittest.TestCase):
    def test_folds_seats_commits_and_feed_only_chairs(self):
        repo = _repo()
        root = _root(repo)
        seat(root, "grok", "g1-happy-path")
        record_commit(root, "luna1-happy-path", worktree=repo)
        (repo / "two.txt").write_text("two\n", encoding="utf-8")
        _run("add", "two.txt", cwd=repo)
        _run("commit", "-q", "-m", "second", cwd=repo)
        record_commit(root, "luna1-happy-path", worktree=repo)

        from convoy.layer import hook

        hook(
            root,
            "commit",
            "commit abcdef123456: remote",
            instance_id="remote-chair",
            author="remote-chair",
            extra={
                "branch": "convoy/remote",
                "sha": "abcdef1234567890",
                "parent": None,
                "files": ["remote.txt"],
                "worktree": None,
            },
        )

        card = build_provenance(root)
        self.assertTrue(card["ok"])
        by_chair = {row["chair"]: row for row in card["provenance"]}
        self.assertEqual(by_chair["g1-happy-path"], {
            "chair": "g1-happy-path",
            "harness": "grok",
            "worktree": None,
            "branch": None,
            "sha": None,
            "last_commit_ts": None,
            "commits": 0,
            "files_touched": [],
        })
        luna = by_chair["luna1-happy-path"]
        self.assertEqual(luna["harness"], "codex")
        self.assertEqual(luna["commits"], 2)
        self.assertEqual(luna["files_touched"], ["one.txt", "two.txt"])
        self.assertEqual(luna["sha"], _run("rev-parse", "HEAD", cwd=repo))
        self.assertEqual(by_chair["remote-chair"]["harness"], None)
        self.assertEqual(by_chair["remote-chair"]["files_touched"], ["remote.txt"])

    def test_cli_since_and_malformed_feed_rows_are_read_only(self):
        repo = _repo()
        root = _root(repo)
        record_commit(root, "luna1-happy-path", worktree=repo)
        feed = root / ".convoy" / "feed.jsonl"
        with feed.open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")
        before = feed.read_bytes()
        rc, card = _cli(root, "provenance", "--since", "1d")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["provenance"][0]["commits"], 1)
        self.assertEqual(feed.read_bytes(), before)

    def test_rail_and_mcp_surface_the_same_public_read(self):
        repo = _repo()
        root = _root(repo)
        record_commit(root, "luna1-happy-path", worktree=repo)

        from convoy.mcp_http import TOOLS, call_tool
        from convoy.rail import build_rail

        rail = build_rail(root, since="1d", probe_fn=lambda _h: {"usage_remaining": None, "limited": False})
        direct = build_provenance(root, since="1d")
        self.assertEqual(rail["provenance"], direct["provenance"])
        self.assertIn("provenance", [tool["name"] for tool in TOOLS])
        mcp = call_tool(root, "provenance", {"since": "1d"})
        self.assertEqual(mcp["provenance"], direct["provenance"])
        self.assertNotIn("token", json.dumps(mcp))


if __name__ == "__main__":
    unittest.main()
