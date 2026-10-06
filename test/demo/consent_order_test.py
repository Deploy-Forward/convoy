"""A verb refuses before it spends the person's consent.

A consent is one-time. Two verbs spent it and then failed: `close` consumed the grant and
then hit the close request already on disk ("File exists"), and `nudge` consumed the grant
and then found its pane-host writer cannot type on this OS. Each verb now checks what can
fail first, and spends the consent only on a step that can happen. The consent card also
names the transport the nudge will really use.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import consent as consent_module
from convoy.consent import grant_consent, request_consent
from convoy.convoy import bind, ensure_id
from convoy.layer import feed_since
from convoy.lifecycle import join
from convoy.nudge import nudge_seat
from convoy.pane_host import close_managed_pane, close_request_path, host_state_path

EPOCH = "1970-01-01T00:00:00.000000Z"


def _status(root, request_id):
    return consent_module._latest(root)[request_id]["status"]


class ConsentIsSpentLast(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        ensure_id(self.root)
        bind(self.root, "consent-order")
        self.worktree = Path(tempfile.mkdtemp())
        join(self.root, "codex", session_id="chair", worktree=str(self.worktree))
        state = host_state_path(self.root, "chair")
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"session_id": "chair", "status": "running", "host_pid": 101,
                                     "child_pid": 202, "incarnation": 1}), encoding="utf-8")

    def grant(self, action, **scope):
        waiting = request_consent(self.root, action, session_id="chair", to="codex",
                                  worktree=str(self.worktree), **scope)
        request_id = waiting["consent_request"]["request_id"]
        return request_id, grant_consent(self.root, request_id)["consent"]

    def test_second_close_reports_already_requested_without_consuming_consent(self):
        with mock.patch("convoy.pane_host.pid_alive", return_value=True):
            _, first = self.grant("close-chair")
            self.assertTrue(close_managed_pane(self.root, "chair", consent=first)["ok"])
            request_id, second = self.grant("close-chair")
            card = close_managed_pane(self.root, "chair", consent=second)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["state"], "close-requested")
        self.assertTrue(card["already"])
        self.assertEqual(_status(self.root, request_id), "granted")

    def test_close_on_dead_host_refuses_before_consent(self):
        request_id, token = self.grant("close-chair")
        with mock.patch("convoy.pane_host.pid_alive", return_value=False):
            asked = close_managed_pane(self.root, "chair")
            card = close_managed_pane(self.root, "chair", consent=token)
        for c in (asked, card):
            self.assertFalse(c["ok"], c)
            self.assertEqual(c["state"], "host-exited", c)
            self.assertNotIn("consent_request", c)
        self.assertEqual(_status(self.root, request_id), "granted")
        self.assertFalse(close_request_path(self.root, "chair").exists())

    def pane_host_nudge(self, **kw):
        record = {"session_id": "chair", "status": "running", "host_pid": 101, "child_pid": 202}
        return nudge_seat(self.root, "chair", keys="Enter", host_records_fn=lambda _r: [record],
                          pid_alive_fn=lambda _p: True, ack_fn=lambda *_a: {"ok": True}, **kw)

    def test_unsupported_adapter_refuses_before_consuming_consent(self):
        pane = "pane-host host_pid=101 child_pid=202"
        request_id, token = self.grant("nudge-pane", keys="Enter", pane=pane)
        with mock.patch("convoy.nudge.console_injection_supported", return_value=False):
            card = self.pane_host_nudge(consent=token)
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["delivery"], "refused")
        self.assertIn("cannot type", card["reason"])
        self.assertEqual(_status(self.root, request_id), "granted")
        self.assertEqual([r for r in feed_since(self.root, EPOCH) if r.get("kind") in ("nudge", "nudge-result")], [])

    def test_consent_card_transport_equals_dispatch_transport(self):
        with mock.patch("convoy.nudge.console_injection_supported", return_value=True):
            card = self.pane_host_nudge(target="%3")
        self.assertEqual(card["adapter"], "pane-host")
        self.assertEqual(card.get("state"), "awaiting-user-consent", card)
        self.assertTrue(card["consent_request"]["scope"]["pane"].startswith("pane-host"), card["consent_request"])


if __name__ == "__main__":
    unittest.main()
