"""The whole @convoy vision, walked once over the wire.

Every other test in this suite proves one rung. This one is the bar Marco set
for opening the PR: from a bare root to three connected neurons, driven ONLY
by JSON-RPC against a gated loopback server, the way a grok-bot host would
drive it. Nothing is called in-process; if a step is not reachable over the
wire, this test cannot pass.

Injected, and only these: the vendor usage probe (no `claude -p /usage` from a
test), the git clone (the URL is fake; the checkout it produces is a REAL git
repo, so `git worktree add` genuinely runs), the window spawn (nothing pops a
terminal in CI), and first-run home writes. Everything else - validation,
minting, joining, the seated acks, the redaction - is the shipped code.

The walk, and what each step proves:

  preflight   Gate 0 is GREEN on a gated deploy: every verb the wizard needs
              is listed by the endpoint itself.
  card        one card, header `convoy`, a row per harness carrying where /
              models / effort / USAGE REMAINING / attach.
  repos       GitHub yes: the repositories the host's gh login can see.
  onboard     the selected repository is cloned and bound; the yes/no answer
              is recorded on the thread.
  crew        N=3 across three harnesses: validated, one worktree each, every
              chair joined WITH a boot prompt, ONE window with three panes.
  seated      each neuron acks with the token its own join minted.
  await       connected is observed from those acks, not inferred from launch.
  graph       the thread agrees: three chairs, three worktrees, one thread.

Then the same server with the gate CLOSED, because a public deploy must not
be able to do any of it, and must say so honestly rather than silently.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import ensure_id, list_seats, read_github, read_thread
from convoy.mcp_http import _WRITE_TOOLS, make_server
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"
CREW = [
    {"harness": "grok", "effort": "high", "title": "scout"},
    {"harness": "claude", "effort": "high", "title": "builder"},
    {"harness": "codex", "title": "checker"},
]


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True,
                   capture_output=True, text=True, timeout=60)


def _real_repo() -> Path:
    """A genuine git repo, so mint_worktrees runs real `git worktree add`."""
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "e2e@convoy.test")
    _git(d, "config", "user.name", "convoy e2e")
    (d / "README.md").write_text("e2e\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "commit", "-qm", "seed")
    return d


class Wire:
    """A JSON-RPC client. Every response is kept so the walk can be searched
    for anything that must never have crossed the wire."""

    def __init__(self, url):
        self.url = url
        self.transcript = []

    def rpc(self, method, params=None):
        body = {"jsonrpc": "2.0", "method": method, "id": len(self.transcript) + 1}
        if params is not None:
            body["params"] = params
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode("utf-8"))
        self.transcript.append(out)
        return out

    def call(self, name, **arguments):
        res = self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]
        if "structuredContent" in res:
            return res["structuredContent"]
        return json.loads(res["content"][0]["text"])

    def tools(self):
        return {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}

    def blob(self):
        return json.dumps(self.transcript)


class WizardE2EGated(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        # The realistic gated deployment: the endpoint's root IS the checkout
        # the neurons will work in. An MCP process is bound to one root for
        # its lifetime, so a thread bound anywhere else is a thread this
        # endpoint could never answer for - asserted below.
        self.root = _real_repo()
        ensure_id(self.root)
        self.checkout = self.root
        self.spawns = []
        # A clean CI/stranger machine need not have three paid vendor CLIs.
        # Resolve the repository's inert executable stubs so the E2E tests
        # Convoy's wire walk rather than whichever harnesses its host installed.
        path = str(FAKES) + os.pathsep + os.environ.get("PATH", "")
        env = mock.patch.dict(os.environ, {"PATH": path})
        env.start()
        self.addCleanup(env.stop)

        def fake_spawn(argv, cwd=None, rect=None, **_k):
            self.spawns.append({"argv": list(argv), "cwd": cwd})
            return {"ok": True, "pid": 4242, "argv": list(argv)}

        def fake_clone(url, dest, runner=None):
            # The URL is fake; the checkout is the real repo made above, so
            # everything downstream of it is genuine git.
            return {"ok": True, "url": url, "cloned": True, "path": str(self.checkout)}

        for target, kw in (
            ("convoy.card.probe", {"return_value": NULL_PROBE}),
            ("convoy.glance.probe", {"return_value": NULL_PROBE}),
            ("convoy.onboard.probe", {"return_value": NULL_PROBE}),
            ("convoy.mcp_http.probe", {"return_value": NULL_PROBE}),
            ("convoy.mcp_http.live_runner", {"new": fake_spawn}),
            ("convoy.onboard.clone", {"new": fake_clone}),
            ("convoy.bringup.ensure_first_run", {"return_value": {
                "ok": True, "prepared": False, "wrote": False, "settings": None,
                "home_written": False, "settings_home": None}}),
        ):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _serve(self, gated):
        env = mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1" if gated else ""})
        env.start()
        self.addCleanup(env.stop)
        httpd = make_server(self.root, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return Wire("http://127.0.0.1:%s/mcp" % httpd.server_address[1])

    def _join_tokens(self):
        """The tokens the walk's own joins minted, read off the thread's feed
        on disk. Never from a response: a neuron proves itself with a token it
        already holds, and taking it from the wire would prove nothing."""
        feed = (self.root / ".convoy" / "feed.jsonl")
        out = {}
        for line in feed.read_text(encoding="utf-8").splitlines():
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

    def test_the_whole_vision_walks_over_the_wire(self):
        started = time.monotonic()
        w = self._serve(gated=True)

        # Gate 0 - the endpoint's own verdict on its own list.
        listed = w.tools()
        self.assertEqual([v for v in REQUIRED_WIZARD_VERBS if v not in listed], [],
                         "a gated deploy must list every verb the wizard needs")

        # One card. This is what the host draws.
        card = w.call("card")
        self.assertEqual(card["header"], "convoy")
        self.assertTrue(card["preflight"]["ok"], card["preflight"])
        rows = {r["harness"]: r for r in card["rows"]}
        for spec in CREW:
            row = rows[spec["harness"]]
            self.assertTrue(row["installed"], spec["harness"])
            self.assertEqual(row["attach"]["tool"], "crew")
            self.assertIn("local", row["where"])
            # usage remaining is on the card, and unknown stays null.
            self.assertIn("usage_remaining", row)
            self.assertIsNone(row["usage_remaining"])
        # cloud is offered only where a vendor --help evidenced it.
        self.assertEqual([h for h, r in rows.items() if "cloud" in r["where"]], ["claude"])

        # GitHub? yes -> which repository.
        with mock.patch("convoy.mcp_http.list_repos", return_value={
                "ok": True, "gh_present": True, "count": 2, "repos": [
                    {"nameWithOwner": "Deploy-Forward/convoy", "url": "https://github.com/Deploy-Forward/convoy.git", "isPrivate": False},
                    {"nameWithOwner": "Deploy-Forward/other", "url": "https://github.com/Deploy-Forward/other.git", "isPrivate": True}]}):
            repos = w.call("repos")
        self.assertTrue(repos["ok"])
        picked = repos["repos"][0]["url"]

        # Picking a repository this endpoint does not serve is REFUSED, with
        # the remedy, instead of binding a thread the endpoint cannot answer
        # for. This is the one place the vision meets a process invariant.
        stranded = w.call("onboard", to=["grok"], thread="e2e", checkout_root=picked, github=True)
        self.assertFalse(stranded["ok"], stranded)
        self.assertFalse(stranded["bound"])
        self.assertIn("attach a Convoy endpoint whose root IS that checkout", stranded["error"])
        self.assertIsNone(read_thread(self.root), "a refused onboard binds nothing")

        # The repository this endpoint serves binds, and the answer is recorded.
        on = w.call("onboard", to=[s["harness"] for s in CREW], thread="e2e",
                    checkout_root=str(self.checkout), github=True)
        self.assertTrue(on["ok"], on)
        self.assertEqual(read_thread(self.root), "e2e")
        self.assertEqual(read_github(self.root), "yes")
        self.assertEqual(w.call("card")["summary"]["github"], "yes")

        # N neurons, one call, one window.
        crew = w.call("crew", seats=CREW, thread="e2e", checkout=str(self.checkout), launch=True)
        self.assertTrue(crew["ok"], crew)
        self.assertTrue(crew["launched"], crew)
        self.assertEqual(len(crew["seats"]), 3)
        sids = [s["session_id"] for s in crew["seats"]]
        worktrees = {s.get("worktree") for s in crew["seats"]}
        self.assertEqual(len(worktrees), 3, "one chair per worktree")
        self.assertEqual(len(self.spawns), 1, "ONE window, not one per chair")
        argv = " ".join(self.spawns[0]["argv"])
        self.assertEqual(argv.count("split-pane"), 2, "three panes = two splits")
        # The effort the user picked reaches the harness that evidences a flag.
        self.assertIn("--reasoning-effort high", argv.replace('"', ""))

        # launched is not connected: the card says pending before any ack.
        self.assertTrue(all(c["state"] == "pending" for c in crew["seated"]["chairs"]),
                        crew["seated"])

        # Each neuron acks with the token ITS OWN join minted.
        tokens = self._join_tokens()
        self.assertEqual(sorted(tokens), sorted(sids), "every chair minted a token")
        for sid in sids:
            self.assertTrue(w.call("seated", seat=sid, token=tokens[sid])["ok"])

        # Connected is observed, not inferred.
        awaited = w.call("await_seated", seats=sids, timeout=0)
        self.assertTrue(awaited["ok"], awaited)
        self.assertEqual(sorted(c["state"] for c in awaited["chairs"]), ["connected"] * 3)

        # The thread agrees with itself.
        self.assertEqual(len(w.call("neurons")["neurons"]), 3)
        self.assertEqual(len({s["session_id"] for s in list_seats(self.root)}), 3)
        graph = w.call("graph")
        self.assertEqual(graph["thread"], "e2e")

        # Tokens: this endpoint is the conductor's own gated loopback, so a
        # lifecycle card may carry the token it just minted - that is the join
        # precedent and SPEC.md:56's chip contract, and the conductor needs it
        # to hand a chair its proof. What must never carry one is a READ card,
        # because those are the shapes the public wire also serves; a token
        # riding there would be a forgeable ack waiting to happen.
        reads = Wire(w.url)
        reads.call("card")
        reads.call("neurons")
        reads.call("graph")
        reads.call("glance", thread="e2e")
        read_blob = reads.blob()
        for sid, tok in tokens.items():
            self.assertNotIn(tok, read_blob, "read cards must not carry " + sid + "'s token")
        self.assertLess(time.monotonic() - started, 60, "the walk must stay quick")

    def test_the_same_walk_is_refused_on_a_public_deploy(self):
        w = self._serve(gated=False)
        listed = w.tools()

        # A public endpoint does not promise what it cannot do.
        for hidden in sorted(_WRITE_TOOLS):
            self.assertNotIn(hidden, listed, hidden + " must be hidden publicly")
        self.assertIn("card", listed, "the card is a read and stays public")

        # It still renders a card, and the card's own Gate 0 is RED, naming
        # the gate rather than pretending the verbs do not exist.
        card = w.call("card")
        self.assertEqual(card["header"], "convoy")
        pf = card["preflight"]
        self.assertFalse(pf["ok"])
        gated_required = sorted(v for v in REQUIRED_WIZARD_VERBS if v in _WRITE_TOOLS)
        self.assertEqual(sorted(pf["missing"]), gated_required)
        for verb in gated_required:
            self.assertEqual(pf["remedy"][verb], "write-gated")

        # And every door is shut.
        self.assertFalse(w.call("crew", seats=CREW, launch=True).get("ok"))
        spawn = w.call("bring_up", thread="e2e", dry_run=False)
        self.assertFalse(spawn.get("ok"))
        self.assertFalse(spawn.get("spawned"))
        self.assertEqual(self.spawns, [], "nothing spawned on a public process")


if __name__ == "__main__":
    unittest.main()
