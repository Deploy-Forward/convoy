"""Identity that cannot lie.

The defect: `panes._mentions_path` matched a seat by path
SUBSTRING anywhere in the command line. A crew boot prompt carries the thread
root inside one quoted argument, so a crew pane on the thread could answer
`whoami` as the ROOT's chair - and `--as-me` authors from that answer. An
identity surface that guesses is worse than one that refuses.

The evidence this file pins:
  - a native id from the caller's harness environment or exact resume argv;
  - the pane-host record for a pid in that lineage;
  - cwd, or an ARGUMENT that IS the worktree path.
Positive sources naming different chairs conflict. An environment id not
recorded on this thread is not a positive chair claim and may fall through.

Paths here are written with doubled backslashes on purpose: these are Windows
command lines, and a single backslash before b or t is an escape, not a
separator. An earlier draft of this file lost that and tested "C:\\w\\crew\\x08in".
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.pane_host import host_state_path
from convoy.panes import identify

ROOT_WT = "C:\\w\\thread-root"
CREW_WT = "C:\\w\\crew"

# What a relaunched crew pane really carries: one quoted argument holding a
# boot prompt that names the THREAD ROOT several times.
BOOT_PROMPT = (
    "You are the occupant of Convoy seat 'crew-t1'. "
    "Run convoy --root " + ROOT_WT + " feed --since 2000-01-01T00:00:00Z then "
    "convoy --root " + ROOT_WT + " inbox --drain --seat crew-t1."
)
CREW_CMDLINE = 'claude.EXE --model claude-opus-5 "' + BOOT_PROMPT + '"'


def _write_host_record(root, session_id, host_pid, child_pid, worktree,
                       status="running", to="claude"):
    path = host_state_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "session_id": session_id, "status": status, "host_pid": host_pid,
        "child_pid": child_pid, "child_exe": "C:\\bin\\claude.EXE",
        "worktree": worktree, "to": to,
    }), encoding="utf-8")


class IdentityDoesNotGuessFromPromptText(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "lead-t1", worktree=ROOT_WT)
        seat(self.root, "claude", "crew-t1", worktree=CREW_WT)
        self.procs = [
            {"pid": 20, "ppid": 1, "cmdline": CREW_CMDLINE, "cwd": None},
            {"pid": 21, "ppid": 20, "cmdline": "bash -c convoy whoami", "cwd": None},
        ]

    def test_the_root_path_inside_a_prompt_argument_does_not_name_the_root_chair(self):
        me = identify(self.root, pid=21, procs=self.procs, cwd="C:\\elsewhere")
        self.assertNotEqual(me["chair"], "lead-t1")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["on_thread"])

    def test_a_pane_host_record_names_the_chair_for_a_pid_in_the_lineage(self):
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20, worktree=CREW_WT)
        me = identify(self.root, pid=21, procs=self.procs, cwd="C:\\elsewhere")
        self.assertEqual((me["chair"], me["via"], me["harness_pid"]), ("crew-t1", "pane-host", 20))
        self.assertTrue(me["on_thread"])

    def test_the_host_pid_itself_is_in_the_lineage_and_names_the_chair(self):
        # The pane host is the parent of the harness; a call made from the
        # host's own tree is still that chair.
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20, worktree=CREW_WT)
        procs = self.procs + [{"pid": 19, "ppid": 1, "cmdline": "convoy-pane-host --seat crew-t1", "cwd": None}]
        me = identify(self.root, pid=19, procs=procs, cwd="C:\\elsewhere")
        self.assertEqual((me["chair"], me["via"]), ("crew-t1", "pane-host"))

    def test_a_record_for_an_exited_pane_does_not_claim_a_recycled_pid(self):
        # The OS reuses pids. A record whose child has exited is history, not
        # a claim, so it may not name a chair for whatever holds that pid now.
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20,
                           worktree=CREW_WT, status="child-exited")
        me = identify(self.root, pid=21, procs=self.procs, cwd="C:\\elsewhere")
        self.assertNotEqual(me["chair"], "crew-t1")
        self.assertIsNone(me["chair"])

    def test_pid_record_and_path_disagreeing_answers_conflict_naming_both(self):
        # The pane-host record says crew-t1; an argument really is the root
        # worktree, so the path rung says lead-t1. Two records disagree.
        procs = [
            {"pid": 20, "ppid": 1, "cmdline": "claude.EXE --cwd " + ROOT_WT, "cwd": None},
            {"pid": 21, "ppid": 20, "cmdline": "bash -c convoy whoami", "cwd": None},
        ]
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20, worktree=CREW_WT)
        me = identify(self.root, pid=21, procs=procs, cwd=None)
        self.assertEqual(me["via"], "conflict")
        self.assertIsNone(me["chair"])          # never the path's chair
        self.assertFalse(me["ok"])
        self.assertEqual(set(me["chairs"]), {"crew-t1", "lead-t1"})
        self.assertIn("crew-t1", me["ask"])
        self.assertIn("lead-t1", me["ask"])

    def test_as_me_refuses_to_author_when_the_prompt_names_another_chair(self):
        """The harm the whole slice exists to stop: a crew pane whose boot
        prompt carries the thread root must not sign a row as the root's
        chair. The feed is the record; a wrong author cannot be withdrawn."""
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        from convoy.layer import feed_since
        import convoy.panes as panes_module

        panes_module._TEST_PROCS = self.procs
        panes_module._TEST_PID = 21
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["--root", str(self.root), "hook", "note", "hello", "--as-me", "--to", "crew-t1"])
        finally:
            panes_module._TEST_PROCS = None
            panes_module._TEST_PID = None
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertIn("refuse --as-me", payload["error"])
        self.assertEqual([r for r in feed_since(self.root, "1970-01-01T00:00:00Z") if r["kind"] == "note"], [])

    def test_a_token_conflicting_with_pane_host_refuses_identity(self):
        seat(self.root, "claude", "tok-t1", worktree="C:\\w\\tok", resume="tok-abc")
        procs = [
            {"pid": 20, "ppid": 1, "cmdline": "claude.EXE --resume tok-abc", "cwd": None},
            {"pid": 21, "ppid": 20, "cmdline": "bash -c convoy whoami", "cwd": None},
        ]
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20, worktree=CREW_WT)
        me = identify(self.root, pid=21, procs=procs, cwd=None)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")
        self.assertEqual(set(me["chairs"]), {"tok-t1", "crew-t1"})

    def test_an_argument_that_is_the_worktree_still_names_its_chair(self):
        # The fix must not blind the honest signal: grok carries its worktree
        # in --agent, and that argument IS a path under the worktree.
        procs = [
            {"pid": 22, "ppid": 1, "cmdline": "claude.EXE --add-dir " + CREW_WT + "\\src", "cwd": None},
            {"pid": 23, "ppid": 22, "cmdline": "bash -c convoy whoami", "cwd": None},
        ]
        me = identify(self.root, pid=23, procs=procs, cwd=None)
        self.assertEqual((me["chair"], me["via"]), ("crew-t1", "worktree"))


class MentionsPathMatchesWholeArgumentsOnly(unittest.TestCase):
    def test_a_path_inside_free_text_is_not_a_mention(self):
        from convoy.panes import _mentions_path
        self.assertFalse(_mentions_path(CREW_CMDLINE, ROOT_WT))

    def test_an_argument_equal_to_the_worktree_is_a_mention(self):
        from convoy.panes import _mentions_path
        self.assertTrue(_mentions_path("claude.EXE --cwd " + CREW_WT, CREW_WT))

    def test_an_argument_under_the_worktree_is_a_mention(self):
        from convoy.panes import _mentions_path
        cmd = "grok.EXE --trust --agent " + CREW_WT + "\\.grok\\agents\\convoy-neuron.md"
        self.assertTrue(_mentions_path(cmd, CREW_WT))

    def test_a_quoted_argument_that_is_the_worktree_is_a_mention(self):
        from convoy.panes import _mentions_path
        self.assertTrue(_mentions_path('claude.EXE --cwd "' + CREW_WT + '"', CREW_WT))

    def test_the_executable_itself_is_not_a_claim(self):
        from convoy.panes import _mentions_path
        self.assertFalse(_mentions_path(CREW_WT + "\\bin\\claude.EXE --help", CREW_WT))

    def test_a_sibling_worktree_with_the_same_prefix_is_not_a_mention(self):
        from convoy.panes import _mentions_path
        self.assertFalse(_mentions_path("claude.EXE --cwd " + CREW_WT + "-2", CREW_WT))


class LinkedSessionIdentityContract(unittest.TestCase):
    """Red cases for process ownership, using only synthetic ids and processes."""

    NATIVE_ID = "synthetic-native-session-a"
    OTHER_ID = "synthetic-native-session-b"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "link-identity")
        self.env = {
            "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": "",
        }

    def _identify(self, harness_cmd, caller_cmd="convoy whoami"):
        procs = [
            {"pid": 80, "ppid": 1, "cmdline": harness_cmd, "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": caller_cmd, "cwd": None},
        ]
        return identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=self.env)

    def test_claude_in_process_session_id_matches_its_recorded_chair(self):
        seat(self.root, "claude", "claude-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("claude.EXE --model synthetic")
        self.assertEqual(me["chair"], "claude-outside")
        self.assertTrue(me["ok"])

    def test_environment_id_without_a_harness_ancestor_is_not_identity(self):
        seat(self.root, "claude", "claude-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("powershell.EXE")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertIsNone(me["via"])

    def test_environment_id_for_another_session_is_not_identity(self):
        seat(self.root, "claude", "claude-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.OTHER_ID}):
            me = self._identify("claude.EXE --model synthetic")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertIsNone(me["via"])

    def test_unmatched_environment_id_falls_back_to_a_matching_worktree(self):
        seat(self.root, "codex", "codex-outside", worktree="C:\\outside", resume=self.NATIVE_ID)
        other_id = self.OTHER_ID
        with patch.dict(self.env, {"CODEX_THREAD_ID": other_id, "CODEX_SESSION_ID": other_id}):
            me = self._identify("codex.EXE")
        self.assertEqual((me["chair"], me["via"]), ("codex-outside", "cwd"))
        self.assertTrue(me["ok"])

    def test_unrecorded_codex_environment_id_falls_back_to_pane_host(self):
        seat(self.root, "codex", "codex-fresh", worktree="C:\\outside")
        _write_host_record(self.root, "codex-fresh", host_pid=79, child_pid=80,
                           worktree="C:\\outside", to="codex")
        seat_bytes = (self.root / ".convoy" / "seats.jsonl").read_bytes()
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.NATIVE_ID,
        }):
            me = self._identify("codex.EXE")
        self.assertEqual((me["chair"], me["via"]), ("codex-fresh", "pane-host"))
        self.assertEqual(me["native_session"], {
            "id": self.NATIVE_ID, "harness": "codex", "via": "environment", "recorded": False,
        })
        self.assertEqual((self.root / ".convoy" / "seats.jsonl").read_bytes(), seat_bytes)

    def test_changed_claude_environment_id_does_not_veto_agreeing_host_and_argv(self):
        seat(self.root, "claude", "claude-moved", worktree="C:\\outside", resume=self.NATIVE_ID)
        _write_host_record(self.root, "claude-moved", host_pid=79, child_pid=80,
                           worktree="C:\\outside", to="claude")
        changed_id = self.OTHER_ID
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": changed_id}):
            me = self._identify("claude.EXE --resume " + self.NATIVE_ID)
        self.assertEqual((me["chair"], me["via"]), ("claude-moved", "token"))
        self.assertEqual(me["native_session"], {
            "id": changed_id, "harness": "claude", "via": "environment", "recorded": False,
        })

    def test_nested_claude_child_cannot_claim_parents_inherited_environment_id(self):
        seat(self.root, "claude", "claude-parent", resume=self.NATIVE_ID,
             worktree="C:\\parent")
        seat(self.root, "claude", "claude-child", worktree="C:\\child")
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "claude.EXE --resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "claude.EXE --model synthetic", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID}):
            me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=self.env)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")
        self.assertIn("nested", me["ask"])

    def test_nested_claude_child_host_cannot_be_overridden_by_parent_environment(self):
        seat(self.root, "claude", "claude-parent", resume=self.NATIVE_ID)
        seat(self.root, "claude", "claude-child", worktree="C:\\child")
        _write_host_record(self.root, "claude-child", host_pid=79, child_pid=80,
                           worktree="C:\\child", to="claude")
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "claude.EXE --resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "claude.EXE --model synthetic", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID}):
            me = identify(self.root, pid=81, procs=procs, cwd="C:\\child", env=self.env)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")

    def test_nested_child_can_use_its_own_host_after_environment_is_scrubbed(self):
        seat(self.root, "claude", "claude-parent", resume=self.NATIVE_ID)
        seat(self.root, "claude", "claude-child", worktree="C:\\child")
        _write_host_record(self.root, "claude-child", host_pid=79, child_pid=80,
                           worktree="C:\\child", to="claude")
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "claude.EXE --resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "claude.EXE --model synthetic", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\child", env={})
        self.assertEqual((me["chair"], me["via"]), ("claude-child", "pane-host"))

    def test_two_codex_processes_in_one_lineage_do_not_self_conflict(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "codex.EXE", "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "codex.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        env = {"CODEX_THREAD_ID": self.NATIVE_ID, "CODEX_SESSION_ID": self.NATIVE_ID}
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=env)
        self.assertEqual((me["chair"], me["via"]), ("codex-outside", "environment"))

    def test_node_wrapper_and_vendored_codex_resume_are_one_body(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "node.exe C:/npm/codex.js resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "codex.EXE resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        env = {"CODEX_THREAD_ID": self.NATIVE_ID, "CODEX_SESSION_ID": self.NATIVE_ID}
        for hosted in (False, True):
            with self.subTest(hosted=hosted):
                if hosted:
                    _write_host_record(self.root, "codex-outside", host_pid=69, child_pid=70,
                                       worktree="C:\\outside", to="codex")
                me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=env)
                self.assertEqual((me["chair"], me["via"]), ("codex-outside", "environment"))

    def test_app_server_child_of_a_resumed_codex_body_is_not_a_rival(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "node.exe C:/npm/codex.js resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "codex.EXE resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 85, "ppid": 80, "cmdline": "codex.EXE app-server", "cwd": None},
            {"pid": 81, "ppid": 85, "cmdline": "convoy whoami", "cwd": None},
        ]
        env = {"CODEX_THREAD_ID": self.NATIVE_ID, "CODEX_SESSION_ID": self.NATIVE_ID}
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=env)
        self.assertEqual((me["chair"], me["via"]), ("codex-outside", "environment"))

    def test_unrelated_rg_mention_does_not_veto_the_real_harness_body(self):
        seat(self.root, "claude", "claude-outside", resume=self.NATIVE_ID)
        procs = [
            {"pid": 60, "ppid": 1, "cmdline": "rg " + self.NATIVE_ID + " notes", "cwd": None},
            {"pid": 80, "ppid": 1, "cmdline": "claude.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside",
                      env={"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID})
        self.assertEqual((me["chair"], me["via"]), ("claude-outside", "environment"))

    def test_fresh_codex_child_cannot_be_identified_as_claude_parent(self):
        seat(self.root, "claude", "claude-parent", resume=self.NATIVE_ID)
        seat(self.root, "codex", "codex-child")
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "claude.EXE --resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "codex.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        env = {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID,
               "CODEX_THREAD_ID": self.OTHER_ID}
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=env)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")

    def test_nonchair_claude_cannot_claim_a_live_chair_elsewhere_by_environment(self):
        seat(self.root, "claude", "claude-other", resume=self.NATIVE_ID)
        procs = [
            {"pid": 60, "ppid": 1, "cmdline": "claude.EXE --resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 1, "cmdline": "claude.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside",
                      env={"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID})
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")

    def test_nonchair_claude_inside_codex_cannot_claim_codex_parent(self):
        seat(self.root, "codex", "codex-parent", resume=self.NATIVE_ID)
        procs = [
            {"pid": 70, "ppid": 1, "cmdline": "codex.EXE resume " + self.NATIVE_ID, "cwd": None},
            {"pid": 80, "ppid": 70, "cmdline": "claude.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        env = {"CODEX_THREAD_ID": self.NATIVE_ID,
               "CLAUDE_CODE_SESSION_ID": self.OTHER_ID}
        me = identify(self.root, pid=81, procs=procs, cwd="C:\\outside", env=env)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["via"], "conflict")

    def test_default_environment_is_used_with_real_process_enumeration(self):
        from convoy import panes
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        procs = [
            {"pid": 80, "ppid": 1, "cmdline": "codex.EXE", "cwd": None},
            {"pid": 81, "ppid": 80, "cmdline": "convoy whoami", "cwd": None},
        ]
        with patch.dict(os.environ, {"CODEX_THREAD_ID": self.NATIVE_ID,
                                    "CODEX_SESSION_ID": self.NATIVE_ID}), \
             patch.object(panes, "_safe_enumerate", return_value=(procs, None)):
            me = identify(self.root, pid=81, cwd="C:\\outside")
        self.assertEqual((me["chair"], me["via"]), ("codex-outside", "environment"))

    def test_matching_codex_environment_ids_name_the_recorded_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.NATIVE_ID,
        }):
            me = self._identify("codex.EXE")
        self.assertEqual(me["chair"], "codex-outside")
        self.assertTrue(me["ok"])

    def test_codex_thread_id_alone_names_the_recorded_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": "",
        }):
            me = self._identify("codex.EXE")
        self.assertEqual(me["chair"], "codex-outside")
        self.assertTrue(me["ok"])

    def test_codex_session_id_alone_is_not_a_proven_identity_rung(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CODEX_THREAD_ID": "", "CODEX_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("codex.EXE")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertIsNone(me["via"])

    def test_conflicting_codex_environment_ids_refuse_identity(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.OTHER_ID,
        }):
            me = self._identify("codex.EXE")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertEqual(me["via"], "conflict")

    def test_duplicate_native_id_on_two_chairs_refuses_identity(self):
        seat(self.root, "codex", "codex-first", resume=self.NATIVE_ID)
        seat(self.root, "codex", "codex-second", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CODEX_THREAD_ID": "", "CODEX_SESSION_ID": ""}):
            me = self._identify("codex.EXE resume " + self.NATIVE_ID)
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertEqual(me["via"], "conflict")

    def test_environment_and_resume_argument_disagreement_refuses_identity(self):
        other_id = self.OTHER_ID
        seat(self.root, "codex", "codex-environment", resume=self.NATIVE_ID)
        seat(self.root, "codex", "codex-argument", resume=other_id)
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.NATIVE_ID,
        }):
            me = self._identify("codex.EXE resume " + other_id)
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertEqual(me["via"], "conflict")

    def test_environment_and_pane_host_record_disagreement_refuses_identity(self):
        other_id = self.OTHER_ID
        seat(self.root, "codex", "codex-environment", resume=self.NATIVE_ID)
        seat(self.root, "codex", "codex-host", resume=other_id)
        _write_host_record(self.root, "codex-host", host_pid=79, child_pid=80,
                           worktree="C:\\outside", to="codex")
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.NATIVE_ID,
        }):
            me = self._identify("codex.EXE")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])
        self.assertEqual(me["via"], "conflict")

    def test_environment_and_pane_host_agreement_corroborates_identity(self):
        seat(self.root, "codex", "codex-host", resume=self.NATIVE_ID)
        _write_host_record(self.root, "codex-host", host_pid=79, child_pid=80,
                           worktree="C:\\outside", to="codex")
        with patch.dict(self.env, {"CODEX_THREAD_ID": self.NATIVE_ID,
                                    "CODEX_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("codex.EXE")
        self.assertEqual((me["chair"], me["via"]), ("codex-host", "environment"))

    def test_duplicate_native_id_via_environment_refuses_ambiguity(self):
        seat(self.root, "codex", "codex-first", resume=self.NATIVE_ID)
        seat(self.root, "codex", "codex-second", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CODEX_THREAD_ID": self.NATIVE_ID,
                                    "CODEX_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("codex.EXE")
        self.assertEqual(me["via"], "conflict")
        self.assertIn("multiple chairs", me["ask"])

    def test_claude_environment_id_cannot_claim_a_codex_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {"CLAUDE_CODE_SESSION_ID": self.NATIVE_ID}):
            me = self._identify("claude.EXE")
        self.assertIsNone(me["chair"])
        self.assertIsNone(me["via"])

    def test_shell_mention_of_codex_exe_is_not_a_codex_ancestor(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        with patch.dict(self.env, {
            "CODEX_THREAD_ID": self.NATIVE_ID,
            "CODEX_SESSION_ID": self.NATIVE_ID,
        }):
            me = self._identify("powershell.EXE -Command codex.EXE")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])

    def test_session_id_in_the_callers_own_command_does_not_claim_a_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        me = self._identify("codex.EXE", "convoy whoami --probe " + self.NATIVE_ID)
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])

    def test_as_me_cannot_author_from_a_native_id_quoted_in_its_own_note(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        from convoy.layer import feed_since
        import convoy.panes as panes_module

        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        panes_module._TEST_PROCS = [
            {"pid": 80, "ppid": 1, "cmdline": "codex.EXE", "cwd": None},
            {"pid": 81, "ppid": 80,
             "cmdline": "convoy hook note mention " + self.NATIVE_ID + " --as-me", "cwd": None},
        ]
        panes_module._TEST_PID = 81
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["--root", str(self.root), "hook", "note",
                             "mention " + self.NATIVE_ID, "--as-me"])
        finally:
            panes_module._TEST_PROCS = None
            panes_module._TEST_PID = None
        self.assertEqual(code, 1)
        notes = [row for row in feed_since(self.root, "1970-01-01T00:00:00Z")
                 if row["kind"] == "note"]
        self.assertEqual(notes, [])

    def test_resume_id_prefix_is_not_an_exact_id_argument(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        me = self._identify("codex.EXE resume " + self.NATIVE_ID + "-other")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])

    def test_session_id_in_harness_prompt_text_does_not_claim_a_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        me = self._identify('codex.EXE "Please mention --resume ' + self.NATIVE_ID + ' in a note"')
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])

    def test_other_harness_resume_argument_does_not_claim_a_codex_chair(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        me = self._identify("claude.EXE --resume " + self.NATIVE_ID)
        self.assertIsNone(me["chair"])
        self.assertFalse(me["ok"])

    def test_exact_id_after_own_harness_resume_flag_still_matches(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        me = self._identify("codex.EXE resume " + self.NATIVE_ID)
        self.assertEqual((me["chair"], me["via"]), ("codex-outside", "token"))

    def test_codex_global_options_before_resume_still_match_identity(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        for cmdline in ("codex.EXE -a never resume " + self.NATIVE_ID,
                        "codex.EXE --dangerously-bypass-approvals-and-sandbox resume " + self.NATIVE_ID):
            with self.subTest(cmdline=cmdline):
                me = self._identify(cmdline)
                self.assertEqual((me["chair"], me["via"]), ("codex-outside", "token"))

    def test_codex_resume_flags_without_an_evidenced_id_do_not_claim_identity(self):
        seat(self.root, "codex", "codex-outside", resume=self.NATIVE_ID)
        for cmdline in ("codex.EXE resume --last",
                        "codex.EXE resume --yolo " + self.NATIVE_ID):
            with self.subTest(cmdline=cmdline):
                me = self._identify(cmdline)
                self.assertIsNone(me["chair"])
                self.assertIsNone(me["via"])

    def test_claude_short_and_equals_resume_forms_match_identity(self):
        seat(self.root, "claude", "claude-outside", resume=self.NATIVE_ID)
        for cmdline in ("claude.EXE -r " + self.NATIVE_ID,
                        "claude.EXE --resume=" + self.NATIVE_ID):
            with self.subTest(cmdline=cmdline):
                me = self._identify(cmdline)
                self.assertEqual((me["chair"], me["via"]), ("claude-outside", "token"))


if __name__ == "__main__":
    unittest.main()
