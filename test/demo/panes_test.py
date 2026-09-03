"""panes: see every body of every neuron in a session (Marco 2026-09-03).

Live failure that motivated it: codex-fable-opus was running in an unmanaged
pane; Convoy's registry-based liveness said live=false; a second `codex
resume <id>` was launched and codex refused ("already has an active writer").
Liveness must come from the OS process table, not only from what Convoy
launched. Matching is by vendor token in the command line first (portable),
then by cwd == worktree where the OS exposes cwd (Linux /proc, macOS lsof),
then by harness executable name only (an unassigned body the user can still
identify by pid)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.graph_html import resume_neuron
from convoy.panes import bodies, chair_live, match_processes


def _procs():
    return [
        {"pid": 11, "ppid": 1, "cmdline": "node C:/x/codex.js resume 01a0-codex-token", "cwd": None},
        {"pid": 12, "ppid": 1, "cmdline": "claude --resume e05249cb-claude-token", "cwd": "/w/claude"},
        {"pid": 13, "ppid": 1, "cmdline": "grok -m grok-4.6", "cwd": "/w/grok"},
        {"pid": 14, "ppid": 1, "cmdline": "codex", "cwd": None},
        {"pid": 15, "ppid": 1, "cmdline": "notepad.exe", "cwd": None},
    ]


class MatchProcesses(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree="/w/codex", resume="01a0-codex-token")
        seat(self.root, "claude", "a-t1", worktree="/w/claude-other", resume="e05249cb-claude-token")
        seat(self.root, "grok", "g-t1", worktree="/w/grok")
        seat(self.root, "claude", "idle-t1", worktree="/w/idle")

    def test_token_cwd_and_exe_matching(self):
        out = match_processes(self.root, _procs())
        by = {c["session_id"]: c for c in out["chairs"]}
        self.assertTrue(by["c-t1"]["live"])
        self.assertEqual(by["c-t1"]["bodies"][0]["via"], "token")
        self.assertEqual(by["c-t1"]["bodies"][0]["pid"], 11)
        self.assertTrue(by["a-t1"]["live"])           # token wins even when cwd differs
        self.assertEqual(by["a-t1"]["bodies"][0]["via"], "token")
        self.assertTrue(by["g-t1"]["live"])
        self.assertEqual(by["g-t1"]["bodies"][0]["via"], "cwd")
        self.assertFalse(by["idle-t1"]["live"])
        self.assertEqual(by["idle-t1"]["bodies"], [])
        # a harness body Convoy cannot place is listed, not hidden
        self.assertEqual([u["pid"] for u in out["unassigned"]], [14])
        self.assertEqual(out["unassigned"][0]["harness"], "codex")
        # non-harness processes never appear
        self.assertNotIn(15, [b["pid"] for c in out["chairs"] for b in c["bodies"]] + [u["pid"] for u in out["unassigned"]])

    def test_tokens_never_appear_in_the_view(self):
        import json
        blob = json.dumps(match_processes(self.root, _procs()))
        self.assertNotIn("01a0-codex-token", blob)
        self.assertNotIn("e05249cb-claude-token", blob)

    def test_bodies_marks_two_bodies_on_one_chair(self):
        procs = _procs() + [{"pid": 21, "ppid": 1, "cmdline": "codex resume 01a0-codex-token", "cwd": None}]
        by = {c["session_id"]: c for c in match_processes(self.root, procs)["chairs"]}
        self.assertEqual(len(by["c-t1"]["bodies"]), 2)
        self.assertTrue(by["c-t1"]["duplicate"])

    def test_chair_live_and_resume_guard_use_the_process_table(self):
        self.assertTrue(chair_live(self.root, "c-t1", procs=_procs()))
        self.assertFalse(chair_live(self.root, "idle-t1", procs=_procs()))
        card = resume_neuron(self.root, "c-t1", go=True, spawn=lambda a, c: 1,
                             liveness=lambda root, sid: chair_live(root, sid, procs=_procs()))
        self.assertFalse(card["ok"])
        self.assertIn("live", card["error"])

    def test_bodies_falls_back_to_empty_when_enumeration_fails(self):
        out = bodies(self.root, enumerate_fn=lambda: (_ for _ in ()).throw(OSError("no ps")))
        self.assertEqual(out["source"], None)
        self.assertIn("no ps", out["error"])
        self.assertTrue(all(not c["live"] for c in out["chairs"]))

    def test_helpers_fold_into_one_body_and_worktree_arg_matches_on_windows(self):
        """Live 2026-09-03: the lead chair showed two bodies by token — the
        session plus its --bg-pty-host parent. One ancestor chain is one body.
        A grok launched fresh carries its worktree in --agent; that is the
        Windows substitute for cwd."""
        procs = [
            {"pid": 50, "ppid": 1, "cmdline": "claude --bg-pty-host pipe-e05 -- claude --resume 01a0-codex-token", "cwd": None},
            {"pid": 51, "ppid": 50, "cmdline": "codex resume 01a0-codex-token", "cwd": None},
            {"pid": 52, "ppid": 51, "cmdline": "claude --type=utility --utility-sub-type=x", "cwd": None},
            {"pid": 53, "ppid": 1, "cmdline": "claude daemon run --origin transient", "cwd": None},
            {"pid": 54, "ppid": 1, "cmdline": "codex app-server --listen stdio://", "cwd": None},
            {"pid": 55, "ppid": 1, "cmdline": "grok.EXE --trust --agent C:\\w\\grok\\.grok\\agents\\convoy-neuron.md", "cwd": None},
        ]
        seat(self.root, "grok", "gw-t1", worktree="C:\\w\\grok")
        out = match_processes(self.root, procs)
        by = {c["session_id"]: c for c in out["chairs"]}
        self.assertEqual([b["pid"] for b in by["c-t1"]["bodies"]], [51])   # the pty host is a helper; the session is the body
        self.assertFalse(by["c-t1"]["duplicate"])
        self.assertEqual(by["gw-t1"]["bodies"][0]["via"], "worktree")
        unassigned = {u["pid"] for u in out["unassigned"]}
        self.assertNotIn(52, unassigned)   # utility child of a claimed body
        self.assertNotIn(53, unassigned)   # daemon
        self.assertNotIn(54, unassigned)   # app-server
        self.assertFalse(out.get("error"))


class LivenessHasThreeStates(unittest.TestCase):
    """Marco 2026-09-03, from a screenshot of two obviously running panes:
    `panes` reported codex-fable-opus live=false while eight codex processes
    were running. On Windows a codex body carries neither a token nor its
    worktree in the command line and the OS exposes no cwd, so it cannot be
    placed. Unknown must be null; false is a claim we cannot make, and this
    session repeated it to the user."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree="/w/codex", resume="tok-c")
        seat(self.root, "claude", "idle-t1", worktree="/w/idle")

    def test_unplaceable_harness_processes_make_liveness_unknown_not_false(self):
        procs = [{"pid": 40, "ppid": 1, "cmdline": "node /x/codex.js", "cwd": None}]
        by = {c["session_id"]: c for c in match_processes(self.root, procs)["chairs"]}
        self.assertIsNone(by["c-t1"]["live"])
        self.assertIn("could not be placed", by["c-t1"]["live_reason"])
        self.assertEqual([u["pid"] for u in match_processes(self.root, procs)["unassigned"]], [40])
        # a chair whose harness has no process at all is honestly not live
        self.assertIs(by["idle-t1"]["live"], False)
        self.assertIn("no claude process", by["idle-t1"]["live_reason"])

    def test_a_matched_body_is_still_plain_true(self):
        procs = [{"pid": 41, "ppid": 1, "cmdline": "codex resume tok-c", "cwd": None}]
        by = {c["session_id"]: c for c in match_processes(self.root, procs)["chairs"]}
        self.assertIs(by["c-t1"]["live"], True)

    def test_the_no_steal_guard_refuses_on_unknown(self):
        from convoy.panes import chair_liveness
        procs = [{"pid": 40, "ppid": 1, "cmdline": "node /x/codex.js", "cwd": None}]
        self.assertIsNone(chair_liveness(self.root, "c-t1", procs=procs))
        self.assertTrue(chair_live(self.root, "c-t1", procs=procs), "unknown must read as live to a guard")
        self.assertFalse(chair_live(self.root, "idle-t1", procs=procs))
        card = resume_neuron(self.root, "c-t1", go=True, spawn=lambda a, c: 1,
                             liveness=lambda root, sid: chair_live(root, sid, procs=procs))
        self.assertFalse(card["ok"])
        self.assertIn("live", card["error"])


