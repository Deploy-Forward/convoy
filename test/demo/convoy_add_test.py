"""convoy add: one neuron, launched into its thread's terminal, model auto by default.

`add` mints and joins one chair through crew's code, then launches it through the
targeted path:

- inside tmux: a split of the caller's exact pane;
- on Windows with wt on PATH: the thread's own named Windows Terminal window
  (`wt -w 0` splits whatever pane has focus, so a neuron would land wherever the
  person last clicked); the first neuron opens it, later ones
  split inside it; thread_window_test.py pins the details;
- on POSIX outside tmux, with tmux installed: the thread's own detached tmux
  session, and the card carries the attach command;
- nowhere to put it: a refusal before anything is written.

The card's `placement` says which happened. Model and effort are auto unless
given: auto passes no flag, so the harness picks its own default. Every test
uses the real terminal_capability with an injected env, which and platform;
the runners are mocks, so nothing is ever launched.
"""
import io
import functools
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_fixture import seated_launcher, widget_lead, with_seated_launcher, work_seats  # noqa: E402

from convoy.cli import main  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats  # noqa: E402
from convoy.crew import crew  # noqa: E402

crew = with_seated_launcher(crew)

from convoy.harness_contract import model_flag  # noqa: E402

FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None}
MODEL_FLAGS = ("-m", "--model")


def _add(*args, **kwargs):
    from convoy.crew import add
    kwargs.setdefault("launcher", seated_launcher(args[0]))
    return add(*args, **kwargs)


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _harness_which(name):
    """Every harness (and the pane host) resolves to an absolute fake; nothing runs."""
    return "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"


def _terminal_which(*present):
    """The terminal lookup terminal_capability is handed: only the named tools exist."""
    names = {str(n).lower() for n in present}

    def lookup(name):
        key = str(name).lower().removesuffix(".exe")
        return ("/usr/bin/" + key) if key in names else None

    return lookup


def _base(value) -> str:
    return str(value).replace("\\", "/").split("/")[-1].lower()


WT = {"env": {"WT_SESSION": "caller-window"}, "which": _terminal_which("wt"), "platform_name": "nt"}
TMUX = {"env": {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%3"}, "which": _terminal_which("tmux"),
        "platform_name": "posix"}
TMUX_OUTSIDE = {"env": {"TERM": "xterm-256color"}, "which": _terminal_which("tmux"), "platform_name": "posix"}
BARE_LINUX = {"env": {"TERM": "xterm-256color"}, "which": _terminal_which(), "platform_name": "posix"}
WINDOWS_NO_WT_SESSION = {"env": {}, "which": _terminal_which("wt"), "platform_name": "nt"}


class AddBase(unittest.TestCase):
    def setUp(self):
        # A launch records a proven launcher; these tests exercise launch mechanics, so the
        # launching session is a synthetic seated chair (launcher_always_test covers refusal).
        _launcher = mock.patch("convoy.cli.resolve_launcher", side_effect=seated_launcher)
        _launcher.start()
        self.addCleanup(_launcher.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "add-t")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _harness_which})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        self.window_runner = mock.Mock(return_value={"ok": True, "pid": 4343})

    def add(self, harness, model=None, where=WT, **kw):
        return _add(self.root, harness, model, runner=self.runner, window_runner=self.window_runner, **where, **kw)

    def harness_argv(self, card):
        launch = card.get("launch") or {}
        return [str(a) for a in launch.get("harness_argv") or []]

    def assertNoModelOrEffortFlag(self, argv):
        for flag in (*MODEL_FLAGS, "-c"):
            self.assertNotIn(flag, argv)
        self.assertFalse(any("model_reasoning_effort" in a for a in argv), argv)


