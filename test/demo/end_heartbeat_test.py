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
from convoy.end import end_task


class FakeGit:
    def __init__(self, *, dirty=False, detached=False, upstream="origin/topic", push_code=0):
        self.dirty = dirty
        self.detached = detached
        self.upstream = upstream
        self.push_code = push_code
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), Path(cwd)))
        key = tuple(args)
        if key == ("rev-parse", "--is-inside-work-tree"):
            return subprocess.CompletedProcess(args, 0, "true\n", "")
        if key == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return subprocess.CompletedProcess(args, 1 if self.detached else 0, "" if self.detached else "topic\n", "")
        if key == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        if key == ("status", "--porcelain"):
            return subprocess.CompletedProcess(args, 0, " M file.py\n" if self.dirty else "", "")
        if key == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
            return subprocess.CompletedProcess(args, 0 if self.upstream else 1, (self.upstream or "") + ("\n" if self.upstream else ""), "")
        if key == ("push",):
            return subprocess.CompletedProcess(args, self.push_code, "" if self.push_code else "ok\n", "rejected\n" if self.push_code else "")
        raise AssertionError("unexpected git call: " + repr(args))


class EndHeartbeat(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-end-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-end-wt-"))
        bind(self.root, "end-test")
        seat(self.root, "codex", "codex-end-test", worktree=str(self.wt))

    def _feed(self):
        path = self.root / ".convoy" / "feed.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_stop_hook_records_one_private_heartbeat_and_never_pushes(self):
        git = mock.Mock(side_effect=AssertionError("automatic heartbeat touched git"))
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.wt),
            "session_id": "vendor-secret-session",
            "turn_id": "vendor-secret-turn",
            "last_assistant_message": "private assistant transcript",
            "push": True,
        }
        first = end_task(root=self.root, hook_payload=payload, git_runner=git)
        second = end_task(root=self.root, hook_payload=payload, git_runner=git)
        self.assertTrue(first["ok"])
        self.assertTrue(second["deduplicated"])
        rows = [row for row in self._feed() if row.get("kind") == "heartbeat"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["from"], "codex-end-test")
        self.assertEqual(row["event"], "turn-end")
        self.assertFalse(row["push_requested"])
        raw = json.dumps(row)
        self.assertNotIn("vendor-secret-session", raw)
        self.assertNotIn("vendor-secret-turn", raw)
        self.assertNotIn("private assistant transcript", raw)
        git.assert_not_called()

    def test_hook_outside_convoy_is_a_successful_noop(self):
        other = Path(tempfile.mkdtemp(prefix="convoy-end-none-"))
        card = end_task(hook_payload={"hook_event_name": "Stop", "cwd": str(other)})
        self.assertTrue(card["ok"])
        self.assertTrue(card["skipped"])

    def test_explicit_push_refuses_dirty_state_without_running_push(self):
        git = FakeGit(dirty=True)
        card = end_task(root=self.root, cwd=self.wt, push=True, git_runner=git)
        self.assertFalse(card["ok"])
        self.assertEqual(card["push_status"], "refused")
        self.assertNotIn(["push"], [args for args, _ in git.calls])
        row = [r for r in self._feed() if r.get("kind") == "heartbeat"][-1]
        self.assertEqual(row["event"], "task-end")
        self.assertTrue(row["push_requested"])
        self.assertEqual(row["push_status"], "refused")

    def test_explicit_push_refuses_detached_or_no_upstream(self):
        for git in (FakeGit(detached=True), FakeGit(upstream=None)):
            with self.subTest(detached=git.detached, upstream=git.upstream):
                card = end_task(root=self.root, cwd=self.wt, push=True, git_runner=git)
                self.assertFalse(card["ok"])
                self.assertEqual(card["push_status"], "refused")
                self.assertNotIn(["push"], [args for args, _ in git.calls])

    def test_explicit_push_runs_exactly_plain_git_push(self):
        git = FakeGit()
        card = end_task(
            root=self.root, cwd=self.wt, summary="tests green", push=True, git_runner=git,
        )
        self.assertTrue(card["ok"])
        self.assertEqual(card["push_status"], "pushed")
        pushes = [args for args, _ in git.calls if args == ["push"]]
        self.assertEqual(pushes, [["push"]])
        row = [r for r in self._feed() if r.get("kind") == "heartbeat"][-1]
        self.assertEqual(row["summary"], "tests green")
        self.assertEqual(row["branch"], "topic")
        self.assertEqual(row["upstream"], "origin/topic")

    def test_cli_hook_stdout_is_only_empty_hook_json(self):
        payload = json.dumps({
            "hook_event_name": "Stop",
            "cwd": str(self.wt),
            "session_id": "s",
            "turn_id": "t",
        })
        output = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(output):
            code = main(["--root", str(self.root), "end", "--hook"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "{}\n")


if __name__ == "__main__":
    unittest.main()
