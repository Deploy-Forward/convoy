"""The suite runs inside a person's own harness pane, so it must never prove a real session.

A launch now attaches an unseated launcher it can prove (environment or token). The
runner's environment carries the pane's own native session id, so without isolation a
test that runs a CLI launch could attach the person's real session to its temp thread
and take that thread's lead. The shared test guard clears every native session variable
Convoy's identity code reads (panes.NATIVE_SESSION_ENV, the one list) and the
CONVOY_ROOT pointer for the whole run, and restores them when the run ends. A test that
needs a proven launcher sets the variable itself (patch.dict, or env= on identify).

Every id is synthetic; roots and the Convoy home are temporary; no harness runs.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "convoy"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "test"))

# The child: what a CLI `add` does inside a pane whose environment proves a real
# session. Importing test.demo installs the guard, exactly as every test entrypoint does.
CHILD = r'''
import json, sys
from pathlib import Path
from unittest import mock
import test.demo  # noqa: F401  the shared guard
from convoy import panes
from convoy.cli import main
from convoy.convoy import list_seats
from convoy.lifecycle import lead_state
root = Path(sys.argv[1])
panes._TEST_PROCS = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                     {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]
panes._TEST_PID = 21
first = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
         "settings_home": None}
with mock.patch("convoy.crew._placement", return_value=("split", "synthetic")), \
     mock.patch("convoy.crew.launch_seat", return_value={"ok": True}), \
     mock.patch("convoy.bringup.ensure_first_run", return_value=first), \
     mock.patch("convoy.targeted_launch.ensure_first_run", return_value=first):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--root", str(root), "add", "codex"])
card = json.loads(buf.getvalue().strip().splitlines()[-1])
print(json.dumps({"rc": rc, "card_launcher": card.get("launcher"), "error": card.get("error"),
                  "seats": [s["session_id"] for s in list_seats(root)],
                  "lead": lead_state(root)["status"]}))
'''


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


class ARealPaneSessionNeverReachesATest(unittest.TestCase):
    def test_a_cli_add_under_a_parent_session_id_attaches_nobody(self):
        from convoy.convoy import bind
        owner = tempfile.TemporaryDirectory(prefix="convoy-isolation-")
        self.addCleanup(owner.cleanup)
        root = Path(owner.name) / "repo"
        root.mkdir()
        _git("init", "-q", cwd=root)
        (root / "README.md").write_text("x\n", encoding="utf-8")
        _git("add", "README.md", cwd=root)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=root)
        env = dict(os.environ)
        env["CONVOY_HOME"] = str(Path(owner.name) / "home")
        env["CLAUDE_CODE_SESSION_ID"] = "synthetic-parent-pane-session"
        env["PYTHONPATH"] = os.pathsep.join((str(REPO), str(REPO / "src"), str(REPO / "test")))
        prev = os.environ.get("CONVOY_HOME")
        os.environ["CONVOY_HOME"] = env["CONVOY_HOME"]
        try:
            bind(root, "isolation")
        finally:
            if prev is None:
                os.environ.pop("CONVOY_HOME", None)
            else:
                os.environ["CONVOY_HOME"] = prev
        done = subprocess.run([sys.executable, "-c", CHILD, str(root)], cwd=str(REPO), env=env,
                              capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(out["rc"], 0, out)
        self.assertEqual(len(out["seats"]), 1, "only the added neuron; the pane's session attached: " + json.dumps(out))
        self.assertFalse((out["card_launcher"] or {}).get("attached"), out)
        self.assertEqual(out["lead"], "none", out)


# The child: a CLI `add` inside the person's own Windows Terminal (or tmux) pane. A harmless
# stand-in named wt (or tmux) plays the real terminal: if it ever runs it leaves a marker.
# The real terminal is never reachable: which() answers the stand-in for wt and tmux.
CHILD_TERMINAL = r'''
import json, os, shutil, sys
from pathlib import Path
from unittest import mock
standin = sys.argv[2]
real_which = shutil.which
def which(name, *a, **k):
    if os.path.basename(str(name)).lower().removesuffix(".exe") in ("wt", "tmux"):
        return standin
    return real_which(name, *a, **k)
shutil.which = which
import test.demo  # noqa: F401  the shared guard
from convoy.cli import main
root = Path(sys.argv[1])
first = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
         "settings_home": None}
with mock.patch("convoy.bringup.ensure_first_run", return_value=first), \
     mock.patch("convoy.targeted_launch.ensure_first_run", return_value=first):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--root", str(root), "add", "codex", "--allow-unverified-launch"])
lines = buf.getvalue().strip().splitlines()
card = json.loads(lines[-1]) if lines else {}
print(json.dumps({"rc": rc, "placement": card.get("placement"), "error": card.get("error")}))
'''


class ARealTerminalNeverOpensAPane(unittest.TestCase):
    def test_a_cli_add_inside_a_terminal_pane_spawns_no_terminal(self):
        from convoy.convoy import bind
        owner = tempfile.TemporaryDirectory(prefix="convoy-terminal-")
        self.addCleanup(owner.cleanup)
        base = Path(owner.name)
        root = base / "repo"
        root.mkdir()
        _git("init", "-q", cwd=root)
        (root / "README.md").write_text("x\n", encoding="utf-8")
        _git("add", "README.md", cwd=root)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=root)
        marker = base / "spawned.txt"
        if os.name == "nt":
            standin = base / "wt.cmd"
            standin.write_text("@echo spawned> \"" + str(marker) + "\"\n", encoding="utf-8")
        else:
            standin = base / "wt"
            standin.write_text("#!/bin/sh\necho spawned > '" + str(marker) + "'\n", encoding="utf-8")
            standin.chmod(0o755)
        env = dict(os.environ)
        env["CONVOY_HOME"] = str(base / "home")
        env["WT_SESSION"] = "synthetic-owner-window"
        env["TMUX"] = "/tmp/tmux-synthetic/default,1,0"
        env["TMUX_PANE"] = "%9"
        env["PYTHONPATH"] = os.pathsep.join((str(REPO), str(REPO / "src"), str(REPO / "test")))
        prev = os.environ.get("CONVOY_HOME")
        os.environ["CONVOY_HOME"] = env["CONVOY_HOME"]
        try:
            bind(root, "terminal")
        finally:
            if prev is None:
                os.environ.pop("CONVOY_HOME", None)
            else:
                os.environ["CONVOY_HOME"] = prev
        done = subprocess.run([sys.executable, "-c", CHILD_TERMINAL, str(root), str(standin)], cwd=str(REPO),
                              env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertNotEqual(out["placement"], "split", "the inherited WT_SESSION/TMUX chose a split: " + json.dumps(out))
        self.assertFalse(marker.exists(), "a terminal was started: " + json.dumps(out))


class TheTerminalGuard(unittest.TestCase):
    def standin(self, name):
        d = tempfile.TemporaryDirectory(prefix="guard-terminal-")
        self.addCleanup(d.cleanup)
        path = Path(d.name) / (name + (".cmd" if os.name == "nt" else ""))
        path.write_text("@echo stand-in\n" if os.name == "nt" else "#!/bin/sh\necho stand-in\n", encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o755)
        return path

    def run_in_a_test(self, spawn):
        seen = {"raised": None}

        class Throwaway(unittest.TestCase):
            def runTest(self):
                try:
                    spawn()
                except OSError as e:
                    seen["raised"] = type(e).__name__

        result = unittest.TestResult()
        Throwaway().run(result)
        return seen["raised"], [text for _t, text in result.failures + result.errors]

    def test_a_real_wt_or_tmux_is_refused_and_fails_its_test(self):
        for name in ("wt", "tmux", "convoy-pane-host"):
            path = self.standin(name)
            raised, failures = self.run_in_a_test(
                lambda: subprocess.run([str(path), "-w", "0", "split-pane"], capture_output=True, timeout=30))
            self.assertEqual(raised, "PermissionError", name)
            self.assertTrue(failures and "terminal host" in failures[0], (name, failures))

    def test_a_test_opts_in_to_a_real_terminal(self):
        import harness_guard
        path = self.standin("wt")
        with harness_guard.allow_real_terminal():
            done = subprocess.run([str(path)], capture_output=True, text=True, timeout=30)
        self.assertIn("stand-in", done.stdout)

    def test_the_placement_variables_are_cleared_for_the_run(self):
        import home_guard
        for name in home_guard.PLACEMENT_ENV:
            self.assertNotIn(name, os.environ, name)
        self.assertEqual(set(home_guard.PLACEMENT_ENV), {"WT_SESSION", "WT_PROFILE_ID", "TMUX", "TMUX_PANE"})


class TheGuard(unittest.TestCase):
    def test_the_guard_clears_and_restores_every_listed_variable(self):
        import home_guard
        from convoy.panes import NATIVE_SESSION_ENV
        names = (*NATIVE_SESSION_ENV, "CONVOY_ROOT")
        saved = {n: os.environ.get(n) for n in names}
        try:
            for n in names:
                os.environ[n] = "synthetic-" + n.lower()
            held = home_guard.isolate_native_sessions()
            for n in names:
                self.assertNotIn(n, os.environ, n)
                self.assertEqual(held[n], "synthetic-" + n.lower())
            home_guard.restore_native_sessions(held)
            for n in names:
                self.assertEqual(os.environ.get(n), "synthetic-" + n.lower())
        finally:
            for n, v in saved.items():
                if v is None:
                    os.environ.pop(n, None)
                else:
                    os.environ[n] = v

    def test_the_runs_own_environment_carries_no_native_session(self):
        from convoy.panes import NATIVE_SESSION_ENV
        for n in (*NATIVE_SESSION_ENV, "CONVOY_ROOT"):
            self.assertNotIn(n, os.environ, n)

    def test_the_list_names_every_session_variable_the_code_reads(self):
        from convoy.panes import NATIVE_SESSION_ENV
        read = set()
        for path in SRC.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            read.update(re.findall(r"[\"']([A-Z][A-Z0-9]*_(?:[A-Z0-9]+_)*(?:SESSION_ID|THREAD_ID))[\"']", text))
        self.assertTrue(read)
        self.assertEqual(read - set(NATIVE_SESSION_ENV), set(), "add them to panes.NATIVE_SESSION_ENV")


if __name__ == "__main__":
    unittest.main()
