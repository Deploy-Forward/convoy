"""Calling-session attach: synthetic evidence only, no harness launches."""
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
from convoy.convoy import bind, list_seats, read_id, seat
from convoy.inbox import enqueue, pending
from convoy.layer import hook
from convoy.panes import identify


class ListAttach(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        self.root = Path(self.owner.name) / "project"
        self.root.mkdir()
        self.home = Path(self.owner.name) / "home"
        p = patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        bind(self.root, "synthetic-project")
        self.procs = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                      {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["--root", str(self.root), *args])
        return rc, out.getvalue()

    def identity(self, **changes):
        args = dict(pid=21, procs=self.procs, cwd=str(self.root),
                    env={"CLAUDE_CODE_SESSION_ID": "synthetic-native-id"}, allow_unseated=True)
        args.update(changes)
        return identify(self.root, **args)

    def test_fresh_session_is_proved_without_a_chair(self):
        me = self.identity()
        self.assertTrue(me["ok"], me)
        self.assertIsNone(me["chair"])
        self.assertEqual(me["native_session"], {"id": "synthetic-native-id", "harness": "claude",
                                               "via": "environment", "recorded": False})

    def test_fresh_session_disagreeing_native_sources_refuse(self):
        procs = [dict(self.procs[0], cmdline="claude --resume synthetic-other-id"), self.procs[1]]
        self.assertFalse(self.identity(procs=procs)["ok"])

    def test_nested_harness_cannot_attach_with_inherited_identity(self):
        procs = [dict(self.procs[0], ppid=19), self.procs[1],
                 {"pid": 19, "ppid": 1, "cmdline": "claude --resume synthetic-parent", "cwd": None}]
        self.assertFalse(self.identity(procs=procs)["ok"])

    def test_pi_picker_argument_is_not_native_session_proof(self):
        procs = [dict(self.procs[0], cmdline="pi --resume synthetic-id"), self.procs[1]]
        self.assertFalse(self.identity(procs=procs, env={})["ok"])

    def test_list_keeps_skipped_roots_and_does_not_mutate_index(self):
        from convoy.thread_list import thread_list, format_list
        before = (self.home / "threads.json").read_bytes()
        card = thread_list()
        self.assertEqual(card["threads"], [])
        self.assertEqual(card["skipped"][0]["reason"], "temp")
        self.assertIn(read_id(self.root), format_list(card))
        self.assertEqual(before, (self.home / "threads.json").read_bytes())

    def test_unreadable_root_is_unknown_not_gone(self):
        from convoy.index import list_threads
        from convoy.thread_list import thread_list
        with patch("convoy.index._disk_id", side_effect=PermissionError), \
             patch("convoy.thread_list.is_temp_root", return_value=False):
            self.assertIsNone(list_threads()[0]["present"])
            card = thread_list()
        self.assertEqual(card["skipped"][0]["reason"], "unreadable: PermissionError")

    def test_list_pick_and_full_neuron_rows_match_json(self):
        from convoy.thread_list import thread_list, format_list
        seat(self.root, "claude", "synthetic-long-neuron-name")
        hook(self.root, "heartbeat", "turn ended", author="synthetic-long-neuron-name")
        with patch("convoy.thread_list.is_temp_root", return_value=False):
            card = thread_list()
        self.assertEqual(card["threads"][0]["pick"], 1)
        n = card["threads"][0]["neurons"][0]
        self.assertEqual(n["neuron"], "synthetic-long-neuron-name")
        self.assertTrue(n["active"])
        text = format_list(card)
        self.assertIn("1.", text)
        self.assertIn("synthetic-long-neuron-name", text)
        self.assertIn(n["id"], text)

    def test_no_choice_lists_and_refuses_without_seating(self):
        rc, out = self.cli("attach")
        self.assertEqual(rc, 1)
        self.assertIn("choose a thread", out)
        self.assertEqual(list_seats(self.root), [])

    def test_attach_repeat_detach_and_send_refusal(self):
        from convoy.sessions import attach_session, detach_session
        from convoy.synapse import send_one, fake_runner
        with patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            first = attach_session(read_id(self.root), cwd=self.root)
            self.assertTrue(first["ok"], first)
            sid = first["chair"]
            self.assertEqual(first["verified_by"], "environment")
            again = attach_session(read_id(self.root), cwd=self.root)
            self.assertTrue(again["already"], again)
            self.assertEqual(len(list_seats(self.root)), 1)
        with patch("convoy.sessions.identify", return_value={"ok": True, "chair": sid,
                   "via": "environment", "harness": "claude"}):
            detached = detach_session(root=self.root, cwd=self.root)
        self.assertTrue(detached["ok"], detached)
        self.assertTrue(Path(detached["handoff"]).is_file())
        self.assertTrue(list_seats(self.root)[0]["detached"])
        with patch("convoy.synapse.probe") as probe, patch("convoy.synapse.enqueue") as queue:
            refused = send_one(self.root, "claude", "hello", instance_id=sid, runner=fake_runner)
        self.assertFalse(refused["ok"])
        self.assertIn("detached; attach again", refused["error"])
        probe.assert_not_called()
        queue.assert_not_called()

    def test_unknown_identity_creates_no_chair(self):
        from convoy.sessions import attach_session
        with patch("convoy.sessions.identify", return_value={"ok": False, "chair": None,
                   "ask": "native session unavailable"}), patch("convoy.sessions.is_temp_root", return_value=False):
            result = attach_session(read_id(self.root), cwd=self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(list_seats(self.root), [])

    def test_ambiguous_thread_name_refuses(self):
        from convoy.sessions import attach_session
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-project")
        with patch("convoy.sessions.is_temp_root", return_value=False):
            result = attach_session("synthetic-project", cwd=self.root)
        self.assertFalse(result["ok"])
        self.assertIn("ambiguous", result["error"])

    def test_mcp_list_is_read_only_and_machine_wide(self):
        from convoy.mcp_http import TOOLS, _call_tool, _WRITE_TOOLS, _PRODUCT_SURFACE
        self.assertIn("list", {t["name"] for t in TOOLS})
        self.assertNotIn("list", _WRITE_TOOLS)
        self.assertNotIn("list", _PRODUCT_SURFACE)
        self.assertIn("skipped", _call_tool(None, "list", {}))

    def test_answered_note_excludes_pending_but_other_author_does_not(self):
        msg = enqueue(self.root, "synthetic-chair", "hello")
        hook(self.root, "note", "answer token=" + msg["token"], author="other-chair")
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)
        hook(self.root, "note", "answer token=" + msg["token"], author="synthetic-chair", verified_by="environment")
        self.assertEqual(pending(self.root, "synthetic-chair"), [])

    def test_same_author_send_can_answer_but_target_subject_cannot(self):
        msg = enqueue(self.root, "synthetic-chair", "hello")
        hook(self.root, "synapse", "send claude", instance_id="synthetic-chair", author=None,
             extra={"reply_tokens": [msg["token"]]})
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)
        hook(self.root, "synapse", "send claude", author="synthetic-chair",
             extra={"reply_tokens": [msg["token"]]}, verified_by="environment")
        self.assertEqual(pending(self.root, "synthetic-chair"), [])

    def test_stop_pulse_for_chair_without_worktree_counts_as_active(self):
        from convoy.activity import neuron_activity
        from convoy.end import end_task
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "synthetic-native-id", "CODEX_THREAD_ID": ""}), \
             patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-chair",
                   "via": "environment", "harness": "claude"}), \
             patch("convoy.end._stop_work", return_value={}):
            result = end_task(root=self.root, hook_payload={"cwd": str(self.root), "turn_id": "synthetic-turn"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(neuron_activity(self.root, procs=[])["neurons"][0]["active"])

    def test_missing_and_old_roots_are_named_without_deletion(self):
        from convoy.index import index_path
        from convoy.thread_list import thread_list
        rows = json.loads(index_path().read_text())
        rows[0]["updated_at"] = "2000-01-01T00:00:00.000000Z"
        rows.append({"convoy_id": "cvy_synthetic_missing", "thread": "missing",
                     "root": str(self.root.parent / "missing"), "updated_at": "2001-01-01T00:00:00.000000Z"})
        index_path().write_text(json.dumps(rows))
        before = index_path().read_bytes()
        with patch("convoy.thread_list.is_temp_root", return_value=False):
            default = thread_list()
            all_rows = thread_list(all_threads=True)
        self.assertEqual(len(default["skipped"]), 2)
        self.assertEqual(all_rows["threads"][0]["pick"], 1)
        self.assertIn("inactive since", all_rows["threads"][0]["reason"])
        self.assertEqual(all_rows["skipped"][0]["reason"], "root gone")
        self.assertEqual(before, index_path().read_bytes())

    def test_cli_pick_repeat_detach_flow_and_no_vendor_probes(self):
        with patch("convoy.thread_list.is_temp_root", return_value=False), \
             patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.Path.cwd", return_value=self.root), \
             patch("convoy.convoy.probe") as vendor:
            rc, raw = self.cli("list", "--json")
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(raw)["threads"][0]["pick"], 1)
            rc, raw = self.cli("attach", read_id(self.root))
            self.assertEqual(rc, 0, raw)
            first = json.loads(raw)
            rc, raw = self.cli("attach", read_id(self.root))
            self.assertTrue(json.loads(raw)["already"])
            rc, raw = self.cli("detach")
            self.assertEqual(rc, 0, raw)
            self.assertTrue(json.loads(raw)["detached"])
            rc, raw = self.cli("attach", read_id(self.root))
            self.assertEqual(json.loads(raw)["chair"], first["chair"])
            self.assertFalse(list_seats(self.root)[0]["detached"])
            vendor.assert_not_called()

    def test_as_harness_cannot_override_process_evidence(self):
        from convoy.sessions import attach_session
        with patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            result = attach_session(read_id(self.root), as_harness="codex", cwd=self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(list_seats(self.root), [])

    def test_new_native_id_cannot_steal_existing_path_chair(self):
        from convoy.sessions import attach_session
        seat(self.root, "claude", "synthetic-old-chair", worktree=str(self.root), resume="synthetic-old-id")
        with patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            result = attach_session(read_id(self.root), cwd=self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(list_seats(self.root)[0]["resume"], "synthetic-old-id")

    def test_detached_pending_stays_on_disk_but_does_not_wake(self):
        from convoy.convoy import update_seat
        from convoy.inbox import inbox_path
        seat(self.root, "claude", "synthetic-chair")
        enqueue(self.root, "synthetic-chair", "pending work")
        raw = inbox_path(self.root, "synthetic-chair").read_bytes()
        update_seat(self.root, "synthetic-chair", detached=True)
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)
        self.assertEqual(raw, inbox_path(self.root, "synthetic-chair").read_bytes())
        update_seat(self.root, "synthetic-chair", detached=False)
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)

    def test_real_send_shape_records_only_reply_token_and_proven_author(self):
        from convoy.synapse import send_one, fake_runner
        from convoy.layer import feed_since
        seat(self.root, "claude", "synthetic-chair")
        seat(self.root, "claude", "synthetic-recipient")
        msg = enqueue(self.root, "synthetic-chair", "hello")
        result = send_one(self.root, "claude", "private reply bytes token=" + msg["token"],
                          instance_id="synthetic-recipient", runner=fake_runner,
                          sender={"chair": "synthetic-chair", "verified_by": "environment"})
        self.assertTrue(result["ok"], result)
        row = feed_since(self.root, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(row["from"], "synthetic-chair")
        self.assertEqual(row["reply_tokens"], [msg["token"]])
        self.assertNotIn("private reply bytes", json.dumps(row))
        self.assertEqual(pending(self.root, "synthetic-chair"), [])


if __name__ == "__main__":
    unittest.main()
