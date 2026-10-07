"""`convoy install --local`: the machine setup as one verb with a verify card
(productize move 1). Origin supervisor and
console script on PATH (the tunnel supervisor was removed in 1.3.2). Dry by default;
--live needs --opt-in; every claim in the card is read back, never assumed. Tests
written before the code."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from convoy.convoy import bind, ensure_id


class FakeRunner:
    """Records every PowerShell script the installer would run; answers read-backs."""
    def __init__(self):
        self.scripts: list[str] = []
        self.registered: dict[str, dict] = {}

    def __call__(self, script: str) -> dict:
        self.scripts.append(script)
        if "Register-ScheduledTask" in script:
            name = "ConvoyBotMcp" if "ConvoyBotMcp" in script else "ConvoyBotTunnel"
            self.registered[name] = {"state": "Ready"}
            return {"ok": True, "stdout": json.dumps({"TaskName": name, "State": "Ready"}), "stderr": ""}
        if "Get-ScheduledTask" in script:
            name = "ConvoyBotMcp" if "ConvoyBotMcp" in script else "ConvoyBotTunnel"
            if name in self.registered:
                return {"ok": True, "stdout": json.dumps({"TaskName": name, "State": "Running", "Execute": "x", "Arguments": "y",
                                                          "RestartCount": 99, "RestartInterval": "PT1M", "Trigger": "MSFT_TaskLogonTrigger"}), "stderr": ""}
            return {"ok": False, "stdout": "", "stderr": "no task"}
        if "Start-ScheduledTask" in script:
            return {"ok": True, "stdout": "", "stderr": ""}
        return {"ok": True, "stdout": "", "stderr": ""}


class LocalInstall(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "li")
        self.home = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); self.env.start(); self.addCleanup(self.env.stop)

    def test_dry_run_plans_three_items_and_touches_nothing(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        card = install_local(self.root, runner=r, port=8788, windows=True)
        self.assertTrue(card["ok"]); self.assertTrue(card["dry_run"])
        self.assertEqual([p["name"] for p in card["plan"]], ["origin", "console-script"])
        origin = card["plan"][0]
        self.assertEqual(origin["task"], "ConvoyBotMcp")
        self.assertNotIn(str(self.root), origin["arguments"], "unbound by default: the origin serves every thread (move 3)"); self.assertIn("--port 8788", origin["arguments"])
        self.assertEqual(origin["serves"], "all threads")
        self.assertEqual(Path(origin["execute"]).name.lower(), "pythonw.exe", "windowless interpreter so Windows Terminal never opens a window for it")
        self.assertEqual(Path(origin["execute"]).parent, Path(sys.executable).parent, "the origin still runs on the interpreter that installed Convoy")
        self.assertEqual(r.scripts, [], "dry run registers nothing")

    def test_live_refuses_without_opt_in(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        card = install_local(self.root, runner=r, live=True, opt_in=False, windows=True)
        self.assertFalse(card["ok"]); self.assertIn("opt-in", card["error"]); self.assertEqual(r.scripts, [])

    def test_live_registers_the_origin_mirrored_and_verifies_by_read_back(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        with mock.patch("convoy.local_install._console_script_ok", return_value=(True, "C:/x/Scripts/convoy.exe")):
            card = install_local(self.root, runner=r, live=True, opt_in=True, port=8788, windows=True)
        self.assertTrue(card["ok"], card)
        reg = [s for s in r.scripts if "Register-ScheduledTask" in s]
        self.assertEqual(len(reg), 1)
        self.assertIn("ConvoyBotMcp", reg[0])
        for s in reg:
            self.assertIn("New-ScheduledTaskTrigger -AtLogOn", s)
            self.assertIn("-RestartCount 99", s); self.assertIn("-RestartInterval", s)
            self.assertIn("ExecutionTimeLimit", s)
            self.assertIn("pythonw.exe'", s, "the origin runs on the windowless interpreter")
        v = {x["name"]: x for x in card["verify"]}
        self.assertEqual(v["origin"]["state"], "Running")
        self.assertNotIn("tunnel", v)
        self.assertTrue(v["console-script"]["ok"])
        self.assertEqual(card["next"], "convoy install --local --verify to re-check any time")

    def test_verify_only_reads_back_and_reports_missing_tasks_honestly(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        with mock.patch("convoy.local_install._console_script_ok", return_value=(False, None)):
            card = install_local(self.root, runner=r, verify_only=True, windows=True)
        self.assertFalse(card["ok"])
        v = {x["name"]: x for x in card["verify"]}
        self.assertFalse(v["origin"]["ok"]); self.assertIn("no task", v["origin"]["error"])
        self.assertFalse(v["console-script"]["ok"]); self.assertIn("convoy", v["console-script"]["hint"])
        self.assertEqual([s for s in r.scripts if "Register" in s], [])

    def test_non_windows_is_refused_with_the_missing_adapter_named(self):
        from convoy.local_install import install_local
        card = install_local(self.root, runner=FakeRunner(), windows=False)
        self.assertFalse(card["ok"]); self.assertIn("systemd", card["error"]); self.assertIn("launchd", card["error"])

    def test_cli_install_local_prints_the_card(self):
        from convoy.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("convoy.local_install._powershell", FakeRunner()), \
             mock.patch("convoy.local_install.os.name", "nt"):
            rc = main(["--root", str(self.root), "install", "--local"])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0); self.assertTrue(card["dry_run"]); self.assertEqual(len(card["plan"]), 2)


class NeverPausedByBattery(unittest.TestCase):
    """Task Scheduler defaults to `DisallowStartIfOnBatteries=True` and
    `StopIfGoingOnBatteries=True`. On a machine running on battery the scheduler then holds
    `ConvoyBotMcp` in Queued and nothing serves, with nobody at a terminal to notice. The
    registration itself must carry the flags off so no fresh install regresses it."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "nb")
        self.home = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); self.env.start(); self.addCleanup(self.env.stop)

    def test_registration_script_turns_both_battery_settings_off_and_keeps_restart_policy(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        with mock.patch("convoy.local_install._console_script_ok", return_value=(True, "C:/x/Scripts/convoy.exe")):
            card = install_local(self.root, runner=r, live=True, opt_in=True, port=8788, windows=True)
        self.assertTrue(card["ok"], card)
        reg = [s for s in r.scripts if "Register-ScheduledTask" in s]
        self.assertEqual(len(reg), 1, "ConvoyBotMcp is the one supervisor")
        for s in reg:
            self.assertIn("-DisallowStartIfOnBatteries $false", s,
                          "a machine on battery must not leave the origin Queued")
            self.assertIn("-StopIfGoingOnBatteries $false", s,
                          "going on battery must not stop a running supervisor")
            self.assertIn("-RestartCount 99", s); self.assertIn("-RestartInterval", s)


class RootMustBeAThread(unittest.TestCase):
    """2026-09-13: `install --local --live` run from the home directory bound the public
    origin to C:/Users/<user>, a place with no thread, and the conductor's first
    authenticated stamp landed in CONVOY_HOME/feed.jsonl. The root must be a bound
    thread; a bare directory is refused with the roots the index knows."""
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); self.env.start(); self.addCleanup(self.env.stop)

    def test_a_root_without_a_thread_is_refused_before_anything_is_planned(self):
        from convoy.local_install import install_local
        bare = Path(tempfile.mkdtemp())
        card = install_local(bare, runner=FakeRunner(), windows=True, live=True, opt_in=True, bound=True)
        self.assertFalse(card["ok"]); self.assertIn("not a Convoy thread", card["error"]); self.assertEqual(card["plan"], [])
        self.assertIn("known_roots", card)

    def test_convoy_home_itself_is_refused_even_when_it_looks_like_a_thread(self):
        from convoy.local_install import install_local
        ensure_id(self.home); bind(self.home, "oops")
        card = install_local(self.home, runner=FakeRunner(), windows=True, bound=True)
        self.assertFalse(card["ok"]); self.assertIn("CONVOY_HOME", card["error"])


