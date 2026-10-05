"""One session, several threads: a session holds one chair on each of any number of threads.

A session seated on one thread that launched a neuron on a second thread could not attach
there ("attached to <thread>; detach first"), so the neuron booted with no lead and no
launcher and had nobody to report to. Now attach (and a session joining itself) succeeds on
every thread, the card lists the other threads in `also_on`, and the hooks that run without
a root act on every thread the session sits on, from one process-table read. A command that
needs exactly one thread and finds several refuses with the list.

Every id is synthetic; roots and the Convoy home are temporary; no harness runs.
"""
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

from convoy import panes  # noqa: E402
from convoy.activity import neuron_id  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, read_id, seat  # noqa: E402
from convoy.inbox import enqueue, pending  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import lead_state  # noqa: E402

NATIVE = "synthetic-orchestrator-native"
CHAIN = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
         {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}
EPOCH = "1970-01-01T00:00:00.000000Z"


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _which(name):
    key = str(name).lower().removesuffix(".exe")
    return "C:\\Tools\\" + key + ".exe"


class TwoThreads(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-multi-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name, "CLAUDE_CODE_SESSION_ID": NATIVE})
        p.start()
        self.addCleanup(p.stop)
        for name in ("convoy.sessions.is_temp_root", "convoy.index.is_temp_root"):
            q = mock.patch(name, return_value=False)
            q.start()
            self.addCleanup(q.stop)
        for attr, value in (("_TEST_PROCS", CHAIN), ("_TEST_PID", 21)):
            q = mock.patch.object(panes, attr, value)
            q.start()
            self.addCleanup(q.stop)
        self.a = _git_repo()
        bind(self.a, "thread-a")
        self.b = _git_repo()
        bind(self.b, "thread-b")
        self.elsewhere = Path(tempfile.mkdtemp())   # the session's cwd: no thread's worktree

    def seat_session_on(self, root, sid):
        seat(root, "claude", sid, worktree=str(Path(tempfile.mkdtemp())), resume=NATIVE)
        return sid


class AttachOnASecondThread(TwoThreads):
    def test_a_session_on_thread_a_attaches_to_thread_b_and_lists_also_on(self):
        from convoy.sessions import attach_proven
        self.seat_session_on(self.a, "orch-a")
        me = panes.identify(self.b, cwd=str(self.elsewhere), env=os.environ, allow_unseated=True)
        card = attach_proven(self.b, self.elsewhere, me)
        self.assertTrue(card["ok"], card)
        self.assertIn(read_id(self.a), [x.get("convoy_id") for x in card["also_on"]] + card["also_on"])
        self.assertTrue(card["lead_taken"])

    def test_the_live_sequence_launch_on_b_records_the_launcher_and_names_it(self):
        from convoy.crew import add
        from convoy.launcher import resolve_launcher
        self.seat_session_on(self.a, "orch-a")
        resolved = resolve_launcher(self.b, env=os.environ, cwd=str(self.elsewhere), pid=21)
        self.assertEqual(resolved["kind"], "unseated", resolved)
        runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        with mock.patch("convoy.bringup.ensure_first_run", return_value=dict(FIRST_RUN)), \
             mock.patch("convoy.targeted_launch.ensure_first_run", return_value=dict(FIRST_RUN)), \
             mock.patch("convoy.bringup.shutil.which", side_effect=_which):
            card = add(self.b, "codex", None, runner=runner, window_runner=runner, launcher=resolved,
                       env={"WT_SESSION": "x"}, which=lambda n: "C:\\Tools\\wt.exe" if "wt" in str(n) else None,
                       platform_name="nt")
        self.assertTrue(card["ok"], card)
        chair = card["launcher"]["chair"]
        self.assertTrue(card["launcher"]["attached"])
        self.assertEqual(lead_state(self.b)["chair"], chair, "B's empty lead is taken")
        new = card["seats"][0]["session_id"]
        row = next(s for s in list_seats(self.b) if s["session_id"] == new)
        self.assertEqual(row["launched_by"], chair)
        self.assertIn(neuron_id(read_id(self.b), chair), row["boot_prompt"])
        self.assertNotIn("Launched by: unknown", row["boot_prompt"])


