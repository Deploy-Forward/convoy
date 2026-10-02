"""The occupancy rule: a relaunch never adds a second body to a chair.

Without it several bodies of one chair can be alive at once. `relaunch()` did
not ask whether the chair was occupied: an earlier kill coupling was removed
after a stale close request killed a fresh body two seconds after start, and
nothing replaced it. The memory pressure such orphaned bodies create is what
kills the waiters.

Four guarantees, in the order a caller meets them:

1. A live body of the CURRENT incarnation with no death row refuses the
   relaunch by name and says what to run instead. Refuse is the default: from
   the outside, a sleeping harness and a crashed one look the same.
2. `--take-over` is the human's consent. It writes `kind=evicted` carrying the
   pid and the evidence, asks the host to close THAT life by incarnation, and
   launches only once the body is recorded as exited.
3. Automatic take-over needs a `kind=unreachable` row for that incarnation.
   Nothing else may evict a body nobody proved deaf.
4. A body that is gone still leaves a reason: relaunch writes
   `kind=unreachable {chair, since, evidence}` before it spawns, so the record
   says whether the chair died, was closed, or was never hosted.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat
from convoy.layer import feed_since, hook
from convoy.pane_host import close_request_path
from convoy.relaunch import relaunch

EPOCH = "1970-01-01T00:00:00.000000Z"


def _rows(root, kind):
    return [r for r in feed_since(root, EPOCH) if r.get("kind") == kind]


def _seat_row(root, sid):
    return [s for s in list_seats(root) if s.get("session_id") == sid][-1]




class OccupancyOnRelaunch(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "occupancy-t")
        self.worktree = Path(tempfile.mkdtemp())
        seat(self.root, "codex", "chair", worktree=str(self.worktree))
        # A body recorded by the pane host: incarnation 1, pid 999, running.
        update_seat(self.root, "chair", incarnation=1, harness_pid=999,
                    launched_at="2026-09-17T10:00:00.000000Z", process_state="running")
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def _relaunch(self, **kw):
        alive = kw.pop("alive", lambda pid: int(pid) == 999)
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            return relaunch(self.root, runner=self.runner, alive=alive, **kw)

    def test_relaunch_refuses_live_body_by_name(self):
        card = self._relaunch()
        chair = card["chairs"][0]
        self.assertEqual(chair["refused"], "occupied")
        self.assertEqual(chair["ask"], "relaunch --take-over")
        self.assertEqual(chair["incarnation"], 1)
        self.assertEqual(chair["pid"], 999)
        self.assertFalse(card["launched"], card)
        self.assertEqual(self.runner.call_count, 0, "nothing may spawn beside a live body")
        self.assertEqual(_rows(self.root, "evicted"), [])
        self.assertFalse(close_request_path(self.root, "chair").is_file(),
                         "a refusal must not ask the host to close anything")

    def test_take_over_writes_evicted_then_launches_next_incarnation(self):
        closed = close_request_path(self.root, "chair")

        def fake_sleep(_seconds):
            # The host acknowledged the close: the body is recorded as gone.
            if closed.is_file():
                update_seat(self.root, "chair", process_state="exited")

        card = self._relaunch(take_over=True, sleep=fake_sleep)
        evicted = _rows(self.root, "evicted")
        self.assertEqual(len(evicted), 1, evicted)
        self.assertEqual(evicted[0]["chair"], "chair")
        self.assertEqual(evicted[0]["incarnation"], 1)
        self.assertEqual(evicted[0]["pid"], 999)
        self.assertTrue(evicted[0]["evidence"], evicted[0])
        chair = card["chairs"][0]
        self.assertEqual(chair["evicted"], True)
        self.assertNotIn("refused", chair)
        self.assertEqual(self.runner.call_count, 1, "the chair relaunches once the body is gone")
        self.assertTrue(card["launched"], card)
        # The next body is incarnation 2 and the host is the only writer of
        # that number, so the launched argv must name the chair to be hosted.
        self.assertIn("chair", self.runner.call_args[0][0])

    def test_take_over_that_times_out_refuses_and_launches_nothing(self):
        """_evict can return {evicted: True, exited: False}. The
        chair was still marked launchable, so the very failure this whole design exists to
        prevent happened here: a second body launched beside a live one. An eviction that
        did not finish is a refusal, and the record must say so."""
        def never_exits(_seconds):
            pass  # the host never acknowledges; the body stays alive

        card = self._relaunch(take_over=True, sleep=never_exits)
        chair = card["chairs"][0]
        self.assertEqual(chair.get("evicted"), True, "the eviction was attempted and is on the record")
        self.assertEqual(chair.get("exited"), False)
        self.assertEqual(chair.get("refused"), "evict_timeout", chair)
        self.assertIn("still alive", str(chair.get("reason", "")))
        self.assertEqual(self.runner.call_count, 0, "NO second body while the first is alive")
        self.assertFalse(card["launched"], card)
        # The evicted row is written (the attempt is real); no seated/launch rows follow it.
        self.assertEqual(len(_rows(self.root, "evicted")), 1)

    def test_automatic_take_over_only_from_unreachable_row(self):
        first = self._relaunch()
        self.assertEqual(first["chairs"][0]["refused"], "occupied")
        self.assertEqual(self.runner.call_count, 0)

        hook(self.root, "unreachable", "chair has not pulsed", instance_id="chair", author=None,
             extra={"chair": "chair", "incarnation": 1, "since": "2026-09-17T10:30:00.000000Z",
                    "evidence": ["pulse-stale"]})

        closed = close_request_path(self.root, "chair")

        def fake_sleep(_seconds):
            if closed.is_file():
                update_seat(self.root, "chair", process_state="exited")

        second = self._relaunch(sleep=fake_sleep)
        self.assertEqual(second["chairs"][0]["evicted"], True)
        self.assertNotIn("refused", second["chairs"][0])
        self.assertEqual(len(_rows(self.root, "evicted")), 1)
        self.assertEqual(self.runner.call_count, 1)

    def test_relaunch_records_why_the_body_was_gone_before_spawning(self):
        card = self._relaunch(alive=lambda _pid: False)
        rows = _rows(self.root, "unreachable")
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["chair"], "chair")
        self.assertEqual(rows[0]["incarnation"], 1)
        self.assertIn("pid-dead", rows[0]["evidence"])
        self.assertTrue(rows[0]["since"], rows[0])
        self.assertEqual(_rows(self.root, "evicted"), [], "a body that is gone needs no eviction")
        self.assertEqual(self.runner.call_count, 1)
        self.assertTrue(card["launched"], card)

    def test_chair_that_was_never_hosted_launches_with_no_host_evidence(self):
        seat(self.root, "grok", "fresh", worktree=str(Path(tempfile.mkdtemp())))
        card = self._relaunch(seats=["fresh"], alive=lambda _pid: False, allow_unverified_launch=True)
        rows = [r for r in _rows(self.root, "unreachable") if r.get("chair") == "fresh"]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("no-host", rows[0]["evidence"])
        self.assertIsNone(rows[0]["incarnation"])
        self.assertTrue(card["launched"], card)


class RelaunchResumes(unittest.TestCase):
    """A relaunch that can resume says so, and says which life it booted.

    `resume_argv` has long emitted the vendor resume shape, but nothing
    recorded whether a given relaunch USED it. A chair that came back with a
    fresh conversation and one that continued its own were the same row on the
    feed, so 'it lost its context' was unanswerable from the record. The
    incarnation rides with it because the boot prompt's ack is the only proof
    the new body ever sat down, and an ack that does not name the life it
    belongs to lets a previous body's ack read as this one's.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "resume-t")
        seat(self.root, "codex", "chair", worktree=str(Path(tempfile.mkdtemp())))
        # A dead body of incarnation 1: nothing to evict, so the relaunch runs.
        update_seat(self.root, "chair", incarnation=1, harness_pid=999,
                    process_state="exited",
                    resume="11111111-2222-3333-4444-555555555555", resume_for="codex")
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def _relaunch(self, **kw):
        alive = kw.pop("alive", lambda _pid: False)
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            return relaunch(self.root, runner=self.runner, alive=alive, **kw)

    def test_relaunch_with_resume_emits_vendor_resume_argv(self):
        card = self._relaunch()
        self.assertTrue(card["chairs"][0]["resumed"],
                        "a chair holding a vendor id resumes; the card must say so")
        from convoy.targeted_launch import pane_child_argv
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\codex.exe"):
            argv = pane_child_argv(_seat_row(self.root, "chair"), root=self.root)
        self.assertIn("resume", argv, argv)
        self.assertEqual(argv[argv.index("resume") + 1], "11111111-2222-3333-4444-555555555555")
        self.assertNotIn("--session-id", argv, "a resume is not a mint")

    def test_relaunch_row_records_resumed(self):
        seat(self.root, "codex", "fresh", worktree=str(Path(tempfile.mkdtemp())))
        card = self._relaunch()
        bodies = {b["chair"]: b for b in _rows(self.root, "relaunch")[-1]["bodies"]}
        self.assertEqual(bodies["chair"]["resumed"], True)
        self.assertEqual(bodies["chair"]["incarnation"], 2,
                         "the life about to boot, not the one that died")
        self.assertEqual(bodies["fresh"]["resumed"], False,
                         "a chair with no vendor id starts a new conversation")
        self.assertEqual(bodies["fresh"]["incarnation"], 1)
        self.assertEqual({c["session_id"]: c["resumed"] for c in card["chairs"]},
                         {"chair": True, "fresh": False})

    def test_boot_prompt_cites_the_life_the_ack_must_name(self):
        self._relaunch()
        prompt = str(_seat_row(self.root, "chair").get("boot_prompt") or "")
        self.assertIn("--incarnation 2", prompt, prompt)
        self.assertIn("seated --seat chair", prompt)


if __name__ == "__main__":
    unittest.main()
