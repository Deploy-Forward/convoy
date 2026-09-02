import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.harness_contract import (  # noqa: E402
    canonical_harness_id,
    harness_entries,
    load_harness_contract,
    usage_remaining_null_until_live_probe,
)
from convoy.onboard import onboard  # noqa: E402


class HarnessContract(unittest.TestCase):
    def test_contract_has_locked_effort_types(self):
        data = load_harness_contract()
        self.assertEqual(data["schema_version"], "2026-09-01")
        effort = data["effort_types"]
        self.assertIn("high", effort)
        self.assertIn("xhigh", effort)
        self.assertIn("extra-high", effort)
        self.assertEqual(effort["extra-high"]["vendor_equivalent"], "xhigh")

    def test_contract_lists_supported_harnesses(self):
        ids = [row["id"] for row in harness_entries(mcp_supported_only=True)]
        self.assertEqual(ids, ["grok", "claude", "codex", "cursor-agent", "agy", "hermes", "pi"])

    def test_aliases_and_meter_null_rules(self):
        self.assertEqual(canonical_harness_id("antigravity"), "agy")
        self.assertEqual(canonical_harness_id("claude-code"), "claude")
        self.assertEqual(canonical_harness_id("cursor_agent"), "cursor-agent")
        self.assertTrue(usage_remaining_null_until_live_probe("grok"))
        self.assertTrue(usage_remaining_null_until_live_probe("pi"))
        self.assertFalse(usage_remaining_null_until_live_probe("claude"))

    def test_onboard_accepts_hermes_pi_and_antigravity_alias(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.dict("os.environ", {"PATH": ""}):
            card = onboard(root, ["hermes", "pi", "antigravity"])
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["named"], ["hermes", "pi", "agy"])
        by = {h["to"]: h for h in card["harnesses"]}
        self.assertIn("hermes", by)
        self.assertIn("pi", by)
        self.assertIn("agy", by)
        # Hermes/Pi are BYO-only for now: no installer hint is fabricated.
        self.assertNotIn("install", by["hermes"])
        self.assertNotIn("install", by["pi"])


if __name__ == "__main__":
    unittest.main()
