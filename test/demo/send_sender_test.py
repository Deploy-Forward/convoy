"""A send records its sender only when the sender is proven.

A synapse row's `from` is the sender, and it is written only with proof:

  a CLI send        the chair `whoami` proves for the calling body, with that proof's method
                    as verified_by; no chair, or a failed identify, records nothing
  an MCP send       the conductor named by the request's checked bearer, verified_by bearer;
                    a name passed as an argument is never read
  anything else     no `from`: the sender is unknown, and a reply to it wakes nobody

A conductor may be the `from` of a synapse row it sent over a checked bearer, and of nothing
else: a note from a conductor is still refused, and replies() still leaves the conductor's own
sends out of its mail. With the sender proven, a reply citing the token wakes it.

Every id is synthetic, the thread roots and the Convoy home are temporary folders, and no
harness is started.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.conductor import replies
from convoy.convoy import bind, seat
from convoy.layer import feed_since, hook
from convoy.mcp_http import handle_rpc
from convoy.pulse import write_pulse
from convoy.synapse import fake_runner, send_one
from convoy.wake_dispatch import Dispatcher
from convoy.wake_routes import register_route
try:
    from test.demo.write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401

RECEIVER = "chair-alpha"
SENDER = "chair-beta"
CONDUCTOR = "grok-bot"
PRINCIPAL = {"id": "bearer-0000", "conductor": CONDUCTOR, "label": "synthetic connector"}


class Thread(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-sender-home-")
        self.addCleanup(home.cleanup)
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        env.start()
        self.addCleanup(env.stop)
        folder = tempfile.TemporaryDirectory(prefix="convoy-sender-root-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        bind(self.root, "synthetic-thread")
        seat(self.root, "claude", RECEIVER, worktree=str(self.root), resume="synthetic-resume-alpha")
        other = tempfile.TemporaryDirectory(prefix="convoy-sender-wt-")
        self.addCleanup(other.cleanup)
        seat(self.root, "claude", SENDER, worktree=other.name)

    def synapses(self):
        return [r for r in feed_since(self.root, "1970-01-01T00:00:00Z") if r["kind"] == "synapse"]

    def cli_send(self, whoami, procs=None):
        """whoami: the card identify returns, or the exception it raises. procs: the process
        table the sender probe returns, or the exception it raises (default: an empty table)."""
        if isinstance(whoami, Exception):
            who = mock.patch("convoy.cli.identify", side_effect=whoami)
        else:
            who = mock.patch("convoy.cli.identify", return_value=whoami)
        if isinstance(procs, Exception):
            table = mock.patch("convoy.cli.enumerate_processes", side_effect=procs, create=True)
        else:
            table = mock.patch("convoy.cli.enumerate_processes", return_value=procs or [], create=True)
        with who as self.identify, table as self.enumerate, redirect_stdout(io.StringIO()) as out:
            rc = main(["--root", str(self.root), "send", "--to", RECEIVER, "synthetic body"])
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])

    def mcp_send(self, arguments, principal):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "send", "arguments": arguments}}
        return handle_rpc(self.root, msg, principal=principal)


class TheFeedWriter(Thread):
    def test_a_conductor_may_be_the_sender_of_a_synapse_over_a_bearer(self):
        row = hook(self.root, kind="synapse", summary="send claude", instance_id=RECEIVER, author=CONDUCTOR,
                   verified_by="bearer", local_writer=False)
        self.assertEqual((row["from"], row["verified_by"], row["device"]), (CONDUCTOR, "bearer", None))
        self.assertNotIn("author_claimed", row)

    def test_a_conductor_is_still_refused_as_the_author_of_a_note(self):
        with self.assertRaises(ValueError):
            hook(self.root, kind="note", summary="hello", instance_id=CONDUCTOR, author=CONDUCTOR,
                 verified_by="bearer")

    def test_the_contract_says_a_send_over_a_bearer_carries_the_conductor(self):
        from convoy.conductor import contract_text
        text = contract_text()
        self.assertIn("`kind=synapse`", text)
        self.assertIn("`verified_by=bearer`", text)

    def test_a_conductor_without_a_bearer_is_refused_as_a_sender(self):
        for method in (None, "environment"):
            with self.assertRaises(ValueError):
                hook(self.root, kind="synapse", summary="send claude", instance_id=RECEIVER, author=CONDUCTOR,
                     verified_by=method)


class TheSendPath(Thread):
    def test_a_proven_sender_is_recorded_with_its_method(self):
        card = send_one(self.root, RECEIVER, "synthetic body", runner=fake_runner,
                        sender={"chair": SENDER, "verified_by": "environment"})
        self.assertTrue(card["ok"], card)
        [row] = self.synapses()
        self.assertEqual((row["instance_id"], row["from"], row["verified_by"]), (RECEIVER, SENDER, "environment"))
        self.assertNotIn("author_claimed", row)

    def test_an_unproven_sender_is_not_recorded(self):
        for sender in ({"chair": SENDER, "verified_by": None}, {"chair": SENDER, "verified_by": "claimed"},
                       {"chair": "", "verified_by": "environment"}, None):
            send_one(self.root, RECEIVER, "synthetic body", runner=fake_runner, sender=sender)
        for row in self.synapses():
            self.assertNotIn("from", row)
            self.assertIsNone(row["verified_by"])


class TheCli(Thread):
    def test_a_cli_send_records_the_chair_whoami_proves(self):
        rc, card = self.cli_send({"ok": True, "chair": SENDER, "via": "pane-host"})
        self.assertEqual(rc, 0, card)
        [row] = self.synapses()
        self.assertEqual((row["from"], row["verified_by"]), (SENDER, "pane-host"))

    def test_a_cli_send_from_an_unknown_body_records_no_sender(self):
        rc, card = self.cli_send({"ok": False, "chair": None, "via": None})
        self.assertEqual(rc, 0, card)
        [row] = self.synapses()
        self.assertNotIn("from", row)

    def test_a_failed_identify_never_stops_the_send(self):
        rc, card = self.cli_send(OSError("process table unavailable"))
        self.assertEqual(rc, 0, card)
        [row] = self.synapses()
        self.assertNotIn("from", row)


class TheSenderProbe(Thread):
    def test_the_probe_is_one_short_attempt_and_identify_reads_its_table(self):
        table = [{"pid": 1, "ppid": 0, "cmdline": "synthetic", "cwd": None}]
        rc, card = self.cli_send({"ok": True, "chair": SENDER, "via": "pane-host"}, procs=table)
        self.assertEqual(rc, 0, card)
        self.enumerate.assert_called_once()
        kwargs = self.enumerate.call_args.kwargs
        self.assertEqual(kwargs.get("attempts"), 1)
        self.assertLessEqual(kwargs.get("timeout", 999), 10)
        self.assertIs(self.identify.call_args.kwargs.get("procs"), table)
        self.assertIs(self.identify.call_args.kwargs.get("env"), os.environ, "the caller's own environment")

    def test_a_probe_that_times_out_leaves_the_sender_unknown_and_sends(self):
        import subprocess
        rc, card = self.cli_send({"ok": True, "chair": SENDER, "via": "pane-host"},
                                 procs=subprocess.TimeoutExpired("powershell", 5))
        self.assertEqual(rc, 0, card)
        [row] = self.synapses()
        self.assertNotIn("from", row)

    def test_one_attempt_with_a_timeout_reaches_the_process_table_call(self):
        import subprocess
        from convoy import panes
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Call cancelled")
        with mock.patch.object(panes.shutil, "which", return_value="powershell"),                 mock.patch.object(panes.subprocess, "run", return_value=failed) as run,                 mock.patch.object(panes.time, "sleep"):
            with self.assertRaises(OSError):
                panes._enumerate_windows(attempts=1, timeout=5)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["timeout"], 5)


class TheMcp(Thread):
    def test_a_bearer_proven_conductor_send_records_the_conductor(self):
        reply = self.mcp_send({"to": RECEIVER, "body": "synthetic body"}, PRINCIPAL)
        self.assertTrue(reply["result"]["structuredContent"]["ok"], reply)
        [row] = self.synapses()
        self.assertEqual((row["from"], row["verified_by"], row["device"]), (CONDUCTOR, "bearer", None))

    def test_a_sender_named_in_the_arguments_is_ignored(self):
        open_write_gate(self)
        reply = self.mcp_send({"to": RECEIVER, "body": "synthetic body", "from": CONDUCTOR, "sender": SENDER,
                               "verified_by": "bearer"}, None)
        self.assertTrue(reply["result"]["structuredContent"]["ok"], reply)
        [row] = self.synapses()
        self.assertNotIn("from", row)
        self.assertIsNone(row["verified_by"])

    def test_replies_leaves_the_conductors_own_send_out_of_its_mail(self):
        card = self.mcp_send({"to": RECEIVER, "body": "synthetic body"}, PRINCIPAL)["result"]["structuredContent"]
        hook(self.root, kind="note", summary="re token " + card["token"] + ": done", instance_id=RECEIVER,
             to=CONDUCTOR)
        rows = replies(self.root, CONDUCTOR, token=card["token"])["rows"]
        self.assertEqual([r["kind"] for r in rows], ["note"])


class TheReplyWake(Thread):
    def test_a_reply_wakes_the_proven_sender(self):
        fired = []

        class Routes:
            def fire(self, route, pointer, route_row):
                fired.append(pointer)

            def alert(self, target, text):
                pass

        now = datetime.now(timezone.utc)
        register_route(self.root, SENDER, "waiter", registered_by="person")
        write_pulse(self.root, SENDER, pulse_source="wait")
        card = send_one(self.root, RECEIVER, "synthetic body", runner=fake_runner,
                        sender={"chair": SENDER, "verified_by": "environment"})
        hook(self.root, kind="note", summary="re token " + card["token"] + ": done", instance_id=RECEIVER, to=SENDER)
        d = Dispatcher(self.root, Routes(), clock=lambda: now)
        d.start()
        d.step()
        replies_fired = [p for p in fired if p["reason"] == "reply"]
        self.assertEqual([(p["target"], p["token"], p["from"]) for p in replies_fired],
                         [(SENDER, card["token"], RECEIVER)])


if __name__ == "__main__":
    unittest.main()
