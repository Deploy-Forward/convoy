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
from convoy.layer import SCHEMA_VERSION, hook
from convoy.provenance import commit_row, rail_provenance, summarize


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


def thread(worktree):
    root = Path(tempfile.mkdtemp())
    bind(root, "test-thread")
    seat(root, "codex", "luna1-happy-path", worktree=str(worktree))
    seat(root, "grok", "g1-happy-path")
    return root


def cli(root, *args):
    output = io.StringIO()
    with redirect_stdout(output):
        rc = main(["--root", str(root), *args])
    return rc, json.loads(output.getvalue())


class ProvenanceReads(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": tempfile.mkdtemp()})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_summary_folds_tips_files_and_zero_commit_chair(self):
        worktree = repo()
        root = thread(worktree)
        first = commit_row(root, "luna1-happy-path")["row"]
        (worktree / "two.txt").write_text("two\n", encoding="utf-8")
        git(worktree, "add", "two.txt")
        git(worktree, "commit", "-q", "-m", "second")
        second = commit_row(root, "luna1-happy-path")["row"]
        hook(
            root,
            "commit",
            "commit remote",
            instance_id="remote-chair",
            author="remote-chair",
            extra={
                "branch": "convoy/remote",
                "sha": "f" * 40,
                "parent": None,
                "files": ["remote.txt"],
                "worktree": r"C:\untrusted-row-worktree",
            },
        )

        card = summarize(root)
        self.assertEqual(set(card), {"schema_version", "since", "chairs"})
        self.assertEqual(card["schema_version"], SCHEMA_VERSION)
        by_chair = {row["chair"]: row for row in card["chairs"]}
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
        self.assertEqual(luna["worktree"], str(worktree))
        self.assertEqual(luna["commits"], 2)
        self.assertEqual(luna["sha"], second["sha"])
        self.assertGreaterEqual(luna["last_commit_ts"], first["ts"])
        self.assertEqual(luna["files_touched"], ["one.txt", "two.txt"])
        self.assertIsNone(by_chair["remote-chair"]["harness"])
        self.assertIsNone(by_chair["remote-chair"]["worktree"])

    def test_cli_shape_since_and_malformed_unknown_kind(self):
        worktree = repo()
        root = thread(worktree)
        commit_row(root, "luna1-happy-path")
        feed = root / ".convoy" / "feed.jsonl"
        with feed.open("a", encoding="utf-8") as handle:
            handle.write('{"ts":"2099-01-01T00:00:00Z","kind":"future"}\n')
            handle.write("malformed-fragment\n")
        before = feed.read_bytes()
        rc, card = cli(root, "provenance", "--since", "1d")
        self.assertEqual(rc, 0, card)
        self.assertEqual(set(card), {"schema_version", "since", "chairs"})
        self.assertEqual(card["since"], "1d")
        self.assertEqual(feed.read_bytes(), before)

    def test_rail_summary_is_compact_and_uses_same_fold(self):
        worktree = repo()
        root = thread(worktree)
        row = commit_row(root, "luna1-happy-path")["row"]
        compact = rail_provenance(root, since="1d")
        self.assertEqual(compact, {
            "chairs": 2,
            "with_commits": 1,
            "tips": [{
                "chair": "luna1-happy-path",
                "branch": row["branch"],
                "sha7": row["sha"][:7],
                "ts": row["ts"],
            }],
        })

        from convoy.rail import build_rail

        rail = build_rail(root, since="1d", probe_fn=lambda _h: {"usage_remaining": None, "limited": False})
        self.assertEqual(rail["provenance"], compact)
        self.assertNotIn("token", json.dumps(rail))
        self.assertNotIn("resume", json.dumps(rail))

    def test_mcp_lists_public_read_and_returns_cli_shape(self):
        worktree = repo()
        root = thread(worktree)
        commit_row(root, "luna1-happy-path")
        from convoy.mcp_http import TOOLS, call_tool

        self.assertIn("provenance", [tool["name"] for tool in TOOLS])
        card = call_tool(root, "provenance", {"since": "1d"})
        self.assertEqual(card, summarize(root, since="1d"))
        self.assertNotIn("token", json.dumps(card))
        self.assertNotIn("resume", json.dumps(card))


if __name__ == "__main__":
    unittest.main()
