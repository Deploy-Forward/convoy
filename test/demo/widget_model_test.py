"""Widget model: folds rail/panes/seats/recent/feed/inbox. No Tk."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, set_github, set_lead
from convoy.inbox import drain, enqueue
from convoy.lifecycle import join, seated_ack
from convoy.widget import build_widget_model, chip_state, idle_threshold_s, _usage_display


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo(remote: str | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q")
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    if remote:
        _git(d, "remote", "add", "origin", remote)
    return d


NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


class WidgetModel(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)

        self.t1 = _git_repo()
        ensure_id(self.t1)
        bind(self.t1, "one")
        set_github(self.t1, False)
        j1 = join(self.t1, "grok", session_id="g-one", worktree=str(self.t1), effort="high")
        seated_ack(self.t1, "g-one", j1["token"])

        self.t2 = _git_repo(remote="https://github.com/acme/api.git")
        ensure_id(self.t2)
        bind(self.t2, "two")
        set_github(self.t2, True)
        join(self.t2, "claude", session_id="c-two", worktree=str(self.t2), model="claude-opus-5")

        self.procs = [
            {"pid": 12, "ppid": 1, "cmdline": "grok --resume unused", "cwd": str(self.t1)},
            {"pid": 13, "ppid": 1, "cmdline": "claude --resume unused", "cwd": None},
        ]

    def _model(self, **kw):
        return build_widget_model(
            [self.t1, self.t2],
            probe_fn=lambda _h: dict(NULL_PROBE),
            **kw,
        )

    def test_two_threads_dots_newest_shape(self):
        card = self._model()
        self.assertTrue(card["ok"])
        self.assertEqual([t["dot"] for t in card["threads"]], ["·1", "·2"])
        self.assertEqual([t["thread"] for t in card["threads"]], ["one", "two"])

    def test_github_no_shows_no_url_yes_shows_real_remote(self):
        card = self._model()
        one, two = card["threads"]
        self.assertFalse(one["repo"]["connected"])
        self.assertIsNone(one["repo"]["url"])
        self.assertEqual(one["repo"]["github"], "no")
        self.assertTrue(two["repo"]["connected"])
        self.assertEqual(two["repo"]["url"], "https://github.com/acme/api.git")

    def test_connected_and_pending_states(self):
        card = self._model()
        one, two = card["threads"]
        self.assertEqual(one["chairs"][0]["state"], "connected")
        self.assertEqual(two["chairs"][0]["state"], "pending")
        self.assertIn("seat", one["chairs"][0]["tune"])
        self.assertIn("swap --seat g-one", one["chairs"][0]["tune"]["swap"])
        self.assertIn("focus --seat", one["chairs"][0]["focus"])

    def test_live_body_only_when_panes_proves_a_process(self):
        procs = [{"pid": 99, "ppid": 1, "cmdline": "grok -d " + str(self.t1), "cwd": str(self.t1)}]
        card = self._model(enumerate_fn=lambda: procs)
        self.assertTrue(card["threads"][0]["chairs"][0]["live_body"])
        card2 = self._model(enumerate_fn=lambda: [])
        self.assertFalse(card2["threads"][0]["chairs"][0]["live_body"])

    def test_usage_null_renders_unknown_never_zero(self):
        self.assertEqual(_usage_display({"usage_remaining": None}), "unknown")
        card = self._model()
        for t in card["threads"]:
            for harness, u in t["usage"].items():
                self.assertEqual(u["display"], "unknown", harness)
                self.assertIsNone(u["usage_remaining"])
                self.assertNotEqual(u["display"], "0")
                self.assertNotEqual(u["usage_remaining"], 0)

    def test_tune_is_command_text_not_applied(self):
        seats = (self.t1 / ".convoy" / "seats.jsonl").read_text(encoding="utf-8")
        card = self._model()
        cmd = card["threads"][0]["chairs"][0]["tune"]["seat"]
        self.assertIn("seat --to grok", cmd)
        self.assertEqual((self.t1 / ".convoy" / "seats.jsonl").read_text(encoding="utf-8"), seats)

    def test_local_storage_is_thread_dot_convoy_not_a_threads_json(self):
        card = self._model()
        one, two = card["threads"]
        self.assertEqual(one["repo"]["local_storage"], str(self.t1 / ".convoy"))
        self.assertEqual(one["repo"]["chip"], "LOCAL")
        self.assertNotIn("threads/", one["repo"]["local_storage"].replace("\\", "/"))
        self.assertFalse(one["repo"]["local_storage"].endswith(".json"))
        self.assertEqual(two["repo"]["chip"], "CONNECTED")
        self.assertIn("threads.json", two["repo"]["index_path"].replace("\\", "/"))
        self.assertEqual(one["header"]["wordmark"], "convoy.bot")
        self.assertIn(" start", one["header"]["plus"])

    def test_usage_session_week_unknown_never_invents_percent(self):
        card = self._model()
        grok = card["threads"][0]["usage"]["grok"]
        self.assertEqual(grok["display_session"], "unknown")
        self.assertEqual(grok["display_week"], "unknown")
        self.assertIsNone(grok["bar_session"])
        self.assertIsNone(grok["bar_week"])
        self.assertEqual(grok["footnote"], "grok reports no meter")

    def test_lead_row_and_seated_count(self):
        set_lead(self.t1, "grok")
        card = self._model()
        chair = card["threads"][0]["chairs"][0]
        self.assertTrue(chair["lead"])
        self.assertEqual(chair["seat_label"], "lead")
        self.assertEqual(card["threads"][0]["seated_n"], 1)
        self.assertEqual(card["threads"][1]["seated_n"], 0)


def _rewrite_feed_ts(root: Path, ts: str) -> None:
    path = root / ".convoy" / "feed.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["ts"] = ts
        rows.append(row)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


class WidgetStaleChip(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "stale")
        set_github(self.root, False)
        self.join = join(self.root, "grok", session_id="g1", worktree=str(self.root))
        seated_ack(self.root, "g1", self.join["token"])
        self.live = [{"pid": 7, "ppid": 1, "cmdline": "grok -d " + str(self.root), "cwd": str(self.root)}]

    def _model(self, now, idle_s=300, procs=None):
        return build_widget_model(
            [self.root],
            probe_fn=lambda _h: dict(NULL_PROBE),
            enumerate_fn=lambda: (self.live if procs is None else procs),
            now_fn=lambda: now,
            idle_s=idle_s,
        )

    def test_chip_state_table(self):
        self.assertEqual(chip_state(body=False, waiting=3, idle_s=999, threshold_s=300), "gone")
        self.assertEqual(chip_state(body=True, waiting=3, idle_s=10, threshold_s=300), "working")
        self.assertEqual(chip_state(body=True, waiting=0, idle_s=999, threshold_s=300), "idle")
        self.assertEqual(chip_state(body=True, waiting=3, idle_s=999, threshold_s=300), "stale")
        self.assertEqual(chip_state(body=True, waiting=3, idle_s=None, threshold_s=300), "stale")

    def test_threshold_is_a_flag_not_a_constant(self):
        with mock.patch.dict(os.environ, { "CONVOY_STALE_IDLE_S": "12" }):
            self.assertEqual(idle_threshold_s(), 12.0)
        self.assertEqual(idle_threshold_s("0"), 0.0)
        self.assertEqual(idle_threshold_s("nope"), 300.0)

    def test_g1_waiting_alive_hook_silent_is_stale_with_red_ring(self):
        # Live case: 2026-09-05 04:56-05:05Z, 3 rows waiting, body alive, hook silent.
        _rewrite_feed_ts(self.root, "2026-09-05T04:56:00.000000Z")
        for i in range(3):
            enqueue(self.root, "g1", "wait-" + str(i))
        card = self._model("2026-09-05T05:05:00.000000Z", idle_s=300)
        chair = card["threads"][0]["chairs"][0]
        self.assertEqual(chair["waiting"], 3)
        self.assertTrue(chair["live_body"])
        self.assertEqual(chair["body"], True)
        self.assertEqual(chair["chip"], "stale")
        self.assertGreaterEqual(chair["idle_s"], 500)
        self.assertTrue(card["threads"][0]["stale_ring"])

    def test_authored_within_threshold_is_working_even_with_waiting(self):
        _rewrite_feed_ts(self.root, "2026-09-05T05:04:00.000000Z")
        enqueue(self.root, "g1", "fresh")
        card = self._model("2026-09-05T05:05:00.000000Z", idle_s=300)
        chair = card["threads"][0]["chairs"][0]
        self.assertEqual(chair["chip"], "working")
        self.assertFalse(card["threads"][0]["stale_ring"])

    def test_live_body_no_waiting_old_tape_is_idle(self):
        _rewrite_feed_ts(self.root, "2026-09-05T04:00:00.000000Z")
        card = self._model("2026-09-05T05:05:00.000000Z", idle_s=300)
        chair = card["threads"][0]["chairs"][0]
        self.assertEqual(chair["waiting"], 0)
        self.assertEqual(chair["chip"], "idle")
        self.assertFalse(card["threads"][0]["stale_ring"])

    def test_no_body_is_gone(self):
        _rewrite_feed_ts(self.root, "2026-09-05T04:56:00.000000Z")
        enqueue(self.root, "g1", "x")
        card = self._model("2026-09-05T05:05:00.000000Z", idle_s=300, procs=[])
        chair = card["threads"][0]["chairs"][0]
        self.assertIsNone(chair["body"])
        self.assertEqual(chair["chip"], "gone")

    def test_drain_marker_counts_as_activity(self):
        _rewrite_feed_ts(self.root, "2026-09-05T04:00:00.000000Z")
        enqueue(self.root, "g1", "x")
        drain(self.root, "g1")
        card = self._model("2026-09-05T04:00:10.000000Z", idle_s=300)
        chair = card["threads"][0]["chairs"][0]
        self.assertIsNotNone(chair["last_drained"])
        self.assertEqual(chair["chip"], "working")
        self.assertEqual(chair["waiting"], 0)


try:
    import tkinter as _tk  # noqa: F401
    _HAS_TK = True
except Exception:
    _HAS_TK = False


@unittest.skipUnless(_HAS_TK, "tkinter missing")
class WidgetWindow(unittest.TestCase):
    def test_builds_without_mainloop(self):
        from convoy.widget import run_widget
        root = _git_repo()
        ensure_id(root)
        bind(root, "w")
        card = run_widget([root], loop=False, probe_fn=lambda _h: dict(NULL_PROBE))
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["threads"], 1)
        self.assertFalse(card.get("loop", True))


if __name__ == "__main__":
    unittest.main()
