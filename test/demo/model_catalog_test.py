"""Per-harness model catalog with evidence discipline (wizard item B,
2026-09-04).

Three guarantees:

1. Every harness row in harness_effort.json carries `models`: a list or null,
   never a remembered name. A list carries a `models_evidence` string quoting
   the local output it came from; a null says "unverified <date>" and why.
2. `choices` and `roster` surface the catalog per harness straight from the
   contract; roster no longer hardcodes null.
3. seat/join/swap refuse a model outside a NON-null catalog naming the
   harness's real list; a null catalog accepts anything (unknown is not a
   refusal). A refused seat writes nothing.

On this box no harness --help enumerates a closed model list (see the
models_evidence strings), so the non-null path is proven against a fixture
contract, never an invented catalog.
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

from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat  # noqa: E402
from convoy.harness_contract import load_harness_contract, model_catalog, validate_model  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import join, swap  # noqa: E402
from convoy.registry import lookup  # noqa: E402
from convoy.mcp_http import make_server  # noqa: E402
from convoy.targeted_launch import launch_choices  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@contextmanager
def _catalog(hid, models, evidence):
    """The real contract with ONE harness's catalog replaced. Patches the
    loader the module's own helpers call, so choices/roster/seat all see it."""
    data = copy.deepcopy(load_harness_contract())
    for row in data["harnesses"]:
        if row["id"] == hid:
            row["models"] = models
            row["models_evidence"] = evidence
    with mock.patch("convoy.harness_contract.load_harness_contract", return_value=data):
        yield data


def _which(*present):
    names = {str(n).lower() for n in present}

    def lookup(name):
        key = str(name).lower()
        return ("C:\\Tools\\" + str(name)) if key in names or key.removesuffix(".exe") in names else None

    return lookup


class ContractCarriesAModelCatalog(unittest.TestCase):
    def test_every_harness_has_models_list_or_null_with_evidence(self):
        data = load_harness_contract()
        self.assertEqual(data["schema_version"], "2026-09-04")
        for row in data["harnesses"]:
            self.assertIn("models", row, row["id"])
            self.assertIn("models_evidence", row, row["id"])
            evidence = row["models_evidence"]
            self.assertIsInstance(evidence, str, row["id"])
            self.assertTrue(evidence.strip(), row["id"])
            models = row["models"]
            if models is None:
                # unverified stays unverified: the string says so and dates it
                self.assertTrue(evidence.startswith("unverified 20"), (row["id"], evidence))
            else:
                self.assertIsInstance(models, list, row["id"])
                self.assertTrue(models, row["id"] + ": an empty list is not a catalog; use null")
                self.assertTrue(all(isinstance(m, str) and m.strip() for m in models), row["id"])
                self.assertFalse(evidence.startswith("unverified"), (row["id"], evidence))

    def test_plugin_copy_is_byte_identical(self):
        bundled = (REPO / "plugin" / "convoy" / "harness_effort.json").read_bytes()
        packaged = (REPO / "src" / "convoy" / "harness_effort.json").read_bytes()
        self.assertEqual(bundled, packaged)
        self.assertIn("models", json.loads(bundled)["harnesses"][0])

    def test_model_catalog_view_is_null_where_unverified_and_the_list_where_listed(self):
        for row in load_harness_contract()["harnesses"]:
            view = model_catalog(row["id"])
            self.assertEqual(view, {"models": row["models"], "evidence": row["models_evidence"]}, row["id"])
        self.assertEqual(model_catalog("not-a-harness"), {"models": None, "evidence": None})
        with _catalog("grok", ["grok-fixture-a", "grok-fixture-b"], "fixture"):
            self.assertEqual(model_catalog("grok.exe")["models"], ["grok-fixture-a", "grok-fixture-b"])


class ChoicesAndRosterEchoTheCatalog(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "catalog-thread")

    def _choices(self):
        return launch_choices(
            self.root, cwd=self.root, env={}, which=_which("grok", "claude"),
            platform_name="nt", git_worktrees=lambda _paths: [],
        )

    def test_choices_carries_models_and_evidence_per_harness(self):
        contract = {h["id"]: h for h in load_harness_contract()["harnesses"]}
        for h in self._choices()["harnesses"]:
            self.assertEqual(h["models"], contract[h["id"]]["models"], h["id"])
            self.assertEqual(h["models_evidence"], contract[h["id"]]["models_evidence"], h["id"])
        with _catalog("claude", ["fixture-1"], "fixture"):
            by_id = {h["id"]: h for h in self._choices()["harnesses"]}
        self.assertEqual(by_id["claude"]["models"], ["fixture-1"])
        self.assertEqual(by_id["claude"]["models_evidence"], "fixture")

    def test_roster_takes_models_from_the_contract_not_a_hardcoded_null(self):
        from convoy.mcp_http import build_roster

        with _catalog("grok", ["grok-fixture"], "fixture"), \
             mock.patch("convoy.mcp_http.shutil.which", return_value=None), \
             mock.patch("convoy.mcp_http.ensure_interactive_path", return_value={"ok": True}):
            card = build_roster(self.root)
        by_id = {a["id"]: a for a in card["agents"]}
        # a catalog is a contract fact, not a liveness fact: absent binary, list still shown
        self.assertEqual(by_id["grok"]["models"], ["grok-fixture"])
        self.assertEqual(by_id["grok"]["models_evidence"], "fixture")
        self.assertIsNone(by_id["cursor-agent"]["models"])
        self.assertTrue(str(by_id["cursor-agent"]["models_evidence"]).startswith("unverified"))
        self.assertEqual(card["contract"]["schema_version"], "2026-09-04")


