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
        self.assertEqual(grok["footnote"], "no billing row yet")   # without a billing log row grok is unknown, never 0

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
class UsageIsRemainingNotUsed(unittest.TestCase):
    def test_vendor_used_percent_renders_as_remaining(self):
        from convoy.widget import _usage_block
        b = _usage_block("claude", {"usage_remaining": {"session_pct": 64}, "limited": False, "session_pct": 64, "week_pct": 20})
        self.assertEqual(b["used_session"], 64); self.assertEqual(b["bar_session"], 36); self.assertEqual(b["display_session"], "36%")
        self.assertEqual(b["bar_week"], 80); self.assertEqual(b["display_week"], "80%"); self.assertEqual(b["display"], "36%")
        u = _usage_block("codex", {"usage_remaining": None, "limited": False, "probe_timed_out": True})
        self.assertIsNone(u["bar_session"]); self.assertEqual(u["display_session"], "unknown"); self.assertIn("timed out", u["reason"])


class VendorTabsData(unittest.TestCase):
    def test_resets_and_near_limit_come_from_the_vendor_text(self):
        from convoy.usage import parse_resets, surface
        from convoy.widget import _usage_block
        raw = "Current session: 82% used (Resets in 3h 53m)\nCurrent week (all models): 3% used (Resets in 3d 20h)\n"
        r = parse_resets(raw)
        self.assertEqual(r, {"session": "in 3h 53m", "week": "in 3d 20h"})
        s = surface("claude", {"usage_remaining": {"session_pct": 82, "week_pct": 3}, "limited": False, "raw": raw})
        b = _usage_block("claude", s)
        self.assertEqual(b["used_session"], 82); self.assertEqual(b["bar_session"], 18); self.assertTrue(b["near_limit"])
        self.assertEqual(b["resets"]["session"], "in 3h 53m"); self.assertEqual(b["resets"]["week"], "in 3d 20h")
        self.assertEqual(parse_resets("no reset info here"), {"session": None, "week": None})
        c = _usage_block("codex", surface("codex", {"usage_remaining": None, "limited": False, "raw": None, "probe_timed_out": True}))
        self.assertFalse(c["near_limit"]); self.assertEqual(c["resets"], {"session": None, "week": None}); self.assertIn("timed out", c["reason"])


class CodexRolloutSnapshot(unittest.TestCase):
    def test_newest_rollout_rate_limits_become_session_and_week(self):
        import json as _j, os as _o, tempfile, time
        from convoy.usage import codex_rollout_rate_limits, surface
        from convoy.widget import _usage_block
        home = Path(tempfile.mkdtemp()); d = home / "sessions" / "2026" / "09" / "05"; d.mkdir(parents=True)
        old = d / "rollout-old.jsonl"; old.write_text(_j.dumps({"timestamp": "2026-09-05T01:00:00Z", "payload": {"rate_limits": {"primary": {"used_percent": 10, "window_minutes": 300, "resets_at": 1788669963}, "secondary": {"used_percent": 5, "window_minutes": 10080, "resets_at": 1789199219}}}}) + "\n", encoding="utf-8")
        new = d / "rollout-new.jsonl"; new.write_text("garbage\n" + _j.dumps({"timestamp": "2026-09-05T02:00:00Z", "payload": {"rate_limits": {"primary": {"used_percent": 99.0, "window_minutes": 300, "resets_at": 1788669963}, "secondary": {"used_percent": 31.0, "window_minutes": 10080, "resets_at": 1789199219}}}}) + "\n", encoding="utf-8")
        _o.utime(old, (1000, 1000)); _o.utime(new, (2000, 2000))
        snap = codex_rollout_rate_limits(home, now=2000 + 7200)
        self.assertEqual(snap["session_pct"], 99); self.assertEqual(snap["week_pct"], 31); self.assertEqual(snap["age_s"], 7200)
        self.assertEqual(snap["source"], "codex rollout snapshot"); self.assertTrue(snap["resets"]["session"].startswith("at 2026-"))
        b = _usage_block("codex", surface("codex", snap))
        self.assertEqual(b["bar_session"], 1); self.assertEqual(b["bar_week"], 69); self.assertTrue(b["near_limit"]); self.assertIn("2 h old", b["reason"])
        self.assertIsNone(codex_rollout_rate_limits(Path(tempfile.mkdtemp())))


