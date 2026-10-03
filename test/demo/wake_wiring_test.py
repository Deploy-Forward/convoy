"""Wiring the wake dispatcher into a running Convoy, behind a per-root opt-in.

  the switch      .convoy/wake/enabled, written by `convoy wake enable`; absent on every root today,
                  and while it is absent nothing here changes anything
  the service     inside the supervised MCP origin: one dispatcher thread per enabled root, started
                  after the listener binds and stopped when it exits; a loop that raises is restarted
  the lock        an OS lock on an open handle to .convoy/wake/dispatcher.lock, held for the dispatcher
                  thread's life: one holder however many processes race, released by the OS when the
                  holder dies; the file's {pid, started, host} is for status only
  the waiter      on an enabled root it watches only .convoy/wake/inbox/<digest>/, so a dispatcher
                  fire is the only wake; its wait file names its owner (session or hook), and only an
                  unexpired waiter the session runs itself counts as armed
  the Stop hook   on an enabled root, a Claude chair with no armed waiter is told once to arm one

Every route is a fake or a folder write. Nothing is spawned but a sleeping stand-in process for the
lock, every id is synthetic and every root is a temporary folder.
"""
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[2] / "src")
sys.path.insert(0, SRC)

from convoy.cli import main  # noqa: E402
from convoy.convoy import bind, ensure_id, seat  # noqa: E402
from convoy.end import end_task  # noqa: E402
from convoy.inbox import enqueue  # noqa: E402
from convoy.pulse import write_pulse  # noqa: E402
from convoy.wait import (  # noqa: E402
    ARMED_TIMEOUT_S,
    DEFAULT_TIMEOUT_S,
    read_wait_file,
    run,
    session_waiter_armed,
    wait_path,
    write_wait_file,
)
from convoy.wake_dispatch import RouteError, cursor_path, outbox_path, read_outbox  # noqa: E402
from convoy.wake_local import (  # noqa: E402
    disable,
    drop_pointer,
    enable,
    enabled_path,
    is_enabled,
    pending_pointers,
    pointer_dir,
    take_pointers,
)
from convoy.wake_routes import reachability_detail, register_route  # noqa: E402
from convoy.wake_service import (  # noqa: E402
    LocalRoutes,
    WakeService,
    acquire_lock,
    alerts_path,
    lock_path,
)

CHAIR = "neuron-b-thread"
NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def tok(n):
    return format(n, "032x")


def pointer(n=1, target=CHAIR):
    return {"v": 1, "wake_id": "wk_" + format(n, "016x"), "reason": "send", "target": target,
            "token": tok(n), "from": "neuron-a-thread", "from_neuron": None,
            "stamp": {"device": None, "verified_by": "environment"}, "thread": None,
            "ts": iso(NOW), "read_with": "inbox(chair)"}


def lock_info(root):
    from convoy.wake_service import lock_info as info
    return info(root)


def listening_wait_file(root, chair):
    from convoy.wait import listening_wait_file as listening
    return listening(root, chair)


