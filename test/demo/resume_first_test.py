"""A neuron is resumable from its first launch, by construction.

A first launch used to pass no session id, the vendor invented one, and
Convoy learned it only if something later captured it. A pane that died
before that capture was unresumable - which is how a relaunched seat came up
with `resume: null` and fell through to the path rung.

The fix is to stop waiting: for a harness whose --help documents a flag that
DICTATES the session id of a NEW conversation, Convoy mints a uuid4, writes
it on the neuron row BEFORE the body starts, and passes it on argv. Two
harnesses evidence such a flag in their --help, so the flag lives in the harness
contract with its evidence string, not in an `if` on a harness name:

  claude 2.1.278   --help line 217  `--session-id <uuid>`
  grok   1.0.34    --help line 121  `-s, --session-id <SESSION_ID>`

codex 0.155.1 and agy 1.2.7 document no such flag and keep the capture path.
cursor-agent 2026.09.18-9a7762b has no launch flag either; its `--resume
[chatId]` (help line 32) resumes an EXISTING chat, and its `create-chat`
subcommand (line 87) is a different mechanism, left for later.
"""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import resume_argv
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.resume_first import ensure_session_id


def _row(root, session_id):
    for r in list_seats(root):
        if r.get("session_id") == session_id:
            return r
    raise AssertionError("no seat row for " + session_id)


class AFirstLaunchIsAlreadyResumable(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")

    def test_a_first_claude_launch_carries_session_id_equal_to_the_rows_resume(self):
        seat(self.root, "claude", "mint-t1", worktree="C:\\w\\mint")
        row = ensure_session_id(self.root, _row(self.root, "mint-t1"))
        minted = row["resume"]
        self.assertEqual(uuid.UUID(minted).version, 4)
        self.assertEqual(row["resume_for"], "claude")
        argv = resume_argv(row)
        self.assertIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], minted)
        self.assertNotIn("--resume", argv)

    def test_the_id_is_on_the_row_before_the_body_starts(self):
        seat(self.root, "claude", "mint-t1", worktree="C:\\w\\mint")
        row = ensure_session_id(self.root, _row(self.root, "mint-t1"))
        self.assertEqual(_row(self.root, "mint-t1")["resume"], row["resume"])
        self.assertEqual(_row(self.root, "mint-t1")["resume_for"], "claude")

    def test_grok_gets_one_too_because_its_help_documents_the_flag(self):
        # The SPELLING is the contract's, not this test's: grok --help offers
        # `-s, --session-id`, and `-s` is what Convoy has always put on grok
        # argv (seat_lifecycle_test pins it). Re-spelling it is out of scope.
        from convoy.harness_contract import session_id_flag
        seat(self.root, "grok", "mint-g1", worktree="C:\\w\\g")
        row = ensure_session_id(self.root, _row(self.root, "mint-g1"))
        self.assertEqual(uuid.UUID(row["resume"]).version, 4)
        argv = resume_argv(row)
        self.assertEqual(argv[argv.index(session_id_flag("grok")) + 1], row["resume"])

    def test_a_harness_with_no_such_flag_is_left_on_the_capture_path(self):
        for harness, sid in (("codex", "mint-x1"), ("agy", "mint-a1"), ("cursor-agent", "mint-u1")):
            # cursor-agent's argv reads its model catalog: never a live `cursor-agent models`
            with self.subTest(harness=harness), mock.patch("convoy.cursor_models.read_catalog", return_value=None):
                seat(self.root, harness, sid, worktree="C:\\w\\" + sid)
                row = ensure_session_id(self.root, _row(self.root, sid))
                self.assertIsNone(row.get("resume"))
                self.assertNotIn("--session-id", resume_argv(row))

    def test_a_harness_with_no_such_flag_records_why_not_the_cards_wording(self):
        # It is tempting to say cursor-agent has "no flag in --help". Its --help does
        # carry --resume [chatId]; what it lacks is a flag that dictates the
        # id of a NEW session. The row records the true reason.
        seat(self.root, "cursor-agent", "mint-u2", worktree="C:\\w\\u2")
        row = ensure_session_id(self.root, _row(self.root, "mint-u2"))
        self.assertIsNone(row["resume"])
        self.assertIn("no flag to set a session id at launch", row["resume_reason"])

    def test_a_captured_id_is_resumed_never_redeclared(self):
        """The discriminator is provenance, not novelty of the row.

        A first draft of this used "no incarnations yet" to mean "this
        conversation does not exist", and phase7_bringup caught it: every
        row written before minting carries an id CAPTURED from a vendor after the fact, and
        that conversation does exist. Declaring it with --session-id would be
        refused ("must not already exist"). Only an id Convoy minted itself,
        before the body started, is new.
        """
        seat(self.root, "claude", "mint-cap", worktree="C:\\w\\cap", resume="captured-from-vendor")
        row = _row(self.root, "mint-cap")
        self.assertFalse(row.get("resume_minted"))
        argv = resume_argv(row)
        self.assertNotIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "captured-from-vendor")

    def test_a_minted_id_is_marked_as_minted_on_the_row(self):
        seat(self.root, "claude", "mint-t1", worktree="C:\\w\\mint")
        ensure_session_id(self.root, _row(self.root, "mint-t1"))
        self.assertIs(_row(self.root, "mint-t1")["resume_minted"], True)

    def test_an_existing_id_is_never_reminted(self):
        seat(self.root, "claude", "mint-t1", worktree="C:\\w\\mint", resume="already-here")
        row = ensure_session_id(self.root, _row(self.root, "mint-t1"))
        self.assertEqual(row["resume"], "already-here")

    def test_a_second_launch_resumes_the_id_it_minted_rather_than_reasserting_it(self):
        # `--session-id` is for a NEW conversation: claude refuses an id that
        # already exists, so the flag may be passed exactly once. Once the
        # pane host has recorded an incarnation, the body exists.
        seat(self.root, "claude", "mint-t1", worktree="C:\\w\\mint")
        row = ensure_session_id(self.root, _row(self.root, "mint-t1"))
        booted = {**row, "incarnations": [{"incarnation": 1, "child_pid": 4242}]}
        argv = resume_argv(booted)
        self.assertNotIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], row["resume"])


