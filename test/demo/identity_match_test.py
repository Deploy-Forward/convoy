"""Identity that cannot lie.

The defect: `panes._mentions_path` matched a seat by path
SUBSTRING anywhere in the command line. A crew boot prompt carries the thread
root inside one quoted argument, so a crew pane on the thread could answer
`whoami` as the ROOT's chair - and `--as-me` authors from that answer. An
identity surface that guesses is worse than one that refuses.

The order this file pins:
  1. the chair's vendor token in the caller's pid lineage   (via "token")
  2. the pane-host record for a pid in that lineage         (via "pane-host")
  3. cwd, or an ARGUMENT that IS the worktree path          (via "worktree"/"cwd")
  4. pid record and path disagreeing -> `conflict`, naming both, never the
     path's chair.

Paths here are written with doubled backslashes on purpose: these are Windows
command lines, and a single backslash before b or t is an escape, not a
separator. An earlier draft of this file lost that and tested "C:\\w\\crew\\x08in".
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

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


def _write_host_record(root, session_id, host_pid, child_pid, worktree, status="running"):
    path = host_state_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "session_id": session_id, "status": status, "host_pid": host_pid,
        "child_pid": child_pid, "child_exe": "C:\\bin\\claude.EXE",
        "worktree": worktree, "to": "claude",
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

    def test_a_token_still_outranks_the_pane_host_record(self):
        seat(self.root, "claude", "tok-t1", worktree="C:\\w\\tok", resume="tok-abc")
        procs = [
            {"pid": 20, "ppid": 1, "cmdline": "claude.EXE --resume tok-abc", "cwd": None},
            {"pid": 21, "ppid": 20, "cmdline": "bash -c convoy whoami", "cwd": None},
        ]
        _write_host_record(self.root, "crew-t1", host_pid=19, child_pid=20, worktree=CREW_WT)
        me = identify(self.root, pid=21, procs=procs, cwd=None)
        self.assertEqual((me["chair"], me["via"]), ("tok-t1", "token"))

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


if __name__ == "__main__":
    unittest.main()
