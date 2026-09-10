import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.convoy import bind, ensure_id, lookup_resume, make_resume_key, seat
from convoy.bringup import CREATE_NEW_CONSOLE, _pids_for_resume, bring_up, isolated_wt_argv, live_runner, live_spawn_kwargs, resume_argv, terminals, tile_rects


def _native_resume(argv, name, sid, *, model=None, agent=None):
    """PATH-resolved abs or bare exe; ends with [--resume, sid]."""
    base = os.path.basename(str(argv[0])).lower().removesuffix(".exe")
    assert base == name, (base, name, argv)
    assert "--resume" in argv, argv
    ridx = argv.index("--resume")
    assert argv[ridx:] == ["--resume", sid], argv
    prefix = argv[1:ridx]
    if model is not None:
        assert "-m" in prefix, argv
        midx = prefix.index("-m")
        assert prefix[midx + 1] == model, argv
    else:
        assert "-m" not in prefix, argv
    if agent is not None:
        assert "--agent" in prefix, argv
        aidx = prefix.index("--agent")
        assert prefix[aidx + 1] == agent, argv
    else:
        assert "--agent" not in prefix, argv

def _run(root, *argv):
    buf = io.StringIO()
    err = io.StringIO()
    from contextlib import redirect_stdout, redirect_stderr
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue()
    data = json.loads(raw) if raw.strip() else None
    return rc, data

def _on_screen(rects, sw=1920, sh=1080):
    for r in rects:
        assert isinstance(r["x"], int) and isinstance(r["y"], int)
        assert isinstance(r["w"], int) and isinstance(r["h"], int)
        assert r["w"] > 0 and r["h"] > 0
        assert r["x"] >= 0 and r["y"] >= 0
        assert r["x"] + r["w"] <= sw
        assert r["y"] + r["h"] <= sh

def _overlap_area(a, b):
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, x2 - x1) * max(0, y2 - y1)