class Pairing(unittest.TestCase):
    """Pairing is a file with no secret in it.

    origin.json says WHERE the credential lives and never what it is, so the
    record can be read, copied into a bug report and committed by accident
    without leaking anything. The credential file itself is the secret, read
    at call time by report.py.

    And pairing is proved, not declared: one real beat goes out and the card
    prints the schema that came back. A pairing that only wrote a file would
    be a machine that believes it is connected.
    """

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-home-"))
        self.cred = self.home / "worklanes_credential.txt"
        self.cred.write_text("o_cred_abcdef0123456789", encoding="utf-8")

    def test_pair_writes_origin_json_without_credential_bytes(self):
        from convoy.local_install import pair

        beats = []

        def fake_beat(origin):
            beats.append(origin)
            return {"status": 200, "body": {"originId": origin["origin_id"], "reachability": "live"}}

        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            card = pair(org_id="org1", user_id="u1", credential_file=self.cred,
                        api_base="https://example.invalid", machine_id="m1",
                        beat=fake_beat, now="2026-09-17T00:00:00.000000Z")
        self.assertTrue(card["ok"], card)
        row = json.loads((self.home / "origin.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(row), ["api_base", "credential_path", "machine_id", "org_id",
                                       "origin_id", "paired_at", "user_id"])
        self.assertTrue(row["origin_id"].startswith("o_"))
        self.assertEqual(len(row["origin_id"]), 22, "o_ plus 20 hex")
        self.assertEqual(row["credential_path"], str(self.cred.resolve()))
        raw = (self.home / "origin.json").read_text(encoding="utf-8")
        self.assertNotIn("o_cred_abcdef0123456789", raw, "the file points at the secret, never holds it")
        self.assertNotIn("o_cred_abcdef0123456789", json.dumps(card))
        # Proved, not declared.
        self.assertEqual(len(beats), 1)
        self.assertEqual(card["verified"]["status"], 200)
        self.assertEqual(sorted(card["verified"]["schema"]), ["originId", "reachability"])

    def test_the_origin_id_is_stable_for_the_same_machine_and_user(self):
        from convoy.local_install import pair
        ok = lambda origin: {"status": 200, "body": {"originId": origin["origin_id"]}}
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            first = pair(org_id="org1", user_id="u1", credential_file=self.cred,
                         api_base="https://a.invalid", machine_id="m1", beat=ok)
            second = pair(org_id="org1", user_id="u1", credential_file=self.cred,
                          api_base="https://a.invalid", machine_id="m1", beat=ok)
            other = pair(org_id="org1", user_id="u2", credential_file=self.cred,
                         api_base="https://a.invalid", machine_id="m1", beat=ok)
        self.assertEqual(first["origin_id"], second["origin_id"])
        self.assertNotEqual(first["origin_id"], other["origin_id"])

    def test_a_failed_beat_leaves_the_machine_unpaired(self):
        from convoy.local_install import pair
        from convoy.report import Revoked

        def angry(_origin):
            raise Revoked("the platform refused this origin credential (403)")

        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            card = pair(org_id="org1", user_id="u1", credential_file=self.cred,
                        api_base="https://example.invalid", machine_id="m1", beat=angry)
        self.assertFalse(card["ok"], card)
        self.assertFalse((self.home / "origin.json").exists(),
                         "a machine that could not beat is not paired")
        self.assertNotIn("o_cred_abcdef0123456789", json.dumps(card))

    def test_an_unreadable_credential_is_refused_before_anything_is_written(self):
        from convoy.local_install import pair
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            card = pair(org_id="org1", user_id="u1", credential_file=self.home / "absent.txt",
                        api_base="https://example.invalid", machine_id="m1",
                        beat=lambda _o: {"status": 200, "body": {}})
        self.assertFalse(card["ok"])
        self.assertIn("credential", card["error"])
        self.assertFalse((self.home / "origin.json").exists())

    def test_unpair_removes_the_record_and_never_the_credential(self):
        from convoy.local_install import pair, unpair
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}):
            pair(org_id="org1", user_id="u1", credential_file=self.cred,
                 api_base="https://example.invalid", machine_id="m1",
                 beat=lambda o: {"status": 200, "body": {"originId": o["origin_id"]}})
            card = unpair()
        self.assertTrue(card["ok"], card)
        self.assertFalse((self.home / "origin.json").exists())
        self.assertTrue(self.cred.is_file(), "unpairing is not a deletion of the user's secret")

    def test_the_cli_refuses_an_incomplete_pair_before_it_touches_anything(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}), redirect_stdout(out):
            code = main(["install", "--local", "--pair", "--org", "org1"])
        card = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertIn("--user", card["error"])
        self.assertIn("--credential-file", card["error"])
        self.assertFalse((self.home / "origin.json").exists())
