"""The wake dispatcher: who gets woken, when, by which route, and what stops a runaway.

Only two things wake anyone:

  a send                 wakes its receiver (the synapse row's instance_id)
  a note citing a token  wakes the sender of that token, once; never the note's own author,
                         and nobody when the send row does not name its sender

Everything else wakes nobody: stamps, heartbeats, seats, usage, consumed-markers, and a note
that cites no token (an acknowledgement of an acknowledgement).

The loop tails the feed by a byte cursor and writes the cursor only after it has dispatched,
so a crash replays rows, and the dedupe key token:target:reason absorbs the replay. A wake
carries a pointer, never the body. A budget per pair and per target per hour, per
conversation, and a person's hold refuse a wake with a row. A send wake that is not read within
its route's time is refired once, then dropped, and the ladder takes over: channel to waiter,
anything else to an alert. On start, pending inbox rows and held wakes are caught up.

Every route here is a fake that records what it was asked to do. Nothing is spawned, no queue
or board is called, every id is synthetic and the thread root is a temporary folder.
"""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_id
from convoy.convoy import ensure_id
from convoy.inbox import drain, enqueue
from convoy.pulse import write_pulse
from convoy.wake_dispatch import (
    LIMITS,
    T_ACK,
    T_ACK_LONG,
    Dispatcher,
    RouteError,
    cited_tokens,
    cursor_path,
    outbox_path,
    read_outbox,
    set_hold,
    wake_targets,
)
from convoy.wake_routes import reachability, read_route, register_route

NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
SENDER = "neuron-a-thread"
RECEIVER = "neuron-b-thread"
CONDUCTOR = "grok-bot"
BODY = "PRIVATE-BODY-TEXT do the thing"


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def tok(n: int) -> str:
    return format(n, "032x")


class FakeRoutes:
    """Records every wake and alert; raises for a route told to fail."""

    def __init__(self):
        self.fired = []
        self.alerts = []
        self.fail = {}

    def fire(self, route, pointer, route_row):
        if route in self.fail:
            raise self.fail[route]
        self.fired.append((route, pointer, route_row))

    def alert(self, target, text):
        self.alerts.append((target, text))


class Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.root)
        self.now = NOW
        self.routes = FakeRoutes()
        self.d = self.dispatcher()

    def dispatcher(self):
        return Dispatcher(self.root, self.routes, clock=lambda: self.now)

    def advance(self, seconds, *, pulse=()):
        self.now = self.now + timedelta(seconds=seconds)
        for chair in pulse:
            self.pulse(chair)

    def pulse(self, chair, source=None):
        route = (read_route(self.root, chair) or {}).get("route")
        write_pulse(self.root, chair, pulse_source=source or ("channel" if route == "channel" else "wait"),
                    ts=iso(self.now))

    def live(self, chair, route="channel"):
        config = {"channel": {"server": "convoy-channel"}, "codex-queue": {"thread_id": "thread-0000"},
                  "board-webhook": {"subscription_id": "sub-0000", "agent_id": CONDUCTOR}}.get(route, {})
        register_route(self.root, chair, route, registered_by="person", config=config, ts=iso(self.now))
        if route != "board-webhook":
            self.pulse(chair)

    def feed(self, row, *, newline=True):
        path = self.root / ".convoy" / "feed.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + ("\n" if newline else ""))

    def send(self, to, token, *, sender=None, inbox=True, body=BODY):
        if inbox:
            enqueue(self.root, to, body, to="claude", token=token)
        row = {"ts": iso(self.now), "kind": "synapse", "instance_id": to, "summary": "send claude",
               "to": "claude", "token": token, "delivery": "queued", "delivered": False,
               "device": "device-0000", "verified_by": None}
        if sender:
            row["from"] = sender
            row["verified_by"] = "environment"  # a sender on a send row is proven, or it is not a sender
        self.feed(row)
        return row

    def note(self, author, text, to=None):
        self.feed({"ts": iso(self.now), "kind": "note", "instance_id": author, "from": author,
                   "summary": text, "to": to, "device": None, "verified_by": "environment"})

    def fired_to(self, chair):
        return [(route, pointer) for route, pointer, _ in self.routes.fired if pointer["target"] == chair]

    def rows_for(self, key):
        return [r for r in read_outbox(self.root) if r["dedupe_key"] == key]