class Phase7BringUp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "thread.md").write_text("SECRET_THREAD_BYTES")
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("SECRET_BRIEF")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())
        self.thread = "demo"
        self.cid = ensure_id(self.root)
        bind(self.root, self.thread)
        self.g = seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok", resume="sess-grok")
        self.c = seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="claude-fable-5", resume="sess-claude")
        self.fake_home = Path(tempfile.mkdtemp())
        self._home_patcher = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home_patcher.start()
        self.addCleanup(self._home_patcher.stop)

    def test_resume_argv_native_two_seats(self):
        gargv = resume_argv(self.g)
        cargv = resume_argv(self.c)
        _native_resume(gargv, "grok", "sess-grok", model="explicit-grok")
        _native_resume(cargv, "claude", "sess-claude")
        for argv, sid in ((gargv, "sess-grok"), (cargv, "sess-claude")):
            self.assertIn("--resume", argv)
            self.assertIn(sid, argv)
            joined = " ".join(argv)
            self.assertNotIn("ola-brain", joined)
            self.assertNotIn("side-chat", joined)
            self.assertNotIn("-p", argv)
            self.assertNotIn("-c", argv)
            self.assertNotIn("--output-format", argv)

    def test_dry_run_bring_up_two_windows_distinct_rects(self):
        rc, d = _run(self.root, "bring-up", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertEqual(d["convoy_id"], self.cid)
        self.assertEqual(d["thread"], self.thread)
        self.assertEqual(d["conductor"], "grok-bot")
        self.assertEqual(len(d["windows"]), 2)
        tos = {w["to"] for w in d["windows"]}
        self.assertEqual(tos, {"grok", "claude"})
        rects = [w["rect"] for w in d["windows"]]
        self.assertNotEqual(rects[0], rects[1])
        _on_screen(rects)
        self.assertEqual(_overlap_area(rects[0], rects[1]), 0)
        by = {w["to"]: w for w in d["windows"]}
        self.assertEqual(by["grok"]["resume"], "sess-grok")
        self.assertEqual(by["grok"]["session_id"], "sess-grok")
        self.assertEqual(by["grok"]["resume"], by["grok"]["session_id"])
        self.assertEqual(by["claude"]["resume"], "sess-claude")
        self.assertIsNotNone(by["grok"]["resume"])
        self.assertIsNotNone(by["claude"]["resume"])
        # agent-less grok seats point at the Convoy-owned agent file (#15)
        convoy_agent = str(Path(self.wt_g) / ".grok" / "agents" / "convoy-neuron.md")
        _native_resume(by["grok"]["argv"], "grok", "sess-grok", model="explicit-grok", agent=convoy_agent)
        _native_resume(by["claude"]["argv"], "claude", "sess-claude")
        self.assertEqual(by["grok"]["worktree"], str(self.wt_g))
        self.assertEqual(by["grok"]["cwd"], str(self.wt_g))
        self.assertEqual(by["claude"]["worktree"], str(self.wt_c))
        self.assertTrue(by["grok"]["ok"])
        self.assertTrue(by["claude"]["ok"])
        self.assertFalse(by["grok"]["headless"])
        for w in d["windows"]:
            self.assertNotIn("ola-brain", w["argv"])
            self.assertNotIn("side-chat", w["argv"])
            self.assertNotIn("-p", w["argv"])
            self.assertNotIn("-c", w["argv"])
            self.assertIn("--resume", w["argv"])
            self.assertIn(w["session_id"], w["argv"])
            self.assertEqual(w["resume"], w["session_id"])
            self.assertTrue(str(w["resume_key"]).startswith("cvr_"))

    def test_open_alias_same_as_bring_up(self):
        rc1, a = _run(self.root, "bring-up", "--dry-run")
        rc2, b = _run(self.root, "open", "--dry-run")
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(a["windows"][0]["argv"], b["windows"][0]["argv"])
        self.assertEqual(len(a["windows"]), len(b["windows"]))

    def test_conductor_grok_bot_is_not_a_window(self):
        seat(self.root, "grok-bot", "sess-bot", worktree=str(self.wt_g))
        d = bring_up(self.root)
        self.assertEqual(d["conductor"], "grok-bot")
        tos = [w["to"] for w in d["windows"]]
        self.assertNotIn("grok-bot", tos)
        self.assertEqual(set(tos), {"grok", "claude"})
        rc, cli = _run(self.root, "bring-up", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertNotIn("grok-bot", [w["to"] for w in cli["windows"]])

    def test_missing_vendor_resume_omits_resume_flag(self):
        argv = resume_argv({"to": "grok", "session_id": "seat-only", "model": "explicit-grok"})
        self.assertNotIn("--resume", argv)
        seats_path = self.root / ".convoy" / "seats.jsonl"
        seats_path.write_text(seats_path.read_text(encoding="utf-8") + json.dumps({"convoy_id": self.cid, "to": "codex", "session_id": "", "worktree": None}) + "\n", encoding="utf-8")
        d = bring_up(self.root)
        by = {w["to"]: w for w in d["windows"]}
        self.assertIn("codex", by)
        self.assertTrue(by["codex"]["ok"])
        self.assertIsNone(by["codex"]["resume"])
        self.assertNotIn("--resume", by["codex"]["argv"])
        self.assertTrue(by["grok"]["ok"])

    def test_tile_2_and_3_on_1920x1080(self):
        r2 = tile_rects(2, screen=(1920, 1080))
        self.assertEqual(len(r2), 2)
        _on_screen(r2, 1920, 1080)
        self.assertEqual(_overlap_area(r2[0], r2[1]), 0)
        self.assertEqual(r2[0]["x"] + r2[0]["w"], r2[1]["x"])
        self.assertEqual(r2[0]["h"], 1080)
        self.assertEqual(r2[1]["h"], 1080)
        self.assertEqual(r2[0]["w"] + r2[1]["w"], 1920)
        r3 = tile_rects(3, screen=(1920, 1080))
        self.assertEqual(len(r3), 3)
        _on_screen(r3, 1920, 1080)
        self.assertEqual(_overlap_area(r3[0], r3[1]), 0)
        self.assertEqual(_overlap_area(r3[0], r3[2]), 0)
        self.assertEqual(_overlap_area(r3[1], r3[2]), 0)
        # left + two stacked right
        self.assertEqual(r3[0]["h"], 1080)
        self.assertEqual(r3[1]["x"], r3[2]["x"])
        self.assertEqual(r3[1]["y"] + r3[1]["h"], r3[2]["y"])
        r1 = tile_rects(1, screen=(1920, 1080))
        self.assertEqual(r1[0], {"x": 24, "y": 24, "w": 1872, "h": 1032})

    def test_resume_key_same_inputs_same_hash_different_thread_differs(self):
        a = make_resume_key(self.cid, self.thread, "grok", str(self.wt_g))
        b = make_resume_key(self.cid, self.thread, "grok", str(self.wt_g))
        c = make_resume_key(self.cid, self.thread, "grok", str(self.wt_c))
        d = make_resume_key(self.cid, "other-thread", "grok", str(self.wt_g))
        e = make_resume_key(self.cid, self.thread, "claude", str(self.wt_c))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)
        self.assertTrue(a.startswith("cvr_"))
        self.assertEqual(len(a), 4 + 16)
        self.assertEqual(self.g["resume_key"], a)
        self.assertEqual(self.c["resume_key"], e)
        self.assertEqual(lookup_resume(self.root, self.thread, "grok", worktree=str(self.wt_g)), "sess-grok")
        self.assertEqual(lookup_resume(self.root, self.thread, "claude", worktree=str(self.wt_c)), "sess-claude")
        self.assertIsNone(lookup_resume(self.root, "other-thread", "grok", worktree=str(self.wt_g)))
        card = bring_up(self.root)
        by = {w["to"]: w for w in card["windows"]}
        self.assertEqual(by["grok"]["resume_key"], a)
        self.assertEqual(by["claude"]["resume_key"], e)

    def test_resume_key_includes_worktree_for_same_harness(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t")
        wt_a = Path(tempfile.mkdtemp())
        wt_b = Path(tempfile.mkdtemp())
        a = seat(root, "grok", "sess-a", worktree=str(wt_a), resume="vendor-a")
        b = seat(root, "grok", "sess-b", worktree=str(wt_b), resume="vendor-b")
        self.assertNotEqual(a["resume_key"], b["resume_key"])
        self.assertEqual(lookup_resume(root, "t", "grok", worktree=str(wt_a)), "vendor-a")
        self.assertEqual(lookup_resume(root, "t", "grok", worktree=str(wt_b)), "vendor-b")

    def test_optional_resume_field_used_in_argv(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t")
        row = seat(
            root,
            "grok",
            "ola-instance",
            worktree=str(self.wt_g),
            model="grok-4.6",
            resume="vendor-uuid-not-invented",
            title="lead-prreview",
            agent="agents/lead-prreview.md",
        )
        self.assertEqual(row["session_id"], "ola-instance")
        self.assertEqual(row["resume"], "vendor-uuid-not-invented")
        self.assertEqual(row["model"], "grok-4.6")
        self.assertEqual(row["title"], "lead-prreview")
        self.assertEqual(row["agent"], "agents/lead-prreview.md")
        argv = resume_argv(row)
        _native_resume(
            argv,
            "grok",
            "vendor-uuid-not-invented",
            model="grok-4.6",
            agent="agents/lead-prreview.md",
        )
        self.assertNotIn("ola-instance", argv)
        d = bring_up(root)
        self.assertTrue(d["windows"][0]["ok"])
        self.assertEqual(d["windows"][0]["resume"], "vendor-uuid-not-invented")
        self.assertEqual(d["windows"][0]["session_id"], "ola-instance")
        self.assertEqual(lookup_resume(root, "t", "grok"), "vendor-uuid-not-invented")

    def test_first_run_seat_omits_resume_until_vendor_id_exists(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t")
        row = seat(root, "claude", "seat-key-not-vendor", worktree=str(self.wt_c))
        self.assertIsNone(row.get("resume"))
        argv = resume_argv(row)
        self.assertEqual(os.path.basename(str(argv[0])).lower().removesuffix(".exe"), "claude")
        self.assertNotIn("--resume", argv)
        d = bring_up(root)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["windows"]), 1)
        self.assertIsNone(d["windows"][0]["resume"])
        self.assertNotIn("--resume", d["windows"][0]["argv"])

    def test_codex_resume_uses_subcommand_not_flag(self):
        row = {
            "to": "codex",
            "session_id": "seat-codex",
            "resume": "vendor-codex-uuid",
            "worktree": str(self.wt_c),
        }
        argv = resume_argv(row)
        # stem, not removesuffix(".exe"): Windows npm shims resolve to codex.cmd
        self.assertEqual(Path(str(argv[0])).stem.lower(), "codex")
        self.assertEqual(argv[1:], ["resume", "vendor-codex-uuid"])
        self.assertNotIn("--resume", argv)

    def test_bring_up_uses_latest_seated_neuron_for_same_worktree(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t")
        wt = str(self.wt_g)
        seat(root, "grok", "sess-old", worktree=wt, resume="vendor-old")
        with self.assertRaises(ValueError):
            seat(root, "grok", "sess-new", worktree=wt, resume="vendor-new")
        # Same chair may re-seat the worktree (occupancy update, last row wins).
        seat(root, "grok", "sess-old", worktree=wt, resume="vendor-new")
        d = bring_up(root)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["windows"]), 1)
        win = d["windows"][0]
        self.assertEqual(win["session_id"], "sess-old")
        self.assertEqual(win["resume"], "vendor-new")
        self.assertEqual(win["argv"][-2:], ["--resume", "vendor-new"])

    def test_dry_run_does_not_mint_session_id(self):
        before = {self.g["session_id"], self.c["session_id"]}
        rc, d = _run(self.root, "open", self.cid, "--dry-run")
        self.assertEqual(rc, 0)
        after = {w["session_id"] for w in d["windows"]}
        self.assertTrue(after.issubset(before))
        self.assertNotIn("spawned-grok", after)

    def test_lib_bring_up_does_not_call_live_runner(self):
        called = {"n": 0}
        def boom(*a, **k):
            called["n"] += 1
            raise AssertionError("live runner must not run in this test")
        d = bring_up(self.root)  # default runner is no-op
        self.assertTrue(d["ok"])
        self.assertEqual(called["n"], 0)
        d2 = bring_up(self.root, runner=None)
        self.assertTrue(d2["ok"])
        self.assertEqual(called["n"], 0)
        # injecting boom would exec; we do not pass it. prove default stays dry:
        self.assertEqual(len(d["windows"]), 2)

    def test_terminals_metadata_no_pty(self):
        rc, d = _run(self.root, "terminals")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["windows"]), 2)
        blob = json.dumps(d)
        self.assertNotIn("SECRET_THREAD_BYTES", blob)
        self.assertNotIn("SECRET_BRIEF", blob)
        for w in d["windows"]:
            self.assertIn("to", w)
            self.assertIn("session_id", w)
            self.assertIn("resume", w)
            self.assertIn("resume_key", w)
            self.assertIn("worktree", w)
            self.assertIn("rect", w)
            self.assertFalse(w.get("live"))
            self.assertNotIn("body", w)
            self.assertNotIn("pty", w)
            self.assertNotIn("transcript", w)
        lib = terminals(self.root)
        self.assertEqual(len(lib["windows"]), 2)

    def test_terminals_live_derived_from_pid_lookup(self):
        with mock.patch("convoy.bringup._pids_for_resume", side_effect=lambda resume: {31} if resume == "sess-grok" else set()):
            card = terminals(self.root)
        by = {w["to"]: w for w in card["windows"]}
        self.assertTrue(by["grok"]["live"])
        self.assertFalse(by["claude"]["live"])

    def test_thread_mismatch_refuses(self):
        d = bring_up(self.root, thread="not-this-thread")
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "thread mismatch")
        self.assertFalse(d.get("windows"))

    def test_convoy_id_mismatch_refuses(self):
        rc, d = _run(self.root, "bring-up", "cvy_not_this_convoy", "--dry-run")
        self.assertNotEqual(rc, 0)
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "convoy_id mismatch")


    def _which_map(self, extra=None):
        mapping = {
            "wt": r"C:\\Windows\\System32\\wt.exe",
            "wt.exe": r"C:\\Windows\\System32\\wt.exe",
            "grok": r"C:\\abs\\grok.exe",
            "grok.exe": r"C:\\abs\\grok.exe",
            "claude": r"C:\\abs\\claude.exe",
            "claude.exe": r"C:\\abs\\claude.exe",
            "codex": r"C:\\abs\\codex.exe",
            "codex.exe": r"C:\\abs\\codex.exe",
        }
        if extra:
            mapping.update(extra)
        def fake_which(name):
            return mapping.get(str(name).lower())
        return fake_which

    def _wt_seats(self):
        # bring_up points agent-less grok seats at the Convoy agent file (#15)
        convoy_agent = str(Path(self.wt_g) / ".grok" / "agents" / "convoy-neuron.md")
        return [
            {**self.g, "agent": convoy_agent, "exe": r"C:\\abs\\grok.exe"},
            {**self.c, "exe": r"C:\\abs\\claude.exe"},
        ]

    def test_bring_up_merges_runner_pid_and_note(self):
        recorded = []
        def fake_runner(argv, cwd=None, rect=None, **k):
            recorded.append({"argv": list(argv), "cwd": cwd, "rect": rect, "k": k})
            return {"ok": True, "pid": 4242, "note": "isolated wt"}
        with mock.patch("convoy.bringup.shutil.which", side_effect=self._which_map()):
            d = bring_up(self.root, runner=fake_runner)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["windows"]), 2)
        self.assertEqual(len(recorded), 1)
        for w in d["windows"]:
            self.assertEqual(w.get("pid"), 4242)
            self.assertEqual(w.get("note"), "isolated wt")
            self.assertTrue(w.get("ok"))

    def test_live_bring_up_one_isolated_wt_spawn(self):
        recorded = []
        def fake_runner(argv, cwd=None, rect=None, **k):
            recorded.append({"argv": list(argv), "cwd": cwd, "rect": rect})
            return {"ok": True, "pid": 99}
        with mock.patch("convoy.bringup.shutil.which", side_effect=self._which_map()):
            expected = isolated_wt_argv(self.thread, self._wt_seats(), wt=r"C:\\Windows\\System32\\wt.exe")
            d = bring_up(self.root, runner=fake_runner)
        self.assertTrue(d["ok"])
        self.assertEqual(len(recorded), 1)
        argv = recorded[0]["argv"]
        self.assertEqual(argv, expected)
        self.assertEqual(argv[0], r"C:\\Windows\\System32\\wt.exe")
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertNotIn("-w", argv)
        self.assertNotEqual(argv[2], "0")
        self.assertNotIn("--", argv)
        self.assertNotIn("nw", argv)
        self.assertNotIn("rename-window", argv)
        self.assertNotIn("^;", argv)
        self.assertEqual(argv.count(";"), 1)
        self.assertEqual(argv.count("-V"), 1)
        self.assertNotIn("-H", argv)
        self.assertNotIn("CREATE_NEW_CONSOLE", argv)
        self.assertIsNone(recorded[0]["cwd"])
        self.assertIsNone(recorded[0]["rect"])
        joined = " ".join(argv).lower()
        self.assertNotIn("ola-brain", joined)
        self.assertNotIn("side-chat", joined)
        self.assertNotIn("ultracode-shim", joined)
        self.assertNotIn("-p", argv)
        self.assertNotIn("-c", argv)
        self.assertNotIn("--append-system-prompt", argv)
        self.assertIn("--permission-mode", argv)
        self.assertIn("bypassPermissions", argv)
        self.assertIn("--allow-dangerously-skip-permissions", argv)
        # FileName is wt; ArgumentList is argv[1:]
        self.assertEqual(os.path.basename(str(argv[0]).replace("\\", "/")).lower().replace(".exe", ""), "wt")
        self.assertNotIn("wt", argv[1:])
        self.assertNotIn("wt.exe", [a.lower() for a in argv[1:]])

    def test_live_runner_popen_isolated_wt_once_no_console_no_move(self):
        seats = self._wt_seats()
        argv = isolated_wt_argv(self.thread, seats, wt=r"C:\\Windows\\System32\\wt.exe")
        proc = mock.Mock()
        proc.pid = 7
        with mock.patch("convoy.bringup.subprocess.Popen", return_value=proc) as popen, \
             mock.patch("convoy.bringup.os.name", "nt"), \
             mock.patch("convoy.bringup._tile_console") as tile:
            d = live_runner(argv, cwd=str(self.wt_g), rect={"x": 0, "y": 0, "w": 100, "h": 100})
        self.assertTrue(d["ok"])
        self.assertEqual(d["pid"], 7)
        popen.assert_called_once()
        got = popen.call_args[0][0]
        self.assertEqual(got, argv)
        kw = popen.call_args.kwargs
        self.assertNotIn("creationflags", kw)
        self.assertNotEqual(kw.get("creationflags"), CREATE_NEW_CONSOLE)
        self.assertNotIn("startupinfo", kw)
        tile.assert_not_called()
        self.assertNotIn("-w", got)
        self.assertNotIn("--", got)

    def test_live_runner_refuses_per_seat_argv(self):
        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                live_runner(["claude", "--resume", "sess-claude"], cwd=str(self.wt_c))
        popen.assert_not_called()

    def test_live_spawn_kwargs_windows_create_new_console(self):
        from unittest import mock
        self.assertEqual(CREATE_NEW_CONSOLE, 0x10)
        with mock.patch("convoy.bringup.os.name", "nt"):
            kw = live_spawn_kwargs()
        self.assertEqual(kw.get("creationflags"), CREATE_NEW_CONSOLE)
        self.assertEqual(kw.get("creationflags"), 0x10)
        self.assertNotIn("start_new_session", kw)

    def test_live_spawn_kwargs_posix_start_new_session(self):
        from unittest import mock
        with mock.patch("convoy.bringup.os.name", "posix"):
            kw = live_spawn_kwargs()
        self.assertTrue(kw.get("start_new_session"))
        self.assertNotIn("creationflags", kw)

    def test_isolated_wt_title_uses_seat_title_or_stable_fallback(self):
        seats = [
            {
                "to": "grok",
                "session_id": "sess-grok",
                "resume": "vendor-uuid-grok",
                "worktree": r"C:\\wt\\grok",
                "exe": r"C:\\abs\\grok.exe",
                "title": "lead-prreview",
            },
            {
                "to": "claude",
                "session_id": "sess-claude",
                "worktree": r"C:\\wt\\claude",
                "exe": r"C:\\abs\\claude.exe",
            },
        ]
        argv = isolated_wt_argv("demo", seats, wt=r"C:\\abs\\wt.exe")
        title_values = [argv[i + 1] for i, token in enumerate(argv) if token == "--title"]
        self.assertEqual(title_values[0], "lead-prreview")
        self.assertNotEqual(title_values[1], "claude-1")
        self.assertNotIn("grok-0", title_values)
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])

    def test_pids_for_resume_matches_resume_or_session_id(self):
        cmd = {
            101: r'C:\abs\grok.exe --resume vendor-uuid-1',
            102: r'C:\abs\grok.exe --session-id vendor-uuid-1',
            103: r'C:\abs\claude.exe --resume other',
            104: r'C:\abs\Grok Bot.exe --resume vendor-uuid-1',
        }
        with mock.patch("convoy.bringup.os.name", "nt"), \
             mock.patch("convoy.bringup._iter_processes", return_value=[(101, "grok.exe"), (102, "grok.exe"), (103, "claude.exe"), (104, "Grok Bot.exe")]), \
             mock.patch("convoy.bringup._read_command_line", side_effect=lambda pid: cmd.get(pid)):
            got = _pids_for_resume("vendor-uuid-1")
        self.assertEqual(got, {101, 102})

    def test_pids_for_resume_false_when_no_match(self):
        with mock.patch("convoy.bringup.os.name", "nt"), \
             mock.patch("convoy.bringup._iter_processes", return_value=[(201, "grok.exe")]), \
             mock.patch("convoy.bringup._read_command_line", return_value=r"C:\abs\grok.exe --resume other-uuid"):
            got = _pids_for_resume("vendor-uuid-1")
        self.assertEqual(got, set())