class Whoami(unittest.TestCase):
    """Marco 2026-09-03: detect -> if the detected body is a chair on THIS
    thread, let the agent identify itself, then send. `whoami` walks the
    caller's own ancestry (shell -> harness) and matches it to a chair; only
    then does a note carry that chair as author."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1", worktree="/w/a", resume="tok-a")
        seat(self.root, "grok", "g-t1", worktree="/w/g")
        self.procs = [
            {"pid": 12, "ppid": 1, "cmdline": "claude --resume tok-a", "cwd": None},
            {"pid": 30, "ppid": 12, "cmdline": "bash -c convoy whoami", "cwd": None},
            {"pid": 13, "ppid": 1, "cmdline": "grok -m grok-4.6", "cwd": "/w/g"},
            {"pid": 31, "ppid": 13, "cmdline": "sh", "cwd": "/w/g"},
            {"pid": 40, "ppid": 1, "cmdline": "notepad.exe", "cwd": None},
        ]

    def test_identifies_by_token_in_the_ancestor_harness(self):
        from convoy.panes import identify
        me = identify(self.root, pid=30, procs=self.procs)
        self.assertEqual((me["chair"], me["via"], me["harness_pid"]), ("a-t1", "token", 12))
        self.assertTrue(me["on_thread"])

    def test_identifies_by_cwd_when_no_token(self):
        from convoy.panes import identify
        me = identify(self.root, pid=31, procs=self.procs, cwd="/w/g")
        self.assertEqual((me["chair"], me["via"]), ("g-t1", "cwd"))

    def test_unknown_body_is_null_and_may_not_author(self):
        from convoy.panes import identify
        me = identify(self.root, pid=40, procs=self.procs, cwd="/elsewhere")
        self.assertIsNone(me["chair"])
        self.assertFalse(me["on_thread"])
        self.assertIn("join", me["ask"])

    def test_cli_whoami_and_note_as_me(self):
        import io, json
        from contextlib import redirect_stdout
        from convoy.cli import main
        from convoy.layer import feed_since
        import convoy.panes as panes
        panes._TEST_PROCS = self.procs
        panes._TEST_PID = 30
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--root", str(self.root), "whoami"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["chair"], "a-t1")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--root", str(self.root), "hook", "note", "hello g", "--as-me", "--to", "g-t1"])
            self.assertEqual(rc, 0)
            row = [r for r in feed_since(self.root, "1970-01-01T00:00:00Z") if r["kind"] == "note"][-1]
            self.assertEqual((row["from"], row["to"]), ("a-t1", "g-t1"))
            panes._TEST_PID = 40
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--root", str(self.root), "hook", "note", "who am i", "--as-me"])
            self.assertEqual(rc, 1)
        finally:
            panes._TEST_PROCS = None
            panes._TEST_PID = None


if __name__ == "__main__":
    unittest.main()
