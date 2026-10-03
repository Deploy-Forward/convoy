"""A detached chair is never woken.

`convoy detach` (list-attach) leaves a chair's seat in place, marked detached, so the session can work
on another thread; its pending rows wait for it to attach again. The wake dispatcher must agree:
a send to a detached chair is held with why "detached", catch-up skips detached chairs, and the
wake directory reads the chair as "detached", not live.

The detach is the real one (`detach_session`); only the calling session's identity proof is supplied.
Routes are a fake that records what it was asked to do. Every id is synthetic, every root temporary.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, list_seats, seat  # noqa: E402
from convoy.inbox import enqueue  # noqa: E402
from convoy.pulse import write_pulse  # noqa: E402
from convoy.wake_dispatch import Dispatcher, read_outbox  # noqa: E402
from convoy.wake_routes import reachability_detail, register_route  # noqa: E402

CHAIR = "neuron-b-thread"
NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def tok(n):
    return format(n, "032x")


class FakeRoutes:
    def __init__(self):
        self.fired = []
        self.alerts = []

    def fire(self, route, pointer, route_row):
        self.fired.append((route, pointer["target"]))

    def alert(self, target, text):
        self.alerts.append((target, text))


class DetachedChair(unittest.TestCase):
    def setUp(self):
        owner = tempfile.TemporaryDirectory()
        self.addCleanup(owner.cleanup)
        self.root = Path(owner.name) / "project"
        self.root.mkdir()
        self.wt = Path(owner.name) / "worktree"
        self.wt.mkdir()
        home = mock.patch.dict(os.environ, {"CONVOY_HOME": str(Path(owner.name) / "home")})
        home.start()
        self.addCleanup(home.stop)
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", CHAIR, worktree=str(self.wt))
        register_route(self.root, CHAIR, "waiter", registered_by="person", ts=iso(NOW))
        write_pulse(self.root, CHAIR, pulse_source="wait", ts=iso(NOW))
        self.routes = FakeRoutes()

    def dispatcher(self):
        return Dispatcher(self.root, self.routes, clock=lambda: NOW)

    def detach(self):
        from convoy.sessions import detach_session
        proof = {"ok": True, "chair": CHAIR, "via": "environment", "harness": "claude"}
        with mock.patch("convoy.sessions.identify", return_value=proof):
            card = detach_session(root=self.root, cwd=self.wt)
        self.assertTrue(card["ok"], card)
        self.assertTrue([s for s in list_seats(self.root) if s["session_id"] == CHAIR][0]["detached"])

    def send_row(self, token):
        feed = self.root / ".convoy" / "feed.jsonl"
        with feed.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": iso(NOW), "kind": "synapse", "instance_id": CHAIR, "token": token,
                                "verified_by": None}) + "\n")

    def test_an_attached_chair_is_woken(self):
        d = self.dispatcher()
        d.start()
        self.send_row(tok(1))
        d.step()
        self.assertEqual(self.routes.fired, [("waiter", CHAIR)])

    def test_a_send_to_a_detached_chair_is_held_as_detached(self):
        d = self.dispatcher()
        d.start()
        self.detach()
        self.send_row(tok(1))  # a send made before the detach, read after it
        d.step()
        self.assertEqual(self.routes.fired, [])
        [row] = [r for r in read_outbox(self.root) if r["dedupe_key"] == tok(1) + ":" + CHAIR + ":send"]
        self.assertEqual((row["result"], row["why"]), ("held", "detached"))
        self.assertEqual(self.routes.alerts, [], "a detach is the session's own word: nobody is alerted")

    def test_catch_up_skips_a_detached_chair(self):
        enqueue(self.root, CHAIR, "body", to="claude", token=tok(2))
        self.detach()
        self.dispatcher().start()
        self.assertEqual(self.routes.fired, [])
        self.assertEqual([r for r in read_outbox(self.root) if r.get("target") == CHAIR], [])

    def test_catch_up_never_refires_a_held_wake_for_a_detached_chair(self):
        d = self.dispatcher()
        d.start()
        self.detach()
        self.send_row(tok(3))
        d.step()
        self.dispatcher().start()
        self.assertEqual(self.routes.fired, [])

    def test_a_wake_fired_before_the_detach_is_never_refired_or_alerted(self):
        clock = {"now": NOW}
        d = Dispatcher(self.root, self.routes, clock=lambda: clock["now"])
        d.start()
        self.send_row(tok(4))
        d.step()
        self.assertEqual(len(self.routes.fired), 1)
        self.detach()
        for _ in range(3):
            clock["now"] = clock["now"] + timedelta(seconds=1300)
            write_pulse(self.root, CHAIR, pulse_source="wait", ts=iso(clock["now"]))
            d.step()
        self.assertEqual(len(self.routes.fired), 1, "no refire, no ladder")
        self.assertEqual(self.routes.alerts, [])
        last = [r for r in read_outbox(self.root) if r["dedupe_key"] == tok(4) + ":" + CHAIR + ":send"][-1]
        self.assertEqual((last["result"], last["why"]), ("held", "detached"))

    def test_the_wake_directory_reads_a_detached_chair_as_detached(self):
        self.assertEqual(reachability_detail(self.root, CHAIR, now=iso(NOW))["reachable"], "live")
        self.detach()
        state = reachability_detail(self.root, CHAIR, now=iso(NOW))
        self.assertEqual(state["reachable"], "detached")
        self.assertIn("attach again", state["reason"])


if __name__ == "__main__":
    unittest.main()
