"""An MCP launch records the conductor as the launcher, so a neuron's results reach it.

The MCP caller is a conductor, proven by its bearer, not a chair. So MCP crew, join, launch
and bring_up record `launched_by: {"kind": "conductor", "name": <the bearer's conductor>}`.
A launch with no bearer identity refuses with "cannot prove who is launching". The neuron's
boot prompt says `Launched by: conductor <name>`, `whoami` shows it, and `convoy report` writes
a proven note addressed to the conductor, which its `replies` cursor returns. Chair launchers
keep their string shape.

Every id is synthetic; roots and the Convoy home are temporary; no harness or terminal runs.
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

from convoy.convoy import bind, ensure_id, list_seats, seat  # noqa: E402
from convoy.lifecycle import join  # noqa: E402
try:
    from test.demo.write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401

CONDUCTOR = "grok-bot"
PRINCIPAL = {"id": "bearer-0000", "conductor": CONDUCTOR, "label": "synthetic connector"}
LAUNCHER = {"kind": "conductor", "name": CONDUCTOR}
EPOCH = "1970-01-01T00:00:00.000000Z"
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    for argv in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", *argv], cwd=str(d), check=True, capture_output=True, text=True, timeout=30)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-cond-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "conductor-launch")
        for target in ("convoy.bringup.ensure_first_run", "convoy.targeted_launch.ensure_first_run"):
            q = mock.patch(target, return_value=dict(FIRST_RUN))
            q.start()
            self.addCleanup(q.stop)

    def call(self, name, arguments, principal=PRINCIPAL):
        from convoy.mcp_http import handle_rpc
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        return handle_rpc(self.root, msg, principal=principal)["result"]["structuredContent"]

    def row(self, sid):
        return next(s for s in list_seats(self.root) if s["session_id"] == sid)


class AnMcpLaunchRecordsTheConductor(Base):
    def test_crew_records_the_conductor_and_the_prompt_names_it(self):
        card = self.call("crew", {"seats": [{"harness": "codex"}]})
        self.assertTrue(card["ok"], card)
        row = self.row(card["seats"][0]["session_id"])
        self.assertEqual(row["launched_by"], LAUNCHER)
        self.assertIn("Launched by: conductor " + CONDUCTOR, row["boot_prompt"])

    def test_join_records_the_conductor(self):
        card = self.call("join", {"to": "codex", "session_id": "joined", "worktree": tempfile.mkdtemp()})
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.row("joined")["launched_by"], LAUNCHER)

    def test_launch_records_the_conductor(self):
        join(self.root, "codex", session_id="fresh", worktree=tempfile.mkdtemp())
        with mock.patch("convoy.mcp_http.launch_seat", return_value={"ok": True}) as launch:
            card = self.call("launch", {"seat": "fresh"})
        self.assertTrue(card["ok"], card)
        launch.assert_called_once()
        self.assertEqual(self.row("fresh")["launched_by"], LAUNCHER)
        self.assertIn("Launched by: conductor " + CONDUCTOR, self.row("fresh")["boot_prompt"])

    def test_bring_up_records_the_conductor_on_the_chairs_it_spawns(self):
        join(self.root, "codex", session_id="fresh", worktree=tempfile.mkdtemp())
        window = mock.Mock(return_value={"ok": True, "pid": 1})
        with mock.patch("convoy.mcp_http.live_runner", window), \
             mock.patch("convoy.bringup.shutil.which", side_effect=lambda n: "C:\\Tools\\" + str(n) + ".exe"):
            card = self.call("bring_up", {"dry_run": False})
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.row("fresh")["launched_by"], LAUNCHER)

    def test_a_launch_without_a_bearer_identity_refuses(self):
        with write_gate():   # the gate opens, no identity
            card = self.call("crew", {"seats": [{"harness": "codex"}]}, principal=None)
            self.assertFalse(card["ok"], card)
            self.assertEqual(card["error"], "cannot prove who is launching")
            self.assertEqual(list_seats(self.root), [])
            join(self.root, "codex", session_id="fresh", worktree=tempfile.mkdtemp())
            with mock.patch("convoy.mcp_http.launch_seat", return_value={"ok": True}) as launch:
                card = self.call("launch", {"seat": "fresh"}, principal=None)
            self.assertEqual(card["error"], "cannot prove who is launching")
            launch.assert_not_called()


class TheNeuronReportsToItsConductor(Base):
    def setUp(self):
        super().setUp()
        seat(self.root, "claude", "neuron", worktree=tempfile.mkdtemp(), resume="neuron-native")
        from convoy.lifecycle import record_launcher
        record_launcher(self.root, "neuron", dict(LAUNCHER))

    def test_report_reaches_the_conductors_replies_cursor(self):
        from convoy.conductor import replies
        from convoy.route import report
        card = report(self.root, "synthetic result", me={"ok": True, "chair": "neuron", "via": "environment"})
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["routed_to"], card["route"]), (CONDUCTOR, "conductor"))
        mail = replies(self.root, CONDUCTOR, since=EPOCH)
        notes = [r for r in mail["rows"] if r.get("kind") == "note"]
        self.assertEqual([(r["from"], r["verified_by"], r["summary"]) for r in notes],
                         [("neuron", "environment", "synthetic result")])

    def test_an_unproven_report_to_the_conductor_refuses(self):
        from convoy.route import report
        card = report(self.root, "x", me={"ok": True, "chair": "neuron", "via": "cwd"})
        self.assertFalse(card["ok"], card)

    def test_whoami_shows_the_conductor_launcher(self):
        from convoy.cli import main
        buf = io.StringIO()
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": "neuron", "via": "environment"}), \
             redirect_stdout(buf):
            main(["--root", str(self.root), "whoami"])
        card = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(card["launched_by"], LAUNCHER)

    def test_adopt_over_a_conductor_launcher_needs_the_lead(self):
        from convoy.adopt import adopt
        seat(self.root, "claude", "caller", worktree=tempfile.mkdtemp(), resume="caller-native")
        card = adopt(self.root, "neuron", me={"ok": True, "chair": "caller", "via": "environment"})
        self.assertFalse(card["ok"], card)
        self.assertEqual(self.row("neuron")["launched_by"], LAUNCHER)


class ChairLaunchersKeepTheirShape(Base):
    def test_a_chair_launcher_is_still_a_string_and_still_routes(self):
        from convoy.route import report
        seat(self.root, "claude", "boss", worktree=tempfile.mkdtemp(), resume="boss-native")
        seat(self.root, "claude", "neuron", worktree=tempfile.mkdtemp(), resume="neuron-native")
        from convoy.lifecycle import record_launcher
        record_launcher(self.root, "neuron", "boss")
        self.assertEqual(self.row("neuron")["launched_by"], "boss")
        card = report(self.root, "x", me={"ok": True, "chair": "neuron", "via": "environment"})
        self.assertEqual((card["routed_to"], card["route"]), ("boss", "launcher"))


class AnMcpLaunchAndACliLaunchOfOneChair(Base):
    def test_a_cli_launch_in_flight_keeps_its_launcher_against_an_mcp_bring_up(self):
        from convoy.lifecycle import record_launcher
        from convoy.targeted_launch import take_launch_claim
        seat(self.root, "claude", "cli-chair", worktree=tempfile.mkdtemp(), resume="cli-native")
        join(self.root, "codex", session_id="fresh", worktree=tempfile.mkdtemp())
        take_launch_claim(self.root, "fresh")          # a CLI launch holds the chair's reservation ...
        record_launcher(self.root, "fresh", "cli-chair")   # ... and has recorded its launcher
        window = mock.Mock(return_value={"ok": True, "pid": 1})
        with mock.patch("convoy.mcp_http.live_runner", window), \
             mock.patch("convoy.bringup.shutil.which", side_effect=lambda n: "C:\\Tools\\" + str(n) + ".exe"):
            card = self.call("bring_up", {"dry_run": False})
        self.assertEqual(self.row("fresh")["launched_by"], "cli-chair")
        self.assertIn("fresh", [s["session_id"] for s in card.get("skipped") or []], card)


class TheBearerNamesTheConductor(Base):
    def test_arguments_naming_another_conductor_are_ignored(self):
        args = {"to": "codex", "session_id": "spoofed", "worktree": tempfile.mkdtemp(), "author": "conductor-b",
                "launched_by": {"kind": "conductor", "name": "conductor-b"}, "conductor": "conductor-b"}
        card = self.call("join", args)
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.row("spoofed")["launched_by"], LAUNCHER)
        card = self.call("crew", {"seats": [{"harness": "codex", "title": "spoof2"}], "conductor": "conductor-b",
                                  "launched_by": "conductor-b"})
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.row(card["seats"][0]["session_id"])["launched_by"], LAUNCHER)


if __name__ == "__main__":
    unittest.main()
