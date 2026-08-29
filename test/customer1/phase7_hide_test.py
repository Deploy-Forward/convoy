import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.bringup import (
    _live_argv,
    hide_windows,
    live_applier,
    live_runner,
    resume_argv,
)
from convoy.mcp_http import TOOLS, call_tool, handle_rpc


def _run(root, *argv):
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue()
    data = json.loads(raw) if raw.strip() else None
    return rc, data


class Phase7Hide(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "thread.md").write_text("SECRET_THREAD_BYTES")
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("SECRET_BRIEF")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())
        self.thread = "customer1"
        self.cid = ensure_id(self.root)
        bind(self.root, self.thread)
        self.g = seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok")
        self.c = seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="Fable 5")

    def test_hide_mock_applier_records_minimize_no_mint(self):
        recorded = []

        def mock_applier(resume, mode, to=None, **k):
            recorded.append({"to": to, "resume": resume, "mode": mode})
            return {"ok": True}

        d = hide_windows(self.root, applier=mock_applier)
        self.assertTrue(d["ok"])
        self.assertEqual(d["conductor"], "grok-bot")
        self.assertEqual(d["convoy_id"], self.cid)
        self.assertEqual(d["thread"], self.thread)
        tos = [w["to"] for w in d["windows"]]
        self.assertEqual(set(tos), {"grok", "claude"})
        self.assertNotIn("grok-bot", tos)
        by = {w["to"]: w for w in d["windows"]}
        self.assertEqual(by["grok"]["action"], "minimize")
        self.assertEqual(by["claude"]["action"], "minimize")
        self.assertTrue(by["grok"]["ok"])
        self.assertTrue(by["claude"]["ok"])
        self.assertEqual(by["grok"]["session_id"], "sess-grok")
        self.assertEqual(by["claude"]["session_id"], "sess-claude")
        self.assertEqual(by["grok"]["resume"], "sess-grok")
        self.assertEqual({r["mode"] for r in recorded}, {"minimize"})
        self.assertEqual({r["to"] for r in recorded}, {"grok", "claude"})
        self.assertEqual(len(recorded), 2)
        self.assertNotIn("spawned-grok", {w["session_id"] for w in d["windows"]})

    def test_hide_noop_applier_not_called(self):
        called = {"n": 0}

        def boom(*a, **k):
            called["n"] += 1
            raise AssertionError("applier must not run when dry/no-op")

        d = hide_windows(self.root)
        self.assertTrue(d["ok"])
        self.assertEqual(called["n"], 0)
        d2 = hide_windows(self.root, applier=None)
        self.assertTrue(d2["ok"])
        self.assertEqual(called["n"], 0)
        for w in d["windows"]:
            self.assertEqual(w["action"], "minimize")
            self.assertTrue(w["ok"])
        seat(self.root, "grok-bot", "sess-bot", worktree=str(self.wt_g))
        d3 = hide_windows(self.root)
        self.assertNotIn("grok-bot", [w["to"] for w in d3["windows"]])

    def test_cli_hide_minimize_background_dry_run(self):
        for cmd in ("hide", "minimize", "background"):
            rc, d = _run(self.root, cmd, "--dry-run")
            self.assertEqual(rc, 0, cmd)
            self.assertTrue(d["ok"], cmd)
            self.assertEqual(len(d["windows"]), 2, cmd)
            for w in d["windows"]:
                self.assertEqual(w["action"], "minimize", cmd)
                self.assertIn(w["session_id"], ("sess-grok", "sess-claude"))

    def test_hide_mode_hide_recorded(self):
        recorded = []

        def mock_applier(resume, mode, to=None, **k):
            recorded.append(mode)
            return {"ok": True}

        d = hide_windows(self.root, mode="hide", applier=mock_applier)
        self.assertTrue(d["ok"])
        for w in d["windows"]:
            self.assertEqual(w["action"], "hide")
        self.assertEqual(recorded, ["hide", "hide"])

    def test_mcp_tools_list_includes_hide_aliases(self):
        listed = handle_rpc(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [t["name"] for t in listed["result"]["tools"]]
        for want in ("hide", "minimize", "background", "bring_up", "send"):
            self.assertIn(want, names)
        send = next(t for t in TOOLS if t["name"] == "send")
        desc = send["description"]
        self.assertIn("headless hop; does not pop a TUI", desc)
        low = desc.lower()
        self.assertNotIn("visible tui", low)
        self.assertNotIn("pop windows", low)

    def test_mcp_hide_dry_run_two_seats_action_minimize(self):
        with mock.patch("convoy.mcp_http.live_applier") as applied:
            applied.side_effect = AssertionError("live_applier must not run when dry_run true")
            payload = call_tool(self.root, "hide", {"dry_run": True})
        self.assertTrue(payload["ok"])
        self.assertTrue(payload.get("dry_run", True))
        self.assertEqual(len(payload["windows"]), 2)
        by = {w["to"]: w for w in payload["windows"]}
        self.assertEqual(by["grok"]["action"], "minimize")
        self.assertEqual(by["claude"]["action"], "minimize")
        self.assertEqual(by["grok"]["session_id"], "sess-grok")
        self.assertEqual(by["claude"]["session_id"], "sess-claude")
        applied.assert_not_called()
        for alias in ("minimize", "background"):
            p2 = call_tool(self.root, alias, {"dry_run": True})
            self.assertEqual({w["action"] for w in p2["windows"]}, {"minimize"})

    def test_resume_argv_absolute_when_which_hits_never_wrap(self):
        abs_claude = "/tmp/fake-claude"
        with mock.patch("convoy.bringup.shutil.which", return_value=abs_claude):
            argv = resume_argv(self.c)
        self.assertEqual(argv, [abs_claude, "--resume", "sess-claude"])
        self.assertNotIn("-d", argv)
        self.assertNotIn("--", argv)
        self.assertNotIn("ola-brain", " ".join(argv).lower())
        self.assertNotIn("side-chat", " ".join(argv).lower())
        self.assertNotEqual(os.path.basename(argv[0]).lower(), "wt.exe")
        with self.assertRaises(ValueError):
            resume_argv({"to": "ola-brain", "session_id": "x"})

    def test_live_runner_popen_gets_absolute_file_name(self):
        wt = r"C:\Windows\System32\wt.exe"
        grok = r"C:\abs\grok.exe"
        argv_in = [wt, "--window", "new", "nt", "--title", "grok-0", "-d", str(self.wt_g), grok, "--resume", "sess-grok"]
        proc = mock.Mock()
        proc.pid = 77
        with mock.patch("convoy.bringup.os.name", "nt"), \
             mock.patch("convoy.bringup.subprocess.Popen", return_value=proc) as popen:
            d = live_runner(argv_in, cwd=str(self.wt_g))
        self.assertTrue(d["ok"])
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], wt)
        self.assertEqual(argv, argv_in)
        self.assertNotIn("creationflags", popen.call_args.kwargs)
        self.assertNotIn("--", argv)
        self.assertNotIn("-w", argv)
        self.assertNotIn("ola-brain", " ".join(argv).lower())
        popen.assert_called_once()

    def test_live_argv_refuses_ola_brain_and_dash_d_wrap(self):
        abs_claude = r"C:\abs\claude.exe"
        wt = r"C:\Windows\System32\wt.exe"
        with self.assertRaises(ValueError):
            _live_argv(["ola-brain", "side-chat", "send", "claude", "hi"])
        with self.assertRaises(ValueError):
            _live_argv(["claude", "-d", r"C:\Users\marco\ola\ola-brain", "--", abs_claude, "--resume", "sess-claude"])
        with self.assertRaises(ValueError):
            _live_argv(["wt", "-d", r"C:\tmp", "--", abs_claude, "--resume", "sess-claude"])
        with self.assertRaises(ValueError):
            _live_argv(["claude", "--resume", "sess-claude"])
        out = _live_argv([wt, "--window", "new", "nt", "--title", "claude-0", "-d", r"C:\Users\marco\ola\ola-brain", abs_claude, "--resume", "sess-claude"])
        self.assertEqual(out[0], wt)
        self.assertEqual(out[1:4], ["--window", "new", "nt"])
        self.assertNotIn("--", out)
        self.assertNotIn("-w", out)


if __name__ == "__main__":
    unittest.main()
