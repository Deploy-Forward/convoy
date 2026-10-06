"""One torn registry line never breaks a send, and a seated chair is a known instance.

registry.jsonl is append-only and shared: a writer killed mid-line leaves half a row. Every
lookup used to json.loads each line unguarded, so one torn line crashed every send that
named an instance id. The registry also only knew chairs a send had registered, so a chair
seated through seats.jsonl alone was refused as "instance_id not in registry".
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, seat
from convoy.inbox import pending
from convoy.registry import lookup, lookup_any, register, registry_path
from convoy.synapse import send_one


class RegistryTornLine(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "torn")

    def tear(self):
        with registry_path(self.root).open("a", encoding="utf-8") as f:
            f.write('{"session_id": "half-writ\n')

    def test_registry_lookup_skips_torn_lines(self):
        register(self.root, "chair-a", "grok")
        self.tear()
        register(self.root, "chair-b", "grok", extra={"resume": "vendor-b"})
        self.assertEqual(lookup(self.root, "chair-a")["to"], "grok")
        self.assertEqual(lookup(self.root, "chair-b")["session_id"], "chair-b")
        self.assertEqual(lookup_any(self.root, "vendor-b")["session_id"], "chair-b")
        self.assertIsNone(lookup(self.root, "half-writ"))

    def test_send_by_id_survives_a_torn_registry_line(self):
        seat(self.root, "grok", "chair-a", worktree=str(Path(tempfile.mkdtemp())))
        register(self.root, "chair-a", "grok")
        self.tear()
        card = send_one(self.root, "grok", "hello", instance_id="chair-a")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "queued")

    def test_send_by_id_falls_back_to_seat_row_when_registry_lacks_instance(self):
        seat(self.root, "grok", "chair-s", worktree=str(Path(tempfile.mkdtemp())))
        # The registry lost the chair's row (a deleted or rewritten file); seats.jsonl has it.
        registry_path(self.root).write_text('{"session_id": "someone-else", "to": "grok"}\n', encoding="utf-8")
        self.assertIsNone(lookup(self.root, "chair-s"))
        card = send_one(self.root, "grok", "hello", instance_id="chair-s")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(pending(self.root, "chair-s")[0]["body"], "hello")

    def test_send_by_id_still_refuses_an_unknown_instance(self):
        card = send_one(self.root, "grok", "hello", instance_id="nobody")
        self.assertFalse(card["ok"], card)
        self.assertIn("not in registry", card["error"])


if __name__ == "__main__":
    unittest.main()
