"""g2 verify: failure paths the ultracode brief names.

happy_path_test.py stays the six-frame GREEN walk. This module pins the
edges around `start`, crew window failure, whoami enumerate error, --since
garbage, and index hygiene. A missing verb or helper fails the test; that
is the contract g1 has not landed, not a skip.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cli, index
from convoy.cli import main
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.crew import crew
from convoy.layer import feed_since, parse_since
from convoy.onboard import onboard
from convoy.panes import identify

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "convoy"
EPOCH = "1970-01-01T00:00:00.000000Z"
FIRST_RUN = {
    "ok": True, "prepared": False, "wrote": False, "settings": None,
    "home_written": False, "settings_home": None,
}


def _cli_verbs() -> set[str]:
    text = (SRC / "cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'sub\.add_parser\("([^"]+)"', text))


def _git(*argv, cwd):
    return subprocess.run(
        ["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30,
    )


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _which(name):
    return "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"


def _run_cli(root, *argv):
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        try:
            rc = main(["--root", str(root), *argv])
        except SystemExit as e:
            return int(e.code or 1), {"ok": False, "error": "systemexit", "stderr": err.getvalue()}
    raw = buf.getvalue().strip()
    if not raw:
        return 1, {"ok": False, "error": "empty stdout", "stderr": err.getvalue()}
    try:
        card = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return 1, {"ok": False, "error": "not json", "stdout": raw, "stderr": err.getvalue()}
    return rc, card


class SinceGarbage(unittest.TestCase):
    """`--since` garbage is refused, never guessed — CLI, not just parse_since."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "since-t")

    def test_cli_feed_and_rail_refuse_garbage_since(self):
        for bad in ("", "10", "m", "ten minutes", "-5m", "1.5h"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_since(bad)
            rc, card = _run_cli(self.root, "feed", "--since", bad)
            self.assertNotEqual(rc, 0, bad)
            self.assertFalse(card.get("ok", True), (bad, card))
            self.assertIn("since", str(card.get("error") or "").lower(), (bad, card))
            rc, card = _run_cli(self.root, "rail", "--since", bad)
            self.assertNotEqual(rc, 0, bad)
            self.assertFalse(card.get("ok", True), (bad, card))


class WhoamiEnumerateError(unittest.TestCase):
    """An empty process table from OSError is not 'no chair'."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "who-t")
        seat(self.root, "grok", "g-who-t", worktree=str(self.root))

    def test_enumerate_oserror_surfaces_error_not_a_join_ask(self):
        import convoy.panes as panes
        panes._TEST_PROCS = None
        panes._TEST_PID = 99
        try:
            with mock.patch.object(panes, "enumerate_processes", side_effect=OSError("cim: Call cancelled")):
                me = identify(self.root, pid=99)
            self.assertTrue(me.get("error"), me)
            self.assertIn("cim", str(me["error"]).lower(), me)
            ask = str(me.get("ask") or "").lower()
            self.assertNotIn("join", ask, "enumerate failure must not look like an unmatched body")
        finally:
            panes._TEST_PROCS = None
            panes._TEST_PID = None

    def test_cli_whoami_carries_the_same_error(self):
        import convoy.panes as panes
        panes._TEST_PROCS = None
        panes._TEST_PID = 99
        try:
            with mock.patch.object(panes, "enumerate_processes", side_effect=OSError("cim: Call cancelled")):
                rc, card = _run_cli(self.root, "whoami")
            self.assertNotEqual(rc, 0)
            self.assertTrue(card.get("error"), card)
            self.assertIsNone(card.get("chair"))
        finally:
            panes._TEST_PROCS = None
            panes._TEST_PID = None


class CrewWindowFailure(unittest.TestCase):
    """A failed window is rollback or partial:true with a recovery verb per chair."""

    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "crew-fail")
        for target, kw in (
            ("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
            ("convoy.bringup.shutil.which", {"side_effect": _which}),
        ):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def test_popen_oserror_does_not_leave_orphan_chairs_without_partial(self):
        card = crew(
            self.root,
            [{"harness": "grok"}, {"harness": "claude"}],
            runner=mock.Mock(side_effect=OSError("access denied")),
        )
        self.assertFalse(card.get("ok"), card)
        self.assertFalse(card.get("launched"), card)
        seats = list_seats(self.root)
        joins = [r for r in feed_since(self.root, EPOCH) if r.get("kind") == "join"]
        if card.get("partial") is True:
            self.assertTrue(seats, "partial:true names the chairs that survived")
            rec = card.get("recovery") or card.get("next") or card.get("recover")
            self.assertTrue(rec, "partial:true carries the recovery verb per chair: " + json.dumps(card))
            blob = json.dumps(card)
            for s in seats:
                self.assertIn(s["session_id"], blob)
        else:
            self.assertEqual(seats, [], "window failure must roll back chairs or set partial:true")
            self.assertEqual(joins, [], "rolled-back crew mints no join token")


class GitUrlWithoutGhAuth(unittest.TestCase):
    """A git URL with no gh auth must not invent owner/repo; soft continue-local."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self._prev = os.environ.get("CONVOY_HOME")
        os.environ["CONVOY_HOME"] = str(self.home)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("CONVOY_HOME", None)
        else:
            os.environ["CONVOY_HOME"] = self._prev

    def test_onboard_clone_auth_failure_does_not_invent_a_github_repo(self):
        def fail(_argv, cwd=None, **_k):
            return subprocess.CompletedProcess(_argv, 128, "", "fatal: Authentication failed")

        card = onboard(
            self.root, ["grok"], thread="demo",
            checkout_root="https://github.com/acme/api.git",
            clone_runner=fail,
        )
        blob = json.dumps(card)
        self.assertNotIn('"owner": "acme"', blob)
        self.assertNotIn('"name": "acme/api"', blob)
        self.assertFalse(bool(card.get("repo") and card["repo"].get("cloned")), card)

    def test_onboard_clone_auth_failure_soft_continues_local(self):
        def fail(_argv, cwd=None, **_k):
            return subprocess.CompletedProcess(_argv, 128, "", "fatal: Authentication failed")

        card = onboard(
            self.root, ["grok"], thread="demo",
            checkout_root="https://github.com/acme/api.git",
            clone_runner=fail,
        )
        # "soft continue-local" is an ASK, not a silent bind (repo_step_test:
        # a failed clone binds nothing). The refusal card offers the exact
        # onboard that binds THIS root with github=no, for the human to run.
        self.assertFalse(card.get("ok"), card)
        self.assertIn("Authentication failed", card["error"])
        self.assertTrue(card["ask"]["continue_local"], card)
        self.assertIn("--checkout-root " + str(self.root.resolve()), card["ask"]["next"])
        self.assertIn("--github no", card["ask"]["next"])
        self.assertIn(card.get("github"), (False, "no", None), card)
        self.assertFalse((self.root / ".convoy" / "id").exists(), "a failed clone bound the local root silently")


class IndexHygiene(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._prev = os.environ.get("CONVOY_HOME")
        os.environ["CONVOY_HOME"] = str(self.home)
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "idx-t")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("CONVOY_HOME", None)
        else:
            os.environ["CONVOY_HOME"] = self._prev

    def test_recent_returns_newest_present_excluding_temp(self):
        self.assertTrue(callable(getattr(index, "recent", None)), "g1 slice 1c: index.recent(limit) is missing")
        keep = _durable_root(self)
        cid = ensure_id(keep)
        bind(keep, "keep-t")
        vanished = Path(tempfile.mkdtemp())
        index.record(vanished, "cvy_gone", "ghost")
        temp_root = Path(tempfile.gettempdir()) / "convoy-should-not-pick"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, temp_root, True)
        ensure_id(temp_root)
        bind(temp_root, "tmp-t")
        rows = index.recent(limit=10)
        ids = [r["convoy_id"] for r in rows]
        self.assertNotIn("cvy_gone", ids)
        self.assertIn(cid, ids)
        for r in rows:
            root = Path(str(r.get("root") or ""))
            self.assertTrue(r.get("present"), r)
            self.assertFalse(_is_os_temp(root), "recent() must exclude OS temp roots: " + str(root))

    def test_prune_drops_temp_and_absent_and_reports_what_went(self):
        prune = getattr(index, "prune_threads", None) or getattr(index, "prune", None)
        self.assertTrue(callable(prune), "g1 slice 1b: index.prune_threads / threads --prune is missing")
        vanished = Path(tempfile.mkdtemp())
        index.record(vanished, "cvy_gone", "ghost")
        shutil.rmtree(vanished, True)
        card = prune()
        dropped = card.get("dropped") or card.get("pruned") or []
        self.assertTrue(dropped, card)
        ids = {r.get("convoy_id") for r in dropped if isinstance(r, dict)} or set(dropped)
        self.assertTrue("cvy_gone" in ids or any("cvy_gone" in str(x) for x in dropped), card)
        remaining = {r["convoy_id"] for r in index.list_threads()}
        self.assertNotIn("cvy_gone", remaining)


