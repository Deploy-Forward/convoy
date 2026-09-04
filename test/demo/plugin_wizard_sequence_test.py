import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS

REPO = Path(__file__).resolve().parents[2]
WIZARD = REPO / "plugin" / "convoy" / "skills" / "convoy-wizard" / "SKILL.md"


def _steps(text: str) -> list[str]:
    """Numbered steps of the mandatory sequence, each with its sub-bullets."""
    section = text.split("## Mandatory wizard sequence", 1)[1].split("\n## ", 1)[0]
    parts = re.split(r"(?m)^\d+\. ", section)
    return [p.strip() for p in parts[1:]]


class WizardSequence(unittest.TestCase):
    def setUp(self):
        self.text = WIZARD.read_text(encoding="utf-8")
        self.steps = _steps(self.text)
        self.gate0 = self.text.split("## Gate 0:", 1)[1].split("\n## ", 1)[0]

    def _index(self, needle: str) -> int:
        hits = [i for i, s in enumerate(self.steps) if needle in s]
        self.assertTrue(hits, "no wizard step mentions " + repr(needle))
        return hits[0]

    def test_real_sequence_order(self):
        # Gate 0 is fail-closed preflight before any numbered step.
        self.assertIn("tools/list", self.gate0)
        github = self._index("GitHub?")
        repo = self._index("repository path or URL")
        choices = self._index("Call live `choices`")
        count = self._index("`N` neurons")
        effort = self._index("harness_effort.json")
        join = self._index("call `join`")
        launch = self._index("call `launch`")
        seat = self._index("call `seat`")
        bring = self._index("call `bring_up`")
        consent = self._index("consent")
        graph = self._index("`graph`")
        self.assertLess(github, repo)
        self.assertLess(repo, choices)
        self.assertLess(choices, count)
        self.assertLess(count, effort)
        self.assertLess(effort, join)
        # join/launch/seat/bring_up share one numbered lifecycle step in the skill
        self.assertEqual(join, launch)
        self.assertEqual(launch, seat)
        self.assertEqual(seat, bring)
        self.assertLess(bring, consent)
        self.assertLess(consent, graph)

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

    def test_model_and_effort_come_from_choices_not_a_file(self):
        # Until 2026-09-04 this step told the host to read the pack's
        # ../../harness_effort.json for model/effort. The constraints ride on
        # the wire (choices.harnesses[].models, .effort); the pack copy is the
        # Gate 0 integrity asset, not the wizard's data source. The step must
        # say so WITHOUT contradicting Gate 0 step 4 (which has the host verify
        # the asset is present) and without asserting what the host platform
        # can or cannot do — nothing in this repo verifies that.
        step = self.steps[self._index("harness_effort.json")]
        self.assertIn("`choices`", step)
        self.assertIn("harnesses[].models", step)
        self.assertIn("harnesses[].effort", step)
        self.assertIn("Gate 0", step, "step must reconcile itself with the Gate 0 asset check")
        self.assertNotIn("no filesystem", self.text)
        self.assertNotIn("never reads", step)
        self.assertNotIn("src/convoy/harness_effort.json", step)
        self.assertNotIn("../../harness_effort.json", step)
        self.assertIn("../../harness_effort.json", self.gate0)

    def test_c8_one_chair_per_worktree(self):
        step = self.steps[self._index("one chair per worktree")]
        self.assertIn("one chair per worktree", step)
        join_step = self.steps[self._index("call `join`")]
        self.assertIn("cvy_*", join_step)

    def test_bind_needs_consent(self):
        # Bind is onboard(thread, checkout_root) after approval; consent is its own step.
        bindish = self.steps[self._index("onboard")]
        self.assertIn("approval", bindish.lower() + self.steps[self._index("repository path or URL")].lower())
        consent = self.steps[self._index("consent")]
        self.assertIn("approves", consent)
        self.assertNotIn("pre-authorized", consent)


if __name__ == "__main__":
    unittest.main()