class HooksActOnEveryThread(TwoThreads):
    def setUp(self):
        super().setUp()
        self.seat_session_on(self.a, "orch-a")
        self.seat_session_on(self.b, "orch-b")
        enqueue(self.a, "orch-a", "synthetic message on a", to="claude")
        enqueue(self.b, "orch-b", "synthetic message on b", to="claude")

    def test_the_inbox_hook_delivers_both_threads_labelled_from_one_read(self):
        from convoy import inbox
        reads = []

        def table(**kw):
            reads.append(kw)
            return CHAIN, None

        with mock.patch.object(panes, "_TEST_PROCS", None), \
             mock.patch.object(panes, "_safe_enumerate", side_effect=table), \
             mock.patch.object(inbox, "_hook_payload_from_stdin", return_value={"hook_event_name": "PostToolUse"}), \
             mock.patch.object(inbox, "stamp_usage_row") as usage:   # a usage stamp would probe the vendor CLI
            out = inbox.hook_pretooluse(cwd=self.elsewhere)
        self.assertEqual(sorted(c.args[1] for c in usage.call_args_list), ["orch-a", "orch-b"], "per thread")
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("synthetic message on a", context)
        self.assertIn("synthetic message on b", context)
        self.assertIn("thread-a", context)
        self.assertIn("thread-b", context)
        self.assertEqual(len(reads), 1, "one process-table read for the hook")
        self.assertEqual((pending(self.a, "orch-a"), pending(self.b, "orch-b")), ([], []))

    def test_stop_heartbeats_both_threads(self):
        from convoy.end import end_task
        card = end_task(cwd=self.elsewhere, hook_payload={"hook_event_name": "Stop", "cwd": str(self.elsewhere)})
        self.assertTrue(card["ok"], card)
        for root, sid in ((self.a, "orch-a"), (self.b, "orch-b")):
            beats = [r for r in feed_since(root, EPOCH) if r.get("kind") == "heartbeat" and r.get("from") == sid]
            self.assertEqual(len(beats), 1, root)


class OneThreadCommandsRefuseWithTheList(TwoThreads):
    def setUp(self):
        super().setUp()
        self.seat_session_on(self.a, "orch-a")
        self.seat_session_on(self.b, "orch-b")

    def test_detach_without_a_thread_refuses_with_the_list(self):
        from convoy.sessions import detach_session
        card = detach_session(root=self.elsewhere, cwd=self.elsewhere)
        self.assertFalse(card["ok"], card)
        for root in (self.a, self.b):
            self.assertIn(read_id(root), card["error"])
        self.assertIn("--thread", card["error"])

    def test_whoami_with_no_root_refuses_with_the_list(self):
        from convoy.cli import main
        old = os.getcwd()
        os.chdir(self.elsewhere)
        self.addCleanup(os.chdir, old)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["whoami"])
        card = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(rc, 1, card)
        text = json.dumps(card)
        for root in (self.a, self.b):
            self.assertIn(read_id(root), text)
        self.assertIn("--root", text)

    def test_the_single_chair_helper_refuses_with_pass_root_or_thread(self):
        from convoy.sessions import proven_session_chair, proven_session_chairs
        hits = proven_session_chairs(self.elsewhere)
        self.assertEqual(sorted(str(r) for r, _ in hits), sorted(str(Path(p).resolve()) for p in (self.a, self.b)))
        with self.assertRaises(ValueError) as ctx:
            proven_session_chair(self.elsewhere)
        self.assertIn("pass --root or --thread", str(ctx.exception))


class OneUsageProbePerHarness(TwoThreads):
    def test_a_post_tool_use_on_several_threads_probes_each_harness_once(self):
        from convoy import inbox
        self.seat_session_on(self.a, "orch-a")
        self.seat_session_on(self.b, "orch-b")
        readings = []

        def reading(harness):
            readings.append(harness)
            return {"source": "synthetic", "as_of": "2026-01-01T00:00:00Z", "session_pct": 10, "week_pct": 20}

        with mock.patch.object(inbox, "_hook_payload_from_stdin", return_value={"hook_event_name": "PostToolUse"}), \
             mock.patch.object(inbox, "default_usage_reading", side_effect=reading):
            inbox.hook_pretooluse(cwd=self.elsewhere)
        self.assertEqual(readings, ["claude"], "one vendor probe per harness per hook")
        for root, sid in ((self.a, "orch-a"), (self.b, "orch-b")):
            rows = [r for r in feed_since(root, EPOCH) if r.get("kind") == "usage" and r.get("from") == sid]
            self.assertEqual(len(rows), 1, root)


if __name__ == "__main__":
    unittest.main()