class AddSplitsIntoTheCallersTerminal(AddBase):
    def test_windows_terminal_opens_the_threads_own_window_never_window_zero(self):
        card = self.add("codex")
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["launched"])
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(self.runner.call_count, 1)
        self.window_runner.assert_not_called()
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(_base(argv[0]), "wt")
        self.assertEqual(argv[1:4], ["-w", card["window"], "new-tab"])
        self.assertNotIn("0", argv[1:3])
        self.assertNotIn("--window", argv)
        sid = card["seats"][0]["session_id"]
        self.assertEqual([s["session_id"] for s in work_seats(self.root)], [sid])
        row = work_seats(self.root)[0]
        self.assertTrue(row["boot_prompt"])
        self.assertIn(str(row["worktree"]), argv)

    def test_tmux_splits_the_callers_exact_pane(self):
        card = self.add("codex", where=TMUX)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "split")
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(argv[0], "/usr/bin/tmux")
        self.assertEqual(argv[1:4], ["split-window", "-t", "%3"])
        self.window_runner.assert_not_called()

    def test_windows_outside_windows_terminal_uses_the_same_thread_window(self):
        card = self.add("codex", where=WINDOWS_NO_WT_SESSION)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["launched"])
        self.assertEqual(card["placement"], "thread-window")
        self.assertTrue(card["placement_reason"])
        self.window_runner.assert_not_called()
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(argv[1:4], ["-w", card["window"], "new-tab"])

    def test_a_second_add_of_the_same_harness_gets_its_own_chair(self):
        first = self.add("codex")
        second = self.add("codex")
        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertNotEqual(first["seats"][0]["session_id"], second["seats"][0]["session_id"])
        self.assertNotEqual(_base(first["seats"][0]["worktree"]), _base(second["seats"][0]["worktree"]))


class AddOnLinux(AddBase):
    def test_tmux_installed_but_caller_outside_it_starts_a_detached_session(self):
        card = self.add("codex", where=TMUX_OUTSIDE)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["launched"])
        self.assertEqual(card["placement"], "detached")
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(argv[0], "/usr/bin/tmux")
        self.assertEqual(argv[1:4], ["new-session", "-d", "-s"])
        name = argv[4]
        self.assertRegex(name, r"^convoy-[0-9a-f]{8}$")  # the thread's own session
        self.assertNotIn(".", name)
        self.assertNotIn(":", name)
        worktree = work_seats(self.root)[0]["worktree"]
        from convoy.targeted_launch import root_thread_label
        self.assertEqual(argv[5:7], ["-n", root_thread_label(self.root) + " - codex-1"])   # names the thread
        self.assertEqual(argv[7:9], ["-c", str(worktree)])
        # tmux runs ONE shell command string; it is shlex-quoted, not split argv
        self.assertEqual(len(argv), 10)
        self.assertEqual(card["attach"], "tmux attach -t =" + name)
        self.window_runner.assert_not_called()

    def test_no_tmux_refuses_before_any_chair_or_worktree_is_made(self):
        card = self.add("codex", where=BARE_LINUX)
        self.assertFalse(card["ok"])
        self.assertFalse(card["launched"])
        self.assertEqual(card["placement"], "none")
        self.assertIn("no tmux", card["placement_reason"])
        self.assertIn("install tmux", card["placement_reason"])
        self.runner.assert_not_called()
        self.window_runner.assert_not_called()
        self.assertEqual(work_seats(self.root), [])
        self.assertEqual([p for p in self.root.parent.iterdir() if p.name.startswith(self.root.name + "-wt-")], [])

    def test_failed_spawn_leaves_the_chair_joined_and_says_not_launched(self):
        self.runner.return_value = {"ok": False, "error": "adapter refused"}
        card = self.add("codex", where=TMUX)
        self.assertFalse(card["ok"])
        self.assertFalse(card["launched"])
        self.assertTrue(card["partial"])
        sid = card["seats"][0]["session_id"]
        self.assertEqual([s["session_id"] for s in work_seats(self.root)], [sid])
        self.assertEqual(card["recovery"], [{"session_id": sid, "verb": "launch --seat " + sid}])


