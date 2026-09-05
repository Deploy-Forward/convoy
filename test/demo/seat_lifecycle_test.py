import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import resume_argv, resume_target
from convoy.cli import main
from convoy.convoy import ensure_id, list_seats, seat, update_seat
from convoy.layer import feed_since
from convoy.lifecycle import join, seated_ack, swap
from convoy.registry import live_on_branch, register


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class ResumeTokenHarnessBinding(unittest.TestCase):
    """opus-2 RED at baa6a55: nothing bound a resume token to the harness that
    minted it — a claude UUID came out formatted for `codex resume`. The
    guarantee lives in construction now: rows carry `resume_for`, and
    resume_target returns a token only on harness match, BOTH keys checked."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_seat_stamps_resume_for(self):
        ensure_id(self.root)
        row = seat(self.root, "claude", "s1", resume="claude-uuid-1")
        self.assertEqual(row["resume_for"], "claude")

    def test_resume_target_refuses_cross_harness_token(self):
        self.assertIsNone(resume_target({"to": "codex", "resume": "claude-uuid", "resume_for": "claude"}))
        self.assertIsNone(resume_target({"to": "codex", "vendor_session_id": "claude-uuid", "resume_for": "claude"}))

    def test_resume_target_allows_matching_and_legacy_rows(self):
        self.assertEqual(resume_target({"to": "codex", "resume": "codex-uuid", "resume_for": "codex"}), "codex-uuid")
        # legacy rows predate resume_for: whole-row writes mean the token was
        # minted under the row's own `to` — allowed.
        self.assertEqual(resume_target({"to": "claude", "resume": "claude-uuid"}), "claude-uuid")

    def test_resume_argv_emits_no_token_on_mismatch(self):
        argv = resume_argv({"to": "codex", "resume": "claude-uuid", "resume_for": "claude", "session_id": "s1"})
        self.assertNotIn("claude-uuid", argv)
        self.assertNotIn("resume", argv)


class UpdateSeatPreservesFields(unittest.TestCase):
    """opus-1 AMBER-4: bare seat() writes whole rows last-wins and silently
    blanks title/agent/effort. Swap routes through a field-preserving updater;
    a harness change nulls resume AND vendor_session_id (RED-2: no swap ever
    carries a vendor session)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        seat(self.root, "claude", "chair-1", worktree=r"C:\wt", model="claude-opus-5",
             resume="claude-uuid", title="opus-1", effort="high")

    def _latest(self):
        return [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]

    def test_update_preserves_unpassed_fields(self):
        update_seat(self.root, "chair-1", model="claude-fable-5")
        row = self._latest()
        self.assertEqual(row["model"], "claude-fable-5")
        self.assertEqual(row["title"], "opus-1")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["worktree"], r"C:\wt")
        self.assertEqual(row["resume"], "claude-uuid")

    def test_harness_change_nulls_both_token_fields(self):
        update_seat(self.root, "chair-1", to="codex", model="gpt-5.6-sol")
        row = self._latest()
        self.assertEqual(row["to"], "codex")
        self.assertIsNone(row["resume"])
        self.assertIsNone(row.get("vendor_session_id"))
        self.assertEqual(row["title"], "opus-1")

    def test_unknown_session_id_refuses(self):
        with self.assertRaises(ValueError):
            update_seat(self.root, "no-such-chair", model="x")

    def test_launch_claim_can_be_released_for_relaunch(self):
        """2026-09-03: after a consented close, launch refused the relaunch as
        'already claimed' because the claim file outlived the pane."""
        from convoy.targeted_launch import _claim, release_launch_claim
        path = _claim(self.root, "chair-1")
        self.assertTrue(path.is_file())
        with self.assertRaises(ValueError):
            _claim(self.root, "chair-1")
        self.assertTrue(release_launch_claim(self.root, "chair-1"))
        self.assertFalse(path.is_file())
        self.assertFalse(release_launch_claim(self.root, "chair-1"))
        self.assertTrue(_claim(self.root, "chair-1").is_file())

    def test_same_harness_swap_nulls_both_token_fields(self):
        """2026-09-03: a grok->grok swap kept vendor_session_id, so `launch`
        saw a resumable chair and refused it as not fresh."""
        update_seat(self.root, "chair-1", vendor_session_id="claude-vendor-uuid")
        hp = self.root / "h.md"
        hp.write_text("h", encoding="utf-8")
        swap(self.root, "chair-1", "claude", str(hp), author="chair-1")
        row = self._latest()
        self.assertEqual(row["to"], "claude")
        self.assertIsNone(row["resume"])
        self.assertIsNone(row.get("vendor_session_id"))
        self.assertIsNone(resume_target(row))
        self.assertTrue(row["boot_prompt"])


