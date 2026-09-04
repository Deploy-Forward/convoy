"""Wire coverage for verbs that were CLI-only until PR 50 (grok-bot review,
2026-09-04 ~06:00Z): choices, join, launch, seat, neurons, inbox.

Current Gate 0 is convoy.wizard_preflight.REQUIRED_WIZARD_VERBS and is scored
by wizard_preflight / the wizard sequence test. This module still pins that
those original mutating verbs stay hidden on a public process, that a gated
process lists both them and the current Gate 0 set, and that a refusal never
pretends to have acted.

Three guarantees, and the shape they must keep:

1. The original ten plus current Gate 0 appear in tools/list on a gated server.
2. Read-only verbs (choices, neurons, inbox without drain) answer on a public
   process. Mutating verbs (seat, join, inbox drain) and the one that SPAWNS
   (launch) sit behind the same write gate resume go=true already uses, so a
   public endpoint can never mint a chair or start a process on a stranger's
   behalf. A refused call names the gate and never pretends to have acted.
3. Nothing here prints a vendor token. The seat card echoes what it was
   given; a caller's resume string is its own business, and no tool invents
   one.
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

from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.inbox import enqueue, pending
from convoy.mcp_http import TOOLS, _WRITE_TOOLS, make_server
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS

GATE0 = ("choices", "onboard", "join", "launch", "seat", "bring_up",
         "neurons", "graph", "send", "inbox")


def _rpc(url, method, params=None, rpc_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _gated(card):
    """A refusal is honest at either layer. The RPC layer hides and refuses
    the whole tool ("write tool disabled"); the handler refuses one mode of a
    listed tool ("behind the write gate", e.g. inbox drain). Both name the
    env var that opens the gate. Neither pretends to have acted."""
    err = str(card.get("error") or "")
    return ("write tool disabled" in err or "write gate" in err) and "CONVOY_MCP_WRITE_TOOLS" in err


def _payload(resp):
    result = resp["result"]
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    if isinstance(result, dict) and result.get("content"):
        return json.loads(result["content"][0]["text"])
    return result


class McpWizardVerbs(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "wiz")
        seat(self.root, "claude", "c-wiz", worktree=str(self.wt), model="claude-fable-5")
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.mcp = "http://127.0.0.1:%s/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        # Every test starts on a PUBLIC process: the gate is closed.
        self._env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _call(self, name, **arguments):
        return _payload(_rpc(self.mcp, "tools/call", {"name": name, "arguments": arguments}))

    def _open_gate(self):
        os.environ["CONVOY_MCP_WRITE_TOOLS"] = "1"

    # 1. the dependency set is registered, not merely documented - and the
    #    wire tells the truth about WHERE it is available.
    def test_all_ten_gate0_verbs_are_listed_behind_the_gate(self):
        self._open_gate()
        names = {t["name"] for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}
        missing = [v for v in GATE0 if v not in names]
        self.assertEqual(missing, [], "PR50 Gate 0 verbs absent from tools/list: " + repr(missing))
        still = [v for v in REQUIRED_WIZARD_VERBS if v not in names]
        self.assertEqual(still, [], "current Gate 0 verbs absent from gated tools/list: " + repr(still))

    def test_public_tools_list_hides_seat_join_launch_so_gate0_goes_red_honestly(self):
        # A public endpoint cannot seat or launch. It must not LIST them and
        # then refuse: the wizard reads tools/list to decide, and a listed verb
        # is a promise. Hidden here means Gate 0 is RED on a public deploy by
        # design, and the wizard stops with an install card. The read-only
        # verbs stay listed everywhere.
        # Derived from _WRITE_TOOLS so clone/crew/consent/await_seated cannot
        # leak the way a frozen ("seat","join","launch") tuple did.
        names = {t["name"] for t in _rpc(self.mcp, "tools/list")["result"]["tools"]}
        expected = {t["name"] for t in TOOLS if t["name"] not in _WRITE_TOOLS}
        self.assertEqual(names, expected)

    # 2a. read-only verbs answer on a public process
    def test_choices_is_read_only_and_answers_public(self):
        card = self._call("choices")
        self.assertIn("ok", card)
        self.assertNotIn("error", {k for k, v in card.items() if v and k == "error"})

    def test_neurons_is_read_only_and_never_a_token(self):
        card = self._call("neurons")
        self.assertTrue(card.get("ok"), card)
        self.assertEqual(card.get("thread"), "wiz")
        chairs = {n["session_id"] for n in card["neurons"]}
        self.assertIn("c-wiz", chairs)
        self.assertNotIn("token", json.dumps(card).lower())

    def test_inbox_read_is_public_but_drain_is_gated(self):
        enqueue(self.root, "c-wiz", "hello from the wire", to="claude", label="t")
        peek = self._call("inbox", seat="c-wiz")
        self.assertTrue(peek.get("ok"), peek)
        self.assertEqual(peek.get("pending_count"), 1)
        self.assertFalse(peek.get("drained"))
        # A drain on a public process is REFUSED, and the row is still pending.
        refused = self._call("inbox", seat="c-wiz", drain=True)
        self.assertFalse(refused.get("ok"))
        self.assertIn("write gate", refused.get("error", ""))
        self.assertEqual(len(pending(self.root, "c-wiz")), 1)
        self._open_gate()
        drained = self._call("inbox", seat="c-wiz", drain=True)
        self.assertTrue(drained.get("ok"), drained)
        self.assertTrue(drained.get("drained"))
        self.assertEqual(len(pending(self.root, "c-wiz")), 0)

    def test_public_inbox_read_never_echoes_the_token(self):
        # Caught live before shipping (2026-09-04): pending() rows carry the
        # token, and a public read that returned them verbatim would have let
        # any caller forge the receiver's ack. The body is fine to show; the
        # token is not.
        enqueue(self.root, "c-wiz", "visible body", to="claude", label="t")
        peek = self._call("inbox", seat="c-wiz")
        self.assertEqual(peek["pending_count"], 1)
        self.assertEqual(peek["pending"][0]["body"], "visible body")
        self.assertNotIn("token", peek["pending"][0])
        self.assertNotIn("token", json.dumps(peek).lower())

    def test_inbox_requires_seat_rather_than_guessing(self):
        card = self._call("inbox")
        self.assertFalse(card.get("ok"))
        self.assertIn("seat", card.get("error", ""))

    # 2b. mutating verbs are gated and a refusal never claims to have acted
    def test_seat_and_join_are_gated_on_a_public_process(self):
        before = len(list_seats(self.root))
        for name, args in (("seat", {"to": "codex", "session_id": "x-wiz", "worktree": str(Path(tempfile.mkdtemp()))}),
                           ("join", {"to": "grok", "session_id": "j-wiz", "worktree": str(Path(tempfile.mkdtemp()))})):
            card = self._call(name, **args)
            self.assertFalse(card.get("ok"), (name, card))
            self.assertTrue(_gated(card), card)
            self.assertNotIn("seat", {k for k, v in card.items() if isinstance(v, dict)}, name + " must not return a seat card when refused")
        self.assertEqual(len(list_seats(self.root)), before, "a refused seat/join must not touch seats.jsonl")

    def test_seat_and_join_work_behind_the_gate_and_refuse_c8(self):
        self._open_gate()
        wt2 = str(Path(tempfile.mkdtemp()))
        seated = self._call("seat", to="codex", session_id="x-wiz", worktree=wt2, model="gpt-5.6-sol")
        self.assertTrue(seated.get("ok"), seated)
        self.assertEqual(seated.get("session_id"), "x-wiz")
        joined = self._call("join", to="grok", session_id="j-wiz", worktree=str(Path(tempfile.mkdtemp())))
        self.assertTrue(joined.get("ok"), joined)
        self.assertEqual(joined["seat"]["session_id"], "j-wiz")
        # C8: a worktree belongs to one chair. The refusal names both chairs.
        clash = self._call("seat", to="claude", session_id="y-wiz", worktree=wt2)
        self.assertFalse(clash.get("ok"))
        self.assertIn("x-wiz", clash.get("error", ""))
        self.assertIn("y-wiz", clash.get("error", ""))

    def test_seat_requires_to_and_session_id(self):
        # The tool must be FOUND and refuse on its own terms - "tool not found"
        # is also ok=False and would have let this pass before the verb existed.
        self._open_gate()
        for args in ({"session_id": "only"}, {"to": "claude"}):
            card = self._call("seat", **args)
            self.assertFalse(card.get("ok"))
            self.assertIn("requires to and session_id", card.get("error", ""))
            self.assertNotIn("tool not found", card.get("error", ""))

    # 2c. launch SPAWNS, so it is gated hardest and never spawns when refused
    def test_launch_is_gated_and_spawns_nothing_when_refused(self):
        with mock.patch("convoy.mcp_http.launch_seat") as spawn:
            card = self._call("launch", seat="c-wiz")
        self.assertFalse(card.get("ok"))
        self.assertTrue(_gated(card), card)
        self.assertIn("spawned", card)
        self.assertFalse(card.get("spawned"))
        spawn.assert_not_called()

    def test_launch_behind_the_gate_calls_launch_seat_with_consent(self):
        self._open_gate()
        with mock.patch("convoy.mcp_http.launch_seat", return_value={"ok": True, "state": "launched"}) as spawn:
            card = self._call("launch", seat="c-wiz", consent="yes")
        self.assertTrue(card.get("ok"), card)
        spawn.assert_called_once()
        kwargs = spawn.call_args.kwargs
        self.assertEqual(spawn.call_args.args[1], "c-wiz")
        self.assertEqual(kwargs.get("consent"), "yes")

    def test_launch_requires_seat(self):
        self._open_gate()
        card = self._call("launch")
        self.assertFalse(card.get("ok"))
        self.assertIn("seat", card.get("error", ""))


if __name__ == "__main__":
    unittest.main()
