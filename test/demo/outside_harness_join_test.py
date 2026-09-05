"""The OUTSIDE-HARNESS JOIN path, walked in command truth.

A claude/codex/grok session that a person started OUTSIDE Convoy (its cwd is
in no worktree, it holds no chair) finds a thread and receives work without
stealing anyone's pane. Every step is the shipped CLI (`main`) or the shipped
MCP server, against REAL git repos; only the process table, the vendor usage
probe, the window spawn and first-run home writes are injected.

  1 WHOAMI     from a foreign cwd: ok:false, chair:null, an ask. Never an
               invented chair.
  2 FIND       `threads` lists present threads; `start` with no repo is a
               picker from recent(): present, non-temp roots only, never
               auto-picked (ok:false, ask:pick).
  3 ATTACH     `attach` on the chosen root; `join --to codex` mints a chair,
               a boot prompt and a token (nothing spawned).
  4 SEND       `send --to <chair>` queues: delivery=queued, delivered=false.
  5 RECEIVE    the neuron drains its own inbox, acks citing the inbox token,
               then `seated --token <join token>`; `await-seated` says
               connected only after that.
  6 MCP        the same on a gated loopback server: a where=cloud chair
               (claude only, per harness_effort.json) gets NO pane from
               bring_up and proves connected by its own seated ack. The
               ungated public server can neither join nor seat.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cli
from convoy.convoy import ensure_id, list_seats
from convoy.mcp_http import make_server

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None,
             "home_written": False, "settings_home": None}


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True,
                   capture_output=True, text=True, timeout=60)


def _real_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "outside@convoy.test")
    _git(d, "config", "user.name", "convoy outside join")
    (d / "README.md").write_text("outside\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "commit", "-qm", "seed")
    return d


def _join_tokens(root: Path) -> dict:
    """Tokens off the thread on disk, as the neuron holds them from its boot
    prompt; never from a response card."""
    out = {}
    for line in (root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "join":
            sid = row.get("instance_id") or row.get("to")
            tok = row.get("token") or (row.get("extra") or {}).get("token")
            if sid and tok:
                out[sid] = tok
    return out


class OutsideHarnessJoin(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        # The thread root is minted in the REAL temp dir first; then the temp
        # dir is moved so recent() sees it as a non-temp root, and a second
        # thread minted under the moved temp dir is the residue recent() must
        # exclude. Restored on cleanup.
        self.root = _real_repo()
        self.foreign = Path(tempfile.mkdtemp(prefix="outside-cwd-"))   # no git, no .convoy
        moved_tmp = tempfile.mkdtemp(prefix="moved-tmp-")
        home = tempfile.mkdtemp(prefix="convoy-home-")
        self.spawns = []
        path = str(FAKES) + os.pathsep + os.environ.get("PATH", "")
        for p in (
            mock.patch.dict(os.environ, {"PATH": path, "CONVOY_HOME": home}),
            mock.patch("tempfile.gettempdir", return_value=moved_tmp),
            mock.patch("convoy.panes._TEST_PROCS", []),          # no CIM, no ancestry: an outside body
            mock.patch("convoy.onboard.probe", return_value=NULL_PROBE),
            mock.patch("convoy.convoy.probe", return_value=NULL_PROBE),
            mock.patch("convoy.mcp_http.probe", return_value=NULL_PROBE),
            mock.patch("convoy.cli.live_runner", new=self._fake_spawn),
            mock.patch("convoy.mcp_http.live_runner", new=self._fake_spawn),
            mock.patch("convoy.bringup.ensure_first_run", return_value=FIRST_RUN),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.temp_root = _real_repo()                              # under moved_tmp: residue

    def _fake_spawn(self, argv, cwd=None, rect=None, **_k):
        self.spawns.append({"argv": list(argv), "cwd": cwd})
        return {"ok": True, "pid": 4242, "argv": list(argv)}

    def run_cli(self, *argv, root, expect=0):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["--root", str(root), *argv])
        card = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(code, expect, (argv, card))
        return card

    def _bind_two_threads(self):
        ob = self.run_cli("onboard", "--to", "claude", "--to", "codex", "--thread", "demo",
                          "--checkout-root", str(self.root), "--github", "no", root=self.root)
        self.assertTrue(ob["ok"], ob)
        tmp = self.run_cli("onboard", "--to", "claude", "--thread", "residue",
                           "--checkout-root", str(self.temp_root), "--github", "no", root=self.temp_root)
        self.assertTrue(tmp["ok"], tmp)
        return ob

    def test_outside_session_finds_a_thread_and_receives_work_without_stealing(self):
        ob = self._bind_two_threads()

        # 1 WHOAMI from a foreign cwd: no chair is ever invented.
        with mock.patch("os.getcwd", return_value=str(self.foreign)):
            nowhere = self.run_cli("whoami", root=self.foreign, expect=1)
            self.assertFalse(nowhere["ok"]); self.assertIsNone(nowhere["chair"])
            self.assertIn("join", nowhere["ask"]); self.assertFalse(nowhere["conflict"])
            here = self.run_cli("whoami", root=self.root, expect=1)
            self.assertFalse(here["ok"]); self.assertIsNone(here["chair"]); self.assertIsNone(here["via"])
            self.assertEqual(here["root_thread"], "demo"); self.assertIsNone(here["cwd_thread"])
            self.assertIn("join", here["ask"])

            # 2 FIND: the index lists both; the picker offers only the non-temp one, and picks nothing.
            th = self.run_cli("threads", root=self.foreign)
            roots = {Path(r["root"]).resolve() for r in th["threads"] if r["present"]}
            self.assertTrue({self.root.resolve(), self.temp_root.resolve()} <= roots, th)
            pick = self.run_cli("start", root=self.foreign, expect=1)
            self.assertFalse(pick["ok"]); self.assertEqual(pick["ask"], "pick")
            self.assertFalse(pick["bound"]); self.assertFalse(pick["brought_up"])
            offered = [Path(r["root"]).resolve() for r in pick["threads"]]
            self.assertIn(self.root.resolve(), offered)
            self.assertNotIn(self.temp_root.resolve(), offered, "temp roots never reach the picker")
            self.assertEqual(next(r for r in pick["threads"] if Path(r["root"]).resolve() == self.root.resolve())["title"], "demo")
            self.assertIsNone(self.run_cli("id", root=self.foreign).get("convoy_id"), "picking wrote nothing to the foreign cwd")

            # 3 ATTACH the chosen root, then join a codex chair: prompt + token, no spawn.
            at = self.run_cli("attach", root=self.root)
            self.assertTrue(at["ok"]); self.assertEqual(at["convoy_id"], ob["convoy_id"]); self.assertEqual(at["thread"], "demo")
            jn = self.run_cli("join", "--to", "codex", root=self.root)
            self.assertTrue(jn["ok"], jn)
            sid = jn["seat"]["session_id"]
            self.assertEqual(jn["seat"]["to"], "codex"); self.assertEqual(jn["seat"]["where"], "local")
            self.assertIn(jn["token"], jn["seat"]["boot_prompt"])
            self.assertIn("seated --seat " + sid, jn["seat"]["boot_prompt"])
            self.assertEqual(_join_tokens(self.root)[sid], jn["token"])
            self.assertEqual(self.spawns, [], "join alone spawns nothing")
            self.assertEqual(self.run_cli("await-seated", "--seat", sid, "--timeout", "0", root=self.root, expect=1)["pending"], [sid])

            # 4 SEND into that chair: queued, not delivered.
            sd = self.run_cli("send", "--to", sid, "draft tests for retry planner", root=self.root)
            self.assertTrue(sd["ok"], sd)
            self.assertEqual(sd["delivery"], "queued"); self.assertFalse(sd["delivered"])
            self.assertFalse(sd["resume_stolen"]); self.assertEqual(sd["session_id"], sid)
            self.assertTrue(Path(sd["inbox"]).is_file())
            self.assertEqual(self.spawns, [], "a queued send never opens a second session")

            # 5 RECEIVE: the neuron drains its own inbox, acks the inbox token, then seats with the join token.
            self.assertEqual(self.run_cli("inbox", "--seat", sid, root=self.root)["n"], 1)
            dr = self.run_cli("inbox", "--seat", sid, "--drain", root=self.root)
            self.assertEqual(dr["n"], 1); self.assertEqual(dr["drained"][0]["token"], sd["token"])
            self.assertEqual(self.run_cli("inbox", "--seat", sid, root=self.root)["n"], 0)
            ack = self.run_cli("hook", "note", "received token=" + sd["token"] + "; drafting", "--instance-id", sid, root=self.root)
            self.assertEqual(ack["kind"], "note"); self.assertEqual(ack["instance_id"], sid)
            se = self.run_cli("seated", "--seat", sid, "--token", jn["token"], root=self.root)
            self.assertTrue(se["ok"], se)
            aw = self.run_cli("await-seated", "--seat", sid, "--timeout", "0", root=self.root)
            self.assertEqual(aw["connected"], [sid]); self.assertEqual(aw["pending"], [])
            kinds = [r["kind"] for r in self.run_cli("feed", "--since", "10m", root=self.root)["events"]]
            for k in ("attach", "join", "synapse", "note", "seated"):
                self.assertIn(k, kinds, kinds)
            self.assertNotIn("refuse", kinds, "nothing was stolen, so nothing was refused")
            self.assertEqual(self.spawns, [])

    # -- MCP attach variant ---------------------------------------------------

    def _serve(self, gated):
        env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1" if gated else ""})
        env.start(); self.addCleanup(env.stop)
        httpd = make_server(self.root, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        url = "http://127.0.0.1:%s/mcp" % httpd.server_address[1]

        def call(name, **arguments):
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8"))["result"]
            return res.get("structuredContent") or json.loads(res["content"][0]["text"])
        return call

    def test_mcp_attach_cloud_chair_has_no_pane_and_proves_itself_by_ack(self):
        ensure_id(self.root)
        self.run_cli("bind", "--thread", "demo", root=self.root)
        call = self._serve(gated=True)

        # cloud is offered only where the vendor evidenced an interactive attach: claude, not codex.
        refused = call("join", to="codex", where="cloud")
        self.assertFalse(refused["ok"]); self.assertIn("refuse where='cloud' for codex", refused["error"])
        jn = call("join", to="claude", where="cloud", title="cloud-neuron")
        self.assertTrue(jn["ok"], jn)
        sid = jn["seat"]["session_id"]
        self.assertEqual(jn["seat"]["where"], "cloud"); self.assertIsNone(jn["seat"]["worktree"])

        # bring_up REFUSES a pane for it: no window row names the chair, and the card says why.
        up = call("bring_up", thread="demo", dry_run=True)
        cloud = [c for c in up.get("cloud") or [] if c["session_id"] == sid]
        self.assertEqual(len(cloud), 1, up)
        self.assertFalse(cloud[0]["pane"]); self.assertIn("no cloud launcher", cloud[0]["reason"])
        self.assertNotIn(sid, json.dumps(up.get("windows") or []))
        self.assertEqual(self.spawns, [])

        # launched-ness does not exist for it; connected is its own ack over the same wire.
        before = call("await_seated", seats=[sid], timeout=0)
        self.assertEqual([c["state"] for c in before["chairs"]], ["pending"])
        token = _join_tokens(self.root)[sid]
        ok = call("seated", seat=sid, token=token)
        self.assertTrue(ok["ok"], ok); self.assertNotIn(token, json.dumps(ok))
        after = call("await_seated", seats=[sid], timeout=0)
        self.assertEqual([c["state"] for c in after["chairs"]], ["connected"])
        self.assertEqual(self.spawns, [], "a cloud chair never spawns a local pane")

    def test_public_ungated_server_cannot_join_or_seat(self):
        ensure_id(self.root)
        call = self._serve(gated=False)
        n_before = len(list_seats(self.root))
        jn = call("join", to="claude", where="cloud")
        self.assertFalse(jn.get("ok")); self.assertIn("CONVOY_MCP_WRITE_TOOLS=1", jn["error"], "names the gate, does not pretend the verb is gone")
        self.assertNotIn("seat", jn, "a refusal never claims to have joined")
        se = call("seated", seat="claude-1-demo", token="not-a-real-token")
        self.assertFalse(se.get("ok")); self.assertIn("CONVOY_MCP_WRITE_TOOLS=1", se["error"])
        self.assertEqual(len(list_seats(self.root)), n_before, "nothing written by the public server")
        self.assertFalse((self.root / ".convoy" / "feed.jsonl").exists() and
                         "seated" in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