class WhoGetsWoken(unittest.TestCase):
    def test_a_send_wakes_its_receiver(self):
        row = {"kind": "synapse", "instance_id": RECEIVER, "token": tok(1), "to": "claude"}
        self.assertEqual(wake_targets(row, lambda t: None), [(RECEIVER, "send", tok(1))])

    def test_a_note_citing_a_token_wakes_that_tokens_sender(self):
        senders = {tok(1): SENDER}.get
        for text in ("re token " + tok(1) + ": done", "Received the order. token=" + tok(1)):
            row = {"kind": "note", "from": RECEIVER, "summary": text}
            self.assertEqual(wake_targets(row, senders), [(SENDER, "reply", tok(1))], text)

    def test_a_note_never_wakes_its_own_author(self):
        row = {"kind": "note", "from": SENDER, "summary": "re token " + tok(1) + ": thanks", "verified_by": "environment"}
        self.assertEqual(wake_targets(row, {tok(1): SENDER}.get), [])

    def test_a_send_never_wakes_its_own_proven_sender(self):
        row = {"kind": "synapse", "instance_id": SENDER, "token": tok(1), "from": SENDER, "verified_by": "environment"}
        self.assertEqual(wake_targets(row, lambda t: None), [])

    def test_a_claimed_sender_cannot_silence_a_send_to_itself(self):
        row = {"kind": "synapse", "instance_id": SENDER, "token": tok(1), "from": SENDER, "verified_by": None,
               "author_claimed": True}
        self.assertEqual(wake_targets(row, lambda t: None), [(SENDER, "send", tok(1))])

    def test_a_reply_whose_send_names_no_sender_wakes_nobody(self):
        row = {"kind": "note", "from": RECEIVER, "summary": "re token " + tok(1) + ": done"}
        self.assertEqual(wake_targets(row, lambda t: None), [], "an unknown sender is never guessed")

    def test_nothing_else_wakes_anyone(self):
        quiet = [
            {"kind": "heartbeat", "instance_id": RECEIVER, "summary": "heartbeat: claude turn ended"},
            {"kind": "usage", "instance_id": RECEIVER, "summary": "claude usage"},
            {"kind": "seated", "instance_id": RECEIVER, "token": tok(2)},
            {"kind": "join", "instance_id": RECEIVER, "token": tok(3), "to": RECEIVER},
            {"kind": "conductor", "from": CONDUCTOR, "summary": "stamp"},
            {"kind": "consumed-marker", "token": tok(4)},
            {"kind": "refuse", "instance_id": RECEIVER, "summary": "budget"},
            {"kind": "note", "from": RECEIVER, "summary": "thanks for the thanks"},
            {"kind": "synapse", "instance_id": RECEIVER, "token": None},
        ]
        for row in quiet:
            self.assertEqual(wake_targets(row, {tok(2): SENDER, tok(3): SENDER, tok(4): SENDER}.get), [], row)

    def test_a_cited_token_is_32_hex_after_the_word_token(self):
        text = "merged as 0123456789abcdef0123456789abcdef01234567, re token " + tok(7) + ": ok"
        self.assertEqual(cited_tokens(text), [tok(7)])
        self.assertEqual(cited_tokens("no token here"), [])


class TheProvenSender(Case):
    def unproven(self, token, **fields):
        self.feed({"ts": iso(self.now), "kind": "synapse", "instance_id": RECEIVER, "token": token,
                   "from": SENDER, **fields})

    def test_an_unproven_sender_is_not_woken_by_a_reply(self):
        self.live(SENDER)
        self.unproven(tok(1), verified_by=None, author_claimed=True)
        self.unproven(tok(2), verified_by="environment", author_claimed=True)
        self.unproven(tok(3), verified_by="claimed")
        for n in (1, 2, 3):
            self.note(RECEIVER, "re token " + tok(n) + ": done")
        self.d.start()
        self.d.step()
        self.assertEqual(self.fired_to(SENDER), [], "a reply wakes only a proven sender")

    def test_an_unproven_sender_is_null_on_the_pointer(self):
        self.live(RECEIVER)
        self.unproven(tok(1), verified_by=None, author_claimed=True)
        self.d.start()
        self.d.step()
        [(_, p)] = self.fired_to(RECEIVER)
        self.assertIsNone(p["from"])
        self.assertIsNone(p["from_neuron"])