def race(code, n, root):
    """Run `code` in n processes that start together; `code` sees `W` (0..n-1) and `R` (the root)."""
    script = ("import sys, time, json; sys.path.insert(0, %r)\n"
              "from pathlib import Path\n"
              "W = int(sys.argv[1]); R = Path(sys.argv[2])\n"
              "while not (R / 'go').exists(): time.sleep(0.005)\n" % SRC) + code
    procs = [subprocess.Popen([sys.executable, "-c", script, str(w), str(root)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for w in range(n)]
    time.sleep(0.5)
    (Path(root) / "go").write_text("go", encoding="utf-8")
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        if p.returncode != 0:
            raise AssertionError(err)
        outs.append(out)
    return outs


def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


class Root(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)


class TheSwitch(Root):
    def test_a_root_is_not_enabled_until_a_person_enables_it(self):
        self.assertFalse(is_enabled(self.root))
        row = enable(self.root, by="person")
        self.assertTrue(is_enabled(self.root))
        self.assertEqual(row["enabled_by"], "person")
        self.assertTrue(row["enabled_at"])
        self.assertTrue(disable(self.root))
        self.assertFalse(is_enabled(self.root))
        self.assertFalse(enabled_path(self.root).exists())

    def test_enable_refuses_an_empty_author(self):
        with self.assertRaises(ValueError):
            enable(self.root, by="  ")
        self.assertFalse(is_enabled(self.root))

    def cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--root", str(self.root), "wake", *argv])
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_the_cli_enables_reports_and_disables(self):
        code, card = self.cli("status")
        self.assertEqual(code, 0)
        self.assertFalse(card["enabled"])
        code, card = self.cli("enable", "--by", "person")
        self.assertEqual((code, card["ok"], card["enabled"]), (0, True, True))
        register_route(self.root, CHAIR, "waiter", registered_by="person")
        code, card = self.cli("status")
        self.assertTrue(card["enabled"])
        self.assertEqual(card["enabled_by"], "person")
        self.assertIsNone(card["lock"])
        self.assertIn(CHAIR, card["routes"])
        self.assertEqual(card["routes"][CHAIR]["route"], "waiter")
        for key in ("cursor", "feed_bytes", "lag_bytes", "outbox", "alerts"):
            self.assertIn(key, card)
        code, card = self.cli("disable")
        self.assertEqual((code, card["enabled"]), (0, False))


class ThePointerFolder(Root):
    def test_a_pointer_is_a_file_per_wake_with_no_body(self):
        path = drop_pointer(self.root, pointer(1))
        self.assertEqual(path.parent, pointer_dir(self.root, CHAIR))
        self.assertEqual(path.name, "wk_" + format(1, "016x") + ".json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), pointer(1))
        drop_pointer(self.root, pointer(1))  # a refire of the same wake is the same file
        self.assertEqual(len(pending_pointers(self.root, CHAIR)), 1)

    def test_two_takers_take_each_of_300_pointers_exactly_once(self):
        for n in range(300):
            drop_pointer(self.root, pointer(n + 1))
        outs = race("from convoy.wake_local import take_pointers, pending_pointers\n"
                    "got = []\n"
                    "while True:\n"
                    "    rows = take_pointers(R, %r)\n"
                    "    got += [r['wake_id'] for r in rows]\n"
                    "    if not rows and not pending_pointers(R, %r): break\n"
                    "print(json.dumps(got))\n" % (CHAIR, CHAIR), 2, self.root)
        first, second = (json.loads(out.strip().splitlines()[-1]) for out in outs)
        self.assertEqual(len(first) + len(second), 300, "every pointer taken once in total")
        self.assertEqual(set(first) & set(second), set(), "no pointer taken by both")

    def test_a_stalled_taker_never_releases_or_moves_on_another_taker_s_claim(self):
        import convoy.wake_local as wl
        path = drop_pointer(self.root, pointer(1))
        claim, nonce = wl._claim(path)
        claim.write_text("another-taker", encoding="utf-8")  # A stalled; B cleared it and claimed it
        self.assertFalse(wl._still_mine(claim, nonce))
        wl._release(claim, nonce)
        self.assertEqual(claim.read_text(encoding="utf-8"), "another-taker", "B's claim is left alone")
        claim.unlink()

    def test_a_refire_after_a_take_is_taken_again(self):
        drop_pointer(self.root, pointer(1))
        self.assertEqual(len(take_pointers(self.root, CHAIR)), 1)
        drop_pointer(self.root, pointer(1))  # the same wake, refired
        self.assertEqual(len(take_pointers(self.root, CHAIR)), 1)

    def test_a_refire_onto_a_pointer_held_open_is_retried(self):
        import convoy.wake_local as wl
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) <= 2:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)

        with mock.patch.object(wl.os, "replace", flaky):
            drop_pointer(self.root, pointer(1))
        self.assertEqual(len(pending_pointers(self.root, CHAIR)), 1)
        self.assertEqual([p.name for p in pointer_dir(self.root, CHAIR).iterdir() if ".tmp-" in p.name], [])

    def test_a_pointer_for_a_target_with_no_name_is_refused(self):
        with self.assertRaises(ValueError):
            drop_pointer(self.root, {**pointer(1), "target": ""})


class TheWaiter(Root):
    """On an enabled root the waiter wakes only on a dispatcher fire; elsewhere, as today."""

    def wait(self, *, owner="session", timeout=3.0):
        return run(self.root, CHAIR, timeout=timeout, owner=owner, clock=itertools.count(0.0, 1.0).__next__,
                   sleep=lambda s: None, now=lambda: iso(NOW), write=lambda *a, **k: None)

    def test_a_disabled_root_keeps_today_s_waiter(self):
        drop_pointer(self.root, pointer(1))
        card = self.wait()
        self.assertTrue(card["timed_out"], "a pointer is nothing to a waiter on a root that never opted in")
        enqueue(self.root, CHAIR, "body", to="claude", token=tok(2))
        card = self.wait()
        self.assertEqual(card["n"], 1)
        self.assertNotIn("owner", read_wait_file(self.root, CHAIR))

    def test_on_an_enabled_root_an_inbox_row_alone_is_not_a_wake(self):
        enable(self.root, by="person")
        enqueue(self.root, CHAIR, "body", to="claude", token=tok(2))
        self.assertTrue(self.wait()["timed_out"])

    def test_the_session_s_waiter_takes_the_pointer_and_names_the_wake(self):
        enable(self.root, by="person")
        drop_pointer(self.root, pointer(1))
        card = self.wait()
        self.assertFalse(card["timed_out"])
        self.assertEqual(card["n"], 1)
        self.assertEqual(card["pointers"][0]["token"], tok(1))
        self.assertEqual(card["pending"], [], "both fields, on every card")
        self.assertEqual(card["next"], "inbox --drain --seat " + CHAIR)
        self.assertEqual(pending_pointers(self.root, CHAIR), [], "taken: moved to notified")
        self.assertTrue((pointer_dir(self.root, CHAIR) / "notified" / ("wk_" + format(1, "016x") + ".json")).is_file())
        row = read_wait_file(self.root, CHAIR, owner="session")
        self.assertEqual(row["owner"], "session")
        self.assertTrue(row["ended"], "a waiter that exits says so: it is no longer armed")

    def test_the_hook_s_waiter_leaves_the_pointer_for_the_session(self):
        enable(self.root, by="person")
        drop_pointer(self.root, pointer(1))
        card = self.wait(owner="hook")
        self.assertEqual(card["n"], 1)
        self.assertEqual(len(pending_pointers(self.root, CHAIR)), 1)
        self.assertEqual(read_wait_file(self.root, CHAIR)["owner"], "hook")
        self.assertIsNone(read_wait_file(self.root, CHAIR, owner="session"))

    def test_disabling_the_root_returns_an_armed_waiter_to_today_s_behaviour(self):
        enable(self.root, by="person")
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            if len(polls) == 2:
                disable(self.root)
                enqueue(self.root, CHAIR, "body", to="claude", token=tok(2))

        card = run(self.root, CHAIR, timeout=3600.0, clock=itertools.count(0.0, 1.0).__next__, sleep=sleep,
                   now=lambda: iso(NOW), write=lambda *a, **k: None)
        self.assertFalse(card["timed_out"])
        self.assertEqual(card["n"], 1, "the inbox row wakes it, as on any root that never opted in")
        self.assertEqual(card["pending"][0]["token"], tok(2))
        self.assertEqual(card["pointers"], [], "both fields, on every card")
        self.assertTrue(read_wait_file(self.root, CHAIR, owner="session")["ended"])

    def test_the_re_arm_line_quotes_the_root_and_the_chair(self):
        enable(self.root, by="person")
        card = self.wait()
        self.assertIn('--root "' + str(self.root) + '"', card["next"])
        self.assertIn('--seat "' + CHAIR + '"', card["next"])
        self.assertIn(sys.executable.replace("\\", "/"), card["next"], "the interpreter that runs the waiter")

    def test_the_waiter_line_runs_in_bash_and_in_powershell(self):
        import shutil
        from convoy.wait import wait_command
        line = wait_command(self.root, CHAIR)
        self.assertFalse(line.startswith('"'), "a quoted interpreter first is a PowerShell parse error")
        env = {**os.environ, "PYTHONPATH": SRC}
        shells = [("bash", ["bash", "-c", line + " --help"]),
                  ("powershell", ["powershell", "-NoProfile", "-Command", line + " --help"])]
        ran = 0
        for name, argv in shells:
            found = shutil.which(argv[0])  # PATH's shell: a bare name on Windows finds System32's (WSL) bash first
            if not found:
                continue
            if name == "bash" and "system32" in found.replace("\\", "/").lower():
                continue  # WSL's bash cannot run a Windows interpreter path; not the shell this line is for
            out = subprocess.run([found] + argv[1:], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(out.returncode, 0, name + ": " + out.stderr[-400:])
            self.assertIn("--seat", out.stdout, name)
            ran += 1
        self.assertGreater(ran, 0, "no shell to run the line in")

    def test_an_armed_waiter_waits_hours_by_default(self):
        enable(self.root, by="person")
        run(self.root, CHAIR, clock=itertools.count(0.0, 3600.0).__next__, sleep=lambda s: None,
            now=lambda: iso(NOW), write=lambda *a, **k: None)
        row = read_wait_file(self.root, CHAIR, owner="session")
        self.assertEqual(row["expires"], iso(NOW + timedelta(seconds=ARMED_TIMEOUT_S)))
        self.assertGreaterEqual(ARMED_TIMEOUT_S, 3600.0)

    def test_a_disabled_root_keeps_today_s_timeout(self):
        run(self.root, CHAIR, clock=itertools.count(0.0, 600.0).__next__, sleep=lambda s: None,
            now=lambda: iso(NOW), write=lambda *a, **k: None)
        self.assertEqual(read_wait_file(self.root, CHAIR)["expires"], iso(NOW + timedelta(seconds=DEFAULT_TIMEOUT_S)))


class Armed(Root):
    def arm(self, *, beat, expires_in=3600.0, ended=None, owner="session"):
        write_wait_file(self.root, CHAIR, pid=os.getpid(), started=iso(beat), timeout=expires_in,
                        incarnation=None, owner=owner, beat=iso(beat), ended=ended)

    def test_a_fresh_unexpired_session_waiter_is_armed(self):
        self.arm(beat=NOW)
        self.assertTrue(session_waiter_armed(self.root, CHAIR, now=iso(NOW + timedelta(seconds=30))))

    def test_a_stale_beat_an_expiry_an_exit_or_a_hook_waiter_is_not_armed(self):
        self.arm(beat=NOW)
        self.assertFalse(session_waiter_armed(self.root, CHAIR, now=iso(NOW + timedelta(seconds=120))))
        self.arm(beat=NOW, expires_in=10.0)
        self.assertFalse(session_waiter_armed(self.root, CHAIR, now=iso(NOW + timedelta(seconds=20))))
        self.arm(beat=NOW, ended=iso(NOW))
        self.assertFalse(session_waiter_armed(self.root, CHAIR, now=iso(NOW)))
        wait_path(self.root, CHAIR, owner="session").unlink()
        self.arm(beat=NOW, owner="hook")
        self.assertFalse(session_waiter_armed(self.root, CHAIR, now=iso(NOW)))


class WhoIsListening(Armed):
    """panes, rail and the origin loop read the waiter through one helper: on an enabled root, the
    session's own waiter; elsewhere, today's file."""

    def test_on_an_enabled_root_it_is_the_session_s_waiter(self):
        enable(self.root, by="person")
        self.arm(beat=NOW, owner="hook")
        self.assertIsNone(listening_wait_file(self.root, CHAIR))
        self.arm(beat=NOW)
        self.assertEqual(listening_wait_file(self.root, CHAIR)["owner"], "session")
        self.arm(beat=NOW, ended=iso(NOW))
        self.assertIsNone(listening_wait_file(self.root, CHAIR), "an ended waiter listens to nothing")

    def test_elsewhere_it_is_today_s_file(self):
        self.arm(beat=NOW, owner="hook")
        self.assertEqual(listening_wait_file(self.root, CHAIR), read_wait_file(self.root, CHAIR))

    def test_panes_rail_and_the_origin_loop_use_it(self):
        for name in ("panes", "rail", "origin_loop"):
            text = (Path(SRC) / "convoy" / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn("listening_wait_file(", text, name)
            self.assertNotIn("read_wait_file(", text, name)


class WaiterReachability(Armed):
    def setUp(self):
        super().setUp()
        register_route(self.root, CHAIR, "waiter", registered_by="person")
        write_pulse(self.root, CHAIR, pulse_source="wait", ts=iso(NOW))  # the hook's waiter beats

    def test_on_an_enabled_root_the_hook_s_waiter_alone_is_not_live(self):
        enable(self.root, by="person")
        self.arm(beat=NOW, owner="hook")
        state = reachability_detail(self.root, CHAIR, now=iso(NOW))
        self.assertEqual(state["reachable"], "degraded")
        self.assertIn("not armed", state["reason"])

    def test_on_an_enabled_root_a_session_waiter_is_live(self):
        enable(self.root, by="person")
        self.arm(beat=NOW)
        self.assertEqual(reachability_detail(self.root, CHAIR, now=iso(NOW))["reachable"], "live")

    def test_a_disabled_root_keeps_today_s_reachability(self):
        self.assertEqual(reachability_detail(self.root, CHAIR, now=iso(NOW))["reachable"], "live")


class TheLocalRoutes(Root):
    def test_the_waiter_route_drops_a_pointer(self):
        LocalRoutes(self.root).fire("waiter", pointer(1), {"route": "waiter"})
        self.assertEqual([p["token"] for p in pending_pointers(self.root, CHAIR)], [tok(1)])

    def test_a_route_not_wired_on_this_host_raises_a_route_error(self):
        for route in ("channel", "codex-queue", "board-webhook", "none"):
            with self.assertRaises(RouteError):
                LocalRoutes(self.root).fire(route, pointer(1), {"route": route})
        self.assertEqual(pending_pointers(self.root, CHAIR), [])

    def test_a_refire_write_that_keeps_failing_is_not_a_failed_wake(self):
        import convoy.wake_local as wl
        LocalRoutes(self.root).fire("waiter", pointer(1), {"route": "waiter"})

        def denied(src, dst):
            raise PermissionError(5, "Access is denied")

        with mock.patch.object(wl.os, "replace", denied), mock.patch.object(wl.time, "sleep", lambda s: None):
            LocalRoutes(self.root).fire("waiter", pointer(1), {"route": "waiter"})  # the pointer is still there
        self.assertEqual(len(pending_pointers(self.root, CHAIR)), 1)
        self.assertEqual([p.name for p in pointer_dir(self.root, CHAIR).iterdir() if ".tmp-" in p.name], [])

    def test_a_first_write_that_keeps_failing_is_a_route_error(self):
        import convoy.wake_local as wl

        def denied(src, dst):
            raise PermissionError(5, "Access is denied")

        with mock.patch.object(wl.os, "replace", denied), mock.patch.object(wl.time, "sleep", lambda s: None):
            with self.assertRaises(RouteError):
                LocalRoutes(self.root).fire("waiter", pointer(1), {"route": "waiter"})
        self.assertFalse(pointer_dir(self.root, CHAIR).exists()
                         and [p for p in pointer_dir(self.root, CHAIR).iterdir() if ".tmp-" in p.name])

    def test_an_alert_is_a_row_the_person_can_read(self):
        LocalRoutes(self.root).alert(CHAIR, CHAIR + " did not read wake k")
        [row] = [json.loads(line) for line in alerts_path(self.root).read_text(encoding="utf-8").splitlines()]
        self.assertEqual((row["target"], row["text"]), (CHAIR, CHAIR + " did not read wake k"))
        self.assertTrue(row["ts"])


class TheLock(Root):
    def test_one_holder_at_a_time_in_one_process(self):
        held = acquire_lock(self.root)
        self.assertIsNotNone(held)
        self.assertIsNone(acquire_lock(self.root), "a second handle is refused while the first holds it")
        info = lock_info(self.root)
        self.assertTrue(info["held"])
        self.assertEqual(info["pid"], os.getpid())
        held.release()
        self.assertFalse(lock_info(self.root)["held"])
        again = acquire_lock(self.root)
        self.assertIsNotNone(again)
        again.release()

    def test_a_status_poll_never_turns_an_acquire_away(self):
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                lock_info(self.root)

        poller = threading.Thread(target=poll)
        acquire_lock(self.root).release()
        poller.start()
        refused = 0
        try:
            for _ in range(200):
                held = acquire_lock(self.root)
                if held is None:
                    refused += 1
                else:
                    held.release()
        finally:
            stop.set()
            poller.join()
        self.assertEqual(refused, 0)

    def test_six_processes_race_over_a_dead_holder_s_lock_and_exactly_one_holds(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait(timeout=30)
        lock_path(self.root).parent.mkdir(parents=True, exist_ok=True)
        lock_path(self.root).write_text(json.dumps({"pid": dead.pid, "started": iso(NOW), "host": "h"}),
                                        encoding="utf-8")
        outs = race("from convoy.wake_service import acquire_lock\n"
                    "h = acquire_lock(R)\n"
                    "print('held' if h else 'refused', flush=True)\n"
                    "time.sleep(3)\n", 6, self.root)
        self.assertEqual(sorted(o.strip() for o in outs), ["held"] + ["refused"] * 5)

    def test_the_os_releases_it_when_the_holder_dies_without_a_finally(self):
        code = ("import sys, time; sys.path.insert(0, %r)\n"
                "from convoy.wake_service import acquire_lock\n"
                "h = acquire_lock(sys.argv[1])\n"
                "print('held' if h else 'refused', flush=True)\n"
                "time.sleep(60)\n" % SRC)
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.root)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.assertIsNone(acquire_lock(self.root))
        self.assertTrue(lock_info(self.root)["held"])
        holder.kill()  # no finally runs: a hard kill
        holder.wait(timeout=10)
        self.assertTrue(wait_for(lambda: not lock_info(self.root)["held"], 5.0))
        mine = acquire_lock(self.root)
        self.assertIsNotNone(mine, "the OS released it")
        mine.release()

    def test_a_stale_or_unreadable_file_is_no_lock(self):
        lock_path(self.root).parent.mkdir(parents=True, exist_ok=True)
        lock_path(self.root).write_text("not json", encoding="utf-8")
        self.assertFalse(lock_info(self.root)["held"])
        mine = acquire_lock(self.root)
        self.assertIsNotNone(mine)
        mine.release()
        lock_path(self.root).write_text(json.dumps({"pid": os.getpid(), "started": iso(NOW)}), encoding="utf-8")
        self.assertFalse(lock_info(self.root)["held"], "a pid in the file is not a holder")


class FakeRoutes:
    def __init__(self):
        self.fired = []
        self.alerts = []

    def fire(self, route, pointer, route_row):
        self.fired.append((route, pointer))

    def alert(self, target, text):
        self.alerts.append((target, text))


class TheService(Root):
    def setUp(self):
        super().setUp()
        self.routes = FakeRoutes()
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.stop()

    def service(self, **kw):
        kw.setdefault("bound", self.root)
        svc = WakeService(routes_for=lambda root: self.routes, rescan_s=0.05, poll_s=0.05, backoff_s=0.05, **kw)
        self.services.append(svc)
        return svc

    def live_send(self, token=tok(1)):
        now = datetime.now(timezone.utc)
        register_route(self.root, CHAIR, "channel", registered_by="person", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="channel", ts=iso(now))
        feed = self.root / ".convoy" / "feed.jsonl"
        with feed.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": iso(now), "kind": "synapse", "instance_id": CHAIR, "token": token,
                                "verified_by": None}) + "\n")

    def test_a_root_that_never_opted_in_runs_nothing(self):
        self.live_send()
        svc = self.service().start()
        time.sleep(0.5)
        self.assertEqual(svc.running(), [])
        self.assertFalse(cursor_path(self.root).exists())
        self.assertFalse(lock_path(self.root).exists())
        self.assertEqual(self.routes.fired, [])

    def test_an_enabled_root_dispatches_and_stop_releases_the_lock(self):
        enable(self.root, by="person")
        self.live_send()
        svc = self.service().start()
        self.assertTrue(wait_for(lambda: self.routes.fired), "the send woke its receiver")
        self.assertEqual(svc.running(), [str(self.root)])
        self.assertTrue(lock_info(self.root)["held"])
        svc.stop()
        self.assertEqual(svc.running(), [])
        self.assertFalse(lock_info(self.root)["held"])

    def test_enable_and_disable_are_picked_up_while_it_runs(self):
        svc = self.service().start()
        enable(self.root, by="person")
        self.assertTrue(wait_for(lambda: svc.running() == [str(self.root)]))
        disable(self.root)
        self.assertTrue(wait_for(lambda: svc.running() == []))
        self.assertTrue(wait_for(lambda: not lock_info(self.root)["held"]))

    def test_a_second_service_on_the_same_root_runs_no_loop(self):
        enable(self.root, by="person")
        first = self.service().start()
        self.assertTrue(wait_for(lambda: first.running() == [str(self.root)]))
        second = self.service().start()
        time.sleep(0.4)
        self.assertEqual(second.running(), [])
        self.live_send()
        self.assertTrue(wait_for(lambda: self.routes.fired))
        time.sleep(0.4)
        self.assertEqual(len(self.routes.fired), 1, "one dispatcher, one fire")

    def test_an_unbound_service_serves_every_root_it_is_given(self):
        other = Path(tempfile.mkdtemp())
        ensure_id(other)
        enable(self.root, by="person")
        svc = self.service(bound=None, roots=lambda: [self.root, other]).start()
        self.assertTrue(wait_for(lambda: svc.running() == [str(self.root)]))

    def test_a_loop_that_raises_is_restarted(self):
        enable(self.root, by="person")
        runs = []

        class Flaky:
            def __init__(self, root, routes, **kw):
                pass

            def run(self, *, poll_s, should_stop, sleep):
                runs.append(1)
                if len(runs) == 1:
                    raise RuntimeError("the feed could not be read")
                while not should_stop():
                    sleep(poll_s)

        with mock.patch("convoy.wake_service.Dispatcher", Flaky):
            self.service().start()
            self.assertTrue(wait_for(lambda: len(runs) >= 2))


