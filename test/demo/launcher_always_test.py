"""Every launch records a proven launcher, so messages can flow back.

A neuron with no recorded launcher has nobody to report to. So add, crew, launch,
join --launch and bring-up refuse before any write when the launching session cannot be
proven (a cwd match only, a script, a conflict, an unreadable process table), with the error
"cannot prove who is launching" and a `next` saying how to run it from an agent session or
attach first. A dry run reports `would_refuse` with the same reason. `launched_by: null` is no
longer produced by any launch.

Every id is synthetic; roots and the Convoy home are temporary; no harness or terminal runs.
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

from convoy.cli import main  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, seat  # noqa: E402
from convoy.lifecycle import join, lead_state  # noqa: E402

FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}
UNPROVEN = {"kind": "unproven", "chair": None, "via": None, "why": "only a cwd match names chair x"}
WT = {"env": {"WT_SESSION": "x"}, "platform_name": "nt"}


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _which(name):
    return "C:\\Tools\\" + str(name).lower().removesuffix(".exe") + ".exe"


class Base(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-always-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "always")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which})):
            q = mock.patch(target, **kw)
            q.start()
            self.addCleanup(q.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def minted(self):
        return [p for p in self.root.parent.iterdir() if p.name.startswith(self.root.name + "-wt-")]

    def claims(self):
        d = self.root / ".convoy" / "launch-claims"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def assertRefusedUnproven(self, card):
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "cannot prove who is launching")
        self.assertIn("convoy attach", card["next"])
        self.assertIn("agent session", card["next"])


class AnUnprovenLauncherRefusesBeforeAnyWrite(Base):
    def test_add_refuses_and_writes_nothing(self):
        from convoy.crew import add
        card = add(self.root, "codex", None, runner=self.runner, window_runner=self.runner, which=_which,
                   launcher=dict(UNPROVEN), **WT)
        self.assertRefusedUnproven(card)
        self.assertEqual(list_seats(self.root), [])
        self.assertEqual(self.minted(), [])
        self.assertEqual(self.claims(), [])
        self.assertEqual(lead_state(self.root)["status"], "none")
        self.runner.assert_not_called()

    def test_a_dry_add_says_would_refuse(self):
        from convoy.crew import add
        card = add(self.root, "codex", None, runner=None, which=_which, launcher=dict(UNPROVEN), **WT)
        self.assertEqual(card["would_refuse"], "cannot prove who is launching")
        self.assertIn("convoy attach", card["next"])
        self.assertEqual(list_seats(self.root), [])

    def test_crew_refuses_and_writes_nothing(self):
        from convoy.crew import crew
        card = crew(self.root, [{"harness": "codex"}], launcher=dict(UNPROVEN))
        self.assertRefusedUnproven(card)
        self.assertEqual(list_seats(self.root), [])
        self.assertEqual(self.minted(), [])

    def test_launch_refuses_and_writes_nothing(self):
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        with mock.patch("convoy.cli.resolve_launcher", return_value=dict(UNPROVEN)), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch:
            rc, card = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 1, card)
        self.assertRefusedUnproven(card)
        launch.assert_not_called()
        self.assertNotIn("launched_by", list_seats(self.root)[0])
        self.assertEqual(self.claims(), [])

    def test_a_dry_launch_says_would_refuse(self):
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        with mock.patch("convoy.cli.resolve_launcher", return_value=dict(UNPROVEN)):
            rc, card = self.cli("launch", "--seat", "fresh", "--dry-run")
        self.assertEqual(card["would_refuse"], "cannot prove who is launching")

    def test_join_launch_refuses_before_the_join(self):
        with mock.patch("convoy.cli.resolve_launcher", return_value=dict(UNPROVEN)), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch:
            rc, card = self.cli("join", "--to", "codex", "--session-id", "new-chair",
                                "--worktree", str(Path(tempfile.mkdtemp())), "--launch")
        self.assertEqual(rc, 1, card)
        self.assertRefusedUnproven(card)
        launch.assert_not_called()
        self.assertEqual(list_seats(self.root), [])

    def test_bring_up_of_a_pending_chair_refuses_and_writes_nothing(self):
        join(self.root, "codex", session_id="fresh", worktree=str(Path(tempfile.mkdtemp())))
        window = mock.Mock(return_value={"ok": True, "pid": 1})
        with mock.patch("convoy.cli.resolve_launcher", return_value=dict(UNPROVEN)), \
             mock.patch("convoy.cli.live_runner", window):
            rc, card = self.cli("bring-up")
        self.assertEqual(rc, 1, card)
        self.assertRefusedUnproven(card)
        window.assert_not_called()
        self.assertEqual(self.claims(), [])


class ALaunchAlwaysNamesItsLauncher(Base):
    def test_no_launch_path_records_a_null_launcher(self):
        from convoy.launcher import seat_launcher
        with self.assertRaises(ValueError):
            seat_launcher(self.root, dict(UNPROVEN))

    def test_a_legacy_null_launcher_points_at_adopt(self):
        from convoy.activity import neuron_id
        from convoy.convoy import read_id, update_seat
        from convoy.launcher import identity_sentence
        join(self.root, "codex", session_id="legacy", worktree=str(Path(tempfile.mkdtemp())))
        update_seat(self.root, "legacy", launched_by=None, launched_by_why="an older launch")
        text = identity_sentence(self.root, "legacy")
        self.assertNotIn("unknown", text)
        self.assertIn("convoy adopt --id " + neuron_id(read_id(self.root), "legacy"), text)


CONDUCTOR = {"kind": "conductor", "name": "grok-bot", "via": "bearer", "why": None}


class NoCallerCanBypassTheLauncher(Base):
    def test_add_with_no_launcher_refuses(self):
        from convoy.crew import add
        card = add(self.root, "codex", None, runner=self.runner, window_runner=self.runner, which=_which, **WT)
        self.assertRefusedUnproven(card)
        self.assertEqual(list_seats(self.root), [])

    def test_crew_with_no_launcher_refuses(self):
        from convoy.crew import crew
        card = crew(self.root, [{"harness": "codex"}])
        self.assertRefusedUnproven(card)
        self.assertEqual(list_seats(self.root), [])

    def test_a_conductor_launcher_is_accepted_and_recorded(self):
        from convoy.crew import add
        card = add(self.root, "codex", None, runner=self.runner, window_runner=self.runner, which=_which,
                   launcher=dict(CONDUCTOR), **WT)
        self.assertTrue(card["ok"], card)
        self.assertEqual(list_seats(self.root)[0]["launched_by"], {"kind": "conductor", "name": "grok-bot"})

    def test_a_relaunch_of_a_legacy_null_launcher_says_not_recorded_and_adopt(self):
        from convoy.convoy import update_seat
        from convoy.relaunch import relaunch_prompt
        join(self.root, "codex", session_id="legacy", worktree=str(Path(tempfile.mkdtemp())))
        update_seat(self.root, "legacy", launched_by=None)
        prompt = relaunch_prompt(self.root, "legacy", token="0" * 32, incarnation=2, now="t", since="s", worktree="w")
        self.assertIn("not recorded", prompt)
        self.assertIn("convoy adopt --id", prompt)


class AWorktreeServesOneThread(Base):
    def test_a_chair_is_not_seated_in_another_threads_worktree(self):
        from convoy.inbox import write_root_pointer
        other = _git_repo()
        ensure_id(other)
        bind(other, "other-thread")
        shared = Path(tempfile.mkdtemp())
        write_root_pointer(shared, other)   # this worktree already serves the other thread
        with self.assertRaises(ValueError) as ctx:
            join(self.root, "codex", session_id="intruder", worktree=str(shared))
        self.assertIn("serves thread", str(ctx.exception))
        self.assertEqual(list_seats(self.root), [])

    def test_join_launch_into_another_threads_worktree_refuses_with_the_reason(self):
        from convoy.inbox import write_root_pointer
        other = _git_repo()
        ensure_id(other)
        bind(other, "other-thread")
        shared = Path(tempfile.mkdtemp())
        write_root_pointer(shared, other)
        seated = {"kind": "seated", "chair": "x", "via": "environment", "why": None}
        with mock.patch("convoy.cli.resolve_launcher", return_value=seated), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch:
            rc, card = self.cli("join", "--to", "codex", "--session-id", "intruder", "--worktree", str(shared), "--launch")
        self.assertEqual(rc, 1, card)
        self.assertIn("serves thread", card["error"])
        launch.assert_not_called()


class ASwapNamesNoStaleLauncher(Base):
    def test_the_new_occupants_prompt_says_the_launcher_is_recorded_at_launch(self):
        from convoy.convoy import update_seat
        from convoy.lifecycle import swap
        seat(self.root, "claude", "old-launcher", worktree=str(Path(tempfile.mkdtemp())), resume="old-native")
        seat(self.root, "codex", "chair", worktree=str(Path(tempfile.mkdtemp())), resume="chair-native")
        update_seat(self.root, "chair", launched_by="old-launcher")
        handoff = Path(tempfile.mkdtemp()) / "handoff.md"
        handoff.write_text("synthetic\n", encoding="utf-8")
        card = swap(self.root, "chair", to="claude", handoff=str(handoff), author="chair")
        prompt = card["seat"]["boot_prompt"]
        self.assertNotIn("old-launcher", prompt)
        self.assertIn("Launched by: recorded when this chair is launched", prompt)

    def test_the_launch_after_a_swap_records_its_launcher(self):
        from convoy.convoy import update_seat
        from convoy.lifecycle import swap
        seat(self.root, "claude", "old-launcher", worktree=str(Path(tempfile.mkdtemp())), resume="old-native")
        seat(self.root, "claude", "new-launcher", worktree=str(Path(tempfile.mkdtemp())), resume="new-native")
        seat(self.root, "codex", "chair", worktree=str(Path(tempfile.mkdtemp())), resume="chair-native")
        update_seat(self.root, "chair", launched_by="old-launcher")
        handoff = Path(tempfile.mkdtemp()) / "handoff.md"
        handoff.write_text("synthetic\n", encoding="utf-8")
        swap(self.root, "chair", to="claude", handoff=str(handoff), author="chair")
        seated = {"kind": "seated", "chair": "new-launcher", "via": "environment", "why": None}
        with mock.patch("convoy.cli.resolve_launcher", return_value=seated), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}):
            rc, card = self.cli("launch", "--seat", "chair")
        self.assertEqual(rc, 0, card)
        row = next(s for s in list_seats(self.root) if s["session_id"] == "chair")
        self.assertEqual(row["launched_by"], "new-launcher")


class AChairLauncherMustBeSeatedHere(Base):
    def test_a_chair_launcher_that_is_not_a_seat_on_this_thread_refuses(self):
        from convoy.launcher import seat_launcher
        with self.assertRaises(ValueError) as ctx:
            seat_launcher(self.root, {"kind": "seated", "chair": "nobody-here", "via": "environment", "why": None})
        self.assertIn("not a seated chair", str(ctx.exception))

    def test_a_detached_chair_launcher_refuses(self):
        from convoy.convoy import update_seat
        from convoy.launcher import seat_launcher
        seat(self.root, "claude", "gone-chair", worktree=str(Path(tempfile.mkdtemp())), resume="gone-native")
        update_seat(self.root, "gone-chair", detached=True)
        with self.assertRaises(ValueError):
            seat_launcher(self.root, {"kind": "seated", "chair": "gone-chair", "via": "environment", "why": None})


if __name__ == "__main__":
    unittest.main()