class SwapVerb(unittest.TestCase):
    """Marco's ratified contract: swap keeps the chair (session_id), replaces
    the occupant, never reuses a resume token, and the replacement proves life
    by echoing the swap token in a `seated` row before any close."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        seat(self.root, "claude", "chair-1", worktree=str(self.root), model="claude-opus-5",
             resume="claude-uuid", title="opus-1", effort="high")
        self.handoff = self.root / ".convoy" / "handoff" / "chair-1-20260905T000000Z.md"
        self.handoff.parent.mkdir(parents=True, exist_ok=True)
        self.handoff.write_text("state of the work\n", encoding="utf-8")

    def test_swap_stamps_row_and_reseats_same_chair(self):
        card = swap(self.root, "chair-1", to="codex", model="gpt-5.6-sol",
                    handoff=str(self.handoff), author="chair-1")
        self.assertTrue(card["ok"])
        row = feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(row["kind"], "swap")
        self.assertEqual(row["from"], "chair-1")
        self.assertEqual(row["to"], "chair-1")
        self.assertEqual(row["swap_to"], "codex")
        self.assertEqual(row["memory"], "convoy-state")
        self.assertTrue(row["token"])
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]
        self.assertEqual(seat_row["to"], "codex")
        self.assertIsNone(seat_row["resume"])
        self.assertEqual(seat_row["title"], "opus-1")
        # boot prompt carries the join instruction: handoff path + token
        self.assertIn(card["token"], seat_row["boot_prompt"])
        self.assertIn(str(self.handoff), seat_row["boot_prompt"])

    def test_swap_same_harness_also_drops_resume(self):
        swap(self.root, "chair-1", to="claude", model="claude-fable-5",
             handoff=str(self.handoff), author="chair-1")
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]
        self.assertIsNone(seat_row["resume"])

    def test_swap_refuses_missing_handoff_and_conductor_author(self):
        with self.assertRaises(ValueError):
            swap(self.root, "chair-1", to="codex", handoff=str(self.root / "nope.md"), author="chair-1")
        with self.assertRaises(ValueError):
            swap(self.root, "chair-1", to="codex", handoff=str(self.handoff), author="grok-bot")

    def test_boot_prompt_rides_resume_argv_positionally(self):
        card = swap(self.root, "chair-1", to="codex", handoff=str(self.handoff), author="chair-1")
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]
        argv = resume_argv(seat_row)
        self.assertEqual(argv[-1], seat_row["boot_prompt"])
        self.assertIn(card["token"], argv[-1])
        agy_argv = resume_argv({"to": "agy", "session_id": "x", "boot_prompt": "hello seat"})
        self.assertEqual(agy_argv[-2:], ["--prompt", "hello seat"])

    def test_swap_accepts_labelled_legacy_ola_handoff(self):
        legacy = self.root / ".ola" / "handoff-swap.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("legacy state\n", encoding="utf-8")
        card = swap(self.root, "chair-1", to="codex", handoff=str(legacy), author="chair-1")
        self.assertTrue(card["ok"])
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]
        self.assertIn(str(legacy), seat_row["boot_prompt"])

    def test_seated_ack_closes_the_loop(self):
        card = swap(self.root, "chair-1", to="codex", handoff=str(self.handoff), author="chair-1")
        ack = seated_ack(self.root, "chair-1", token=card["token"])
        self.assertTrue(ack["ok"])
        row = feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(row["kind"], "seated")
        self.assertEqual(row["from"], "chair-1")
        self.assertEqual(row["token"], card["token"])
        # ack also clears the one-shot boot prompt
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "chair-1"][0]
        self.assertIsNone(seat_row.get("boot_prompt"))


class JoinVerb(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)

    def test_join_seats_and_stamps(self):
        card = join(self.root, "codex", session_id="sol-1", worktree=str(self.root),
                    model="gpt-5.6-sol", title="sol-1")
        self.assertTrue(card["ok"])
        row = feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(row["kind"], "join")
        self.assertEqual(row["to"], "sol-1")
        seat_row = [s for s in list_seats(self.root) if s["session_id"] == "sol-1"][0]
        self.assertEqual(seat_row["to"], "codex")
        self.assertIn(card["token"], seat_row["boot_prompt"])

    def test_cli_join_swap_seated(self):
        rc, _ = _run_cli(self.root, "join", "--to", "claude", "--session-id", "c1",
                         "--worktree", str(self.root), "--title", "c1")
        self.assertEqual(rc, 0)
        handoff = self.root / ".convoy" / "handoff" / "c1-20260905T000000Z.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("x", encoding="utf-8")
        rc, card = _run_cli(self.root, "swap", "--seat", "c1", "--to", "codex",
                            "--handoff", str(handoff), "--as", "c1")
        self.assertEqual(rc, 0)
        rc, _ = _run_cli(self.root, "seated", "--seat", "c1", "--token", card["token"])
        self.assertEqual(rc, 0)


class LiveOnBranchDedupe(unittest.TestCase):
    """opus-1 AMBER-2: the guard counted rows, not live agents, degrading
    permanently after any swap. One chair = one agent, however many occupants
    it has had."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_dedupe_by_session_id(self):
        register(self.root, "chair-1", "claude", extra={"git_branch": "feat-x"})
        register(self.root, "chair-1", "codex", extra={"git_branch": "feat-x"})
        rows = live_on_branch(self.root, "feat-x")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["to"], "codex")


if __name__ == "__main__":
    unittest.main()
