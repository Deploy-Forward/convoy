import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.bringup import bring_up, ensure_first_run, ensure_interactive_path, isolated_wt_argv, resume_argv, _with_claude_live_flags, _pane_seats, CONVOY_PATH_BEGIN



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
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue()
    data = json.loads(raw) if raw.strip() else None
    return rc, data


class Phase7FirstRun(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "thread.md").write_text("SECRET_THREAD_BYTES")
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("SECRET_BRIEF")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())
        self.wt_x = Path(tempfile.mkdtemp())
        self.thread = "customer1"
        self.cid = ensure_id(self.root)
        bind(self.root, self.thread)
        self.g = seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok", resume="sess-grok")
        self.c = seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="Fable 5", resume="sess-claude")
        # Snapshot real home BEFORE patching Path.home (classmethod is process-global).
        self.real_home = Path(os.path.expanduser("~"))
        self.real_home_settings = self.real_home / ".claude" / "settings.json"
        self._real_home_existed = self.real_home_settings.is_file()
        self._real_home_before = self.real_home_settings.read_bytes() if self._real_home_existed else None
        self.fake_home = Path(tempfile.mkdtemp())
        self._home_patcher = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home_patcher.start()
        self.addCleanup(self._home_patcher.stop)
        self.addCleanup(self._assert_real_home_untouched)

    def _settings(self, wt):
        return Path(wt) / ".claude" / "settings.json"

    def _home_settings(self):
        return self.fake_home / ".claude" / "settings.json"

    def _assert_real_home_untouched(self):
        if self._real_home_existed:
            self.assertEqual(self.real_home_settings.read_bytes(), self._real_home_before)
        else:
            self.assertFalse(self.real_home_settings.exists())

    def test_ensure_first_run_creates_claude_settings(self):
        wt = Path(tempfile.mkdtemp())
        self.assertFalse(self._settings(wt).exists())
        card = ensure_first_run({"to": "claude", "worktree": str(wt)})
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("prepared"))
        self.assertTrue(card.get("wrote"))
        path = self._settings(wt)
        self.assertTrue(path.is_file())
        self.assertEqual(card.get("settings"), str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIs(data["skipDangerousModePermissionPrompt"], True)
        self.assertEqual(data["permissions"]["defaultMode"], "bypassPermissions")
        blob = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("ola-brain", blob)
        self.assertNotIn("side-chat", blob)
        self.assertNotIn("--append-system-prompt", blob)
        self.assertTrue(card.get("home_written"))
        home_path = self._home_settings()
        self.assertEqual(card.get("settings_home"), str(home_path))
        self.assertTrue(card.get("trust_written"))
        self.assertEqual(card.get("trust_settings_home"), str(self.fake_home / ".claude.json"))
        self.assertTrue(home_path.is_file())
        home = json.loads(home_path.read_text(encoding="utf-8"))
        self.assertIs(home["skipDangerousModePermissionPrompt"], True)
        self.assertNotIn("defaultMode", home.get("permissions") or {})
        self.assertNotIn("permissions", home)
        state = json.loads((self.fake_home / ".claude.json").read_text(encoding="utf-8"))
        projects = state.get("projects") or {}
        self.assertIn(str(wt.resolve()), projects)
        self.assertIs(projects[str(wt.resolve())]["hasTrustDialogAccepted"], True)

    def test_ensure_first_run_merges_existing_keys(self):
        wt = Path(tempfile.mkdtemp())
        claude_dir = wt / ".claude"
        claude_dir.mkdir()
        existing = {
            "env": {"FOO": "keep-me"},
            "permissions": {"allow": ["Read"], "deny": ["WebSearch"]},
            "other": 42,
        }
        self._settings(wt).write_text(json.dumps(existing), encoding="utf-8")
        card = ensure_first_run({"to": "claude", "worktree": str(wt)})
        self.assertTrue(card.get("ok"))
        data = json.loads(self._settings(wt).read_text(encoding="utf-8"))
        self.assertEqual(data["env"], {"FOO": "keep-me"})
        self.assertEqual(data["other"], 42)
        self.assertEqual(data["permissions"]["allow"], ["Read"])
        self.assertEqual(data["permissions"]["deny"], ["WebSearch"])
        self.assertEqual(data["permissions"]["defaultMode"], "bypassPermissions")
        self.assertIs(data["skipDangerousModePermissionPrompt"], True)

    def test_ensure_first_run_writes_home_skip_key_not_default_mode(self):
        wt = Path(tempfile.mkdtemp())
        home_dir = self.fake_home / ".claude"
        home_dir.mkdir()
        existing = {
            "env": {"KEEP": "yes"},
            "other": 1,
            "permissions": {"allow": ["Bash"]},
        }
        (home_dir / "settings.json").write_text(json.dumps(existing), encoding="utf-8")
        card = ensure_first_run({"to": "claude", "worktree": str(wt)})
        self.assertTrue(card.get("ok"))
        self.assertTrue(self._settings(wt).is_file())
        proj = json.loads(self._settings(wt).read_text(encoding="utf-8"))
        self.assertIs(proj["skipDangerousModePermissionPrompt"], True)
        self.assertEqual(proj["permissions"]["defaultMode"], "bypassPermissions")
        home_path = self._home_settings()
        self.assertTrue(home_path.is_file())
        self.assertTrue(card.get("home_written"))
        self.assertEqual(card.get("settings_home"), str(home_path))
        self.assertEqual(card.get("settings"), str(self._settings(wt)))
        self.assertTrue(card.get("trust_written"))
        self.assertEqual(card.get("trust_settings_home"), str(self.fake_home / ".claude.json"))
        home = json.loads(home_path.read_text(encoding="utf-8"))
        self.assertIs(home["skipDangerousModePermissionPrompt"], True)
        self.assertEqual(home["env"], {"KEEP": "yes"})
        self.assertEqual(home["other"], 1)
        self.assertEqual(home["permissions"]["allow"], ["Bash"])
        self.assertNotIn("defaultMode", home.get("permissions") or {})
        self.assertFalse((wt.parent / ".claude" / "settings.json").exists())

    def test_ensure_first_run_writes_trust_for_both_windows_slash_spellings(self):
        wt = Path(tempfile.mkdtemp())
        variants = [r"C:\Users\marco\ola\da-integration", "C:/Users/marco/ola/da-integration"]
        with mock.patch("convoy.bringup._project_path_variants", return_value=variants):
            card = ensure_first_run({"to": "claude", "worktree": str(wt)})
        self.assertTrue(card.get("ok"))
        state = json.loads((self.fake_home / ".claude.json").read_text(encoding="utf-8"))
        projects = state.get("projects") or {}
        self.assertIn(variants[0], projects)
        self.assertIn(variants[1], projects)
        self.assertIs(projects[variants[0]]["hasTrustDialogAccepted"], True)
        self.assertIs(projects[variants[1]]["hasTrustDialogAccepted"], True)

    def test_ensure_first_run_refuses_when_worktree_is_home(self):
        card = ensure_first_run({"to": "claude", "worktree": str(self.fake_home)})
        self.assertFalse(card.get("ok"))
        self.assertFalse(card.get("prepared"))
        self.assertFalse(card.get("wrote"))
        self.assertFalse(card.get("home_written"))
        self.assertFalse(card.get("trust_written"))
        self.assertIsNone(card.get("settings_home"))
        self.assertIsNone(card.get("trust_settings_home"))
        self.assertFalse(self._home_settings().exists())
        err = str(card.get("error") or "").lower()
        self.assertTrue("home" in err)

    def test_ensure_first_run_grok_codex_noop(self):
        for to in ("grok", "codex"):
            wt = Path(tempfile.mkdtemp())
            card = ensure_first_run({"to": to, "worktree": str(wt)})
            self.assertTrue(card.get("ok"))
            self.assertTrue(card.get("prepared"))
            self.assertFalse(card.get("wrote"))
            self.assertFalse(self._settings(wt).exists())
            self.assertIsNone(card.get("settings"))
            self.assertFalse(card.get("home_written"))
            self.assertIsNone(card.get("settings_home"))
            self.assertFalse(card.get("trust_written"))
            self.assertIsNone(card.get("trust_settings_home"))
            self.assertFalse(self._home_settings().exists())
            self.assertFalse((self.fake_home / ".claude").exists())
            self.assertTrue(card.get("path_ok"))
            if os.name == "nt":
                # WT inherits user PATH; bashrc ungate is POSIX-only
                self.assertEqual(card.get("path_host"), "windows-user")
                self.assertIsNone(card.get("path_bashrc"))
            else:
                self.assertEqual(card.get("path_host"), "bash-interactive")
                self.assertEqual(card.get("path_bashrc"), str(self.fake_home / ".bashrc"))

    def test_ensure_interactive_path_writes_bashrc_when_profile_only(self):
        profile = self.fake_home / ".profile"
        profile.write_text(
            'if [ -d "$HOME/.local/bin" ] ; then PATH="$HOME/.local/bin:$PATH"; fi\n',
            encoding="utf-8",
        )
        bashrc = self.fake_home / ".bashrc"
        if bashrc.exists():
            bashrc.unlink()
        # bashrc ungate is POSIX-only; pin that branch on every OS.
        with mock.patch("convoy.bringup.os.name", "posix"):
            card = ensure_interactive_path()
            again = ensure_interactive_path()
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("path_written"))
        self.assertTrue(card.get("path_ok"))
        self.assertEqual(card.get("path_host"), "bash-interactive")
        self.assertEqual(card.get("path_bashrc"), str(bashrc))
        blob = bashrc.read_text(encoding="utf-8")
        self.assertIn(CONVOY_PATH_BEGIN, blob)
        self.assertIn("$HOME/.local/bin", blob)
        self.assertIn("$HOME/.grok/bin", blob)
        self.assertNotIn("ola-brain", blob)
        self.assertTrue(again.get("path_ok"))
        self.assertFalse(again.get("path_written"))
        self.assertEqual(blob.count(CONVOY_PATH_BEGIN), 1)

    def test_ensure_interactive_path_is_idempotent_on_existing_block(self):
        bashrc = self.fake_home / ".bashrc"
        bashrc.write_text("export FOO=keep\n\n" + CONVOY_PATH_BEGIN + "\n# <<< convoy harness PATH <<<\n", encoding="utf-8")
        before = bashrc.read_text(encoding="utf-8")
        # bashrc ungate is POSIX-only; pin that branch on every OS.
        with mock.patch("convoy.bringup.os.name", "posix"):
            card = ensure_interactive_path()
        self.assertTrue(card.get("path_ok"))
        self.assertFalse(card.get("path_written"))
        self.assertEqual(bashrc.read_text(encoding="utf-8"), before)
        self.assertIn("FOO=keep", before)

    def test_dry_run_bring_up_calls_ensure_first_run_no_popen_wt(self):
        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            rc, d = _run(self.root, "bring-up", "--dry-run")
        popen.assert_not_called()
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        by = {w["to"]: w for w in d["windows"]}
        self.assertTrue(by["claude"]["first_run"]["prepared"])
        self.assertTrue(by["grok"]["first_run"]["prepared"])
        self.assertTrue(self._settings(self.wt_c).is_file())
        data = json.loads(self._settings(self.wt_c).read_text(encoding="utf-8"))
        self.assertIs(data["skipDangerousModePermissionPrompt"], True)
        self.assertEqual(data["permissions"]["defaultMode"], "bypassPermissions")
        self.assertFalse(self._settings(self.wt_g).exists())
        _native_resume(by["claude"]["argv"], "claude", "sess-claude")
        _native_resume(by["grok"]["argv"], "grok", "sess-grok", model="explicit-grok")
        self.assertTrue(by["claude"]["first_run"]["home_written"])
        self.assertEqual(by["claude"]["first_run"]["settings_home"], str(self._home_settings()))
        self.assertEqual(by["claude"]["first_run"]["settings"], str(self._settings(self.wt_c)))
        self.assertTrue(by["claude"]["first_run"]["trust_written"])
        self.assertEqual(by["claude"]["first_run"]["trust_settings_home"], str(self.fake_home / ".claude.json"))
        self.assertFalse(by["grok"]["first_run"].get("home_written"))
        self.assertIsNone(by["grok"]["first_run"].get("settings_home"))
        self.assertFalse(by["grok"]["first_run"].get("trust_written"))
        self.assertIsNone(by["grok"]["first_run"].get("trust_settings_home"))
        home = json.loads(self._home_settings().read_text(encoding="utf-8"))
        self.assertIs(home["skipDangerousModePermissionPrompt"], True)
        self.assertNotIn("defaultMode", home.get("permissions") or {})
        for w in d["windows"]:
            joined = " ".join(str(a) for a in w["argv"])
            self.assertNotIn("ola-brain", joined)
            self.assertNotIn("side-chat", joined)
            self.assertNotIn("-p", w["argv"])
            self.assertNotIn("-c", w["argv"])
            self.assertNotIn("--append-system-prompt", w["argv"])
            self.assertNotEqual(os.path.basename(str(w["argv"][0])).lower(), "wt.exe")

    def test_lib_bring_up_dry_prepares_first_run_without_runner(self):
        called = {"n": 0}

        def boom(*a, **k):
            called["n"] += 1
            raise AssertionError("live runner must not run")

        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            d = bring_up(self.root)
        popen.assert_not_called()
        self.assertTrue(d["ok"])
        self.assertEqual(called["n"], 0)
        by = {w["to"]: w for w in d["windows"]}
        self.assertTrue(by["claude"]["first_run"]["prepared"])
        self.assertTrue(self._settings(self.wt_c).is_file())
        self.assertFalse(self._settings(self.wt_g).exists())
        self.assertTrue(by["claude"]["first_run"]["home_written"])
        self.assertEqual(by["claude"]["first_run"]["settings_home"], str(self._home_settings()))
        self.assertTrue(by["claude"]["first_run"]["trust_written"])
        self.assertEqual(by["claude"]["first_run"]["trust_settings_home"], str(self.fake_home / ".claude.json"))
        self.assertFalse(by["grok"]["first_run"].get("home_written"))

    def test_resume_argv_unchanged_native_shape(self):
        _native_resume(resume_argv(self.g), "grok", "sess-grok", model="explicit-grok")
        _native_resume(resume_argv(self.c), "claude", "sess-claude")


