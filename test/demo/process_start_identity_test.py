"""Process identity carries a start time.

The OS reuses process ids. A long-running system process can list a parent pid that died
long ago and now belongs to an unrelated, much newer process. An ancestry walk that trusts a
bare ppid then splices an unrelated tree onto the caller's chain: a second harness appears
"outside" the caller, the session reads as nested, and attach, add and launch refuse a real,
independent session. The same reuse makes a liveness probe by bare pid answer for a process
that is not the recorded one.

The rule: a parent is an ancestor only when it started no later than its child; a repeated
pid ends the walk; a start time that cannot be read ends the walk (toward "no further
ancestor", never toward "nested"); and every recorded body is alive only when its pid AND
its recorded start time answer.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat
from convoy.panes import hook_body, identify, match_processes


def walk_ancestry(by_pid, pid):
    from convoy.panes import walk_ancestry as walk
    return walk(by_pid, pid)

NATIVE_ID = "synthetic-native-session"


def _p(pid, ppid, cmdline, started):
    return {"pid": pid, "ppid": ppid, "cmdline": cmdline, "cwd": None, "started": started}


def _spliced_table():
    """The caller (a shell under a fresh claude) descends from a terminal whose parent is a
    long-running system process. That system process names a parent pid which died long ago
    and is now held by a new node process, itself a child of an unrelated claude."""
    return [
        _p(5, 0, "system-init", 10),
        _p(40, 5, "service-host", 100),             # long-running; its real parent is gone
        _p(900, 800, "node mcp-server.js", 5000),   # holds the dead parent's pid, created later
        _p(800, 700, "claude.exe", 4000),           # an unrelated claude session
        _p(700, 5, "terminal.exe", 300),
        _p(10, 40, "terminal.exe", 200),
        _p(20, 10, "claude.exe", 6000),             # the caller's own harness
        _p(30, 20, "bash -c convoy attach", 6100),  # the caller
    ]


def _with_reused_parent(rows):
    out = []
    for r in rows:
        r = dict(r)
        if r["pid"] == 40:
            r["ppid"] = 900   # the dead parent pid, now reused by the node process
        out.append(r)
    return out


class AncestryWalk(unittest.TestCase):
    def test_younger_parent_is_not_an_ancestor(self):
        by_pid = {p["pid"]: p for p in _with_reused_parent(_spliced_table())}
        chain = [p["pid"] for p in walk_ancestry(by_pid, 30)]
        self.assertEqual(chain, [30, 20, 10, 40])

    def test_a_cycle_terminates_with_distinct_pids(self):
        rows = [_p(1, 3, "a", None), _p(2, 1, "b", None), _p(3, 2, "c", None)]
        for r in rows:
            r.pop("started")   # a table that carries no start times at all
        by_pid = {p["pid"]: p for p in rows}
        chain = [p["pid"] for p in walk_ancestry(by_pid, 3)]
        self.assertEqual(chain, [3, 2, 1])

    def test_a_self_parented_process_is_one_entry(self):
        by_pid = {0: _p(0, 0, "idle", 0)}
        self.assertEqual([p["pid"] for p in walk_ancestry(by_pid, 0)], [0])

    def test_an_unreadable_start_time_ends_the_walk(self):
        rows = [_p(1, 0, "claude.exe", 1), _p(2, 1, "claude.exe", None), _p(3, 2, "bash", 9)]
        by_pid = {p["pid"]: p for p in rows}
        self.assertEqual([p["pid"] for p in walk_ancestry(by_pid, 3)], [3])

    def test_equal_start_times_still_link(self):
        rows = [_p(1, 0, "claude.exe", 5), _p(2, 1, "bash", 5)]
        by_pid = {p["pid"]: p for p in rows}
        self.assertEqual([p["pid"] for p in walk_ancestry(by_pid, 2)], [2, 1])


class ReusedParentIsNotNested(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "start-time-thread")
        self.env = {"CLAUDE_CODE_SESSION_ID": NATIVE_ID}

    def test_reused_parent_pid_does_not_fake_a_second_harness_on_attach(self):
        me = identify(self.root, pid=30, procs=_with_reused_parent(_spliced_table()),
                      cwd=str(self.root), env=self.env, allow_unseated=True)
        self.assertTrue(me["ok"], me)
        self.assertEqual(me["harness"], "claude")
        self.assertEqual(me["harness_pid"], 20)
        self.assertEqual(me["native_session"]["id"], NATIVE_ID)
        self.assertNotIn("nested", str(me.get("ask") or ""))

    def test_reused_parent_pid_proves_the_seated_chair(self):
        seat(self.root, "claude", "real-chair", worktree=str(self.root / "wt"), resume=NATIVE_ID)
        me = identify(self.root, pid=30, procs=_with_reused_parent(_spliced_table()),
                      cwd=str(self.root), env=self.env)
        self.assertEqual((me["ok"], me["chair"], me["harness_pid"]), (True, "real-chair", 20), me)

    def test_hook_body_is_not_nested_through_a_reused_parent(self):
        body = hook_body(pid=30, procs=_with_reused_parent(_spliced_table()))
        self.assertEqual((body["harness"], body["nested"]), ("claude", False))

    def test_a_cycle_through_the_callers_own_harness_is_not_nested(self):
        rows = _with_reused_parent(_spliced_table())
        for r in rows:
            if r["pid"] == 900:
                r["ppid"] = 20    # loops back into the caller's own claude
            r.pop("started")      # no start times: only the cycle check can stop it
        me = identify(self.root, pid=30, procs=rows, cwd=str(self.root), env=self.env, allow_unseated=True)
        self.assertTrue(me["ok"], me)
        self.assertEqual(me["harness_pid"], 20)
        self.assertIs(hook_body(pid=30, procs=rows)["nested"], False)

    def test_a_genuinely_nested_codex_exec_is_still_nested(self):
        rows = [
            _p(1, 0, "terminal.exe", 10),
            _p(20, 1, "codex.exe --model synthetic", 100),
            _p(25, 20, "bash -c codex", 200),
            _p(30, 25, "codex.exe exec review", 300),
            _p(31, 30, "python hook.py", 400),
        ]
        body = hook_body(pid=31, procs=rows)
        self.assertEqual((body["harness"], body["nested"]), ("codex", True))
        me = identify(self.root, pid=31, procs=rows, cwd=str(self.root),
                      env={"CODEX_THREAD_ID": NATIVE_ID}, allow_unseated=True)
        self.assertFalse(me["ok"])
        self.assertIn("nested", me["ask"])


class EnumeratorsCarryStartTimes(unittest.TestCase):
    def test_windows_enumerator_reads_creation_time(self):
        from convoy import panes
        payload = json.dumps([{"ProcessId": 7, "ParentProcessId": 3, "CommandLine": "x", "Started": 1234567},
                              {"ProcessId": 8, "ParentProcessId": 7, "CommandLine": "y", "Started": None}])
        done = mock.Mock(returncode=0, stdout=payload, stderr="")
        with mock.patch("convoy.panes.shutil.which", return_value="powershell"), \
                mock.patch("convoy.panes.subprocess.run", return_value=done) as run:
            rows = panes._enumerate_windows(attempts=1, timeout=5)
        self.assertIn("CreationDate", run.call_args[0][0][-1])
        self.assertEqual([(r["pid"], r["started"]) for r in rows], [(7, 1234567), (8, None)])

    def test_proc_stat_parse_reads_field_22(self):
        from convoy.panes import _parse_proc_stat
        fields = ["S", "41"] + [str(i) for i in range(5, 22)] + ["987654", "0", "0"]
        stat = "42 (some (odd) name) " + " ".join(fields)
        self.assertEqual(_parse_proc_stat(stat), (41, 987654))


class RecordedBodyNeedsItsStartTime(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "start-time-thread")
        seat(self.root, "codex", "c-1", worktree=str(self.root / "wt"))

    def test_pid_rung_rejects_a_reused_pid(self):
        update_seat(self.root, "c-1", harness_pid=40, harness_started="111", incarnation=1,
                    process_state="running")
        procs = [_p(40, 1, "node /x/codex.js", 2220)]   # same pid, another process
        chair = {c["session_id"]: c for c in match_processes(self.root, procs)["chairs"]}["c-1"]
        self.assertNotEqual([b.get("via") for b in chair["bodies"]], ["pid"])

    def test_pid_rung_accepts_the_recorded_process(self):
        update_seat(self.root, "c-1", harness_pid=40, harness_started="2220", incarnation=1,
                    process_state="running")
        procs = [_p(40, 1, "node /x/codex.js", 2220)]
        chair = {c["session_id"]: c for c in match_processes(self.root, procs)["chairs"]}["c-1"]
        self.assertEqual([b.get("via") for b in chair["bodies"]], ["pid"])

    def test_occupancy_false_when_recorded_start_differs(self):
        from convoy.relaunch import chair_occupancy
        update_seat(self.root, "c-1", harness_pid=40, harness_started="132000000000000000", incarnation=1,
                    process_state="running")
        row = [s for s in list_seats(self.root) if s.get("session_id") == "c-1"][-1]
        with mock.patch("convoy.pane_host.process_started", return_value="133000000000000000"):
            occ = chair_occupancy(self.root, row, alive=lambda _pid: True)
        self.assertIs(occ["occupied"], False)
        self.assertIn("pid-reused", occ["evidence"])

    def test_occupancy_true_when_recorded_start_matches(self):
        from convoy.relaunch import chair_occupancy
        update_seat(self.root, "c-1", harness_pid=40, harness_started="1", incarnation=1,
                    process_state="running")
        row = [s for s in list_seats(self.root) if s.get("session_id") == "c-1"][-1]
        with mock.patch("convoy.pane_host.process_started", return_value="1"):
            occ = chair_occupancy(self.root, row, alive=lambda _pid: True)
        self.assertIs(occ["occupied"], True)

    def test_legacy_record_without_start_reads_reused_when_the_process_is_newer_than_the_launch(self):
        from convoy.relaunch import chair_occupancy
        update_seat(self.root, "c-1", harness_pid=40, incarnation=1, process_state="running",
                    launched_at="2020-01-01T00:00:00.000000Z")
        row = [s for s in list_seats(self.root) if s.get("session_id") == "c-1"][-1]
        with mock.patch("convoy.pane_host.process_started", return_value="x"), \
                mock.patch("convoy.pane_host.started_epoch", return_value=1_900_000_000.0):
            occ = chair_occupancy(self.root, row, alive=lambda _pid: True)
        self.assertIs(occ["occupied"], False)
        self.assertIn("pid-reused", occ["evidence"])


class ReusedPaneHostPidIsNotAlive(unittest.TestCase):
    def setUp(self):
        from convoy.lifecycle import join
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "start-time-thread")
        self.worktree = Path(tempfile.mkdtemp())
        join(self.root, "codex", session_id="hosted", worktree=str(self.worktree))

    def _state(self, **extra):
        from convoy.pane_host import host_state_path
        path = host_state_path(self.root, "hosted")
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {"session_id": "hosted", "status": "running", "host_pid": 4242, "child_pid": 5252,
                 "incarnation": 1, "host_started": "111", "child_started": "112"}
        state.update(extra)
        path.write_text(json.dumps(state), encoding="utf-8")

    def test_host_alive_rejects_a_reused_pid(self):
        from convoy.pane_host import host_alive
        with mock.patch("convoy.pane_host.pid_alive", return_value=True), \
                mock.patch("convoy.pane_host.process_started", return_value="222"):
            self.assertIs(host_alive(4242, "111"), False)
            self.assertIs(host_alive(4242, "222"), True)

    def test_close_on_a_reused_host_pid_refuses_before_consent(self):
        from convoy.pane_host import close_managed_pane
        self._state()
        with mock.patch("convoy.pane_host.pid_alive", return_value=True), \
                mock.patch("convoy.pane_host.process_started", return_value="222"):
            card = close_managed_pane(self.root, "hosted")
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "host-exited")
        self.assertNotIn("consent_request", card)

    def test_nudge_does_not_identify_a_reused_host_pid(self):
        from convoy.nudge import identify_target
        self._state()
        no_body = lambda *_a, **_k: {"ok": True, "chairs": [{"session_id": "hosted", "bodies": [],
                                                              "live": False, "live_reason": "none"}],
                                    "unassigned": []}
        with mock.patch("convoy.pane_host.pid_alive", return_value=True), \
                mock.patch("convoy.nudge.pid_alive", return_value=True), \
                mock.patch("convoy.pane_host.process_started", return_value="222"):
            card = identify_target(self.root, "hosted", panes_fn=no_body,
                                   windows_fn=lambda *_a, **_k: [], leader_fn=lambda: {"available": False})
        self.assertNotEqual(card.get("adapter"), "pane-host", card)

    def test_identify_ignores_a_host_record_whose_pid_was_reused(self):
        from convoy.lifecycle import join
        join(self.root, "claude", session_id="claude-hosted", worktree=str(self.worktree / "c"))
        from convoy.pane_host import host_state_path
        path = host_state_path(self.root, "claude-hosted")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": "claude-hosted", "status": "running", "host_pid": 60,
                                    "child_pid": 61, "host_started": "50", "child_started": "51"}),
                        encoding="utf-8")
        procs = [_p(1, 0, "terminal.exe", 1), _p(61, 1, "claude.exe", 9000), _p(70, 61, "bash", 9100)]
        me = identify(self.root, pid=70, procs=procs, cwd=str(self.root), env={})
        self.assertNotEqual(me.get("via"), "pane-host", me)

    def test_identify_accepts_a_host_record_whose_start_matches(self):
        from convoy.lifecycle import join
        join(self.root, "claude", session_id="claude-hosted", worktree=str(self.worktree / "c"))
        from convoy.pane_host import host_state_path
        path = host_state_path(self.root, "claude-hosted")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": "claude-hosted", "status": "running", "host_pid": 60,
                                    "child_pid": 61, "host_started": "50", "child_started": "9000"}),
                        encoding="utf-8")
        procs = [_p(1, 0, "terminal.exe", 1), _p(61, 1, "claude.exe", 9000), _p(70, 61, "bash", 9100)]
        me = identify(self.root, pid=70, procs=procs, cwd=str(self.root), env={})
        self.assertEqual((me.get("chair"), me.get("via")), ("claude-hosted", "pane-host"), me)


class HostRecordsStartTimes(unittest.TestCase):
    @mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe")
    def test_run_host_records_host_and_child_start_times(self, _which):
        from convoy.lifecycle import join
        from convoy.pane_host import host_state_path, run_host
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "start-time-thread")
        wt = Path(tempfile.mkdtemp())
        join(root, "codex", session_id="hosted", worktree=str(wt))

        class FakeProcess:
            pid = 303

            def poll(self):
                return 0

        starts = {303: "child-start"}
        with mock.patch("convoy.pane_host.process_started",
                        side_effect=lambda pid: starts.get(int(pid), "host-start")):
            run_host(root, "hosted", popen=lambda *_a, **_k: FakeProcess(),
                     terminate=lambda _p: None, sleep=lambda _s: None)
        state = json.loads(host_state_path(root, "hosted").read_text(encoding="utf-8"))
        self.assertEqual((state["host_started"], state["child_started"]), ("host-start", "child-start"))
        row = [s for s in list_seats(root) if s.get("session_id") == "hosted"][-1]
        self.assertEqual(row.get("harness_started"), "child-start")
        self.assertEqual(row.get("pane_host_started"), "host-start")


if __name__ == "__main__":
    unittest.main()