class TheOrigin(unittest.TestCase):
    def test_serve_starts_the_service_after_the_bind_and_stops_it_on_exit(self):
        import convoy.mcp_http as mcp_http
        order = []

        class FakeServer:
            server_address = ("127.0.0.1", 0)
            convoy_root = Path(tempfile.mkdtemp())

            def serve_forever(self):
                order.append("serve")
                raise KeyboardInterrupt

            def server_close(self):
                order.append("close")

        def make_server(root, host, port):
            order.append("bind")
            return FakeServer()

        service = mock.Mock()
        with mock.patch.object(mcp_http, "make_server", make_server), \
                mock.patch("convoy.origin_loop.start_daemon", return_value=None), \
                mock.patch("convoy.wake_service.start_daemon",
                           side_effect=lambda bound: order.append("wake") or service) as start:
            self.assertEqual(mcp_http.serve(None), 0)
        start.assert_called_once_with(FakeServer.convoy_root)
        service.stop.assert_called_once()
        self.assertEqual(order[:3], ["bind", "wake", "serve"])


class FakeGit:
    def __call__(self, args, cwd):
        return subprocess.CompletedProcess(args, 128, "", "not a git repository")


class TheStopHook(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-wake-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-wake-wt-"))
        bind(self.root, "wake-test")
        patch = mock.patch("convoy.end._spawn_waiter", return_value={"spawned": True, "pid": 1})
        patch.start()
        self.addCleanup(patch.stop)

    def stop(self, harness="claude", chair="claude-wake-test", **payload):
        wt = self.wt if chair == "claude-wake-test" else Path(tempfile.mkdtemp(prefix="convoy-wake-wt-"))
        seat(self.root, harness, chair, worktree=str(wt))  # one worktree, one chair
        body = {"hook_event_name": "Stop", "cwd": str(wt), "session_id": "vendor-" + str(len(payload)),
                "turn_id": "turn-" + str(time.monotonic_ns()), **payload}
        return end_task(root=self.root, hook_payload=body, git_runner=FakeGit())

    def test_an_enabled_root_tells_a_claude_chair_with_no_waiter_to_arm_one(self):
        enable(self.root, by="person")
        hook = self.stop()["hook"]
        self.assertEqual(hook.get("decision"), "block")
        self.assertIn("-m convoy.wait", hook["reason"])
        self.assertIn('--seat "claude-wake-test"', hook["reason"])
        self.assertIn("--root", hook["reason"])
        self.assertIn("background", hook["reason"])

    def test_it_blocks_once(self):
        enable(self.root, by="person")
        self.assertEqual(self.stop(stop_hook_active=True)["hook"], {})

    def test_three_unarmed_turns_in_a_row_then_a_note_instead_of_a_block(self):
        enable(self.root, by="person")
        for _ in range(3):
            self.assertEqual(self.stop()["hook"].get("decision"), "block")
        hook = self.stop()["hook"]
        self.assertNotIn("decision", hook)
        self.assertIn("convoy.wait", hook.get("systemMessage", ""))

    def test_an_armed_turn_resets_the_count(self):
        enable(self.root, by="person")
        for _ in range(3):
            self.stop()
        now = datetime.now(timezone.utc)
        write_wait_file(self.root, "claude-wake-test", pid=os.getpid(), started=iso(now), timeout=3600.0,
                        incarnation=None, owner="session", beat=iso(now))
        self.assertEqual(self.stop()["hook"], {})
        wait_path(self.root, "claude-wake-test", owner="session").unlink()
        self.assertEqual(self.stop()["hook"].get("decision"), "block")

    def test_a_waiter_still_starting_when_the_turn_ends_counts_as_armed(self):
        enable(self.root, by="person")
        seat(self.root, "claude", "claude-wake-test", worktree=str(self.wt))

        def arm_late():
            time.sleep(0.5)  # the background waiter is still importing when the Stop hook runs
            now = datetime.now(timezone.utc)
            write_wait_file(self.root, "claude-wake-test", pid=os.getpid(), started=iso(now), timeout=3600.0,
                            incarnation=None, owner="session", beat=iso(now))

        late = threading.Thread(target=arm_late)
        late.start()
        try:
            self.assertEqual(self.stop()["hook"], {})
        finally:
            late.join()

    def test_the_arm_command_quotes_the_root_and_the_chair(self):
        from convoy.end import arm_reason
        root = Path(tempfile.mkdtemp(prefix="convoy wake root "))
        reason = arm_reason(root, "chair one")
        self.assertIn('--root "' + str(root) + '"', reason)
        self.assertIn('--seat "chair one"', reason)
        unsafe = arm_reason(root, 'chair$(touch x)')
        self.assertNotIn("$(touch x)", unsafe.split("--seat")[-1] if "--seat" in unsafe else "")
        self.assertNotIn("-m convoy.wait", unsafe, "a chair that cannot be quoted safely gets no command")

    def test_an_armed_waiter_ends_the_turn_cleanly(self):
        enable(self.root, by="person")
        now = datetime.now(timezone.utc)
        write_wait_file(self.root, "claude-wake-test", pid=os.getpid(), started=iso(now), timeout=3600.0,
                        incarnation=None, owner="session", beat=iso(now))
        self.assertEqual(self.stop()["hook"], {})

    def test_a_disabled_root_and_a_codex_chair_are_never_told(self):
        self.assertEqual(self.stop()["hook"], {})
        enable(self.root, by="person")
        self.assertEqual(self.stop(harness="codex", chair="codex-wake-test")["hook"], {})


class TheThresholdRow(unittest.TestCase):
    def test_a_threshold_row_the_lock_kept_out_is_named_never_silent(self):
        import convoy.end as end
        root = Path(tempfile.mkdtemp(prefix="convoy-wake-root-"))
        wt = Path(tempfile.mkdtemp(prefix="convoy-wake-wt-"))
        bind(root, "wake-test")
        seat(root, "codex", "codex-quota-test", worktree=str(wt))
        real = end.hook

        def busy(r, kind, *a, **k):
            if kind == "threshold":
                raise TimeoutError("could not lock feed.jsonl.lock within 10.0 s")
            return real(r, kind, *a, **k)

        reading = {"session_pct": 97, "week_pct": 10, "resets": {"session": "2030-01-01T17:00:00Z"}}
        with mock.patch.object(end, "hook", busy), mock.patch.object(end, "_seat_quota", return_value=reading), \
                mock.patch.object(end, "_spawn_waiter", return_value={"spawned": True, "pid": 1}):
            card = end_task(root=root, hook_payload={"hook_event_name": "Stop", "cwd": str(wt),
                                                     "session_id": "v", "turn_id": "t"}, git_runner=FakeGit())
        self.assertIn("threshold", card["hook"].get("systemMessage", ""))


class TheHookWaiterArgv(unittest.TestCase):
    def test_the_stop_hook_s_waiter_names_itself_the_hook_s(self):
        import convoy.end as end
        seen = []

        class Proc:
            pid = 4321

        def popen(argv, **kw):
            seen.append(argv)
            return Proc()

        with mock.patch.object(end.subprocess, "Popen", popen):
            end._spawn_waiter(Path(tempfile.mkdtemp()), CHAIR, None)
        argv = seen[0]
        self.assertEqual(argv[argv.index("--owner") + 1], "hook")


if __name__ == "__main__":
    unittest.main()