if __name__ == "__main__":
    unittest.main()


class LiveArgvEscapesWtSeparators(unittest.TestCase):
    def test_a_semicolon_in_a_pane_argument_is_escaped_for_wt(self):
        from convoy import bringup
        argv = ["wt", "--window", "new", "nt", "--title", "a;b", "-d", "C:/x", "grok.EXE", "do this; then that"]
        with mock.patch.object(bringup, "_resolve_wt_bin", return_value="wt.exe"):
            live = bringup._live_argv(argv)
        self.assertEqual(live[5], "a\\;b")
        self.assertEqual(live[-1], "do this\\; then that")
        self.assertEqual(live[0], "wt.exe")
        self.assertNotIn(";", "".join(live[1:]).replace("\\;", ""))

    def test_relaunch_prompt_carries_no_bare_semicolon(self):
        import inspect
        from convoy import relaunch
        src = inspect.getsource(relaunch.relaunch)
        self.assertNotIn('"; ', src)


class SeatModelRidesArgv(unittest.TestCase):
    """Live 2026-09-06: relaunching seat luna1 (declared gpt-5.6 / high) booted
    a codex pane reading `gpt-6-astra medium`, ~/.codex/config.toml's defaults,
    because only grok's model reached argv. Every harness with an evidenced
    model flag now carries the seat's model; codex effort rides -c."""

    def test_codex_seat_carries_model_and_effort_before_resume(self):
        argv = resume_argv({"to": "codex", "session_id": "luna1", "model": "gpt-5.6", "effort": "high", "resume": "vendor-uuid"})
        self.assertEqual(argv[1:], ["-m", "gpt-5.6", "-c", "model_reasoning_effort=high", "resume", "vendor-uuid"])

    def test_claude_seat_carries_model(self):
        argv = resume_argv({"to": "claude", "session_id": "c", "model": "claude-opus-5", "effort": "high", "resume": "uuid"})
        self.assertEqual(argv[1:], ["--model", "claude-opus-5", "--effort", "high", "--resume", "uuid"])

    def test_no_model_declared_passes_no_model(self):
        argv = resume_argv({"to": "codex", "session_id": "x", "resume": "uuid"})
        self.assertNotIn("-m", argv)
        self.assertNotIn("-c", argv)

    def test_model_flag_is_contract_evidenced(self):
        from convoy.harness_contract import model_flag, model_argv
        for hid, flag in (("grok", "-m"), ("codex", "-m"), ("claude", "--model"), ("agy", "--model"), ("hermes", "-m"), ("pi", "--model")):
            self.assertEqual(model_flag(hid)["flag"], flag, hid)
            self.assertTrue(str(model_flag(hid)["evidence"]).strip(), hid)
        self.assertEqual(model_flag("cursor-agent")["flag"], "--model")  # on this box since 2026-09-08
        self.assertEqual(model_argv("cursor-agent", "gpt-5.6-luna-high"), ["--model", "gpt-5.6-luna-high"])
        self.assertEqual(model_argv("codex", "  "), [])


