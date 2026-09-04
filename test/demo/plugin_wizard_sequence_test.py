import re
import unittest
from pathlib import Path

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

    def _index(self, needle: str) -> int:
        hits = [i for i, s in enumerate(self.steps) if needle in s]
        self.assertTrue(hits, "no wizard step mentions " + repr(needle))
        return hits[0]

    def test_real_sequence_order(self):
        github = self._index("GitHub?")
        repo = self._index("repository path or URL")
        preflight = self._index("tools/list")
        choices = self._index("Query live choices")
        count = self._index("`N` neurons")
        effort = self._index("harness_effort.json")
        launch = self._index("join --launch")
        bind = self._index("bind --thread")
        graph = self._index("Confirm topology")
        self.assertLess(github, repo)
        self.assertLess(repo, preflight)
        self.assertLess(preflight, choices, "preflight must run before any live choices are proposed")
        self.assertLess(choices, count)
        self.assertLess(count, effort)
        self.assertLess(effort, launch)
        self.assertLess(launch, bind)
        self.assertLess(bind, graph)

    def test_preflight_is_fail_closed_and_names_required_verbs(self):
        step = self.steps[self._index("tools/list")]
        self.assertIn("fail-closed", step)
        for verb in ("choices", "graph", "inbox", "join", "launch", "seat"):
            self.assertIn("`" + verb + "`", step)
        self.assertIn("never freeze a static tool menu", step)
        self.assertIn("`redeploy`", step)
        self.assertIn("`cli-only`", step)
        self.assertIn("stop", step)

    def test_effort_comes_from_the_pack_not_src(self):
        step = self.steps[self._index("harness_effort.json")]
        self.assertIn("plugin/convoy/harness_effort.json", step)
        self.assertIn("no `src/` checkout", step)

    def test_c8_one_chair_per_worktree(self):
        step = self.steps[self._index("join --launch")]
        self.assertIn("C8", step)
        self.assertIn("one worktree, one chair", step)
        self.assertIn("one `cvy_*` thread", step)

    def test_bind_needs_consent(self):
        step = self.steps[self._index("bind --thread")]
        self.assertIn("approved", step)
        self.assertIn("pre-authorized", step)
        self.assertIn("consent --grant", step)


if __name__ == "__main__":
    unittest.main()
