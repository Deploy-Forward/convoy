import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.mcp_http import TOOLS
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS

REPO = Path(__file__).resolve().parents[2]
WIZARD = REPO / "plugin" / "convoy" / "skills" / "convoy-wizard" / "SKILL.md"


def _steps(text: str) -> list[str]:
    """Numbered steps of the mandatory sequence, each with its sub-bullets."""
    section = text.split("## Mandatory wizard sequence", 1)[1].split("\n## ", 1)[0]
    parts = re.split(r"(?m)^\d+\. ", section)
    return [p.strip() for p in parts[1:]]


def _flat(text: str) -> str:
    """One line, single-spaced. These tests assert what the prose CLAIMS, and
    a claim that wrapped across a line ('one chair per\\n   worktree') is still
    the claim - matching layout instead of content made a green test go red on
    a reflow (live 2026-09-04)."""
    return " ".join(text.split())


def _backticked_tools(text: str) -> set[str]:
    registered = {str(t["name"]) for t in TOOLS}
    return {m for m in re.findall(r"`([a-z_]+)`", text) if m in registered}


class WizardSequence(unittest.TestCase):
    def setUp(self):
        self.text = WIZARD.read_text(encoding="utf-8")
        self.steps = _steps(self.text)
        self.gate0 = self.text.split("## Gate 0:", 1)[1].split("\n## ", 1)[0]
        self.sequence = self.text.split("## Mandatory wizard sequence", 1)[1]

    def _index(self, needle: str) -> int:
        flat = _flat(needle)
        hits = [i for i, s in enumerate(self.steps) if flat in _flat(s)]
        self.assertTrue(hits, "no wizard step mentions " + repr(needle))
        return hits[0]

    def test_real_sequence_order(self):
        # Gate 0 is fail-closed preflight before any numbered step; card is
        # read ONCE before step 1 and every step reads from it (item F).
        self.assertIn("tools/list", self.gate0)
        preamble = self.sequence.split("\n1. ", 1)[0]
        self.assertIn("call `card` ONCE", preamble)
        github = self._index("GitHub?")
        repo = self._index("repository path or URL")
        onboard = self._index("Call `onboard`")
        count = self._index("`N` neurons")
        crew = self._index("call `crew`")
        consent = self._index("call `consent`")
        seated = self._index("Call `await_seated`")
        graph = self._index("`graph`")
        self.assertLess(github, repo)
        self.assertLess(repo, onboard)
        self.assertLess(onboard, count)
        self.assertLess(count, crew)
        self.assertLess(crew, consent)
        self.assertLess(consent, seated)
        # verification (neurons + graph) shares the await_seated step; send is last
        self.assertEqual(seated, graph)
        self.assertLess(graph, self._index("Route work with `send`"))

    def test_preflight_is_fail_closed_and_names_required_verbs(self):
        self.assertIn("fail-closed", self.gate0.lower().replace("fail closed", "fail-closed"))
        self.assertTrue("fail-closed" in self.gate0 or "fail closed" in self.gate0)
        for verb in REQUIRED_WIZARD_VERBS:
            self.assertIn("`" + verb + "`", self.gate0, "Gate 0 must name every verb the preflight module requires")
        self.assertIn("never freeze a static tool menu", self.gate0)
        self.assertIn("stop", self.gate0.lower())
        self.assertTrue(
            "redeploy" in self.gate0.lower() or "upgrade-plugin" in self.gate0,
            "gate must name redeploy/upgrade remedy",
        )

    def test_gate0_list_equals_the_preflight_constant(self):
        # The verb-count drift (item F review, 2026-09-04): Gate 0's prose list
        # and REQUIRED_WIZARD_VERBS were checked one way only (constant subset
        # of prose), so prose could require a verb the module never scored, or
        # keep one the wizard stopped calling. Equal sets, both directions.
        self.assertEqual(_backticked_tools(self.gate0), set(REQUIRED_WIZARD_VERBS))
        self.assertIn("card", REQUIRED_WIZARD_VERBS)

    def test_every_registered_verb_the_sequence_calls_is_a_gate0_requirement(self):
        # review 2026-09-04: step 4 said "call `mint` once" while Gate 0 and
        # REQUIRED_WIZARD_VERBS omitted mint, so a live list without mint passed
        # GREEN and step 4 then called an unpromised verb - the fail-open Gate 0
        # forbids. Derived from TOOLS, not a frozen list: any registered verb
        # the sequence backticks must be required by the preflight module.
        called = _backticked_tools(self.sequence)
        self.assertIn("crew", called, "precondition: the sequence still calls crew")
        self.assertIn("card", called, "precondition: the sequence reads card")
        unrequired = sorted(v for v in called if v not in REQUIRED_WIZARD_VERBS)
        self.assertEqual(unrequired, [], "sequence calls verbs Gate 0 does not require: " + repr(unrequired))

    def test_model_effort_and_usage_come_from_card_never_a_file(self):
        # Until 2026-09-04 (item F) Gate 0 had the host verify the pack's
        # ../../harness_effort.json and a step read model/effort from it. A
        # remote host has no filesystem: every constraint now rides on card
        # (rows[].models, rows[].effort, rows[].usage_remaining) and the skill
        # names no path at all. The pack copy still ships (other tests hold it
        # byte-identical) as the endpoint's contract, not the wizard's input.
        step = self.steps[self._index("rows[].models")]
        self.assertIn("`card", step)
        self.assertIn("rows[].effort", step)
        self.assertIn("rows[].usage_remaining", step)
        self.assertIn("never as 0", step)
        for path_like in ("../../", "src/convoy/", "relative to this `SKILL.md`", "present and readable"):
            self.assertNotIn(path_like, self.text, "the wizard must not read from a filesystem: " + path_like)
        self.assertNotIn("pack-asset-missing", self.gate0)

    def test_c8_one_chair_per_worktree(self):
        step = self.steps[self._index("one chair per worktree")]
        self.assertIn("one chair per worktree", _flat(step))
        crew_step = self.steps[self._index("call `crew`")]
        self.assertIn("cvy_*", crew_step)
        self.assertEqual(step, crew_step, "crew mints the worktrees, so the rule lives on its step")

    def test_bind_needs_consent(self):
        # Bind is onboard(thread, checkout_root) after approval; consent is its own step.
        bindish = self.steps[self._index("onboard")]
        self.assertIn("approval", bindish.lower() + self.steps[self._index("repository path or URL")].lower())
        consent = self.steps[self._index("consent")]
        self.assertIn("approves", consent)
        self.assertNotIn("pre-authorized", consent)


if __name__ == "__main__":
    unittest.main()