class CursorAgentSeat(unittest.TestCase):
    """cursor-agent --help (2026.08.11, 2026-09-08): positional prompt, --model,
    --resume [chatId], --trust, --force. Dry argv carries model + resume + boot;
    only a live pane adds --trust --force, before the boot prompt."""

    def test_dry_argv_model_resume_boot(self):
        argv = resume_argv({"to": "cursor-agent", "session_id": "cur1", "model": "gpt-5.6-luna-high", "effort": "high",
                            "resume": "chat-123", "boot_prompt": "You are the new occupant of seat cur1"})
        self.assertEqual(argv[1:], ["--model", "gpt-5.6-luna-high", "--resume", "chat-123", "You are the new occupant of seat cur1"])
        self.assertNotIn("--trust", argv); self.assertNotIn("high", argv[1:-1])

    def test_live_flags_ride_before_the_boot_prompt(self):
        from convoy.bringup import _with_claude_live_flags
        live = _with_claude_live_flags(["C:/x/cursor-agent.CMD", "--model", "auto", "You are the new occupant of seat cur1"], "cursor-agent")
        self.assertEqual(live[1:], ["--model", "auto", "--trust", "--force", "You are the new occupant of seat cur1"])
        self.assertEqual(_with_claude_live_flags(["C:/x/cursor-agent.CMD", "--resume", "c"], "cursor-agent")[1:], ["--resume", "c", "--trust", "--force"])
        self.assertEqual(_with_claude_live_flags(["C:/x/codex.CMD", "resume", "c"], "codex")[1:], ["resume", "c"], "no live flags without contract evidence")

    def test_contract_flags_are_evidenced(self):
        from convoy.harness_contract import model_flag, live_flags, effort_contract
        self.assertEqual(model_flag("cursor-agent")["flag"], "--model")
        self.assertEqual(live_flags("cursor-agent"), ["--trust", "--force"])
        self.assertEqual(live_flags("codex"), [])
        self.assertEqual(effort_contract("cursor-agent")["mode"], "model-driven")


