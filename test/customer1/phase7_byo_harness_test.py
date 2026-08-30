import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.bringup import (
    _absolute_harness,
    isolated_wt_argv,
    live_runner,
)


ROOT = Path(__file__).resolve().parents[2]
FAKES = (ROOT / "test" / "fakes").resolve()
GROK = str(FAKES / "grok")
CLAUDE = str(FAKES / "claude")
WT = str(FAKES / "wt")
CODEX = str(FAKES / "codex")


def _count_tests(suite):
    n = 0
    for x in suite:
        if isinstance(x, unittest.TestSuite):
            n += _count_tests(x)
        else:
            n += 1
    return n


class Phase7ByoHarness(unittest.TestCase):
    def setUp(self):
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())
        self.wt_g2 = Path(tempfile.mkdtemp())
        for name, path in (("grok", GROK), ("claude", CLAUDE), ("wt", WT), ("codex", CODEX)):
            self.assertTrue(Path(path).is_file(), name)
            self.assertTrue(os.access(path, os.X_OK), name)

    def _grok_claude(self):
        return [
            {"to": "grok", "session_id": "sess-grok", "worktree": str(self.wt_g), "exe": GROK},
            {"to": "claude", "session_id": "sess-claude", "worktree": str(self.wt_c), "exe": CLAUDE},
        ]

    def test_fakes_print_json_exit_zero_never_ola_brain(self):
        import subprocess
        for name, path in (("grok", GROK), ("claude", CLAUDE), ("wt", WT), ("codex", CODEX)):
            blob = Path(path).read_text(encoding="utf-8").lower()
            self.assertNotIn("ola-brain", blob, name)
            self.assertNotIn("side-chat", blob, name)
            self.assertNotIn("ultracode-shim", blob, name)
            extra = ["--permission-mode", "bypassPermissions"] if name == "claude" else ["--resume", "sess"]
            r = subprocess.run([path, *extra], capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            line = r.stdout.strip().splitlines()[-1]
            data = json.loads(line)
            self.assertTrue(data["ok"])
            self.assertEqual(data["harness"], name)
            self.assertIn("argv", data)
        # grok stub must not require -p / -c
        r = subprocess.run([GROK], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(data["ok"])
        self.assertEqual(data["harness"], "grok")

    def test_isolated_wt_argv_n2_real_posix_stubs(self):
        seats = self._grok_claude()
        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            argv = isolated_wt_argv("customer1", seats, wt=WT)
        popen.assert_not_called()
        self.assertEqual(argv[0], WT)
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertIn(GROK, argv)
        self.assertIn(CLAUDE, argv)
        self.assertTrue(os.path.isabs(GROK))
        self.assertTrue(os.path.isabs(CLAUDE))
        self.assertEqual(argv.count("-V"), 1)
        self.assertNotIn("-H", argv)
        self.assertEqual(argv.count(";"), 1)
        self.assertNotIn("--", argv)
        self.assertNotIn("-w", argv)
        self.assertNotIn("0", argv[1:4])
        joined = " ".join(argv).lower()
        self.assertNotIn("ola-brain", joined)
        self.assertNotIn("side-chat", joined)
        self.assertNotIn("-p", argv)
        self.assertNotIn("-c", argv)
        self.assertIn(str(self.wt_g), argv)
        self.assertIn(str(self.wt_c), argv)
        self.assertIn("--resume", argv)
        self.assertIn("sess-grok", argv)
        self.assertIn("sess-claude", argv)
        self.assertIn("--permission-mode", argv)

    def test_which_path_fakes_resolves_grok_stub(self):
        with mock.patch.dict(os.environ, {"PATH": str(FAKES)}):
            got = _absolute_harness("grok")
        self.assertTrue(os.path.isabs(got))
        self.assertEqual(Path(got).resolve(), Path(GROK).resolve())
        self.assertNotEqual(got, 0)
        self.assertNotEqual(str(got), "0")
        self.assertNotIn("ola-brain", got.lower())

    def test_which_path_without_fakes_missing_not_invented_as_zero(self):
        empty = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"PATH": empty}):
            got = _absolute_harness("grok")
        self.assertNotEqual(got, 0)
        self.assertNotEqual(got, "0")
        self.assertIsNotNone(got)
        self.assertEqual(got, "grok")
        self.assertFalse(os.path.isabs(got))

    def test_live_runner_popen_mocked_no_real_wt(self):
        argv = isolated_wt_argv("customer1", self._grok_claude(), wt=WT)
        proc = mock.Mock()
        proc.pid = 11
        with mock.patch("convoy.bringup.subprocess.Popen", return_value=proc) as popen:
            d = live_runner(argv)
        popen.assert_called_once()
        self.assertTrue(d["ok"])
        self.assertEqual(d["pid"], 11)
        got = popen.call_args[0][0]
        self.assertEqual(got[0], WT)
        self.assertIn("--window", got)
        self.assertNotIn("-w", got)
        self.assertNotIn("--", got)
        joined = " ".join(got).lower()
        self.assertNotIn("ola-brain", joined)

    def test_two_grok_stubs_different_worktrees_two_panes(self):
        seats = [
            {"to": "grok", "session_id": "sess-1", "worktree": str(self.wt_g), "exe": GROK},
            {"to": "grok", "session_id": "sess-2", "worktree": str(self.wt_g2), "exe": GROK},
        ]
        with mock.patch("convoy.bringup.subprocess.Popen") as popen:
            argv = isolated_wt_argv("customer1", seats, wt=WT)
        popen.assert_not_called()
        self.assertEqual(argv.count("--resume"), 2)
        self.assertEqual(argv.count(GROK), 2)
        self.assertEqual(argv.count(";"), 1)
        self.assertEqual(argv.count("-V"), 1)
        self.assertNotIn("-H", argv)
        self.assertIn(str(self.wt_g), argv)
        self.assertIn(str(self.wt_g2), argv)
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertNotIn("--", argv)
        self.assertNotIn("-w", argv)
        self.assertNotIn("ola-brain", " ".join(argv).lower())

    def test_refuse_ola_brain_as_exe(self):
        seats = [{
            "to": "grok",
            "session_id": "sess-x",
            "worktree": str(self.wt_g),
            "exe": "/usr/local/bin/ola-brain",
        }]
        with self.assertRaises(ValueError) as ctx:
            isolated_wt_argv("customer1", seats, wt=WT)
        self.assertIn("ola-brain", str(ctx.exception).lower())
        with self.assertRaises(ValueError):
            _absolute_harness("ola-brain")
        with self.assertRaises(ValueError):
            _absolute_harness("/usr/local/bin/ola-brain")
        with self.assertRaises(ValueError):
            _absolute_harness("ola-brain.exe")

    def test_readme_documents_star_test_py_not_default_pattern(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("test/customer1", readme)
        self.assertIn("*_test.py", readme)
        self.assertFalse(Path(__file__).name.startswith("test"))
        self.assertTrue(Path(__file__).name.endswith("_test.py"))
        start = str(Path(__file__).resolve().parent)
        default = unittest.defaultTestLoader.discover(start, pattern="test*.py")
        star = unittest.defaultTestLoader.discover(start, pattern="*_test.py")
        self.assertGreater(_count_tests(star), _count_tests(default))


if __name__ == "__main__":
    unittest.main()
