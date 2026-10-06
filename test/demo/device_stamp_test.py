"""Device provenance comes from Convoy's paired machine and caller proof.

All devices, chairs, origins and tokens here are synthetic. No credential is
opened and no vendor process or network connection is started.
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

from convoy.cli import main
from convoy.conductor import replies
from convoy.convoy import bind, seat
from convoy.layer import conductor_stamp, feed_since, hook
from convoy.mcp_http import call_tool
from convoy.origin_loop import _deliver_via_synapse
from convoy.synapse import send_one


class PairedDeviceStampContract(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        (self.home / "origin.json").write_text(json.dumps({
            "origin_id": "o_synthetic_origin",
            "org_id": "synthetic-org",
            "user_id": "synthetic-user",
            "machine_id": "synthetic-device-a",
            "api_base": "https://example.invalid",
            "credential_path": str(self.home / "unused-credential"),
        }), encoding="utf-8")
        self.root = Path(tempfile.mkdtemp())
        bind(self.root, "stamp-contract")
        seat(self.root, "codex", "chair-a", worktree=str(self.root))
        seat(self.root, "claude", "chair-b", worktree=str(Path(tempfile.mkdtemp())))

    def _cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def _rows(self):
        return feed_since(self.root, "1970-01-01T00:00:00Z")

    def test_verified_note_and_token_ack_carry_server_added_device_and_method(self):
        for via in ("environment", "token", "pane-host"):
            with self.subTest(via=via):
                proof = {"ok": True, "chair": "chair-a", "via": via, "harness": "codex"}
                with mock.patch("convoy.cli.identify", return_value=proof):
                    rc, note = self._cli("hook", "note", "started-" + via, "--as-me", "--to", "chair-b")
                    rc_ack, ack = self._cli("hook", "note", "ACK synthetic-token-" + via,
                                            "--as-me", "--to", "grok-bot")
                self.assertEqual((rc, rc_ack), (0, 0))
                for row in (note, ack):
                    self.assertEqual(row["from"], "chair-a")
                    self.assertEqual(row["device"], "synthetic-device-a")
                    self.assertEqual(row["verified_by"], via)
        self.assertEqual(len([r for r in self._rows() if r["kind"] == "note"]), 6)

    def test_send_row_has_paired_device_without_inventing_a_sender_proof(self):
        card = send_one(self.root, "chair-b", "synthetic review")
        self.assertTrue(card["ok"])
        row = [r for r in self._rows() if r["kind"] == "synapse"][-1]
        self.assertEqual(row["device"], "synthetic-device-a")
        self.assertIsNone(row["verified_by"])
        self.assertNotIn("from", row, "a send without proven caller must not borrow the recipient's identity")

    def test_claiming_another_chair_refuses_before_writing(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof):
            code, result = self._cli("hook", "note", "forged", "--instance-id", "chair-b")
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertEqual([r for r in self._rows() if r["kind"] == "note"], [])

    def test_caller_supplied_stamp_fields_cannot_override_machine_evidence(self):
        row = hook(self.root, "synapse", "synthetic send", instance_id="chair-b", author=None,
                   extra={"device": "spoofed-device", "verified_by": "token",
                          "from": "chair-b", "kind": "note", "ts": "false-time",
                          "instance_id": "chair-a", "to": "chair-a"})
        self.assertEqual(row["device"], "synthetic-device-a")
        self.assertIsNone(row["verified_by"])
        self.assertNotIn("from", row)
        self.assertEqual(row["kind"], "synapse")
        self.assertEqual(row["instance_id"], "chair-b")
        self.assertNotEqual(row["ts"], "false-time")
        self.assertNotIn("to", row)

    def test_unpaired_device_stays_unknown(self):
        (self.home / "origin.json").unlink()
        row = hook(self.root, "synapse", "synthetic send", instance_id="chair-b", author=None)
        self.assertIsNone(row["device"])
        self.assertIsNone(row["verified_by"])

        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof):
            code, note = self._cli("hook", "note", "synthetic note", "--as-me")
        self.assertEqual(code, 0)
        self.assertIsNone(note["device"])
        self.assertEqual(note["verified_by"], "environment")

    def test_seated_ack_stamps_matching_body_and_refuses_another_chair(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof):
            code, ack = self._cli("seated", "--seat", "chair-a", "--token", "synthetic-life")
            bad_code, bad = self._cli("seated", "--seat", "chair-b", "--token", "synthetic-life")
        self.assertEqual(code, 0)
        self.assertEqual(ack["row"]["device"], "synthetic-device-a")
        self.assertEqual(ack["row"]["verified_by"], "environment")
        self.assertNotEqual(bad_code, 0)
        self.assertFalse(bad["ok"])
        self.assertEqual([r["instance_id"] for r in self._rows() if r["kind"] == "seated"], ["chair-a"])

    def test_mcp_claimed_author_never_inherits_server_device_or_proof(self):
        card = call_tool(self.root, "note", {"summary": "synthetic hosted note", "instance_id": "chair-b", "to": "grok-bot"})
        self.assertTrue(card["ok"])
        self.assertEqual(card["from"], "chair-b")
        self.assertTrue(card["author_claimed"])
        self.assertIsNone(card["device"])
        self.assertIsNone(card["verified_by"])
        row = [r for r in self._rows() if r["kind"] == "note"][-1]
        self.assertTrue(row["author_claimed"])
        self.assertIsNone(row["device"])
        self.assertIsNone(replies(self.root, "grok-bot")["rows"][-1]["verified_by"])
        neuron = next(n for n in call_tool(self.root, "neurons", {})["neurons"] if n["session_id"] == "chair-b")
        self.assertIsNone(neuron["verified_by"])
        self.assertTrue(neuron["author_claimed"])

    def test_mcp_seated_row_does_not_borrow_server_device(self):
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"}):
            card = call_tool(self.root, "seated", {"seat": "chair-a", "token": "synthetic-life"})
        self.assertTrue(card["ok"])
        row = [r for r in self._rows() if r["kind"] == "seated"][-1]
        self.assertEqual(row["from"], "chair-a")
        self.assertTrue(row["author_claimed"])
        self.assertIsNone(row["device"])
        self.assertIsNone(row["verified_by"])

    def test_mcp_send_row_does_not_borrow_server_device(self):
        card = call_tool(self.root, "send", {"to": "chair-b", "body": "synthetic remote send"})
        self.assertTrue(card["ok"])
        row = [r for r in self._rows() if r["kind"] == "synapse"][-1]
        self.assertEqual(row["to"], "claude")
        self.assertIsNone(row["device"])
        self.assertIsNone(row["verified_by"])

    def test_worklanes_origin_brief_does_not_borrow_local_device(self):
        origin_root = Path(tempfile.mkdtemp())
        bind(origin_root, "synthetic-origin-thread")
        # The brief goes to the link harness's one seated chair (never a spawned stand-in).
        seat(origin_root, "codex", "synthetic-origin-chair", worktree=str(Path(tempfile.mkdtemp())))
        link = {"id": "synthetic-origin-link", "originId": "o_synthetic_origin",
                "harness": "codex"}
        card = _deliver_via_synapse(root=origin_root, link=link, body="synthetic board brief")
        self.assertTrue(card["ok"])
        row = [r for r in feed_since(origin_root, "1970-01-01T00:00:00Z")
               if r["kind"] == "synapse"][-1]
        self.assertEqual(row["label"], "worklanes")
        self.assertIsNone(row["device"])
        self.assertIsNone(row["verified_by"])

    def test_conductor_stamp_still_refuses_conductor_alias_as_subject(self):
        with self.assertRaises(ValueError):
            conductor_stamp(self.root, "synthetic decision", instance_id="grok-bot")
        self.assertEqual([r for r in self._rows() if r["kind"] == "conductor"], [])

    def test_cli_explicit_author_without_proof_is_only_a_claim(self):
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": None}):
            code, row = self._cli("hook", "note", "synthetic claim", "--instance-id", "chair-a")
        self.assertEqual(code, 0)
        self.assertTrue(row["author_claimed"])
        self.assertEqual(row["device"], "synthetic-device-a")
        self.assertIsNone(row["verified_by"])

    def test_generic_stamped_hook_refuses_a_proven_chair_conflict(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof):
            for kind in ("seated", "synapse"):
                with self.subTest(kind=kind):
                    code, card = self._cli("hook", kind, "forged", "--instance-id", "chair-b")
                    self.assertNotEqual(code, 0)
                    self.assertFalse(card["ok"])
        self.assertEqual([r for r in self._rows() if r["kind"] in ("seated", "synapse")], [])

    def test_local_stamped_claim_and_worktree_proof_are_distinct(self):
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": None}):
            code, claim = self._cli("hook", "seated", "synthetic life", "--instance-id", "chair-a")
        self.assertEqual(code, 0)
        self.assertEqual(claim["device"], "synthetic-device-a")
        self.assertTrue(claim["author_claimed"])
        self.assertIsNone(claim["verified_by"])

        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": "chair-a", "via": "worktree"}):
            code, proven = self._cli("hook", "note", "synthetic worktree", "--as-me")
        self.assertEqual(code, 0)
        self.assertEqual(proven["verified_by"], "worktree")
        self.assertNotIn("author_claimed", proven)

        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": "chair-a", "via": "cwd"}):
            code, weak = self._cli("hook", "note", "synthetic cwd", "--as-me")
        self.assertEqual(code, 0)
        self.assertIsNone(weak["verified_by"])
        self.assertTrue(weak["author_claimed"])

    def test_neurons_uses_latest_stamped_row_not_later_unstamped_activity(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof):
            code, note = self._cli("hook", "note", "synthetic note", "--as-me")
        self.assertEqual(code, 0)
        hook(self.root, "usage", "synthetic usage", instance_id="chair-a", author="chair-a")
        neuron = next(n for n in call_tool(self.root, "neurons", {})["neurons"] if n["session_id"] == "chair-a")
        self.assertEqual(neuron["verified_by"], "environment")
        self.assertEqual(neuron["device"], "synthetic-device-a")
        self.assertEqual(neuron["last_said"], "synthetic usage")
