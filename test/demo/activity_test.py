"""`convoy neurons`: who is active on this thread and how do I reach them.

Marco 2026-09-03: "We should be able to see active neurons in this Terminal
tab and send messages. We should be able to understand what neurons are
active." Neither `panes` nor `graph` answered that: panes reports the OS
process table, which on Windows cannot place a codex or claude body at all
(8 codex processes, chair reported unknown), and graph reports structure, not
recency.

The strongest liveness evidence Convoy actually holds is the bus itself: a
chair that AUTHORED a row six minutes ago is demonstrably alive, whatever the
process table can or cannot see. This view leads with that, carries the
process evidence beside it as a second opinion, and hands back the exact
command to message each chair.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_activity
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.inbox import enqueue
from convoy.layer import hook


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class NeuronActivity(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "grok", "talker", worktree="/w/talker", model="grok-4.6")
        seat(self.root, "codex", "quiet", worktree="/w/quiet")
        seat(self.root, "claude", "never", worktree="/w/never")
        # talker spoke last; quiet spoke earlier; never spoke at all
        hook(self.root, "note", "hello from quiet", instance_id="quiet", author="quiet", to="talker")
        hook(self.root, "note", "hello from talker", instance_id="talker", author="talker", to="quiet")

    def _by(self, card):
        return {n["session_id"]: n for n in card["neurons"]}

    def test_a_chair_that_authored_a_row_is_active_even_when_unplaceable(self):
        # no process evidence at all: the bus is the evidence
        card = neuron_activity(self.root, procs=[])
        by = self._by(card)
        self.assertTrue(by["talker"]["active"])
        self.assertEqual(by["talker"]["evidence"], "authored")
        self.assertTrue(by["quiet"]["active"])
        self.assertFalse(by["never"]["active"])
        self.assertIsNone(by["never"]["last_authored"])
        self.assertEqual(by["never"]["evidence"], "silent")

    def test_most_recently_active_first(self):
        order = [n["session_id"] for n in neuron_activity(self.root, procs=[])["neurons"]]
        self.assertEqual(order[:2], ["talker", "quiet"])
        self.assertEqual(order[-1], "never")

    def test_unread_counts_rows_addressed_after_its_last_word(self):
        hook(self.root, "note", "ping 1", instance_id="talker", author="talker", to="quiet")
        hook(self.root, "note", "ping 2", instance_id="talker", author="talker", to="quiet")
        by = self._by(neuron_activity(self.root, procs=[]))
        # setUp already addressed one row to quiet after quiet's own last word
        self.assertEqual(by["quiet"]["unread"], 3)
        self.assertEqual(by["quiet"]["last_addressed_by"], "talker")
        self.assertEqual(by["talker"]["unread"], 0)

    def test_pending_inbox_is_counted_separately_from_feed_unread(self):
        enqueue(self.root, "quiet", "queued body", to="codex")
        by = self._by(neuron_activity(self.root, procs=[]))
        self.assertEqual(by["quiet"]["inbox_pending"], 1)
        self.assertEqual(by["talker"]["inbox_pending"], 0)

    def test_process_evidence_rides_along_and_upgrades_the_reason(self):
        procs = [{"pid": 9, "ppid": 1, "cmdline": "grok -m grok-4.6 --agent /w/talker/.grok/a.md", "cwd": None},
                 {"pid": 10, "ppid": 1, "cmdline": "node /x/codex.js", "cwd": None}]
        by = self._by(neuron_activity(self.root, procs=procs))
        self.assertIs(by["talker"]["process"], True)
        self.assertEqual(by["talker"]["evidence"], "authored+process")
        # an unplaceable codex process makes quiet's process evidence UNKNOWN,
        # never a claim of dead
        self.assertIsNone(by["quiet"]["process"])
        # and a chair whose harness has no process at all is honestly False
        self.assertIs(by["never"]["process"], False)

    def test_every_neuron_carries_the_command_that_messages_it_and_no_token(self):
        seat(self.root, "claude", "tokened", worktree="/w/tok", resume="super-secret-uuid")
        card = neuron_activity(self.root, procs=[])
        blob = json.dumps(card)
        self.assertNotIn("super-secret-uuid", blob)
        for n in card["neurons"]:
            self.assertIn("hook note", n["send_command"])
            self.assertIn(n["session_id"], n["send_command"])
            self.assertIn("--root", n["send_command"])

    def test_cli_neurons_reports_and_exits_zero(self):
        rc, card = _run_cli(self.root, "neurons")
        self.assertEqual(rc, 0)
        self.assertEqual(card["thread"], "t1")
        self.assertEqual(card["active_count"], 2)
        self.assertEqual(len(card["neurons"]), 3)

    def test_since_window_narrows_active(self):
        card = neuron_activity(self.root, procs=[], since="2099-01-01T00:00:00Z")
        self.assertEqual([n["session_id"] for n in card["neurons"] if n["active"]], [])


if __name__ == "__main__":
    unittest.main()


class EveryThreadOnTheMachine(unittest.TestCase):
    """Marco 2026-09-13: `/convoy-list` is one table across threads,
    harness | model | neuron | thread, so a person knows who to message before
    typing a send. `neurons --all` walks the machine index deterministically;
    hidden threads and roots that are gone are left out and named as such."""
    def setUp(self):
        import os
        from unittest import mock
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        self.a = Path(tempfile.mkdtemp()); ensure_id(self.a); bind(self.a, "alpha")
        seat(self.a, "claude", "c-alpha", worktree=str(self.a), model="claude-fable-5")
        hook(self.a, "note", "hello", instance_id="c-alpha")
        self.b = Path(tempfile.mkdtemp()); ensure_id(self.b); bind(self.b, "beta")
        seat(self.b, "codex", "x-beta", worktree=str(self.b), model="gpt-5.6-sol")
        from convoy.convoy import read_id
        from convoy.index import record, set_hidden
        record(self.a, read_id(self.a), "alpha"); record(self.b, read_id(self.b), "beta")
        self.c = Path(tempfile.mkdtemp()); ensure_id(self.c); bind(self.c, "gamma"); record(self.c, read_id(self.c), "gamma")
        set_hidden(read_id(self.c), True)

    def test_all_threads_is_one_flat_table_of_chairs(self):
        from convoy.activity import neurons_everywhere
        card = neurons_everywhere()
        self.assertTrue(card["ok"])
        rows = {(r["harness"], r["model"], r["neuron"], r["thread"]) for r in card["rows"]}
        self.assertIn(("claude", "claude-fable-5", "c-alpha", "alpha"), rows)
        self.assertIn(("codex", "gpt-5.6-sol", "x-beta", "beta"), rows)
        self.assertFalse(any(r["thread"] == "gamma" for r in card["rows"]), "hidden threads stay off the table")
        self.assertEqual(card["skipped"], [{"thread": "gamma", "reason": "hidden"}])
        for r in card["rows"]:
            self.assertIn("active", r); self.assertIn("root", r); self.assertIn("send_command", r)
            self.assertNotIn("token", json.dumps(r))

    def test_cli_neurons_all_prints_the_table_card(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["neurons", "--all"])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0); self.assertEqual(card["columns"], ["id", "harness", "model", "neuron", "thread"])
        self.assertGreaterEqual(len(card["rows"]), 2)


class ShortNeuronId(unittest.TestCase):
    """Marco 2026-09-13: "an additional .id so we can say send --id". A short,
    stable handle per chair, derived from convoy_id and session_id, so a send
    names one neuron on one thread without a root path or a harness word."""
    def setUp(self):
        import os
        from unittest import mock
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        from convoy.convoy import read_id
        from convoy.index import record
        self.a = Path(tempfile.mkdtemp()); ensure_id(self.a); bind(self.a, "alpha")
        seat(self.a, "codex", "x-alpha", worktree=str(self.a), model="gpt-5.6-sol"); record(self.a, read_id(self.a), "alpha")
        self.b = Path(tempfile.mkdtemp()); ensure_id(self.b); bind(self.b, "beta")
        seat(self.b, "codex", "x-beta", worktree=str(self.b), model="gpt-5.6-sol"); record(self.b, read_id(self.b), "beta")

    def test_every_row_carries_a_short_stable_id(self):
        from convoy.activity import neurons_everywhere, neuron_id
        from convoy.convoy import read_id
        rows = {r["neuron"]: r for r in neurons_everywhere()["rows"]}
        nid = rows["x-alpha"]["id"]
        self.assertRegex(nid, r"^n[0-9a-f]{6}$")
        self.assertEqual(nid, neuron_id(read_id(self.a), "x-alpha"), "derived, so it never changes and is never stored")
        self.assertNotEqual(nid, rows["x-beta"]["id"], "same harness, same model, different thread: different id")
        self.assertEqual(neurons_everywhere()["rows"][0]["id"], rows[neurons_everywhere()["rows"][0]["neuron"]]["id"])

    def test_resolve_finds_the_one_chair_or_says_why_not(self):
        from convoy.activity import neurons_everywhere, resolve_neuron_id
        rows = {r["neuron"]: r for r in neurons_everywhere()["rows"]}
        hit = resolve_neuron_id(rows["x-beta"]["id"])
        self.assertTrue(hit["ok"]); self.assertEqual(hit["session_id"], "x-beta"); self.assertEqual(Path(hit["root"]), self.b.resolve()); self.assertEqual(hit["to"], "codex")
        miss = resolve_neuron_id("n000000")
        self.assertFalse(miss["ok"]); self.assertIn("no neuron", miss["error"]); self.assertIn("convoy neurons --all", miss["error"])

    def test_cli_send_by_id_queues_on_that_chair_in_its_thread(self):
        from convoy.activity import neurons_everywhere
        rows = {r["neuron"]: r for r in neurons_everywhere()["rows"]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["send", "--id", rows["x-beta"]["id"], "take the importer"])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["session_id"], "x-beta"); self.assertEqual(card["thread"], "beta")
        inbox = self.b / ".convoy" / "inbox" / "x-beta.jsonl"
        self.assertTrue(inbox.is_file(), "the row landed in beta's inbox, not the cwd thread")
        self.assertIn("take the importer", inbox.read_text(encoding="utf-8"))
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = main(["send", "--id", "n000000", "x"])
        self.assertEqual(rc2, 1); self.assertFalse(json.loads(buf2.getvalue())["ok"])
