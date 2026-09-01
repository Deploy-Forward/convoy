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

    def test_conductor_stamp_from_stays_grok_bot(self):
        row = conductor_stamp(self.root, "decision", instance_id="a487bca8-agent-id")
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


class ServerBuildId(unittest.TestCase):
    """Deploy drift must be detectable in one call: serverInfo.version carries
    the commit sha when the package sits in a git checkout."""

    def test_initialize_version_carries_commit_sha(self):
        pkg_dir = Path(__file__).resolve().parents[2]
        sha = subprocess.run(
            ["git", "-C", str(pkg_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        self.assertTrue(sha, "test requires a git checkout")
        resp = handle_rpc(Path(tempfile.mkdtemp()), {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        version = resp["result"]["serverInfo"]["version"]
        self.assertEqual(version, "0.1.0+" + sha)


if __name__ == "__main__":
    unittest.main()
