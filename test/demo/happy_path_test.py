"""The Convoy happy path, walked once in command truth.

Marco's storyboard (2026-09-04) has six frames and a thread rail. This test is
that storyboard as executable proof: every frame is the shipped CLI (`main`),
driven the way a person in a terminal drives it, against a REAL git repo. The
only things injected are what a CI box cannot have: the vendor usage probe, the
window spawn, and first-run home writes. Minting, joining, the seated acks,
delegation, the feed and the rail are the shipped code.

  1 LAUNCH      the harness that onboards first conducts: `.convoy/lead` names
                it and the onboard card says so. Never set twice.
  2 CONNECT     `onboard --to claude --to codex --to grok --thread demo`
                binds ONE thread: convoy_id, thread, root on the card.
  3 POINT       `--checkout-root <path> --github no`: local folder, same memory.
  4 SUMMON      `crew --seat codex --seat grok,effort=high --launch`: one
                worktree per seat, two chairs joined, ONE window.
  5 SEATED      `await-seated` reports connected only after each neuron echoes
                the token its own join minted; pending before.
  6 DELEGATE    `send --to <chair> "..."` comes back with a delivery word;
                `feed --since 10m` (relative, not ISO) shows synapse + seats;
                `stamp "tests drafted"` lands as the last stamp.
  RAIL          `rail` is the strip under the panes: feed count, seats
                connected, usage per harness (null is unknown, never 0), last
                stamp. It reads only the thread, so ANY neuron rehydrates from
                it: the same rail from a chair's worktree says the same thing.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cli
from convoy.layer import parse_since

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True,
                   capture_output=True, text=True, timeout=60)


def _real_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "happy@convoy.test")
    _git(d, "config", "user.name", "convoy happy path")
    (d / "README.md").write_text("happy\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "commit", "-qm", "seed")
    return d


class ParseSince(unittest.TestCase):
    NOW = "2026-09-04T12:00:00.000000Z"

    def test_relative_durations_resolve_against_now(self):
        self.assertEqual(parse_since("10m", now=self.NOW), "2026-09-04T11:50:00.000000Z")
        self.assertEqual(parse_since("2h", now=self.NOW), "2026-09-04T10:00:00.000000Z")
        self.assertEqual(parse_since("1d", now=self.NOW), "2026-09-03T12:00:00.000000Z")
        self.assertEqual(parse_since("45s", now=self.NOW), "2026-09-04T11:59:15.000000Z")

    def test_iso_passes_through_untouched(self):
        self.assertEqual(parse_since("2026-09-01T00:00:00Z", now=self.NOW), "2026-09-01T00:00:00Z")

    def test_garbage_is_refused_not_guessed(self):
        for bad in ("", "  ", "10", "m", "ten minutes", "-5m", "1.5h"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_since(bad, now=self.NOW)


class HappyPath(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = _real_repo()
        self.spawns = []
        path = str(FAKES) + os.pathsep + os.environ.get("PATH", "")
        env = mock.patch.dict(os.environ, {"PATH": path})
        env.start()
        self.addCleanup(env.stop)

        def fake_spawn(argv, cwd=None, rect=None, **_k):
            self.spawns.append({"argv": list(argv), "cwd": cwd})
            return {"ok": True, "pid": 4242, "argv": list(argv)}

        for target, kw in (
            ("convoy.onboard.probe", {"return_value": NULL_PROBE}),
            ("convoy.rail.probe", {"return_value": NULL_PROBE}),
            ("convoy.cli.live_runner", {"new": fake_spawn}),
            ("convoy.bringup.ensure_first_run", {"return_value": {
                "ok": True, "prepared": False, "wrote": False, "settings": None,
                "home_written": False, "settings_home": None}}),
        ):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv, root=None, expect=0):
        """One terminal command. Returns the JSON card it printed."""
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["--root", str(root or self.root), *argv])
        text = out.getvalue().strip().splitlines()[-1]
        card = json.loads(text)
        self.assertEqual(code, expect, (argv, card))
        return card

    def _join_tokens(self):
        """Tokens read off the thread on disk, as the neuron in its pane holds
        them; never from a response."""
        out = {}
        for line in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "join":
                sid = row.get("instance_id") or row.get("to")
                tok = row.get("token") or (row.get("extra") or {}).get("token")
                if not tok:
                    for part in str(row.get("summary") or "").split():
                        if part.startswith("token="):
                            tok = part.split("=", 1)[1]
                if sid and tok:
                    out[sid] = tok
        return out

    def test_six_frames_and_the_rail(self):
        # 1 LAUNCH + 2 CONNECT + 3 POINT (local folder, no GitHub)
        ob = self.run_cli("onboard", "--to", "claude", "--to", "codex", "--to", "grok",
                          "--thread", "demo", "--checkout-root", str(self.root), "--github", "no")
        self.assertTrue(ob["ok"])
        self.assertEqual(ob["thread"], "demo")
        self.assertTrue(str(ob["convoy_id"]).startswith("cvy_"), ob["convoy_id"])
        self.assertEqual(Path(ob["root"]).resolve(), self.root.resolve())
        self.assertEqual(ob["github"], "no")
        # whoever launched first conducts: the first harness named, recorded once
        self.assertEqual(ob["lead"], {"harness": "claude", "set": True})
        self.assertEqual((self.root / ".convoy" / "lead").read_text(encoding="utf-8").strip(), "claude")
        again = self.run_cli("onboard", "--to", "codex", "--thread", "demo")
        self.assertEqual(again["lead"], {"harness": "claude", "set": False}, "a second onboard never steals lead")
        self.assertEqual(self.run_cli("lead")["lead"], "claude")

        # 4 SUMMON: one worktree per seat, two chairs, one window
        cw = self.run_cli("crew", "--seat", "codex", "--seat", "grok,effort=high", "--thread", "demo", "--launch")
        self.assertTrue(cw["ok"], cw)
        chairs = cw["seats"] if "seats" in cw else cw["chairs"]
        sids = [c["session_id"] for c in chairs]
        self.assertEqual(len(sids), 2)
        harness_by_sid = {c["session_id"]: c["harness"] if "harness" in c else c["to"] for c in chairs}
        self.assertEqual(sorted(harness_by_sid.values()), ["codex", "grok"])
        wts = {c["worktree"] for c in chairs}
        self.assertEqual(len(wts), 2, "one worktree per seat")
        for wt in wts:
            self.assertTrue((Path(wt) / ".git").exists(), wt)
        self.assertEqual(len(self.spawns), 1, "ONE window")
        grok = next(c for c in chairs if harness_by_sid[c["session_id"]] == "grok")
        self.assertEqual(grok.get("effort"), "high")

        # 5 SEATED: pending until each neuron echoes its own minted token
        before = self.run_cli("await-seated", *sum((["--seat", s] for s in sids), []), "--timeout", "0", expect=1)
        self.assertEqual(sorted(before["pending"]), sorted(sids))
        tokens = self._join_tokens()
        self.assertEqual(sorted(tokens), sorted(sids))
        for sid in sids:
            self.assertTrue(self.run_cli("seated", "--seat", sid, "--token", tokens[sid])["ok"])
        after = self.run_cli("await-seated", *sum((["--seat", s] for s in sids), []), "--timeout", "0")
        self.assertEqual(sorted(after["connected"]), sorted(sids))
        self.assertIn("waited_s", after)

        # 6 DELEGATE
        codex_sid = next(s for s in sids if harness_by_sid[s] == "codex")
        grok_sid = next(s for s in sids if harness_by_sid[s] == "grok")
        s1 = self.run_cli("send", "--to", codex_sid, "draft tests for retry planner")
        self.assertTrue(s1["ok"], s1)
        self.assertIn(s1["delivery"], ("queued", "native-queued", "recorded", "executed"))
        s2 = self.run_cli("send", "--to", grok_sid, "audit retry paths")
        self.assertTrue(s2["ok"], s2)
        st = self.run_cli("stamp", "tests drafted")
        self.assertEqual(st["kind"], "conductor")

        fd = self.run_cli("feed", "--since", "10m")
        kinds = {r["kind"] for r in fd["events"]}
        self.assertTrue({"join", "seated", "synapse", "conductor"} <= kinds, kinds)
        self.assertEqual(fd["since"], "10m")
        self.assertTrue(fd["since_iso"].endswith("Z"))

        # RAIL under the panes
        rail = self.run_cli("rail")
        self.assertTrue(rail["ok"], rail)
        self.assertEqual(rail["thread"], "demo")
        self.assertEqual(rail["convoy_id"], ob["convoy_id"])
        self.assertEqual(rail["lead"], "claude")
        self.assertEqual(rail["feed"]["since"], "10m")
        self.assertEqual(rail["feed"]["events"], len(fd["events"]))
        self.assertEqual(rail["seats"], {"total": 2, "connected": 2, "pending": 0, "stale": 0})
        self.assertEqual(sorted(rail["usage"]), ["codex", "grok"])
        for h, u in rail["usage"].items():
            self.assertIsNone(u["usage_remaining"], h)   # unknown is null, never 0
            self.assertFalse(u["limited"], h)
        self.assertEqual(rail["last_stamp"]["summary"], "tests drafted")
        self.assertTrue(rail["last_stamp"]["ts"].endswith("Z"))
        self.assertNotIn("token", json.dumps(rail))

        # any neuron rehydrates from the thread: the rail from a chair's
        # worktree is the same rail
        from_chair = self.run_cli("rail", root=grok["worktree"])
        self.assertEqual(from_chair["convoy_id"], rail["convoy_id"])
        self.assertEqual(from_chair["seats"], rail["seats"])
        self.assertEqual(from_chair["last_stamp"], rail["last_stamp"])

    def test_relaunch_after_the_panes_die_carries_the_timeline(self):
        self.run_cli("onboard", "--to", "claude", "--to", "codex", "--to", "grok", "--thread", "demo",
                     "--checkout-root", str(self.root), "--github", "no")
        cw = self.run_cli("crew", "--seat", "codex", "--seat", "grok", "--thread", "demo", "--launch")
        sids = [c["session_id"] for c in cw["seats"]]
        tokens = self._join_tokens()
        for sid in sids:
            self.run_cli("seated", "--seat", sid, "--token", tokens[sid])
        self.run_cli("send", "--to", sids[0], "draft tests")          # left undrained
        self.run_cli("hook", "note", "half done", "--instance-id", sids[1])
        self.spawns.clear()

        # the laptop died here. Dry first: nothing spawned, nothing written.
        dry = self.run_cli("relaunch", "--dry-run")
        self.assertEqual(len(self.spawns), 0)
        self.assertFalse(dry["launched"])
        inbox_before = (self.root / ".convoy" / "inbox" / (sids[0] + ".jsonl")).read_text(encoding="utf-8")

        live = self.run_cli("relaunch", "--thread", "demo")
        self.assertTrue(live["launched"], live)
        self.assertEqual(len(self.spawns), 1, "one window again")
        by = {c["session_id"]: c for c in live["chairs"]}
        self.assertEqual(by[sids[0]]["unread"], 1)
        self.assertEqual(by[sids[0]]["worktree"], cw["seats"][0]["worktree"])
        self.assertIsNotNone(by[sids[1]]["last_seen"])
        self.assertTrue(by[sids[1]]["last_seen"] <= live["relaunched_at"])
        self.assertTrue(by[sids[1]]["relaunch_note"].endswith(sids[1] + ".jsonl"))
        # old acks do not count: every chair is pending until it acks again
        self.assertEqual(sorted(live["seated"]["pending"]), sorted(sids))
        self.assertEqual(live["seated"]["after"], live["relaunched_at"])
        after = (self.root / ".convoy" / "inbox" / (sids[0] + ".jsonl")).read_text(encoding="utf-8")
        self.assertIn("Relaunched at", after.replace(inbox_before, "", 1))
        self.assertIn("feed --since " + by[sids[0]]["last_seen"], after)
        # a fresh ack citing the SAME join token proves the chair is back
        self.run_cli("seated", "--seat", sids[0], "--token", tokens[sids[0]])
        again = self.run_cli("await-seated", "--seat", sids[0], "--timeout", "0")
        self.assertEqual(again["connected"], [sids[0]])
        kinds = [r["kind"] for r in self.run_cli("feed", "--since", "10m")["events"]]
        self.assertIn("relaunch", kinds)

    def test_one_torn_feed_line_never_takes_the_bus_down(self):
        self.run_cli("onboard", "--to", "claude", "--thread", "demo", "--checkout-root", str(self.root), "--github", "no")
        self.run_cli("stamp", "before")
        with (self.root / ".convoy" / "feed.jsonl").open("ab") as f:
            f.write(b'-happy-path"}\r\n')                       # a tail of a torn PowerShell >> append
        self.run_cli("stamp", "after")
        fd = self.run_cli("feed", "--since", "10m")
        kinds = [r["kind"] for r in fd["events"]]
        self.assertEqual(kinds.count("conductor"), 2, kinds)        # before, after: the tear cost nothing
        bad = [r for r in fd["events"] if r["kind"] == "malformed"]
        self.assertEqual(len(bad), 1)
        self.assertIn("line", bad[0]["summary"])
        self.assertIsNone(bad[0]["ts"])
        rail = self.run_cli("rail")
        self.assertEqual(rail["last_stamp"]["summary"], "after")

    def test_idle_wake_is_vendor_native_stop_gate_and_background_wait(self):
        from convoy.identity import grok_inbox_hook_document
        from convoy.inbox import hook_pretooluse, wait_for_pending
        doc = grok_inbox_hook_document("convoy inbox --hook-pretooluse")
        self.assertIn("Stop", doc["hooks"], "grok Stop gate keeps a neuron working while rows wait")
        self.assertEqual(doc["hooks"]["Stop"], doc["hooks"]["PreToolUse"])

        self.run_cli("onboard", "--to", "claude", "--thread", "demo", "--checkout-root", str(self.root), "--github", "no")
        cw = self.run_cli("crew", "--seat", "grok", "--thread", "demo", "--launch")
        sid = cw["seats"][0]["session_id"]; wt = cw["seats"][0]["worktree"]

        # the pane's hook resolves its thread root the way a live pane does
        # (pointer or CONVOY_ROOT); the fake spawn wrote no pointer here.
        env = mock.patch.dict(os.environ, {"CONVOY_ROOT": str(self.root)}); env.start(); self.addCleanup(env.stop)
        # nothing waiting: Stop returns the safe no-op, never a block
        with mock.patch("convoy.inbox._hook_event_from_stdin", return_value="Stop"):
            self.assertEqual(hook_pretooluse(wt), {})

        # background wait: the arriving row ends the wait; the row is NOT drained by the waiter
        ticks = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0])
        def fake_sleep(_s):
            if not (self.root / ".convoy" / "inbox" / (sid + ".jsonl")).exists():
                self.run_cli("send", "--to", sid, "draft tests")
        card = wait_for_pending(self.root, sid, timeout=10, interval=1, clock=lambda: next(ticks), sleep=fake_sleep)
        self.assertTrue(card["ok"]); self.assertEqual(card["n"], 1); self.assertFalse(card["timed_out"])
        self.assertEqual(self.run_cli("inbox", "--seat", sid)["n"], 1, "wait never drains")

        # Stop with a row waiting: block the stop, the row is the reason
        with mock.patch("convoy.inbox._hook_event_from_stdin", return_value="Stop"):
            out = hook_pretooluse(wt)
        self.assertEqual(out["decision"], "block")
        self.assertIn("draft tests", out["reason"])
        self.assertEqual(self.run_cli("inbox", "--seat", sid)["n"], 0, "the Stop hook drained it")

        # timeout is honest
        t2 = iter([0.0, 0.0, 5.0, 5.0])
        card = wait_for_pending(self.root, sid, timeout=4, interval=1, clock=lambda: next(t2), sleep=lambda s: None)
        self.assertTrue(card["timed_out"]); self.assertEqual(card["n"], 0)

    def test_rail_on_an_unbound_root_says_so(self):
        card = self.run_cli("rail", expect=1)
        self.assertFalse(card["ok"])
        self.assertIsNone(card["convoy_id"])
        self.assertIn("no thread", card["error"])


if __name__ == "__main__":
    unittest.main()


class RailOnTheWire(unittest.TestCase):
    """The same rail a chat sees over MCP, public (no gate), never a token."""

    def setUp(self):
        import threading
        from convoy.convoy import ensure_id
        from convoy.lifecycle import join, seated_ack
        from convoy.layer import conductor_stamp
        from convoy.mcp_http import make_server
        self.root = _real_repo()
        ensure_id(self.root)
        joined = join(self.root, "grok", session_id="grok-1", title="scout")
        seated_ack(self.root, "grok-1", token=joined["token"])
        join(self.root, "codex", session_id="codex-1", title="builder")
        conductor_stamp(self.root, "tests drafted")
        self.token = joined["token"]
        env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch("convoy.mcp_http.probe", return_value=NULL_PROBE)
        p.start(); self.addCleanup(p.stop)
        httpd = make_server(self.root, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        self.url = "http://127.0.0.1:%s/mcp" % httpd.server_address[1]

    def rpc(self, method, params=None):
        import urllib.request
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    def test_rail_is_a_public_read_verb_and_carries_no_token(self):
        names = {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertIn("rail", names)
        res = self.rpc("tools/call", {"name": "rail", "arguments": {}})["result"]
        card = res.get("structuredContent") or json.loads(res["content"][0]["text"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["seats"], {"total": 2, "connected": 1, "pending": 1, "stale": 0})
        self.assertEqual(card["last_stamp"]["summary"], "tests drafted")
        self.assertEqual(sorted(card["usage"]), ["codex", "grok"])
        self.assertIsNone(card["usage"]["codex"]["usage_remaining"])
        self.assertNotIn(self.token, json.dumps(res))

    def test_feed_takes_a_window_on_the_wire(self):
        res = self.rpc("tools/call", {"name": "feed", "arguments": {"since": "10m"}})["result"]
        card = res.get("structuredContent") or json.loads(res["content"][0]["text"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["since"], "10m")
        self.assertTrue(card["since_iso"].endswith("Z"))
        self.assertTrue({"join", "seated", "conductor"} <= {r["kind"] for r in card["events"]})
        self.assertNotIn(self.token, json.dumps(res), "public feed drops tokens")
        bad = self.rpc("tools/call", {"name": "feed", "arguments": {"since": "ten minutes"}})["result"]
        card = bad.get("structuredContent") or json.loads(bad["content"][0]["text"])
        self.assertFalse(card["ok"])
