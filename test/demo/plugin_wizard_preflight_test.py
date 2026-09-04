import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy import cli
from convoy.mcp_http import TOOLS
from convoy.wizard_preflight import (
    REMEDY_NOT_REGISTERED,
    REMEDY_REDEPLOY,
    REMEDY_WRITE_GATED,
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
        self.assertIsNone(card["next"])
        self.assertFalse(card["frozen_menu"])

    def test_lagging_public_deploy_is_red_and_names_remedy_per_verb(self):
        card = preflight(LIVE_2026_09_04, url="https://convoy.bot/mcp")
        self.assertFalse(card["ok"])
        self.assertEqual(card["status"], "RED")
        # onboard, bring_up, send are live already; the rest are missing.
        self.assertEqual(card["missing"], [v for v in REQUIRED_WIZARD_VERBS if v not in LIVE_2026_09_04])
        self.assertEqual(card["reason"], "required-tools-missing")
        self.assertFalse(card["mutation_attempted"])
        packaged = {t["name"] for t in TOOLS}
        for verb in card["missing"]:
            self.assertIn(verb, packaged, verb + " must be a packaged tool on this branch")
        # Every required verb is packaged now. Read verbs are a redeploy away;
        # the write verbs stay hidden until the deploy opts in. (Until item F
        # this named join/seat/launch/mint and choices; the wizard no longer
        # calls those - card and crew replaced them - so they left the set.)
        for verb in ("card", "neurons", "inbox", "graph"):
            self.assertEqual(card["remedy"][verb], REMEDY_REDEPLOY, verb)
        # crew mints git worktrees and spawns, repos runs gh as the host's
        # login, consent mints a grant, await_seated holds the request.
        for verb in ("crew", "repos", "consent", "await_seated"):
            self.assertEqual(card["remedy"][verb], REMEDY_WRITE_GATED, verb)
        self.assertEqual(card["next"], "enable-write-tools-on-deploy")
        self.assertIn("redeploy the public MCP", card["ask"])
        self.assertIn("CONVOY_MCP_WRITE_TOOLS=1", card["ask"])
        self.assertIn("not a source checkout", card["ask"])
        self.assertNotIn("python -m convoy", card["ask"], "the card must not offer a CLI fallback to a marketplace install")

    def test_only_lagging_read_tools_point_at_redeploy(self):
        listed = [v for v in REQUIRED_WIZARD_VERBS if v != "graph"]
        card = preflight(listed)
        self.assertEqual(card["missing"], ["graph"])
        self.assertEqual(card["remedy"], {"graph": REMEDY_REDEPLOY})
        self.assertEqual(card["next"], "reconnect-or-redeploy-mcp")

    def test_write_gated_verbs_point_at_the_deploy_switch(self):
        gated = ("repos", "onboard", "crew", "consent", "await_seated")
        listed = [v for v in REQUIRED_WIZARD_VERBS if v not in gated]
        card = preflight(listed)
        self.assertEqual(card["missing"], list(gated), "missing keeps the constant's order")
        self.assertEqual(card["remedy"], {v: REMEDY_WRITE_GATED for v in gated})
        self.assertEqual(card["next"], "enable-write-tools-on-deploy")
        self.assertNotIn("redeploy the public MCP", card["ask"])

    def test_unregistered_verb_is_not_a_redeploy_problem(self):
        # Shrink the packaged set: a verb the server does not register at all
        # needs a server commit; a redeploy cannot conjure it.
        with mock.patch("convoy.wizard_preflight.PACKAGED_TOOLS", [{"name": "graph"}]):
            card = preflight(["roster"])
        self.assertEqual(card["remedy"]["graph"], REMEDY_REDEPLOY)
        self.assertEqual(card["remedy"]["card"], REMEDY_NOT_REGISTERED)
        self.assertEqual(card["next"], "mcp-server-commit")
        self.assertIn("server needs a commit", card["ask"])

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
        self.assertEqual(card["reason"], "tools-list-failed")
        self.assertEqual(card["next"], "reconnect-or-redeploy-mcp")
        self.assertIn("propose seats", card["ask"])

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
        self.assertEqual(card["remedy"]["crew"], REMEDY_WRITE_GATED)


if __name__ == "__main__":
    unittest.main()
