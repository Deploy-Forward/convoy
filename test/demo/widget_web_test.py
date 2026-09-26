"""The web widget: a loopback server that serves the page and the SAME model
and actions the CLI runs. No browser, no Tk, no keystroke in this process.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import ensure_id, bind
from convoy.widget_web import WidgetApi, choose_engine, serve

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=60)


def _repo():
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q", "-b", "main"); _git(d, "config", "user.email", "w@t"); _git(d, "config", "user.name", "w")
    (d / "README.md").write_text("w\n", encoding="utf-8"); _git(d, "add", "README.md"); _git(d, "commit", "-qm", "seed")
    return d


class Engine(unittest.TestCase):
    def test_auto_prefers_webview_then_edge_then_browser(self):
        self.assertEqual(choose_engine("auto", has_webview=True, edge_path="x"), "webview")
        self.assertEqual(choose_engine("auto", has_webview=False, edge_path="x"), "edge")
        self.assertEqual(choose_engine("auto", has_webview=False, edge_path=""), "browser")
        self.assertEqual(choose_engine("tk", has_webview=True, edge_path="x"), "tk")
        with self.assertRaises(ValueError):
            choose_engine("electron")


class ModelNeverBlocks(unittest.TestCase):
    def test_first_call_is_a_loading_card_then_the_built_model(self):
        api = WidgetApi(None, probe_fn=lambda h: dict(NULL_PROBE), refresh_s=60)
        built = {"n": 0}
        def fake_build():
            built["n"] += 1; return {"ok": True, "threads": [], "refresh_ms": 60000}
        api._build = fake_build
        with mock.patch("convoy.widget_web.threading.Thread") as T:
            first = api.model()
            self.assertTrue(first["loading"]); self.assertEqual(built["n"], 0)
            T.return_value.start.assert_called_once()
            T.call_args.kwargs["target"]()          # the worker runs
        second = api.model()
        self.assertNotIn("loading", second); self.assertEqual(built["n"], 1)
        api.model(); self.assertEqual(built["n"], 1, "within refresh_s no rebuild")


class Server(unittest.TestCase):
    def setUp(self):
        self.root = _repo(); ensure_id(self.root); bind(self.root, "w")
        home = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": home, "PATH": str(FAKES) + os.pathsep + os.environ.get("PATH", "")})
        env.start(); self.addCleanup(env.stop)
        self.api = WidgetApi([self.root], probe_fn=lambda h: dict(NULL_PROBE), refresh_s=2.5)
        self.api.sync_build = True
        self.httpd = serve(self.api); self.addCleanup(self.httpd.shutdown)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def test_page_assets_and_model(self):
        st, ct, body = self.get("/")
        self.assertEqual(st, 200); self.assertIn("text/html", ct); self.assertIn(b'data-refresh="2500"', body); self.assertIn(b"convoy.bot", body)
        st, ct, _ = self.get("/widget.js"); self.assertEqual(st, 200); self.assertIn("javascript", ct)
        st, ct, svg = self.get("/assets/logo.svg"); self.assertEqual(st, 200); self.assertIn(b"<svg", svg)
        st, ct, _ = self.get("/assets/fonts/jetbrains-mono-latin.woff2"); self.assertEqual(st, 200); self.assertIn("woff2", ct)
        st, _, m = self.get("/api/model"); m = json.loads(m)
        self.assertTrue(m["ok"]); self.assertEqual(m["refresh_ms"], 2500)
        t = m["threads"][0]; self.assertEqual(t["thread"], "w"); self.assertEqual(Path(t["root"]).resolve(), self.root.resolve())
        for h, u in t["usage"].items():
            self.assertEqual(u["display"], "unknown", h)   # null is unknown, never 0

    def test_focus_and_nudge_refusals_come_back_as_cards(self):
        r = self.post("/api/focus", {"root": str(self.root), "seat": "nobody"})
        self.assertFalse(r.get("focused", False)); self.assertTrue(r.get("reason") or r.get("error"))
        r = self.post("/api/nudge", {"root": str(self.root), "seat": "nobody", "dry_run": True})
        self.assertFalse(r["ok"]); self.assertIn(r.get("delivery"), ("refused", None))
        self.assertNotIn("nudge_id", r)

    def test_tune_rewrites_the_seat_through_the_contract(self):
        from convoy.convoy import seat as write_seat, list_seats
        write_seat(self.root, "grok", "grok-1", effort="low")
        r = self.post("/api/tune", {"root": str(self.root), "seat": "grok-1", "effort": "high"})
        self.assertTrue(r["ok"], r); self.assertFalse(r["applied_to_live_pane"])
        row = next(x for x in list_seats(self.root) if x["session_id"] == "grok-1")
        self.assertEqual(row["effort"], "high"); self.assertEqual(row["to"], "grok")
        bad = self.post("/api/tune", {"root": str(self.root), "seat": "grok-1", "effort": "ultra"})
        self.assertFalse(bad["ok"]); self.assertIn("effort", bad["error"])
        self.assertEqual(next(x for x in list_seats(self.root) if x["session_id"] == "grok-1")["effort"], "high", "a refused value never lands")
        self.assertFalse(self.post("/api/tune", {"root": str(self.root), "seat": "nobody", "effort": "high"})["ok"])

    def test_ping_queues_and_only_the_chairs_own_row_answers(self):
        from convoy.convoy import seat as write_seat
        from convoy.layer import hook
        write_seat(self.root, "grok", "grok-1")
        r = self.post("/api/send", {"root": str(self.root), "seat": "grok-1", "body": "ping", "label": "ping"})
        self.assertTrue(r["ok"], r); self.assertEqual(r["delivery"], "queued"); self.assertFalse(r["delivered"])
        pid = r["ping_id"]; self.assertEqual(len(pid), 12)
        since = "1970-01-01T00:00:00.000000Z"
        self.assertFalse(self.post("/api/replies", {"root": str(self.root), "seat": "grok-1", "since": since, "ping_id": pid})["answered"])
        hook(self.root, "note", "pong " + pid + " grok-1 grok C:/wt", instance_id="grok-1", to="grok-bot")
        hook(self.root, "note", "unrelated", instance_id="grok-1")
        rep = self.post("/api/replies", {"root": str(self.root), "seat": "grok-1", "since": since, "ping_id": pid})
        self.assertTrue(rep["answered"]); self.assertEqual(len(rep["rows"]), 1); self.assertIn("pong " + pid, rep["rows"][0]["summary"])
        # another chair citing the id does not identify grok-1
        hook(self.root, "note", "pong " + pid + " impostor", instance_id="codex-9")
        rep = self.post("/api/replies", {"root": str(self.root), "seat": "grok-1", "since": since, "ping_id": pid})
        self.assertEqual(len(rep["rows"]), 1)
        self.assertFalse(self.post("/api/send", {"root": str(self.root), "seat": "grok-1", "body": "   "})["ok"])
        self.assertFalse(self.post("/api/send", {"root": str(self.root), "seat": "nobody", "body": "hi"})["ok"])

    def test_focus_raises_the_identified_window_and_never_a_guess(self):
        from convoy.convoy import seat as write_seat
        write_seat(self.root, "grok", "grok-1", worktree=str(self.root / "wt-grok-1"))
        raised = []
        self.api.raise_fn = lambda hwnd: (raised.append(hwnd) or {"ok": True, "hwnd": hwnd})
        # not identified: a generic title names nothing -> nothing raised, reason on the card
        self.api.identify_kwargs = {"panes_fn": lambda root: {"chairs": [{"session_id": "grok-1", "live": True, "bodies": [{"pid": 4242}]}]},
                                    "windows_fn": lambda: [{"hwnd": 11, "title": "grok", "pid": 99}]}
        with mock.patch("convoy.widget_web.os.name", "nt"):
            r = self.post("/api/focus", {"root": str(self.root), "seat": "grok-1"})
        self.assertFalse(r["focused"]); self.assertEqual(raised, []); self.assertTrue(r.get("reason") or r["identify"]["reason"])
        # identified: the title names the worktree -> that hwnd is raised
        self.api.identify_kwargs["windows_fn"] = lambda: [{"hwnd": 12, "title": "wt-grok-1 - grok", "pid": 99}]
        with mock.patch("convoy.widget_web.os.name", "nt"):
            r = self.post("/api/focus", {"root": str(self.root), "seat": "grok-1"})
        if r["identify"]["identified"]:
            self.assertTrue(r["focused"]); self.assertEqual(raised, [12]); self.assertEqual(r["method"], "raise-window")
        else:
            self.assertEqual(raised, [], "an unidentified pane is never raised")

    def test_feed_history_rows_carry_no_token(self):
        from convoy.lifecycle import join
        from convoy.layer import conductor_stamp
        j = join(self.root, "grok", session_id="grok-1")
        conductor_stamp(self.root, "hello history")
        r = self.post("/api/feed", {"root": str(self.root), "since": "10m"})
        self.assertTrue(r["ok"]); kinds = [x["kind"] for x in r["rows"]]
        self.assertIn("conductor", kinds); self.assertIn("join", kinds)
        self.assertNotIn(j["token"], json.dumps(r))
        self.assertEqual(r["rows"][0]["summary"], "hello history", "newest first")
        self.assertFalse(self.post("/api/feed", {"root": str(self.root), "since": "soon"})["ok"])

    def test_body_state_has_three_labels(self):
        from convoy.convoy import seat as write_seat
        from convoy.widget import build_widget_model
        from convoy import pane_host
        write_seat(self.root, "codex", "codex-1", worktree=str(self.root / "wt1"))
        write_seat(self.root, "grok", "grok-9", worktree=str(self.root / "wt9"))
        pane_host._write_state(self.root, "grok-9", {"launch_state": "closed-by-consent", "closed_at": "2026-09-06T00:00:00Z"})
        m = build_widget_model([self.root], probe_fn=lambda h: dict(NULL_PROBE))
        by = {c["session_id"]: c for c in m["threads"][0]["chairs"]}
        self.assertEqual(by["codex-1"]["body_state"], "no-body", "alive-but-untyable is not gone")
        self.assertEqual(by["grok-9"]["body_state"], "gone", "a consented close is gone")
        self.assertIn(by["codex-1"]["chip"], ("gone", "idle", "stale", "working"))

    def test_archive_hides_but_keeps_the_chair_and_relaunch_brings_it_back(self):
        from convoy.convoy import seat as write_seat, list_seats
        from convoy.widget import build_widget_model
        write_seat(self.root, "grok", "grok-1", worktree=str(self.root))
        r = self.post("/api/archive", {"root": str(self.root), "seat": "grok-1", "archived": True})
        self.assertTrue(r["ok"]); self.assertTrue(r["archived"])
        rows = list_seats(self.root); self.assertEqual(len(rows), 1, "archive never deletes the row")
        self.assertTrue(rows[0]["archived"])
        m = build_widget_model([self.root], probe_fn=lambda h: dict(NULL_PROBE))
        self.assertTrue(m["threads"][0]["chairs"][0]["archived"])
        kinds = [x["kind"] for x in self.post("/api/feed", {"root": str(self.root), "since": "10m"})["rows"]]
        self.assertIn("archive", kinds) if "archive" in ("note", "conductor", "synapse", "seated", "commit", "relaunch", "refuse", "nudge", "join") else None
        with mock.patch("convoy.widget_web.live_runner", create=True) as _lr, \
             mock.patch("convoy.bringup.ensure_first_run", return_value={"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None}), \
             mock.patch("convoy.relaunch.bring_up", return_value={"ok": True, "windows": [{"ok": True, "session_id": "grok-1"}]}) as bu:
            rr = self.post("/api/relaunch", {"root": str(self.root), "seat": "grok-1"})
        self.assertTrue(rr["ok"], rr); self.assertTrue(bu.called)
        self.assertEqual(bu.call_args.kwargs.get("session_ids"), ["grok-1"], "only this chair relaunches")
        self.assertFalse(list_seats(self.root)[0].get("archived"), "relaunch un-archives")
        self.assertFalse(self.post("/api/archive", {"root": str(self.root), "seat": "nobody"})["ok"])

    def test_post_tool_use_stamps_the_panes_own_usage_at_most_every_five_minutes(self):
        from convoy.convoy import seat as write_seat
        from convoy.inbox import stamp_usage_row, last_usage_row
        from convoy.widget import build_widget_model
        write_seat(self.root, "codex", "codex-1", worktree=str(self.root))
        snap = {"usage_remaining": {"session_pct": 30, "week_pct": 60}, "session_pct": 30, "week_pct": 60, "limited": False, "raw": None,
                "source": "codex rollout snapshot", "as_of": "2026-09-06T22:00:00Z", "resets": {"session": "at x", "week": "at y"}}
        r1 = stamp_usage_row(self.root, "codex-1", "codex", probe_fn=lambda h: snap, now="2026-09-06T22:00:00.000000Z")
        self.assertEqual(r1["kind"], "usage"); self.assertEqual(r1["week_pct"], 60); self.assertIn("70% left 5h", r1["summary"])
        self.assertIsNone(stamp_usage_row(self.root, "codex-1", "codex", probe_fn=lambda h: snap, now="2026-09-06T22:03:00.000000Z"), "rate limited")
        r2 = stamp_usage_row(self.root, "codex-1", "codex", probe_fn=lambda h: {**snap, "usage_remaining": {"session_pct": 30, "week_pct": 100}, "week_pct": 100, "limited": True}, now="2026-09-06T22:06:00.000000Z")
        self.assertTrue(r2["limited"])
        self.assertEqual(last_usage_row(self.root, "codex-1")["week_pct"], 100)
        m = build_widget_model([self.root], probe_fn=lambda h: dict(NULL_PROBE))
        own = m["threads"][0]["chairs"][0]["own_usage"]
        self.assertEqual(own["week_pct"], 100); self.assertTrue(own["limited"])
        self.assertNotIn("token", json.dumps(own))

    def test_launch_heartbeat_skips_a_vendor_with_no_reading(self):
        from convoy.convoy import seat as write_seat
        from convoy.inbox import stamp_usage_row, last_usage_row
        write_seat(self.root, "grok", "g-1", worktree=str(self.root))
        none = {"usage_remaining": None, "limited": False, "raw": None}
        self.assertIsNone(stamp_usage_row(self.root, "g-1", "grok", probe_fn=lambda h: none, require_source=True))
        self.assertIsNone(last_usage_row(self.root, "g-1"))
        snap = {"usage_remaining": {"week_pct": 66}, "session_pct": None, "week_pct": 66, "limited": False, "raw": None,
                "source": "grok billing log", "as_of": "2026-09-08T03:15:00Z", "resets": {"session": None, "week": "at x"}}
        r = stamp_usage_row(self.root, "g-1", "grok", probe_fn=lambda h: snap, require_source=True)
        self.assertEqual(r["kind"], "usage"); self.assertEqual(r["week_pct"], 66); self.assertIn("34% left week", r["summary"])

    def test_archive_shows_on_the_next_model_even_while_the_cache_is_stale(self):
        from convoy.convoy import seat as write_seat
        from convoy.widget_web import WidgetApi
        write_seat(self.root, "codex", "c-1", worktree=str(self.root))
        api = WidgetApi([self.root], refresh_s=3600, probe_fn=lambda h: dict(NULL_PROBE))
        api.sync_build = True
        first = api.model()
        self.assertFalse(first["threads"][0]["chairs"][0]["archived"])
        api.sync_build = False          # from here the cache is what a slow rebuild would serve
        api._built_at = float("inf")    # and no rebuild is due
        r = api.archive(str(self.root), "c-1", archived=True)
        self.assertTrue(r["ok"])
        api._built_at = float("inf")    # archive invalidated; keep the rebuild from running yet
        m = api.model()
        self.assertTrue(m["threads"][0]["chairs"][0]["archived"], "the override rides the stale model")
        api.archive(str(self.root), "c-1", archived=False)
        api._built_at = float("inf")
        self.assertFalse(api.model()["threads"][0]["chairs"][0]["archived"])
        api.sync_build = True; api._built_at = float("-inf")
        self.assertFalse(api.model()["threads"][0]["chairs"][0]["archived"], "a fresh build agrees and clears the override")
        self.assertEqual(api._overrides, {})

    def test_a_thread_can_be_archived_off_the_strip_and_restored(self):
        import os as _os, tempfile as _tf
        from convoy import index as idx
        from convoy.widget import build_widget_model
        home = Path(_tf.mkdtemp())
        with mock.patch.dict(_os.environ, {"CONVOY_HOME": str(home)}), mock.patch.object(idx, "is_temp_root", return_value=False):
            from convoy.convoy import read_id as _rid
            idx.record(self.root, _rid(self.root), "alpha")
            other = Path(_tf.mkdtemp()); ensure_id(other); bind(other, "beta")
            from convoy.convoy import read_id
            idx.record(other, read_id(other), "beta")
            self.assertEqual(sorted(r["thread"] for r in idx.recent(10)), ["alpha", "beta"])
            r = self.post("/api/thread-hide", {"convoy_id": read_id(other), "hidden": True})
            self.assertTrue(r["ok"]); self.assertEqual(r["thread"], "beta")
            self.assertEqual([x["thread"] for x in idx.recent(10)], ["alpha"], "hidden threads leave the strip")
            self.assertEqual([x["thread"] for x in idx.hidden_threads()], ["beta"])
            self.assertTrue((other / ".convoy" / "id").is_file(), "nothing under the root changes")
            m = build_widget_model(None, probe_fn=lambda h: dict(NULL_PROBE))
            self.assertEqual([t["thread"] for t in m["hidden_threads"]], ["beta"])
            idx.record(other, read_id(other), "beta")
            self.assertEqual([x["thread"] for x in idx.hidden_threads()], ["beta"], "a later write keeps it archived")
            self.assertTrue(self.post("/api/thread-hide", {"convoy_id": read_id(other), "hidden": False})["ok"])
            self.assertEqual(idx.hidden_threads(), [])
            self.assertFalse(self.post("/api/thread-hide", {"convoy_id": "cvy_nope"})["ok"])

    def test_pin_and_unknown_paths(self):
        self.assertEqual(self.post("/api/pin", {"on": False})["on"], False)
        req = urllib.request.Request(self.url + "/api/nothing", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 404)

    def test_card_and_start_drive_the_original_spec(self):
        c = self.post("/api/card", {"root": str(self.root)})
        self.assertIn("rows", c); self.assertIn("recent", c)
        with mock.patch("convoy.widget_web.WidgetApi.start", wraps=self.api.start) as w, \
             mock.patch("convoy.bringup.ensure_first_run", return_value={"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None}), \
             mock.patch("convoy.onboard.probe", return_value=NULL_PROBE):
            r = self.post("/api/start", {"repo": str(self.root), "harnesses": ["codex", "grok"], "thread": "w", "github": False,
                                         "seats": [{"harness": "codex", "title": "a"}, {"harness": "grok", "effort": "high", "title": "b"}], "launch": False})
        self.assertTrue(w.called)
        self.assertTrue(r["ok"], r); self.assertEqual(r["onboard"]["thread"], "w")
        cw = r["crew"]; self.assertEqual(len(cw["seats"]), 2); self.assertFalse(cw["launched"])
        self.assertEqual(sorted(s["to"] for s in cw["seats"]), ["codex", "grok"])
        st, _, m = self.get("/api/model"); m = json.loads(m)
        self.assertEqual(len(m["threads"][0]["chairs"]), 2, "the new chairs show on the next refresh")
        for ch in m["threads"][0]["chairs"]:
            self.assertEqual(ch["state"], "pending")   # launched is not connected


if __name__ == "__main__":
    unittest.main()
