"""The host contract this repo cannot settle (wizard item F, 2026-09-04).

Whether Grok Bot maps the convoy skill to `@convoy` or `/convoy`, and whether
it renders the card tool's structuredContent as a card (the way `@treg` renders
its provider drill-down), is a fact about the HOST. No test here can observe
it: there is no host in the suite and the public URL is not live. So the claim
is held in test/demo/fixtures/host_rendering.json with every value null, the
README says "Host rendering: unverified", and this test skips.

Once Marco verifies it live he records what he saw (verified: true|false,
verified_on, invocation, renders_structured_content_as_card, evidence) and the
same test starts asserting the recorded contract and that the README stopped
saying unverified. The fixture and the README may not disagree in either state.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "test" / "demo" / "fixtures" / "host_rendering.json"
README = REPO / "plugin" / "convoy" / "README.md"
FIELDS = ("verified", "verified_on", "host", "invocation", "renders_structured_content_as_card", "evidence")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8-sig"))


def _readme_line() -> str:
    lines = [ln for ln in README.read_text(encoding="utf-8-sig").splitlines() if ln.startswith("Host rendering:")]
    assert len(lines) == 1, "plugin/convoy/README.md must carry exactly one 'Host rendering:' line, found " + repr(lines)
    return lines[0]


class HostRenderingContract(unittest.TestCase):
    def test_fixture_has_the_contract_fields_and_the_readme_agrees_on_the_state(self):
        fx = _fixture()
        for field in FIELDS:
            self.assertIn(field, fx, field)
        self.assertEqual(fx["host"], "grok-bot")
        line = _readme_line()
        if fx["verified"] is None:
            # unverified: every observed value is null, and the README says so
            for field in ("verified_on", "invocation", "renders_structured_content_as_card", "evidence"):
                self.assertIsNone(fx[field], field + " must stay null until the host is observed live")
            self.assertIn("unverified", line)
        else:
            self.assertNotIn("unverified", line, "the fixture is verified; the README still says unverified")
            self.assertIn(str(fx["verified_on"])[:10], line, "the README line must carry the verification date")

    def test_recorded_host_contract(self):
        fx = _fixture()
        if fx["verified"] is None:
            self.skipTest("host rendering unverified: record it in " + str(FIXTURE.relative_to(REPO)) + " after a live @convoy run")
        self.assertIsInstance(fx["verified"], bool)
        self.assertRegex(str(fx["verified_on"]), r"^\d{4}-\d{2}-\d{2}")
        self.assertTrue(str(fx["evidence"] or "").strip(), "a verified contract quotes what was seen")
        self.assertIn(fx["invocation"], ("@convoy", "/convoy"))
        self.assertIsInstance(fx["renders_structured_content_as_card"], bool)


if __name__ == "__main__":
    unittest.main()
