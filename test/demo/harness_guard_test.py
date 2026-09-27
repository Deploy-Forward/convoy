"""The suite never starts a real harness CLI (test/harness_guard.py).

A harmless stand-in, an echo script named claude, sits in a temp folder outside
test/fakes and plays the operator's real binary. However a test starts it, the
guard refuses the spawn and fails that test. The fakes and plain Python still
run. Only the stand-in's folder is on PATH while it is spawned, so a broken
guard runs the stand-in or finds nothing: never a real binary.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FAKES = Path(__file__).resolve().parents[1] / "fakes"
WINDOWS = os.name == "nt"


def _run(command, **kw):
    return subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, **kw)


def _in_a_test(spawn):
    """Run spawn() inside a throwaway test, the way the suite runs one.

    Returns what the spawn raised (or None), its exit code (or None), and the test's failures.
    """
    seen = {"raised": None, "code": None}

    class Throwaway(unittest.TestCase):
        def runTest(self):
            try:
                seen["code"] = spawn().returncode
            except OSError as e:
                seen["raised"] = type(e).__name__

    result = unittest.TestResult()
    Throwaway().run(result)
    return seen["raised"], seen["code"], [text for _test, text in result.failures + result.errors]


class TheSuiteNeverStartsARealHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="guard-standin-")
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        if WINDOWS:
            self.standin = self.dir / "claude.cmd"
            self.standin.write_text("@echo stand-in\n", encoding="utf-8")
        else:
            self.standin = self.dir / "claude"
            self.standin.write_text("#!/bin/sh\necho stand-in\n", encoding="utf-8")
            self.standin.chmod(0o755)

    def test_a_standin_outside_the_fakes_is_refused_and_fails_its_test(self):
        quoted = '"%s"' % self.standin if WINDOWS else shlex.quote(str(self.standin))
        ways = {
            "argv": lambda: _run([str(self.standin)]),
            "a bare name, first on PATH": lambda: _run(["claude"], cwd=str(self.dir)),
            "shell=True": lambda: _run(quoted, shell=True, cwd=str(self.dir)),
        }
        for way, spawn in ways.items():
            with self.subTest(way=way), mock.patch.dict(os.environ, {"PATH": str(self.dir)}):
                raised, code, failures = _in_a_test(spawn)
                self.assertEqual(raised, "PermissionError", "the spawn is refused")
                self.assertIsNone(code, "the stand-in never ran")
                self.assertEqual(len(failures), 1, "the test that tried fails")
                self.assertIn(str(self.dir).lower(), failures[0].lower(), "and names what it tried")

    def test_the_fakes_and_plain_python_still_run(self):
        fake = FAKES / ("claude.cmd" if WINDOWS else "claude")
        ways = {
            "a fake in test/fakes": lambda: _run([str(fake), "--version"]),
            "python -c pass": lambda: _run([sys.executable, "-c", "pass"]),
        }
        for way, spawn in ways.items():
            with self.subTest(way=way):
                self.assertEqual(_in_a_test(spawn), (None, 0, []))


if __name__ == "__main__":
    unittest.main()