class OneMintingPathNotTwo(unittest.TestCase):
    """Minting at spawn, inside `pane_child_argv`, once came from a hardcoded
    MINT_FLAG dict that listed claude and grok. Two places that mint are two
    answers that can disagree; the binding (`resume_for`), the provenance
    (`resume_minted`) and the harness list in the contract make them one.
    This pins that there is one path, not two.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")

    def test_the_spawn_path_records_the_binding_and_the_provenance(self):
        from convoy.targeted_launch import pane_child_argv
        seat(self.root, "claude", "mint-spawn", worktree=str(self.root))
        argv = pane_child_argv(_row(self.root, "mint-spawn"), root=self.root)
        row = _row(self.root, "mint-spawn")
        self.assertEqual(uuid.UUID(row["resume"]).version, 4)
        self.assertEqual(row["resume_for"], "claude")
        self.assertIs(row["resume_minted"], True)
        self.assertEqual(argv[argv.index("--session-id") + 1], row["resume"])

    def test_the_minted_flag_stays_ahead_of_the_positional_boot_prompt(self):
        from convoy.targeted_launch import pane_child_argv
        seat(self.root, "claude", "mint-bp", worktree=str(self.root))
        from convoy.convoy import update_seat
        update_seat(self.root, "mint-bp", boot_prompt="you are seated")
        argv = pane_child_argv(_row(self.root, "mint-bp"), root=self.root)
        self.assertLess(argv.index("--session-id"), argv.index("you are seated"))

    def test_the_flag_is_never_added_twice_when_both_paths_run(self):
        from convoy.targeted_launch import pane_child_argv
        seat(self.root, "claude", "mint-twice", worktree=str(self.root))
        ensure_session_id(self.root, _row(self.root, "mint-twice"))
        argv = pane_child_argv(_row(self.root, "mint-twice"), root=self.root)
        self.assertEqual(argv.count("--session-id"), 1)
        self.assertEqual(argv[argv.index("--session-id") + 1], _row(self.root, "mint-twice")["resume"])

    def test_which_harnesses_mint_is_the_contracts_answer_everywhere(self):
        from convoy.harness_contract import session_id_flag
        from convoy.targeted_launch import pane_child_argv
        for harness in ("claude", "grok", "codex", "agy", "cursor-agent"):
            # cursor-agent's argv reads its model catalog: never a live `cursor-agent models`
            with self.subTest(harness=harness), mock.patch("convoy.cursor_models.read_catalog", return_value=None):
                sid = "mint-c-" + harness
                seat(self.root, harness, sid, worktree=str(self.root / harness))
                argv = pane_child_argv(_row(self.root, sid), root=self.root)
                flag = session_id_flag(harness)
                minted = _row(self.root, sid).get("resume")
                if flag:
                    self.assertEqual(argv[argv.index(flag) + 1], minted)
                else:
                    self.assertIsNone(minted)


if __name__ == "__main__":
    unittest.main()
