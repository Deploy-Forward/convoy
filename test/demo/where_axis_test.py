"""The WHERE axis, truthfully (wizard item C, 2026-09-04).

A seat now says where its neuron runs: `where` in {local, cloud}, default
local. Every harness row in harness_effort.json carries a `cloud` block
{mode, cli, evidence} with mode in {unsupported, unverified,
interactive-session, task}, populated only from a local --help that was run
and quoted. Four guarantees:

1. Contract: every harness has the block; an interactive-session row carries
   the cli it quotes; an unverified row's evidence says so and dates it.
2. Writes: seat/join/register stamp where (local by default). join with
   where=cloud is REFUSED unless that harness's cloud.mode is
   interactive-session with evidence, and the refusal names the mode in the
   vendor's own words. A cloud seat has worktree null; C8 is a local rule.
3. Reads: choices lists where options per harness (local always; cloud only
   when offered, otherwise {offered: false, mode, evidence}); graph and
   neurons echo the seat's where.
4. No launcher: a cloud chair is never split into a pane and never rides a
   bring_up window; the card says why. Nothing in here spawns anything.
"""
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_activity  # noqa: E402
from convoy.bringup import bring_up  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat  # noqa: E402
from convoy.graph import build_graph  # noqa: E402
from convoy.harness_contract import cloud_contract, load_harness_contract, where_options  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import join, swap  # noqa: E402
from convoy.mcp_http import make_server  # noqa: E402
from convoy.registry import lookup  # noqa: E402
from convoy.targeted_launch import launch_choices, launch_seat  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MODES = {"unsupported", "unverified", "interactive-session", "task"}
EPOCH = "1970-01-01T00:00:00.000000Z"


def _by_mode(mode):
    return [row["id"] for row in load_harness_contract()["harnesses"] if row["cloud"]["mode"] == mode]


@contextmanager
def _cloud(hid, block):
    """The real contract with ONE harness's cloud block replaced."""
    data = copy.deepcopy(load_harness_contract())
    for row in data["harnesses"]:
        if row["id"] == hid:
            row["cloud"] = block
    with mock.patch("convoy.harness_contract.load_harness_contract", return_value=data):
        yield data


def _which(*present):
    names = {str(n).lower() for n in present}

    def lookup_name(name):
        key = str(name).lower()
        return ("C:\\Tools\\" + str(name)) if key in names or key.removesuffix(".exe") in names else None

    return lookup_name


class ContractCarriesACloudBlock(unittest.TestCase):
    def test_every_harness_has_a_cloud_block_with_mode_and_evidence(self):
        for row in load_harness_contract()["harnesses"]:
            self.assertIn("cloud", row, row["id"])
            block = row["cloud"]
            self.assertEqual(set(block), {"mode", "cli", "evidence"}, row["id"])
            self.assertIn(block["mode"], MODES, row["id"])
            self.assertIsInstance(block["evidence"], str, row["id"])
            self.assertTrue(block["evidence"].strip(), row["id"])
            if block["mode"] == "unverified":
                self.assertTrue(block["evidence"].startswith("unverified 20"), (row["id"], block["evidence"]))
                self.assertIsNone(block["cli"], row["id"] + ": no cli without a verified surface")
            else:
                self.assertFalse(block["evidence"].startswith("unverified"), (row["id"], block["evidence"]))
            if block["mode"] in ("interactive-session", "task"):
                # a mode that names a surface quotes the flag or subcommand
                # that IS that surface, and the evidence contains it verbatim
                self.assertIsInstance(block["cli"], str, row["id"])
                self.assertIn(block["cli"], block["evidence"], row["id"])

    def test_plugin_copy_is_byte_identical_and_carries_the_block(self):
        bundled = (REPO / "plugin" / "convoy" / "harness_effort.json").read_bytes()
        packaged = (REPO / "src" / "convoy" / "harness_effort.json").read_bytes()
        self.assertEqual(bundled, packaged)
        self.assertIn("cloud", json.loads(bundled)["harnesses"][0])

    def test_cloud_contract_view_and_where_options_follow_the_contract(self):
        for row in load_harness_contract()["harnesses"]:
            self.assertEqual(cloud_contract(row["id"]), row["cloud"], row["id"])
            opts = where_options(row["id"])
            self.assertEqual(opts["local"], {"offered": True}, row["id"])
            cloud = opts["cloud"]
            self.assertEqual(cloud["mode"], row["cloud"]["mode"], row["id"])
            self.assertEqual(cloud["evidence"], row["cloud"]["evidence"], row["id"])
            self.assertEqual(cloud["offered"], row["cloud"]["mode"] == "interactive-session", row["id"])
        self.assertEqual(cloud_contract("not-a-harness"), {"mode": None, "cli": None, "evidence": None})
        self.assertFalse(where_options("not-a-harness")["cloud"]["offered"])
        # the view is read from the contract, not a remembered table
        with _cloud("hermes", {"mode": "interactive-session", "cli": "--fixture", "evidence": "fixture --fixture"}):
            self.assertTrue(where_options("hermes.exe")["cloud"]["offered"])
            self.assertEqual(where_options("hermes")["cloud"]["cli"], "--fixture")
        with _cloud("hermes", {"mode": "interactive-session", "cli": "--fixture", "evidence": ""}):
            self.assertFalse(where_options("hermes")["cloud"]["offered"], "no evidence, no offer")


