"""N neurons -> N chairs -> ONE window -> they ALL connect, observed not trusted
(wizard item E, 2026-09-04).

Reader 4 found the gap: the wizard prose said join + launch for chair 1, then
`seat` for chairs 2..N, then bring_up - and `seat` never writes a boot prompt,
so chairs 2..N came up with a bare harness argv and no instruction to connect.
Nothing waited for a seated ack either: launch_state='launched' meant wt.exe
Popen returned, not that a neuron sat down.

Four guarantees:

1. crew(seats) validates every seat (where/model/effort, items A-C) BEFORE any
   write, mints one worktree per local seat (item D), joins every chair with a
   boot prompt + token, and launches ONCE through bring_up: one runner call,
   one wt window, N panes (N-1 split-pane flags). Never launch_seat per chair.
2. seated and consent are MCP tools behind the write gate, hidden from a public
   tools/list; a public call refuses without writing.
3. await_seated polls kind=seated rows and returns per chair
   connected | pending | stale with the time waited - measured on an injected
   clock, never a sleep in this suite. connected means the seated row cites
   the token this mint issued; anything else is not a connection.
4. Harnesses whose hooks cannot fire (cursor-agent / agy / hermes / pi,
   inbox.HARNESS_INBOX) carry connect_mode 'cli-drain' on the card and are
   never reported connected on the label alone.
"""
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import bring_up  # noqa: E402
from convoy.cli import main  # noqa: E402
from convoy.consent import request_consent  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, seat  # noqa: E402
from convoy.crew import await_seated, crew  # noqa: E402
from convoy.graph import build_graph  # noqa: E402
from convoy.inbox import HARNESS_INBOX, connect_mode  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import join, seated_ack  # noqa: E402
from convoy.mcp_http import _WRITE_TOOLS, make_server  # noqa: E402
from convoy.targeted_launch import launch_choices  # noqa: E402

EPOCH = "1970-01-01T00:00:00.000000Z"
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None}


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
    """Every harness and wt resolve to an absolute fake; nothing runs."""
    return "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"


def _norm(p) -> str:
    return os.path.normcase(str(Path(p).resolve()))


def _row(root, sid):
    return [s for s in list_seats(root) if s["session_id"] == sid][-1]


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd=None, **_k):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")