class TheClaimedCitation(Case):
    """A note whose author is only claimed (a hosted neuron's honest answer is claimed too) never
    pre-empts or suppresses a first fire and never verifies a route. After the first fire, one from
    the target may stop the refire and the ladder, logged answered-claimed, not as delivery."""

    def claimed_note(self, author, text):
        self.feed({"ts": iso(self.now), "kind": "note", "instance_id": author, "from": author, "summary": text,
                   "to": None, "device": None, "verified_by": None, "author_claimed": True})

    def key(self):
        return tok(1) + ":" + RECEIVER + ":send"

    def test_a_claimed_citation_never_preempts_the_first_fire(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), sender=SENDER, inbox=False)
        self.claimed_note(RECEIVER, "re token " + tok(1) + ": done")
        self.d.start()
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)

    def test_a_claimed_citation_never_verifies_a_route(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.claimed_note(RECEIVER, "re token " + tok(1) + ": done")
        self.advance(5, pulse=[RECEIVER])
        self.d.step()
        self.assertIsNone(read_route(self.root, RECEIVER)["verified_at"])
        self.assertEqual(self.rows_for(self.key())[-1]["result"], "answered-claimed")

    def test_a_claimed_citation_after_the_fire_stops_the_refire_without_a_drop(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.claimed_note(RECEIVER, "re token " + tok(1) + ": done")
        for _ in range(3):
            self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
            self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)
        self.assertNotIn("dropped", [r["result"] for r in self.rows_for(self.key())])
        self.assertIsNone(read_route(self.root, RECEIVER)["fault"])
        self.assertEqual(self.routes.alerts, [])

    def test_a_claimed_note_never_suppresses_its_authors_reply_wake(self):
        self.live(SENDER)
        self.send(RECEIVER, tok(1), sender=SENDER, inbox=False)
        self.claimed_note(SENDER, "re token " + tok(1) + ": still waiting")
        self.d.start()
        self.d.step()
        self.assertEqual([(p["reason"], p["token"]) for _, p in self.fired_to(SENDER)], [("reply", tok(1))])


class TheLoop(Case):
    def test_a_send_fires_its_receiver_once_and_the_cursor_moves_after(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1))
        self.d.start()
        self.d.step()
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)
        size = (self.root / ".convoy" / "feed.jsonl").stat().st_size
        self.assertEqual(int(cursor_path(self.root).read_text(encoding="utf-8")), size)
        [row] = self.rows_for(tok(1) + ":" + RECEIVER + ":send")
        self.assertEqual(row["result"], "fired")
        self.assertEqual(row["route"], "channel")
        self.assertEqual(row["attempt"], 1)
        self.assertRegex(row["wake_id"], r"^wk_[0-9a-f]{16}$")
        for key in ("target", "reason", "token", "why", "ts"):
            self.assertIn(key, row)

    def test_a_crash_before_the_cursor_is_written_replays_and_dedupe_absorbs_it(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        cursor_path(self.root).write_text("0", encoding="utf-8")
        again = self.dispatcher()
        again.start()
        again.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1, "never twice")
        fired = [r for r in self.rows_for(tok(1) + ":" + RECEIVER + ":send") if r["result"] == "fired"]
        self.assertEqual(len(fired), 1)

    def test_the_cursor_stops_before_a_torn_line(self):
        self.live(RECEIVER)
        self.d.start()
        self.send(RECEIVER, tok(1), inbox=False)
        self.feed({"ts": iso(self.now), "kind": "synapse", "instance_id": RECEIVER, "token": tok(2)}, newline=False)
        self.d.step()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(1)])
        size = (self.root / ".convoy" / "feed.jsonl").stat().st_size
        self.assertLess(int(cursor_path(self.root).read_text(encoding="utf-8")), size)
        with (self.root / ".convoy" / "feed.jsonl").open("a", encoding="utf-8") as f:
            f.write("\n")
        self.d.step()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(1), tok(2)])

    def test_a_line_that_is_not_json_is_skipped_and_the_loop_goes_on(self):
        self.live(RECEIVER)
        self.d.start()
        with (self.root / ".convoy" / "feed.jsonl").open("a", encoding="utf-8") as f:
            f.write("stray output, not a row\n")
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)

    def test_a_route_that_raises_never_escapes_the_loop(self):
        self.live(RECEIVER)
        self.routes.fail["channel"] = RuntimeError("boom")
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        rows = self.rows_for(tok(1) + ":" + RECEIVER + ":send")
        self.assertEqual(rows[0]["result"], "held")
        self.assertIn("boom", rows[0]["why"])

    def test_an_error_on_one_row_is_recorded_and_the_loop_moves_on(self):
        from unittest import mock
        import convoy.wake_dispatch as wd
        real = wd.read_route

        def flaky(root, chair):
            if chair == "neuron-x-thread":
                raise OSError("store unreadable")
            return real(root, chair)

        self.live(RECEIVER)
        self.send("neuron-x-thread", tok(1), inbox=False)
        self.send(RECEIVER, tok(2), inbox=False)
        self.d.start()
        with mock.patch.object(wd, "read_route", flaky):
            self.d.step()
            self.d.step()
        [row] = self.rows_for(tok(1) + ":neuron-x-thread:send")
        self.assertEqual(row["result"], "held")
        self.assertIn("OSError", row["why"])
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(2)])
        size = (self.root / ".convoy" / "feed.jsonl").stat().st_size
        self.assertEqual(int(cursor_path(self.root).read_text(encoding="utf-8")), size)

    def test_an_error_in_the_timers_leaves_the_wake_armed_for_the_next_tick(self):
        from unittest import mock
        import convoy.wake_dispatch as wd
        real, calls = wd.read_route, []

        def once(root, chair):
            calls.append(chair)
            if len(calls) == 1:
                raise OSError("store busy")
            return real(root, chair)

        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        with mock.patch.object(wd, "read_route", once):
            self.d.step()
            self.assertEqual(len(self.fired_to(RECEIVER)), 1)
            self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 2, "the refire comes on the next tick")
        rows = self.rows_for(tok(1) + ":" + RECEIVER + ":send")
        self.assertIn("OSError", " ".join(r["why"] for r in rows))

    def test_a_held_send_retried_by_catch_up_keeps_its_proven_sender(self):
        from unittest import mock
        import convoy.wake_dispatch as wd

        def broken(root, chair):
            raise OSError("store unreadable")

        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), sender=SENDER, inbox=False)
        self.d.start()
        with mock.patch.object(wd, "read_route", broken):
            self.d.step()
        self.assertEqual(self.fired_to(RECEIVER), [])
        self.d.catch_up()
        [(_, p)] = self.fired_to(RECEIVER)
        self.assertEqual(p["from"], SENDER)

    def test_run_steps_until_told_to_stop(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        sleeps = []
        self.d.run(poll_s=1.0, should_stop=lambda: len(sleeps) >= 1, sleep=sleeps.append)
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)
        self.assertEqual(sleeps, [1.0])