class AddModelDefaultsToAuto(AddBase):
    def test_add_codex_passes_no_model_or_effort_flag(self):
        card = self.add("codex")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["model"], "auto")
        self.assertEqual(card["effort"], "auto")
        self.assertNoModelOrEffortFlag(self.harness_argv(card))
        self.assertNoModelOrEffortFlag([str(a) for a in self.runner.call_args[0][0]])
        self.assertIsNone(work_seats(self.root)[0].get("model"))

    def test_add_codex_auto_is_the_same_as_no_model(self):
        card = self.add("codex", "auto")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["model"], "auto")
        self.assertNoModelOrEffortFlag(self.harness_argv(card))
        self.assertIsNone(work_seats(self.root)[0].get("model"))

    def test_add_claude_passes_no_model_flag(self):
        card = self.add("claude")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["model"], "auto")
        self.assertNoModelOrEffortFlag(self.harness_argv(card))

    def test_an_explicit_model_and_effort_ride_the_contracts_flags(self):
        card = self.add("codex", "gpt-5.6-sol", effort="high")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["model"], "gpt-5.6-sol")
        self.assertEqual(card["effort"], "high")
        argv = self.harness_argv(card)
        flag = model_flag("codex")["flag"]
        self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index(flag) + 1], "gpt-5.6-sol")
        self.assertIn("model_reasoning_effort=high", argv)

    def test_an_effort_the_harness_does_not_take_is_refused_before_any_write(self):
        card = self.add("codex", effort="ludicrous")
        self.assertFalse(card["ok"])
        self.assertIn("ludicrous", card["error"])
        self.runner.assert_not_called()
        self.assertEqual(work_seats(self.root), [])


class AddKeepsTheLaunchGates(AddBase):
    def test_unverified_harness_refuses_without_the_override(self):
        card = self.add("grok")
        self.assertFalse(card["ok"])
        self.assertIn("unverified launch eligibility", card["error"])
        self.runner.assert_not_called()
        self.assertEqual(work_seats(self.root), [])

    def test_unverified_harness_launches_with_the_override(self):
        card = self.add("grok", allow_unverified_launch=True, trust_probe=lambda _row: True)
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.runner.call_count, 1)

    def test_dry_run_writes_nothing_and_reports_the_placement(self):
        card = _add(self.root, "codex", **WT)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["dry_run"])
        self.assertFalse(card["launched"])
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(work_seats(self.root), [])

    def test_crew_launch_opens_the_threads_own_window(self):
        from convoy.targeted_launch import thread_window_name
        card = crew(self.root, [{"harness": "codex"}], runner=self.window_runner)
        self.assertTrue(card["ok"], card)
        argv = [str(a) for a in self.window_runner.call_args[0][0]]
        self.assertEqual(argv[1:4], ["-w", thread_window_name(card["convoy_id"]), "new-tab"])