class CursorAgentEffortRidesTheModelId(unittest.TestCase):
    """cursor-agent has no effort flag; <model>-<effort> is emitted only when the
    account's catalog (`cursor-agent models`) lists it. Fixture catalog via
    CONVOY_CURSOR_MODELS_FILE so no vendor CLI runs in tests."""

    def setUp(self):
        import tempfile
        self.fx = Path(tempfile.mkdtemp()) / "models.txt"
        self.fx.write_text("Available models\n\nauto - Auto (default)\ngpt-5.6-luna-high - GPT-5.6 Luna 1M High\n"
                           "gpt-5.6-luna-xhigh - GPT-5.6 Luna 1M Extra High\ngpt-5.6-luna-xhigh-fast - Fast\n"
                           "gpt-5.5-extra-high - GPT-5.5 Extra High\nclaude-opus-5-low - Claude Opus 5 1M Low\n", encoding="utf-8")
        self._old = os.environ.get("CONVOY_CURSOR_MODELS_FILE")
        os.environ["CONVOY_CURSOR_MODELS_FILE"] = str(self.fx)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CONVOY_CURSOR_MODELS_FILE", None)
        else:
            os.environ["CONVOY_CURSOR_MODELS_FILE"] = self._old

    def test_compose_against_the_catalog(self):
        from convoy.cursor_models import compose, read_catalog
        cat = read_catalog()
        self.assertIn("gpt-5.6-luna-xhigh", cat)
        self.assertEqual(compose("gpt-5.6-luna", "xhigh", cat)["model"], "gpt-5.6-luna-xhigh")
        self.assertEqual(compose("gpt-5.6-luna-fast", "xhigh", cat)["model"], "gpt-5.6-luna-xhigh-fast")
        self.assertEqual(compose("gpt-5.5", "xhigh", cat)["model"], "gpt-5.5-extra-high", "alias xhigh -> extra-high when that is the listed id")
        r = compose("gpt-5.6-luna", "max", cat); self.assertEqual(r["model"], "gpt-5.6-luna"); self.assertFalse(r["applied"])
        r = compose("gpt-5.6-luna-high", "xhigh", cat); self.assertEqual(r["model"], "gpt-5.6-luna-high"); self.assertFalse(r["applied"])
        self.assertIsNone(compose("gpt-5.6-luna", None, cat)["applied"])
        self.assertFalse(compose("gpt-5.6-luna", "xhigh", None)["applied"])

    def test_argv_and_seat_row_carry_the_composed_id(self):
        argv = resume_argv({"to": "cursor-agent", "session_id": "c", "model": "gpt-5.6-luna", "effort": "xhigh", "resume": "chat-1"})
        self.assertEqual(argv[1:], ["--model", "gpt-5.6-luna-xhigh", "--resume", "chat-1"])
        argv = resume_argv({"to": "cursor-agent", "session_id": "c", "model": "gpt-5.6-luna", "effort": "max", "resume": "chat-1"})
        self.assertEqual(argv[1:], ["--model", "gpt-5.6-luna", "--resume", "chat-1"], "unlisted composition: bare model, never an invented id")
        root = Path(tempfile.mkdtemp()); ensure_id(root); bind(root, "t")
        row = seat(root, "cursor-agent", "cur-x", worktree=str(root), model="gpt-5.6-luna", effort="xhigh")
        self.assertTrue(row["effort_applied"]); self.assertEqual(row["model"], "gpt-5.6-luna", "the seat keeps what was declared")
        wt2 = Path(tempfile.mkdtemp()); wt3 = Path(tempfile.mkdtemp())
        row2 = seat(root, "cursor-agent", "cur-y", worktree=str(wt2), model="gpt-5.6-luna", effort="max")
        self.assertFalse(row2["effort_applied"])
        with self.assertRaises(ValueError):
            seat(root, "cursor-agent", "cur-z", worktree=str(wt3), model="gpt-5.6-luna", effort="banana")


