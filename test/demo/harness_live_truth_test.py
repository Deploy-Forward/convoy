import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import resume_argv
from convoy.harness_contract import load_harness_contract
from convoy.mcp_http import TOOLS
from convoy.synapse import native_runner


def _harness(data, hid):
    return next(h for h in data["harnesses"] if h["id"] == hid)


class HarnessLiveTruth(unittest.TestCase):
    """cloud-g1 UltraCode on #21 + live --help on the demo box
    (2026-09-01): the contract must state what the binaries actually take."""

    def setUp(self):
        load_harness_contract.cache_clear()
        self.data = load_harness_contract()

    def tearDown(self):
        load_harness_contract.cache_clear()

    def test_grok_effort_keys_match_live_cli(self):
        # grok --help: --reasoning-effort <EFFORT> [aliases: --effort];
        # live reject enum (lead research): xhigh, high, medium, low
        grok = _harness(self.data, "grok")
        self.assertEqual(grok["effort"]["keys"], ["low", "medium", "high", "xhigh"])
        self.assertEqual(grok["effort"]["cli_flag"], "--reasoning-effort")

    def test_agy_effort_keys_match_live_cli(self):
        # agy --help: --effort (low|medium|high)
        agy = _harness(self.data, "agy")
        self.assertEqual(agy["effort"]["keys"], ["low", "medium", "high"])
        self.assertEqual(agy["effort"]["cli_flag"], "--effort")

    def test_claude_ultracode_is_named_not_silent(self):
        claude = _harness(self.data, "claude")
        self.assertEqual(claude["effort"]["keys"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(claude["effort"]["docs_only_tokens"], ["ultracode"])

    def test_pi_thinking_surface_recorded_verbatim(self):
        # pi --help: --thinking <level> off,minimal,low,medium,high,xhigh,max
        pi = _harness(self.data, "pi")
        self.assertEqual(pi["effort"]["mode"], "model-driven")
        self.assertIsNone(pi["effort"]["keys"])
        self.assertEqual(pi["effort"]["cli_flag"], "--thinking")
        self.assertEqual(
            pi["effort"]["cli_values"],
            ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
        )

    def test_agy_resume_argv_uses_conversation_not_resume(self):
        # agy --help resumes via --conversation <ID>; there is no --resume
        argv = resume_argv({"to": "agy", "session_id": "seat-agy", "resume": "vendor-agy-id"})
        self.assertEqual(argv[1:], ["--conversation", "vendor-agy-id"])
        self.assertNotIn("--resume", argv)

    def test_agy_native_runner_uses_conversation(self):
        calls = []

        def fake_run(cmd, **_k):
            calls.append(list(cmd))

            class R:
                returncode = 0
                stdout = '{"session_id":"sess-agy"}'
                stderr = ""

            return R()

        with mock.patch("convoy.synapse.shutil.which", return_value="/abs/agy"), \
             mock.patch("convoy.synapse.subprocess.run", side_effect=fake_run):
            card = native_runner("agy", "hello", resume="vendor-agy-id")
        self.assertTrue(card["ok"])
        self.assertEqual(calls[0][1:], ["--conversation", "vendor-agy-id"])
        self.assertNotIn("--resume", calls[0])

    def test_install_tool_does_not_advertise_hermes_or_pi(self):
        desc = next(t for t in TOOLS if t["name"] == "install")["inputSchema"]["properties"]["to"]["description"]
        self.assertNotIn("hermes", desc.lower())
        self.assertIsNone(re.search(r"\bpi\b", desc.lower()))
        self.assertIn("agy", desc)

    def test_hermes_pi_stay_on_roster_with_verified_resume(self):
        # hermes --resume SESSION and pi --resume both exist in live --help;
        # they stay mcp_supported (BYO present; install cannot fetch them).
        for hid in ("hermes", "pi"):
            row = _harness(self.data, hid)
            self.assertTrue(row["mcp_supported"])
        argv = resume_argv({"to": "hermes", "resume": "sess-h"})
        self.assertEqual(argv[1:], ["--resume", "sess-h"])


if __name__ == "__main__":
    unittest.main()
