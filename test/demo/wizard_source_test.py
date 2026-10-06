"""The docs and source say where the wizard's verb list lives, and point at no deleted path.

The convoy-wizard skill is not in Deploy-Forward/plugins, so no doc may say the plugins carry
every Convoy skill or that the wizard's Gate 0 lives in a plugin skill. REQUIRED_WIZARD_VERBS in
wizard_preflight is the list's only source; this module checks it against the packaged server.
"""
import re
import unittest
from pathlib import Path

from convoy import wizard_preflight

REPO = Path(__file__).resolve().parents[2]
DELETED_PATHS = re.compile(r"(?<![\w/.-])(?:plugin|plugins)/convoy/|skills/convoy-wizard")


def _docs_and_source() -> list[Path]:
    files = [REPO / n for n in ("README.md", "SPEC.md", "CANON.md") if (REPO / n).is_file()]
    files += sorted((REPO / "docs").glob("*.md"))
    files += sorted((REPO / "src" / "convoy").rglob("*.py"))
    return files


class WizardSource(unittest.TestCase):
    def test_no_doc_or_source_names_a_deleted_plugin_path(self):
        hits = []
        for f in _docs_and_source():
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if DELETED_PATHS.search(line):
                    hits.append(f"{f.relative_to(REPO).as_posix()}:{n}")
        self.assertEqual(hits, [])

    def test_the_readme_does_not_say_the_plugins_carry_every_skill(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("every Convoy skill", text)
        self.assertIn("convoy-wizard", text)

    def test_the_verb_list_does_not_claim_a_plugin_skill_as_its_source(self):
        src = Path(wizard_preflight.__file__).read_text(encoding="utf-8")
        self.assertNotIn("in the convoy plugin's skills", src)
        self.assertIn("only source", src)

    def test_every_required_wizard_verb_is_a_packaged_tool(self):
        packaged = set(wizard_preflight.packaged_tool_names())
        self.assertEqual([v for v in wizard_preflight.REQUIRED_WIZARD_VERBS if v not in packaged], [])


if __name__ == "__main__":
    unittest.main()
