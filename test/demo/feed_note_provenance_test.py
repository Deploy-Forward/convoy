import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.layer import SCHEMA_VERSION, conductor_stamp, feed_since, hook, neuron_note
from convoy.cli import main
from convoy.mcp_http import TOOLS, call_tool, handle_rpc
from convoy.synapse import fake_runner, native_runner, ola_runner, send_one


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class FeedAddresseeAndHonestFrom(unittest.TestCase):
    """v2.1 additive: rows carry an addressee `to` and an honest author `from`.
    `grok-bot` is a reserved addressee, never an author — conductor lines are
    stamp-only. Anything else is impersonation on the bus."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_hook_writes_to_and_from(self):
        row = hook(self.root, "note", "ping opus-1", instance_id="fable-fable-opus", to="opus-1-fable-opus")
        self.assertEqual(row["from"], "fable-fable-opus")
        self.assertEqual(row["to"], "opus-1-fable-opus")
        disk = feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(disk["from"], "fable-fable-opus")
        self.assertEqual(disk["to"], "opus-1-fable-opus")

    def test_hook_without_to_or_author_stays_v1_shape(self):
        row = hook(self.root, "note", "v1 row, no extras")
        self.assertNotIn("to", row)
        self.assertNotIn("from", row)

    def test_hook_refuses_grok_bot_author(self):
        with self.assertRaises(ValueError):
            hook(self.root, "note", "forged", instance_id="grok-bot")

    def test_hook_refuses_grok_bot_author_aliases(self):
        for alias in ("Grok-Bot", "GROK-BOT", "grok_bot", "grokbot", " grok-bot "):
            with self.assertRaises(ValueError, msg=alias):
                hook(self.root, "note", "forged", instance_id=alias)

    def test_mcp_note_refuses_grok_bot_alias(self):
        from convoy.mcp_http import call_tool

        card = call_tool(self.root, "note", {"summary": "forged", "instance_id": "Grok-Bot"})
        self.assertFalse(card["ok"])

    def test_conductor_stamp_from_stays_grok_bot(self):
        row = conductor_stamp(self.root, "decision", instance_id="conductor-agent-id")
        self.assertEqual(row["from"], "grok-bot")

    def test_grok_bot_is_a_valid_addressee(self):
        row = hook(self.root, "note", "to the chair", instance_id="fable-fable-opus", to="grok-bot")
        self.assertEqual(row["to"], "grok-bot")

    def test_cli_hook_to_flag(self):
        rc, row = _run_cli(self.root, "hook", "note", "cli addressed", "--instance-id", "fable-fable-opus", "--to", "grok-bot")
        self.assertEqual(rc, 0)
        self.assertEqual(row["to"], "grok-bot")
        self.assertEqual(row["from"], "fable-fable-opus")

    def test_cli_hook_refuses_grok_bot_author_gracefully(self):
        rc, card = _run_cli(self.root, "hook", "note", "forged", "--instance-id", "grok-bot")
        self.assertEqual(rc, 1)
        self.assertFalse(card["ok"])
        self.assertIn("grok-bot", str(card["error"]))


class SynapseAuthorNotRecipient(unittest.TestCase):
    """OPUS-2 verified defect: synapse rows carried the RECIPIENT in `from`
    (hook promoted instance_id — the spawned/target session — to author).
    `from` is authorship: absent-when-unknown beats a recorded lie."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _last_row(self):
        return feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]

    def test_synapse_row_does_not_claim_target_as_author(self):
        card = send_one(self.root, "grok", "hi")
        self.assertTrue(card["ok"])
        row = self._last_row()
        self.assertEqual(row["kind"], "synapse")
        self.assertEqual(row["instance_id"], "spawned-grok")
        self.assertNotIn("from", row)

    def test_refuse_row_does_not_claim_target_as_author(self):
        def probe(_to):
            return {"usage_remaining": None, "limited": True, "raw": "session 100%"}

        card = send_one(self.root, "claude", "hi", probe_fn=probe)
        self.assertTrue(card.get("refused"))
        row = self._last_row()
        self.assertEqual(row["kind"], "refuse")
        self.assertNotIn("from", row)

    def test_note_rows_keep_author_from_instance_id(self):
        row = hook(self.root, "note", "authored", instance_id="fable-fable-opus")
        self.assertEqual(row["from"], "fable-fable-opus")

    def test_send_to_conductor_alias_named_subject_still_stamps(self):
        # The authorship refusal must not apply to the row SUBJECT: a send
        # targeting a seat unluckily named like the conductor must complete
        # and stamp — never raise post-runner leaving a hop with zero rows.
        from convoy.registry import register

        register(self.root, "Grok-Bot", "claude")
        card = send_one(self.root, "claude", "ping", instance_id="Grok-Bot")
        self.assertTrue(card["ok"])
        row = self._last_row()
        self.assertEqual(row["kind"], "synapse")
        self.assertEqual(row["instance_id"], "Grok-Bot")
        self.assertNotIn("from", row)