class ThePointer(Case):
    def test_a_pointer_names_the_wake_and_where_to_read_it(self):
        self.live(RECEIVER)
        row = self.send(RECEIVER, tok(1), sender=SENDER, inbox=False)
        self.d.start()
        self.d.step()
        [(_, p)] = self.fired_to(RECEIVER)
        self.assertEqual(p["v"], 1)
        self.assertRegex(p["wake_id"], r"^wk_[0-9a-f]{16}$")
        self.assertEqual((p["reason"], p["target"], p["token"]), ("send", RECEIVER, tok(1)))
        self.assertEqual(p["from"], SENDER)
        self.assertEqual(p["from_neuron"], neuron_id(self.cid, SENDER))
        self.assertEqual(p["stamp"], {"device": row["device"], "verified_by": row["verified_by"]})
        self.assertEqual(p["thread"], self.cid)
        self.assertEqual(p["ts"], iso(self.now))
        self.assertEqual(p["read_with"], "inbox(chair)")

    def test_a_wake_never_carries_the_body(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1))
        self.d.start()
        self.d.step()
        [(_, p)] = self.fired_to(RECEIVER)
        self.assertNotIn("body", p)
        self.assertNotIn("PRIVATE-BODY-TEXT", json.dumps(p))
        self.assertNotIn("PRIVATE-BODY-TEXT", outbox_path(self.root).read_text(encoding="utf-8"))

    def test_a_conductor_reads_its_wake_with_replies(self):
        self.live(CONDUCTOR, "board-webhook")
        self.send(CONDUCTOR, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        [(route, p)] = self.fired_to(CONDUCTOR)
        self.assertEqual(route, "board-webhook")
        self.assertEqual(p["read_with"], "replies(token)")

    def test_an_unknown_sender_is_null(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        [(_, p)] = self.fired_to(RECEIVER)
        self.assertIsNone(p["from"])
        self.assertIsNone(p["from_neuron"])


class TheBudget(Case):
    def test_a_pair_is_refused_past_its_hourly_limit_with_a_row(self):
        self.live(RECEIVER)
        self.d.start()
        for n in range(LIMITS["per_pair_per_hour"] + 1):
            self.send(RECEIVER, tok(n + 1), sender=SENDER, inbox=False)
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), LIMITS["per_pair_per_hour"])
        last = tok(LIMITS["per_pair_per_hour"] + 1)
        [row] = self.rows_for(last + ":" + RECEIVER + ":send")
        self.assertEqual(row["result"], "refused")
        self.assertIn("per_pair_per_hour", row["why"])
        feed = [json.loads(line) for line in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines()]
        refuse = [r for r in feed if r.get("kind") == "refuse"]
        self.assertEqual(len(refuse), 1)
        self.assertEqual(refuse[0]["reason"], "budget")
        self.assertEqual(sorted(refuse[0]["pair"]), sorted([SENDER, RECEIVER]))
        self.assertEqual(refuse[0]["token"], last)

    def test_the_pair_may_wake_again_an_hour_later(self):
        self.live(RECEIVER)
        self.d.start()
        for n in range(LIMITS["per_pair_per_hour"]):
            self.send(RECEIVER, tok(n + 1), sender=SENDER)
        self.d.step()
        drain(self.root, RECEIVER)
        self.d.step()
        self.advance(3601, pulse=[RECEIVER])
        self.send(RECEIVER, tok(999), sender=SENDER, inbox=False)
        self.d.step()
        self.assertEqual(self.fired_to(RECEIVER)[-1][1]["token"], tok(999))

    def test_a_target_is_refused_past_its_hourly_limit(self):
        self.live(RECEIVER)
        self.d.start()
        for n in range(LIMITS["per_target_per_hour"] + 1):
            self.send(RECEIVER, tok(n + 1), sender="neuron-" + str(n) + "-thread", inbox=False)
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), LIMITS["per_target_per_hour"])
        [row] = self.rows_for(tok(LIMITS["per_target_per_hour"] + 1) + ":" + RECEIVER + ":send")
        self.assertEqual(row["result"], "refused")
        self.assertIn("per_target_per_hour", row["why"])

    def test_a_token_is_refused_past_its_limit(self):
        self.live(SENDER)
        self.d.start()
        outbox_path(self.root).parent.mkdir(parents=True, exist_ok=True)
        with outbox_path(self.root).open("a", encoding="utf-8") as f:
            for n in range(LIMITS["per_token"]):
                f.write(json.dumps({"wake_id": "wk_" + format(n, "016x"), "dedupe_key": tok(1) + ":x" + str(n) + ":send",
                                    "target": "x" + str(n), "reason": "send", "token": tok(1), "from": None,
                                    "route": "waiter", "attempt": 1, "result": "fired", "why": "waiter",
                                    "ts": iso(self.now - timedelta(days=1))}) + "\n")
        self.feed({"ts": iso(self.now), "kind": "synapse", "instance_id": RECEIVER, "token": tok(1), "from": SENDER,
                   "verified_by": "environment"})
        self.note(RECEIVER, "re token " + tok(1) + ": done")
        self.d.step()
        [row] = self.rows_for(tok(1) + ":" + SENDER + ":reply")
        self.assertEqual(row["result"], "refused")
        self.assertIn("per_token", row["why"])

    def test_a_hold_refuses_until_its_time(self):
        self.live(RECEIVER)
        self.d.start()
        set_hold(self.root, RECEIVER, until=iso(self.now + timedelta(seconds=600)), by="person")
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.step()
        [row] = self.rows_for(tok(1) + ":" + RECEIVER + ":send")
        self.assertEqual(row["result"], "refused")
        self.assertIn("hold", row["why"])
        self.advance(601, pulse=[RECEIVER])
        self.send(RECEIVER, tok(2), inbox=False)
        self.d.step()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(2)])

    def test_a_refusal_alerts_the_person_once_an_hour(self):
        self.live(RECEIVER)
        self.d.start()
        set_hold(self.root, RECEIVER, until=iso(self.now + timedelta(hours=3)), by="person")
        self.send(RECEIVER, tok(1), inbox=False)
        self.send(RECEIVER, tok(2), inbox=False)
        self.d.step()
        self.assertEqual(len(self.routes.alerts), 1)
        self.advance(3601, pulse=[RECEIVER])
        self.send(RECEIVER, tok(3), inbox=False)
        self.d.step()
        self.assertEqual(len(self.routes.alerts), 2)


