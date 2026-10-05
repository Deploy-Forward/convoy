"""One terminal window per Convoy thread.

Windows Terminal's CLI cannot split a specific pane: `wt -w 0 split-pane` splits whichever
pane has focus in the most recently used window, so a neuron landed wherever the person last
clicked. Every launch on a thread now targets that thread's own named window,
`wt -w convoy-<8 hex of sha256(convoy_id)> ...`: the first neuron opens it with new-tab, later
ones split-pane inside it. Never window 0, never the caller's window, and WT_SESSION no longer
decides anything. tmux mirrors it outside tmux: one detached session per thread, the same name.

Runners are mocks and which() answers fakes: no test executes a real wt or tmux (and the
test guard refuses one if a test ever tried).
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_fixture import seated_launcher, widget_lead, with_seated_launcher  # noqa: E402

from convoy.convoy import bind, ensure_id, list_seats, read_id  # noqa: E402
from convoy.lifecycle import join  # noqa: E402

FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}
NAME = re.compile(r"^convoy-[0-9a-f]{8}$")


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
NO_WT_SESSION = {"env": {}, "which": _terminal_which("wt"), "platform_name": "nt"}
TMUX_OUTSIDE = {"env": {"TERM": "xterm-256color"}, "which": _terminal_which("tmux"), "platform_name": "posix"}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = self.thread("tw-a")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _harness_which})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        self.window_runner = mock.Mock(return_value={"ok": True, "pid": 4343})

    def thread(self, name):
        root = _git_repo()
        ensure_id(root)
        bind(root, name)
        return root

    def name_for(self, root):
        from convoy.targeted_launch import thread_window_name
        return thread_window_name(read_id(root))

    def add(self, where, root=None):
        from convoy.crew import add
        return add(root or self.root, "codex", None, runner=self.runner, window_runner=self.window_runner,
                   launcher=seated_launcher(root or self.root), **where)

    def argv(self):
        return [str(a) for a in self.runner.call_args[0][0]]

    def host_is_live(self, card):
        from convoy.targeted_launch import take_launch_claim, _claim_path
        sid = card["seats"][0]["session_id"]
        _claim_path(self.root, sid).unlink(missing_ok=True)
        take_launch_claim(self.root, sid, host_pid=os.getpid())


class TheThreadsOwnWindow(Base):
    def test_the_name_is_short_safe_and_derived_from_the_convoy_id(self):
        from convoy.targeted_launch import thread_window_name
        cid = read_id(self.root)
        name = thread_window_name(cid)
        self.assertRegex(name, NAME)
        self.assertEqual(name, "convoy-" + hashlib.sha256(cid.encode("utf-8")).hexdigest()[:8])
        self.assertEqual(thread_window_name(cid), name, "deterministic")

    def test_the_first_neuron_opens_the_threads_window_with_new_tab(self):
        card = self.add(WT)
        self.assertTrue(card["ok"], card)
        name = self.name_for(self.root)
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(card["window"], name)
        argv = self.argv()
        self.assertEqual(argv[1:4], ["-w", name, "new-tab"])
        self.assertNotIn("0", argv[1:3])
        self.window_runner.assert_not_called()
        self.assertNotIn("caller's active pane", card["placement_reason"])
        self.assertIn(name, card["placement_reason"])

    def test_the_second_neuron_splits_inside_the_same_window(self):
        first = self.add(WT)
        self.host_is_live(first)
        second = self.add(WT)
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["window"], first["window"])
        self.assertEqual(self.argv()[1:4], ["-w", first["window"], "split-pane"])

    def test_the_callers_windows_terminal_session_decides_nothing(self):
        card = self.add(NO_WT_SESSION)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(self.argv()[1:4], ["-w", self.name_for(self.root), "new-tab"])
        self.window_runner.assert_not_called()

    def test_a_different_thread_gets_a_different_window(self):
        other = self.thread("tw-b")
        self.add(WT)
        mine = self.argv()[2]
        self.add(WT, root=other)
        theirs = self.argv()[2]
        self.assertNotEqual(mine, theirs)
        self.assertEqual(theirs, self.name_for(other))

    def test_a_dry_add_shows_the_same_argv_and_window(self):
        from convoy.crew import add
        card = add(self.root, "codex", None, runner=None, launcher=seated_launcher(self.root), **WT)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["placement"], "thread-window")
        self.assertEqual(card["window"], self.name_for(self.root))
        self.assertEqual([str(a) for a in card["argv"]][1:4], ["-w", self.name_for(self.root), "new-tab"])


class BringUpUsesTheThreadsWindow(Base):
    def test_bring_up_opens_the_threads_window_then_splits_inside_it(self):
        from convoy.bringup import bring_up
        for sid in ("one", "two"):
            join(self.root, "codex", session_id=sid, worktree=str(Path(tempfile.mkdtemp())))
        card = bring_up(self.root, runner=self.runner, session_ids=["one", "two"])
        self.assertTrue(card["ok"], card)
        argv = self.argv()
        name = self.name_for(self.root)
        self.assertEqual(argv[1:4], ["-w", name, "new-tab"])
        self.assertNotIn("--window", argv)
        self.assertIn("split-pane", argv)

    def test_a_bring_up_while_the_window_holds_a_live_neuron_splits_into_it(self):
        from convoy.bringup import bring_up
        from convoy.targeted_launch import take_launch_claim
        join(self.root, "codex", session_id="live", worktree=str(Path(tempfile.mkdtemp())))
        take_launch_claim(self.root, "live", host_pid=os.getpid())
        join(self.root, "codex", session_id="new", worktree=str(Path(tempfile.mkdtemp())))
        card = bring_up(self.root, runner=self.runner, session_ids=["new"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.argv()[1:4], ["-w", self.name_for(self.root), "split-pane"])

    def test_the_window_builder_refuses_window_zero(self):
        from convoy.bringup import isolated_wt_argv
        seat = {"to": "codex", "session_id": "s", "worktree": str(Path(tempfile.mkdtemp()))}
        with self.assertRaises(ValueError):
            isolated_wt_argv("t", [seat], wt="C:\\Tools\\wt.exe", window="0")


class TmuxMirrorsIt(Base):
    def test_one_detached_session_per_thread_first_new_then_split(self):
        first = self.add(TMUX_OUTSIDE)
        self.assertTrue(first["ok"], first)
        name = self.name_for(self.root)
        self.assertEqual(first["placement"], "detached")
        self.assertEqual(self.argv()[1:5], ["new-session", "-d", "-s", name])
        self.host_is_live(first)
        second = self.add(TMUX_OUTSIDE)
        self.assertTrue(second["ok"], second)
        self.assertEqual(self.argv()[1:3], ["split-window", "-t"])
        self.assertEqual(self.argv()[3], "=" + name + ":")


class TheWindowNamesTheThread(Base):
    """The thread window's tab shows the focused pane's title, so every pane title there is
    `<thread label> - <chair title>`. The label is the bound thread name, else the repo folder
    name, plus `-<4 hex of the window id>` so it is unique per thread (two repos with one folder
    name never share it); with neither name it is the window's 8 hex. ASCII, at most 24
    characters (the name is trimmed, never the hex), never a cvy_ id or a path."""

    def titles(self, argv=None):
        argv = argv or self.argv()
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--title"]

    def hex4(self, root=None):
        return self.name_for(root or self.root).removeprefix("convoy-")[:4]

    def test_the_first_and_second_neuron_carry_the_thread_label(self):
        first = self.add(WT)
        label = "tw-a-" + self.hex4()
        self.assertEqual(self.titles(), [label + " - codex-1"])
        self.host_is_live(first)
        self.add(WT)
        self.assertEqual(self.titles(), [label + " - codex-2"])

    def test_an_unbound_thread_is_labelled_by_its_repo_folder(self):
        root = _git_repo()
        ensure_id(root)          # what `start` does without a thread name: no bound name
        self.add(WT, root=root)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-")[:19].strip("-")
        self.assertEqual(self.titles(), [stem + "-" + self.hex4(root) + " - codex-1"])

    def test_the_label_is_never_an_id_or_a_path_and_falls_back_to_the_window_hex(self):
        from convoy.targeted_launch import thread_label
        cid = read_id(self.root)
        hexpart = self.name_for(self.root).removeprefix("convoy-")
        h4 = hexpart[:4]
        self.assertEqual(thread_label("tw-a", "folder", cid), "tw-a-" + h4)
        self.assertEqual(thread_label(None, "folder", cid), "folder-" + h4)
        self.assertEqual(thread_label(cid, "", cid), hexpart, "a cvy_ id is never a label")
        self.assertEqual(thread_label("C:/work/repo", "", cid), hexpart, "a path is never a label")
        self.assertEqual(thread_label("D:\\work\\repo", "", cid), hexpart, "a path is never a label")
        long = thread_label("a" * 60, "", cid)
        self.assertEqual(len(long), 24, "the name is trimmed to fit")
        self.assertTrue(long.endswith("-" + h4), "never the hex")
        self.assertTrue(long.isascii())
        self.assertEqual(thread_label("caf\u00e9 r\u00e9po", "", cid), "caf-r-po-" + h4)

    def test_two_repos_with_one_folder_name_get_different_labels(self):
        from convoy.targeted_launch import root_thread_label
        roots = []
        for base in (Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())):
            root = base / "demo"
            root.mkdir()
            ensure_id(root)
            roots.append(root)
        a, b = (root_thread_label(r) for r in roots)
        self.assertTrue(a.startswith("demo-") and b.startswith("demo-"))
        self.assertNotEqual(a, b)

    def test_bring_up_titles_carry_the_thread_label(self):
        from convoy.bringup import bring_up
        for sid, title in (("one", "alpha"), ("two", "beta")):
            join(self.root, "codex", session_id=sid, title=title, worktree=str(Path(tempfile.mkdtemp())))
        bring_up(self.root, runner=self.runner, session_ids=["one", "two"])
        label = "tw-a-" + self.hex4()
        self.assertEqual(self.titles(), [label + " - alpha", label + " - beta"])
        for title in self.titles():
            self.assertNotIn("cvy_", title)

    def test_the_tmux_session_window_is_named_for_the_thread(self):
        self.add(TMUX_OUTSIDE)
        self.assertEqual(self.argv()[5:7], ["-n", "tw-a-" + self.hex4() + " - codex-1"])


class OnlyTheChairsOwnTitleProvesIt(Base):
    """nudge and the wt walk prove a chair from a window title only by its OWN exact composed
    title (its thread's label and its own title), never by any label; a composed title never
    proves a chair through the old `<seat title> - ` prefix; two matching panes are ambiguous."""

    OWN = "demo-aaaa - reviewer"

    def seat(self, title="reviewer", pane_title=OWN):
        return {"title": title, "pane_title": pane_title, "worktree": ""}

    def test_the_chairs_own_composed_title_proves_it(self):
        from convoy.nudge import _match_window, _window_names_chair
        from convoy.wt_walk import pane_belongs_to
        self.assertTrue(_window_names_chair(self.OWN, "", "reviewer", self.OWN))
        self.assertEqual(pane_belongs_to(self.seat(), self.OWN), "seat-title")
        self.assertEqual(_match_window(self.seat(), [{"hwnd": 1, "title": self.OWN}])["hwnd"], 1)

    def test_another_threads_label_never_proves_the_chair(self):
        from convoy.nudge import _match_window, _window_names_chair
        from convoy.wt_walk import pane_belongs_to
        other = "other-bbbb - reviewer"
        self.assertFalse(_window_names_chair(other, "", "reviewer", self.OWN))
        self.assertIsNone(pane_belongs_to(self.seat(), other))
        windows = [{"hwnd": 1, "title": "demo-aaaa - builder"}, {"hwnd": 2, "title": other}]
        self.assertIsNone(_match_window(self.seat(), windows), "the other thread's window is never picked")

    def test_the_same_folder_in_two_repos_never_proves_the_other(self):
        from convoy.nudge import _match_window
        windows = [{"hwnd": 1, "title": "demo-aaaa - builder"}, {"hwnd": 2, "title": "demo-cccc - reviewer"}]
        self.assertIsNone(_match_window(self.seat(), windows))

    def test_a_chair_titled_like_a_label_matches_no_pane_of_that_window(self):
        from convoy.nudge import _window_names_chair
        from convoy.wt_walk import pane_belongs_to
        seat = self.seat(title="demo-aaaa", pane_title="demo-aaaa - demo-aaaa")
        for pane in ("demo-aaaa - a", "demo-aaaa - reviewer"):
            self.assertFalse(_window_names_chair(pane, "", "demo-aaaa", seat["pane_title"]), pane)
            self.assertIsNone(pane_belongs_to(seat, pane), pane)

    def test_near_misses_are_refused(self):
        from convoy.nudge import _window_names_chair
        for pane in ("demo-aaaa - reviewer2", "demo-aaaa - review", "demo-aaaa  - reviewer",
                     "please run demo-aaaa - reviewer now", "demo-aaaa - reviewer - extra"):
            self.assertFalse(_window_names_chair(pane, "", "reviewer", self.OWN), pane)

    def test_two_panes_with_the_chairs_title_are_ambiguous(self):
        from convoy.nudge import _match_window
        windows = [{"hwnd": 1, "title": self.OWN}, {"hwnd": 2, "title": self.OWN}]
        self.assertIsNone(_match_window(self.seat(), windows))

    def test_nudge_reads_the_chairs_own_composed_title_from_its_thread(self):
        from convoy.nudge import _seat_row
        from convoy.targeted_launch import root_thread_label
        join(self.root, "codex", session_id="n1", title="reviewer", worktree=str(Path(tempfile.mkdtemp())))
        row = _seat_row(self.root, "n1")
        self.assertEqual(row["pane_title"], root_thread_label(self.root) + " - reviewer")


if __name__ == "__main__":
    unittest.main()
