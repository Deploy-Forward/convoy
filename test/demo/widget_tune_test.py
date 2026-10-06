"""Widget tune changes model and effort and nothing else on the seat row.

Tune used to rewrite the whole row through `seat()`, which writes a fixed key set: a no-op
tune dropped launched_by, detached, harness_pid and vendor_session_id, and a legacy row with
a broad worktree could not be tuned at all. Tune now merges only the fields it changes.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat
from convoy.widget_web import WidgetApi


def _row(root, sid):
    return [s for s in list_seats(root) if s.get("session_id") == sid][-1]


class WidgetTuneKeepsTheRow(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "tune")
        self.api = WidgetApi([self.root], probe_fn=lambda h: {}, refresh_s=3600)

    def test_tune_preserves_unrelated_seat_fields(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())), effort="low")
        update_seat(self.root, "chair", launched_by="conductor-x", detached=True, harness_pid=4242,
                    vendor_session_id="vs-123")
        before = _row(self.root, "chair")
        out = self.api.tune(str(self.root), "chair", effort="high")
        self.assertTrue(out["ok"], out)
        after = _row(self.root, "chair")
        for key, value in before.items():
            if key not in ("effort", "effort_applied"):
                self.assertEqual(after.get(key), value, key)
        self.assertEqual(after["effort"], "high")

    def test_tune_noop_appends_nothing(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        seats = self.root / ".convoy" / "seats.jsonl"
        lines = seats.read_text(encoding="utf-8").splitlines()
        out = self.api.tune(str(self.root), "chair")
        self.assertTrue(out["ok"], out)
        self.assertEqual(seats.read_text(encoding="utf-8").splitlines(), lines)

    def test_tune_allowed_on_legacy_broad_worktree_row(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        legacy = {**_row(self.root, "chair"), "worktree": str(Path.home())}
        with (self.root / ".convoy" / "seats.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        out = self.api.tune(str(self.root), "chair", effort="high")
        self.assertTrue(out["ok"], out)
        self.assertEqual(_row(self.root, "chair")["effort"], "high")
        self.assertEqual(_row(self.root, "chair")["worktree"], str(Path.home()))

    def test_tune_refused_value_never_lands(self):
        seat(self.root, "grok", "chair", worktree=str(Path(tempfile.mkdtemp())), effort="low")
        out = self.api.tune(str(self.root), "chair", effort="ultra")
        self.assertFalse(out["ok"], out)
        self.assertIn("effort", out["error"])
        self.assertEqual(_row(self.root, "chair")["effort"], "low")

    def test_model_only_tune_recomputes_effort_applied(self):
        # A model-id harness carries effort inside the model id, so whether the effort
        # is applied depends on the model: changing only the model must recompute it.
        catalog = ["gpt-5", "gpt-5-high", "sonnet-4"]
        with mock.patch("convoy.cursor_models.read_catalog", return_value=catalog):
            seat(self.root, "cursor-agent", "chair", worktree=str(Path(tempfile.mkdtemp())),
                 model="gpt-5", effort="high")
            self.assertTrue(_row(self.root, "chair")["effort_applied"])
            out = self.api.tune(str(self.root), "chair", model="sonnet-4")
        self.assertTrue(out["ok"], out)
        after = _row(self.root, "chair")
        self.assertEqual(after["model"], "sonnet-4")
        self.assertFalse(after["effort_applied"])

    def test_model_only_update_seat_recomputes_effort_applied(self):
        catalog = ["gpt-5", "gpt-5-high", "sonnet-4"]
        with mock.patch("convoy.cursor_models.read_catalog", return_value=catalog):
            seat(self.root, "cursor-agent", "chair", worktree=str(Path(tempfile.mkdtemp())),
                 model="sonnet-4", effort="high")
            self.assertFalse(_row(self.root, "chair")["effort_applied"])
            update_seat(self.root, "chair", model="gpt-5")
        self.assertTrue(_row(self.root, "chair")["effort_applied"])


if __name__ == "__main__":
    unittest.main()
