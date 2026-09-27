"""Red contracts for test entrypoints that must not touch the live Convoy home."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestHomeIsolationContract(unittest.TestCase):
    def _probe(self, code: str, *, home: str | None) -> dict[str, object]:
        env = os.environ.copy()
        if home is None:
            env.pop("CONVOY_HOME", None)
        else:
            env["CONVOY_HOME"] = home
        env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "src"), str(ROOT / "test")))
        env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_runner_rejects_or_redirects_preexisting_non_temp_home(self):
        # The sentinel is never created. Discovery is replaced with an empty
        # suite, so this probes the runner's guard without running any tests.
        sentinel = str(ROOT / "convoy-isolation-sentinel-never-create")
        code = (
            "import json, os, runpy, unittest\n"
            "unittest.defaultTestLoader.discover = lambda *a, **k: unittest.TestSuite()\n"
            "try:\n"
            "    runpy.run_path('test/run.py', run_name='__main__')\n"
            "except SystemExit as e:\n"
            "    rc = int(e.code or 0)\n"
            "print(json.dumps({'home': os.environ.get('CONVOY_HOME'), 'rc': rc}))\n"
        )
        result = self._probe(code, home=sentinel)
        self.assertFalse(Path(sentinel).exists())
        self.assertTrue(
            result["rc"] != 0 or result["home"] != sentinel,
            "test/run.py must refuse or redirect a preexisting non-temp CONVOY_HOME",
        )

    def test_direct_discovery_guards_home_before_loading_modules(self):
        # No PYTHONPATH: a checkout-local sitecustomize is not loaded before
        # plain `python -m unittest discover -s test/demo` starts.
        for home in (None, str(ROOT / "convoy-isolation-sentinel-never-create")):
            with self.subTest(home=home):
                env = os.environ.copy()
                env.pop("PYTHONPATH", None)
                env["PYTHONNOUSERSITE"] = "1"
                if home is None:
                    env.pop("CONVOY_HOME", None)
                else:
                    env["CONVOY_HOME"] = home
                completed = subprocess.run(
                    [sys.executable, "-m", "unittest", "discover", "-s", "test/demo",
                     "-p", "home_discovery_probe.py"],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                    timeout=30, stdin=subprocess.DEVNULL,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                if home is not None:
                    self.assertFalse(Path(home).exists())


if __name__ == "__main__":
    unittest.main()
