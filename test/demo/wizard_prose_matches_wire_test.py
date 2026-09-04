"""Prose about the wire must agree with the wire.

The vision readers (2026-09-04) found three places that said a registered MCP
tool did not exist: wizard_preflight.py's docstring kept a "CLI-only" remedy
the classifier no longer has; plugin/convoy/README.md said six wizard verbs
"have no MCP tool on main at all"; plugin/convoy/skills/convoy/SKILL.md listed
seat/join/choices/launch as "CLI-only, never on the wire". All six have been
registered since PR 50 (mcp_http.TOOLS). A skill or README that denies a tool
the server serves makes the wizard refuse work it can do - the honesty bar cuts
both ways.

The repo-root sheet skills/convoy/SKILL.md still had that CLI-only list
(multiline, so a same-line regex missed `seat`/`join`/`choices`/`launch`/
`consent`) after Gate 0 moved on; this test now covers that file and every
name in TOOLS, not only current Gate 0.

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
    "skills/convoy/SKILL.md": REPO / "skills" / "convoy" / "SKILL.md",
}
# Each pattern, with a verb substituted, is a claim that the verb is NOT served.
# Same-line only: a multiline "CLI-only: `a`,\\n`b`" list is caught separately.
DENIALS = (
    r"`{v}`[^.\n]{{0,80}}\bno MCP tool\b",
    r"\bno MCP tool\b[^.\n]{{0,120}}`{v}`",
    r"`{v}`[^.\n]{{0,80}}\bnever on the wire\b",
    r"\bCLI-only\b[^.\n]{{0,120}}`{v}`",
    r"`{v}`[^.\n]{{0,80}}\bCLI-only\b",
)
CLI_ONLY_LIST = re.compile(
    r"(?:CLI-only|never on the wire)\s*:?\s*(.*?)(?:\.(?:\s|$))",
    re.I | re.S,
)


def _registered_tool_names():
    return [str(t["name"]) for t in TOOLS]


def _registered_wizard_verbs():
    names = set(_registered_tool_names())
    return [v for v in wp.REQUIRED_WIZARD_VERBS if v in names]


def _cli_only_listed_names(text: str) -> list[str]:
    names = []
    for m in CLI_ONLY_LIST.finditer(text):
        names.extend(re.findall(r"`([A-Za-z][A-Za-z0-9_-]*)`", m.group(1)))
    return names


class WizardProseMatchesWire(unittest.TestCase):
    def test_every_gate0_verb_is_registered_so_the_denials_would_all_be_false(self):
        # Precondition for the rest: if this fails the docs may be RIGHT and
        # the server wrong. The reader must decide which, not this test.
        names = set(_registered_tool_names())
        missing = [v for v in wp.REQUIRED_WIZARD_VERBS if v not in names]
        self.assertEqual(missing, [], "Gate 0 verbs not registered on this build: " + repr(missing))

    def test_no_doc_denies_a_registered_verb(self):
        registered = set(_registered_tool_names())
        offenders = []
        for label, path in DOCS.items():
            text = path.read_text(encoding="utf-8-sig")
            for verb in registered:
                for pat in DENIALS:
                    m = re.search(pat.format(v=re.escape(verb)), text)
                    if m:
                        offenders.append((label, verb, m.group(0)[:100]))
            for verb in _cli_only_listed_names(text):
                if verb in registered:
                    offenders.append((label, verb, "cli-only-list"))
        self.assertEqual(offenders, [], "docs deny a tool the server serves:\n" + "\n".join(map(str, offenders)))

    def test_preflight_docstring_names_only_remedies_the_classifier_has(self):
        doc = wp.__doc__ or ""
        self.assertNotIn("CLI-only", doc, "docstring describes a remedy class that was removed")
        for remedy in (wp.REMEDY_REDEPLOY, wp.REMEDY_NOT_REGISTERED, wp.REMEDY_WRITE_GATED):
            self.assertIn(remedy, doc, "docstring should name the real remedy classes")

    def test_docs_explain_the_gate_for_the_hidden_verbs(self):
        # The TRUE reason a public tools/list lacks seat/join/launch/onboard is
        # the write gate. Whichever doc talks about the public catalog lagging
        # must attribute the hidden verbs to the gate, not to non-existence.
        # onboard joined the gate 2026-09-04 (item D): it binds the thread and
        # clones a URL. mint (spawns git) and repos (gh as the host's login)
        # joined after review the same day. crew (mints, joins, may spawn),
        # consent (mints a grant) and await_seated (holds the request thread)
        # joined with item E.
        # The set shrank when the wizard stopped driving chairs one at a time:
        # crew mints, joins and launches in ONE call, so join/launch/seat/mint
        # stay gated tools but are no longer verbs Gate 0 requires (item F).
        gated = sorted(v for v in _registered_wizard_verbs() if v in _WRITE_TOOLS)
        self.assertEqual(gated, ["await_seated", "clone", "consent", "crew", "onboard", "repos"])
        readme = DOCS["plugin/convoy/README.md"].read_text(encoding="utf-8-sig")
        self.assertIn("CONVOY_MCP_WRITE_TOOLS", readme, "README must name the gate that hides seat/join/launch")
        for verb in gated:
            self.assertIn("`" + verb + "`", readme, "README must name " + verb + " among the write-gated verbs")
        pack_skill = DOCS["plugin/convoy/skills/convoy/SKILL.md"].read_text(encoding="utf-8-sig")
        self.assertIn("write-gated", pack_skill, "pack skill must name the third #51 class, not only redeploy/not-registered")
        self.assertIn("`card`", pack_skill, "pack skill must read model/effort from card, not only choices")


if __name__ == "__main__":
    unittest.main()
