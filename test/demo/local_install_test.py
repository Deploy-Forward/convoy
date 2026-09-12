"""`convoy install --local`: the machine setup that broke three times this week, as one
verb with a verify card (Marco 2026-09-12, productize move 1). Origin supervisor,
tunnel supervisor, console script on PATH. Dry by default; --live needs --opt-in;
every claim in the card is read back, never assumed. Tests written before the code."""
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
        self.tok = self.home / "run.token"; self.tok.write_text("SECRET-TUNNEL-TOKEN\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); self.env.start(); self.addCleanup(self.env.stop)

    def test_dry_run_plans_three_items_and_touches_nothing(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        card = install_local(self.root, token_file=self.tok, runner=r, port=8788, windows=True)
        self.assertTrue(card["ok"]); self.assertTrue(card["dry_run"])
        self.assertEqual([p["name"] for p in card["plan"]], ["origin", "tunnel", "console-script"])
        origin = card["plan"][0]
        self.assertEqual(origin["task"], "ConvoyBotMcp")
        self.assertIn(str(self.root), origin["arguments"]); self.assertIn("--port 8788", origin["arguments"])
        self.assertEqual(Path(origin["execute"]), Path(sys.executable), "the origin runs on the interpreter that installed Convoy")
        tunnel = card["plan"][1]
        self.assertEqual(tunnel["task"], "ConvoyBotTunnel")
        self.assertTrue(str(tunnel["wrapper"]).startswith(str(self.home)), "the wrapper is Convoy's, under CONVOY_HOME, not C:\\.grok")
        self.assertEqual(Path(tunnel["token_file"]), self.tok)
        self.assertEqual(r.scripts, [], "dry run registers nothing")
        self.assertNotIn("SECRET-TUNNEL-TOKEN", json.dumps(card), "the token never appears in a card")
        self.assertFalse(Path(tunnel["wrapper"]).exists(), "dry run writes no wrapper")

    def test_live_refuses_without_opt_in(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        card = install_local(self.root, token_file=self.tok, runner=r, live=True, opt_in=False, windows=True)
        self.assertFalse(card["ok"]); self.assertIn("opt-in", card["error"]); self.assertEqual(r.scripts, [])

    def test_live_registers_both_supervisors_mirrored_and_verifies_by_read_back(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        with mock.patch("convoy.local_install._console_script_ok", return_value=(True, "C:/x/Scripts/convoy.exe")):
            card = install_local(self.root, token_file=self.tok, runner=r, live=True, opt_in=True, port=8788, windows=True)
        self.assertTrue(card["ok"], card)
        reg = [s for s in r.scripts if "Register-ScheduledTask" in s]
        self.assertEqual(len(reg), 2)
        for s in reg:
            self.assertIn("New-ScheduledTaskTrigger -AtLogOn", s)
            self.assertIn("-RestartCount 99", s); self.assertIn("-RestartInterval", s)
            self.assertIn("ExecutionTimeLimit", s)
            self.assertNotIn("SECRET-TUNNEL-TOKEN", s, "the token is read by the wrapper at run time, never baked into a task")
        wrapper = Path(card["plan"][1]["wrapper"])
        self.assertTrue(wrapper.is_file())
        w = wrapper.read_text(encoding="utf-8")
        self.assertIn("--metrics", w); self.assertIn("--logfile", w); self.assertIn(str(self.tok), w); self.assertNotIn("SECRET-TUNNEL-TOKEN", w)
        v = {x["name"]: x for x in card["verify"]}
        self.assertEqual(v["origin"]["state"], "Running"); self.assertEqual(v["tunnel"]["state"], "Running")
        self.assertTrue(v["console-script"]["ok"])
        self.assertEqual(card["next"], "convoy install --local --verify to re-check any time")

    def test_verify_only_reads_back_and_reports_missing_tasks_honestly(self):
        from convoy.local_install import install_local
        r = FakeRunner()
        with mock.patch("convoy.local_install._console_script_ok", return_value=(False, None)):
            card = install_local(self.root, token_file=self.tok, runner=r, verify_only=True, windows=True)
        self.assertFalse(card["ok"])
        v = {x["name"]: x for x in card["verify"]}
        self.assertFalse(v["origin"]["ok"]); self.assertIn("no task", v["origin"]["error"])
        self.assertFalse(v["console-script"]["ok"]); self.assertIn("convoy", v["console-script"]["hint"])
        self.assertEqual([s for s in r.scripts if "Register" in s], [])

    def test_non_windows_is_refused_with_the_missing_adapter_named(self):
        from convoy.local_install import install_local
        card = install_local(self.root, token_file=self.tok, runner=FakeRunner(), windows=False)
        self.assertFalse(card["ok"]); self.assertIn("systemd", card["error"]); self.assertIn("launchd", card["error"])

    def test_missing_token_file_is_a_plan_warning_not_a_secret_leak(self):
        from convoy.local_install import install_local
        card = install_local(self.root, token_file=self.home / "absent.token", runner=FakeRunner(), windows=True)
        self.assertTrue(card["ok"]); self.assertTrue(any("token file" in w for w in card["warnings"]))

    def test_cli_install_local_prints_the_card(self):
        from convoy.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("convoy.local_install._powershell", FakeRunner()), \
             mock.patch("convoy.local_install.os.name", "nt"):
            rc = main(["--root", str(self.root), "install", "--local", "--token-file", str(self.tok)])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0); self.assertTrue(card["dry_run"]); self.assertEqual(len(card["plan"]), 3)