class BootPromptReadsThreadOnce(unittest.TestCase):
    def test_handoff_equal_to_thread_is_named_once(self):
        from convoy.lifecycle import _boot_prompt
        root = Path(tempfile.mkdtemp())
        p = _boot_prompt(root, "s", "tok", "thread.md")
        self.assertEqual(p.count(str(root / "thread.md")), 1)
        self.assertNotIn(" and ", p.split(". Then run")[0])
        q = _boot_prompt(root, "s", "tok", "handoff.md")
        self.assertIn(" and " + str(root / "handoff.md"), q)


class PaneEnvIsTheUsersNotTheLaunchers(unittest.TestCase):
    """Live 2026-09-10: a pane launched with the launcher's env minus SHELL still
    failed cursor-agent's hooks (Git-first PATH); the registry-built env passed."""

    def test_windows_pane_env_comes_from_the_registry_plus_process_vars_and_convoy_settings(self):
        from convoy.bringup import pane_env
        launcher = {"PATH": "C:/Git/usr/bin;C:/Python314", "SHELL": "C:/Git/usr/bin/bash.exe", "MSYSTEM": "MINGW64",
                    "USERPROFILE": "C:/Users/m", "TEMP": "C:/t", "CONVOY_HOME": "C:/Users/m/.convoy", "PYTHONPATH": "src"}
        reg = {"PATH": "C:/Windows;C:/Python314", "TEMP": "C:/regtemp"}
        with mock.patch.object(os, "name", "nt"):
            env = pane_env(launcher, registry=reg)
        self.assertEqual(env["PATH"], "C:/Windows;C:/Python314", "PATH is the registry's, never the launcher's")
        self.assertNotIn("SHELL", env); self.assertNotIn("MSYSTEM", env); self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["USERPROFILE"], "C:/Users/m", "logon process vars ride along")
        with mock.patch.object(os, "name", "nt"):
            up = pane_env({"SYSTEMROOT": "C:/Windows", "PATH": "x"}, registry={"PATH": "y"})
        self.assertEqual(up.get("SystemRoot"), "C:/Windows", "os.environ uppercases keys on Windows; the copy must not care")
        self.assertEqual(env["TEMP"], "C:/regtemp", "registry wins where both exist")
        self.assertEqual(env["CONVOY_HOME"], "C:/Users/m/.convoy", "Convoy's own settings ride along")
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(pane_env(launcher)["SHELL"], launcher["SHELL"])