class NeuronNoteAndMcpTool(unittest.TestCase):
    """MCP `note`: the neuron-side write, symmetric to `stamp` but with an
    honest `from` (the writing seat), one compact clamped line, never grok-bot."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_neuron_note_writes_compact_row(self):
        row = neuron_note(self.root, "line one\nline two " + "x" * 5000, instance_id="opus-2-fable-opus", to="grok-bot")
        self.assertEqual(row["kind"], "note")
        self.assertEqual(row["from"], "opus-2-fable-opus")
        self.assertEqual(row["to"], "grok-bot")
        self.assertNotIn("\n", row["summary"])
        self.assertLessEqual(len(row["summary"]), 500)
        self.assertIs(row["truncated"], True)

    def test_neuron_note_requires_author(self):
        with self.assertRaises(ValueError):
            neuron_note(self.root, "anonymous", instance_id=None)
        with self.assertRaises(ValueError):
            neuron_note(self.root, "forged", instance_id="grok-bot")
        with self.assertRaises(ValueError):
            neuron_note(self.root, "   ", instance_id="opus-2-fable-opus")

    def test_mcp_note_tool_listed_and_writes_row(self):
        names = [t["name"] for t in TOOLS]
        self.assertIn("note", names)
        spec = next(t for t in TOOLS if t["name"] == "note")
        self.assertIn("instance_id", spec["inputSchema"].get("required", []))
        card = call_tool(self.root, "note", {"summary": "hosted neuron says hi", "instance_id": "fable-fable-opus", "to": "grok-bot"})
        self.assertTrue(card["ok"])
        self.assertEqual(card["schema_version"], SCHEMA_VERSION)
        self.assertEqual(card["from"], "fable-fable-opus")
        payload = call_tool(self.root, "feed", {"since": "1970-01-01T00:00:00.000000Z"})
        self.assertEqual(payload["events"][-1]["kind"], "note")
        self.assertEqual(payload["events"][-1]["to"], "grok-bot")

    def test_mcp_note_refuses_grok_bot_and_blank(self):
        card = call_tool(self.root, "note", {"summary": "forged", "instance_id": "grok-bot"})
        self.assertFalse(card["ok"])
        self.assertIn("grok-bot", str(card["error"]))
        card = call_tool(self.root, "note", {"summary": "  ", "instance_id": "fable-fable-opus"})
        self.assertFalse(card["ok"])
        card = call_tool(self.root, "note", {"summary": "no author"})
        self.assertFalse(card["ok"])


class SynapseRunnerProvenance(unittest.TestCase):
    """The SoT must distinguish a native vendor send from a fake ACK: every
    synapse row records which runner ran and argv[0] when the card carries one."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _last_row(self):
        return feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]

    def test_fake_runner_row_says_fake(self):
        card = send_one(self.root, "grok", "hi")
        self.assertTrue(card["ok"])
        row = self._last_row()
        self.assertEqual(row["kind"], "synapse")
        self.assertEqual(row["runner"], "fake")
        self.assertIsNone(row["argv0"])

    def test_custom_runner_records_name_and_argv0(self):
        def probe(_to):
            return {"usage_remaining": None, "limited": False, "raw": None}

        def custom_runner(to, body, **kw):
            return {"ok": True, "to": to, "session_id": "sess-x", "argv": ["/usr/bin/grok", "--flag"]}

        send_one(self.root, "grok", "hi", runner=custom_runner, probe_fn=probe)
        row = self._last_row()
        self.assertEqual(row["runner"], "custom_runner")
        self.assertEqual(row["argv0"], "/usr/bin/grok")

    def test_runner_kind_mapping_is_identity_based(self):
        from convoy.synapse import runner_kind

        self.assertEqual(runner_kind(native_runner), "native")
        self.assertEqual(runner_kind(fake_runner), "fake")
        self.assertEqual(runner_kind(ola_runner), "ola")