class TheHoldOnEveryFire(Case):
    def key(self):
        return tok(1) + ":" + RECEIVER + ":send"

    def test_a_hold_set_after_the_wake_stops_its_refire(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        set_hold(self.root, RECEIVER, until=iso(self.now + timedelta(hours=1)), by="person")
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1)
        last = self.rows_for(self.key())[-1]
        self.assertEqual(last["result"], "refused")
        self.assertIn("hold", last["why"])

    def test_a_hold_set_before_the_drop_stops_the_ladder(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        set_hold(self.root, RECEIVER, until=iso(self.now + timedelta(hours=1)), by="person")
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        results = [r["result"] for r in self.rows_for(self.key())]
        self.assertIn("dropped", results)
        self.assertEqual(results[-1], "refused")
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel"], "no waiter")


class TheAckTimer(Case):
    def key(self, token=tok(1)):
        return token + ":" + RECEIVER + ":send"

    def test_a_drained_inbox_row_acks_the_wake_and_verifies_the_route(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1))
        self.d.start()
        self.d.step()
        drain(self.root, RECEIVER)
        self.advance(5, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(self.rows_for(self.key())[-1]["result"], "acked")
        self.assertEqual(read_route(self.root, RECEIVER)["verified_at"], iso(self.now))

    def test_a_citing_note_answers_the_wake(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.note(RECEIVER, "re token " + tok(1) + ": done")
        self.d.step()
        self.assertEqual(self.rows_for(self.key())[-1]["result"], "answered")

    def test_an_unread_wake_is_refired_once_with_the_same_wake_id(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.advance(T_ACK["channel"] - 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1, "not before its time")
        self.advance(2, pulse=[RECEIVER])
        self.d.step()
        first, second = self.fired_to(RECEIVER)
        self.assertEqual(first[1]["wake_id"], second[1]["wake_id"])
        self.assertEqual(self.rows_for(self.key())[-1]["attempt"], 2)

    def test_a_channel_wake_unread_twice_is_dropped_then_the_waiter_then_an_alert(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        results = [r["result"] for r in self.rows_for(self.key())]
        self.assertIn("dropped", results)
        self.assertIn("no read after 2 wakes", [r["why"] for r in self.rows_for(self.key())])
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel", "waiter"])
        self.assertEqual(self.routes.alerts, [])
        self.advance(T_ACK["waiter"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.routes.alerts), 1)
        self.assertEqual(self.routes.alerts[0][0], RECEIVER)
        self.assertIn(self.key(), self.routes.alerts[0][1])
        self.advance(T_ACK["waiter"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.routes.alerts), 1, "the ladder ends at the person")
        self.assertEqual(len(self.fired_to(RECEIVER)), 3)

    def test_a_codex_queue_wake_unread_twice_goes_to_an_alert(self):
        self.live(RECEIVER, "codex-queue")
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        for _ in range(2):
            self.advance(T_ACK["codex-queue"] + 1, pulse=[RECEIVER])
            self.d.step()
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["codex-queue", "codex-queue"])
        self.assertEqual(len(self.routes.alerts), 1)

    def test_a_route_error_holds_the_wake_and_takes_the_ladder_at_once(self):
        self.live(RECEIVER)
        self.routes.fail["channel"] = RouteError("channel refused the event")
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        rows = self.rows_for(self.key())
        self.assertEqual((rows[0]["result"], rows[0]["why"]), ("held", "channel refused the event"))
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["waiter"])

    def test_a_reply_wake_is_fired_once_and_never_timed(self):
        self.live(SENDER)
        self.send(RECEIVER, tok(1), sender=SENDER, inbox=False)
        self.note(RECEIVER, "re token " + tok(1) + ": done")
        self.d.start()
        self.d.step()
        self.d.step()
        [(_, p)] = self.fired_to(SENDER)
        self.assertEqual((p["reason"], p["token"], p["from"]), ("reply", tok(1), RECEIVER))
        for _ in range(3):
            self.advance(1000, pulse=[SENDER])
            self.d.step()
        self.assertEqual(len(self.fired_to(SENDER)), 1)
        self.assertEqual(self.routes.alerts, [])

    def test_a_send_answered_before_the_wake_is_not_fired(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1))
        self.send(RECEIVER, tok(2), inbox=False)
        drain(self.root, RECEIVER)
        self.note(RECEIVER, "re token " + tok(2) + ": done")
        self.d.start()
        self.d.step()
        self.assertEqual(self.fired_to(RECEIVER), [])
        for token in (tok(1), tok(2)):
            [row] = self.rows_for(self.key(token))
            self.assertEqual((row["result"], row["why"]), ("answered", "handled before the wake"))


class TheTurnSignal(Case):
    """When an unread send wake may be refired or dropped, by the target's Stop pulse:

      a Stop pulse newer than the fire    a turn ended and did not read: T_ACK after the fire
      no Stop pulse since the fire        busy, or never woke: T_ACK_LONG after the fire
      never a Stop pulse at all           no turn signal: T_ACK after the fire
    """

    def key(self):
        return tok(1) + ":" + RECEIVER + ":send"

    def fire_one(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()

    def stop(self, seconds_from_now=0.0):
        write_pulse(self.root, RECEIVER, pulse_source="stop", ts=iso(self.now + timedelta(seconds=seconds_from_now)))

    def test_a_turn_that_ended_after_the_wake_without_reading_is_refired_after_t_ack(self):
        self.fire_one()
        self.advance(10, pulse=[RECEIVER])
        self.stop()
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1, "not before T_ACK")
        self.advance(T_ACK["channel"] - 9, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 2)

    def test_no_turn_end_since_the_wake_waits_for_t_ack_long(self):
        self.stop(-30)
        self.fire_one()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1, "busy or not woken: cannot tell yet")
        self.advance(T_ACK_LONG - T_ACK["channel"], pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 2)

    def test_an_idle_target_that_never_woke_is_dropped_at_t_ack_long(self):
        self.stop(-30)
        self.fire_one()
        self.advance(T_ACK_LONG + 1, pulse=[RECEIVER])
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertNotIn("dropped", [r["result"] for r in self.rows_for(self.key())], "the refire waits too")
        self.advance(T_ACK_LONG, pulse=[RECEIVER])
        self.d.step()
        self.assertIn("dropped", [r["result"] for r in self.rows_for(self.key())])
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel", "waiter"])

    def test_a_target_that_never_had_a_stop_pulse_uses_t_ack_alone(self):
        self.fire_one()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.assertEqual(len(self.fired_to(RECEIVER)), 2)

    def test_a_drop_records_a_wake_dropped_fault_and_the_route_reads_degraded(self):
        self.fire_one()
        for _ in range(2):
            self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
            self.d.step()
        fault = read_route(self.root, RECEIVER)["fault"]
        self.assertEqual((fault["name"], fault["by"]), ("wake-dropped", "wake-dispatcher"))
        self.assertIn(self.key(), fault["reason"])
        self.assertEqual(reachability(self.root, RECEIVER, now=iso(self.now)), "degraded")
        self.assertIn("dropped", [r["result"] for r in self.rows_for(self.key())], "the outbox row is kept")


