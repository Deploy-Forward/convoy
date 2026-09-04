import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy import cli
from convoy.mcp_http import TOOLS
from convoy.wizard_preflight import (
    REMEDY_CLI_ONLY,
    REMEDY_REDEPLOY,
    REQUIRED_WIZARD_VERBS,
    preflight,
    run_preflight,
)

# Verbatim public tools/list, 2026-09-04 (13 tools). A fixture, not a menu.
LIVE_2026_09_04 = ["roster", "glance", "onboard", "terminals", "context", "send", "feed",
                   "bring_up", "open", "hide", "minimize", "background", "install"]


class WizardPreflight(unittest.TestCase):
    def test_all_required_present_is_green(self):
        card = preflight(list(REQUIRED_WIZARD_VERBS) + ["roster"])
        self.assertTrue(card["ok"])
        self.assertEqual(card["status"], "GREEN")
        self.assertEqual(card["missing"], [])
        self.assertFalse(card["frozen_menu"])

    def test_lagging_public_deploy_is_red_and_names_remedy_per_verb(self):
        card = preflight(LIVE_2026_09_04, url="https://convoy.bot/mcp")
        self.assertFalse(card["ok"])
        self.assertEqual(card["status"], "RED")
        self.assertEqual(card["missing"], list(REQUIRED_WIZARD_VERBS))
        packaged = {t["name"] for t in TOOLS}
        for verb, remedy in card["remedy"].items():
            self.assertEqual(remedy, REMEDY_REDEPLOY if verb in packaged else REMEDY_CLI_ONLY, verb)
        # All required wizard verbs are now packaged MCP tools on main, so a
        # lagging public tools/list is a redeploy problem for each one.
        for verb in REQUIRED_WIZARD_VERBS:
            self.assertEqual(card["remedy"][verb], REMEDY_REDEPLOY)
        self.assertIn("redeploy", card["ask"])
        self.assertNotIn("cli-only", card["ask"])

    def test_listed_is_only_what_live_returned_never_padded(self):
        card = preflight(["roster", "roster", "glance"])
        self.assertEqual(card["listed"], ["glance", "roster"])
        for verb in REQUIRED_WIZARD_VERBS:
            self.assertNotIn(verb, card["listed"])

    def test_tools_list_failure_is_red_with_error_verbatim(self):
        def boom(url):
            raise TimeoutError("timed out after 20s")
        card = run_preflight("https://example.invalid/mcp", fetch=boom)
        self.assertFalse(card["ok"])
        self.assertIsNone(card["listed"])
        self.assertEqual(card["missing"], list(REQUIRED_WIZARD_VERBS))
        self.assertIn("TimeoutError: timed out after 20s", card["error"])
        self.assertIn("must not propose seats", card["ask"])

    def test_offline_tools_bypass_network(self):
        called = []

        def never(url):
            called.append(url)
            return []
        card = run_preflight(tools=list(REQUIRED_WIZARD_VERBS), fetch=never)
        self.assertTrue(card["ok"])
        self.assertEqual(called, [])

    def test_cli_verb_exit_code_follows_ok(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["preflight", "--tools", ",".join(REQUIRED_WIZARD_VERBS)])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main(["preflight", "--tools", ",".join(LIVE_2026_09_04)])
        self.assertEqual(rc, 1)
        card = json.loads(out.getvalue())
        self.assertEqual(card["status"], "RED")
        self.assertEqual(card["remedy"]["seat"], REMEDY_REDEPLOY)


if __name__ == "__main__":
    unittest.main()
