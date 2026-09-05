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