class TheTimerErrors(Case):
    """An error in the timers is on the record, leaves the wake armed, and is written at most once
    per wake per T_ACK window. A drop whose fault or ladder step failed is completed on the next tick."""

    def key(self):
        return tok(1) + ":" + RECEIVER + ":send"

    def fire_and_refire(self):
        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
        self.d.step()
        self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])

    def test_a_fault_error_at_the_drop_is_completed_on_the_next_tick(self):
        from unittest import mock
        import convoy.wake_dispatch as wd
        real, calls = wd.record_fault, []

        def once(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("store busy")
            return real(*a, **k)

        self.fire_and_refire()
        with mock.patch.object(wd, "record_fault", once):
            self.d.step()
            self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel"])
            self.d.step()
        self.assertEqual(read_route(self.root, RECEIVER)["fault"]["name"], "wake-dropped")
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel", "waiter"])
        self.assertEqual([r["result"] for r in self.rows_for(self.key())].count("dropped"), 1)

    def test_a_ladder_error_at_the_drop_is_completed_on_the_next_tick(self):
        real, calls = self.d._fallback, []

        def once(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("store busy")
            return real(*a, **k)

        self.fire_and_refire()
        self.d._fallback = once
        self.d.step()
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel"])
        self.d.step()
        self.assertEqual([route for route, _ in self.fired_to(RECEIVER)], ["channel", "channel", "waiter"])
        self.assertEqual([r["result"] for r in self.rows_for(self.key())].count("dropped"), 1)

    def test_a_persistent_timer_error_writes_one_row_per_window(self):
        from unittest import mock
        import convoy.wake_dispatch as wd

        def broken(root, chair):
            raise OSError("store unreadable")

        self.live(RECEIVER)
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        with mock.patch.object(wd, "read_route", broken):
            for _ in range(50):
                self.d.step()
            errors = [r for r in self.rows_for(self.key()) if r["result"] == "error"]
            self.assertEqual(len(errors), 1)
            self.advance(T_ACK["channel"] + 1, pulse=[RECEIVER])
            self.d.step()
        errors = [r for r in self.rows_for(self.key()) if r["result"] == "error"]
        self.assertEqual(len(errors), 2)


class DownAndCatchUp(Case):
    def test_a_malformed_held_row_is_skipped_and_start_goes_on(self):
        self.live(RECEIVER)
        outbox_path(self.root).parent.mkdir(parents=True, exist_ok=True)
        good = {"wake_id": "wk_" + "0" * 16, "dedupe_key": tok(2) + ":" + RECEIVER + ":send", "target": RECEIVER,
                "reason": "send", "token": tok(2), "from": None, "stamp": {}, "route": None, "attempt": 0,
                "result": "held", "why": "no wake route registered", "alerted": False, "ts": iso(self.now)}
        with outbox_path(self.root).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"dedupe_key": "x:y:send", "result": "held", "route": "channel"}) + "\n")
            f.write(json.dumps(good) + "\n")
        self.d.start()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(2)])

    def test_a_receiver_that_is_down_holds_the_wake_and_alerts_once(self):
        register_route(self.root, RECEIVER, "channel", registered_by="person",
                       config={"server": "convoy-channel"}, ts=iso(self.now))
        self.send(RECEIVER, tok(1), inbox=False)
        self.send(RECEIVER, tok(2), inbox=False)
        self.d.start()
        self.d.step()
        self.assertEqual(self.fired_to(RECEIVER), [])
        for token in (tok(1), tok(2)):
            [row] = self.rows_for(token + ":" + RECEIVER + ":send")
            self.assertEqual(row["result"], "held")
            self.assertIn("receiver unreachable", row["why"])
        self.assertEqual(len(self.routes.alerts), 1)

    def test_a_chair_with_no_route_is_held_without_an_alert(self):
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        [row] = self.rows_for(tok(1) + ":" + RECEIVER + ":send")
        self.assertEqual((row["result"], row["why"]), ("held", "no wake route registered"))
        self.assertEqual(self.routes.alerts, [])

    def test_catch_up_fires_a_held_wake_once_the_receiver_is_back(self):
        register_route(self.root, RECEIVER, "channel", registered_by="person",
                       config={"server": "convoy-channel"}, ts=iso(self.now))
        self.send(RECEIVER, tok(1), inbox=False)
        self.d.start()
        self.d.step()
        self.pulse(RECEIVER)
        self.d.catch_up()
        self.d.catch_up()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(1)])

    def test_on_start_pending_inbox_rows_are_woken_and_consumed_ones_are_not(self):
        self.live(RECEIVER)
        enqueue(self.root, RECEIVER, BODY, to="claude", token=tok(1))
        drain(self.root, RECEIVER)
        enqueue(self.root, RECEIVER, BODY, to="claude", token=tok(2))
        self.d.start()
        self.assertEqual([p["token"] for _, p in self.fired_to(RECEIVER)], [tok(2)])
        self.dispatcher().start()
        self.assertEqual(len(self.fired_to(RECEIVER)), 1, "a second start is safe")


if __name__ == "__main__":
    unittest.main()
