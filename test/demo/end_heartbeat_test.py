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
    def __init__(self, *, dirty=False, detached=False, upstream="origin/topic", push_code=0, pushed_paths=""):
        self.pushed_paths = pushed_paths
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
        if key == ("diff", "--name-only", "@{upstream}...HEAD"):
            return subprocess.CompletedProcess(args, 0, self.pushed_paths, "")
        if key == ("push",):
            return subprocess.CompletedProcess(args, self.push_code, "" if self.push_code else "ok\n", "rejected\n" if self.push_code else "")
        raise AssertionError("unexpected git call: " + repr(args))


class EndHeartbeat(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-end-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-end-wt-"))
        bind(self.root, "end-test")
        seat(self.root, "codex", "codex-end-test", worktree=str(self.wt))
        # A clean Stop now arms a waiter. The spawn is a seam so a suite
        # never leaves a real 10-minute process behind.
        patch = mock.patch("convoy.end._spawn_waiter", return_value={"spawned": True, "pid": 1})
        patch.start()
        self.addCleanup(patch.stop)
        # The hook runs under a codex body: its ancestry names the harness that may stamp.
        from convoy import panes
        procs = [{"pid": 900, "ppid": 700, "cmdline": "python -m convoy end --hook"},
                 {"pid": 700, "ppid": 1, "cmdline": "codex"}]
        for name, value in (("_TEST_PROCS", procs), ("_TEST_PID", 900)):
            body = mock.patch.object(panes, name, value)
            body.start()
            self.addCleanup(body.stop)

    def _feed(self):
        path = self.root / ".convoy" / "feed.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_stop_hook_records_one_private_heartbeat_and_never_pushes(self):
        # This reconciles the invariant rather than dropping it: the automatic
        # path now READS git, because the rolling handoff and the pulse's
        # last_commit are derived from branch/HEAD/dirty. It still never
        # MUTATES git - the assertion below is that no writing command runs,
        # whatever a hostile payload asks for.
        git = FakeGit()
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
        ran = [tuple(args) for args, _cwd in git.calls]
        self.assertNotIn(("push",), ran, "the automatic path may read git; it may never write")
        self.assertTrue(all(a[0] in ("rev-parse", "symbolic-ref", "status") for a in ran), ran)

    def test_stop_hook_stamps_resume_for_matching_seat_only(self):
        """Convoy has held this id in its hand at every Stop since the
        beginning and dropped it on purpose - the rule was written for the
        feed and is right for the feed, but nobody wrote the seat-side
        counterpart, so every seat row had resume null and every relaunch
        booted a first run. The seat is where graph.py
        already says tokens live. Matched by cwd, never by recency."""
        from convoy.convoy import list_seats, seat as seat_row

        other_wt = Path(tempfile.mkdtemp(prefix="convoy-end-other-"))
        seat_row(self.root, "claude", "claude-elsewhere", worktree=str(other_wt))
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.wt),
            "session_id": "vendor-observed-1",
            "turn_id": "t-1",
        }
        card = end_task(root=self.root, hook_payload=payload)
        self.assertTrue(card["ok"], card)
        rows = {r["session_id"]: r for r in list_seats(self.root)}
        self.assertEqual(rows["codex-end-test"]["resume"], "vendor-observed-1")
        self.assertEqual(rows["codex-end-test"]["resume_for"], "codex")
        self.assertIsNone(rows["claude-elsewhere"]["resume"],
                          "only the chair whose worktree matched may learn an id")

        # Null until observed, and a second Stop from the same life does not
        # churn the row.
        end_task(root=self.root, hook_payload={**payload, "turn_id": "t-1b"})
        rows = {r["session_id"]: r for r in list_seats(self.root)}
        self.assertEqual(rows["codex-end-test"]["resume"], "vendor-observed-1")
        # A codex Stop from this exact worktree with another id is a restarted
        # Codex: the live body is the one taking turns, so its id replaces the
        # old one and the incarnation moves on.
        end_task(root=self.root, hook_payload={**payload, "session_id": "vendor-observed-2", "turn_id": "t-2"})
        rows = {r["session_id"]: r for r in list_seats(self.root)}
        self.assertEqual(rows["codex-end-test"]["resume"], "vendor-observed-2")
        self.assertIsNone(rows["codex-end-test"].get("incarnation"), "the incarnation is the pane host's")
        self.assertIsNone(rows["claude-elsewhere"]["resume"])

    def test_stop_hook_never_writes_session_id_to_feed(self):
        """The feed rule is unchanged: the id goes on the seat row, and
        the feed still sees it only as hash material."""
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.wt),
            "session_id": "vendor-must-not-ride",
            "turn_id": "t-9",
        }
        end_task(root=self.root, hook_payload=payload)
        raw = json.dumps(self._feed())
        self.assertNotIn("vendor-must-not-ride", raw)

    def test_hook_outside_convoy_is_a_successful_noop(self):
        other = Path(tempfile.mkdtemp(prefix="convoy-end-none-"))
        card = end_task(hook_payload={"hook_event_name": "Stop", "cwd": str(other)})
        self.assertTrue(card["ok"])
        self.assertTrue(card["skipped"])

    def test_claude_stop_without_turn_id_still_deduplicates_privately(self):
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.wt),
            "session_id": "claude-private-session",
            "last_assistant_message": "same private final answer",
        }
        first = end_task(root=self.root, hook_payload=payload)
        second = end_task(root=self.root, hook_payload=payload)
        self.assertTrue(first["ok"])
        self.assertTrue(second["deduplicated"])
        rows = [row for row in self._feed() if row.get("kind") == "heartbeat"]
        self.assertEqual(len(rows), 1)
        raw = json.dumps(rows[0])
        self.assertNotIn("claude-private-session", raw)
        self.assertNotIn("same private final answer", raw)

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

    def test_a_push_carrying_convoy_written_files_warns_and_names_them(self):
        git = FakeGit(pushed_paths="src/app.py\n.codex/hooks.json\n.claude/convoy-root\n.claude/settings.local.json\n")
        card = end_task(root=self.root, cwd=self.wt, push=True, git_runner=git)
        self.assertEqual(card["push_status"], "pushed", "a warning, not a refusal")
        self.assertEqual(card["convoy_files"], [".claude/convoy-root", ".claude/settings.local.json", ".codex/hooks.json"])
        self.assertIn("Convoy", card["warning"])

    def test_a_push_without_convoy_files_says_nothing(self):
        card = end_task(root=self.root, cwd=self.wt, push=True, git_runner=FakeGit(pushed_paths="src/app.py\n"))
        self.assertEqual(card["push_status"], "pushed")
        self.assertNotIn("convoy_files", card)

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