class DemoPackageIsolatesHome(unittest.TestCase):
    def test_importing_demo_without_run_py_sets_throwaway_home(self):
        env = {k: v for k, v in os.environ.items() if k != "CONVOY_HOME"}
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(ROOT / "src")
        code = (
            "import test.demo, os, sys;"
            "h = os.environ.get('CONVOY_HOME') or '';"
            "sys.stdout.write(h)"
        )
        r = subprocess.run(
            [sys.executable, "-c", code], env=env, cwd=str(ROOT),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        home = r.stdout.strip()
        self.assertTrue(home, "test.demo must set CONVOY_HOME so bare unittest cannot write ~/.convoy")
        self.assertTrue(_is_os_temp(Path(home)), "throwaway CONVOY_HOME must sit under the OS temp dir: " + home)
        self.assertNotEqual(Path(home).resolve(), (Path.home() / ".convoy").resolve())


class StartFailurePaths(unittest.TestCase):
    """`convoy start [<repo>]` — picker, never auto-bind newest, never duplicate bring_up."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._prev = os.environ.get("CONVOY_HOME")
        os.environ["CONVOY_HOME"] = str(self.home)
        self.root = Path(tempfile.mkdtemp())
        if "start" not in _cli_verbs():
            self.fail("g1 slice 3: `convoy start` is not a CLI verb yet")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("CONVOY_HOME", None)
        else:
            os.environ["CONVOY_HOME"] = self._prev

    def test_no_repo_empty_index_asks_new_thread_and_does_not_bind(self):
        rc, card = _run_cli(self.root, "start")
        blob = json.dumps(card).lower()
        self.assertIn("new thread", blob, card)
        self.assertFalse(card.get("ok") and card.get("convoy_id"), "empty index must not auto-bind: " + json.dumps(card))
        self.assertFalse((self.root / ".convoy" / "id").is_file())

    def test_no_repo_many_threads_requires_picker_never_auto_newest(self):
        older = _durable_root(self)
        newer = _durable_root(self)
        ensure_id(older)
        bind(older, "old-t")
        ensure_id(newer)
        bind(newer, "new-t")
        rc, card = _run_cli(self.root, "start")
        self.assertFalse(card.get("ok"), card)
        self.assertEqual(card.get("ask"), "pick", card)
        titles = [t.get("title") or t.get("thread") for t in (card.get("threads") or [])]
        self.assertIn("old-t", titles, card)
        self.assertIn("new-t", titles, card)
        self.assertIsNone(card.get("convoy_id") if not card.get("bound") else card.get("root"))
        self.assertFalse((self.root / ".convoy" / "id").is_file(), "never auto-bind newest")
        self.assertFalse(card.get("brought_up"))

    def test_git_url_without_gh_auth_soft_continues_local(self):
        def fail(_argv, cwd=None, **_k):
            return subprocess.CompletedProcess(_argv, 128, "", "gh: To get started with GitHub CLI, please run:  gh auth login")

        with mock.patch("convoy.repo.list_repos", return_value={
            "ok": False, "gh_present": True, "repos": None, "count": None,
            "error": "gh auth login",
        }), mock.patch("convoy.repo.clone", side_effect=lambda *a, **k: {
            "ok": False, "cloned": False, "error": "fatal: Authentication failed",
        }):
            rc, card = _run_cli(self.root, "start", "https://github.com/acme/api.git")
        blob = json.dumps(card)
        self.assertNotIn('"owner": "acme"', blob)
        self.assertTrue(card.get("ok") or "continue" in blob.lower() or card.get("github") in (False, "no", None), card)
        self.assertNotEqual(card.get("github"), True, "no gh auth must not claim github yes with a fake clone")

    def test_already_live_harness_attaches_and_does_not_bring_up(self):
        repo = _git_repo()
        onboard(repo, ["grok"], thread="live-t", checkout_root=str(repo), github=False)
        spawns = []

        def capture(argv, cwd=None, rect=None, **_k):
            spawns.append(list(argv))
            return {"ok": True, "pid": 7, "argv": list(argv)}

        with mock.patch("convoy.cli.live_runner", new=capture), \
             mock.patch("convoy.bringup.live_runner", new=capture), \
             mock.patch("convoy.start.identify", return_value={"ok": True, "chair": "g-live", "harness": "grok"}), \
             mock.patch("convoy.start.bodies", return_value={"ok": True, "chairs": [{"session_id": "g-live", "live": True}]}):
            rc, card = _run_cli(repo, "start", str(repo))
        self.assertEqual(spawns, [], "already-live harness must attach, never duplicate bring_up: " + json.dumps(card))
        blob = json.dumps(card).lower()
        self.assertTrue(card.get("attached") or "attach" in blob, card)


def _durable_root(test: unittest.TestCase) -> Path:
    base = Path(__file__).resolve().parent / "_keep_roots"
    base.mkdir(exist_ok=True)
    p = Path(tempfile.mkdtemp(prefix="g2-keep-", dir=str(base)))
    test.addCleanup(shutil.rmtree, p, True)
    return p


def _is_os_temp(path: Path) -> bool:
    try:
        path = path.resolve()
        tmp = Path(tempfile.gettempdir()).resolve()
        return os.path.normcase(str(path)).startswith(os.path.normcase(str(tmp)))
    except OSError:
        return False


if __name__ == "__main__":
    unittest.main()
