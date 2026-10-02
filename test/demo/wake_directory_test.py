"""The wake directory: which route wakes each chair, and whether it can be reached now.

A wake route is recorded, never inferred: `.convoy/wake_routes.jsonl` is append-only and the last
row per chair wins, like seats.jsonl. Its config names references (a channel server's name, a queue
thread, a board subscription), never a secret.

Reachability is read from the chair's pulses, by source. A pulse file records its latest writer,
so a channel route could not tell a channel that stopped from a pane host that kept beating; each
source now keeps its own file beside the latest one. The rules:

  route none                          down
  a fault the route recorded          down, with its reason and when it was seen: a queue too old or not
                                      running, a harness out of credits, a parked board
                                      subscription; a later verified wake clears it
  board-webhook                       live unless a fault is recorded
  no pulse from any source in 90 s    down (the session or the device is gone)
  channel, fresh channel pulse        live
  channel, no fresh channel pulse     degraded (never loaded, or killed beside a live session)
  any other route, a fresh pulse      live
  no route registered                 None: unknown, never down

Every id and path here is synthetic, and the thread root is a temporary folder.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.pulse import PULSE_SOURCES, read_pulse, read_pulse_by_source, write_pulse
from convoy.wake_routes import (
    FAULTS,
    REACH_FRESH_SEC,
    ROUTES,
    mark_verified,
    record_fault,
    reachability,
    reachability_detail,
    read_route,
    read_routes,
    register_route,
    wake_routes_path,
)

NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


NOW_S = at(0)
CHAIR = "neuron-a-thread"


class TheStore(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_the_last_row_per_chair_wins_and_other_chairs_keep_theirs(self):
        register_route(self.root, CHAIR, "waiter", registered_by="person", ts=at(30))
        register_route(self.root, "neuron-b-thread", "codex-queue", registered_by="person",
                       config={"thread_id": "thread-0000"}, ts=at(20))
        register_route(self.root, CHAIR, "channel", registered_by=CHAIR,
                       config={"server": "convoy-channel"}, ts=at(10))
        routes = read_routes(self.root)
        self.assertEqual(routes[CHAIR]["route"], "channel")
        self.assertEqual(routes["neuron-b-thread"]["config"], {"thread_id": "thread-0000"})
        lines = wake_routes_path(self.root).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3, "append-only: nothing is rewritten")

    def test_a_row_carries_the_fields_the_directory_reads_and_unknown_is_null(self):
        row = register_route(self.root, CHAIR, "waiter", registered_by="person", neuron="n000000", ts=at(5))
        self.assertEqual(read_route(self.root, CHAIR), row)
        for key in ("chair", "neuron", "device", "route", "config", "verified_at", "fault", "registered_by", "ts"):
            self.assertIn(key, row)
        self.assertIsNone(row["fault"], "no fault until one is recorded")
        self.assertIsNone(row["device"], "no device until one is recorded")
        self.assertIsNone(row["verified_at"], "no wake receipt yet")
        self.assertNotIn("status", row, "status is derived by reachability(), never stored")

    def test_a_malformed_line_is_skipped_not_fatal(self):
        register_route(self.root, CHAIR, "waiter", registered_by="person", ts=at(5))
        with wake_routes_path(self.root).open("a", encoding="utf-8") as f:
            f.write("{not json\n")
            f.write(json.dumps({"route": "waiter"}) + "\n")  # no chair
        self.assertEqual(set(read_routes(self.root)), {CHAIR})

    def test_an_unknown_route_is_refused(self):
        with self.assertRaises(ValueError):
            register_route(self.root, CHAIR, "email", registered_by="person")
        self.assertEqual(ROUTES, ("channel", "codex-queue", "board-webhook", "waiter", "none"))

    def test_config_names_references_only_and_never_a_secret(self):
        with self.assertRaises(ValueError):
            register_route(self.root, CHAIR, "board-webhook", registered_by="person",
                           config={"subscription_id": "wh-0000", "secret": "x"})
        with self.assertRaises(ValueError):
            register_route(self.root, CHAIR, "channel", registered_by="person", config={"thread_id": "t"})
        row = register_route(self.root, CHAIR, "board-webhook", registered_by="person",
                             config={"subscription_id": "wh-0000", "agent_id": "agent-0000"})
        self.assertEqual(row["config"]["subscription_id"], "wh-0000")

    def test_config_values_are_short_plain_strings_and_never_a_secret(self):
        refused = [
            ("channel", {"server": ""}),
            ("channel", {"server": "   "}),
            ("channel", {"server": {"name": "convoy-channel"}}),
            ("codex-queue", {"thread_id": ["thread-0000"]}),
            ("codex-queue", {"thread_id": 7}),
            ("codex-queue", {"thread_id": "t" * 201}),
            ("board-webhook", {"subscription_id": "Bearer abc123"}),
            ("board-webhook", {"subscription_id": "wh-0000", "agent_id": "sk-abc123"}),
            ("codex-queue", {"thread_id": "thread-0000?token=abc"}),
        ]
        for route, config in refused:
            with self.assertRaises(ValueError, msg=repr(config)):
                register_route(self.root, CHAIR, route, registered_by="person", config=config)
        self.assertEqual(read_routes(self.root), {}, "a refused row is never written")
        register_route(self.root, CHAIR, "codex-queue", registered_by="person", config={"thread_id": "t" * 200})

    def test_common_credential_shapes_are_refused_and_a_name_that_merely_contains_sk_is_not(self):
        shapes = [
            "ghp_" + "a" * 36, "gho_" + "b" * 36, "ghs_" + "c" * 36, "github_pat_" + "d" * 40,
            "xoxb-1234-abcd", "xoxp-1234-abcd", "xoxa-1", "xoxr-1", "xoxs-1",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig",
            "AKIA" + "ABCDEFGHIJKLMNOP",
            "sk-abc123", "key: sk-abc123", "k=sk-abc123",
        ]
        for value in shapes:
            with self.assertRaises(ValueError, msg=value):
                register_route(self.root, CHAIR, "codex-queue", registered_by="person", config={"thread_id": value})
        for value in ("my-desk-sk-1", "my_sk-1", "task-list", "askew"):
            register_route(self.root, CHAIR, "codex-queue", registered_by="person", config={"thread_id": value})
        self.assertEqual(read_route(self.root, CHAIR)["config"]["thread_id"], "askew")

    def test_an_sk_key_after_any_separator_and_temporary_or_live_keys_are_refused(self):
        for value in ("/sk-abc123", '"sk-abc123', "x,sk-abc123", "sk_live_abc123", "ASIA" + "ABCDEFGHIJKLMNOP"):
            with self.assertRaises(ValueError, msg=value):
                register_route(self.root, CHAIR, "codex-queue", registered_by="person", config={"thread_id": value})

    def test_an_aws_key_id_is_upper_case_so_a_lower_case_name_is_accepted(self):
        for value in ("akia" + "abcdefghijklmnop", "asia" + "abcdefghijklmnop"):
            register_route(self.root, CHAIR, "codex-queue", registered_by="person", config={"thread_id": value})

    def test_a_row_whose_route_is_unknown_is_skipped(self):
        register_route(self.root, CHAIR, "waiter", registered_by="person", ts=at(5))
        with wake_routes_path(self.root).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"chair": CHAIR, "route": "email", "ts": at(1)}) + "\n")
        self.assertEqual(read_route(self.root, CHAIR)["route"], "waiter", "a row no reader understands is not the last word")

    def test_an_unreadable_store_reads_as_no_routes_and_never_raises(self):
        from unittest import mock
        path = wake_routes_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28\n")
        self.assertEqual(read_routes(self.root), {})
        register_route(self.root, "neuron-c-thread", "waiter", registered_by="person")
        with mock.patch.object(Path, "read_text", side_effect=OSError("locked")):
            self.assertEqual(read_routes(self.root), {})
            self.assertIsNone(reachability(self.root, "neuron-c-thread", now=NOW_S))

    def test_mark_verified_records_the_receipt_time_and_keeps_the_route(self):
        register_route(self.root, CHAIR, "channel", registered_by=CHAIR, config={"server": "convoy-channel"}, ts=at(60))
        mark_verified(self.root, CHAIR, ts=at(1))
        row = read_route(self.root, CHAIR)
        self.assertEqual(row["verified_at"], at(1))
        self.assertEqual(row["route"], "channel")
        self.assertEqual(row["config"], {"server": "convoy-channel"})

    def test_mark_verified_without_a_route_is_refused(self):
        with self.assertRaises(ValueError):
            mark_verified(self.root, CHAIR, ts=at(1))


class PulsesBySource(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_channel_is_a_pulse_source(self):
        self.assertIn("channel", PULSE_SOURCES)

    def test_each_source_keeps_its_own_pulse_and_the_latest_is_still_read(self):
        write_pulse(self.root, CHAIR, pulse_source="channel", ts=at(50))
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(10))
        self.assertEqual(read_pulse(self.root, CHAIR)["pulse_source"], "host", "the latest writer, as before")
        self.assertEqual(read_pulse_by_source(self.root, CHAIR, "channel")["ts"], at(50))
        self.assertEqual(read_pulse_by_source(self.root, CHAIR, "host")["ts"], at(10))
        self.assertIsNone(read_pulse_by_source(self.root, CHAIR, "stop"))


class Reachability(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _route(self, route, **kw):
        register_route(self.root, CHAIR, route, registered_by="person", ts=at(3600), **kw)

    def _detail(self):
        return reachability_detail(self.root, CHAIR, now=NOW_S)

    def test_the_window_is_ninety_seconds(self):
        self.assertEqual(REACH_FRESH_SEC, 90)

    def test_no_route_registered_is_unknown_not_down(self):
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(5))
        self.assertIsNone(reachability(self.root, CHAIR, now=NOW_S))
        self.assertEqual(self._detail()["reason"], "no wake route registered")

    def test_route_none_is_down(self):
        self._route("none")
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(5))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "down")

    def test_a_waiter_with_a_fresh_pulse_is_live(self):
        self._route("waiter")
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(30))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live")

    def test_no_pulse_within_the_window_is_down(self):
        self._route("waiter")
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(120))
        d = self._detail()
        self.assertEqual(d["reachable"], "down")
        self.assertIn("no pulse", d["reason"])
        self._route("channel", config={"server": "convoy-channel"})
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "down", "no pulse at all is down for a channel too")

    def test_a_channel_route_with_a_fresh_channel_pulse_is_live(self):
        self._route("channel", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="channel", ts=at(20))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live")

    def test_a_channel_never_loaded_beside_a_live_session_is_degraded(self):
        self._route("channel", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(20))
        d = self._detail()
        self.assertEqual(d["reachable"], "degraded")
        self.assertIn("channel not loaded", d["reason"])

    def test_a_channel_pulse_gone_stale_beside_a_live_session_is_degraded(self):
        self._route("channel", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="channel", ts=at(300))
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(20))
        d = self._detail()
        self.assertEqual(d["reachable"], "degraded")
        self.assertIn("channel stopped", d["reason"])

    def test_a_recorded_queue_fault_is_down_with_its_name_reason_and_time(self):
        self._route("codex-queue", config={"thread_id": "thread-0000"})
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(5))
        record_fault(self.root, CHAIR, "codex-too-old", reason="unrecognized subcommand 'queue'",
                     by="dispatcher", seen_at=at(2))
        d = self._detail()
        self.assertEqual(d["reachable"], "down")
        self.assertIn("codex-too-old", d["reason"])
        self.assertIn("unrecognized subcommand", d["reason"])
        fault = read_route(self.root, CHAIR)["fault"]
        self.assertEqual((fault["name"], fault["by"], fault["seen_at"]), ("codex-too-old", "dispatcher", at(2)))
        self.assertEqual(read_route(self.root, CHAIR)["route"], "codex-queue", "the route itself is kept")
        with self.assertRaises(ValueError):
            record_fault(self.root, CHAIR, "it broke", reason="x", by="dispatcher")
        with self.assertRaises(ValueError):
            record_fault(self.root, CHAIR, "codex-too-old", reason="", by="dispatcher")

    def test_a_harness_out_of_credits_is_down_while_it_still_pulses(self):
        self._route("codex-queue", config={"thread_id": "thread-0000"})
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(5))
        record_fault(self.root, CHAIR, "out-of-credits",
                     reason="turns end in 1 s: usage_limit_exceeded", by="dispatcher", seen_at=at(3))
        self.assertIn("out-of-credits", FAULTS)
        d = self._detail()
        self.assertEqual(d["reachable"], "down", "a fresh pulse does not make an out-of-credits harness reachable")
        self.assertIn("usage_limit_exceeded", d["reason"])

    def test_a_later_verified_wake_clears_the_fault(self):
        self._route("codex-queue", config={"thread_id": "thread-0000"})
        write_pulse(self.root, CHAIR, pulse_source="host", ts=at(5))
        record_fault(self.root, CHAIR, "out-of-credits", reason="usage_limit_exceeded", by="dispatcher", seen_at=at(60))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "down")
        mark_verified(self.root, CHAIR, ts=at(1))
        row = read_route(self.root, CHAIR)
        self.assertIsNone(row["fault"])
        self.assertEqual(row["verified_at"], at(1))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live")

    def test_a_fault_without_a_route_is_refused(self):
        with self.assertRaises(ValueError):
            record_fault(self.root, CHAIR, "codex-not-running", reason="exit 1", by="dispatcher")

    def test_a_codex_queue_with_a_fresh_pulse_and_no_fault_is_live(self):
        self._route("codex-queue", config={"thread_id": "thread-0000"})
        write_pulse(self.root, CHAIR, pulse_source="stop", ts=at(40))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live")

    def test_a_board_webhook_is_live_until_its_subscription_parks_and_again_after_a_verified_wake(self):
        self._route("board-webhook", config={"subscription_id": "wh-0000", "agent_id": "agent-0000"})
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live", "no local pulse: the board queues it")
        record_fault(self.root, CHAIR, "subscription-parked", reason="parked after 6 failed deliveries",
                     by="board-reader", seen_at=at(30))
        d = self._detail()
        self.assertEqual(d["reachable"], "down")
        self.assertIn("parked", d["reason"])
        self.assertEqual(read_route(self.root, CHAIR)["fault"]["by"], "board-reader")
        mark_verified(self.root, CHAIR, ts=at(1))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live", "a re-enabled subscription does not stay down")

    def test_a_dropped_wake_degrades_a_live_route_until_a_verified_wake(self):
        self._route("channel", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="channel", ts=at(5))
        record_fault(self.root, CHAIR, "wake-dropped", reason="no read after 2 wakes", by="wake-dispatcher",
                     seen_at=at(2))
        self.assertIn("wake-dropped", FAULTS)
        d = self._detail()
        self.assertEqual(d["reachable"], "degraded", "the route still pulses; its wakes went unread")
        self.assertIn("wake-dropped", d["reason"])
        self.assertIn("no read after 2 wakes", d["reason"])
        mark_verified(self.root, CHAIR, ts=at(1))
        self.assertEqual(reachability(self.root, CHAIR, now=NOW_S), "live")

    def test_a_dropped_wake_on_a_route_with_no_pulse_is_down(self):
        self._route("waiter")
        record_fault(self.root, CHAIR, "wake-dropped", reason="no read after 2 wakes", by="wake-dispatcher",
                     seen_at=at(2))
        d = self._detail()
        self.assertEqual(d["reachable"], "down")
        self.assertIn("no pulse", d["reason"])


if __name__ == "__main__":
    unittest.main()


class TheNeuronsView(unittest.TestCase):
    """`convoy neurons` (CLI and MCP) and `convoy neurons --all` show each neuron's wake route and
    whether it is reachable, beside the provenance fields: never null where a record exists."""

    def setUp(self):
        from convoy.convoy import bind, ensure_id, seat
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t-directory")
        seat(self.root, "claude", CHAIR, worktree=r"C:\w\directory-a")
        seat(self.root, "codex", "neuron-b-thread", worktree=r"C:\w\directory-b")

    def _rows(self):
        from convoy.activity import neuron_activity
        return {n["session_id"]: n for n in neuron_activity(self.root)["neurons"]}

    def test_a_neuron_with_a_route_shows_it_and_its_reachability_with_the_reason(self):
        register_route(self.root, CHAIR, "channel", registered_by="person", config={"server": "convoy-channel"})
        write_pulse(self.root, CHAIR, pulse_source="host")
        row = self._rows()[CHAIR]
        self.assertEqual(row["wake_route"], "channel")
        self.assertEqual(row["reachable"], "degraded")
        self.assertIn("channel not loaded", row["reachable_reason"])
        for key in ("device", "verified_by", "author_claimed"):
            self.assertIn(key, row, "the provenance fields stay beside the directory's")

    def test_a_neuron_with_no_route_shows_null_route_and_unknown_reachability(self):
        row = self._rows()["neuron-b-thread"]
        self.assertIsNone(row["wake_route"])
        self.assertIsNone(row["reachable"])
        self.assertEqual(row["reachable_reason"], "no wake route registered")

    def test_neurons_all_carries_the_same_fields(self):
        from unittest import mock
        from convoy.activity import neurons_everywhere
        register_route(self.root, CHAIR, "waiter", registered_by="person")
        write_pulse(self.root, CHAIR, pulse_source="host")
        thread = {"thread": "t-directory", "root": str(self.root), "present": True, "hidden": False, "convoy_id": None}
        with mock.patch("convoy.index.list_threads", return_value=[thread]), \
                mock.patch("convoy.index.is_discoverable_thread", return_value=True):
            rows = {r["neuron"]: r for r in neurons_everywhere()["rows"]}
        self.assertEqual((rows[CHAIR]["wake_route"], rows[CHAIR]["reachable"]), ("waiter", "live"))
        self.assertIn("reachable_reason", rows[CHAIR])
        self.assertEqual((rows["neuron-b-thread"]["wake_route"], rows["neuron-b-thread"]["reachable"]), (None, None))
