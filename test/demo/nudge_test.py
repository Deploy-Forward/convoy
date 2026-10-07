"""nudge --seat: proven pane + consent + exact keys; delivery=nudged never delivered."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.consent import grant_consent
from convoy.convoy import bind, ensure_id, seat
from convoy.mcp_http import TOOLS, _WRITE_TOOLS, call_tool
from convoy.nudge import WAKE_EVIDENCE, identify_target, nudge_seat
from convoy.pane_host import host_state_path, nudge_request_path
try:
    from test.demo.write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401


def _panes(sid, bodies, *, duplicate=False, live=True, live_reason="matched 1 body/bodies"):
    def fn(_root):
        return {
            "ok": True,
            "chairs": [{
                "session_id": sid,
                "bodies": bodies,
                "duplicate": duplicate,
                "live": live,
                "live_reason": live_reason,
            }],
            "unassigned": [],
        }
    return fn


def _windows(*rows):
    return lambda: list(rows)


class NudgeSeat(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "nudge-t")
        self.wt = Path(tempfile.mkdtemp()) / "demo-wt-g2"
        self.wt.mkdir()
        seat(self.root, "grok", "g2", worktree=str(self.wt), title="g2")
        self.body = {"pid": 3001, "via": "worktree", "exe": "grok"}
        self.env = mock.patch.dict(os.environ, {"TMUX": ""}, clear=False)
        self.env.start()
        os.environ.pop("TMUX", None)
        self.addCleanup(self.env.stop)

    def test_unknown_seat_is_not_nudged(self):
        card = nudge_seat(self.root, "nope", dry_run=True, panes_fn=_panes("g2", [self.body]),
                          windows_fn=_windows(), leader_fn=lambda: {"available": False})
        self.assertFalse(card["ok"])
        self.assertFalse(card.get("identified"))
        self.assertIsNone(card["delivery"])
        self.assertFalse(card["delivered"])
        self.assertIn("unknown seat", card["reason"])

    def test_no_live_body_refuses(self):
        card = identify_target(
            self.root, "g2",
            panes_fn=_panes("g2", [], live=False, live_reason="no grok process is running"),
            windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
            leader_fn=lambda: {"available": False},
        )
        self.assertFalse(card["identified"])
        self.assertIn("no grok process", card["reason"])

    def test_duplicate_bodies_refuse(self):
        card = identify_target(
            self.root, "g2",
            panes_fn=_panes("g2", [self.body, {"pid": 2, "via": "worktree", "exe": "grok"}], duplicate=True),
            windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
            leader_fn=lambda: {"available": False},
        )
        self.assertFalse(card["identified"])
        self.assertIn("duplicate", card["reason"])

    def test_generic_grok_title_is_never_identity(self):
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = identify_target(
                self.root, "g2",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows(
                    {"hwnd": 11, "pid": 5001, "title": "grok"},
                    {"hwnd": 12, "pid": 5001, "title": "grok"},
                ),
                leader_fn=lambda: {"available": False},
            )
        self.assertFalse(card["identified"])
        self.assertIn("no unique title", card["reason"])
        self.assertIsNone(card["delivery"])

    def test_prompt_titled_grok_pane_is_not_proven(self):
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = identify_target(
                self.root, "g2",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({
                    "hwnd": 1001, "pid": 5001,
                    "title": "? - List Windows Terminal windows and titles. - grok",
                }),
                leader_fn=lambda: {"available": False},
            )
        self.assertFalse(card["identified"])
        self.assertIn("prompt-titled", card["reason"])

    def test_short_seat_title_inside_a_prompt_is_not_identity(self):
        # A live dry-run of g2 matched because the WT title
        # was the grok tool description "Dry-run nudge identity for g2".
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = identify_target(
                self.root, "g2",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({
                    "hwnd": 1001, "pid": 5001,
                    "title": "Dry-run nudge identity for g2… - grok",
                }),
                leader_fn=lambda: {"available": False},
            )
        self.assertFalse(card["identified"], card)

    def test_unique_worktree_title_identifies_and_dry_run_sends_nothing(self):
        sends = []
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                self.root, "g2", dry_run=True,
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 1002, "pid": 5001, "title": self.wt.name}),
                leader_fn=lambda: {"available": False},
                send_fn=lambda w, k: sends.append((w, k)) or {"ok": True},
            )
        self.assertTrue(card["ok"])
        self.assertTrue(card["identified"])
        self.assertEqual(card["adapter"], "wt-sendinput")
        self.assertEqual(card["pane"]["hwnd"], 1002)
        self.assertIsNone(card["delivery"])
        self.assertFalse(card["delivered"])
        self.assertEqual(sends, [])

    def test_live_without_keys_refuses(self):
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                self.root, "g2",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
                leader_fn=lambda: {"available": False},
            )
        self.assertFalse(card["ok"])
        self.assertIn("--keys", card["reason"])

    def test_live_without_consent_asks_and_names_pane_and_keys(self):
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                self.root, "g2", keys="Enter",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 99, "pid": 9, "title": self.wt.name}),
                leader_fn=lambda: {"available": False},
                send_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no send before consent")),
            )
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "awaiting-user-consent")
        prompt = card["consent_request"]["prompt"]
        self.assertIn("HWND 99", prompt)
        self.assertIn("Enter", prompt)
        self.assertIn(self.wt.name, prompt)
        self.assertIsNone(card["delivery"])
        self.assertFalse(card["delivered"])

    def test_tmux_send_keys_after_consent_is_nudged_never_delivered(self):
        calls = []

        def runner(argv):
            calls.append(list(argv))
            return {"ok": True, "returncode": 0, "argv": argv}

        with mock.patch.dict(os.environ, {"TMUX": "1,2,3"}):
            waiting = nudge_seat(
                self.root, "g2", keys="Enter", target="%5",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows(),
                leader_fn=lambda: {"available": False},
                runner=runner,
            )
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(
                self.root, "g2", keys="Enter", target="%5", consent=token,
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows(),
                leader_fn=lambda: {"available": False},
                runner=runner,
            )
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "nudged")
        self.assertFalse(card["delivered"])
        self.assertEqual(card["host"], "tmux")
        self.assertEqual(calls, [["tmux", "send-keys", "-t", "%5", "Enter"]])

    def test_wrong_keys_do_not_consume_or_send(self):
        sends = []
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(
                self.root, "g2", keys="Enter",
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
                leader_fn=lambda: {"available": False},
            )
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(
                self.root, "g2", keys="hello", consent=token,
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
                leader_fn=lambda: {"available": False},
                send_fn=lambda w, k: sends.append((w, k)) or {"ok": True},
            )
        self.assertFalse(card["ok"])
        self.assertIn("scope mismatch", card["reason"])
        self.assertEqual(sends, [])
        self.assertIsNone(card["delivery"])

    def test_codex_queue_adapter_when_resume_is_on_the_seat(self):
        c2_wt = Path(tempfile.mkdtemp()) / "demo-wt-c2"
        c2_wt.mkdir()
        seat(self.root, "codex", "c2", worktree=str(c2_wt), title="c2", resume="01codex-demo")
        queued = []

        def queue_fn(thread, body):
            queued.append((thread, body))
            return {"ok": True, "runner": "codex-queue", "delivery": "native-queued"}

        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(
                self.root, "c2", keys="wake",
                panes_fn=_panes("c2", [{"pid": 3, "via": "worktree", "exe": "codex"}]),
                windows_fn=_windows({"hwnd": 7, "pid": 9, "title": c2_wt.name}),
                queue_fn=queue_fn,
            )
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(
                self.root, "c2", keys="wake", consent=token,
                panes_fn=_panes("c2", [{"pid": 3, "via": "worktree", "exe": "codex"}]),
                windows_fn=_windows({"hwnd": 7, "pid": 9, "title": c2_wt.name}),
                queue_fn=queue_fn,
            )
        self.assertEqual(card["adapter"], "codex-queue")
        self.assertEqual(card["delivery"], "nudged")
        self.assertFalse(card["delivered"])
        # the typed text carries the nudge_id (WIDGET.md rule); the feed row is the record
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][0], "01codex-demo")
        self.assertEqual(queued[0][1], "wake nudge=" + card["nudge_id"])

    def test_grok_leader_up_refuses_keystroke_rather_than_steal(self):
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                self.root, "g2", keys="Enter", dry_run=True,
                panes_fn=_panes("g2", [self.body]),
                windows_fn=_windows({"hwnd": 1, "pid": 9, "title": self.wt.name}),
                leader_fn=lambda: {"available": True, "raw": "leader pid 1"},
                send_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no keystroke when leader is up")),
            )
        self.assertEqual(card["adapter"], "grok-acp-unshipped")
        self.assertIn("steal", card["reason"])
        self.assertIsNone(card["delivery"])

    def test_nudge_is_write_gated_and_public_call_sends_nothing(self):
        self.assertIn("nudge", _WRITE_TOOLS)
        self.assertTrue(any(t["name"] == "nudge" for t in TOOLS))
        card = call_tool(self.root, "nudge", {"seat": "g2", "keys": "Enter"})
        # tools/call short-circuits write tools before call_tool; call_tool itself
        # still refuses when the gate is closed.
        self.assertFalse(card["ok"])
        self.assertIn("convoy conductor mint", card["error"])
        self.assertFalse(card["delivered"])
        self.assertIsNone(card["delivery"])

    def test_evidence_notes_are_command_observed_ts(self):
        for row in WAKE_EVIDENCE:
            self.assertIn("command", row)
            self.assertIn("observed", row)
            self.assertIn("ts", row)


class PaneHostNudge(unittest.TestCase):
    """`panes` can never place a claude body (no process
    cwd on this OS, and a busy pane's title is its own prompt), so the
    window-title path above refuses every claude neuron at its prompt. The
    pane host already proved this exact body at launch; a running host
    record wins outright and needs no window at all."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "nudge-host-t")
        self.wt = Path(tempfile.mkdtemp()) / "demo-wt-host"
        self.wt.mkdir()
        seat(self.root, "claude", "host-fixture", worktree=str(self.wt), title="host-fixture")
        self.no_body = _panes("host-fixture", [], live=False, live_reason="no claude process could be placed")

    def _write_host_state(self, *, status="running", host_pid=4242, child_pid=5252, terminal_session="term-1"):
        path = host_state_path(self.root, "host-fixture")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "session_id": "host-fixture", "status": status,
            "host_pid": host_pid, "child_pid": child_pid,
            "terminal_session": terminal_session,
        }), encoding="utf-8")
        return path

    def test_running_pane_host_record_identifies_even_when_panes_and_windows_find_nothing(self):
        self._write_host_state()
        card = identify_target(
            self.root, "host-fixture",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        self.assertTrue(card["identified"], card)
        self.assertEqual(card["adapter"], "pane-host")
        self.assertEqual(card["pane"], {"host_pid": 4242, "child_pid": 5252, "terminal_session": "term-1"})

    def test_no_running_host_record_falls_back_to_the_old_refusal(self):
        card = identify_target(
            self.root, "host-fixture",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        self.assertFalse(card["identified"])
        self.assertNotEqual(card.get("adapter"), "pane-host")

    def test_dead_host_pid_is_not_a_running_record(self):
        self._write_host_state()
        card = identify_target(
            self.root, "host-fixture",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: False,
        )
        self.assertFalse(card["identified"])
        self.assertNotEqual(card.get("adapter"), "pane-host")

    def test_exited_host_status_is_not_a_running_record(self):
        self._write_host_state(status="child-exited")
        card = identify_target(
            self.root, "host-fixture",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        self.assertFalse(card["identified"])

    def test_pane_host_route_without_consent_asks_and_names_it(self):
        self._write_host_state()
        card = nudge_seat(
            self.root, "host-fixture", keys="drain your inbox and continue",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "awaiting-user-consent")
        prompt = card["consent_request"]["prompt"]
        self.assertIn("pane-host", prompt)
        self.assertIn("4242", prompt)
        self.assertIn("drain your inbox and continue", prompt)

    def test_pane_host_route_types_with_consent_and_reports_typed_at(self):
        self._write_host_state()
        seen = []

        def fake_ack(root, session_id, nudge_id):
            seen.append((str(root), session_id, nudge_id))
            return {"ok": True, "typed_at": "2026-09-21T16:20:00Z", "error": None}

        waiting = nudge_seat(
            self.root, "host-fixture", keys="drain your inbox and continue",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
        card = nudge_seat(
            self.root, "host-fixture", keys="drain your inbox and continue", consent=token,
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True, ack_fn=fake_ack,
        )
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "nudged")
        self.assertFalse(card["delivered"])
        self.assertEqual(card["typed_at"], "2026-09-21T16:20:00Z")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], "host-fixture")
        self.assertEqual(seen[0][2], card["nudge_id"])
        written = json.loads(nudge_request_path(self.root, "host-fixture").read_text(encoding="utf-8-sig"))
        self.assertEqual(written["nudge_id"], card["nudge_id"])
        self.assertIn("nudge=" + card["nudge_id"], written["text"])

    def test_pane_host_route_reports_failure_when_host_never_acks(self):
        self._write_host_state()

        def fake_ack(root, session_id, nudge_id):
            return {"ok": False, "typed_at": None, "error": "pane host has not consumed the nudge request yet (timeout)"}

        waiting = nudge_seat(
            self.root, "host-fixture", keys="drain your inbox and continue",
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True,
        )
        token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
        card = nudge_seat(
            self.root, "host-fixture", keys="drain your inbox and continue", consent=token,
            panes_fn=self.no_body, windows_fn=_windows(), leader_fn=lambda: {"available": False},
            pid_alive_fn=lambda _pid: True, ack_fn=fake_ack,
        )
        self.assertFalse(card["ok"])
        self.assertEqual(card["delivery"], "failed")
        self.assertIn("timeout", card["reason"])
        self.assertIsNone(card["typed_at"])


if __name__ == "__main__":
    unittest.main()