class SeatWritesWhere(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "where-thread")

    def _row(self, sid):
        return [s for s in list_seats(self.root) if s["session_id"] == sid][-1]

    def test_seat_defaults_where_to_local_on_seat_row_and_registry(self):
        row = seat(self.root, "grok", "g1", worktree=str(self.wt))
        self.assertEqual(row["where"], "local")
        self.assertEqual(self._row("g1")["where"], "local")
        self.assertEqual(lookup(self.root, "g1")["where"], "local")
        self.assertEqual(seat(self.root, "claude", "c1", where="LOCAL ")["where"], "local")

    def test_join_where_local_writes_local_on_the_seat_row(self):
        card = join(self.root, "grok", session_id="j1", worktree=str(self.wt), where="local")
        self.assertEqual(card["seat"]["where"], "local")
        self.assertEqual(self._row("j1")["where"], "local")
        self.assertEqual(lookup(self.root, "j1")["where"], "local")

    def test_join_where_cloud_is_refused_for_an_unverified_harness_naming_the_mode(self):
        unverified = _by_mode("unverified")
        self.assertTrue(unverified, "the contract must carry at least one unverified harness today")
        hid = unverified[0]
        evidence = cloud_contract(hid)["evidence"]
        with self.assertRaises(ValueError) as ctx:
            join(self.root, hid, session_id="cloudy", where="cloud")
        msg = str(ctx.exception)
        self.assertIn(hid, msg)
        self.assertIn("unverified", msg)
        self.assertIn(evidence, msg, "the refusal quotes the vendor's own --help evidence")
        self.assertEqual(list_seats(self.root), [], "a refused join writes nothing")
        self.assertEqual(feed_since(self.root, EPOCH), [], "a refused join mints no token and stamps no row")

    def test_join_where_cloud_is_refused_for_a_task_harness_too(self):
        with _cloud("codex", {"mode": "task", "cli": "codex cloud exec", "evidence": "fixture: codex cloud exec"}):
            with self.assertRaises(ValueError) as ctx:
                join(self.root, "codex", session_id="t1", where="cloud")
        self.assertIn("task", str(ctx.exception))
        self.assertIn("codex cloud exec", str(ctx.exception))
        self.assertEqual(list_seats(self.root), [])

    def test_join_where_cloud_seats_an_interactive_session_harness_with_worktree_null(self):
        offered = _by_mode("interactive-session")
        self.assertTrue(offered, "the contract must evidence at least one interactive-session harness today")
        hid = offered[0]
        card = join(self.root, hid, session_id="cl1", where="cloud")
        self.assertEqual(card["seat"]["where"], "cloud")
        self.assertIsNone(card["seat"]["worktree"])
        self.assertEqual(lookup(self.root, "cl1")["where"], "cloud")
        # a cloud seat has no local checkout: a worktree is refused, not dropped
        with self.assertRaises(ValueError) as ctx:
            join(self.root, hid, session_id="cl2", where="cloud", worktree=str(self.wt))
        self.assertIn("worktree", str(ctx.exception))
        self.assertEqual([s["session_id"] for s in list_seats(self.root)], ["cl1"])
        # and C8 still holds for local chairs on the same root
        seat(self.root, "grok", "g-local", worktree=str(self.wt))
        with self.assertRaises(ValueError):
            seat(self.root, "claude", "c-local", worktree=str(self.wt))

    def test_where_outside_the_axis_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            seat(self.root, "grok", "orbit", where="orbit")
        self.assertIn("local", str(ctx.exception))
        self.assertIn("cloud", str(ctx.exception))
        self.assertEqual(list_seats(self.root), [])

    def test_swap_onto_a_harness_without_cloud_attach_is_refused_and_silent(self):
        offered = _by_mode("interactive-session")
        self.assertTrue(offered)
        join(self.root, offered[0], session_id="cl-swap", where="cloud")
        hp = self.root / "h.md"
        hp.write_text("h", encoding="utf-8")
        before = feed_since(self.root, EPOCH)
        unverified = _by_mode("unverified")[0]
        with self.assertRaises(ValueError) as ctx:
            swap(self.root, "cl-swap", unverified, str(hp), author="cl-swap")
        self.assertIn("unverified", str(ctx.exception))
        self.assertEqual(feed_since(self.root, EPOCH), before, "a refused swap stamps nothing")
        self.assertEqual(self._row("cl-swap")["to"], offered[0])
        # a legacy row without the field is a local chair: the axis did not
        # exist when it was written and every pane then was local
        seat(self.root, "grok", "legacy", worktree=str(self.wt))
        legacy = {k: v for k, v in self._row("legacy").items() if k != "where"}
        with (Path(self.root) / ".convoy" / "seats.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        self.assertNotIn("where", self._row("legacy"))
        self.assertEqual(update_seat(self.root, "legacy", title="t")["where"], "local")


class ReadsEchoWhere(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "where-reads")

    def _choices(self):
        return launch_choices(
            self.root, cwd=self.root, env={}, which=_which("grok", "claude"),
            platform_name="nt", git_worktrees=lambda _paths: [],
        )

    def test_choices_lists_where_per_harness_and_never_offers_cloud_unverified(self):
        contract = {h["id"]: h for h in load_harness_contract()["harnesses"]}
        for h in self._choices()["harnesses"]:
            block = contract[h["id"]]["cloud"]
            self.assertEqual(h["where"]["local"], {"offered": True}, h["id"])
            cloud = h["where"]["cloud"]
            self.assertEqual(cloud["mode"], block["mode"], h["id"])
            self.assertEqual(cloud["evidence"], block["evidence"], h["id"])
            if block["mode"] == "interactive-session":
                self.assertTrue(cloud["offered"], h["id"])
                self.assertEqual(cloud["cli"], block["cli"], h["id"])
            else:
                self.assertFalse(cloud["offered"], h["id"])
        # offered flips with the contract, not with installation
        with _cloud("pi", {"mode": "interactive-session", "cli": "--fixture", "evidence": "pi --fixture"}):
            by_id = {h["id"]: h for h in self._choices()["harnesses"]}
        self.assertFalse(by_id["pi"]["installed"])
        self.assertTrue(by_id["pi"]["where"]["cloud"]["offered"])

    def test_choices_seats_graph_and_neurons_echo_where(self):
        seat(self.root, "grok", "g-loc", worktree=str(self.wt))
        offered = _by_mode("interactive-session")
        self.assertTrue(offered)
        join(self.root, offered[0], session_id="c-cloud", where="cloud")
        by_sid = {s["session_id"]: s for s in self._choices()["seats"]}
        self.assertEqual(by_sid["g-loc"]["where"], "local")
        self.assertEqual(by_sid["c-cloud"]["where"], "cloud")
        chairs = {n["session_id"]: n for n in build_graph(self.root)["nodes"] if n["kind"] == "chair"}
        self.assertEqual(chairs["g-loc"]["where"], "local")
        self.assertEqual(chairs["c-cloud"]["where"], "cloud")
        self.assertIsNone(chairs["c-cloud"]["worktree"])
        rows = {n["session_id"]: n for n in neuron_activity(self.root, procs=[])["neurons"]}
        self.assertEqual(rows["g-loc"]["where"], "local")
        self.assertEqual(rows["c-cloud"]["where"], "cloud")

    def test_roster_carries_where_options_from_the_contract(self):
        from convoy.mcp_http import build_roster

        with mock.patch("convoy.mcp_http.shutil.which", return_value=None), \
             mock.patch("convoy.mcp_http.ensure_interactive_path", return_value={"ok": True}):
            card = build_roster(self.root)
        for a in card["agents"]:
            self.assertEqual(a["where"], where_options(a["id"]), a["id"])


class NoCloudLauncherExists(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "where-launch")
        offered = _by_mode("interactive-session")
        self.assertTrue(offered)
        self.hid = offered[0]

    def test_launch_refuses_a_cloud_chair_and_spawns_nothing(self):
        join(self.root, self.hid, session_id="cl-launch", where="cloud")
        runner = mock.Mock(return_value={"ok": True, "pid": 1})
        card = launch_seat(self.root, "cl-launch", runner=runner, env={"WT_SESSION": "x"},
                           which=_which("wt", self.hid), platform_name="nt")
        self.assertFalse(card["ok"])
        self.assertIn("cloud", card["error"])
        self.assertIn("launcher", card["error"])
        runner.assert_not_called()

    @mock.patch("convoy.bringup.ensure_first_run", return_value={"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None})
    def test_bring_up_never_makes_a_cloud_chair_a_pane_and_says_so(self, _fr):
        seat(self.root, "grok", "g-pane", worktree=str(self.wt), resume="vendor-1")
        join(self.root, self.hid, session_id="cl-pane", where="cloud")
        runner = mock.Mock(return_value={"ok": True, "pid": 7})
        with mock.patch("convoy.bringup.shutil.which", return_value="C:\\Tools\\wt.exe"):
            card = bring_up(self.root, runner=runner)
        self.assertEqual([w["session_id"] for w in card["windows"]], ["g-pane"])
        self.assertEqual(runner.call_count, 1)
        wt_argv = runner.call_args[0][0]
        self.assertFalse(any("cl-pane" in str(a) for a in wt_argv), wt_argv)
        cloud = {c["session_id"]: c for c in card["cloud"]}
        self.assertEqual(cloud["cl-pane"]["to"], self.hid)
        self.assertEqual(cloud["cl-pane"]["where"], "cloud")
        self.assertFalse(cloud["cl-pane"]["pane"])
        self.assertIn("launcher", cloud["cl-pane"]["reason"])
        self.assertIn("MCP", cloud["cl-pane"]["reason"])


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class WhereOverTheMcpWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "where-wire")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _call(self, name, **arguments):
        return _rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments})["result"]["structuredContent"]

    def test_public_choices_carries_where_and_the_seat_join_schemas_take_it(self):
        for h in self._call("choices")["harnesses"]:
            self.assertEqual(h["where"], where_options(h["id"]), h["id"])
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        tools = {t["name"]: t for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}
        for name in ("seat", "join"):
            prop = tools[name]["inputSchema"]["properties"]["where"]
            self.assertEqual(prop["enum"], ["local", "cloud"], name)
            self.assertIn("choices.harnesses[].where", prop["description"], name)

    def test_join_where_cloud_refused_over_the_wire_writes_nothing(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        unverified = _by_mode("unverified")[0]
        card = self._call("join", to=unverified, session_id="w-cloud", where="cloud")
        self.assertFalse(card["ok"])
        self.assertIn("unverified", card["error"])
        self.assertEqual(list_seats(self.root), [])
        offered = _by_mode("interactive-session")[0]
        good = self._call("join", to=offered, session_id="w-cloud", where="cloud")
        self.assertTrue(good["ok"], good)
        self.assertEqual(good["seat"]["where"], "cloud")
        self.assertIsNone(good["seat"]["worktree"])
        local = self._call("seat", to="grok", session_id="w-local")
        self.assertEqual(local["where"], "local")


if __name__ == "__main__":
    unittest.main()