class GrokBillingLog(unittest.TestCase):
    def test_newest_billing_row_is_the_weekly_meter(self):
        import json as _j, tempfile
        from convoy.usage import grok_unified_billing, surface
        from convoy.widget import _usage_block
        home = Path(tempfile.mkdtemp()); (home / "logs").mkdir()
        rows = [
            {"ts": "2026-09-05T01:00:00.000Z", "msg": "billing: fetched credits config", "ctx": {"config": {"creditUsagePercent": 40.0, "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY", "end": "2026-09-11T06:55:23+00:00"}}, "subscriptionTier": "SuperGrok"}},
            {"ts": "2026-09-05T02:00:00.000Z", "msg": "something else", "ctx": {}},
            {"ts": "2026-09-06T20:00:00.000Z", "msg": "billing: fetched credits config", "ctx": {"config": {"creditUsagePercent": 66.0, "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-09-04T06:55:23+00:00", "end": "2026-09-11T06:55:23+00:00"}}, "subscriptionTier": "SuperGrok"}},
        ]
        (home / "logs" / "unified.jsonl").write_text("\n".join(_j.dumps(r) for r in rows) + "\ngarbage\n", encoding="utf-8")
        import calendar, time
        now = calendar.timegm(time.strptime("2026-09-06T22:00:00", "%Y-%m-%dT%H:%M:%S"))
        snap = grok_unified_billing(home, now=now)
        self.assertEqual(snap["week_pct"], 66); self.assertIsNone(snap["session_pct"]); self.assertEqual(snap["tier"], "SuperGrok")
        self.assertEqual(snap["age_s"], 7200); self.assertTrue(snap["resets"]["week"].startswith("at 2026-09-11"))
        b = _usage_block("grok", surface("grok", snap))
        self.assertEqual(b["bar_week"], 34); self.assertIsNone(b["bar_session"]); self.assertFalse(b["near_limit"]); self.assertIn("2 h old", b["reason"])
        self.assertIsNone(grok_unified_billing(Path(tempfile.mkdtemp())))
        full = dict(snap); full["week_pct"] = 100
        self.assertTrue(_usage_block("grok", surface("grok", {**full, "limited": True}))["limited"])


class WidgetWindow(unittest.TestCase):
    def test_builds_without_mainloop(self):
        # Tk must not live in this interpreter: destroy() + later GC on a
        # non-main thread aborts the whole suite (Tcl_AsyncDelete, live 2026-09-05).
        home = Path(tempfile.mkdtemp())
        root = _git_repo()
        ensure_id(root)
        bind(root, "w")
        src = str(Path(__file__).resolve().parents[2] / "src")
        code = (
            "import json, os, sys\n"
            "sys.path.insert(0, " + repr(src) + ")\n"
            "os.environ['CONVOY_HOME'] = " + repr(str(home)) + "\n"
            "from convoy.widget import run_widget\n"
            "card = run_widget([" + repr(str(root)) + "], loop=False, "
            "probe_fn=lambda _h: {'usage_remaining': None, 'limited': False, 'raw': None})\n"
            "print(json.dumps(card))\n"
        )
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        blob = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 and ("widget requires" in blob or "TclError" in blob or "no display" in blob.lower()):
            self.skipTest("tkinter/display unavailable")
        self.assertEqual(r.returncode, 0, blob)
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")]
        self.assertTrue(lines, blob)
        card = json.loads(lines[-1])
        if not card.get("ok") and "widget requires" in str(card.get("error") or ""):
            self.skipTest("tkinter/display unavailable")
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["threads"], 1)
        self.assertFalse(card.get("loop", True))


if __name__ == "__main__":
    unittest.main()
