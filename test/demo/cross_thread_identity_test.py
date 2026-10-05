"""A session acts on one thread from another thread's folder, and adopts from a detached chair.

1. A session sits on several threads, so running `convoy --root <A> ...` from thread B's folder
   is normal. When the chair on A is proven by environment or token, the cwd walking into B is
   information, `cwd_thread_differs: {cwd_thread, root_thread, hint}`, not a conflict. Real
   disagreements still refuse: environment and token naming different chairs, or a cwd/worktree
   chair contradicting an environment chair on the same root.
2. `adopt` from a proven caller whose own chair on the thread is detached re-attaches that chair
   (the attach path, with its lead rules) and proceeds.
3. The relaxation needs an explicit --root, and the CLI carries it to every verb that resolves
   a caller: add's launcher, a send's sender, reply. A root inferred from the cwd, or from a
   neuron id (adopt --id), keeps the conflict visible.
4. A path proof never identifies a different session than the caller's native id proves.

Every id is synthetic; roots and the Convoy home are temporary; no harness runs.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import panes  # noqa: E402
from convoy.convoy import bind, list_seats, read_id, seat, update_seat  # noqa: E402
from convoy.layer import feed_since  # noqa: E402

NATIVE = "synthetic-session-native"
CHAIN = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
         {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]
EPOCH = "1970-01-01T00:00:00.000000Z"


class Base(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-xthread-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        self.a = Path(tempfile.mkdtemp(prefix="convoy-xthread-a-"))
        bind(self.a, "thread-a")
        self.b = Path(tempfile.mkdtemp(prefix="convoy-xthread-b-"))
        bind(self.b, "thread-b")

    def who(self, root, *, env, cwd, procs=CHAIN, explicit_root=True):
        return panes.identify(root, pid=21, procs=procs, cwd=str(cwd), env=env, explicit_root=explicit_root)


class ACwdInAnotherThreadIsInformation(Base):
    def test_an_environment_chair_on_a_from_bs_folder_is_proven_not_a_conflict(self):
        seat(self.a, "claude", "orch-a", worktree=tempfile.mkdtemp(), resume=NATIVE)
        me = self.who(self.a, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=self.b)
        self.assertTrue(me["ok"], me)
        self.assertEqual((me["chair"], me["via"]), ("orch-a", "environment"))
        self.assertFalse(me.get("conflict"), me)
        differs = me["cwd_thread_differs"]
        self.assertEqual((differs["cwd_thread"], differs["root_thread"]), ("thread-b", "thread-a"))
        self.assertIn("your cwd walks up to thread", differs["hint"])

    def test_the_launcher_resolves_it_as_seated(self):
        from convoy.launcher import resolve_launcher
        seat(self.a, "claude", "orch-a", worktree=tempfile.mkdtemp(), resume=NATIVE)
        out = resolve_launcher(self.a, procs=CHAIN, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=str(self.b), pid=21)
        self.assertEqual((out["kind"], out["chair"]), ("seated", "orch-a"), out)

    def test_environment_and_token_naming_different_chairs_still_refuse(self):
        seat(self.a, "claude", "env-chair", worktree=tempfile.mkdtemp(), resume=NATIVE)
        seat(self.a, "claude", "token-chair", worktree=tempfile.mkdtemp(), resume="synthetic-other-native")
        procs = [dict(CHAIN[0], cmdline="claude --resume synthetic-other-native"), CHAIN[1]]
        me = self.who(self.a, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=self.b, procs=procs)
        self.assertFalse(me["ok"], me)
        self.assertEqual(me["via"], "conflict")

    def test_a_cwd_chair_contradicting_an_environment_chair_on_the_same_root_still_refuses(self):
        wt = Path(tempfile.mkdtemp())
        seat(self.a, "claude", "env-chair", worktree=tempfile.mkdtemp(), resume=NATIVE)
        seat(self.a, "claude", "cwd-chair", worktree=str(wt))
        me = self.who(self.a, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=wt)
        self.assertFalse(me["ok"], me)
        self.assertEqual(me["via"], "conflict")


    def test_an_inferred_root_keeps_the_visible_warning(self):
        seat(self.a, "claude", "orch-a", worktree=tempfile.mkdtemp(), resume=NATIVE)
        me = self.who(self.a, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=self.b, explicit_root=False)
        self.assertTrue(me.get("conflict"), me)
        self.assertIn("your cwd walks up to thread", me["ask"])
        self.assertNotIn("cwd_thread_differs", me)

    def test_the_cli_passes_whether_root_was_explicit(self):
        from convoy.cli import main
        seen = []

        def spy(root, **kw):
            seen.append(kw.get("explicit_root"))
            return {"ok": False, "chair": None, "via": None}

        old = os.getcwd()
        os.chdir(self.b)
        self.addCleanup(os.chdir, old)
        with mock.patch("convoy.cli.identify", side_effect=spy), redirect_stdout(io.StringIO()):
            main(["--root", str(self.a), "whoami"])
            main(["whoami"])
        self.assertEqual(seen, [True, False])


class APathNeverProvesADifferentSession(Base):
    """The caller's native session X is a chair on thread A only. From thread B's worktree,
    whose chair is another session Y, a path proof (cwd, or the worktree in the argv) must not
    make X author as Y."""

    def setUp(self):
        super().setUp()
        seat(self.a, "claude", "x-on-a", worktree=tempfile.mkdtemp(), resume=NATIVE)
        self.wt_b = Path(tempfile.mkdtemp(prefix="convoy-xthread-wtb-"))
        seat(self.b, "claude", "y-on-b", worktree=str(self.wt_b), resume="synthetic-y-native")

    def test_a_cwd_proof_of_another_sessions_chair_refuses_naming_both(self):
        me = self.who(self.b, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=self.wt_b, explicit_root=False)
        self.assertFalse(me["ok"], me)
        self.assertEqual(me["via"], "conflict")
        self.assertIn("x-on-a", me["ask"])
        self.assertIn("y-on-b", me["ask"])

    def test_a_worktree_argv_proof_of_another_sessions_chair_refuses(self):
        procs = [dict(CHAIN[0], cmdline="claude --add-dir " + str(self.wt_b)), CHAIN[1]]
        me = self.who(self.b, env={"CLAUDE_CODE_SESSION_ID": NATIVE}, cwd=self.elsewhere(), procs=procs,
                      explicit_root=False)
        self.assertFalse(me["ok"], me)
        self.assertEqual(me["via"], "conflict")

    def test_a_path_only_body_with_no_native_id_still_resolves(self):
        me = self.who(self.b, env={}, cwd=self.wt_b, explicit_root=False)
        self.assertTrue(me["ok"], me)
        self.assertEqual((me["chair"], me["via"]), ("y-on-b", "cwd"))

    def test_the_environment_chair_on_its_own_worktree_is_unchanged(self):
        wt_a = Path(tempfile.mkdtemp())
        seat(self.a, "claude", "own", worktree=str(wt_a), resume="synthetic-own-native")
        me = self.who(self.a, env={"CLAUDE_CODE_SESSION_ID": "synthetic-own-native"}, cwd=wt_a, explicit_root=False)
        self.assertTrue(me["ok"], me)
        self.assertEqual((me["chair"], me["via"]), ("own", "environment"))

    def elsewhere(self):
        return Path(tempfile.mkdtemp())

class AdoptFromADetachedChair(Base):
    def test_a_proven_caller_whose_chair_is_detached_is_reattached_and_adopts(self):
        from convoy.cli import main
        from convoy.launcher import resolve_launcher
        seat(self.a, "claude", "caller", worktree=tempfile.mkdtemp(), resume=NATIVE)
        update_seat(self.a, "caller", detached=True)
        seat(self.a, "claude", "worker", worktree=tempfile.mkdtemp(), resume="worker-native")
        env = {"CLAUDE_CODE_SESSION_ID": NATIVE}
        resolved = resolve_launcher(self.a, procs=CHAIN, env=env, cwd=str(self.b), pid=21)
        me = {"ok": True, "chair": "caller", "via": "environment", "harness": "claude"}
        buf = io.StringIO()
        with mock.patch("convoy.cli.identify", return_value=me), \
             mock.patch("convoy.cli.resolve_launcher", return_value=resolved), redirect_stdout(buf):
            rc = main(["--root", str(self.a), "adopt", "--seat", "worker"])
        card = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["attached"], card)
        self.assertEqual(card["launched_by"], "caller")
        rows = {s["session_id"]: s for s in list_seats(self.a)}
        self.assertFalse(rows["caller"].get("detached"))
        self.assertEqual(rows["worker"]["launched_by"], "caller")
        sent = [r for r in feed_since(self.a, EPOCH) if r.get("kind") == "synapse" and r.get("instance_id") == "worker"]
        self.assertEqual([r["from"] for r in sent], ["caller"])


FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}


def _git_repo(prefix: str) -> Path:
    import subprocess
    d = Path(tempfile.mkdtemp(prefix=prefix))
    for argv in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                  "-m", "init"]):
        subprocess.run(["git", *argv], cwd=str(d), check=True, capture_output=True, text=True, timeout=30)
    return d


class TheExplicitRootReachesTheCli(unittest.TestCase):
    """The CLI verbs that resolve a caller (add's launcher, adopt --id, a send's sender, reply)
    from thread B's folder, against thread A. Runners are mocks and the process table is
    synthetic: nothing launches."""

    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-xthread-cli-home-")
        self.addCleanup(home.cleanup)
        for patcher in (mock.patch.dict(os.environ, {"CONVOY_HOME": home.name}),
                        mock.patch.object(panes, "_TEST_PID", 21)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.a = _git_repo("convoy-xthread-cli-a-")
        bind(self.a, "thread-a")
        self.b = Path(tempfile.mkdtemp(prefix="convoy-xthread-cli-b-"))
        bind(self.b, "thread-b")
        seat(self.a, "claude", "orch-a", worktree=tempfile.mkdtemp(), resume=NATIVE)
        old = os.getcwd()
        os.chdir(self.b)
        self.addCleanup(os.chdir, old)

    def body(self, procs, env=None):
        """The calling body: this process table, and this native environment."""
        for patcher in (mock.patch.object(panes, "_TEST_PROCS", procs),
                        mock.patch.dict(os.environ, env or {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def spy(self):
        """Every identify the CLI and the launcher make: (explicit_root, answer)."""
        seen = []
        real = panes.identify

        def record(root, *args, **kw):
            out = real(root, *args, **kw)
            seen.append((kw.get("explicit_root", False), out))
            return out

        for target in ("convoy.panes.identify", "convoy.cli.identify"):
            patcher = mock.patch(target, side_effect=record)
            patcher.start()
            self.addCleanup(patcher.stop)
        return seen

    def cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main_cli(list(argv))
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def mocked_add(self):
        """The real add with mocked runners and a Windows Terminal placement."""
        from convoy.crew import add
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        self.window_runner = mock.Mock(return_value={"ok": True, "pid": 4343})

        def run(root, *args, **kw):
            kw.update(runner=None if kw.get("runner") is None else self.runner,
                      window_runner=None if kw.get("window_runner") is None else self.window_runner,
                      env={"WT_SESSION": "synthetic-window"}, which=lambda name: "/usr/bin/wt",
                      platform_name="nt")
            return add(root, *args, **kw)

        for target, kw in (("convoy.cli.add_neuron", {"side_effect": run}),
                           ("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which",
                            {"side_effect": lambda name: "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"})):
            patcher = mock.patch(target, **kw)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_an_add_with_an_explicit_root_from_another_threads_folder_launches_as_the_seated_chair(self):
        self.body(CHAIN, {"CLAUDE_CODE_SESSION_ID": NATIVE})
        self.mocked_add()
        seen = self.spy()
        rc, card = self.cli("--root", str(self.a), "add", "codex")
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["ok"], card)
        self.assertNotIn("would_refuse", card)
        self.assertFalse(card.get("conflict"), card)
        self.assertEqual(card["launcher"]["launched_by"], "orch-a", card)
        self.assertEqual(self.runner.call_count, 1)
        new = [s for s in list_seats(self.a) if s.get("session_id") != "orch-a"]
        self.assertEqual([s.get("launched_by") for s in new], ["orch-a"])
        self.assertEqual(list_seats(self.b), [])
        explicit, me = seen[0]
        self.assertTrue(explicit)
        self.assertEqual((me["chair"], me["via"], me["conflict"]), ("orch-a", "environment", False), me)
        self.assertEqual(me["cwd_thread_differs"]["cwd_thread"], "thread-b")

    def test_an_add_with_an_inferred_root_never_borrows_the_other_threads_chair(self):
        # No --root from B's folder: the root is B, where this session has no chair. The A
        # chair is not its launcher here; a live add would attach the session to B first.
        self.body(CHAIN, {"CLAUDE_CODE_SESSION_ID": NATIVE})
        self.mocked_add()
        seen = self.spy()
        rc, card = self.cli("add", "codex", "--dry-run")
        self.assertEqual(rc, 0, card)
        self.assertEqual((card["launcher"]["kind"], card["launcher"]["chair"]), ("unseated", None), card)
        self.assertTrue(card["launcher"]["would_attach"], card)
        self.assertEqual(list_seats(self.b), [])
        self.runner.assert_not_called()
        self.assertEqual({explicit for explicit, _ in seen}, {False})

    def test_adopt_by_neuron_id_from_a_foreign_folder_scopes_to_the_neurons_own_root(self):
        from convoy.activity import neuron_id
        seat(self.a, "claude", "worker", worktree=tempfile.mkdtemp(), resume="synthetic-worker-native")
        nid = neuron_id(read_id(self.a), "worker")
        # The caller is proven on A by token; --root B is ignored once the id names A.
        self.body([dict(CHAIN[0], cmdline="claude --resume " + NATIVE), CHAIN[1]])
        seen = self.spy()
        with mock.patch("convoy.index.is_temp_root", return_value=False):   # temp roots do not route
            rc, card = self.cli("--root", str(self.b), "adopt", "--id", nid)
        self.assertEqual(rc, 0, card)
        self.assertEqual((card["session_id"], card["launched_by"]), ("worker", "orch-a"), card)
        rows = {s["session_id"]: s for s in list_seats(self.a)}
        self.assertEqual(rows["worker"]["launched_by"], "orch-a")
        self.assertEqual(list_seats(self.b), [])
        # The id's root is inferred: the cwd in B stays a visible conflict on the proven chair.
        explicit, me = seen[0]
        self.assertFalse(explicit)
        self.assertEqual((me["chair"], me["via"], me["conflict"]), ("orch-a", "token", True), me)

    def test_a_send_with_an_explicit_root_from_a_foreign_folder_proves_its_sender_so_reply_works(self):
        from convoy.cli import _proven_sender
        seat(self.a, "claude", "worker", worktree=tempfile.mkdtemp(), resume="synthetic-worker-native")
        seen = self.spy()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": NATIVE}), \
             mock.patch("convoy.cli.enumerate_processes", return_value=CHAIN, create=True):
            self.assertEqual(_proven_sender(self.a, False, explicit_root=True),
                             {"chair": "orch-a", "verified_by": "environment"})
            rc, sent = self.cli("--root", str(self.a), "send", "--to", "worker", "synthetic body")
        self.assertEqual(rc, 0, sent)
        synapse = [r for r in feed_since(self.a, EPOCH) if r.get("kind") == "synapse"]
        self.assertEqual([(r["from"], r["instance_id"]) for r in synapse], [("orch-a", "worker")])
        # The worker replies from the same foreign folder, proven on A by its token.
        self.body([dict(CHAIN[0], cmdline="claude --resume synthetic-worker-native"), CHAIN[1]])
        rc, card = self.cli("--root", str(self.a), "reply", synapse[0]["token"], "synthetic answer")
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["to"], "orch-a")
        self.assertEqual({explicit for explicit, _ in seen}, {True})
        self.assertEqual([(me["chair"], me["via"], me["conflict"]) for _, me in seen],
                         [("orch-a", "environment", False)] * 2 + [("worker", "token", False)])


def main_cli(argv):
    from convoy.cli import main
    return main(argv)


if __name__ == "__main__":
    unittest.main()
