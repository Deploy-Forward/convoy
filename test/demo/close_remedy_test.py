"""Close names the remedy that fits the chair.

Every chair without a running pane host got "Focus the exited pane and press Ctrl+D". For a
session someone attached by hand that is wrong: Ctrl+D ends that person's own harness. An
attached live chair now gets "run `convoy detach` in that session, then close its terminal",
with its pid when Convoy knows it. A host that exited keeps the Ctrl+D remedy.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, update_seat
from convoy.lifecycle import join
from convoy.pane_host import close_managed_pane, host_state_path


class CloseRemedy(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        ensure_id(self.root)
        bind(self.root, "remedy")
        join(self.root, "claude", session_id="chair", worktree=str(Path(tempfile.mkdtemp())))

    def test_close_attached_chair_remedy_names_detach_and_pid(self):
        update_seat(self.root, "chair", attached_at="2026-10-01T00:00:00.000000Z", detached=False, harness_pid=4242)
        card = close_managed_pane(self.root, "chair")
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "attached-session")
        self.assertIn("convoy", card["remedy"])
        self.assertIn("detach", card["remedy"])
        self.assertIn("4242", card["remedy"])
        self.assertNotIn("Ctrl+D", card["remedy"])
        self.assertNotIn("consent_request", card)

    def test_close_exited_host_keeps_ctrl_d_remedy(self):
        state = host_state_path(self.root, "chair")
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"session_id": "chair", "status": "exited", "host_pid": 101}), encoding="utf-8")
        card = close_managed_pane(self.root, "chair")
        self.assertFalse(card["ok"])
        self.assertEqual(card["state"], "manual-close-required")
        self.assertIn("Ctrl+D", card["remedy"])


if __name__ == "__main__":
    unittest.main()
