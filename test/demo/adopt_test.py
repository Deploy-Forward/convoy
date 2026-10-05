"""`convoy adopt`: give an existing neuron a launcher, so messages can flow back.

A neuron with no recorded launcher (every seat from before launches recorded one, or a
launcher that has gone) has nobody to report to. `adopt --id <neuron id>` (or `--seat <chair>`)
makes the proven caller its launcher, attaching the caller first when it is not seated, and
then sends the neuron one message naming its new launcher and the commands to report and
answer, so the return path exists at once. A live recorded launcher is replaced only by the
thread's lead.

Every id is synthetic; roots and the Convoy home are temporary; no harness runs.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import panes  # noqa: E402
from convoy.activity import neuron_id  # noqa: E402
from convoy.convoy import bind, list_seats, read_id, seat, update_seat  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import lead_state, take_lead  # noqa: E402

EPOCH = "1970-01-01T00:00:00.000000Z"
CHAIN = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
         {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]


class Base(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-adopt-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        d = tempfile.TemporaryDirectory(prefix="convoy-adopt-root-")
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        bind(self.root, "adopt")
        self.chair("worker", "claude")   # a codex chair's send would ask the real `codex queue`
        self.chair("caller", "claude")

    def chair(self, sid, harness="claude"):
        wt = tempfile.TemporaryDirectory(prefix="convoy-adopt-wt-")
        self.addCleanup(wt.cleanup)
        seat(self.root, harness, sid, worktree=wt.name, resume=sid + "-native")
        return sid

    def me(self, sid, via="environment"):
        return {"ok": True, "chair": sid, "via": via, "harness": "claude"}

    def nid(self, sid):
        return neuron_id(read_id(self.root), sid)

    def row(self, sid):
        return next(s for s in list_seats(self.root) if s["session_id"] == sid)

    def adopt(self, target="worker", me=None, **kw):
        from convoy.adopt import adopt
        return adopt(self.root, target, me=me or self.me("caller"), **kw)

    def sent_to_worker(self):
        return [r for r in feed_since(self.root, EPOCH) if r.get("kind") == "synapse" and r.get("instance_id") == "worker"]


class AdoptGivesANeuronItsLauncher(Base):
    def test_a_null_launcher_is_set_and_the_neuron_is_told(self):
        update_seat(self.root, "worker", launched_by=None, launched_by_why="an older launch")
        card = self.adopt()
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["previous_launched_by"], card["launched_by"]), (None, "caller"))
        self.assertTrue(card["token"])
        self.assertEqual(self.row("worker")["launched_by"], "caller")
        [sent] = self.sent_to_worker()
        self.assertEqual((sent["from"], sent["token"]), ("caller", card["token"]))
        body = card["message"]
        self.assertIn("Your launcher is now caller (neuron " + self.nid("caller") + ")", body)
        self.assertIn('report "..."', body)
        self.assertIn("reply <token>", body)

    def test_a_seat_with_no_launcher_field_at_all_is_adopted(self):
        self.assertNotIn("launched_by", self.row("worker"))
        self.assertTrue(self.adopt()["ok"])
        self.assertEqual(self.row("worker")["launched_by"], "caller")

    def test_after_adopt_the_neurons_report_routes_to_the_adopter(self):
        from convoy.route import report
        self.adopt()
        card = report(self.root, "synthetic result", me=self.me("worker"))
        self.assertEqual((card["routed_to"], card["route"]), ("caller", "launcher"), card)

    def test_a_gone_or_detached_launcher_is_replaced(self):
        update_seat(self.root, "worker", launched_by="never-seated")
        self.assertTrue(self.adopt()["ok"])
        self.chair("old-launcher")
        update_seat(self.root, "old-launcher", detached=True)
        update_seat(self.root, "worker", launched_by="old-launcher")
        card = self.adopt()
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["previous_launched_by"], "old-launcher")


class AdoptOverALiveLauncher(Base):
    def setUp(self):
        super().setUp()
        self.chair("live-launcher")
        update_seat(self.root, "worker", launched_by="live-launcher")

    def test_a_non_lead_caller_is_refused_and_told_why(self):
        card = self.adopt()
        self.assertFalse(card["ok"], card)
        self.assertIn("live-launcher", card["error"])
        self.assertIn("lead", card["error"])
        self.assertEqual(self.row("worker")["launched_by"], "live-launcher")
        self.assertEqual(self.sent_to_worker(), [])

    def test_the_lead_may_replace_it(self):
        take_lead(self.root, "caller", lead_state(self.root))
        card = self.adopt()
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["previous_launched_by"], card["launched_by"]), ("live-launcher", "caller"))


class AdoptNeedsAProvenCaller(Base):
    def test_a_cwd_only_caller_is_refused(self):
        card = self.adopt(me=self.me("caller", via="cwd"))
        self.assertFalse(card["ok"], card)
        self.assertNotIn("launched_by", self.row("worker"))

    def test_a_pane_host_proven_caller_may_adopt(self):
        self.assertTrue(self.adopt(me=self.me("caller", via="pane-host"))["ok"])

    def test_a_chair_cannot_adopt_itself(self):
        card = self.adopt(me=self.me("worker"))
        self.assertFalse(card["ok"], card)

    def test_an_unseated_proven_caller_is_attached_first(self):
        from convoy.launcher import resolve_launcher
        with mock.patch.object(panes, "_TEST_PROCS", CHAIN), mock.patch.object(panes, "_TEST_PID", 21):
            env = {"CLAUDE_CODE_SESSION_ID": "orchestrator-native"}
            resolved = resolve_launcher(self.root, env=env, cwd=tempfile.mkdtemp())
            self.assertEqual(resolved["kind"], "unseated", resolved)
            card = self.adopt(me={"ok": False, "chair": None}, launcher=resolved)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["attached"])
        self.assertEqual(self.row("worker")["launched_by"], card["launched_by"])
        self.assertNotIn(card["launched_by"], ("caller", "worker"))


class AdoptCli(Base):
    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main_cli(["--root", str(self.root), *args])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_adopt_by_seat_and_by_neuron_id(self):
        with mock.patch("convoy.cli.identify", return_value=self.me("caller")):
            rc, card = self.cli("adopt", "--seat", "worker")
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.row("worker")["launched_by"], "caller")
        self.chair("second")
        with mock.patch("convoy.cli.identify", return_value=self.me("caller")), \
             mock.patch("convoy.index.is_temp_root", return_value=False):
            rc, card = self.cli("adopt", "--id", self.nid("second"))
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.row("second")["launched_by"], "caller")


def main_cli(argv):
    from convoy.cli import main
    return main(argv)


class ReportNamesTheFix(Base):
    def test_a_refused_report_says_to_run_adopt_with_the_neurons_id(self):
        from convoy.route import report
        card = report(self.root, "x", me=self.me("worker"))
        self.assertFalse(card["ok"], card)
        self.assertIn("convoy adopt --id " + self.nid("worker"), card["why"])
        self.assertIn("ask the person or your conductor", card["why"])


class AdoptIsSafeToRetryAndRace(Base):
    def test_a_detached_neuron_is_refused_before_any_write(self):
        update_seat(self.root, "worker", detached=True)
        card = self.adopt()
        self.assertFalse(card["ok"], card)
        self.assertIn("detached", card["error"])
        self.assertNotIn("launched_by", self.row("worker"))
        self.assertEqual(self.sent_to_worker(), [])

    def test_a_send_that_fails_after_the_write_rolls_launched_by_back(self):
        update_seat(self.root, "worker", launched_by=None, launched_by_why="an older launch")
        with mock.patch("convoy.synapse.send_one", return_value={"ok": False, "error": "synthetic: no route"}):
            card = self.adopt()
        self.assertFalse(card["ok"], card)
        self.assertIsNone(self.row("worker")["launched_by"])

    def test_the_cards_token_is_the_sends_own(self):
        with mock.patch("convoy.synapse.send_one", return_value={"ok": True, "token": "a" * 32, "delivery": "queued"}):
            card = self.adopt()
        self.assertEqual(card["token"], "a" * 32)

    def test_a_launcher_that_changed_while_adopting_refuses(self):
        with mock.patch("convoy.adopt._current_launcher", return_value="someone-else"):
            card = self.adopt()
        self.assertFalse(card["ok"], card)
        self.assertIn("launcher changed while adopting; run adopt again", card["error"])
        self.assertEqual(self.sent_to_worker(), [])

    def test_two_concurrent_adopts_have_one_winner_and_one_message(self):
        from convoy import adopt as adopt_mod
        self.chair("rival")
        state = {"inner": None}
        real = adopt_mod._before_write

        def interleave(*a, **k):
            if state["inner"] is None:
                state["inner"] = "running"
                state["inner"] = adopt_mod.adopt(self.root, "worker", me=self.me("rival"))
            return real(*a, **k)

        with mock.patch.object(adopt_mod, "_before_write", side_effect=interleave):
            outer = self.adopt()
        inner = state["inner"]
        self.assertEqual(sorted([bool(outer["ok"]), bool(inner["ok"])]), [False, True], (outer, inner))
        self.assertEqual(len(self.sent_to_worker()), 1)
        self.assertEqual(self.row("worker")["launched_by"], "rival")

    def test_an_outsider_who_just_took_a_dangling_lead_cannot_replace_a_live_launcher(self):
        from convoy.convoy import set_lead
        from convoy.launcher import resolve_launcher
        self.chair("live-launcher")
        update_seat(self.root, "worker", launched_by="live-launcher")
        set_lead(self.root, "codex")   # a lead file naming a harness no chair holds: dangling
        self.assertEqual(lead_state(self.root)["status"], "dangling")
        with mock.patch.object(panes, "_TEST_PROCS", CHAIN), mock.patch.object(panes, "_TEST_PID", 21):
            resolved = resolve_launcher(self.root, env={"CLAUDE_CODE_SESSION_ID": "outsider-native"},
                                        cwd=tempfile.mkdtemp())
            card = self.adopt(me={"ok": False, "chair": None}, launcher=resolved)
        self.assertFalse(card["ok"], card)
        self.assertEqual(self.row("worker")["launched_by"], "live-launcher")


class AdoptLeavesAPendingLaunchAlone(Base):
    def test_a_chair_not_yet_launched_is_refused(self):
        from convoy.lifecycle import join
        join(self.root, "codex", session_id="pending", worktree=tempfile.mkdtemp())
        card = self.adopt("pending")
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "this chair has not launched yet; its launch will record its launcher")
        self.assertNotIn("launched_by", self.row("pending"))


if __name__ == "__main__":
    unittest.main()
