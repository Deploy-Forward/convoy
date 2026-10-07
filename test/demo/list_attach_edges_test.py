"""Attachment edge cases: synthetic identities and isolated thread records only."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from test.demo import list_attach_test as fixtures
from convoy.convoy import bind, list_seats, read_id, seat, update_seat
from convoy.inbox import enqueue, pending
from convoy.layer import hook
try:
    from test.demo.write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401


class ListAttachEdges(unittest.TestCase):
    def setUp(self):
        import os
        fixtures.ListAttach.setUp(self)
        p = patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "synthetic-native-id", "CODEX_THREAD_ID": ""})
        p.start()
        self.addCleanup(p.stop)
    identity = fixtures.ListAttach.identity
    cli = fixtures.ListAttach.cli
    def test_numbers_are_display_only(self):
        from convoy.sessions import attach_session
        result = attach_session("1", cwd=self.root)
        self.assertFalse(result["ok"])
        self.assertIn("pass the cvy_ id from convoy list", result["error"])
        self.assertEqual(list_seats(self.root), [])

    def test_each_block_prints_stable_attach_command(self):
        from convoy.thread_list import thread_list, format_list
        with patch("convoy.thread_list.is_temp_root", return_value=False):
            card = thread_list()
        self.assertIn("convoy attach " + read_id(self.root), format_list(card))

    def test_a_chair_on_another_thread_is_listed_not_refused(self):
        # A session may hold one chair on each of several threads.
        from convoy.sessions import attach_session
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(other, "claude", "synthetic-existing", resume="synthetic-native-id")
        with patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            result = attach_session(read_id(self.root), cwd=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual([x["convoy_id"] for x in result["also_on"]], [read_id(other)])
        self.assertEqual(len(list_seats(self.root)), 1)

    def test_detach_rejects_cwd_identity(self):
        from convoy.sessions import detach_session
        seat(self.root, "claude", "synthetic-victim")
        with patch("convoy.sessions.identify", return_value={"ok": True, "chair": "synthetic-victim", "via": "cwd"}):
            result = detach_session(root=self.root, cwd=self.root)
        self.assertFalse(result["ok"], result)
        self.assertFalse(list_seats(self.root)[0].get("detached", False))

    def test_claimed_reply_does_not_clear_pending(self):
        msg = enqueue(self.root, "synthetic-chair", "hello")
        hook(self.root, "note", "token=" + msg["token"], author="synthetic-chair")
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)
        hook(self.root, "note", "token=" + msg["token"], author="synthetic-chair", verified_by="cwd")
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)
        hook(self.root, "note", "token=" + msg["token"], author="synthetic-chair", verified_by="environment")
        self.assertEqual(pending(self.root, "synthetic-chair"), [])

    def test_detached_pending_count_is_not_zero(self):
        seat(self.root, "claude", "synthetic-chair")
        enqueue(self.root, "synthetic-chair", "hello")
        update_seat(self.root, "synthetic-chair", detached=True)
        self.assertEqual(len(pending(self.root, "synthetic-chair")), 1)

    def test_since_does_not_widen_active_window(self):
        from convoy.thread_list import thread_list
        seat(self.root, "claude", "synthetic-chair")
        with patch("convoy.layer.utc_now", return_value="2026-09-22T00:00:00.000000Z"):
            hook(self.root, "heartbeat", "old pulse", author="synthetic-chair")
        with patch("convoy.thread_list.is_temp_root", return_value=False):
            card = thread_list(since="14d", now=datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertFalse(card["threads"][0]["neurons"][0]["active"])

    def test_bad_mcp_since_is_refusal_card(self):
        from convoy.mcp_http import _call_tool
        result = _call_tool(None, "list", {"since": "not-a-time"})
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_outside_hook_receives_by_session_proof(self):
        from convoy.inbox import hook_pretooluse
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        enqueue(self.root, "synthetic-chair", "outside message")
        outside = self.root.parent / "outside"
        outside.mkdir()
        with patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-chair", "via": "environment"}), \
             patch("convoy.panes._TEST_PROCS", []), \
             patch("convoy.inbox._hook_payload_from_stdin", return_value={}), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            card = hook_pretooluse(outside)
        self.assertIn("outside message", str(card))

    def test_outside_stop_pulses_by_session_proof(self):
        from convoy.end import end_task
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        outside = self.root.parent / "outside"
        outside.mkdir()
        with patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-chair", "via": "environment"}), \
             patch("convoy.panes._TEST_PROCS", []), \
             patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.end._stop_work", return_value={}):
            card = end_task(hook_payload={"cwd": str(outside), "turn_id": "synthetic-turn"})
        self.assertTrue(card["ok"], card)
        self.assertFalse(card.get("skipped"), card)

    def test_join_after_attach_reuses_chair(self):
        from convoy.lifecycle import join
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        with patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-chair", "via": "environment", "harness": "claude"}):
            card = join(self.root, "claude", calling_session=True)
        self.assertTrue(card.get("already"), card)
        self.assertEqual(len(list_seats(self.root)), 1)

    def test_join_on_a_second_thread_seats_the_session_there_too(self):
        from convoy.lifecycle import join
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(other, "claude", "synthetic-existing", resume="synthetic-native-id")
        me = {"ok": True, "chair": None, "native_session": {
            "id": "synthetic-native-id", "harness": "claude", "via": "environment"}}
        with patch("convoy.panes.identify", return_value=me), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            card = join(self.root, "claude", calling_session=True)
        self.assertTrue(card["ok"], card)
        self.assertEqual(len(list_seats(self.root)), 1)

    def test_detached_harness_send_refuses_before_probe(self):
        from convoy.synapse import send_one, fake_runner
        seat(self.root, "claude", "synthetic-chair")
        update_seat(self.root, "synthetic-chair", detached=True)
        with patch("convoy.synapse.probe") as probe:
            card = send_one(self.root, "claude", "hello", runner=fake_runner)
        self.assertIn("detached; attach again", card["error"])
        probe.assert_not_called()

    def test_detached_worktreeless_stop_skips_explicitly(self):
        from convoy.end import end_task
        seat(self.root, "claude", "synthetic-chair", worktree=str(self.root), resume="synthetic-native-id")
        update_seat(self.root, "synthetic-chair", detached=True)
        with patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-chair", "via": "environment"}):
            card = end_task(root=self.root, hook_payload={"cwd": str(self.root), "turn_id": "synthetic-turn"})
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["reason"], "detached; attach again")

    def test_previous_detached_thread_does_not_hide_current_attachment(self):
        from convoy.sessions import proven_session_chair
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-old", resume="synthetic-native-id")
        update_seat(self.root, "synthetic-old", detached=True)
        seat(other, "claude", "synthetic-current", resume="synthetic-native-id")
        def proof(root, **kw):
            return {"ok": True, "chair": "synthetic-old" if root == self.root else "synthetic-current", "via": "environment"}
        with patch("convoy.panes.identify", side_effect=proof), \
             patch("convoy.panes._TEST_PROCS", []), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            found, chair = proven_session_chair(self.root.parent)
        self.assertEqual(found, other)
        self.assertEqual(chair["session_id"], "synthetic-current")

    def test_mcp_join_does_not_borrow_server_session(self):
        import os
        from convoy.mcp_http import _call_tool
        seat(self.root, "claude", "synthetic-server", resume="synthetic-server-id")
        # An MCP join records the conductor its bearer proves; the gate is the legacy flag here,
        # so the conductor is synthetic. The server's own session is never borrowed.
        conductor = {"kind": "conductor", "name": "grok-bot", "via": "bearer", "why": None}
        with write_gate(), \
             patch("convoy.mcp_http._launch_launcher", return_value=conductor), \
             patch("convoy.panes.identify", return_value={"ok": True, "chair": "synthetic-server", "via": "environment"}):
            card = _call_tool(self.root, "join", {"to": "claude", "session_id": "synthetic-remote"})
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["seat"]["session_id"], "synthetic-remote")
        self.assertEqual(card["seat"]["launched_by"], {"kind": "conductor", "name": "grok-bot"})

    def test_low_level_provisioning_join_never_probes_identity(self):
        from convoy.lifecycle import join
        with patch("convoy.panes.identify", side_effect=AssertionError("provisioning must not inspect caller")):
            card = join(self.root, "claude", session_id="synthetic-provisioned")
        self.assertTrue(card["ok"], card)

    def test_cli_explicit_join_provisions_and_launches_new_chair(self):
        import json
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        worktree = self.root.parent / "new-worktree"
        worktree.mkdir()
        with patch("convoy.panes.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.cli.launch_seat") as launch:
            launch.return_value = {"ok": True}
            rc, raw = self.cli("join", "--to", "claude", "--session-id", "synthetic-second", "--worktree", str(worktree), "--launch")
        self.assertEqual(rc, 0, raw)
        self.assertFalse(json.loads(raw).get("already", False))
        self.assertEqual(len(list_seats(self.root)), 2)
        launch.assert_called_once()

    def test_bare_cli_join_still_reuses_self(self):
        import json
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        with patch("convoy.panes.identify", side_effect=lambda root, **kw: self.identity()):
            rc, raw = self.cli("join", "--to", "claude")
        self.assertEqual(rc, 0, raw)
        self.assertTrue(json.loads(raw)["already"])
        self.assertEqual(len(list_seats(self.root)), 1)

    def test_hooks_prefer_attached_identity_over_foreign_cwd(self):
        from convoy.end import end_task
        from convoy.inbox import hook_pretooluse
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-chair", resume="synthetic-native-id")
        seat(other, "claude", "synthetic-foreign", worktree=str(other), resume="synthetic-foreign-id")
        enqueue(self.root, "synthetic-chair", "owned message")
        def proof(root, **kw):
            return {"ok": True, "chair": "synthetic-chair", "via": "environment"} if root == self.root else {"ok": False}
        with patch("convoy.panes.identify", side_effect=proof), \
             patch("convoy.panes._TEST_PROCS", []), \
             patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.inbox._hook_payload_from_stdin", return_value={}), \
             patch("convoy.end._stop_work", return_value={}):
            inbox = hook_pretooluse(other)
            ended = end_task(hook_payload={"cwd": str(other), "turn_id": "synthetic-turn"})
        self.assertIn("owned message", str(inbox))
        self.assertEqual(ended.get("chair"), "synthetic-chair", ended)
        self.assertEqual(ended.get("root"), str(self.root), ended)

    def test_alias_names_the_other_thread_in_also_on(self):
        from convoy.sessions import attach_session
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(other, "claude-code", "synthetic-alias", resume="synthetic-native-id")
        with patch("convoy.sessions.identify", side_effect=lambda root, **kw: self.identity()), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            card = attach_session(read_id(self.root), cwd=self.root)
        self.assertTrue(card["ok"], card)
        self.assertEqual([x["convoy_id"] for x in card["also_on"]], [read_id(other)])

    def test_hook_enumerates_processes_once_for_many_roots(self):
        from convoy.inbox import hook_pretooluse
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-one", resume="synthetic-native-id")
        seat(other, "claude", "synthetic-two", resume="synthetic-two-id")
        with patch("convoy.panes.enumerate_processes", return_value=self.procs) as enumeration, \
             patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.inbox._hook_payload_from_stdin", return_value={}):
            hook_pretooluse(self.root.parent)
        self.assertEqual(enumeration.call_count, 1)

    def test_join_can_provision_other_harness_on_other_thread(self):
        from convoy.lifecycle import join
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(other, "claude", "synthetic-existing", resume="synthetic-native-id")
        me = {"ok": True, "chair": None, "native_session": {
            "id": "synthetic-native-id", "harness": "claude", "via": "environment"}}
        with patch("convoy.panes.identify", return_value=me), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            card = join(self.root, "codex", session_id="synthetic-new", calling_session=True)
        self.assertTrue(card["ok"], card)

    def test_offline_root_is_unknown_not_free_ownership(self):
        from convoy.sessions import attached_elsewhere
        with patch("convoy.sessions.list_threads", return_value=[{
            "root": str(self.root.parent / "offline"), "present": False,
            "convoy_id": "cvy_synthetic_offline"}]), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            with self.assertRaisesRegex(ValueError, "ownership.*unknown"):
                attached_elsewhere(self.root, "claude", "synthetic-native-id")

    def real_hooks(self, cwd, *, enum_error=False):
        import os
        from convoy.end import end_task
        from convoy.inbox import hook_pretooluse
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "synthetic-native-id", "CODEX_THREAD_ID": ""}), \
             patch("convoy.panes._TEST_PID", 21), patch("convoy.panes._TEST_PROCS", None), \
             patch("convoy.panes.enumerate_processes", side_effect=OSError("synthetic failure") if enum_error else None,
                   return_value=self.procs) as enumeration, \
             patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.inbox._hook_payload_from_stdin", return_value={}), \
             patch("convoy.end._stop_work", return_value={}):
            inbox = hook_pretooluse(cwd)
            ended = end_task(hook_payload={"cwd": str(cwd), "turn_id": "synthetic-real-turn"})
        return inbox, ended, enumeration.call_count

    def test_detached_elsewhere_leaves_real_cwd_chair_receiving(self):
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-detached", resume="synthetic-native-id")
        update_seat(self.root, "synthetic-detached", detached=True)
        seat(other, "claude", "synthetic-cwd", worktree=str(other))
        enqueue(other, "synthetic-cwd", "cwd still receives")
        inbox, ended, _ = self.real_hooks(other)
        self.assertIn("cwd still receives", str(inbox))
        self.assertEqual(pending(other, "synthetic-cwd"), [])
        self.assertEqual(ended.get("chair"), "synthetic-cwd", ended)

    def test_matching_cwd_native_id_never_enumerates(self):
        seat(self.root, "claude", "synthetic-cwd", worktree=str(self.root), resume="synthetic-native-id")
        enqueue(self.root, "synthetic-cwd", "cheap hook")
        inbox, ended, count = self.real_hooks(self.root)
        self.assertIn("cheap hook", str(inbox))
        self.assertEqual(ended.get("chair"), "synthetic-cwd", ended)
        self.assertEqual(count, 0)

    def test_enumeration_error_falls_back_to_cwd(self):
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-outside", resume="synthetic-native-id")
        seat(other, "claude", "synthetic-cwd", worktree=str(other))
        enqueue(other, "synthetic-cwd", "fallback receives")
        inbox, ended, count = self.real_hooks(other, enum_error=True)
        self.assertIn("fallback receives", str(inbox))
        self.assertEqual(ended.get("chair"), "synthetic-cwd", ended)
        self.assertEqual(count, 2)

    def test_unrecorded_env_id_skips_enumeration(self):
        seat(self.root, "claude", "synthetic-cwd", worktree=str(self.root), resume="synthetic-other-native")
        enqueue(self.root, "synthetic-cwd", "new vendor session")
        inbox, ended, count = self.real_hooks(self.root)
        self.assertIn("new vendor session", str(inbox))
        self.assertEqual(ended.get("chair"), "synthetic-cwd", ended)
        self.assertEqual(count, 0)

    def test_changed_root_id_skips_ownership_and_explicit_prune_drops_old_row(self):
        from convoy.index import record, prune_threads, list_threads
        from convoy.sessions import attached_elsewhere
        record(self.root, "cvy_synthetic_old", "synthetic-old")
        skipped = []
        with patch("convoy.sessions.is_temp_root", return_value=False), \
             patch("convoy.index.is_temp_root", return_value=False):
            self.assertIsNone(attached_elsewhere(self.root, "claude", "synthetic-native-id", skipped=skipped))
            self.assertIn({"convoy_id": "cvy_synthetic_old", "reason": "id changed"}, skipped)
            self.assertEqual(len(list_threads()), 2)
            result = prune_threads()
        self.assertEqual(result["n_dropped"], 1)
        self.assertEqual(result["dropped"][0]["reason"], "id changed")
        self.assertEqual(len(list_threads()), 1)

    def test_unknown_ownership_names_explicit_prune_remedy(self):
        from convoy.sessions import attached_elsewhere
        with patch("convoy.sessions.list_threads", return_value=[{
            "root": str(self.root.parent / "offline"), "present": False, "convoy_id": "cvy_synthetic_offline"}]), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            with self.assertRaisesRegex(ValueError, "convoy threads --prune"):
                attached_elsewhere(self.root, "claude", "synthetic-native-id")

    def test_outside_enumeration_error_is_explicit_not_silent(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        seat(self.root, "claude", "synthetic-attached", resume="synthetic-native-id")
        enqueue(self.root, "synthetic-attached", "still pending")
        inbox, ended, _ = self.real_hooks(outside, enum_error=True)
        self.assertIn("process table unavailable", str(inbox))
        self.assertFalse(ended["ok"], ended)
        self.assertIn("process table unavailable", ended["error"])
        self.assertEqual(len(pending(self.root, "synthetic-attached")), 1)

    def test_a_session_on_two_threads_ends_its_turn_on_both(self):
        other = self.root.parent / "other"
        other.mkdir()
        bind(other, "synthetic-other")
        seat(self.root, "claude", "synthetic-one", resume="synthetic-native-id")
        seat(other, "claude", "synthetic-two", resume="synthetic-native-id")
        inbox, ended, reads = self.real_hooks(self.root.parent)
        self.assertNotIn("refuse", str(inbox))
        self.assertTrue(ended["ok"], ended)
        self.assertEqual(sorted(c["root"] for c in ended["threads"]),
                         sorted(str(p.resolve()) for p in (self.root, other)))