class CrewMintsJoinsAndLaunchesOnce(unittest.TestCase):
    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "crew-t")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def test_three_seats_three_worktrees_every_chair_booted_one_window(self):
        runner = mock.Mock(return_value={"ok": True, "pid": 4242})
        card = crew(self.root, [{"harness": "grok", "model": "grok-4", "effort": "high"},
                                {"harness": "claude", "effort": "max"},
                                {"harness": "codex", "model": "gpt-5.6-sol"}], runner=runner)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["thread"], "crew-t")
        self.assertTrue(card["launched"])
        sids = [s["session_id"] for s in card["seats"]]
        self.assertEqual(len(sids), 3)
        # 3 distinct worktrees, each a DERIVED sibling of the checkout (item D)
        wts = [s["worktree"] for s in card["seats"]]
        self.assertEqual(len({_norm(w) for w in wts}), 3)
        for w in wts:
            self.assertTrue(Path(w).is_dir(), w)
            self.assertTrue(Path(w).name.startswith(self.root.name + "-wt-"), w)
        # every chair has a boot prompt carrying ITS token, and a join row minted it
        joins = {r["instance_id"]: r for r in feed_since(self.root, EPOCH) if r["kind"] == "join"}
        for s in card["seats"]:
            disk = _row(self.root, s["session_id"])
            self.assertEqual(disk["where"], "local")
            self.assertTrue(disk["boot_prompt"], s["session_id"])
            self.assertIn(joins[s["session_id"]]["token"], disk["boot_prompt"])
            self.assertIn(s["session_id"], disk["boot_prompt"])
        by_to = {s["to"]: s for s in card["seats"]}
        self.assertEqual(by_to["grok"]["model"], "grok-4")
        self.assertEqual(by_to["grok"]["effort"], "high")
        self.assertTrue(by_to["grok"]["effort_applied"])
        self.assertEqual(by_to["claude"]["effort"], "max")
        self.assertEqual(by_to["codex"]["model"], "gpt-5.6-sol")
        # ONE runner call, ONE window, N panes: nt then N-1 split-pane
        self.assertEqual(runner.call_count, 1)
        argv = runner.call_args[0][0]
        self.assertEqual(argv[1:4], ["--window", "new", "nt"])
        self.assertEqual(argv.count("split-pane"), 2)
        dirs = [argv[i + 1] for i, a in enumerate(argv) if a == "-d"]
        self.assertEqual({_norm(d) for d in dirs}, {_norm(w) for w in wts})
        # the boot prompt rides each pane's argv (it is how the neuron learns to ack)
        for s in card["seats"]:
            self.assertTrue(any(s["session_id"] in a and "seated" in a for a in argv), s["session_id"])
        self.assertEqual([w["session_id"] for w in card["windows"]], sids)
        self.assertTrue(all(w["pid"] == 4242 for w in card["windows"]))
        # launched is not connected: the snapshot says pending for every chair
        self.assertEqual(card["seated"]["pending"], sids)
        self.assertEqual(card["seated"]["connected"], [])
        self.assertFalse(card["seated"]["ok"])
        self.assertEqual(card["next"], "await_seated")
        # receive labels ride the card; codex is native queue or drain, never "hook"
        self.assertEqual(by_to["grok"]["connect_mode"], "hook")
        self.assertEqual(by_to["claude"]["connect_mode"], "hook")
        self.assertEqual(by_to["codex"]["connect_mode"], "native-queue-or-cli-drain")

    def test_a_refused_seat_writes_nothing_mints_nothing_spawns_nothing(self):
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        minted = Recorder()
        cases = (
            ([{"harness": "grok", "effort": "ultra"}], "effort"),
            ([{"harness": "not-a-harness"}], "harness"),
            ([{"harness": "grok", "where": "orbit"}], "where"),
            ([{"harness": "agy", "where": "cloud"}], "unverified"),
            ([{"harness": "grok", "title": "same"}, {"harness": "claude", "title": "same"}], "same"),
            ([], "seats"),
        )
        for seats, needle in cases:
            card = crew(self.root, seats, runner=runner, mint_runner=minted)
            self.assertFalse(card["ok"], (seats, card))
            self.assertIn(needle, card["error"], card["error"])
            self.assertEqual(card["seats"], [])
            # review 2026-09-04: launched was `runner is not None`, so a refusal
            # with a runner handed in claimed to have acted. It never spawned.
            self.assertFalse(card["launched"], (seats, card))
        # `to` was an undocumented alias for harness; the schema names harness only
        alias = crew(self.root, [{"to": "codex"}], runner=runner, mint_runner=minted)
        self.assertFalse(alias["ok"])
        self.assertIn("harness", alias["error"])
        self.assertFalse(alias["launched"])
        mismatch = crew(self.root, [{"harness": "grok"}], thread="other", runner=runner, mint_runner=minted)
        self.assertFalse(mismatch["launched"], mismatch)
        self.assertEqual(list_seats(self.root), [], "a refused crew writes no chair")
        self.assertEqual(feed_since(self.root, EPOCH), [], "a refused crew mints no token")
        self.assertEqual(minted.calls, [], "a refused crew runs no git")
        runner.assert_not_called()

    def test_an_existing_chair_name_is_refused_before_mint(self):
        seat(self.root, "grok", "grok-1-crew-t")
        minted = Recorder()
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        card = crew(self.root, [{"harness": "grok"}], mint_runner=minted, runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("grok-1-crew-t", card["error"])
        self.assertEqual(minted.calls, [])
        runner.assert_not_called()
        self.assertFalse(card["launched"])

    def test_a_spawn_that_fails_or_raises_is_not_launched(self):
        # The chairs ARE written (join happened) but the window never came up:
        # launched is read from the runner's result, and the error is on the card
        # itself, not only buried in windows[i].
        card = crew(self.root, [{"harness": "grok"}], runner=mock.Mock(return_value={"ok": False, "error": "wt.exe: not found"}))
        self.assertFalse(card["ok"])
        self.assertFalse(card["launched"], card)
        self.assertIn("wt.exe: not found", card["error"])
        self.assertEqual(len(card["seats"]), 1)
        card = crew(self.root, [{"harness": "claude"}], runner=mock.Mock(side_effect=OSError("access denied")))
        self.assertFalse(card["ok"])
        self.assertFalse(card["launched"], card)
        self.assertIn("access denied", card["error"])
        # mint refused (checkout is not a git repo): joined nothing, launched nothing
        runner = mock.Mock(return_value={"ok": True, "pid": 3})
        card = crew(self.root, [{"harness": "codex"}], checkout=Path(tempfile.mkdtemp()), runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("mint refused", card["error"])
        self.assertFalse(card["launched"], card)
        runner.assert_not_called()

    def test_launch_false_writes_the_chairs_and_spawns_nothing(self):
        card = crew(self.root, [{"harness": "grok"}, {"harness": "claude"}])
        self.assertTrue(card["ok"], card)
        self.assertFalse(card["launched"])
        self.assertEqual(len(list_seats(self.root)), 2)
        # the argv that WOULD run is shown; nothing ran
        self.assertEqual(len(card["windows"]), 2)
        for w in card["windows"]:
            self.assertNotIn("pid", w)
            self.assertTrue(w["argv"])

    def test_thread_mismatch_refuses_and_a_cloud_seat_gets_no_pane(self):
        card = crew(self.root, [{"harness": "grok"}], thread="other")
        self.assertFalse(card["ok"])
        self.assertIn("other", card["error"])
        self.assertEqual(list_seats(self.root), [])
        offered = [h["id"] for h in launch_choices(self.root, which=_which, env={}, platform_name="nt",
                                                   git_worktrees=lambda _p: [])["harnesses"] if h["where"]["cloud"]["offered"]]
        self.assertTrue(offered, "the contract must offer cloud somewhere today")
        runner = mock.Mock(return_value={"ok": True, "pid": 9})
        card = crew(self.root, [{"harness": "grok"}, {"harness": offered[0], "where": "cloud"}], runner=runner)
        self.assertTrue(card["ok"], card)
        cloud = [s for s in card["seats"] if s["where"] == "cloud"]
        self.assertEqual(len(cloud), 1)
        self.assertIsNone(cloud[0]["worktree"])
        self.assertEqual(len(card["mint"]["worktrees"]), 1, "only local seats mint a worktree")
        self.assertEqual([w["session_id"] for w in card["windows"]], [s["session_id"] for s in card["seats"] if s["where"] == "local"])
        self.assertEqual([c["session_id"] for c in card["cloud"]], [cloud[0]["session_id"]])
        self.assertEqual(runner.call_args[0][0].count("split-pane"), 0)

    def test_bring_up_session_ids_filter_launches_only_the_named_chairs(self):
        wt_a, wt_b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        seat(self.root, "grok", "a", worktree=str(wt_a), resume="va")
        seat(self.root, "claude", "b", worktree=str(wt_b), resume="vb")
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        card = bring_up(self.root, runner=runner, session_ids=["b"])
        self.assertEqual([w["session_id"] for w in card["windows"]], ["b"])
        self.assertNotIn("va", runner.call_args[0][0])
        self.assertEqual([w["session_id"] for w in bring_up(self.root)["windows"]], ["a", "b"])


class ConnectModeLabels(unittest.TestCase):
    def test_hookless_harnesses_are_cli_drain_never_hook(self):
        for hid, kind in HARNESS_INBOX.items():
            mode = connect_mode(hid)
            if kind in ("grok-hooks", "claude-settings"):
                self.assertEqual(mode, "hook", hid)
            else:
                self.assertEqual(mode, kind, hid)
        for hid in ("cursor-agent", "agy", "hermes", "pi", "antigravity"):
            self.assertEqual(connect_mode(hid), "cli-drain", hid)
        self.assertEqual(connect_mode("codex.exe"), "native-queue-or-cli-drain")
        self.assertIsNone(connect_mode("not-a-harness"))

    def test_choices_rows_carry_connect_mode(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        rows = {h["id"]: h for h in launch_choices(root, which=_which, env={}, platform_name="nt",
                                                   git_worktrees=lambda _p: [])["harnesses"]}
        for hid in ("cursor-agent", "agy", "hermes", "pi"):
            self.assertEqual(rows[hid]["connect_mode"], "cli-drain", hid)
        self.assertEqual(rows["grok"]["connect_mode"], "hook")
        self.assertEqual(rows["codex"]["connect_mode"], "native-queue-or-cli-drain")


class AwaitSeated(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "aw")
        self.j1 = join(self.root, "grok", session_id="g1", worktree=str(Path(tempfile.mkdtemp())))
        self.j2 = join(self.root, "pi", session_id="p1", worktree=str(Path(tempfile.mkdtemp())))

    def test_pending_then_connected_as_rows_land_on_an_injected_clock(self):
        snap = await_seated(self.root, ["g1", "p1"], timeout=0, clock=lambda: 7.0, sleep=lambda _s: None)
        self.assertFalse(snap["ok"])
        self.assertEqual(snap["pending"], ["g1", "p1"])
        self.assertEqual(snap["connected"], [])
        self.assertEqual(snap["waited_s"], 0)
        states = {c["session_id"]: c for c in snap["chairs"]}
        self.assertEqual(states["g1"]["state"], "pending")
        self.assertEqual(states["p1"]["connect_mode"], "cli-drain")
        self.assertNotIn("token", json.dumps(snap).lower())

        # each fake second one neuron acks; no real time passes
        acks = iter([("g1", self.j1["token"]), ("p1", self.j2["token"])])
        slept = []

        def land(seconds):
            slept.append(seconds)
            sid, token = next(acks)
            seated_ack(self.root, sid, token)

        card = await_seated(self.root, ["g1", "p1"], timeout=30, interval=1, clock=itertools.count().__next__, sleep=land)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["connected"], ["g1", "p1"])
        self.assertEqual(card["pending"], [])
        self.assertEqual(len(slept), 2)
        self.assertGreater(card["waited_s"], 0)
        self.assertLessEqual(card["waited_s"], card["timeout_s"])
        for c in card["chairs"]:
            self.assertEqual(c["state"], "connected")
            self.assertTrue(c["seated_at"])
            self.assertTrue(c["minted_at"])

    def test_timeout_leaves_pending_with_time_waited_and_a_wrong_token_is_stale(self):
        clock = itertools.count(step=5).__next__  # every read is 5s later
        card = await_seated(self.root, ["g1"], timeout=10, interval=1, clock=clock, sleep=lambda _s: None)
        self.assertFalse(card["ok"])
        self.assertEqual(card["pending"], ["g1"])
        self.assertGreaterEqual(card["waited_s"], 10)
        # an ack citing a token this mint never issued is a stale proof, not a connection
        seated_ack(self.root, "g1", "not-the-minted-token")
        card = await_seated(self.root, ["g1"], timeout=0, clock=itertools.count().__next__, sleep=lambda _s: None)
        self.assertEqual(card["stale"], ["g1"])
        self.assertEqual(card["connected"], [])
        self.assertFalse(card["ok"])

    def test_unknown_chair_is_refused(self):
        with self.assertRaises(ValueError):
            await_seated(self.root, ["nope"], timeout=0, clock=itertools.count().__next__, sleep=lambda _s: None)


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class CrewWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".git").mkdir()  # mint's checkout check; git itself is mocked here
        ensure_id(self.root)
        bind(self.root, "wire")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.git = Recorder()
        # mcp_http imports live_runner by name, so that is the seam; the Popen
        # guard makes sure a missed seam can never reach wt.exe from here.
        for target, kw in (("convoy.repo.run_argv", {"new": self.git}),
                           ("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which}),
                           ("convoy.bringup.subprocess.Popen", {"side_effect": AssertionError("a test must never spawn")}),
                           ("convoy.mcp_http.live_runner", {"return_value": {"ok": True, "pid": 77}})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _call(self, name, **arguments):
        return _rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments})["result"]["structuredContent"]

    def _names(self):
        return {t["name"] for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}

    def test_public_list_hides_crew_seated_consent_await_and_a_public_call_writes_nothing(self):
        names = self._names()
        for hidden in ("crew", "seated", "consent", "await_seated"):
            self.assertNotIn(hidden, names, hidden)
            self.assertIn(hidden, _WRITE_TOOLS)
        card = self._call("crew", seats=[{"harness": "grok"}], launch=True)
        self.assertFalse(card["ok"])
        self.assertIn("CONVOY_MCP_WRITE_TOOLS", card["error"])
        self.assertEqual(list_seats(self.root), [])
        self.assertEqual(self.git.calls, [], "a refused crew runs no git")
        refused = self._call("seated", seat="x", token="t")
        self.assertFalse(refused["ok"])
        self.assertEqual(feed_since(self.root, EPOCH), [])
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        for name in ("crew", "seated", "consent", "await_seated"):
            self.assertIn(name, self._names(), name)

    def test_gated_crew_then_seated_over_rpc_closes_the_loop_the_graph_shows(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        card = self._call("crew", seats=[{"harness": "grok", "effort": "low"},
                                          {"harness": "claude"},
                                          {"harness": "codex"}], launch=True)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["launched"])
        self.assertEqual(len(card["seats"]), 3)
        self.assertEqual(len(self.git.calls), 3, "one git worktree add per local seat")
        self.assertTrue(all(c[:5] == ["git", "-C", str(self.root), "worktree", "add"] for c in self.git.calls))
        sids = [s["session_id"] for s in card["seats"]]
        # behind the gate the card is whole (the join precedent): the token rides
        tokens = {s["session_id"]: s["token"] for s in card["seats"]}
        self.assertTrue(all(tokens.values()))
        self.assertTrue(all(_row(self.root, sid)["boot_prompt"] for sid in sids))
        snap = self._call("await_seated", seats=sids, timeout=0)
        self.assertEqual(snap["pending"], sids)
        # the first neuron acks over the wire (a cloud neuron's proof will be exactly this)
        ack = self._call("seated", seat=sids[0], token=tokens[sids[0]])
        self.assertTrue(ack["ok"], ack)
        self.assertIsNone(_row(self.root, sids[0]).get("boot_prompt"), "the one-shot boot prompt clears on ack")
        chair = next(n for n in build_graph(self.root)["nodes"] if n["id"] == "chair:" + sids[0])
        self.assertEqual([e["kind"] for e in chair["lineage"]], ["join", "seated"])
        self.assertEqual(chair["lineage"][0]["state"], "acked")
        after = self._call("await_seated", seats=sids, timeout=0)
        self.assertEqual(after["connected"], [sids[0]])
        self.assertEqual(after["pending"], sids[1:])
        self.assertFalse(after["ok"])
        self.assertNotIn("token", json.dumps(after).lower())

    def test_await_seated_timeout_is_coerced_like_every_other_arg_never_defaulted(self):
        # review 2026-09-04: a string "0" (what an LLM client sends) fell through
        # `isinstance(raw, (int, float))` to 120.0 real seconds - the documented
        # snapshot became a two-minute block. Numeric strings coerce, like
        # _opt_bool does; out-of-schema values are refused, never replaced.
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        seen = mock.Mock(return_value={"ok": False, "chairs": [], "pending": [], "connected": [], "stale": []})
        with mock.patch("convoy.mcp_http.await_seated", seen):
            self._call("await_seated", seats=["g1"], timeout="0")
            self.assertEqual(seen.call_args.kwargs["timeout"], 0.0)
            self._call("await_seated", seats=["g1"], timeout=" 2.5 ")
            self.assertEqual(seen.call_args.kwargs["timeout"], 2.5)
            self._call("await_seated", seats=["g1"])
            self.assertEqual(seen.call_args.kwargs["timeout"], 120.0, "absent means the schema default")
            self._call("await_seated", seats=["g1"], timeout=10 ** 6)
            self.assertEqual(seen.call_args.kwargs["timeout"], 600.0, "clamped to AWAIT_SEATED_MAX_S")
            seen.reset_mock()
            for bad in ("soon", True, "nan", "inf", [5], {"s": 5}):
                card = self._call("await_seated", seats=["g1"], timeout=bad)
                self.assertFalse(card["ok"], bad)
                self.assertIn("timeout", card["error"], bad)
                self.assertEqual(card["chairs"], [])
            seen.assert_not_called()

    def test_gated_consent_grants_a_pending_request_over_rpc(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        wt = Path(tempfile.mkdtemp())
        req = request_consent(self.root, "trust-worktree", session_id="g", to="grok", worktree=str(wt))
        rid = req["consent_request"]["request_id"]
        card = self._call("consent", grant=rid)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["state"], "consent-granted")
        self.assertEqual(card["request_id"], rid)
        self.assertTrue(card["consent"])
        again = self._call("consent", grant=rid)
        self.assertFalse(again["ok"])
        self.assertIn("not pending", again["error"])
        missing = self._call("consent")
        self.assertFalse(missing["ok"])
        self.assertIn("grant", missing["error"])


class CrewCli(unittest.TestCase):
    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "cli-t")
        # real git mints here (no Popen guard: git IS a Popen); the window
        # seam is cli.live_runner, asserted below
        self.runner = mock.Mock(return_value={"ok": True, "pid": 5})
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which}),
                           ("convoy.cli.live_runner", {"new": self.runner})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--root", str(self.root), *argv])
        return rc, json.loads(buf.getvalue())

    def test_crew_spec_and_await_seated_verbs(self):
        rc, card = self._run("crew", "--seat", "grok,model=grok-4,effort=high", "--seat", "claude,title=opus", "--launch")
        self.assertEqual(rc, 0, card)
        self.assertTrue(card["launched"])
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(self.runner.call_args[0][0].count("split-pane"), 1)
        by_to = {s["to"]: s for s in card["seats"]}
        self.assertEqual(by_to["grok"]["model"], "grok-4")
        self.assertEqual(by_to["grok"]["effort"], "high")
        self.assertEqual(by_to["claude"]["title"], "opus")
        self.assertEqual(by_to["claude"]["session_id"], "opus-cli-t")
        rc, waited = self._run("await-seated", "--seat", by_to["grok"]["session_id"], "--timeout", "0")
        self.assertEqual(rc, 1, "not connected is not ok")
        self.assertEqual(waited["pending"], [by_to["grok"]["session_id"]])
        rc, bad = self._run("crew", "--seat", "grok,effort=ultra")
        self.assertEqual(rc, 1)
        self.assertIn("effort", bad["error"])


if __name__ == "__main__":
    unittest.main()
