"""ONE card (wizard item F, 2026-09-04): what a host renders for @convoy in
place of Exa/Apollo provider rows.

Marco's vision: `@convoy` renders one card headed "convoy" with a drill-down
harness -> model -> effort | attach as neuron, USAGE REMAINING per harness, and
"launch your neurons in the cloud/local" where a SaaS card would say Exa/Apollo.
The wizard calls `card` once and drives repos -> onboard -> crew -> consent ->
await_seated from what it returned; a remote host has no filesystem, so the
card must carry everything the older prose told the host to read from disk.

Guarantees:

1. `card` is a public READ tool (not in _WRITE_TOOLS) declared with an MCP
   outputSchema and answered through structuredContent; the payload satisfies
   its own schema's required keys.
2. One row per contract harness, in contract order, with effort.keys from the
   contract, models from the catalog (null where unverified), where = the
   offered axis, connect_mode, and attach = {tool: crew, args.seats[...]}.
3. usage_remaining rides the same path glance uses: JSON null when the probe
   says null, the probed number when it says one, never an invented 0. The
   probe is mocked here; the suite never shells out to a vendor CLI.
4. The card carries its own Gate 0 verdict: preflight() scored against THIS
   server's own tools/list, so preflight.ok is False on a public process
   (gated verbs hidden) and True on a gated one.
5. A seeded vendor resume id and a seeded inbox token appear NOWHERE in
   json.dumps(card): the card never names a seat row.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.card import CARD_OUTPUT_SCHEMA, HEADER, TAGLINE, build_card  # noqa: E402
from convoy.convoy import bind, ensure_id, seat  # noqa: E402
from convoy.harness_contract import load_harness_contract  # noqa: E402
from convoy.lifecycle import join  # noqa: E402
from convoy.mcp_http import TOOLS, _WRITE_TOOLS, make_server  # noqa: E402
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS  # noqa: E402

RESUME_ID = "LEAK-RESUME-card-7c3e91"
NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


def _which(*present):
    names = {str(n).lower() for n in present}

    def lookup(name):
        key = str(name).lower().removesuffix(".exe")
        return ("C:\\Tools\\" + str(name)) if key in names else None

    return lookup


def _contract_ids():
    return [h["id"] for h in load_harness_contract()["harnesses"]]


def _require(schema, payload, path="card"):
    """Every `required` key the schema names is present in the payload,
    recursively through object properties and array items."""
    for key in schema.get("required") or []:
        assert key in payload, path + " lacks required key " + repr(key)
    for key, sub in (schema.get("properties") or {}).items():
        if key not in payload or not isinstance(sub, dict):
            continue
        val = payload[key]
        if isinstance(val, dict) and sub.get("properties"):
            _require(sub, val, path + "." + key)
        elif isinstance(val, list) and isinstance(sub.get("items"), dict):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    _require(sub["items"], item, path + "." + key + "[" + str(i) + "]")


class CardShape(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "card-t")

    def _card(self, probe=None, which=None, listed=REQUIRED_WIZARD_VERBS):
        # listed=None is a FAILED tools/list, not the default; the default is a green list
        return build_card(
            self.root,
            listed=None if listed is None else list(listed),
            probe_fn=probe or (lambda _h: dict(NULL_PROBE)),
            which_fn=which or _which("grok", "claude"),
            git_worktrees=lambda _paths: [],
        )

    def test_header_tagline_and_one_row_per_contract_harness_in_contract_order(self):
        card = self._card()
        self.assertTrue(card["ok"])
        self.assertEqual(card["header"], "convoy")
        self.assertEqual(card["header"], HEADER)
        self.assertEqual(card["tagline"], TAGLINE)
        self.assertIn("cloud/local", card["tagline"])
        self.assertEqual([r["harness"] for r in card["rows"]], _contract_ids())
        _require(CARD_OUTPUT_SCHEMA, card)

    def test_rows_carry_effort_keys_models_where_connect_mode_and_a_crew_attach(self):
        contract = {h["id"]: h for h in load_harness_contract()["harnesses"]}
        rows = {r["harness"]: r for r in self._card()["rows"]}
        for hid, row in rows.items():
            eff = contract[hid].get("effort") or {}
            self.assertEqual(row["effort"]["keys"], eff.get("keys") or (eff.get("cli_values") if eff.get("cli_flag") else None), hid)
            self.assertIn("applied", row["effort"], hid)
            self.assertIn("cli_flag", row["effort"], hid)
            self.assertEqual(row["models"], contract[hid]["models"], hid)
            self.assertEqual(row["models_evidence"], contract[hid]["models_evidence"], hid)
            self.assertIn("local", row["where"], hid)
            self.assertEqual("cloud" in row["where"], contract[hid]["cloud"]["mode"] == "interactive-session", hid)
            self.assertEqual(row["attach"]["tool"], "crew", hid)
            self.assertEqual(row["attach"]["args"]["seats"], [{"harness": hid, "where": "local", "model": None, "effort": None}], hid)
            self.assertIn(row["connect_mode"], ("hook", "native-queue-or-cli-drain", "cli-drain"), hid)
        self.assertEqual(rows["grok"]["effort"]["keys"], ["low", "medium", "high", "xhigh"])
        self.assertIsNone(rows["hermes"]["effort"]["keys"])
        self.assertEqual(rows["claude"]["where"], ["local", "cloud"])
        self.assertEqual(rows["codex"]["where"], ["local"])
        self.assertTrue(rows["grok"]["installed"])
        self.assertFalse(rows["pi"]["installed"])

    def test_usage_remaining_is_null_from_a_null_probe_and_the_number_from_a_live_one(self):
        rows = {r["harness"]: r for r in self._card()["rows"]}
        for hid, row in rows.items():
            self.assertIsNone(row["usage_remaining"], hid)
            self.assertFalse(row["limited"], hid)
        probed = []

        def live(key):
            probed.append(key)
            if key == "claude":
                return {"usage_remaining": 42, "limited": False, "raw": "42"}
            return dict(NULL_PROBE)

        rows = {r["harness"]: r for r in self._card(probe=live)["rows"]}
        self.assertEqual(rows["claude"]["usage_remaining"], 42)
        self.assertIsNone(rows["grok"]["usage_remaining"], "grok has no meter; a probe answer never becomes 0")
        # only installed harnesses are probed; a missing binary is never asked
        self.assertEqual(sorted(probed), ["claude", "grok"])
        self.assertIsNone(rows["codex"]["usage_remaining"])
        # a probe that says 0 without raw output is a non-answer, not a zero
        zero = lambda _k: {"usage_remaining": 0, "limited": False, "raw": None}  # noqa: E731
        rows = {r["harness"]: r for r in self._card(probe=zero, which=_which("grok", "agy"))["rows"]}
        self.assertIsNone(rows["grok"]["usage_remaining"])
        self.assertIsNone(rows["agy"]["usage_remaining"])

    def test_summary_counts_installed_and_seats_and_github_stays_null_until_asked(self):
        card = self._card()
        self.assertEqual(card["summary"]["harnesses_installed"], 2)
        self.assertEqual(card["summary"]["seats"], 0)
        self.assertEqual(card["summary"]["thread"], "card-t")
        self.assertIsNone(card["summary"]["github"])
        self.assertIsNone(card["repo"]["github"])
        # no .git at the root: crew has nothing to mint from, and the card says null, not the root
        self.assertIsNone(card["repo"]["checkout"])
        wt = Path(tempfile.mkdtemp())
        seat(self.root, "grok", "g-card", worktree=str(wt))
        seat(self.root, "grok-bot", "grok-bot")
        (self.root / ".git").mkdir()
        card = self._card()
        self.assertEqual(card["summary"]["seats"], 1, "the conductor is not a neuron seat")
        self.assertEqual(Path(card["repo"]["checkout"]).resolve(), self.root.resolve())
        known = {os.path.normcase(str(Path(w).resolve())) for w in card["repo"]["worktrees"]}
        self.assertIn(os.path.normcase(str(wt.resolve())), known, "a seated worktree is a known worktree")

    def test_preflight_rides_the_card_and_is_scored_on_the_list_handed_in(self):
        public = [t["name"] for t in TOOLS if t["name"] not in _WRITE_TOOLS]
        card = self._card(listed=public)
        self.assertFalse(card["preflight"]["ok"])
        self.assertEqual(card["preflight"]["status"], "RED")
        self.assertTrue(card["preflight"]["missing"])
        self.assertTrue(all(v in _WRITE_TOOLS for v in card["preflight"]["missing"]))
        self.assertEqual(card["preflight"]["listed"], sorted(set(public)))
        gated = self._card(listed=[t["name"] for t in TOOLS])
        self.assertTrue(gated["preflight"]["ok"])
        self.assertEqual(gated["preflight"]["missing"], [])
        broken = self._card(listed=None)
        self.assertFalse(broken["preflight"]["ok"])
        self.assertEqual(broken["preflight"]["reason"], "tools-list-failed")


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class CardWire(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "card-w")
        seat(self.root, "claude", "c-card", worktree=str(Path(tempfile.mkdtemp())), resume=RESUME_ID)
        self.join_token = join(self.root, "codex", session_id="x-card", worktree=str(Path(tempfile.mkdtemp())))["token"]
        self.assertTrue(self.join_token)
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.probe = mock.Mock(return_value=dict(NULL_PROBE))
        for target, kw in (("convoy.card.probe", {"new": self.probe}),
                           ("convoy.card.which", {"new": _which("claude", "codex")})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _tools(self):
        return {t["name"]: t for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}

    def _call(self, name, **arguments):
        return _rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments})["result"]

    def test_card_is_a_public_read_tool_declared_with_an_output_schema(self):
        tools = self._tools()
        self.assertIn("card", tools, "card must be listed on a PUBLIC process")
        self.assertNotIn("card", _WRITE_TOOLS)
        self.assertIn("card", REQUIRED_WIZARD_VERBS)
        schema = tools["card"]["outputSchema"]
        self.assertEqual(schema, CARD_OUTPUT_SCHEMA)
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["header"]["const"], "convoy")
        row_keys = set(schema["properties"]["rows"]["items"]["properties"])
        self.assertTrue({"where", "harness", "installed", "usage_remaining", "limited", "models", "effort",
                         "connect_mode", "attach"} <= row_keys, sorted(row_keys))
        self.assertEqual(tools["card"]["inputSchema"]["properties"], {})

    def test_card_answers_through_structured_content_matching_its_schema(self):
        result = self._call("card")
        self.assertFalse(result["isError"])
        card = result["structuredContent"]
        self.assertEqual(json.loads(result["content"][0]["text"]), card)
        self.assertEqual(card["header"], "convoy")
        _require(CARD_OUTPUT_SCHEMA, card)
        self.assertEqual([r["harness"] for r in card["rows"]], _contract_ids())
        rows = {r["harness"]: r for r in card["rows"]}
        self.assertTrue(rows["claude"]["installed"])
        self.assertIsNone(rows["claude"]["usage_remaining"])
        self.assertEqual(card["summary"]["seats"], 2)
        self.assertEqual(card["summary"]["thread"], "card-w")
        self.assertTrue(self.probe.called, "installed harnesses are probed through the seam")
        self.probe.return_value = {"usage_remaining": {"session_pct": 30}, "limited": False, "raw": "x"}
        rows = {r["harness"]: r for r in self._call("card")["structuredContent"]["rows"]}
        self.assertEqual(rows["claude"]["usage_remaining"], {"session_pct": 30})

    def test_a_seeded_resume_id_and_inbox_token_appear_nowhere_in_the_card(self):
        for gate in ("", "1"):
            os.environ["CONVOY_MCP_WRITE_TOOLS"] = gate
            blob = json.dumps(self._call("card")["structuredContent"])
            self.assertNotIn(RESUME_ID, blob, gate)
            self.assertNotIn(self.join_token, blob, gate)
            self.assertNotIn("boot_prompt", blob, gate)
            self.assertNotIn("token", blob.lower(), gate)

    def test_preflight_is_red_on_a_public_server_and_green_behind_the_gate(self):
        public = self._call("card")["structuredContent"]["preflight"]
        self.assertFalse(public["ok"])
        self.assertEqual(public["listed"], sorted(self._tools()))
        self.assertEqual(public["next"], "enable-write-tools-on-deploy")
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"
        gated = self._call("card")["structuredContent"]["preflight"]
        self.assertTrue(gated["ok"], gated)
        self.assertEqual(gated["listed"], sorted(self._tools()))


if __name__ == "__main__":
    unittest.main()
