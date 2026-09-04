"""Prose about the wire must agree with the wire.

The vision readers (2026-09-04) found three places that said a registered MCP
tool did not exist: wizard_preflight.py's docstring kept a "CLI-only" remedy
the classifier no longer has; plugin/convoy/README.md said six wizard verbs
"have no MCP tool on main at all"; plugin/convoy/skills/convoy/SKILL.md listed
seat/join/choices/launch as "CLI-only, never on the wire". All six have been
registered since PR 50 (mcp_http.TOOLS). A skill or README that denies a tool
the server serves makes the wizard refuse work it can do - the honesty bar cuts
both ways.

Truth here is DERIVED from mcp_http.TOOLS and _WRITE_TOOLS, never a frozen
list, so this test cannot itself drift. It checks the docs for the specific
false claims, per registered verb, rather than for phrasing.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import convoy.wizard_preflight as wp
from convoy.mcp_http import TOOLS, _WRITE_TOOLS

REPO = Path(__file__).resolve().parents[2]
DOCS = {
    "plugin/convoy/README.md": REPO / "plugin" / "convoy" / "README.md",
    "plugin/convoy/skills/convoy/SKILL.md": REPO / "plugin" / "convoy" / "skills" / "convoy" / "SKILL.md",
    "plugin/convoy/skills/convoy-wizard/SKILL.md": REPO / "plugin" / "convoy" / "skills" / "convoy-wizard" / "SKILL.md",
}
# Each pattern, with a verb substituted, is a claim that the verb is NOT served.
DENIALS = (
    r"`{v}`[^.\n]{{0,80}}\bno MCP tool\b",
    r"\bno MCP tool\b[^.\n]{{0,120}}`{v}`",
    r"`{v}`[^.\n]{{0,80}}\bnever on the wire\b",
    r"\bCLI-only\b[^.\n]{{0,120}}`{v}`",
    r"`{v}`[^.\n]{{0,80}}\bCLI-only\b",
)


def _registered_wizard_verbs():
    names = {str(t["name"]) for t in TOOLS}
    return [v for v in wp.REQUIRED_WIZARD_VERBS if v in names]


class WizardProseMatchesWire(unittest.TestCase):
    def test_every_gate0_verb_is_registered_so_the_denials_would_all_be_false(self):
        # Precondition for the rest: if this fails the docs may be RIGHT and
        # the server wrong. The reader must decide which, not this test.
        names = {str(t["name"]) for t in TOOLS}
        missing = [v for v in wp.REQUIRED_WIZARD_VERBS if v not in names]
        self.assertEqual(missing, [], "Gate 0 verbs not registered on this build: " + repr(missing))

    def test_no_doc_denies_a_registered_verb(self):
        offenders = []
        for label, path in DOCS.items():
            text = path.read_text(encoding="utf-8-sig")
            for verb in _registered_wizard_verbs():
                for pat in DENIALS:
                    m = re.search(pat.format(v=re.escape(verb)), text)
                    if m:
                        offenders.append((label, verb, m.group(0)[:100]))
        self.assertEqual(offenders, [], "docs deny a tool the server serves:\n" + "\n".join(map(str, offenders)))

    def test_preflight_docstring_names_only_remedies_the_classifier_has(self):
        doc = wp.__doc__ or ""
        self.assertNotIn("CLI-only", doc, "docstring describes a remedy class that was removed")
        for remedy in (wp.REMEDY_REDEPLOY, wp.REMEDY_NOT_REGISTERED, wp.REMEDY_WRITE_GATED):
            self.assertIn(remedy, doc, "docstring should name the real remedy classes")

    def test_docs_explain_the_gate_for_the_hidden_verbs(self):
        # The TRUE reason a public tools/list lacks seat/join/launch is the
        # write gate. Whichever doc talks about the public catalog lagging must
        # attribute the hidden verbs to the gate, not to non-existence.
        gated = sorted(v for v in _registered_wizard_verbs() if v in _WRITE_TOOLS)
        self.assertEqual(gated, ["join", "launch", "seat"])
        readme = DOCS["plugin/convoy/README.md"].read_text(encoding="utf-8-sig")
        self.assertIn("CONVOY_MCP_WRITE_TOOLS", readme, "README must name the gate that hides seat/join/launch")


if __name__ == "__main__":
    unittest.main()