class StopBlocksAndPulses(unittest.TestCase):
    """A Stop is the only moment Convoy is certain a neuron is listening.

    Without it a chair sat idle with rows waiting because only Grok's
    Stop path blocked; Claude and Codex ended their turn and went quiet. The
    same Stop is also the cheapest honest pulse there is - it fires from
    inside the body - and the cheapest place to rewrite a handoff, because
    every fact in it is derivable and none of it needs the model's attention.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-stop-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-stop-wt-"))
        bind(self.root, "stop-test")
        seat(self.root, "codex", "c1", worktree=str(self.wt))
        from convoy.convoy import update_seat
        update_seat(self.root, "c1", incarnation=2, resume="rollout-session-1", resume_for="codex")
        self.spawned = []
        patch = mock.patch("convoy.end._spawn_waiter",
                           side_effect=lambda *a, **k: self.spawned.append((a, k)) or {"spawned": True})
        patch.start()
        self.addCleanup(patch.stop)

    def _feed(self):
        path = self.root / ".convoy" / "feed.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _stop(self, turn="t1", **kw):
        # The chair's own recorded id: a different one is a restarted Codex (observe_resume).
        payload = {"hook_event_name": "Stop", "cwd": str(self.wt), "session_id": "rollout-session-1", "turn_id": turn}
        return end_task(root=self.root, hook_payload=payload, git_runner=FakeGit(), **kw)

    def test_stop_with_pending_rows_blocks_with_reason(self):
        from convoy.inbox import enqueue, pending
        enqueue(self.root, "c1", "please rebase onto the lead branch", to="codex", label="synapse")
        card = self._stop()
        self.assertEqual(card["hook"]["decision"], "block", card)
        self.assertIn("please rebase onto the lead branch", card["hook"]["reason"])
        self.assertEqual(pending(self.root, "c1"), [], "a blocked Stop delivers the rows, it does not re-serve them")
        self.assertEqual(self.spawned, [], "a blocked turn keeps working; it needs no waiter")

    def test_stop_without_rows_prints_empty_object_and_spawns_wait(self):
        card = self._stop()
        self.assertEqual(card["hook"], {})
        self.assertEqual(len(self.spawned), 1, self.spawned)
        output = io.StringIO()
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(self.wt),
                              "session_id": "rollout-session-1", "turn_id": "t2"})
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(output):
            code = main(["--root", str(self.root), "end", "--hook"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "{}\n")

    def test_stop_rewrites_rolling_handoff_from_derivable_facts(self):
        from convoy.inbox import enqueue
        enqueue(self.root, "c1", "one waiting row", to="codex", label="synapse")
        self._stop()
        path = self.root / ".convoy" / "handoff" / "c1.rolling.md"
        text = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode("utf-8")), 4096, "the rolling handoff is bounded")
        for fact in ("topic", "abc123", "incarnation 2", "resume: present"):
            self.assertIn(fact, text, text)
        self.assertNotIn("rollout-session-1", text, "a vendor session id is never written down in prose")
        # Rewritten, never appended: a second Stop leaves one copy of the facts.
        self._stop(turn="t2")
        self.assertEqual(path.read_text(encoding="utf-8").count("## chair c1"), 1)

    def test_stop_writes_the_pulse_with_its_source(self):
        from convoy.pulse import read_pulse
        self._stop()
        row = read_pulse(self.root, "c1")
        self.assertEqual(row["pulse_source"], "stop")
        self.assertEqual(row["incarnation"], 2)
        self.assertEqual(row["last_commit"], {"sha": "abc123", "branch": "topic"})

    def test_stop_at_quota_threshold_writes_threshold_row_and_blocks_once(self):
        reading = {"session_pct": 97, "week_pct": 12,
                   "resets": {"session": "at 2026-09-17T18:00:00Z", "week": "at 2026-09-20T00:00:00Z"},
                   "window_minutes": {"session": 300, "week": 10080},
                   "as_of": "2026-09-17T16:00:00Z", "source": "codex rollout snapshot"}
        with mock.patch("convoy.end._seat_quota", return_value=reading):
            card = self._stop()
            self.assertEqual(card["hook"]["decision"], "block", card)
            self.assertIn("handoff", card["hook"]["reason"])
            self.assertIn("97", card["hook"]["reason"])
            rows = [r for r in self._feed() if r.get("kind") == "threshold"]
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0]["chair"], "c1")
            self.assertEqual(rows[0]["harness"], "codex")
            self.assertEqual(rows[0]["window"], "session")
            self.assertEqual(rows[0]["used_percent"], 97)
            self.assertEqual(rows[0]["incarnation"], 2)
            self.assertEqual(rows[0]["resets_at"], "at 2026-09-17T18:00:00Z")
            # Once per (chair, incarnation, resets_at): the next Stop of the
            # same life inside the same window adds nothing.
            self._stop(turn="t2")
            self.assertEqual(len([r for r in self._feed() if r.get("kind") == "threshold"]), 1)
        self.assertEqual(self.spawned, [], "a chair at the ceiling waits for a human, not for a row")

    def test_quota_below_threshold_writes_no_row_and_still_waits(self):
        reading = {"session_pct": 40, "week_pct": 12, "resets": {"session": None, "week": None},
                   "window_minutes": {"session": 300, "week": 10080},
                   "as_of": "2026-09-17T16:00:00Z", "source": "codex rollout snapshot"}
        with mock.patch("convoy.end._seat_quota", return_value=reading):
            self._stop()
        self.assertEqual([r for r in self._feed() if r.get("kind") == "threshold"], [])
        self.assertEqual(len(self.spawned), 1)


if __name__ == "__main__":
    unittest.main()
