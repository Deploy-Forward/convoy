import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.context import newest_handoff, pack, stdin_for
from convoy.registry import lookup, parse_agents_jsonl, parse_session_id
from convoy.synapse import send_one

class Phase1ThreadedContext(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "thread.md").write_text("SECRET_THREAD_BYTES")
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("SECRET_BRIEF")

    def test_pack_is_paths_not_bytes(self):
        p = pack(self.root)
        self.assertTrue(str(p["thread"]).endswith("thread.md"))
        self.assertIsNone(p["role"])
        self.assertTrue(str(p["brief"]).endswith("brief.md"))
        self.assertIsNone(p["instance_id"])
        self.assertIsNone(p["branch"])
        blob = json.dumps(p)
        self.assertNotIn("SECRET_THREAD_BYTES", blob)
        self.assertNotIn("SECRET_BRIEF", blob)

    def test_stdin_says_read_paths(self):
        p = pack(self.root)
        msg = stdin_for(p, "Reply PHASE1")
        self.assertIn("read these paths", msg)
        self.assertIn("Reply PHASE1", msg)
        self.assertNotIn("SECRET_THREAD_BYTES", msg)

    def test_dry_run_mints_no_session_id(self):
        card = send_one(self.root, "grok", "ping", dry_run=True, label="p1")
        self.assertIsNone(card["session_id"])
        self.assertTrue(card["dry_run"])
        self.assertIsNone(lookup(self.root, "anything"))
        rc = main(["--root", str(self.root), "send", "--dry-run", "--to", "grok", "ping"])
        self.assertEqual(rc, 0)

    def test_turn2_uses_registered_session_id(self):
        t1 = send_one(self.root, "grok", "T1", label="p1")
        sid = t1["session_id"]
        self.assertTrue(sid)
        self.assertIsNotNone(lookup(self.root, sid))
        t2 = send_one(self.root, "grok", "T2", instance_id=sid)
        self.assertEqual(t2["session_id"], sid)
        self.assertEqual(t2.get("delivery"), "queued")
        self.assertIn("T2", t2["stdin"])

    def test_parse_ola_brain_colon_reply(self):
        raw = "grok-session-phase1thread: Marco, load the brief\nPHASE1_T1"
        self.assertEqual(parse_session_id(raw), "grok-session-phase1thread")
        self.assertEqual(parse_session_id('{"instance_id":"grok-session-json"}'), "grok-session-json")
        self.assertIsNone(parse_session_id("00000000-0000-4000-8000-000000000002"))
        self.assertIsNone(parse_session_id("error: not a session"))

    def test_parse_agents_jsonl_fallback(self):
        chat = self.root / ".ola" / "agent-chat"
        chat.mkdir()
        (chat / "agents.jsonl").write_text(
            '{"instance_id":"grok-session-phase1autoreg","agent":"grok"}' + chr(10)
        )
        self.assertEqual(parse_agents_jsonl(self.root, "grok", label="phase1-autoreg"), "grok-session-phase1autoreg")
        self.assertIsNone(parse_agents_jsonl(self.root, "claude", label="phase1-autoreg"))

    def test_newest_handoff_prefers_convoy_folder_over_legacy_ola(self):
        legacy = self.root / ".ola" / "old-handoff.md"
        legacy.write_text("old", encoding="utf-8")
        self.assertTrue(str(newest_handoff(self.root)).endswith("old-handoff.md"))
        dest = self.root / ".convoy" / "handoff"
        dest.mkdir(parents=True)
        fresh = dest / "chair-1-20260905T010000Z.md"
        fresh.write_text("new", encoding="utf-8")
        self.assertEqual(newest_handoff(self.root), str(fresh))
        brief = self.root / ".convoy" / "brief.md"
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text("NEW_BRIEF", encoding="utf-8")
        p = pack(self.root)
        self.assertEqual(p["brief"], str(brief))
        self.assertEqual(p["handoff"], str(fresh))

    def test_unknown_instance_refuses(self):
        card = send_one(self.root, "grok", "nope", instance_id="not-registered")
        self.assertFalse(card["ok"])
        self.assertIsNone(card["session_id"])

if __name__ == "__main__":
    unittest.main()


class RecordIsConvoyNotOla(unittest.TestCase):
    """Marco 2026-09-10: a conductor kept writing under .ola/. context now names the
    canonical write paths and lists every legacy .ola file it still reads."""

    def test_legacy_is_labelled_and_canonical_paths_are_named(self):
        import tempfile
        from convoy.context import pack
        root = Path(tempfile.mkdtemp())
        (root / ".convoy").mkdir(); (root / ".ola").mkdir()
        (root / ".ola" / "brief.md").write_text("b", encoding="utf-8")
        (root / ".ola" / "handoff-20260910T073611Z.md").write_text("h", encoding="utf-8")
        out = pack(root)
        self.assertEqual(out["brief_source"], "legacy-ola"); self.assertEqual(out["handoff_source"], "legacy-ola")
        self.assertEqual(sorted(Path(x).name for x in out["legacy_ola"]), ["brief.md", "handoff-20260910T073611Z.md"])
        self.assertTrue(out["advice"].startswith("write briefs to .convoy/brief.md"))
        self.assertEqual(Path(out["canonical"]["brief"]), root / ".convoy" / "brief.md")
        self.assertEqual(Path(out["canonical"]["handoff_dir"]), root / ".convoy" / "handoff")
        (root / ".convoy" / "brief.md").write_text("new", encoding="utf-8")
        (root / ".convoy" / "handoff").mkdir(); (root / ".convoy" / "handoff" / "20260910T080000.md").write_text("n", encoding="utf-8")
        out2 = pack(root)
        self.assertEqual(out2["brief_source"], "convoy"); self.assertEqual(out2["handoff_source"], "convoy")
        self.assertEqual(Path(out2["brief"]), root / ".convoy" / "brief.md")
        self.assertEqual(len(out2["legacy_ola"]), 2, "legacy files are still listed so the drift stays visible")
        clean = Path(tempfile.mkdtemp()); (clean / ".convoy").mkdir()
        self.assertEqual(pack(clean)["legacy_ola"], []); self.assertIsNone(pack(clean)["advice"])
