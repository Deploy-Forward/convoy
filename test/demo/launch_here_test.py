"""`add --here` / `launch --here`: an opt-in split of the person's own window.

Since the thread window, every Windows launch goes to `wt -w convoy-<8 hex>` and `-w 0`
(the most recently used window, i.e. wherever the person is) is refused. `--here` is the
explicit opt-in to exactly that: `wt -w 0 split-pane -V -d <worktree> <host argv>`, never
new-tab, never `--`. Inside tmux it is the existing split of the caller's pane. Anywhere
else it refuses, naming thread-window and detached, before anything is written. The card
says `placement: here`. The default is unchanged: without --here, -w 0 still refuses.

Runners are mocks and which() answers fakes: no test executes a real wt or tmux.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_fixture import seated_launcher, work_seats  # noqa: E402

from convoy.convoy import bind, ensure_id, list_seats, read_id  # noqa: E402
from convoy.lifecycle import join  # noqa: E402

FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}


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
    return "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"


def _terminal_which(*present):
    names = {str(n).lower() for n in present}

    def lookup(name):
        key = str(name).lower().removesuffix(".exe")
        return ("C:\\Tools\\" + key + ".exe" if key == "wt" else "/usr/bin/" + key) if key in names else None

    return lookup


WT = {"env": {"WT_SESSION": "the-callers-window"}, "which": _terminal_which("wt"), "platform_name": "nt"}
NO_WT = {"env": {}, "which": _terminal_which(), "platform_name": "nt"}
TMUX = {"env": {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7"}, "which": _terminal_which("tmux"),
        "platform_name": "posix"}
TMUX_OUTSIDE = {"env": {"TERM": "xterm-256color"}, "which": _terminal_which("tmux"), "platform_name": "posix"}
BARE_POSIX = {"env": {}, "which": _terminal_which(), "platform_name": "posix"}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "here-a")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _harness_which})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def add(self, where, here=True, runner="live"):
        from convoy.crew import add
        return add(self.root, "codex", None, runner=self.runner if runner == "live" else None,
                   launcher=seated_launcher(self.root), here=here, **where)

    def argv(self):
        return [str(a) for a in self.runner.call_args[0][0]]

    def window_name(self):
        from convoy.targeted_launch import thread_window_name
        return thread_window_name(read_id(self.root))


class HereOnWindowsSplitsThePersonsWindow(Base):
    def test_the_argv_is_a_split_of_window_zero(self):
        card = self.add(WT)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "here")
        argv = self.argv()
        self.assertEqual(argv[1:5], ["-w", "0", "split-pane", "-V"])
        self.assertNotIn("new-tab", argv)
        self.assertNotIn("nt", argv)
        self.assertNotIn("--", argv)
        self.assertNotIn(self.window_name(), argv, "a here launch never names the thread's window")
        worktree = card["seats"][0]["worktree"]
        self.assertEqual(argv[argv.index("-d") + 1], worktree)
        self.assertNotIn("window", card)
        self.assertNotIn("attach", card)
        self.assertIn("--here", card["placement_reason"])

    def test_the_second_neuron_also_splits_window_zero_never_the_threads_window(self):
        from convoy.targeted_launch import take_launch_claim, _claim_path
        first = self.add(WT)
        sid = first["seats"][0]["session_id"]
        _claim_path(self.root, sid).unlink(missing_ok=True)
        take_launch_claim(self.root, sid, host_pid=os.getpid())
        second = self.add(WT)
        self.assertTrue(second["ok"], second)
        self.assertEqual(self.argv()[1:4], ["-w", "0", "split-pane"])

    def test_the_card_records_the_placement_on_the_launch(self):
        card = self.add(WT)
        self.assertEqual(card["launch"]["placement"], "here")
        self.assertEqual(card["launch"]["adapter"], "windows-terminal-here")
        self.assertEqual(card["launch"]["target"], "0")

    def test_without_the_opt_in_the_default_is_still_the_threads_window(self):
        card = self.add(WT, here=False)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(self.argv()[1:4], ["-w", self.window_name(), "new-tab"])

    def test_here_without_windows_terminal_refuses_before_any_write(self):
        card = self.add(NO_WT)
        self.assertFalse(card["ok"])
        self.assertEqual(card["placement"], "none")
        self.assertIn("thread-window", card["error"])
        self.assertIn("detached", card["error"])
        self.assertEqual(work_seats(self.root), [])
        self.runner.assert_not_called()


class HereOnPosix(Base):
    def test_inside_tmux_here_is_the_existing_split_of_the_callers_pane(self):
        card = self.add(TMUX)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "here")
        argv = self.argv()
        self.assertEqual(argv[1:4], ["split-window", "-t", "%7"])
        self.assertNotIn("attach", card)

    def test_outside_tmux_here_refuses_and_names_the_alternatives(self):
        for where in (TMUX_OUTSIDE, BARE_POSIX):
            self.runner.reset_mock()
            card = self.add(where)
            self.assertFalse(card["ok"], card)
            self.assertEqual(card["placement"], "none")
            self.assertIn("thread-window", card["error"])
            self.assertIn("detached", card["error"])
            self.assertEqual(work_seats(self.root), [], "refused before any write")
            self.runner.assert_not_called()

    def test_without_here_outside_tmux_is_still_the_detached_session(self):
        card = self.add(TMUX_OUTSIDE, here=False)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "detached")


class TheWindowZeroRefusalStillFiresForEveryOtherPlacement(Base):
    def seat(self):
        return {"to": "codex", "session_id": "s", "worktree": str(Path(tempfile.mkdtemp()))}

    def test_the_window_builder_refuses_window_zero_unless_here(self):
        from convoy.bringup import isolated_wt_argv
        with self.assertRaises(ValueError):
            isolated_wt_argv("t", [self.seat()], wt="C:\\Tools\\wt.exe", window="0")
        with self.assertRaises(ValueError):
            isolated_wt_argv("0", [self.seat()], wt="C:\\Tools\\wt.exe")
        argv = isolated_wt_argv("t", [self.seat()], wt="C:\\Tools\\wt.exe", window="0", here=True)
        self.assertEqual(argv[1:5], ["C:\\Tools\\wt.exe", "-w", "0", "split-pane"][1:] + ["-V"])
        self.assertNotIn("new-tab", argv)
        self.assertNotIn("--", argv)

    def test_the_wt_validator_refuses_window_zero_unless_here(self):
        from convoy.bringup import _check_thread_window
        tail = ["--title", "t", "-d", "C:\\w", "C:\\Tools\\codex.exe"]
        with self.assertRaises(ValueError):
            _check_thread_window(["wt", "-w", "0", "split-pane", "-V", *tail])
        _check_thread_window(["wt", "-w", "0", "split-pane", "-V", *tail], here=True)
        with self.assertRaises(ValueError):
            _check_thread_window(["wt", "-w", "0", "new-tab", *tail], here=True)
        with self.assertRaises(ValueError):
            _check_thread_window(["wt", "-w", "convoy-0a1b2c3d", "split-pane", "-V", *tail], here=True)

    def test_the_pane_builder_refuses_window_zero_for_the_thread_window_adapter(self):
        from convoy.targeted_launch import active_pane_argv, terminal_capability
        row = join(self.root, "codex", session_id="p", worktree=str(Path(tempfile.mkdtemp())))["seat"]
        thread = terminal_capability(**WT)
        with self.assertRaises(ValueError):
            active_pane_argv(row, {**thread, "target": "0", "first": False})
        here = terminal_capability(**WT, here=True)
        self.assertEqual(here["adapter"], "windows-terminal-here")
        with self.assertRaises(ValueError):
            active_pane_argv(row, {**here, "target": "convoy-0a1b2c3d"})
        argv = active_pane_argv(row, here)
        self.assertEqual(argv[1:5], ["-w", "0", "split-pane", "-V"])


class DryRunPrintsTheExactArgv(Base):
    def test_a_dry_add_reports_the_here_argv_and_writes_nothing(self):
        card = self.add(WT, runner=None)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["dry_run"])
        self.assertEqual(card["placement"], "here")
        argv = [str(a) for a in card["argv"]]
        self.assertEqual(argv[1:5], ["-w", "0", "split-pane", "-V"])
        self.assertEqual(argv[argv.index("-d") + 1], card["worktree"])
        self.assertNotIn("new-tab", argv)
        self.assertNotIn("window", card)
        self.assertEqual(work_seats(self.root), [])

    def test_a_dry_launch_reports_the_here_argv(self):
        from convoy.targeted_launch import launch_seat
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        card = launch_seat(self.root, "fresh", runner=None, here=True, **WT)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "here")
        self.assertEqual([str(a) for a in card["argv"]][1:5], ["-w", "0", "split-pane", "-V"])
        self.assertNotIn("window", card)
        self.assertNotIn("attach", card)

    def test_a_dry_launch_outside_tmux_refuses_with_the_alternatives(self):
        from convoy.targeted_launch import launch_seat
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        card = launch_seat(self.root, "fresh", runner=None, here=True, **TMUX_OUTSIDE)
        self.assertFalse(card["ok"])
        self.assertIn("thread-window", card["error"])
        self.assertIn("detached", card["error"])

    def test_the_cli_flag_reaches_add_and_launch(self):
        from convoy.cli import main
        with mock.patch("convoy.cli.add_neuron", return_value={"ok": True}) as add, \
                mock.patch("convoy.cli.resolve_launcher", return_value=seated_launcher(self.root)):
            with redirect_stdout(io.StringIO()):
                main(["--root", str(self.root), "add", "codex", "--dry-run", "--here"])
        self.assertTrue(add.call_args.kwargs["here"])
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        with mock.patch("convoy.cli.launch_seat", return_value={"ok": True, "session_id": "fresh"}) as launch:
            out = io.StringIO()
            with redirect_stdout(out):
                main(["--root", str(self.root), "launch", "--seat", "fresh", "--dry-run", "--here"])
        self.assertTrue(launch.call_args.kwargs["here"])
        self.assertTrue(json.loads(out.getvalue().strip().splitlines()[-1])["ok"])


class TheMcpLaunchToolTakesHere(unittest.TestCase):
    def test_here_is_plumbed_to_launch_seat(self):
        from convoy import mcp_http
        root = _git_repo()
        ensure_id(root)
        bind(root, "here-mcp")
        join(root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        tool = next(t for t in mcp_http.TOOLS if t["name"] == "launch")
        self.assertEqual(tool["inputSchema"]["properties"]["here"]["type"], "boolean")
        with mock.patch.object(mcp_http, "launch_seat", return_value={"ok": True}) as launch, \
                mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True), \
                mock.patch.object(mcp_http, "_launch_launcher", return_value={"kind": "conductor", "name": "c"}), \
                mock.patch.object(mcp_http, "_record_mcp_launcher", return_value=({}, {})), \
                mock.patch.object(mcp_http, "_settle_mcp_launcher"):
            mcp_http.call_tool(root, "launch", {"seat": "fresh", "here": True})
            self.assertTrue(launch.call_args.kwargs["here"])
            mcp_http.call_tool(root, "launch", {"seat": "fresh"})
            self.assertFalse(launch.call_args.kwargs["here"])


if __name__ == "__main__":
    unittest.main()