class AddCli(unittest.TestCase):
    def _run(self, root, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["--root", str(root), *argv])
        raw = out.getvalue().strip()
        return rc, (json.loads(raw) if raw else None)

    def test_dry_run_refuses_the_repo_file_opt_in(self):
        root = Path(tempfile.mkdtemp())
        rc, card = self._run(root, "add", "codex", "--dry-run", "--write-repo-files")
        self.assertEqual(rc, 1)
        self.assertIn("--write-repo-files needs a live run", card["error"])

    def test_positional_model_and_options_reach_add(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch("convoy.cli.add_neuron", return_value={"ok": True}) as add:
            rc, _ = self._run(root, "add", "codex", "gpt-5.6-sol", "--effort", "high", "--allow-unverified-launch")
        self.assertEqual(rc, 0)
        args, kwargs = add.call_args
        self.assertEqual(args[1:3], ("codex", "gpt-5.6-sol"))
        self.assertEqual(kwargs["effort"], "high")
        self.assertTrue(kwargs["allow_unverified_launch"])
        self.assertIsNotNone(kwargs["runner"])
        self.assertIsNotNone(kwargs["window_runner"])

    def test_dry_run_passes_no_runner(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch("convoy.cli.add_neuron", return_value={"ok": True}) as add:
            rc, _ = self._run(root, "add", "codex", "--dry-run")
        self.assertEqual(rc, 0)
        args, kwargs = add.call_args
        self.assertEqual(args[1:3], ("codex", None))
        self.assertIsNone(kwargs["runner"])
        self.assertIsNone(kwargs["window_runner"])


def _cli(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = out.getvalue().strip()
    return rc, (json.loads(raw) if raw else None)


def _no_terminal_env():
    """The process env with no terminal of its own, so a CLI retry decides from what a test sets."""
    env = {k: v for k, v in os.environ.items() if k not in ("WT_SESSION", "TMUX", "TMUX_PANE")}
    return mock.patch.dict(os.environ, env, clear=True)


class DetachedSessionsNeverCollide(AddBase):
    """One detached tmux session per thread: chairs of one thread share it (the second
    splits inside it once the first neuron's host is live), and two threads never do."""

    def _name(self, card):
        self.assertTrue(card["ok"], card)
        return [str(a) for a in self.runner.call_args[0][0]][4]

    def _other_root(self, thread):
        other = _git_repo()
        ensure_id(other)
        bind(other, thread)
        return other

    def test_two_chairs_of_one_thread_share_its_session_and_the_second_splits_into_it(self):
        from convoy.targeted_launch import take_launch_claim
        card = self.add("codex", where=TMUX_OUTSIDE, title="a.b")
        first = self._name(card)
        from convoy.targeted_launch import _claim_path
        sid = card["seats"][0]["session_id"]
        _claim_path(self.root, sid).unlink(missing_ok=True)
        take_launch_claim(self.root, sid, host_pid=os.getpid())   # the first neuron's host is live
        self.add("codex", where=TMUX_OUTSIDE, title="a-b")
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertRegex(first, r"^convoy-[0-9a-f]{8}$")
        self.assertEqual(argv[1:4], ["split-window", "-t", "=" + first + ":"])

    def test_two_roots_on_one_thread_name_with_default_titles_get_distinct_sessions(self):
        first = self._name(_add(self.root, "codex", runner=self.runner, window_runner=self.window_runner, **TMUX_OUTSIDE))
        other = self._other_root("add-t")
        second = self._name(_add(other, "codex", runner=self.runner, window_runner=self.window_runner, **TMUX_OUTSIDE))
        self.assertNotEqual(first, second)

    def test_thread_and_title_that_join_to_the_same_text_get_distinct_sessions(self):
        one, two = self._other_root("a"), self._other_root("a-b")
        first = self._name(_add(one, "codex", title="b-c", runner=self.runner, window_runner=self.window_runner, **TMUX_OUTSIDE))
        second = self._name(_add(two, "codex", title="c", runner=self.runner, window_runner=self.window_runner, **TMUX_OUTSIDE))
        self.assertNotEqual(first, second)

    def test_attach_names_the_session_exactly(self):
        card = self.add("codex", where=TMUX_OUTSIDE)
        self.assertEqual(card["attach"], "tmux attach -t =" + self._name(card))

    def test_the_runner_waits_for_new_session_and_a_nonzero_exit_is_not_a_launch(self):
        from convoy.targeted_launch import active_pane_runner
        argv = ["/usr/bin/tmux", "new-session", "-d", "-s", "convoy-t-x-abcdef", "-c", "/w", "codex"]
        refused = subprocess.CompletedProcess(argv, 1, "", "duplicate session: convoy-t-x-abcdef\n")
        with mock.patch("convoy.targeted_launch.subprocess.run", return_value=refused) as run, \
                mock.patch("convoy.targeted_launch.subprocess.Popen") as popen:
            card = active_pane_runner(argv)
        popen.assert_not_called()
        self.assertEqual(run.call_count, 1)
        self.assertFalse(card["ok"])
        self.assertIn("duplicate session", card["error"])
        made = subprocess.CompletedProcess(argv, 0, "", "")
        with mock.patch("convoy.targeted_launch.subprocess.run", return_value=made), \
                mock.patch("convoy.targeted_launch.subprocess.Popen") as popen:
            self.assertTrue(active_pane_runner(argv)["ok"])
        popen.assert_not_called()

    def test_a_refused_new_session_leaves_the_card_not_launched_with_tmuxs_words(self):
        self.runner.return_value = {"ok": False, "error": "tmux new-session exited 1: duplicate session: x"}
        card = self.add("codex", where=TMUX_OUTSIDE)
        self.assertFalse(card["ok"])
        self.assertFalse(card["launched"])
        self.assertIn("duplicate session", card["error"])
        self.assertNotIn("attach", card)


class EveryPrintedRecoveryLaunches(AddBase):
    """The retry a partial or consent card prints is run as printed, against
    mocked runners, and must launch."""

    def _retry(self, verb, env):
        pane, window = mock.Mock(return_value={"ok": True, "pid": 1}), mock.Mock(return_value={"ok": True, "pid": 2})
        # The CLI looks tmux up on PATH: a stand-in file the mocked runner never executes.
        tools = Path(tempfile.mkdtemp())
        for name in ("tmux", "tmux.exe"):
            (tools / name).write_text("", encoding="utf-8")
            (tools / name).chmod(0o755)
        path = str(tools) + os.pathsep + os.environ.get("PATH", "")
        with _no_terminal_env(), mock.patch.dict(os.environ, {**env, "PATH": path}), \
                mock.patch("convoy.cli.active_pane_runner", pane), mock.patch("convoy.cli.live_runner", window):
            rc, card = _cli(self.root, *shlex.split(verb))
        return rc, card, pane, window

    def test_split_retry_carries_the_unverified_override(self):
        self.runner.return_value = {"ok": False, "error": "adapter refused"}
        card = self.add("agy", where=TMUX, allow_unverified_launch=True)
        self.assertTrue(card["partial"], card)
        verb = card["recovery"][0]["verb"]
        self.assertIn("--allow-unverified-launch", verb)
        rc, out, pane, window = self._retry(verb, TMUX["env"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(pane.call_count, 1)
        window.assert_not_called()

    def test_thread_window_retry_launches_that_one_chair_into_the_threads_window(self):
        first = self.add("codex", where=WINDOWS_NO_WT_SESSION)
        self.assertTrue(first["ok"], first)
        self.runner.return_value = {"ok": False, "error": "wt refused"}
        card = self.add("agy", where=WINDOWS_NO_WT_SESSION, allow_unverified_launch=True)
        self.assertTrue(card["partial"], card)
        sid = card["seats"][0]["session_id"]
        verb = card["recovery"][0]["verb"]
        self.assertIn("--allow-unverified-launch", verb)
        if os.name != "nt":
            self.skipTest("the CLI retry places by this machine's platform; the thread window is Windows")
        tools = Path(tempfile.mkdtemp())
        (tools / "wt.exe").write_text("", encoding="utf-8")   # looked up on PATH; the mocked runner never runs it
        rc, out, pane, window = self._retry(verb, {"PATH": str(tools) + os.pathsep + os.environ.get("PATH", "")})
        self.assertEqual(rc, 0, out)
        window.assert_not_called()
        self.assertEqual(pane.call_count, 1)
        argv = [str(a) for a in pane.call_args[0][0]]
        self.assertEqual(argv[1:3], ["-w", card["window"]])
        self.assertIn(sid, " ".join(argv))
        self.assertNotIn(first["seats"][0]["session_id"], " ".join(argv))

    def test_consent_retry_carries_the_override_and_launches_after_the_grant(self):
        card = self.add("grok", where=TMUX, allow_unverified_launch=True, trust_probe=lambda _row: False)
        self.assertEqual(card["next"], "consent", card)
        self.assertFalse(card["launched"])
        self.assertIn("consent_request", card)
        request = card["consent_request"]["request_id"]
        recovery = card["recovery"][0]
        self.assertEqual(recovery["grant"], "consent --grant " + request)
        verb = recovery["verb"]
        self.assertIn("--allow-unverified-launch", verb)
        self.assertIn("--consent <consent>", verb)
        rc, granted = _cli(self.root, *shlex.split(recovery["grant"]))
        self.assertEqual(rc, 0, granted)
        untrusted = subprocess.CompletedProcess(["grok", "inspect"], 0, "Project trusted: no\n", "")
        with mock.patch("convoy.targeted_launch.subprocess.run", return_value=untrusted):
            rc, out, pane, _window = self._retry(verb.replace("<consent>", granted["consent"]), TMUX["env"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(pane.call_count, 1)


class AddDryRunShowsWhatItWouldRun(AddBase):
    def test_dry_run_in_tmux_outside_reports_argv_session_and_attach(self):
        card = _add(self.root, "codex", **TMUX_OUTSIDE)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "detached")
        self.assertIn("argv", card)
        argv = [str(a) for a in card["argv"]]
        self.assertEqual(argv[1:5], ["new-session", "-d", "-s", card["session_name"]])
        self.assertEqual(card["attach"], "tmux attach -t =" + card["session_name"])
        self.assertEqual(work_seats(self.root), [])

    def test_dry_run_in_windows_terminal_reports_the_thread_window_argv(self):
        card = _add(self.root, "codex", **WT)
        self.assertTrue(card["ok"], card)
        self.assertIn("argv", card)
        self.assertEqual([str(a) for a in card["argv"]][1:4], ["-w", card["window"], "new-tab"])
        self.assertNotIn("attach", card)

    def test_dry_run_refuses_a_title_the_live_run_would_refuse(self):
        card = _add(self.root, "codex", title="a b", **WT)
        self.assertFalse(card["ok"])
        self.assertIn("refuse seat name", card["error"])


class LaunchSurfacesNameTheDetachedPlacement(unittest.TestCase):
    def test_launch_help_names_split_and_detached(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            main(["launch", "--help"])
        text = " ".join(out.getvalue().split())
        self.assertIn("detached tmux session", text)

    def test_mcp_launch_tool_names_split_and_detached(self):
        from convoy.mcp_http import TOOLS
        tool = [t for t in TOOLS if t["name"] == "launch"][0]
        self.assertIn("detached tmux session", tool["description"])


class AddWithTheRealFirstRun(unittest.TestCase):
    """No first-run mock: the person's repo gets nothing; first-run files land
    in the minted worktree and home files in the sandboxed home."""

    def test_nothing_lands_in_the_persons_repo(self):
        root = _git_repo()
        ensure_id(root)
        bind(root, "first-run-t")
        home = Path(tempfile.mkdtemp())

        def tree(path):
            return sorted(str(p.relative_to(path)) for p in path.rglob("*")
                          if ".git" not in p.relative_to(path).parts and ".convoy" not in p.relative_to(path).parts)

        before = tree(root)
        runner = mock.Mock(return_value={"ok": True, "pid": 7})
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), \
                mock.patch("convoy.bringup.shutil.which", side_effect=_harness_which):
            card = _add(root, "codex", runner=runner, window_runner=mock.Mock(), **TMUX)
        self.assertTrue(card["ok"], card)
        self.assertIn("first_run", card["launch"])
        self.assertEqual(tree(root), before)
        status = _git("status", "--porcelain", "--untracked-files=all", cwd=root).stdout
        self.assertEqual([line for line in status.splitlines() if ".convoy" not in line], [])
        worktree = Path(card["seats"][0]["worktree"])
        self.assertTrue((worktree / "AGENTS.md").is_file(), sorted(p.name for p in worktree.iterdir()))
        self.assertTrue((worktree / ".codex").is_dir(), sorted(p.name for p in worktree.iterdir()))


class BringUpSeatFilter(AddBase):
    def test_an_unknown_seat_refuses_instead_of_an_empty_success(self):
        window = mock.Mock(return_value={"ok": True, "pid": 2})
        with mock.patch("convoy.cli.live_runner", window):
            rc, card = _cli(self.root, "bring-up", "--seat", "no-such-chair")
        self.assertEqual(rc, 1, card)
        self.assertFalse(card["ok"])
        self.assertIn("unknown seat: no-such-chair", card["error"])
        window.assert_not_called()


class DetachedTimeoutSaysABodyMayExist(unittest.TestCase):
    def test_a_new_session_that_does_not_answer_points_at_tmux_ls_and_the_attach(self):
        from convoy.targeted_launch import active_pane_runner
        argv = ["/usr/bin/tmux", "new-session", "-d", "-s", "convoy-t-x-abcdef", "-c", "/w", "codex"]
        with mock.patch("convoy.targeted_launch.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(argv, 30)), \
                mock.patch("convoy.targeted_launch.subprocess.Popen") as popen:
            card = active_pane_runner(argv)
        popen.assert_not_called()
        self.assertFalse(card["ok"])
        self.assertIn("tmux did not answer in 30 s; a session may exist: tmux ls", card["error"])
        self.assertIn("tmux attach -t =convoy-t-x-abcdef", card["error"])


if __name__ == "__main__":
    unittest.main()