class Phase7IsolatedWtArgv(unittest.TestCase):
    def _seats(self, n):
        seats = []
        names = ("grok", "claude", "codex", "agy")
        for i in range(n):
            to = names[i % len(names)]
            seats.append({
                "to": to,
                "session_id": "sess-%s-%d" % (to, i),
                # vendor resume id; session_id alone omits --resume by contract
                "resume": "sess-%s-%d" % (to, i),
                "worktree": r"C:\wt\%s-%d" % (to, i),
                "exe": r"C:\abs\%s.exe" % to,
            })
        return seats

    def _inners_after_d(self, argv):
        inners = []
        i = 0
        while i < len(argv):
            if argv[i] == "-d" and i + 2 < len(argv):
                chunk = []
                i += 2
                while i < len(argv) and argv[i] != ";":
                    chunk.append(argv[i])
                    i += 1
                inners.append(chunk)
                continue
            i += 1
        return inners

    def test_named_window_nt_first_n3_vh_splits(self):
        seats = self._seats(3)
        argv = isolated_wt_argv("customer1", seats, wt=r"C:\Windows\System32\wt.exe")
        self.assertEqual(argv[0], r"C:\Windows\System32\wt.exe")
        self.assertEqual(argv[1], "--window")
        self.assertEqual(argv[2], "new")
        self.assertNotIn("-w", argv)
        self.assertNotEqual(argv[2], "0")
        self.assertIn(argv[3], ("nt", "new-tab"))
        self.assertNotIn("nw", argv)
        self.assertNotIn("rename-window", argv)
        self.assertNotIn("--", argv)
        self.assertEqual(argv.count(";"), 2)
        self.assertEqual(argv.count("-V"), 1)
        self.assertEqual(argv.count("-H"), 1)
        self.assertLess(argv.index("-V"), argv.index("-H"))
        self.assertNotIn("^;", argv)
        self.assertNotIn("--append-system-prompt", argv)
        self.assertNotIn("-p", argv)
        self.assertNotIn("-c", argv)
        joined = " ".join(argv).lower()
        self.assertNotIn("ola-brain", joined)
        self.assertNotIn("side-chat", joined)
        inners = self._inners_after_d(argv)
        self.assertEqual(len(inners), 3)
        for inner in inners:
            self.assertTrue(inner)
            self.assertTrue(os.path.isabs(inner[0].replace("\\", "/")) or inner[0][1:3] in (":\\", ":/"))
            if "codex" in inner[0].lower():
                # codex resumes via subcommand, not --resume
                self.assertIn("resume", inner)
                self.assertNotIn("--resume", inner)
            else:
                self.assertIn("--resume", inner)
        claude_inner = [i for i in inners if "claude" in i[0].lower()][0]
        self.assertIn("--permission-mode", claude_inner)
        self.assertIn("bypassPermissions", claude_inner)
        self.assertIn("--allow-dangerously-skip-permissions", claude_inner)
        self.assertEqual(claude_inner.count("--allow-dangerously-skip-permissions"), 1)
        grok_inner = [i for i in inners if "grok" in i[0].lower()][0]
        self.assertNotIn("--permission-mode", grok_inner)
        self.assertNotIn("--allow-dangerously-skip-permissions", grok_inner)

    def test_claude_live_flags_do_not_duplicate(self):
        once = _with_claude_live_flags(["claude", "--resume", "s"], "claude")
        twice = _with_claude_live_flags(once, "claude")
        self.assertEqual(once.count("--allow-dangerously-skip-permissions"), 1)
        self.assertEqual(twice.count("--allow-dangerously-skip-permissions"), 1)
        self.assertEqual(once.count("--permission-mode"), 1)
        self.assertEqual(twice.count("--permission-mode"), 1)
        self.assertIn("bypassPermissions", twice)
        already = _with_claude_live_flags(
            ["claude", "--resume", "s", "--allow-dangerously-skip-permissions", "--permission-mode", "bypassPermissions"],
            "claude",
        )
        self.assertEqual(already.count("--allow-dangerously-skip-permissions"), 1)
        self.assertEqual(already.count("--permission-mode"), 1)
        grok = _with_claude_live_flags(["grok", "--resume", "s"], "grok")
        self.assertEqual(grok, ["grok", "--resume", "s"])

    def test_refuse_w0_and_nw_first(self):
        seats = self._seats(1)
        with self.assertRaises(ValueError) as ctx:
            isolated_wt_argv("0", seats)
        self.assertIn("0", str(ctx.exception).lower())
        with self.assertRaises(ValueError):
            isolated_wt_argv(0, seats)
        argv = isolated_wt_argv("customer1", seats, wt=r"C:\abs\wt.exe")
        self.assertEqual(argv[1], "--window")
        self.assertEqual(argv[2], "new")
        self.assertNotIn("-w", argv)
        self.assertIn(argv[3], ("nt", "new-tab"))

    def test_no_live_spawn(self):
        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            argv = isolated_wt_argv("t", self._seats(2), wt=r"C:\abs\wt.exe")
        popen.assert_not_called()
        self.assertIn(";", argv)
        self.assertEqual(argv.count("-V"), 1)
        self.assertNotIn("--", argv)
        self.assertIn("--window", argv)
        self.assertEqual(argv[argv.index("--window") + 1], "new")

    def test_n1_one_nt_no_split(self):
        argv = isolated_wt_argv("customer1", self._seats(1), wt=r"C:\\abs\\wt.exe")
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertNotIn(";", argv)
        self.assertNotIn("-V", argv)
        self.assertNotIn("-H", argv)
        self.assertNotIn("split-pane", argv)
        self.assertNotIn("--", argv)
        self.assertNotIn("-w", argv)

    def test_duplicate_to_one_pane(self):
        exe = r"C:\\abs\\grok.exe"
        same_wt = r"C:\\wt\\grok-same"
        collapsed = [
            {"to": "grok", "session_id": "sess-a", "resume": "sess-a", "worktree": same_wt, "exe": exe},
            {"to": "grok", "session_id": "sess-b", "resume": "sess-b", "worktree": same_wt, "exe": exe},
        ]
        panes = _pane_seats(collapsed)
        self.assertEqual(len(panes), 1)
        argv = isolated_wt_argv("customer1", collapsed, wt=r"C:\\abs\\wt.exe")
        self.assertEqual(argv.count("--resume"), 1)
        self.assertNotIn(";", argv)
        self.assertNotIn("split-pane", argv)

        kept = [
            {"to": "grok", "session_id": "sess-1", "resume": "sess-1", "worktree": "wt-grok-1", "exe": exe},
            {"to": "grok", "session_id": "sess-2", "resume": "sess-2", "worktree": "wt-grok-2", "exe": exe},
        ]
        panes = _pane_seats(kept)
        self.assertEqual(len(panes), 2)
        self.assertEqual([p["worktree"] for p in panes], ["wt-grok-1", "wt-grok-2"])
        argv2 = isolated_wt_argv("customer1", kept, wt=r"C:\\abs\\wt.exe")
        self.assertEqual(argv2.count("--resume"), 2)
        self.assertEqual(argv2.count(";"), 1)
        self.assertEqual(argv2.count("-V"), 1)
        self.assertNotIn("-H", argv2)
        self.assertIn("wt-grok-1", argv2)
        self.assertIn("wt-grok-2", argv2)

    def test_n3_claude_grok_grok_argv(self):
        seats = [
            {"to": "claude", "session_id": "sess-claude", "resume": "sess-claude", "worktree": r"C:\\wt\\claude", "exe": r"C:\\abs\\claude.exe"},
            {"to": "grok", "session_id": "sess-grok-1", "resume": "sess-grok-1", "worktree": "wt-grok-1", "exe": r"C:\\abs\\grok.exe"},
            {"to": "grok", "session_id": "sess-grok-2", "resume": "sess-grok-2", "worktree": "wt-grok-2", "exe": r"C:\\abs\\grok.exe"},
        ]
        argv = isolated_wt_argv("customer1", seats, wt=r"C:\\abs\\wt.exe")
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertEqual(argv.count("--resume"), 3)
        semis = [i for i, a in enumerate(argv) if a == ";"]
        self.assertEqual(len(semis), 2)
        self.assertEqual(argv[semis[0]:semis[0] + 3], [";", "split-pane", "-V"])
        self.assertEqual(argv[semis[1]:semis[1] + 3], [";", "split-pane", "-H"])
        self.assertNotIn("-w", argv)
        self.assertNotIn("--", argv)
        self.assertIn("wt-grok-1", argv)
        self.assertIn("wt-grok-2", argv)

    def test_refuse_ultracode_shim_exe(self):
        seats = [{
            "to": "ultracode-shim",
            "session_id": "sess-x",
            "worktree": r"C:\\wt\\x",
            "exe": r"C:\\abs\\ultracode-shim.exe",
        }]
        with self.assertRaises(ValueError):
            isolated_wt_argv("customer1", seats, wt=r"C:\\abs\\wt.exe")


if __name__ == "__main__":
    unittest.main()
