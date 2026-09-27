"""Classify a harness's own limit/exhaustion text into a structured signal.

Scope: the table and the classifier only. What reads a harness's first pane
output through a pseudo-console, and what refuses `seated` or writes the seat
row's `failed: quota`, come later and are not built here. This module
only answers, given a harness id and a chunk of that harness's own output,
whether it names an exhaustion and what Convoy can read from it — nothing
here writes a seat row or launches anything.

New module, not an addition to `harness_contract.py`: that module's whole job
is loading and querying the static JSON contract (flags, efforts, models),
one row lookup per call. Classifying free-form vendor text is a different
kind of interface — pattern matching over prose, not a keyed lookup — and
giving it its own module keeps `harness_contract.py`'s interface (a pure
contract accessor) from picking up a second, unrelated responsibility.

Fixture text below is built from known phrase families (`"You've hit your
spend limit"`, `"Reset occurs at 6:14 PM"`, and the SuperGrok/week-percent
and Claude-usage-limit families, named without a literal quote) plus a
plausible surrounding sentence. It is not a captured
screenshot; the test file says so at the top. A harness with no row in the
table below always classifies to `None`, for any text — unverified stays
unverified, never a guess.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .harness_contract import canonical_harness_id

ALL_HARNESS_IDS: tuple[str, ...] = ("cursor-agent", "codex", "claude", "grok", "agy")
REASONS: tuple[str, ...] = ("quota", "spend", "rate")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _iso_midnight_utc(year: int, month: int, day: int) -> str:
    return datetime(year, month, day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reset_from_iso_date(match: re.Match[str]) -> str | None:
    """`resets on 2026-10-01` — a bare calendar date, no clock time or zone.
    Convoy reports that date's own midnight UTC; it anchors the day the text
    named, it does not guess which zone the vendor meant by it."""
    year, month, day = (int(part) for part in match.group("date").split("-"))
    return _iso_midnight_utc(year, month, day)


def _reset_from_month_name_date(match: re.Match[str]) -> str | None:
    """`September 22, 2026` — same midnight-UTC anchor convention."""
    month = _MONTHS[match.group("month").lower()]
    day = int(match.group("day"))
    year = int(match.group("year"))
    return _iso_midnight_utc(year, month, day)


def _no_reset(_match: re.Match[str]) -> None:
    """The family names a bare clock time, or no reset info at all — never a
    full date. A clock time with no day and no zone is not enough to build
    one safe instant (today's date depends on when Convoy happens to read
    it), so resetsAt stays null even though a time is visible in the text."""
    return None


# One row per harness, in match order (first hit for that harness wins, so
# keep a harness's own families disjoint). `pattern` must match the
# harness's own text; `resets_at` reads resetsAt out of the match, or None.
_TABLE: tuple[dict[str, Any], ...] = (
    {
        "harness": "cursor-agent",
        "reason": "spend",
        "pattern": re.compile(
            r"you.?ve hit your spend limit.*?resets on (?P<date>\d{4}-\d{2}-\d{2})",
            re.IGNORECASE | re.DOTALL,
        ),
        "resets_at": _reset_from_iso_date,
    },
    {
        "harness": "grok",
        "reason": "quota",
        "pattern": re.compile(
            r"supergrok weekly limit reached.*?resets on "
            r"(?P<month>[a-zA-Z]+) (?P<day>\d{1,2}), (?P<year>\d{4})",
            re.IGNORECASE | re.DOTALL,
        ),
        "resets_at": _reset_from_month_name_date,
    },
    {
        "harness": "codex",
        "reason": "rate",
        "pattern": re.compile(r"reset occurs at \d{1,2}:\d{2}\s*[ap]m", re.IGNORECASE),
        "resets_at": _no_reset,
    },
    {
        "harness": "claude",
        "reason": "quota",
        "pattern": re.compile(r"claude usage limit reached", re.IGNORECASE),
        "resets_at": _no_reset,
    },
)


def _fallbacks_for(harness_id: str) -> list[str]:
    """The other four of the five, never the exhausted one. Static over the
    five harnesses Convoy knows — not a live probe of who else is available;
    a fallback that is itself at its limit is a separate concern."""
    wanted = canonical_harness_id(harness_id)
    return [h for h in ALL_HARNESS_IDS if h != wanted]


def classify_limit_text(harness_id: str, text: Any) -> dict[str, Any] | None:
    """Read one harness's own output for its exhaustion family.

    Returns `{"reason", "resetsAt", "fallbacks"}` when the text matches that
    harness's row in the table; `None` otherwise — an unknown harness, a
    harness with no row yet, or text that does not match its family. Never a
    partial guess: a match yields all three fields, a non-match yields
    nothing.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    wanted = canonical_harness_id(harness_id)
    for row in _TABLE:
        if row["harness"] != wanted:
            continue
        match = row["pattern"].search(text)
        if not match:
            continue
        return {
            "reason": row["reason"],
            "resetsAt": row["resets_at"](match),
            "fallbacks": _fallbacks_for(wanted),
        }
    return None