class ChipSeatFields(unittest.TestCase):
    """Conductor chip contract: harness/model/effort/session%/vendor-id/
    worktree renderable from feed + glance reads, no jsonl archaeology.
    effort is stored on the seat row (real-or-null; since 2026-09-04 it is
    validated per harness and applied to argv only where harness_effort.json
    evidences a flag, see effort_contract_test); glance by-thread seat cards
    surface effort and resume."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _glance_seat(self):
        from convoy.glance import build_by_thread

        def fake_probe(_h):
            return {"usage_remaining": None, "limited": False, "raw": None}

        card = build_by_thread(self.root, probe_fn=fake_probe, which_fn=lambda _n: None)
        return card["seats"][0]

    def test_seat_stores_effort_and_glance_surfaces_chip_fields(self):
        from convoy.convoy import ensure_id, seat

        ensure_id(self.root)
        seat(
            self.root,
            "claude",
            "fable-seat",
            worktree=r"C:\wt\fable",
            model="claude-fable-5",
            resume="00000000-0000-4000-8000-000000000001",
            effort="high",
        )
        row = self._glance_seat()
        self.assertEqual(row["model"], "claude-fable-5")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["resume"], "00000000-0000-4000-8000-000000000001")
        self.assertEqual(row["worktree"], r"C:\wt\fable")

    def test_unknown_effort_and_resume_stay_off_the_card(self):
        from convoy.convoy import ensure_id, seat

        ensure_id(self.root)
        seat(self.root, "claude", "bare-seat")
        row = self._glance_seat()
        self.assertNotIn("effort", row)
        self.assertNotIn("resume", row)

    def test_cli_seat_effort_flag(self):
        _run_cli(self.root, "init")
        rc, card = _run_cli(
            self.root, "seat", "--to", "claude", "--session-id", "s1", "--effort", "high"
        )
        self.assertEqual(rc, 0)
        self.assertEqual(card["effort"], "high")


class PublicWriteToolGate(unittest.TestCase):
    """N-5: the public wire must not expose SoT write tools ungated. Default
    OFF at the RPC layer only — CLI and in-process call_tool stay usable, so a
    gated/loopback deploy opts in with CONVOY_MCP_WRITE_TOOLS=1."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _rpc(self, method, params):
        return handle_rpc(self.root, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    def test_write_tools_hidden_from_public_tools_list(self):
        names = [t["name"] for t in self._rpc("tools/list", {})["result"]["tools"]]
        self.assertNotIn("stamp", names)
        self.assertNotIn("note", names)
        self.assertIn("feed", names)
        self.assertIn("roster", names)

    def test_write_tools_refused_over_rpc_by_default(self):
        resp = self._rpc("tools/call", {"name": "stamp", "arguments": {"summary": "gated"}})
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("disabled", resp["result"]["structuredContent"]["error"])
        resp = self._rpc("tools/call", {"name": "note", "arguments": {"summary": "gated", "instance_id": "seat-x"}})
        self.assertTrue(resp["result"]["isError"])
        self.assertEqual(feed_since(self.root, "1970-01-01T00:00:00.000000Z"), [])

    def test_env_flag_enables_write_tools(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"}):
            names = [t["name"] for t in self._rpc("tools/list", {})["result"]["tools"]]
            self.assertIn("stamp", names)
            self.assertIn("note", names)
            resp = self._rpc("tools/call", {"name": "note", "arguments": {"summary": "gated open", "instance_id": "seat-x", "to": "grok-bot"}})
            self.assertFalse(resp["result"]["isError"])
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(rows[-1]["kind"], "note")

    def test_in_process_call_tool_is_not_gated(self):
        card = call_tool(self.root, "stamp", {"summary": "in-process conductor line"})
        self.assertTrue(card["ok"])


class ServerBuildId(unittest.TestCase):
    """Deploy drift must be detectable in one call: serverInfo.version carries
    the commit sha when the package sits in a git checkout."""

    def test_initialize_version_carries_commit_sha(self):
        pkg_dir = Path(__file__).resolve().parents[2]
        build = subprocess.run(
            ["git", "-C", str(pkg_dir), "describe", "--always", "--dirty"],
            capture_output=True, text=True,
        ).stdout.strip()
        if not build:
            # A packaged/exported tree (git archive) has no .git — exactly the
            # deploy shape where the build stamp is legitimately absent (N-4).
            # Skip keeps the suite signal honest there instead of a false RED.
            self.skipTest("no git checkout: build stamp legitimately absent")
        resp = handle_rpc(Path(tempfile.mkdtemp()), {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        version = resp["result"]["serverInfo"]["version"]
        self.assertEqual(version, "0.1.0+" + build)

    def test_server_version_survives_git_timeout(self):
        from unittest import mock

        from convoy import mcp_http

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        with mock.patch.object(mcp_http.subprocess, "run", boom):
            self.assertEqual(mcp_http._server_version(), "0.1.0")

    def test_server_version_marks_dirty_checkout(self):
        from convoy.mcp_http import _server_version

        repo = Path(tempfile.mkdtemp())
        for argv in (
            ["git", "-C", str(repo), "init", "-q"],
            ["git", "-C", str(repo), "config", "user.email", "t@t"],
            ["git", "-C", str(repo), "config", "user.name", "t"],
            ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "seed"],
        ):
            self.assertEqual(subprocess.run(argv, capture_output=True).returncode, 0)
        clean = _server_version(repo_dir=repo)
        self.assertTrue(clean.startswith("0.1.0+"))
        self.assertFalse(clean.endswith("-dirty"))
        (repo / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "f.txt"], capture_output=True)
        self.assertTrue(_server_version(repo_dir=repo).endswith("-dirty"))


if __name__ == "__main__":
    unittest.main()