class SeatValidatesModelAgainstTheCatalog(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)

    def _row(self, sid):
        return [s for s in list_seats(self.root) if s["session_id"] == sid][-1]

    def test_null_catalog_accepts_any_model(self):
        # every real row is null today; the model rides through as declared
        self.assertIsNone(load_harness_contract()["harnesses"][0]["models"])
        row = seat(self.root, "grok", "g1", model="whatever-the-user-typed")
        self.assertEqual(row["model"], "whatever-the-user-typed")
        self.assertIsNone(seat(self.root, "claude", "c1")["model"])
        self.assertEqual(validate_model("hermes", "any/model"), "any/model")
        self.assertIsNone(validate_model("hermes", None))
        self.assertIsNone(validate_model("hermes", "  "))
        # the registry row carries the same normalised value as the seat row:
        # blank is null in both, never "  " in one and null in the other
        blank = seat(self.root, "claude", "c-blank", model="  ")
        self.assertIsNone(blank["model"])
        self.assertIsNone(lookup(self.root, "c-blank")["model"])

    def test_seat_refuses_a_model_outside_a_non_null_catalog_naming_it(self):
        with _catalog("grok", ["grok-fixture-a", "grok-fixture-b"], "fixture"):
            with self.assertRaises(ValueError) as ctx:
                seat(self.root, "grok", "g2", model="grok-invented")
            msg = str(ctx.exception)
            self.assertIn("grok-invented", msg)
            self.assertIn("grok-fixture-a", msg)
            self.assertIn("grok-fixture-b", msg)
            self.assertEqual(list_seats(self.root), [], "a refused seat writes nothing")
            ok = seat(self.root, "grok", "g2", model="grok-fixture-b")
            self.assertEqual(ok["model"], "grok-fixture-b")
            # the catalog is per harness: claude is still null and accepts anything
            self.assertEqual(seat(self.root, "claude", "c2", model="grok-invented")["model"], "grok-invented")

    def test_join_and_swap_validate_for_the_incoming_harness(self):
        with _catalog("codex", ["codex-fixture"], "fixture"):
            with self.assertRaises(ValueError):
                join(self.root, "codex", session_id="x1", worktree=str(self.root), model="nope")
            self.assertEqual(list_seats(self.root), [])
            card = join(self.root, "codex", session_id="x1", worktree=str(self.root), model="codex-fixture")
            self.assertEqual(card["seat"]["model"], "codex-fixture")
            hp = self.root / "h.md"
            hp.write_text("h", encoding="utf-8")
            feed_before = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
            with self.assertRaises(ValueError):
                swap(self.root, "x1", "codex", str(hp), author="x1", model="nope")
            self.assertEqual(self._row("x1")["model"], "codex-fixture")
            # a refused swap is silent: no kind=swap row, no minted token in
            # the feed asserting a swap that never happened
            self.assertEqual(feed_since(self.root, "1970-01-01T00:00:00.000000Z"), feed_before)
            # a model does not follow the chair onto a harness whose catalog
            # lacks it: dropped, not refused (the effort precedent)
            seat(self.root, "claude", "chair-9", model="claude-thing")
            update_seat(self.root, "chair-9", to="codex")
            self.assertIsNone(self._row("chair-9")["model"])
            # and it survives onto a harness with no catalog
            update_seat(self.root, "chair-9", model="codex-fixture")
            update_seat(self.root, "chair-9", to="hermes")
            self.assertEqual(self._row("chair-9")["model"], "codex-fixture")


def _rpc(url, method, params=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


class ModelOverTheMcpWire(unittest.TestCase):
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

    def test_seat_refuses_over_the_wire_and_writes_nothing(self):
        with _catalog("grok", ["grok-fixture"], "fixture"):
            card = self._call("seat", to="grok", session_id="g-wire", model="grok-invented")
            self.assertFalse(card["ok"])
            self.assertIn("grok-fixture", card["error"])
            self.assertEqual(list_seats(self.root), [])
            good = self._call("seat", to="grok", session_id="g-wire", model="grok-fixture")
            self.assertTrue(good["ok"], good)
            self.assertEqual(good["model"], "grok-fixture")

    def test_seat_schema_says_model_is_checked_against_choices(self):
        tools = {t["name"]: t for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}
        for name in ("seat", "join"):
            desc = tools[name]["inputSchema"]["properties"]["model"].get("description", "")
            self.assertIn("choices.harnesses[].models", desc, name)
            self.assertNotIn("enum", tools[name]["inputSchema"]["properties"]["model"])


class WizardSkillTakesModelsFromTheWire(unittest.TestCase):
    def test_wizard_takes_models_from_the_wire_not_the_pack_file(self):
        # The artifact under test IS the prose. Intent is unchanged since this
        # test was written: the model source must be the WIRE, never a file on
        # disk. Only the wire verb moved - `choices` became `card`, whose rows
        # carry models/effort/usage per harness (item F, 2026-09-04) - so the
        # test names the source generically instead of one tool.
        text = (REPO / "plugin" / "convoy" / "skills" / "convoy-wizard" / "SKILL.md").read_text(encoding="utf-8")
        seq = text[text.index("## Mandatory wizard sequence"):]
        body = " ".join(seq.split())          # the prose wraps; match on claims, not layout
        self.assertIn("rows[].models", body, "the sequence must name the wire row as the model source")
        self.assertIn("card", body)
        self.assertNotIn("Read model/effort constraints from the bundled", body)
        # And no step may send the host to a file: a remote grok-bot has no
        # filesystem, so a read instruction there is unrunnable, not merely wrong.
        for path in ("../../harness_effort.json", "src/convoy/harness_effort.json"):
            self.assertNotIn("Read `" + path + "`", body)
            self.assertNotIn("read " + path, body.lower())


if __name__ == "__main__":
    unittest.main()
