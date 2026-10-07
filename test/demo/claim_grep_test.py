"""No false claim about a hosted Convoy survives in the shipped tree.

convoy.bot/mcp was a hosted attach point reached through a tunnel to one
laptop. It is retired: Convoy's MCP runs on your machine at
http://127.0.0.1:8788/mcp, and there is no hosted Convoy endpoint. The words
that described the old endpoint ("convoy.bot", "Grok Bot MCP", "grok-bot
native") must not appear in the package, its metadata, the README or the spec.
Nor may the words for what 1.3.2 removed with it: the "tunnel task" an install
registered, the "legacy-flag" write gate and the "public URL" it served.

The wider scan covers every tracked file. A hit is allowed only in a dated
history document that says, in a banner, that it is superseded; that list is
explicit here so a new hit cannot hide in a doc nobody reads.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAIM = re.compile(r"convoy\.bot|grok bot mcp|grok-bot native|tunnel task|legacy-flag|public url", re.I)
SHIPPED = ("src", "pyproject.toml", "README.md", "SPEC.md")
BANNER = "Superseded 2026-10: convoy.bot/mcp is retired"
# Dated history: each records a run or a decision against the retired endpoint.
HISTORY = frozenset({
    "docs/LANDSCAPE_RUNTIME_VS_SOT.md",
    "docs/e2e-dod.md",
    "docs/live-certification-2026-09-06.md",
    "docs/audits/OPUS1_STRESS.md",
    "docs/amendment-2026-09-12-productize.md",
})
THIS_FILE = "test/demo/claim_grep_test.py"
# The closed repo's name, assembled so this file does not spell it out.
CLOSED_REPO = "/".join(("Deploy-Forward", "platform"))
# Tests that name the words in order to assert their absence.
ABSENCE_TESTS = frozenset({THIS_FILE, "test/demo/loopback_mcp_test.py"})


def _tracked() -> list[str]:
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, timeout=60)
    if r.returncode != 0:
        return [p.relative_to(REPO).as_posix() for p in REPO.rglob("*")
                if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts]
    return [x for x in r.stdout.decode("utf-8").split("\0") if x]


def _hits(rel: str) -> list[str]:
    path = REPO / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [str(i) + ": " + line.strip()[:120] for i, line in enumerate(text.splitlines(), 1) if CLAIM.search(line)]


class ClaimGrep(unittest.TestCase):
    def test_the_package_metadata_readme_and_spec_make_no_hosted_claim(self):
        found = {}
        for rel in _tracked():
            if rel == THIS_FILE or not any(rel == s or rel.startswith(s + "/") for s in SHIPPED):
                continue
            hits = _hits(rel)
            if hits:
                found[rel] = hits
        for p in (REPO / "src").rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = p.relative_to(REPO).as_posix()
                if rel not in found and _hits(rel):
                    found[rel] = _hits(rel)
        self.assertEqual(found, {})

    def test_every_other_hit_is_a_dated_history_doc_with_a_banner(self):
        outside = {}
        for rel in _tracked():
            if rel in ABSENCE_TESTS or not (REPO / rel).is_file():
                continue
            if _hits(rel) and rel not in HISTORY:
                outside[rel] = _hits(rel)
        self.assertEqual(outside, {}, "a claim outside the allowlist of dated history docs")

    def test_each_history_doc_carries_the_superseded_banner(self):
        for rel in sorted(HISTORY):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn(BANNER, "\n".join(text.splitlines()[:12]), rel + " must open with the superseded banner")

    def test_the_readme_says_where_the_mcp_runs_and_that_remote_access_is_yours(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:8788/mcp", readme)
        self.assertIn("There is no hosted Convoy endpoint", readme)
        self.assertIn("Remote access to your loopback MCP is not a Convoy feature; if you build it, "
                      "put it behind your own access control.", readme)
        self.assertNotIn("Cloudflare split hosting", readme)

    def test_the_spec_header_names_public_repos_only(self):
        head = "\n".join((REPO / "SPEC.md").read_text(encoding="utf-8").splitlines()[:12])
        for gone in (CLOSED_REPO, "/workspace/convoy", "convoy.deployforward.dev", "tweet this"):
            self.assertNotIn(gone, head)

    def test_no_shipped_file_names_the_closed_platform_repo(self):
        found = {}
        for rel in _tracked():
            if rel == THIS_FILE or not any(rel == s or rel.startswith(s + "/") for s in SHIPPED):
                continue
            try:
                text = (REPO / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lines = [i for i, line in enumerate(text.splitlines(), 1) if CLOSED_REPO.lower() in line.lower()]
            if lines:
                found[rel] = lines
        self.assertEqual(found, {})

    def test_the_package_description_is_the_product(self):
        import tomllib
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["description"],
                         "Convoy: local-first multi-agent orchestration CLI and loopback MCP")

    def test_the_mcp_module_docstring_claims_nothing_false(self):
        from convoy import mcp_http
        doc = mcp_http.__doc__ or ""
        self.assertNotIn("Grok Bot", doc)
        self.assertNotIn("One MCP process is bound to one convoy root", doc)
        self.assertIn("http://127.0.0.1:8788/mcp", doc)

    def test_the_conductor_contract_claims_no_public_mcp(self):
        from convoy.conductor import contract_text
        text = contract_text()
        self.assertNotIn("public MCP", text)
        self.assertIn("Your local MCP serves every thread on its machine.", text)
        rule3 = next(line for line in text.splitlines() if line.startswith("3. "))
        self.assertIn("never `nudge` without a consent card", rule3)

    def test_no_tool_description_promises_a_public_deploy(self):
        from convoy.mcp_http import TOOLS
        stale = re.compile(r"public (url|mcp|deploy|process|endpoint)|ungated public", re.I)
        found = {t["name"]: t["description"] for t in TOOLS if stale.search(t.get("description") or "")}
        self.assertEqual(found, {})

    def test_the_gate_contract_speaks_of_bearers_not_a_public_wire(self):
        text = (REPO / "SECURITY_GATES.md").read_text(encoding="utf-8")
        contract = text.split("## Gate contract", 1)[1]
        hits = [line.strip() for line in contract.splitlines() if re.search(r"\bpublic\b", line, re.I)]
        self.assertEqual(hits, [])
        nudge = (REPO / "scripts" / "wt-nudge.ps1").read_text(encoding="utf-8")
        self.assertNotIn("public MCP", nudge)

    def test_note_is_the_neuron_side_write_not_a_hosted_one(self):
        from convoy.mcp_http import TOOLS
        note = next(t for t in TOOLS if t["name"] == "note")
        self.assertNotIn("hosted-neuron", note["description"])
        self.assertNotIn("hosted-neuron", (REPO / "SPEC.md").read_text(encoding="utf-8"))

    def test_no_doc_links_a_file_removed_in_1_3_2_as_if_it_were_there(self):
        gone = ("docs/deploy-convoy-bot-mcp.md", "workers-site.mjs")
        found = {}
        for rel in _tracked():
            if rel in ABSENCE_TESTS or not rel.endswith(".md"):
                continue
            try:
                lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            bad = [i for i, line in enumerate(lines, 1)
                   if any(g in line for g in gone) and "removed in 1.3.2" not in line]
            if bad:
                found[rel] = bad
        self.assertEqual(found, {})

    def test_the_widget_wordmark_is_convoy(self):
        from convoy import widget
        self.assertEqual(widget.WORDMARK, "Convoy")
        page = (REPO / "src" / "convoy" / "widget_page" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<span class="word">Convoy</span>', page)
        js = (REPO / "src" / "convoy" / "widget_page" / "widget.js").read_text(encoding="utf-8")
        self.assertIn('"https://github.com/Deploy-Forward/convoy"', js)


def _flat(rel: str) -> str:
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())


class DocsMatchTheListGate(unittest.TestCase):
    """tools/list hides the write tools only while no bearer is minted on the
    machine (mcp_http._listed_tools). Once one exists they are listed for every
    loopback caller and refused at tools/call without the bearer. The docs must
    say that, not promise a per-caller hide the code does not do."""

    def test_the_gate_contract_states_when_write_tools_are_listed(self):
        text = _flat("SECURITY_GATES.md")
        self.assertNotIn("**must hide**", text)
        self.assertIn("hidden from `tools/list` only while no bearer is minted on this machine", text)
        self.assertIn("listed for every caller and refused at `tools/call` without the bearer", text)

    def test_the_gate_contract_quotes_the_write_set_the_code_enforces(self):
        import ast
        src = (REPO / "src" / "convoy" / "mcp_http.py").read_text(encoding="utf-8")
        code = None
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_WRITE_TOOLS" for t in node.targets):
                code = set(ast.literal_eval(node.value.args[0]))
        self.assertIsNotNone(code, "mcp_http._WRITE_TOOLS not found")
        doc = re.search(r"`_WRITE_TOOLS = (\{[^`]*\})`", (REPO / "SECURITY_GATES.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(doc, "SECURITY_GATES.md no longer quotes _WRITE_TOOLS")
        self.assertEqual(set(ast.literal_eval(doc.group(1))), code)

    def test_the_readme_limits_the_listed_verb_promise_to_the_bearer_holder(self):
        text = _flat("README.md")
        sentence = re.search(r"[^.]*listed verb is a promise[^.]*\.", text)
        self.assertIsNotNone(sentence)
        self.assertIn("bearer", sentence.group(0))
        self.assertIn("listed for every caller", text)

    def test_the_sot_names_no_public_root_and_no_public_wire(self):
        text = _flat("docs/CONVOY_SOT.md")
        self.assertNotIn("public `--root`", text)
        self.assertNotIn("on the public wire", text)
        self.assertIn("Tokens never leave `seats.jsonl` to a caller without a bearer.", text)
        self.assertIn("There is no hosted Convoy endpoint", text)
        self.assertIn("loopback-only", text)

    def test_the_happy_path_needs_a_bearer_not_an_endpoint(self):
        text = _flat("docs/convoy-happy-path.md")
        for stale in ("trusted endpoint", "shared public process", "public plugin"):
            self.assertNotIn(stale, text)
        self.assertIn("Full crew creation needs a conductor bearer (`convoy conductor mint`) sent to your local `convoy mcp`.", text)
        self.assertIn("Without one the write-gated lifecycle tools refuse.", text)

    def test_the_conductor_contract_brings_up_with_a_bearer_not_a_deploy(self):
        from convoy.conductor import contract_text
        text = " ".join(contract_text().split())
        self.assertNotIn("gated deploy", text)
        self.assertIn("`bring_up` with your conductor bearer", text)

    def test_code_comments_speak_of_callers_without_a_bearer(self):
        src = REPO / "src" / "convoy"
        mcp = (src / "mcp_http.py").read_text(encoding="utf-8")
        for stale in ("public tools/list", "ungated public wire", "public endpoint"):
            self.assertNotIn(stale, mcp)
        self.assertNotIn("public wire", " ".join((src / "nudge.py").read_text(encoding="utf-8").split()))
        self.assertNotIn("hosted conductor", " ".join((src / "convoy.py").read_text(encoding="utf-8").split()))

    def test_a_superseded_doc_claims_no_authority(self):
        text = (REPO / "docs" / "LANDSCAPE_RUNTIME_VS_SOT.md").read_text(encoding="utf-8")
        self.assertNotIn("this file is authoritative", text)

    def test_the_build_needs_a_setuptools_that_reads_recursive_globs(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"setuptools>=62.3"', text)


if __name__ == "__main__":
    unittest.main()
