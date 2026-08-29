import io, json, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.convoy import attach, bind, ensure_id, list_seats, read_id, read_thread, seat
from convoy.layer import feed_since
from convoy.context import pack
from convoy.synapse import send_one

def _run(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue()
    data = json.loads(raw) if raw.strip() else None
    return rc, data

class Phase7Attach(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "thread.md").write_text("SECRET_THREAD_BYTES")
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("SECRET_BRIEF")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())

    def test_init_writes_id_second_init_same(self):
        rc1, d1 = _run(self.root, "init")
        self.assertEqual(rc1, 0)
        self.assertTrue(d1["ok"])
        cid = d1["convoy_id"]
        self.assertTrue(cid.startswith("cvy_"))
        id_file = self.root / ".convoy" / "id"
        self.assertTrue(id_file.is_file())
        raw = id_file.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.decode("utf-8").strip(), cid)
        rc2, d2 = _run(self.root, "init")
        self.assertEqual(rc2, 0)
        self.assertEqual(d2["convoy_id"], cid)
        self.assertEqual(ensure_id(self.root), cid)

    def test_id_before_init_is_null_does_not_create(self):
        rc, d = _run(self.root, "id")
        self.assertEqual(rc, 0)
        self.assertIsNone(d["convoy_id"])
        self.assertIsNone(read_id(self.root))
        self.assertFalse((self.root / ".convoy" / "id").exists())

    def test_two_seats_one_convoy_different_worktrees(self):
        _, initd = _run(self.root, "init")
        cid = initd["convoy_id"]
        rcg, g = _run(
            self.root, "seat", "--to", "grok", "--session-id", "sess-grok",
            "--worktree", str(self.wt_g), "--model", "explicit-grok",
        )
        self.assertEqual(rcg, 0)
        rcc, c = _run(
            self.root, "seat", "--to", "claude", "--session-id", "sess-claude",
            "--worktree", str(self.wt_c),
        )
        self.assertEqual(rcc, 0)
        self.assertEqual(g["session_id"], "sess-grok")
        self.assertEqual(c["session_id"], "sess-claude")
        self.assertEqual(g["convoy_id"], cid)
        self.assertEqual(c["convoy_id"], cid)
        self.assertNotEqual(g["worktree"], c["worktree"])
        self.assertEqual(g["model"], "explicit-grok")
        self.assertIsNone(c.get("model"))
        rc, rows = _run(self.root, "seats")
        self.assertEqual(rc, 0)
        ids = {r["session_id"] for r in rows}
        self.assertEqual(ids, {"sess-grok", "sess-claude"})
        self.assertEqual(len(rows), 2)
        by = {r["to"]: r for r in rows}
        self.assertEqual(by["grok"]["worktree"], str(self.wt_g))
        self.assertEqual(by["claude"]["worktree"], str(self.wt_c))
        self.assertEqual(by["grok"]["convoy_id"], cid)
        listed = list_seats(self.root, convoy_id=cid)
        self.assertEqual({r["session_id"] for r in listed}, ids)

    def test_attach_unknown_id_mismatch_no_seats(self):
        _run(self.root, "init")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        rc, d = _run(self.root, "attach", "cvy_not_this_convoy")
        self.assertNotEqual(rc, 0)
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "convoy_id mismatch")
        self.assertFalse(d.get("seats"))
        disk = read_id(self.root)
        self.assertEqual(d["convoy_id"], disk)
        lib = attach(self.root, "cvy_not_this_convoy")
        self.assertFalse(lib["ok"])
        self.assertEqual(lib["error"], "convoy_id mismatch")
        self.assertFalse(lib.get("seats"))

    def test_attach_after_init_seats_pointers_no_contents(self):
        _, initd = _run(self.root, "init")
        cid = initd["convoy_id"]
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok")
        seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c))
        rc, d = _run(self.root, "attach")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertEqual(d["convoy_id"], cid)
        ids = {s["session_id"] for s in d["seats"]}
        self.assertEqual(ids, {"sess-grok", "sess-claude"})
        ptr = d["pointers"]
        self.assertIsInstance(ptr, dict)
        blob = json.dumps(ptr)
        self.assertNotIn("SECRET_THREAD_BYTES", blob)
        self.assertNotIn("SECRET_BRIEF", blob)
        for v in ptr.values():
            self.assertTrue(v is None or isinstance(v, (str, int)))
            if isinstance(v, str):
                self.assertNotIn("SECRET_THREAD_BYTES", v)

    def test_send_with_instance_id_resumes(self):
        _run(self.root, "init")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        card = send_one(self.root, "grok", "resume", instance_id="sess-grok")
        self.assertTrue(card["ok"])
        self.assertEqual(card["session_id"], "sess-grok")
        self.assertNotEqual(card["session_id"], "spawned-grok")
        rc, d = _run(self.root, "send", "--to", "grok", "--instance-id", "sess-grok", "resume")
        self.assertEqual(rc, 0)
        self.assertEqual(d["session_id"], "sess-grok")
        self.assertNotEqual(d["session_id"], "spawned-grok")

    def test_send_without_instance_id_refuses_when_seat_exists(self):
        _run(self.root, "init")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        spawned = {"n": 0}
        def runner(to, body, instance_id=None, **k):
            spawned["n"] += 1
            return {"ok": True, "to": to, "session_id": "spawned-" + to, "model": None, "usage_remaining": None, "body": "ACK"}
        card = send_one(self.root, "grok", "ping", runner=runner)
        self.assertFalse(card["ok"])
        self.assertIsNone(card["session_id"])
        self.assertIn("seat exists", card["error"])
        self.assertEqual(spawned["n"], 0)
        rc, d = _run(self.root, "send", "--to", "grok", "ping")
        self.assertNotEqual(rc, 0)
        self.assertFalse(d["ok"])
        self.assertIsNone(d["session_id"])
        self.assertNotEqual(d.get("session_id"), "spawned-grok")

    def test_dry_run_session_id_null(self):
        _run(self.root, "init")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        card = send_one(self.root, "grok", "ping", dry_run=True)
        self.assertIsNone(card["session_id"])
        self.assertTrue(card["dry_run"])
        rc, d = _run(self.root, "send", "--dry-run", "--to", "grok", "ping")
        self.assertEqual(rc, 0)
        self.assertIsNone(d["session_id"])

    def test_bind_writes_thread_and_pointer_path(self):
        key = "THREAD_KEY_NOT_A_TRANSCRIPT"
        rc, d = _run(self.root, "bind", "--thread", key)
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertEqual(d["thread"], key)
        tfile = self.root / ".convoy" / "thread"
        self.assertTrue(tfile.is_file())
        raw = tfile.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.decode("utf-8").strip(), key)
        self.assertEqual(read_thread(self.root), key)
        md = self.root / "thread.md"
        self.assertTrue(md.is_file())
        md_text = md.read_text(encoding="utf-8")
        cid = read_id(self.root)
        self.assertIn(cid, md_text)
        self.assertIn(key, md_text)
        packed = pack(self.root)
        self.assertEqual(packed["thread"], str(md.resolve()))
        self.assertNotEqual(packed["thread"], md_text)
        self.assertNotIn(key, packed["thread"])
        rc, att = _run(self.root, "attach")
        self.assertEqual(rc, 0)
        self.assertEqual(att["thread"], key)
        self.assertEqual(att["pointers"]["thread"], str(md.resolve()))
        self.assertNotEqual(att["pointers"]["thread"], md_text)
        blob = json.dumps(att["pointers"])
        self.assertNotIn("SECRET_THREAD_BYTES", blob)

    def test_bind_does_not_mint_second_convoy_id(self):
        _, initd = _run(self.root, "init")
        cid = initd["convoy_id"]
        rc, d = _run(self.root, "bind", "--thread", "same-convoy-thread")
        self.assertEqual(rc, 0)
        self.assertEqual(d["convoy_id"], cid)
        self.assertEqual(read_id(self.root), cid)
        self.assertEqual(ensure_id(self.root), cid)
        rc2, d2 = _run(self.root, "init")
        self.assertEqual(d2["convoy_id"], cid)

    def test_first_attach_hooks_since_null_feed_empty(self):
        _run(self.root, "init")
        rc, d = _run(self.root, "attach")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertIsNone(d["since"])
        self.assertEqual(d["feed"], [])
        self.assertTrue(d["ts"])
        rows = feed_since(self.root, d["ts"])
        attach_rows = [r for r in rows if r.get("kind") == "attach"]
        self.assertEqual(len(attach_rows), 1)
        self.assertEqual(attach_rows[0]["ts"], d["ts"])
        self.assertEqual(attach_rows[0]["kind"], "attach")
        self.assertEqual(attach_rows[0]["convoy_id"], d["convoy_id"])

    def test_second_attach_since_and_feed(self):
        _run(self.root, "init")
        rc1, a1 = _run(self.root, "attach")
        self.assertEqual(rc1, 0)
        first_ts = a1["ts"]
        time.sleep(0.002)
        rc2, a2 = _run(self.root, "attach")
        self.assertEqual(rc2, 0)
        self.assertEqual(a2["since"], first_ts)
        self.assertGreater(a2["ts"], first_ts)
        self.assertTrue(a2["feed"])
        first_in_feed = [r for r in a2["feed"] if r.get("kind") == "attach" and r.get("ts") == first_ts]
        self.assertEqual(len(first_in_feed), 1)
        self.assertGreaterEqual(first_in_feed[0]["ts"], a2["since"])

    def test_mismatch_attach_does_not_stamp(self):
        _run(self.root, "init")
        rc, first = _run(self.root, "attach")
        self.assertEqual(rc, 0)
        before = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "attach"]
        n = len(before)
        rc2, d = _run(self.root, "attach", "cvy_not_this_convoy")
        self.assertNotEqual(rc2, 0)
        self.assertFalse(d["ok"])
        after = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "attach"]
        self.assertEqual(len(after), n)
        lib = attach(self.root, "cvy_not_this_convoy")
        self.assertFalse(lib["ok"])
        after2 = [r for r in feed_since(self.root, "1970-01-01T00:00:00.000000Z") if r.get("kind") == "attach"]
        self.assertEqual(len(after2), n)

    def test_send_one_card_has_convoy_id_after_init(self):
        self.assertIsNone(send_one(self.root, "grok", "ping")["convoy_id"])
        _, initd = _run(self.root, "init")
        cid = initd["convoy_id"]
        card = send_one(self.root, "grok", "ping")
        self.assertEqual(card["convoy_id"], cid)
        self.assertTrue(card["ok"])
        rc, d = _run(self.root, "send", "--to", "grok", "ping")
        self.assertEqual(rc, 0)
        self.assertEqual(d["convoy_id"], cid)

    def test_attach_seats_surface_usage(self):
        _run(self.root, "init")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g), model="explicit-grok")
        seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="Fable 5")
        def stub(to):
            if to == "grok":
                return {"usage_remaining": None, "limited": False, "raw": None}
            if to == "claude":
                return {
                    "usage_remaining": "Current session: 7% used\nCurrent week (all models): 69% used",
                    "limited": False,
                    "raw": "Current session: 7% used\nCurrent week (all models): 69% used",
                }
            return {"usage_remaining": None, "limited": False, "raw": None}
        d = attach(self.root, probe_fn=stub)
        self.assertTrue(d["ok"])
        by = {s["to"]: s for s in d["seats"]}
        self.assertIsNone(by["grok"]["usage_remaining"])
        self.assertNotEqual(by["grok"]["usage_remaining"], 0)
        self.assertNotIn("session_pct", by["grok"])
        self.assertEqual(by["claude"]["session_pct"], 7)
        self.assertEqual(by["claude"]["week_pct"], 69)
        self.assertFalse(by["claude"]["limited"])

    def test_lead_conductor_grok_bot(self):
        rc0, d0 = _run(self.root, "lead")
        self.assertEqual(rc0, 0)
        self.assertEqual(d0["conductor"], "grok-bot")
        self.assertIsNone(d0["lead"])
        rc, d = _run(self.root, "lead", "--to", "grok")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertEqual(d["lead"], "grok")
        self.assertEqual(d["conductor"], "grok-bot")
        self.assertEqual(d["convoy_id"], read_id(self.root))
        rc2, d2 = _run(self.root, "lead")
        self.assertEqual(d2["lead"], "grok")
        att = attach(self.root, probe_fn=lambda to: {"usage_remaining": None, "limited": False, "raw": None})
        self.assertEqual(att["conductor"], "grok-bot")
        self.assertEqual(att["lead"], "grok")

if __name__ == "__main__":
    unittest.main()
