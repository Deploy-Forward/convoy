"""Per-harness effort on the wire, validated per harness, applied to argv
only where the contract carries an evidenced CLI flag (wizard item A,
2026-09-04).

Three guarantees:

1. `choices` surfaces harnesses[].effort = {mode, keys, cli_flag, evidence,
   applied} straight from harness_effort.json. No effort block -> nulls.
2. seat/join/swap validate effort PER HARNESS: grok takes xhigh, codex takes
   extra-high, pi takes --thinking levels. A refusal names the harness's
   real keys. A harness with no vocabulary (cursor-agent unknown, hermes
   model-driven) records the declaration and marks it not applied.
3. resume_argv emits the harness's flag when, and only when, the contract has
   cli_flag + evidence; the seat row says so in effort_applied. A legacy row
   carrying a value the harness does not take never reaches argv.
"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import resume_argv
from convoy.cli import main
from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat
from convoy.harness_contract import effort_contract, load_harness_contract, validate_effort
from convoy.lifecycle import join, swap
from convoy.mcp_http import make_server
from convoy.targeted_launch import launch_choices


def _contract(hid):
    return next(h for h in load_harness_contract()["harnesses"] if h["id"] == hid)


def _which(*present):
    names = {str(n).lower() for n in present}

    def lookup(name):
        key = str(name).lower()
        return ("C:\\Tools\\" + str(name)) if key in names or key.removesuffix(".exe") in names else None

    return lookup


def _flag_pair(argv, flag):
    """The (flag, value) pair as it sits in argv, or None."""
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return [a, argv[i + 1]]
    return None


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue().strip()
    return rc, (json.loads(raw) if raw else None)


class EffortOnTheWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "effort-thread")

    def _choices(self):
        return launch_choices(
            self.root, cwd=self.root, env={}, which=_which("grok", "claude"),
            platform_name="nt", git_worktrees=lambda _paths: [],
        )

    def test_choices_carries_each_harness_effort_from_the_contract(self):
        by_id = {h["id"]: h for h in self._choices()["harnesses"]}
        grok = by_id["grok"]["effort"]
        self.assertEqual(grok["keys"], _contract("grok")["effort"]["keys"])
        self.assertEqual(grok["cli_flag"], "--reasoning-effort")
        self.assertTrue(grok["evidence"])
        self.assertTrue(grok["applied"])
        claude = by_id["claude"]["effort"]
        self.assertEqual(claude["cli_flag"], "--effort")
        self.assertIn("max", claude["keys"])
        self.assertNotIn("ultracode", claude["keys"])

    def test_choices_is_null_where_the_contract_is_silent(self):
        by_id = {h["id"]: h for h in self._choices()["harnesses"]}
        cursor = by_id["cursor-agent"]["effort"]
        # the contract spells this mode "unknown"; the wire says null, never "unknown"
        self.assertIsNone(cursor["mode"])
        self.assertIsNone(cursor["keys"])
        self.assertIsNone(cursor["cli_flag"])
        self.assertIsNone(cursor["evidence"])
        self.assertFalse(cursor["applied"])
        # codex has keys but no cli_flag and no evidence string: recorded, not applied
        codex = by_id["codex"]["effort"]
        self.assertIn("extra-high", codex["keys"])
        self.assertIsNone(codex["cli_flag"])
        self.assertFalse(codex["applied"])

    def test_pi_keys_are_its_thinking_levels(self):
        # pi has no harness-scoped keys; what seat/join accept as effort and
        # what --thinking takes are the same list, so that is what the card shows.
        pi = effort_contract("pi")
        self.assertEqual(pi["mode"], "model-driven")
        self.assertEqual(pi["cli_flag"], "--thinking")
        self.assertEqual(pi["keys"], _contract("pi")["effort"]["cli_values"])
        self.assertTrue(pi["applied"])

    def test_unknown_harness_is_all_null(self):
        self.assertEqual(
            effort_contract("not-a-harness"),
            {"mode": None, "keys": None, "cli_flag": None, "evidence": None, "applied": False},
        )


class EffortValidatedPerHarness(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)

    def _row(self, sid):
        return [s for s in list_seats(self.root) if s["session_id"] == sid][-1]

    def test_seat_refuses_an_effort_the_harness_does_not_have_naming_its_keys(self):
        with self.assertRaises(ValueError) as ctx:
            seat(self.root, "grok", "g1", effort="max")
        msg = str(ctx.exception)
        self.assertIn("grok", msg)
        for key in ("low", "medium", "high", "xhigh"):
            self.assertIn(key, msg)
        self.assertEqual(list_seats(self.root), [], "a refused seat writes nothing")

    def test_validate_effort_is_per_harness_not_a_global_enum(self):
        self.assertEqual(validate_effort("codex", "extra-high"), "extra-high")
        with self.assertRaises(ValueError):
            validate_effort("claude", "extra-high")
        self.assertEqual(validate_effort("claude", "max"), "max")
        with self.assertRaises(ValueError):
            validate_effort("agy", "max")
        self.assertEqual(validate_effort("pi", "off"), "off")
        with self.assertRaises(ValueError):
            validate_effort("pi", "extra-high")
        # aliases resolve to the harness they name
        self.assertEqual(validate_effort("claude-code", "xhigh"), "xhigh")
        # blank is null, never ""
        self.assertIsNone(validate_effort("grok", "  "))
        self.assertIsNone(validate_effort("grok", None))

    def test_seat_row_says_whether_the_effort_reaches_argv(self):
        self.assertTrue(seat(self.root, "claude", "c1", effort="high")["effort_applied"])
        codex = seat(self.root, "codex", "x1", effort="extra-high")
        self.assertEqual(codex["effort"], "extra-high")
        self.assertFalse(codex["effort_applied"])
        # no vocabulary to check against: recorded, not applied, not refused
        cursor = seat(self.root, "cursor-agent", "k1", effort="high")
        self.assertEqual(cursor["effort"], "high")
        self.assertFalse(cursor["effort_applied"])
        # no effort declared: nothing to apply, and that is null, not false
        bare = seat(self.root, "claude", "c2")
        self.assertIsNone(bare["effort"])
        self.assertIsNone(bare["effort_applied"])

    def test_join_validates_for_the_joined_harness(self):
        with self.assertRaises(ValueError) as ctx:
            join(self.root, "agy", session_id="a1", worktree=str(self.root), effort="xhigh")
        self.assertIn("agy", str(ctx.exception))
        self.assertIn("medium", str(ctx.exception))
        card = join(self.root, "agy", session_id="a1", worktree=str(self.root), effort="high")
        self.assertEqual(card["seat"]["effort"], "high")
        self.assertTrue(card["seat"]["effort_applied"])

    def test_swap_revalidates_against_the_incoming_harness(self):
        seat(self.root, "claude", "chair-1", worktree=str(self.root), effort="max")
        hp = self.root / "h.md"
        hp.write_text("h", encoding="utf-8")
        # claude's max is not a grok key: the declaration does not follow the
        # chair onto a harness that cannot take it.
        swap(self.root, "chair-1", "grok", str(hp), author="chair-1")
        row = self._row("chair-1")
        self.assertIsNone(row["effort"])
        self.assertIsNone(row["effort_applied"])
        # an explicit effort on swap is validated for the new harness
        with self.assertRaises(ValueError):
            swap(self.root, "chair-1", "codex", str(hp), author="chair-1", effort="xhigh")
        swap(self.root, "chair-1", "codex", str(hp), author="chair-1", effort="extra-high")
        row = self._row("chair-1")
        self.assertEqual(row["effort"], "extra-high")
        self.assertFalse(row["effort_applied"])

    def test_update_seat_recomputes_applied_when_the_harness_changes(self):
        seat(self.root, "claude", "chair-2", effort="high")
        update_seat(self.root, "chair-2", to="codex")
        row = self._row("chair-2")
        self.assertEqual(row["effort"], "high")  # high is a codex key too
        self.assertFalse(row["effort_applied"])
        with self.assertRaises(ValueError):
            update_seat(self.root, "chair-2", effort="banana")

    def test_cli_swap_takes_effort(self):
        _run_cli(self.root, "init")
        _run_cli(self.root, "join", "--to", "claude", "--session-id", "c1", "--worktree", str(self.root))
        hp = self.root / ".ola" / "h-handoff.md"
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text("x", encoding="utf-8")
        rc, card = _run_cli(self.root, "swap", "--seat", "c1", "--to", "grok",
                            "--handoff", str(hp), "--as", "c1", "--effort", "xhigh")
        self.assertEqual(rc, 0)
        self.assertEqual(card["seat"]["effort"], "xhigh")
        self.assertTrue(card["seat"]["effort_applied"])


class EffortReachesArgvWhereEvidenced(unittest.TestCase):
    def test_evidenced_flags_are_emitted_from_the_contract(self):
        self.assertEqual(_flag_pair(resume_argv({"to": "claude", "effort": "high"}), "--effort"), ["--effort", "high"])
        grok = resume_argv({"to": "grok", "model": "grok-4", "effort": "xhigh", "resume": "sid-g"})
        self.assertEqual(_flag_pair(grok, "--reasoning-effort"), ["--reasoning-effort", "xhigh"])
        self.assertLess(grok.index("--reasoning-effort"), grok.index("--resume"))
        self.assertEqual(_flag_pair(resume_argv({"to": "agy", "effort": "low"}), "--effort"), ["--effort", "low"])
        self.assertEqual(_flag_pair(resume_argv({"to": "pi", "effort": "high"}), "--thinking"), ["--thinking", "high"])

    def test_no_flag_without_evidence(self):
        cursor = resume_argv({"to": "cursor-agent", "effort": "high"})
        self.assertNotIn("--effort", cursor)
        self.assertNotIn("high", cursor)
        codex = resume_argv({"to": "codex", "effort": "extra-high", "resume": "sid-x"})
        self.assertNotIn("extra-high", codex)
        self.assertNotIn("model_reasoning_effort", " ".join(codex))
        self.assertNotIn("--effort", resume_argv({"to": "hermes", "effort": "high"}))

    def test_a_legacy_row_with_a_foreign_value_never_reaches_argv(self):
        # rows written before validation existed may carry anything; the
        # vendor never sees a value its --help does not list.
        argv = resume_argv({"to": "claude", "effort": "banana", "resume": "sid-c"})
        self.assertNotIn("--effort", argv)
        self.assertNotIn("banana", argv)
        self.assertNotIn("--effort", resume_argv({"to": "claude"}))


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class EffortOverTheMcpWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "wire")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _call(self, name, **arguments):
        return _rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments})["result"]["structuredContent"]

    def test_seat_and_join_refuse_a_bad_effort_naming_the_harness_keys(self):
        card = self._call("seat", to="grok", session_id="g-wire", effort="max")
        self.assertFalse(card["ok"])
        self.assertIn("xhigh", card["error"])
        self.assertEqual(list_seats(self.root), [])
        card = self._call("join", to="agy", session_id="a-wire", worktree=str(self.root), effort="xhigh")
        self.assertFalse(card["ok"])
        self.assertIn("medium", card["error"])
        good = self._call("seat", to="grok", session_id="g-wire", effort="xhigh")
        self.assertTrue(good["ok"], good)
        self.assertTrue(good["effort_applied"])

    def test_seat_schema_says_effort_is_per_harness(self):
        tools = {t["name"]: t for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}
        for name in ("seat", "join"):
            desc = tools[name]["inputSchema"]["properties"]["effort"].get("description", "")
            self.assertIn("choices", desc, name)
            self.assertNotIn("enum", tools[name]["inputSchema"]["properties"]["effort"])

    def test_roster_scopes_effort_per_harness_not_globally(self):
        with mock.patch("convoy.mcp_http.shutil.which", return_value=None), \
             mock.patch("convoy.mcp_http.ensure_interactive_path", return_value={"ok": True}):
            card = self._call("roster")
        self.assertNotIn("effort_types", card["contract"])
        by_id = {a["id"]: a for a in card["agents"]}
        self.assertEqual(by_id["grok"]["effort"]["keys"], _contract("grok")["effort"]["keys"])
        self.assertIsNone(by_id["cursor-agent"]["effort"]["keys"])


class EffortAppliedOnTheChip(unittest.TestCase):
    def test_glance_seat_card_says_recorded_not_applied(self):
        from convoy.glance import build_by_thread

        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        seat(root, "codex", "x-chip", effort="extra-high")
        card = build_by_thread(
            root, probe_fn=lambda _h: {"usage_remaining": None, "limited": False, "raw": None},
            which_fn=lambda _n: None,
        )
        row = card["seats"][0]
        self.assertEqual(row["effort"], "extra-high")
        self.assertFalse(row["effort_applied"])
        seat(root, "claude", "c-chip")
        bare = [s for s in build_by_thread(
            root, probe_fn=lambda _h: {"usage_remaining": None, "limited": False, "raw": None},
            which_fn=lambda _n: None)["seats"] if s["session_id"] == "c-chip"][0]
        self.assertNotIn("effort", bare)
        self.assertNotIn("effort_applied", bare)


if __name__ == "__main__":
    unittest.main()
