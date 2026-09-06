"""The widget's '+' flow IS the original specification, walked end to end.

Marco's spec (2026-09-04, recorded in plugin/convoy/skills/convoy-wizard/SKILL.md
and docs/HAPPY_PATH.md): "@convoy allows for a connect GitHub, yes/no; if yes
which repository; selected repository; then select which harnesses are
available on either local or cloud; how many neurons desired; model selection
with effort. Terminal launches with the thread, then they all connect!" plus
usage remaining per harness.

This test drives the widget's own HTTP API (the same calls the page makes)
against a REAL git repo with the window spawn, first-run home writes, vendor
probes and the clone injected. Every spec clause is one assertion block.
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
from convoy.widget_web import WidgetApi, serve

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"
SPEC = Path(__file__).resolve().parents[2] / "plugin" / "convoy" / "skills" / "convoy-wizard" / "SKILL.md"


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=60)


def _repo():
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q", "-b", "main"); _git(d, "config", "user.email", "s@t"); _git(d, "config", "user.name", "s")
    (d / "README.md").write_text("spec\n", encoding="utf-8"); _git(d, "add", "README.md"); _git(d, "commit", "-qm", "seed")
    return d


class WidgetWalksTheOriginalSpec(unittest.TestCase):
    def setUp(self):
        self.root = _repo(); ensure_id(self.root); bind(self.root, "spec")
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": tempfile.mkdtemp(), "PATH": str(FAKES) + os.pathsep + os.environ.get("PATH", "")})
        env.start(); self.addCleanup(env.stop)
        self.spawns = []
        def fake_spawn(argv, cwd=None, rect=None, **_k):
            self.spawns.append({"argv": list(argv), "cwd": cwd}); return {"ok": True, "pid": 4242, "argv": list(argv)}
        for target, kw in (
            ("convoy.bringup.live_runner", {"new": fake_spawn}),
            ("convoy.bringup.ensure_first_run", {"return_value": {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False, "settings_home": None}}),
            ("convoy.onboard.probe", {"return_value": NULL_PROBE}),
            ("convoy.card.probe", {"return_value": NULL_PROBE}),
        ):
            p = mock.patch(target, **kw); p.start(); self.addCleanup(p.stop)
        self.api = WidgetApi([self.root], probe_fn=lambda h: dict(NULL_PROBE), refresh_s=1); self.api.sync_build = True
        self.httpd = serve(self.api); self.addCleanup(self.httpd.shutdown)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=60) as r:
            return json.loads(r.read())

    def test_the_spec_is_on_disk_and_says_what_the_flow_does(self):
        text = SPEC.read_text(encoding="utf-8")
        for clause in ("GitHub?", "repos", "installed", "cloud", "`N` neurons", "model", "effort", "usage_remaining", "crew", "await_seated"):
            self.assertIn(clause, text, clause)

    def test_plus_flow_walks_every_clause(self):
        # "select which harnesses are available on either local or cloud ... usage remaining"
        card = self.post("/api/card", {"root": str(self.root)})
        self.assertTrue(card["ok"], card)
        rows = {r["harness"]: r for r in card["rows"]}
        self.assertTrue(rows, "the card lists harnesses")
        for name, r in rows.items():
            self.assertIn("installed", r); self.assertIn("where", r); self.assertIn("local", r["where"], name)
            self.assertIn("usage_remaining", r)                         # per harness, null when unknown
            self.assertTrue(r["usage_remaining"] is None or isinstance(r["usage_remaining"], (int, float, dict)))
        self.assertIn("cloud", rows["claude"]["where"], "cloud offered where the vendor evidences an interactive attach (claude)")
        self.assertNotIn("cloud", rows["grok"]["where"])
        self.assertIn("recent", card, "recent threads for the picker")

        # "connect GitHub, yes/no; if yes which repository": GitHub yes with a URL is cloned once
        with mock.patch("convoy.onboard.clone", side_effect=lambda url, dest, runner=None: {"ok": True, "url": url, "cloned": True, "path": str(self.root)}), \
             mock.patch("convoy.onboard.checkout_path_for", return_value=self.root):
            gh = self.post("/api/start", {"repo": "https://github.com/acme/api.git", "harnesses": ["grok"], "thread": "spec", "github": True, "seats": [], "launch": False})
        self.assertTrue(gh["ok"], gh); self.assertEqual(gh["onboard"]["github"], "yes")
        self.assertEqual(gh["onboard"]["repo"]["url"], "https://github.com/acme/api.git")

        # "how many neurons desired; model selection with effort": N=3 across harnesses, where local, then launch
        seats = [{"harness": "codex", "title": "builder", "model": "gpt-5.6", "where": "local"},
                 {"harness": "grok", "title": "scout", "effort": "high", "where": "local"},
                 {"harness": "claude", "title": "checker", "effort": "high", "where": "local"}]
        r = self.post("/api/start", {"repo": str(self.root), "harnesses": ["codex", "grok", "claude"], "thread": "spec", "github": False, "seats": seats, "launch": True})
        self.assertTrue(r["ok"], r)
        cw = r["crew"]; self.assertEqual(len(cw["seats"]), 3)
        by = {s["title"]: s for s in cw["seats"]}
        self.assertEqual(by["builder"]["model"], "gpt-5.6"); self.assertEqual(by["scout"]["effort"], "high")
        self.assertEqual(len({s["worktree"] for s in cw["seats"]}), 3, "one worktree per local seat")

        # "Terminal launches with the thread": ONE window, launched read from the runner
        self.assertTrue(cw["launched"]); self.assertEqual(len(self.spawns), 1)
        # "... then they all connect": pending until each chair echoes its own join token
        self.assertEqual(sorted(cw["seated"]["pending"]), sorted(s["session_id"] for s in cw["seats"]))
        tokens = {}
        for line in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("kind") == "join" and row.get("token"):
                tokens[row["instance_id"]] = row["token"]
        from convoy.lifecycle import seated_ack
        from convoy.crew import await_seated
        for s in cw["seats"]:
            self.assertTrue(seated_ack(self.root, s["session_id"], token=tokens[s["session_id"]])["ok"])
        done = await_seated(self.root, [s["session_id"] for s in cw["seats"]], timeout=0)
        self.assertEqual(sorted(done["connected"]), sorted(s["session_id"] for s in cw["seats"]))

        # the widget reads the new thread state back: three chairs, all connected, none invented
        m = self.get("/api/model"); t = m["threads"][0]
        self.assertEqual(t["thread"], "spec"); self.assertEqual(len(t["chairs"]), 3); self.assertEqual(t["seated_n"], 3)
        self.assertNotIn("token", json.dumps(m))

    def test_a_cloud_seat_where_the_vendor_evidences_it_is_a_chair_with_no_pane(self):
        r = self.post("/api/start", {"repo": str(self.root), "harnesses": ["claude"], "thread": "spec", "github": False,
                                     "seats": [{"harness": "claude", "title": "cloudy", "where": "cloud"}], "launch": True})
        self.assertTrue(r["ok"], r)
        s = r["crew"]["seats"][0]; self.assertEqual(s["where"], "cloud"); self.assertIsNone(s.get("worktree"))
        self.assertEqual(len(self.spawns), 0, "a cloud chair opens no local pane")
        bad = self.post("/api/start", {"repo": str(self.root), "harnesses": ["grok"], "thread": "spec", "github": False,
                                       "seats": [{"harness": "grok", "title": "nope", "where": "cloud"}], "launch": False})
        self.assertFalse(bad["ok"]); self.assertIn("cloud", json.dumps(bad).lower())


if __name__ == "__main__":
    unittest.main()
