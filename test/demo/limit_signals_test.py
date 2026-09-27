"""Per-harness limit-signal classifier.

Fixture text is built from known phrase families (`"You've hit your spend
limit"`, `"Reset occurs at 6:14 PM"`, and the SuperGrok/week-percent and
Claude-usage-limit families, named without a literal quote) plus a plausible
surrounding sentence — not a captured
screenshot from a live run. Expected reason/resetsAt/fallbacks values below
are worked out by hand from the fixture text, independent of
`limit_signals.py`'s own logic, per the repo's testing standard against
tautological assertions.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.limit_signals import classify_limit_text  # noqa: E402


class LimitSignals(unittest.TestCase):
    def test_cursor_spend_limit_yields_spend_with_reset_date(self):
        text = (
            "You've hit your spend limit. Your team's spend limit for this "
            "billing cycle has been reached and requests are paused until it "
            "resets on 2026-10-01."
        )
        signal = classify_limit_text("cursor-agent", text)
        self.assertEqual(
            signal,
            {
                "reason": "spend",
                "resetsAt": "2026-10-01T00:00:00Z",
                "fallbacks": ["codex", "claude", "grok", "agy"],
            },
        )

    def test_grok_weekly_quota_yields_quota_with_reset_date(self):
        text = (
            "SuperGrok weekly limit reached: you've used 100% of your usage "
            "this week. Your quota resets on September 22, 2026."
        )
        signal = classify_limit_text("grok", text)
        self.assertEqual(
            signal,
            {
                "reason": "quota",
                "resetsAt": "2026-09-22T00:00:00Z",
                "fallbacks": ["cursor-agent", "codex", "claude", "agy"],
            },
        )

    def test_codex_reset_time_yields_rate_with_null_reset(self):
        text = "You've hit your usage limit. Reset occurs at 6:14 PM."
        signal = classify_limit_text("codex", text)
        self.assertEqual(
            signal,
            {
                "reason": "rate",
                "resetsAt": None,
                "fallbacks": ["cursor-agent", "claude", "grok", "agy"],
            },
        )

    def test_claude_usage_limit_yields_quota_with_null_reset(self):
        text = "Claude usage limit reached. Try again later."
        signal = classify_limit_text("claude", text)
        self.assertEqual(
            signal,
            {
                "reason": "quota",
                "resetsAt": None,
                "fallbacks": ["cursor-agent", "codex", "grok", "agy"],
            },
        )

    def test_unrelated_text_yields_null_never_a_guess(self):
        self.assertIsNone(classify_limit_text("claude", "Here is your answer."))
        self.assertIsNone(classify_limit_text("codex", ""))
        self.assertIsNone(classify_limit_text("grok", "SuperGrok says hello."))

    def test_unknown_harness_yields_null(self):
        self.assertIsNone(classify_limit_text("agy", "Claude usage limit reached."))
        self.assertIsNone(classify_limit_text("nonexistent-harness", "spend limit"))

    def test_alias_resolves_before_matching(self):
        text = "You've hit your usage limit. Reset occurs at 6:14 PM."
        self.assertEqual(
            classify_limit_text("codex.exe", text),
            classify_limit_text("codex", text),
        )


if __name__ == "__main__":
    unittest.main()
