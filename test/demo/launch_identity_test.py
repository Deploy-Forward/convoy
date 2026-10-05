"""Launch identity: every launched neuron knows its lead and who launched it.

A session that was not seated on a fresh thread ran `start` and then `add codex`
twice. Both neurons booted and, asked to report to the lead, found no lead and no
record of who launched them; their boot prompt also pointed at a thread.md that
did not exist.

The rules under test:

- a launch resolves the launching session with the existing identity proof. A
  seated launcher with environment (or token) proof is recorded as the new seat's
  `launched_by`. An unseated launcher with a proven native session is attached
  first, exactly as `convoy attach` does (it takes a lead that is none or
  dangling), then recorded. A launcher with no proof (a cwd match, a script) is
  recorded as `launched_by: null` with `launched_by_why`, the card warns, and
  nothing is attached and no lead changes;
- the boot prompt names the lead and the launcher (informational only), shows
  the `report` and `reply` commands, carries no routing prose, and names only
  files that exist;
- `report` routes in code: to the launcher, else the lead, else a refusal;
- `reply <token>` writes the receipt to the original sender, citing the token;
- `whoami` adds `lead` and `launched_by`.

Every id is synthetic; roots and the Convoy home are temporary; no harness runs.
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

from convoy.activity import neuron_id  # noqa: E402
from convoy.cli import main  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, read_id, seat, update_seat  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import join, lead_state, take_lead  # noqa: E402

EPOCH = "1970-01-01T00:00:00.000000Z"
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}
WT = {"env": {"WT_SESSION": "caller-window"}, "platform_name": "nt"}
CLAUDE_CHAIN = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]
ROUTING_PROSE = ("results go to", "escalat", "when the launcher is gone", "report to your launcher",
                 "send --id")


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
    key = str(name).lower().removesuffix(".exe")
    if key == "wt":
        return "/usr/bin/wt"
    return "C:\\Tools\\" + key + ".exe"


def _row(root, sid):
    return next(s for s in list_seats(root) if s.get("session_id") == sid)


class Base(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-launch-id-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "launch-id")
        self.cid = read_id(self.root)
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.targeted_launch.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which})):
            q = mock.patch(target, **kw)
            q.start()
            self.addCleanup(q.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})

    def nid(self, sid):
        return neuron_id(self.cid, sid)

    def other_dir(self) -> Path:
        d = tempfile.TemporaryDirectory(prefix="convoy-launch-id-wt-")
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def resolve(self, env, cwd):
        from convoy.launcher import resolve_launcher
        return resolve_launcher(self.root, procs=CLAUDE_CHAIN, env=env, cwd=str(cwd), pid=21)

    def add(self, launcher, **kw):
        from convoy.crew import add
        return add(self.root, "codex", None, runner=self.runner, window_runner=self.runner, which=_which,
                   launcher=launcher, **WT, **kw)

    def seat_lead(self, sid="lead-chair", harness="codex", native="lead-native"):
        seat(self.root, harness, sid, worktree=str(self.other_dir()), resume=native)
        take_lead(self.root, sid, lead_state(self.root))
        return sid


class UnseatedLauncherIsAttachedAndTakesTheLead(Base):
    def test_a_proven_unseated_launcher_attaches_takes_the_lead_and_is_recorded(self):
        self.assertEqual(lead_state(self.root)["status"], "none")
        launcher = self.resolve({"CLAUDE_CODE_SESSION_ID": "launcher-native"}, self.root)
        self.assertEqual(launcher["kind"], "unseated", launcher)
        card = self.add(launcher)
        self.assertTrue(card["ok"], card)
        info = card["launcher"]
        self.assertTrue(info["attached"], info)
        self.assertTrue(info["lead_taken"], info)
        chair = info["chair"]
        self.assertTrue(chair)
        # attached exactly as `convoy attach` does: a chair holding the native id
        self.assertEqual(_row(self.root, chair).get("resume"), "launcher-native")
        self.assertEqual(lead_state(self.root)["chair"], chair)
        new = card["seats"][0]["session_id"]
        row = _row(self.root, new)
        self.assertEqual(row.get("launched_by"), chair)
        prompt = row["boot_prompt"]
        self.assertIn(self.nid(chair), prompt)
        self.assertIn("report \"...\"", prompt)
        self.assertIn("reply <token> \"...\"", prompt)

    def test_a_dry_run_attaches_nothing(self):
        from convoy.crew import add
        launcher = self.resolve({"CLAUDE_CODE_SESSION_ID": "launcher-native"}, self.root)
        card = add(self.root, "codex", None, runner=None, which=_which, launcher=launcher, **WT)
        self.assertTrue(card["ok"], card)
        self.assertEqual(list_seats(self.root), [])
        self.assertEqual(lead_state(self.root)["status"], "none")


class SeatedLaunchers(Base):
    def test_a_seated_non_lead_launcher_is_recorded_and_the_lead_is_unchanged(self):
        lead = self.seat_lead()
        wdir = self.other_dir()
        seat(self.root, "claude", "worker-chair", worktree=str(wdir), resume="worker-native")
        launcher = self.resolve({"CLAUDE_CODE_SESSION_ID": "worker-native"}, wdir)
        self.assertEqual((launcher["kind"], launcher["chair"]), ("seated", "worker-chair"), launcher)
        card = self.add(launcher)
        self.assertTrue(card["ok"], card)
        self.assertFalse(card["launcher"]["attached"])
        self.assertFalse(card["launcher"]["lead_taken"])
        self.assertEqual(lead_state(self.root)["chair"], lead)
        row = _row(self.root, card["seats"][0]["session_id"])
        self.assertEqual(row.get("launched_by"), "worker-chair")
        prompt = row["boot_prompt"]
        self.assertIn(self.nid(lead), prompt)
        self.assertIn(self.nid("worker-chair"), prompt)

    def test_the_lead_launching_is_named_once_as_lead_and_launcher(self):
        wdir = self.other_dir()
        seat(self.root, "claude", "lead-chair", worktree=str(wdir), resume="lead-native")
        take_lead(self.root, "lead-chair", lead_state(self.root))
        launcher = self.resolve({"CLAUDE_CODE_SESSION_ID": "lead-native"}, wdir)
        card = self.add(launcher)
        self.assertTrue(card["ok"], card)
        row = _row(self.root, card["seats"][0]["session_id"])
        self.assertEqual(row.get("launched_by"), "lead-chair")
        prompt = row["boot_prompt"]
        self.assertEqual(prompt.count(self.nid("lead-chair")), 1, prompt)
        self.assertIn("lead and launcher", prompt.lower())


class UnprovenLauncher(Base):
    def test_a_cwd_only_launcher_refuses_the_launch_with_no_write(self):
        # Every launch records a proven launcher: a cwd match alone refuses before any write.
        wdir = self.other_dir()
        seat(self.root, "claude", "cwd-chair", worktree=str(wdir))
        launcher = self.resolve({}, wdir)
        self.assertEqual(launcher["kind"], "unproven", launcher)
        self.assertIn("cwd", launcher["why"])
        before = {s["session_id"] for s in list_seats(self.root)}
        card = self.add(launcher)
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "cannot prove who is launching")
        self.assertEqual({s["session_id"] for s in list_seats(self.root)}, before, "no chair, no attach")
        self.assertEqual(lead_state(self.root)["status"], "none")

    def test_a_script_with_no_harness_is_unproven(self):
        from convoy.launcher import resolve_launcher
        procs = [{"pid": 30, "ppid": 1, "cmdline": "python -m convoy", "cwd": None}]
        out = resolve_launcher(self.root, procs=procs, env={}, cwd=str(self.root), pid=30)
        self.assertEqual(out["kind"], "unproven", out)
        self.assertTrue(out["why"])


class CliResolvesTheLauncher(Base):
    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_add_hands_the_resolved_launcher_to_the_verb(self):
        resolved = {"kind": "unproven", "chair": None, "why": "synthetic"}
        with mock.patch("convoy.cli.resolve_launcher", return_value=resolved) as res, \
             mock.patch("convoy.cli.add_neuron", return_value={"ok": True}) as add:
            rc, _ = self.cli("add", "codex")
        self.assertEqual(rc, 0)
        res.assert_called_once()
        self.assertIs(add.call_args.kwargs.get("launcher"), resolved)

    def test_crew_hands_the_resolved_launcher_to_the_verb(self):
        resolved = {"kind": "unproven", "chair": None, "why": "synthetic"}
        with mock.patch("convoy.cli.resolve_launcher", return_value=resolved), \
             mock.patch("convoy.cli.crew", return_value={"ok": True}) as crew:
            rc, _ = self.cli("crew", "--seat", "codex")
        self.assertEqual(rc, 0)
        self.assertIs(crew.call_args.kwargs.get("launcher"), resolved)

    def test_launch_records_the_launcher_on_a_fresh_chair_joined_without_one(self):
        joined = join(self.root, "codex", session_id="fresh-chair", worktree=str(self.other_dir()))
        self.assertNotIn("launched_by", joined["seat"])
        seat(self.root, "claude", "x-chair", worktree=str(self.other_dir()), resume="x-native")
        resolved = {"kind": "seated", "chair": "x-chair", "via": "environment", "why": None}
        with mock.patch("convoy.cli.resolve_launcher", return_value=resolved), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}):
            rc, card = self.cli("launch", "--seat", "fresh-chair")
        self.assertEqual(rc, 0, card)
        row = _row(self.root, "fresh-chair")
        self.assertEqual(row["launched_by"], "x-chair")
        self.assertIn(joined["token"], row["boot_prompt"], "the recomposed prompt keeps the join token")

    def test_join_launch_records_the_launcher_and_a_plain_join_records_nothing(self):
        seat(self.root, "claude", "x-chair", worktree=str(self.other_dir()), resume="x-native")
        resolved = {"kind": "seated", "chair": "x-chair", "via": "environment", "why": None}
        with mock.patch("convoy.cli.resolve_launcher", return_value=resolved) as res, \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}):
            rc, card = self.cli("join", "--to", "codex", "--session-id", "launched-chair",
                                "--worktree", str(self.other_dir()), "--launch")
            self.assertEqual(rc, 0, card)
            self.assertEqual(_row(self.root, "launched-chair")["launched_by"], "x-chair")
            rc, card = self.cli("join", "--to", "codex", "--session-id", "plain-chair",
                                "--worktree", str(self.other_dir()))
        self.assertEqual(rc, 0, card)
        self.assertNotIn("launched_by", _row(self.root, "plain-chair"))
        res.assert_called_once()

    def test_whoami_adds_lead_and_launched_by(self):
        lead = self.seat_lead()
        joined = join(self.root, "claude", session_id="me-chair", worktree=str(self.other_dir()),
                      launched_by="lead-chair")
        self.assertEqual(joined["seat"]["launched_by"], "lead-chair")
        me = {"ok": True, "chair": "me-chair", "via": "environment", "harness": "claude"}
        with mock.patch("convoy.cli.identify", return_value=me):
            rc, card = self.cli("whoami")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["chair"], "me-chair")
        self.assertEqual(card["via"], "environment", "existing fields unchanged")
        self.assertEqual(card["lead"], {"chair": lead, "neuron_id": self.nid(lead)})
        self.assertEqual(card["launched_by"], {"chair": "lead-chair", "neuron_id": self.nid("lead-chair")})

    def test_whoami_lead_and_launched_by_are_null_when_unknown(self):
        join(self.root, "claude", session_id="me-chair", worktree=str(self.other_dir()))
        me = {"ok": True, "chair": "me-chair", "via": "environment", "harness": "claude"}
        with mock.patch("convoy.cli.identify", return_value=me):
            rc, card = self.cli("whoami")
        self.assertIsNone(card["lead"])
        self.assertIsNone(card["launched_by"])


class BootPromptFiles(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-launch-id-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        d = tempfile.TemporaryDirectory(prefix="convoy-launch-id-root-")
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)

    def test_a_started_thread_without_thread_md_is_never_named(self):
        ensure_id(self.root)  # what `start` does on a root with no thread name
        self.assertFalse((self.root / "thread.md").exists())
        joined = join(self.root, "codex", session_id="fresh-chair")
        self.assertNotIn("thread.md", joined["seat"]["boot_prompt"])

    def test_an_existing_thread_md_is_named(self):
        bind(self.root, "named")
        joined = join(self.root, "codex", session_id="fresh-chair")
        self.assertIn(str(self.root / "thread.md"), joined["seat"]["boot_prompt"])

    def test_the_prompt_shows_both_commands_and_no_routing_prose(self):
        bind(self.root, "named")
        prompt = join(self.root, "codex", session_id="fresh-chair")["seat"]["boot_prompt"]
        self.assertIn(" report \"...\"", prompt)
        self.assertIn(" reply <token> \"...\"", prompt)
        low = prompt.lower()
        for phrase in ROUTING_PROSE:
            self.assertNotIn(phrase, low)
        self.assertIn("lead: none", low)


class Routing(unittest.TestCase):
    """report and reply: deterministic routing on the existing send path."""

    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-launch-id-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        d = tempfile.TemporaryDirectory(prefix="convoy-launch-id-root-")
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        bind(self.root, "routing")

    def chair(self, sid, harness="claude", native=None):
        wt = tempfile.TemporaryDirectory(prefix="convoy-launch-id-wt-")
        self.addCleanup(wt.cleanup)
        seat(self.root, harness, sid, worktree=wt.name, resume=native or (sid + "-native"))
        return sid

    def me(self, sid):
        return {"ok": True, "chair": sid, "via": "environment", "harness": "claude"}

    def synapses(self):
        return [r for r in feed_since(self.root, EPOCH) if r.get("kind") == "synapse"]

    def report(self, sid, text="synthetic result"):
        from convoy.route import report
        return report(self.root, text, me=self.me(sid))

    def test_report_routes_to_the_launcher(self):
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        self.chair("launcher-chair")
        self.chair("worker-chair")
        update_seat(self.root, "worker-chair", launched_by="launcher-chair")
        card = self.report("worker-chair")
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["routed_to"], card["route"]), ("launcher-chair", "launcher"))
        [row] = self.synapses()
        self.assertEqual((row["instance_id"], row["from"]), ("launcher-chair", "worker-chair"))

    def test_report_falls_back_to_the_lead_when_the_launcher_is_null(self):
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        self.chair("worker-chair")
        update_seat(self.root, "worker-chair", launched_by=None, launched_by_why="synthetic")
        card = self.report("worker-chair")
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["routed_to"], card["route"]), (lead, "lead"))
        self.assertEqual(self.synapses()[0]["instance_id"], lead)

    def test_report_falls_back_to_the_lead_when_the_launcher_is_gone(self):
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        self.chair("launcher-chair")
        self.chair("worker-chair")
        update_seat(self.root, "worker-chair", launched_by="launcher-chair")
        update_seat(self.root, "launcher-chair", detached=True)
        card = self.report("worker-chair")
        self.assertEqual((card["routed_to"], card["route"]), (lead, "lead"), card)
        update_seat(self.root, "worker-chair", launched_by="never-seated-chair")
        card = self.report("worker-chair")
        self.assertEqual((card["routed_to"], card["route"]), (lead, "lead"), card)

    def test_report_refuses_with_a_reason_when_there_is_no_launcher_and_no_lead(self):
        self.chair("worker-chair")
        card = self.report("worker-chair")
        self.assertFalse(card["ok"])
        self.assertIsNone(card["routed_to"])
        self.assertIn("no launcher", card["why"])
        self.assertIn("no lead", card["why"])
        self.assertEqual(self.synapses(), [])

    def test_the_lead_with_no_launcher_refuses(self):
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        card = self.report(lead)
        self.assertFalse(card["ok"])
        self.assertIn("lead", card["why"])
        self.assertEqual(self.synapses(), [])

    def test_report_refuses_an_unidentified_caller(self):
        from convoy.route import report
        card = report(self.root, "x", me={"ok": False, "chair": None, "ask": "no chair matches"})
        self.assertFalse(card["ok"])
        self.assertTrue(card["why"])

    def sent_token(self, sender, receiver):
        from convoy.synapse import fake_runner, send_one
        card = send_one(self.root, receiver, "synthetic ask", runner=fake_runner,
                        sender={"chair": sender, "verified_by": "environment"})
        self.assertTrue(card["ok"], card)
        return next(r["token"] for r in reversed(self.synapses()) if r["instance_id"] == receiver)

    def test_reply_addresses_the_sender_and_counts_as_delivered(self):
        from convoy.conductor import replies
        from convoy.route import reply
        self.chair("asker-chair")
        self.chair("worker-chair")
        token = self.sent_token("asker-chair", "worker-chair")
        card = reply(self.root, token, "synthetic answer", me=self.me("worker-chair"))
        self.assertTrue(card["ok"], card)
        row = card["row"]
        self.assertEqual((row["kind"], row["from"], row["to"]), ("note", "worker-chair", "asker-chair"))
        self.assertIn(token, row["summary"])
        self.assertTrue(replies(self.root, "asker-chair", token=token)["delivered"])

    def test_reply_refuses_an_unknown_token(self):
        from convoy.route import reply
        self.chair("worker-chair")
        card = reply(self.root, "0" * 32, "x", me=self.me("worker-chair"))
        self.assertFalse(card["ok"])
        self.assertIn("unknown token", card["why"])

    def test_reply_refuses_a_caller_that_was_not_the_recipient(self):
        from convoy.route import reply
        self.chair("asker-chair")
        self.chair("worker-chair")
        self.chair("bystander-chair")
        token = self.sent_token("asker-chair", "worker-chair")
        card = reply(self.root, token, "x", me=self.me("bystander-chair"))
        self.assertFalse(card["ok"])
        self.assertIn("recipient", card["why"])
        self.assertFalse([r for r in feed_since(self.root, EPOCH) if r.get("kind") == "note"])

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_the_cli_verbs_use_the_proven_chair(self):
        self.chair("asker-chair")
        self.chair("worker-chair")
        update_seat(self.root, "worker-chair", launched_by="asker-chair")
        with mock.patch("convoy.cli.identify", return_value=self.me("worker-chair")):
            rc, card = self.cli("report", "synthetic result")
        self.assertEqual(rc, 0, card)
        self.assertEqual((card["routed_to"], card["route"]), ("asker-chair", "launcher"))
        token = self.sent_token("asker-chair", "worker-chair")
        with mock.patch("convoy.cli.identify", return_value=self.me("worker-chair")):
            rc, card = self.cli("reply", token, "synthetic answer")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["row"]["to"], "asker-chair")


# ---- review of 8fc658c: findings B1-B5 and the non-blocking ones ----

class CliBase(Base):
    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def unseated(self):
        return self.resolve({"CLAUDE_CODE_SESSION_ID": "launcher-native"}, self.root)

    def not_a_repo(self) -> Path:
        return self.other_dir()


class B1AFailedVerbAttachesNobody(CliBase):
    def assertNobodyAttached(self, before):
        self.assertEqual({s["session_id"] for s in list_seats(self.root)}, before)
        self.assertEqual(lead_state(self.root)["status"], "none")

    def test_a_refused_join_launch_attaches_nobody_and_moves_no_lead(self):
        join(self.root, "codex", session_id="dup", worktree=str(self.other_dir()))
        before = {s["session_id"] for s in list_seats(self.root)}
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.unseated()), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch:
            rc, card = self.cli("join", "--to", "codex", "--session-id", "dup", "--launch")
        self.assertEqual(rc, 1, card)
        launch.assert_not_called()
        self.assertNobodyAttached(before)

    def test_a_join_launch_that_succeeds_records_the_attached_launcher(self):
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.unseated()), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}):
            rc, card = self.cli("join", "--to", "codex", "--session-id", "new-chair",
                                "--worktree", str(self.other_dir()), "--launch")
        self.assertEqual(rc, 0, card)
        chair = card["launcher"]["chair"]
        self.assertTrue(card["launcher"]["attached"])
        self.assertEqual(_row(self.root, "new-chair")["launched_by"], chair)
        self.assertIn(self.nid(chair), _row(self.root, "new-chair")["boot_prompt"])

    def test_a_crew_whose_mint_failed_attaches_nobody(self):
        from convoy.crew import crew
        card = crew(self.root, [{"harness": "codex"}], checkout=self.not_a_repo(), launcher=self.unseated())
        self.assertFalse(card["ok"], card)
        self.assertNobodyAttached(set())

    def test_an_add_whose_mint_failed_attaches_nobody(self):
        card = self.add(self.unseated(), checkout=self.not_a_repo())
        self.assertFalse(card["ok"], card)
        self.runner.assert_not_called()
        self.assertNobodyAttached(set())


class B2TheLaunchThatSucceedsNamesTheLauncher(CliBase):
    def test_a_refused_launch_by_a_then_a_launch_by_b_records_b(self):
        for sid, native in (("a-chair", "a-native"), ("b-chair", "b-native")):
            seat(self.root, "claude", sid, worktree=str(self.other_dir()), resume=native)
        join(self.root, "codex", session_id="fresh", worktree=str(self.other_dir()))
        a = {"kind": "seated", "chair": "a-chair", "via": "environment", "why": None}
        b = {"kind": "seated", "chair": "b-chair", "via": "environment", "why": None}
        with mock.patch("convoy.cli.resolve_launcher", return_value=a), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": False, "error": "synthetic refusal"}):
            rc, _ = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 1)
        with mock.patch("convoy.cli.resolve_launcher", return_value=b), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}):
            rc, card = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 0, card)
        self.assertEqual(card["launcher"]["chair"], "b-chair")
        row = _row(self.root, "fresh")
        self.assertEqual(row["launched_by"], "b-chair")
        self.assertIn(self.nid("b-chair"), row["boot_prompt"])
        self.assertNotIn(self.nid("a-chair"), row["boot_prompt"])


class B3RoutingNeedsAVerifiedCaller(unittest.TestCase):
    setUp = Routing.setUp
    chair = Routing.chair
    me = Routing.me
    synapses = Routing.synapses
    report = Routing.report
    sent_token = Routing.sent_token

    def cwd_me(self, sid):
        return {"ok": True, "chair": sid, "via": "cwd", "harness": "claude"}

    def test_report_refuses_a_caller_proven_only_by_cwd(self):
        from convoy.route import report
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        self.chair("worker-chair")
        card = report(self.root, "x", me=self.cwd_me("worker-chair"))
        self.assertFalse(card["ok"], card)
        self.assertIn("environment, token or pane-host", card["why"])
        self.assertEqual(self.synapses(), [])

    def test_reply_refuses_a_caller_proven_only_by_cwd(self):
        from convoy.route import reply
        self.chair("asker-chair")
        self.chair("worker-chair")
        token = self.sent_token("asker-chair", "worker-chair")
        card = reply(self.root, token, "x", me=self.cwd_me("worker-chair"))
        self.assertFalse(card["ok"], card)
        self.assertIn("environment, token or pane-host", card["why"])
        self.assertFalse([r for r in feed_since(self.root, EPOCH) if r.get("kind") == "note"])

    def test_an_unproven_note_is_never_a_delivery_receipt(self):
        from convoy.conductor import replies
        from convoy.layer import hook, neuron_note
        self.chair("asker-chair")
        self.chair("worker-chair")
        token = self.sent_token("asker-chair", "worker-chair")
        neuron_note(self.root, "token=" + token + " claimed", instance_id="worker-chair", to="asker-chair")
        self.assertFalse(replies(self.root, "asker-chair", token=token)["delivered"])
        hook(self.root, "note", "token=" + token + " proven", instance_id="worker-chair", to="asker-chair",
             verified_by="environment")
        self.assertTrue(replies(self.root, "asker-chair", token=token)["delivered"])

    def test_a_self_launched_chair_is_not_told_its_launcher_is_detached(self):
        lead = self.chair("lead-chair")
        take_lead(self.root, lead, lead_state(self.root))
        self.chair("worker-chair")
        update_seat(self.root, "worker-chair", launched_by="worker-chair")
        card = self.report("worker-chair")
        self.assertEqual((card["routed_to"], card["route"]), (lead, "lead"), card)
        self.assertNotIn("detached", card["route_why"])
        self.assertIn("yourself", card["route_why"])


class B4TestsNeverReadTheRealProcessTable(Base):
    def test_resolve_launcher_gets_an_empty_table_unless_a_test_opts_in(self):
        from convoy import panes
        from convoy.launcher import resolve_launcher
        with mock.patch.object(panes, "_safe_enumerate", side_effect=AssertionError("real table read")), \
             mock.patch.object(panes, "enumerate_processes", side_effect=AssertionError("real table read")):
            out = resolve_launcher(self.root, env={"CLAUDE_CODE_SESSION_ID": "launcher-native"})
        self.assertEqual(out["kind"], "unproven", out)

    def test_a_test_opts_in_with_its_own_table(self):
        from convoy import panes
        with mock.patch.object(panes, "_TEST_PROCS", CLAUDE_CHAIN), mock.patch.object(panes, "_TEST_PID", 21):
            from convoy.launcher import resolve_launcher
            out = resolve_launcher(self.root, env={"CLAUDE_CODE_SESSION_ID": "launcher-native"}, cwd=str(self.root))
        self.assertEqual(out["kind"], "unseated", out)


class B5TheIdentityLineIsTrueAtLaunch(Base):
    def launch(self, sid):
        from convoy.targeted_launch import launch_seat
        return launch_seat(self.root, sid, runner=self.runner, env=WT["env"], which=_which,
                           platform_name="nt", trust_probe=lambda row: True)

    def test_a_swap_of_the_lead_codex_chair_to_claude_is_not_told_it_leads(self):
        from convoy.lifecycle import swap
        sid = self.seat_lead("lead-chair", "codex", "lead-native")
        handoff = self.other_dir() / "handoff.md"
        handoff.write_text("synthetic handoff\n", encoding="utf-8")
        card = swap(self.root, sid, to="claude", handoff=str(handoff), author=sid)
        prompt = card["seat"]["boot_prompt"]
        self.assertNotIn("Lead: you", prompt)
        self.assertEqual(lead_state(self.root)["status"], "dangling")
        self.assertIn("Lead: none", prompt)

    def test_a_join_matching_only_the_lead_harness_is_not_told_it_leads(self):
        from convoy.convoy import set_lead
        set_lead(self.root, "codex")  # a lead file naming a harness, no lead row naming a chair
        prompt = join(self.root, "codex", session_id="codex-new",
                      worktree=str(self.other_dir()))["seat"]["boot_prompt"]
        self.assertNotIn("Lead: you", prompt)
        self.assertIn("codex", prompt.split("Lead", 1)[1])

    def test_a_pending_prompt_names_the_lead_at_launch_not_at_join(self):
        old = self.seat_lead("old-lead", "claude", "old-native")
        wt = self.other_dir()
        join(self.root, "codex", session_id="pending-chair", worktree=str(wt))
        self.assertIn(self.nid(old), _row(self.root, "pending-chair")["boot_prompt"])
        update_seat(self.root, old, detached=True)
        seat(self.root, "claude", "new-lead", worktree=str(self.other_dir()), resume="new-native")
        take_lead(self.root, "new-lead", lead_state(self.root))
        card = self.launch("pending-chair")
        self.assertTrue(card["ok"], card)
        prompt = _row(self.root, "pending-chair")["boot_prompt"]
        self.assertIn(self.nid("new-lead"), prompt)
        self.assertNotIn(self.nid(old), prompt)
        self.assertIn(prompt, " ".join(str(a) for a in card["harness_argv"]))


class RecordOnlyWhatThisInvocationSpawned(CliBase):
    """A bring-up or launch records launched_by only on the chairs it spawns."""

    def seated(self, sid):
        seat(self.root, "claude", sid, worktree=str(self.other_dir()), resume=sid + "-native")
        return {"kind": "seated", "chair": sid, "via": "environment", "why": None}

    def test_bring_up_skips_a_chair_live_under_a_pane_host_and_records_only_what_it_spawned(self):
        from convoy.lifecycle import record_launcher
        from convoy.targeted_launch import take_launch_claim
        self.seated("a-chair")
        b = self.seated("b-chair")
        join(self.root, "codex", session_id="x-chair", worktree=str(self.other_dir()))
        record_launcher(self.root, "x-chair", "a-chair")           # A launched X ...
        take_launch_claim(self.root, "x-chair", host_pid=os.getpid())  # ... and its pane host is live
        join(self.root, "codex", session_id="y-chair", worktree=str(self.other_dir()))
        window = mock.Mock(return_value={"ok": True, "pid": 4545})
        with mock.patch("convoy.cli.resolve_launcher", return_value=b), \
             mock.patch("convoy.cli.live_runner", window):
            rc, card = self.cli("bring-up")
        self.assertEqual(rc, 0, card)
        self.assertEqual(_row(self.root, "x-chair")["launched_by"], "a-chair")
        self.assertEqual(_row(self.root, "y-chair")["launched_by"], "b-chair")
        self.assertEqual(card["launcher"]["recorded_on"], ["y-chair"])
        spawned = [w.get("session_id") for w in card["windows"]]
        self.assertNotIn("x-chair", spawned)
        self.assertIn("y-chair", spawned)
        self.assertIn("x-chair", [s["session_id"] for s in card["skipped"]])
        self.assertNotIn("x-chair", " ".join(str(a) for a in window.call_args.args[0]))

    def test_a_launch_that_spawns_nothing_records_nothing(self):
        a = self.seated("a-chair")
        join(self.root, "codex", session_id="fresh", worktree=str(self.other_dir()))
        with mock.patch("convoy.cli.resolve_launcher", return_value=a), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": False, "error": "synthetic refusal"}):
            rc, card = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 1)
        self.assertNotEqual(_row(self.root, "fresh").get("launched_by"), "a-chair")
        self.assertNotIn(self.nid("a-chair"), _row(self.root, "fresh")["boot_prompt"])
        self.assertEqual(card["launcher"]["recorded_on"], [])


class A3ACrashedSpawnRecordsNothing(CliBase):
    """The spawn raising (a wt failure, a Ctrl-C) still settles: nothing it did not spawn keeps the record."""
    seated = RecordOnlyWhatThisInvocationSpawned.seated

    def setUp(self):
        super().setUp()
        self.a = self.seated("a-chair")
        join(self.root, "codex", session_id="fresh", worktree=str(self.other_dir()))

    def assertNotRecorded(self):
        row = _row(self.root, "fresh")
        self.assertNotEqual(row.get("launched_by"), "a-chair")
        self.assertNotIn(self.nid("a-chair"), row["boot_prompt"])

    def test_a_bring_up_that_raises_restores_the_previous_value(self):
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.bring_up", side_effect=OSError("synthetic wt failure")):
            with self.assertRaises(OSError):
                self.cli("bring-up", "--seat", "fresh")
        self.assertNotRecorded()

    def test_a_launch_interrupted_by_ctrl_c_restores_the_previous_value(self):
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.launch_seat", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cli("launch", "--seat", "fresh")
        self.assertNotRecorded()

    def test_a_join_launch_that_raises_restores_the_previous_value(self):
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.launch_seat", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                self.cli("join", "--to", "codex", "--session-id", "joined", "--worktree", str(self.other_dir()),
                         "--launch")
        row = _row(self.root, "joined")
        self.assertNotEqual(row.get("launched_by"), "a-chair")


class A1A2OnlyTheClaimHolderRecords(CliBase):
    """Two launches of one chair: the launch claim is taken before launched_by is written,
    so only the invocation that holds it records and settles."""
    seated = RecordOnlyWhatThisInvocationSpawned.seated

    def setUp(self):
        super().setUp()
        self.a = self.seated("a-chair")
        self.b = self.seated("b-chair")
        join(self.root, "codex", session_id="fresh", worktree=str(self.other_dir()))

    def test_b_holds_the_claim_so_a_launch_by_a_records_nothing(self):
        from convoy.lifecycle import record_launcher
        from convoy.targeted_launch import take_launch_claim
        take_launch_claim(self.root, "fresh")            # B's launch is in flight ...
        record_launcher(self.root, "fresh", "b-chair")   # ... and recorded B
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch:
            rc, card = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 1, card)
        self.assertIn("claimed", card["error"])
        launch.assert_not_called()
        self.assertEqual(_row(self.root, "fresh")["launched_by"], "b-chair")

    def test_a_holds_the_claim_so_b_racing_in_records_nothing_and_a_is_named(self):
        seen = {}

        def a_spawns(*args, **kwargs):
            if "inner" not in seen:
                seen["inner"] = True
                with mock.patch("convoy.cli.resolve_launcher", return_value=self.b):
                    seen["b"] = self.cli("launch", "--seat", "fresh")
            return {"ok": True}

        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.launch_seat", side_effect=a_spawns):
            rc, card = self.cli("launch", "--seat", "fresh")
        self.assertEqual(rc, 0, card)
        b_rc, b_card = seen["b"]
        self.assertEqual(b_rc, 1, b_card)
        self.assertIn("claimed", b_card["error"])
        row = _row(self.root, "fresh")
        self.assertEqual(row["launched_by"], "a-chair")
        self.assertIn(self.nid("a-chair"), row["boot_prompt"])
        self.assertNotIn(self.nid("b-chair"), row["boot_prompt"])

    def test_a_bring_up_skips_a_chair_another_launch_holds_and_records_nothing_on_it(self):
        from convoy.targeted_launch import take_launch_claim
        take_launch_claim(self.root, "fresh")            # another launch is in flight
        window = mock.Mock(return_value={"ok": True, "pid": 4545})
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.live_runner", window):
            rc, card = self.cli("bring-up", "--seat", "fresh")
        self.assertNotIn("fresh", [w.get("session_id") for w in card.get("windows") or []])
        self.assertIn("fresh", [s["session_id"] for s in card["skipped"]])
        self.assertNotIn("launched_by", _row(self.root, "fresh"))
        window.assert_not_called()

    def test_a_refused_launch_releases_its_claim(self):
        from convoy.targeted_launch import read_launch_claim
        with mock.patch("convoy.cli.resolve_launcher", return_value=self.a), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": False, "error": "synthetic"}):
            self.cli("launch", "--seat", "fresh")
        self.assertIsNone(read_launch_claim(self.root, "fresh"))


class B1AReusedPidIsNotALiveHost(Base):
    """A claim names its host by pid AND start time: a pid the OS handed to another process is not the host."""

    def write_claim(self, sid, **payload):
        from convoy.targeted_launch import _claim_path
        path = _claim_path(self.root, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": sid, **payload}) + "\n", encoding="utf-8")

    def test_the_host_claim_records_its_start_time_and_reads_live(self):
        from convoy.pane_host import process_started
        from convoy.targeted_launch import hosted_live, read_launch_claim, take_launch_claim
        take_launch_claim(self.root, "x-chair", host_pid=os.getpid())
        claim = read_launch_claim(self.root, "x-chair")
        started = process_started(os.getpid())
        if sys.platform.startswith(("win", "linux")):
            self.assertIsNotNone(started, "Windows and Linux give a process start time")
        self.assertEqual(claim.get("host_started"), started)
        self.assertTrue(hosted_live(self.root, "x-chair"))

    def test_a_live_pid_with_another_start_time_is_not_the_host(self):
        from convoy.pane_host import process_started
        from convoy.targeted_launch import hosted_live, take_launch_claim
        if process_started(os.getpid()) is None:
            self.skipTest("no process start time on this platform: pid alone decides")
        self.write_claim("x-chair", host_pid=os.getpid(), host_started="1")
        self.assertFalse(hosted_live(self.root, "x-chair"))
        take_launch_claim(self.root, "x-chair", host_pid=os.getpid())  # adopts: the recorded host is gone

    def test_without_a_start_time_the_pid_alone_decides(self):
        from convoy.targeted_launch import hosted_live
        self.write_claim("x-chair", host_pid=os.getpid(), host_started="1")
        with mock.patch("convoy.pane_host.process_started", return_value=None):
            self.assertTrue(hosted_live(self.root, "x-chair"))
        self.write_claim("y-chair", host_pid=os.getpid())   # an older claim with no start time
        self.assertTrue(hosted_live(self.root, "y-chair"))


class CABringUpSaysWhatItLaunched(Base):
    def test_a_bring_up_that_skipped_every_chair_says_so_and_launched_nothing(self):
        from convoy.bringup import bring_up
        from convoy.targeted_launch import take_launch_claim
        join(self.root, "codex", session_id="x-chair", worktree=str(self.other_dir()))
        take_launch_claim(self.root, "x-chair", host_pid=os.getpid())
        card = bring_up(self.root, runner=self.runner, session_ids=["x-chair"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["launched"], [])
        self.assertIn("nothing launched", card["note"])
        self.runner.assert_not_called()

    def test_a_bring_up_names_the_chairs_it_spawned(self):
        from convoy.bringup import bring_up
        join(self.root, "codex", session_id="y-chair", worktree=str(self.other_dir()))
        card = bring_up(self.root, runner=self.runner, session_ids=["y-chair"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["launched"], ["y-chair"])
        self.assertNotIn("note", card)
        dry = bring_up(self.root, runner=None, session_ids=["y-chair"])
        self.assertEqual(dry["launched"], [], "a dry run launches nothing")


class R3AClaimOfADeadProcessExpires(Base):
    """A reservation records the process that took it (pid + start time); once that process
    is dead the claim expires and the next launch adopts it, so a crashed invocation never
    blocks a chair forever. A live holder still refuses; an old claim that names no holder
    still refuses (it cannot be judged)."""

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=60)
        return proc.pid

    def write_claim(self, sid, **payload):
        from convoy.targeted_launch import _claim_path
        path = _claim_path(self.root, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": sid, **payload}) + "\n", encoding="utf-8")

    def test_a_reservation_records_the_process_that_took_it(self):
        from convoy.pane_host import process_started
        from convoy.targeted_launch import read_launch_claim, take_launch_claim
        take_launch_claim(self.root, "x-chair")
        claim = read_launch_claim(self.root, "x-chair")
        self.assertEqual(claim["reserver_pid"], os.getpid())
        self.assertEqual(claim.get("reserver_started"), process_started(os.getpid()))

    def test_a_dead_reservers_claim_older_than_the_grace_is_adopted(self):
        import time
        from convoy.targeted_launch import read_launch_claim, take_launch_claim
        self.write_claim("x-chair", reserver_pid=self.dead_pid(), reserved_at=time.time() - 60)
        take_launch_claim(self.root, "x-chair")
        self.assertEqual(read_launch_claim(self.root, "x-chair")["reserver_pid"], os.getpid())

    def test_a_dead_reservers_claim_inside_the_grace_is_refused(self):
        # The launching CLI is the reserver and exits right after wt returns, before the
        # pane host adopts: a young reservation is a handoff in flight, not a crash.
        import time
        from convoy.targeted_launch import take_launch_claim
        self.write_claim("x-chair", reserver_pid=self.dead_pid(), reserved_at=time.time() - 5)
        with self.assertRaises(ValueError):
            take_launch_claim(self.root, "x-chair")

    def test_a_reservation_records_when_it_was_taken(self):
        import time
        from convoy.targeted_launch import read_launch_claim, take_launch_claim
        before = time.time()
        take_launch_claim(self.root, "x-chair")
        self.assertGreaterEqual(read_launch_claim(self.root, "x-chair")["reserved_at"], before - 1)

    def test_two_adopters_of_one_expired_claim_have_exactly_one_winner(self):
        import time
        from convoy import targeted_launch
        self.write_claim("x-chair", reserver_pid=self.dead_pid(), reserved_at=time.time() - 60)
        real = targeted_launch._claim_expired
        results = []
        state = {"first": True}

        def judged(claim, **kw):
            verdict = real(claim, **kw)
            if state["first"]:
                # B has read the stale claim and judged it expired; A now runs to completion.
                state["first"] = False
                try:
                    targeted_launch.take_launch_claim(self.root, "x-chair")
                    results.append("A")
                except ValueError:
                    results.append("A refused")
            return verdict

        with mock.patch.object(targeted_launch, "_claim_expired", side_effect=judged):
            try:
                targeted_launch.take_launch_claim(self.root, "x-chair")
                results.append("B")
            except ValueError:
                results.append("B refused")
        self.assertEqual(results, ["A", "B refused"])

    def test_a_permission_error_on_adoption_is_an_already_claimed_refusal(self):
        import time
        from convoy import targeted_launch
        self.write_claim("x-chair", reserver_pid=self.dead_pid(), reserved_at=time.time() - 60)
        with mock.patch.object(targeted_launch.Path, "unlink", side_effect=PermissionError("in use")):
            with self.assertRaises(ValueError) as ctx:
                targeted_launch.take_launch_claim(self.root, "x-chair")
        self.assertIn("already claimed", str(ctx.exception))

    def test_a_dead_hosts_claim_is_adopted_by_a_reservation(self):
        from convoy.targeted_launch import take_launch_claim
        self.write_claim("x-chair", host_pid=self.dead_pid())
        take_launch_claim(self.root, "x-chair")

    def test_a_live_holder_still_refuses(self):
        from convoy.targeted_launch import take_launch_claim
        self.write_claim("x-chair", reserver_pid=os.getpid())
        with self.assertRaises(ValueError):
            take_launch_claim(self.root, "x-chair")

    def test_an_old_claim_naming_no_holder_still_refuses(self):
        from convoy.targeted_launch import take_launch_claim
        self.write_claim("x-chair")
        with self.assertRaises(ValueError):
            take_launch_claim(self.root, "x-chair")

    def test_a_crashed_cli_launch_no_longer_blocks_the_chair(self):
        join(self.root, "codex", session_id="fresh", worktree=str(self.other_dir()))
        import time
        self.write_claim("fresh", reserver_pid=self.dead_pid(), reserved_at=time.time() - 60)   # died mid-launch
        seat(self.root, "claude", "x-chair", worktree=str(self.other_dir()), resume="x-native")
        a = {"kind": "seated", "chair": "x-chair", "via": "environment", "why": None}
        buf = io.StringIO()
        with mock.patch("convoy.cli.resolve_launcher", return_value=a), \
             mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch, redirect_stdout(buf):
            rc = main(["--root", str(self.root), "launch", "--seat", "fresh"])
        self.assertEqual(rc, 0, buf.getvalue())
        launch.assert_called_once()


class McpNoteSaysItIsNoReceipt(unittest.TestCase):
    def test_the_note_tool_says_a_claimed_note_is_no_receipt_and_names_reply(self):
        from convoy.mcp_http import call_tool
        home = tempfile.TemporaryDirectory(prefix="convoy-launch-id-home-")
        self.addCleanup(home.cleanup)
        with mock.patch.dict(os.environ, {"CONVOY_HOME": home.name}):
            root = Path(tempfile.mkdtemp())
            card = call_tool(root, "note", {"summary": "synthetic", "instance_id": "chair-a", "to": "chair-b"})
        self.assertTrue(card["ok"], card)
        self.assertIs(card["receipt"], False)
        self.assertIn("does not count as a delivery receipt", card["receipt_note"])
        self.assertIn("convoy reply <token>", card["receipt_note"])


class RelaunchPromptCarriesIdentity(Base):
    def test_the_relaunch_prompt_names_the_lead_and_both_commands_and_no_wait_prose(self):
        from convoy.relaunch import relaunch_prompt
        lead = self.seat_lead()
        join(self.root, "codex", session_id="relaunched", worktree=str(self.other_dir()), launched_by=lead)
        prompt = relaunch_prompt(self.root, "relaunched", token="0" * 32, incarnation=2,
                                 now="2026-10-04T00:00:00Z", since=EPOCH, worktree="wt")
        self.assertIn(self.nid(lead), prompt)
        self.assertIn(" report \"...\"", prompt)
        self.assertIn(" reply <token> \"...\"", prompt)
        self.assertNotIn("inbox --wait", prompt)


if __name__ == "__main__":
    unittest.main()
