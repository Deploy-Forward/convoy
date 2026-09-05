"""Widget: nudge affordance on stale rows; detached service behind a pidfile.

No Tk interpreter in this process. No real spawn: the spawner is a fake.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cli
from convoy.convoy import bind, ensure_id, set_github
from convoy.inbox import enqueue
from convoy.lifecycle import join, seated_ack
from convoy.widget import build_widget_model
from convoy.widget_service import (
    PIDFILE,
    auto_widget_service,
    convoy_home,
    ensure_widget_service,
    service_argv,
)

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q")
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return d


class NudgeAffordance(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "wsvc")
        set_github(self.root, False)
        j = join(self.root, "grok", session_id="g-one", worktree=str(self.root))
        seated_ack(self.root, "g-one", j["token"])

    def _model(self, *, live: bool, now: str):
        def enum():
            return [{"pid": 4242, "ppid": 1, "cmdline": "grok -d " + str(self.root), "cwd": str(self.root)}] if live else []
        return build_widget_model([self.root], probe_fn=lambda _h: NULL_PROBE,
                                  enumerate_fn=enum, now_fn=lambda: now, idle_s=300)

    def test_stale_row_exposes_nudge_available(self):
        enqueue(self.root, "g-one", "hello", to="grok")
        m = self._model(live=True, now="2099-01-01T00:00:00.000000Z")
        row = m["threads"][0]["chairs"][0]
        self.assertEqual(row["chip"], "stale")
        self.assertIs(row["nudge_available"], True)
        self.assertEqual(row["nudge"], "nudge --seat g-one --dry-run")

    def test_working_and_gone_rows_do_not(self):
        m = self._model(live=False, now="2099-01-01T00:00:00.000000Z")
        row = m["threads"][0]["chairs"][0]
        self.assertEqual(row["chip"], "gone")
        self.assertIs(row["nudge_available"], False)
        m = self._model(live=True, now=m["threads"][0]["chairs"][0]["last_authored"])
        row = m["threads"][0]["chairs"][0]
        self.assertEqual(row["chip"], "working")
        self.assertIs(row["nudge_available"], False)


class Service(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.spawned: list[list[str]] = []

    def _spawner(self, pid: int):
        def spawn(argv):
            self.spawned.append(list(argv))
            return pid
        return spawn

    def test_convoy_home_follows_env(self):
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            self.assertEqual(convoy_home(), self.home)
        self.assertEqual(convoy_home(self.home), self.home)

    def test_argv_is_widget_refresh_3_topmost_no_resume_no_p(self):
        argv = service_argv()
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1:], ["-m", "convoy", "widget", "--refresh", "3", "--topmost"])
        self.assertNotIn("--resume", argv)
        self.assertNotIn("-p", argv)

    def test_first_run_spawns_once_and_writes_pid(self):
        card = ensure_widget_service(self.home, spawner=self._spawner(777), alive_fn=lambda _p: False)
        self.assertTrue(card["ok"])
        self.assertTrue(card["started"])
        self.assertFalse(card["already"])
        self.assertEqual(card["pid"], 777)
        self.assertEqual(card["pidfile"], str(self.home / PIDFILE))
        self.assertEqual((self.home / PIDFILE).read_text(encoding="utf-8").strip(), "777")
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.spawned[0], service_argv())

    def test_alive_pid_means_no_second_spawn(self):
        self.home.mkdir(exist_ok=True)
        (self.home / PIDFILE).write_text("4321\n", encoding="utf-8")
        card = ensure_widget_service(self.home, spawner=self._spawner(1), alive_fn=lambda p: p == 4321)
        self.assertTrue(card["ok"])
        self.assertFalse(card["started"])
        self.assertTrue(card["already"])
        self.assertEqual(card["pid"], 4321)
        self.assertEqual(self.spawned, [])

    def test_dead_pid_in_pidfile_respawns(self):
        self.home.mkdir(exist_ok=True)
        (self.home / PIDFILE).write_text("4321\n", encoding="utf-8")
        card = ensure_widget_service(self.home, spawner=self._spawner(9), alive_fn=lambda _p: False)
        self.assertTrue(card["started"])
        self.assertFalse(card["already"])
        self.assertEqual(card["stale_pid"], 4321)
        self.assertEqual((self.home / PIDFILE).read_text(encoding="utf-8").strip(), "9")

    def test_garbage_pidfile_is_absent(self):
        self.home.mkdir(exist_ok=True)
        (self.home / PIDFILE).write_text("not-a-pid\n", encoding="utf-8")
        card = ensure_widget_service(self.home, spawner=self._spawner(5), alive_fn=lambda _p: False)
        self.assertTrue(card["started"])
        self.assertIsNone(card["stale_pid"])

    def test_spawn_failure_never_claims_started(self):
        def boom(_argv):
            raise OSError("no python")
        card = ensure_widget_service(self.home, spawner=boom, alive_fn=lambda _p: False)
        self.assertFalse(card["ok"])
        self.assertFalse(card["started"])
        self.assertIsNone(card["pid"])
        self.assertIn("no python", card["error"])
        self.assertFalse((self.home / PIDFILE).exists())

    def test_auto_skips_when_disabled_or_temp_home(self):
        card = auto_widget_service(disabled=True, home=self.home, spawner=self._spawner(1))
        self.assertFalse(card["started"])
        self.assertEqual(card["skipped"], "--no-widget")
        card = auto_widget_service(disabled=False, home=self.home, spawner=self._spawner(1))
        self.assertFalse(card["started"])
        self.assertEqual(card["skipped"], "temp CONVOY_HOME")
        self.assertEqual(self.spawned, [])

    def test_auto_runs_on_a_real_home(self):
        real = Path(tempfile.mkdtemp())
        with mock.patch("convoy.widget_service.is_temp_root", return_value=False):
            card = auto_widget_service(disabled=False, home=real, spawner=self._spawner(3),
                                       alive_fn=lambda _p: False)
        self.assertTrue(card["started"])
        self.assertEqual(len(self.spawned), 1)


class ServiceCli(unittest.TestCase):
    def test_widget_service_flag_calls_ensure_not_tk(self):
        home = Path(tempfile.mkdtemp())
        seen = {}

        def fake_ensure(home_arg=None, **kw):
            seen["home"] = home_arg
            return {"ok": True, "started": False, "already": True, "pid": 1}

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(home)}), \
                mock.patch("convoy.cli.ensure_widget_service", fake_ensure), \
                mock.patch("convoy.cli.run_widget", side_effect=AssertionError("Tk must not open")), \
                redirect_stdout(out):
            rc = cli.main(["widget", "--service"])
        card = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(rc, 0)
        self.assertTrue(card["already"])
        self.assertIn("home", seen)

    def test_crew_and_relaunch_accept_no_widget(self):
        # parse-only: a bad flag exits 2 via argparse before any command runs
        for argv in (["crew", "--seat", "grok", "--no-widget", "--thread", "x"], ["relaunch", "--no-widget", "--dry-run"]):
            out = io.StringIO()
            root = Path(tempfile.mkdtemp())
            with mock.patch.dict(os.environ, {"CONVOY_HOME": str(tempfile.mkdtemp())}), \
                    mock.patch("convoy.cli.auto_widget_service", side_effect=AssertionError("must not auto-start")), \
                    redirect_stdout(out):
                try:
                    rc = cli.main(["--root", str(root), *argv])
                except SystemExit as e:
                    rc = e.code
            self.assertNotEqual(rc, 2, argv)


if __name__ == "__main__":
    unittest.main()
