"""MCP send addresses an existing neuron by its thread-scoped id.

The fixtures are synthetic and cannot reach a vendor harness or the live
Convoy home. A refused address must not leave an inbox or feed row.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_id
from convoy.convoy import bind, list_seats, read_id, seat
from convoy.inbox import pending
from convoy.layer import feed_since
from convoy.mcp_http import TOOLS, call_tool


class McpNeuronSend(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-home-")
        self.addCleanup(home.cleanup)
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name, "CONVOY_MCP_WRITE_TOOLS": "1"})
        env.start()
        self.addCleanup(env.stop)
        alpha = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-alpha-")
        beta = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-beta-")
        self.addCleanup(alpha.cleanup)
        self.addCleanup(beta.cleanup)
        self.alpha = Path(alpha.name)
        self.beta = Path(beta.name)
        bind(self.alpha, "synthetic-alpha")
        bind(self.beta, "synthetic-beta")
        seat(self.alpha, "claude", "chair-alpha", worktree=str(self.alpha), resume="synthetic-resume-alpha")
        seat(self.beta, "claude", "chair-beta", worktree=str(self.beta))
        self.alpha_id = neuron_id(read_id(self.alpha), "chair-alpha")
        self.beta_id = neuron_id(read_id(self.beta), "chair-beta")

    def _synapses(self, root):
        return [row for row in feed_since(root, "1970-01-01T00:00:00Z") if row["kind"] == "synapse"]

    def test_id_queues_the_existing_chair_on_the_selected_thread(self):
        card = call_tool(self.alpha, "send", {"to": self.alpha_id, "body": "synthetic review"})
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["to"], card["session_id"], card["delivery"]),
                         ("claude", "chair-alpha", "queued"))
        self.assertFalse(card["delivered"])
        self.assertEqual(len(pending(self.alpha, "chair-alpha")), 1)
        self.assertEqual(pending(self.alpha, "chair-alpha")[0]["body"], "synthetic review")
        self.assertEqual([row["session_id"] for row in list_seats(self.alpha)], ["chair-alpha"])
        self.assertEqual(self._synapses(self.beta), [])

    def test_id_and_session_address_use_the_same_seat_worktree(self):
        worktree = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-seat-wt-")
        self.addCleanup(worktree.cleanup)
        wt = Path(worktree.name)
        seat(self.alpha, "claude", "chair-split", worktree=str(wt))
        nid = neuron_id(read_id(self.alpha), "chair-split")
        by_session = call_tool(self.alpha, "send", {"to": "chair-split", "body": "by session"})
        by_id = call_tool(self.alpha, "send", {"to": nid, "body": "by id"})
        self.assertTrue(by_session["ok"] and by_id["ok"])
        self.assertEqual(by_session["pointers"]["worktree"], str(wt))
        self.assertEqual(by_id["pointers"]["worktree"], str(wt))
        rows = self._synapses(self.alpha)
        self.assertEqual([row["worktree"] for row in rows], [str(wt), str(wt)])

    def test_foreign_thread_id_is_a_named_refusal_without_a_write(self):
        card = call_tool(self.alpha, "send", {"to": self.beta_id, "body": "wrong thread"})
        self.assertFalse(card["ok"], card)
        self.assertIn("no neuron " + self.beta_id + " on this thread", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])
        self.assertEqual(self._synapses(self.beta), [])
        self.assertEqual(pending(self.alpha, "chair-alpha"), [])
        self.assertEqual(pending(self.beta, "chair-beta"), [])

    def test_unknown_id_never_enters_the_new_session_path(self):
        unknown = "n000000"
        self.assertNotIn(unknown, (self.alpha_id, self.beta_id))
        card = call_tool(self.alpha, "send", {"to": unknown, "body": "wrong id"})
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "no neuron " + unknown + " on this thread")
        self.assertEqual(self._synapses(self.alpha), [])
        self.assertEqual(pending(self.alpha, "chair-alpha"), [])
        self.assertEqual([row["session_id"] for row in list_seats(self.alpha)], ["chair-alpha"])

    def test_typo_is_not_a_new_harness(self):
        card = call_tool(self.alpha, "send", {"to": "synthetic-chair-typo", "body": "wrong chair"})
        self.assertFalse(card["ok"], card)
        self.assertIn("synthetic-chair-typo", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])
        self.assertEqual(pending(self.alpha, "chair-alpha"), [])

    def test_unbound_thread_cannot_route_a_seat_name(self):
        with mock.patch("convoy.mcp_http.read_id", return_value=None):
            card = call_tool(self.alpha, "send", {"to": "chair-alpha", "body": "unbound"})
        self.assertFalse(card["ok"], card)
        self.assertIn("thread", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])

    def test_unbound_root_refuses_a_harness_send_without_a_write(self):
        unbound = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-unbound-")
        self.addCleanup(unbound.cleanup)
        root = Path(unbound.name)
        self.assertIsNone(read_id(root))
        card = call_tool(root, "send", {"to": "claude", "body": "unbound harness"})
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "send requires a bound thread")
        self.assertEqual(self._synapses(root), [])
        self.assertEqual(list_seats(root), [])
        self.assertFalse((root / ".convoy" / "inbox").exists())

    def test_unknown_harness_name_is_intentionally_refused(self):
        card = call_tool(self.alpha, "send", {"to": "gemini", "body": "not contracted"})
        self.assertFalse(card["ok"], card)
        self.assertIn("gemini", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])

    def test_session_id_still_queues_to_its_chair(self):
        card = call_tool(self.alpha, "send", {"to": "chair-alpha", "body": "by chair"})
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["to"], card["session_id"], card["delivery"]),
                         ("claude", "chair-alpha", "queued"))
        self.assertEqual(pending(self.alpha, "chair-alpha")[0]["body"], "by chair")

    def test_padded_session_id_and_neuron_id_still_queue(self):
        for address in (" chair-alpha ", " " + self.alpha_id + " "):
            card = call_tool(self.alpha, "send", {"to": address, "body": "padded"})
            self.assertTrue(card["ok"], card)
            self.assertEqual(card["session_id"], "chair-alpha")
        self.assertEqual(len(pending(self.alpha, "chair-alpha")), 2)

    def test_id_shaped_session_id_wins_over_the_derived_id_pattern(self):
        worktree = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-shaped-wt-")
        self.addCleanup(worktree.cleanup)
        seat(self.alpha, "claude", "n000000", worktree=worktree.name)
        card = call_tool(self.alpha, "send", {"to": "n000000", "body": "exact chair"})
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["session_id"], "n000000")
        self.assertEqual(pending(self.alpha, "n000000")[0]["body"], "exact chair")

    def test_known_harness_keeps_its_existing_seat_refusal(self):
        card = call_tool(self.alpha, "send", {"to": "claude", "body": "by harness"})
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "seat exists; attach and resume session_id")
        self.assertEqual(self._synapses(self.alpha), [])

    def test_harness_name_is_case_insensitive_before_seat_refusal(self):
        card = call_tool(self.alpha, "send", {"to": "CLAUDE", "body": "by harness"})
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["error"], "seat exists; attach and resume session_id")
        self.assertEqual(self._synapses(self.alpha), [])

    def test_matching_id_overrides_are_allowed(self):
        for args in ({"session_id": "chair-alpha"}, {"worktree": str(self.alpha)},
                     {"resume": "synthetic-resume-alpha"}):
            card = call_tool(self.alpha, "send", {"to": self.alpha_id, "body": "agrees", **args})
            self.assertTrue(card["ok"], card)
            self.assertEqual(card["session_id"], "chair-alpha")

    def test_blank_id_overrides_mean_absent(self):
        for key in ("session_id", "worktree", "resume"):
            for blank in ("", "   "):
                card = call_tool(self.alpha, "send", {"to": self.alpha_id, "body": "blank", key: blank})
                self.assertTrue(card["ok"], (key, blank, card))
                self.assertEqual(card["session_id"], "chair-alpha")
                self.assertEqual(card["pointers"]["worktree"], str(self.alpha))
        self.assertEqual(len(pending(self.alpha, "chair-alpha")), 6)

    def test_conflicting_id_overrides_refuse_before_writing(self):
        for args in ({"session_id": "chair-beta"}, {"worktree": str(self.beta)},
                     {"resume": "wrong-resume"}):
            card = call_tool(self.alpha, "send", {"to": self.alpha_id, "body": "conflicts", **args})
            self.assertFalse(card["ok"], card)
            self.assertIn("neuron id", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])
        self.assertEqual(pending(self.alpha, "chair-alpha"), [])

    def test_codex_id_uses_native_queue_when_available(self):
        codex = tempfile.TemporaryDirectory(prefix="convoy-mcp-id-codex-")
        self.addCleanup(codex.cleanup)
        root = Path(codex.name)
        bind(root, "synthetic-codex")
        seat(root, "codex", "chair-codex", worktree=str(root), resume="synthetic-native-id")
        cid = neuron_id(read_id(root), "chair-codex")
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native) as queue:
            card = call_tool(root, "send", {"to": cid, "body": "native proof"})
        queue.assert_called_once()
        self.assertEqual(queue.call_args.args[0], "synthetic-native-id")
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["to"], card["session_id"], card["delivery"], card["path"]),
                         ("codex", "chair-codex", "native-queued", "codex-queue"))
        self.assertFalse(card["delivered"])
        self.assertEqual(pending(root, "chair-codex")[0]["path"], "codex-queue")

    def test_id_cannot_be_redirected_by_a_session_override(self):
        card = call_tool(self.alpha, "send", {"to": self.alpha_id, "body": "wrong chair",
                                             "session_id": "chair-beta"})
        self.assertFalse(card["ok"], card)
        self.assertIn("neuron id", card["error"])
        self.assertEqual(self._synapses(self.alpha), [])
        self.assertEqual(pending(self.alpha, "chair-alpha"), [])

    def test_schema_names_neuron_ids_as_an_address(self):
        schema = next(tool["inputSchema"] for tool in TOOLS if tool["name"] == "send")
        self.assertIn("neuron id", schema["properties"]["to"]["description"].lower())
