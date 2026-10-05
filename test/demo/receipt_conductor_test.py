"""Receipts reach the sender; the conductor field names a real chair.

(A) A note that cites a send token and names no addressee goes to that send's
    proven sender. A note citing a token someone else sent, addressed to its
    own author, refuses: a receipt goes to the sender.
(B) On a thread with no hosted conductor, the lead, attach and start cards
    print `conductor` as the lead chair, or null. Never the constant.

Synthetic evidence only: no harness launches, no real home, no real index.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import attach, bind, seat
from convoy.layer import hook, neuron_note

TOKEN = "0123456789abcdef0123456789abcdef"
HOSTED = "grok-bot"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        base = Path(self.owner.name)
        self.root = base / "project"
        self.root.mkdir()
        home = base / "home"
        home.mkdir()
        env = patch.dict(os.environ, {"CONVOY_HOME": str(base / "convoy-home"), "HOME": str(home),
                                      "USERPROFILE": str(home)})
        env.start()
        self.addCleanup(env.stop)
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "chair-sender", resume="native-chair-sender")
        seat(self.root, "codex", "chair-receiver", resume="native-chair-receiver")
        who = patch("convoy.cli.identify", return_value={"ok": True, "chair": None, "via": None})
        who.start()
        self.addCleanup(who.stop)

    def cli(self, *args, proven=None):
        me = {"ok": True, "chair": proven, "via": "environment" if proven else None}
        out = io.StringIO()
        with redirect_stdout(out), patch("convoy.cli.identify", return_value=me):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])


class ReceiptsGoToTheSender(Sandbox):
    def setUp(self):
        super().setUp()
        # the send row as `convoy send` writes it: subject = the receiver, from = the proven sender
        hook(self.root, "synapse", "send codex", instance_id="chair-receiver", author="chair-sender",
             to="codex", extra={"token": TOKEN}, verified_by="token")

    def test_a_receipt_with_no_addressee_goes_to_the_sender(self):
        rc, row = self.cli("hook", "note", "Acknowledged token=" + TOKEN + " from the sender",
                           "--instance-id", "chair-receiver")
        self.assertEqual(rc, 0, row)
        self.assertEqual(row["to"], "chair-sender")

    def test_a_receipt_addressed_to_its_own_author_refuses(self):
        rc, row = self.cli("hook", "note", "Acknowledged token=" + TOKEN + " from the sender",
                           "--instance-id", "chair-receiver", "--to", "chair-receiver")
        self.assertEqual(rc, 1, row)
        self.assertEqual(row["error"], "a receipt goes to the sender: --to chair-sender")

    def test_the_mcp_note_addresses_the_sender_too(self):
        row = neuron_note(self.root, "re token " + TOKEN + ": done", instance_id="chair-receiver")
        self.assertEqual(row["to"], "chair-sender")

    def test_a_note_with_no_token_keeps_no_addressee(self):
        rc, row = self.cli("hook", "note", "plain progress", "--instance-id", "chair-receiver")
        self.assertEqual(rc, 0, row)
        self.assertNotIn("to", row)

    def test_a_third_party_citing_the_token_stays_unaddressed(self):
        rc, row = self.cli("hook", "note", "fyi the send with token=" + TOKEN + " looked stuck",
                           "--instance-id", "chair-third")
        self.assertEqual(rc, 0, row)
        self.assertNotIn("to", row)

    def test_an_explicit_other_addressee_is_kept(self):
        rc, row = self.cli("hook", "note", "re token " + TOKEN + ": cc", "--instance-id", "chair-receiver",
                           "--to", "chair-third")
        self.assertEqual(rc, 0, row)
        self.assertEqual(row["to"], "chair-third")


class ConductorIsARealChair(Sandbox):
    def test_no_lead_means_conductor_null(self):
        rc, card = self.cli("lead")
        self.assertIsNone(card["conductor"])
        self.assertIsNone(attach(self.root, probe_fn=lambda h: {})["conductor"])

    def test_the_lead_chair_is_the_conductor(self):
        self.assertEqual(self.cli("lead", "--to", "chair-receiver", "--as", "chair-sender", proven="chair-sender")[0], 0)
        rc, card = self.cli("lead")
        self.assertEqual(card["conductor"], "chair-receiver")
        self.assertEqual(attach(self.root, probe_fn=lambda h: {})["conductor"], "chair-receiver")
        rc, legacy = self.cli("lead", "--to", "claude", proven="chair-receiver")
        self.assertEqual(rc, 0, legacy)
        self.assertEqual(legacy["conductor"], "chair-sender")
        self.assertNotEqual(legacy["conductor"], HOSTED)


if __name__ == "__main__":
    unittest.main()
