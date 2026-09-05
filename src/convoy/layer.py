"""Convoy layer: timestamped hook events. Not vendor --resume.

Feed contract v2 (additive; same file, same single writer, same MCP URL):
schema_version rides the feed envelope, kinds stay open (synapse, refuse+ask,
conductor, attach, note, ...). A conductor stamp is ONE compact line — the
Grok Bot bubble history never lands here; a transcript is a pointer at most.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .usage import normalize_usage_remaining

FEED_NAME = "feed.jsonl"

# Versioned feed contract. v1: bare {ts, kind, instance_id, summary, ...extra}
# rows. v2 adds: conductor stamps (this module), refuse rows carrying the full
# ask card, and schema_version on feed envelopes. Additive only — v1 rows and
# unknown kinds keep flowing; readers skip kinds they do not know.
SCHEMA_VERSION = 2

# Conductor const mirrors convoy.CONDUCTOR (convoy.py imports this module).
_CONDUCTOR = "grok-bot"

STAMP_MAX_CHARS = 500

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def feed_path(root: Path) -> Path:
    p = Path(root) / ".convoy" / FEED_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _is_conductor_alias(val: Any) -> bool:
    # Exact-match refusal is bypassable (Grok-Bot, grok_bot, grokbot):
    # normalize case/spacing/separators before comparing.
    if not isinstance(val, str):
        return False
    return val.strip().lower().replace("_", "").replace("-", "") == "grokbot"


_AUTHOR_IS_INSTANCE = object()


def hook(root: Path, kind: str, summary: str, instance_id: str | None = None, extra: dict[str, Any] | None = None, to: str | None = None, author: Any = _AUTHOR_IS_INSTANCE) -> dict[str, Any]:
    # `from` is AUTHORSHIP, `instance_id` is the row's subject. They coincide
    # on note-family rows (default), but a synapse/refuse row's instance_id is
    # the TARGET session — passing author=None there records "sender unknown"
    # instead of promoting the recipient to author (OPUS-2 verified defect).
    if author is _AUTHOR_IS_INSTANCE:
        author = instance_id
    # The refusal is an AUTHORSHIP rule: it tests author only. instance_id is
    # the row's subject and may legitimately name any seat — refusing it here
    # would raise post-runner on synapse rows, discarding the card and leaving
    # a hop with zero feed rows (opus-1/opus-2 pre-merge finding). Constraining
    # subject names belongs at seat/register write time, where nothing has run.
    if _is_conductor_alias(author):
        raise ValueError("refuse grok-bot as author; conductor identity is stamp-only")
    event = {"ts": utc_now(), "kind": kind, "instance_id": instance_id, "summary": summary}
    if author:
        event["from"] = author
    if to:
        event["to"] = to
    if extra:
        event.update(extra)
    path = feed_path(root)
    # ONE os-level append per row. Four neurons and a lead write this file
    # concurrently; buffered text-mode appends tore a row in two on Windows
    # (live 2026-09-05, feed lines 37-39). O_APPEND + a single write() is the
    # strongest atomicity the OS offers for a small record; the reader still
    # tolerates a tear (feed_since) so the bus never goes down on one.
    data = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return event

def _blank_to_none(val: Any) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _compact(summary: str, who: str) -> tuple[str, bool]:
    text = " ".join(str(summary or "").split())
    if not text:
        raise ValueError("refuse empty " + who + " summary")
    truncated = len(text) > STAMP_MAX_CHARS
    if truncated:
        text = text[:STAMP_MAX_CHARS]
    return text, truncated


def conductor_stamp(
    root: Path,
    summary: str,
    agent: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    instance_id: str | None = None,
    transcript: str | None = None,
    usage_remaining: Any = None,
) -> dict[str, Any]:
    """One compact conductor line into the thread feed (kind=conductor).

    Front-matter shape ({Agent} | {model} | {effort}): unknown stays JSON
    null, never filled from memory. The summary is clamped to one line of at
    most STAMP_MAX_CHARS (truncated=true marks a clamp — no silent loss).
    transcript is a pointer to where the bubble lives, never its bytes.
    """
    text, truncated = _compact(summary, "conductor")
    extra: dict[str, Any] = {
        "from": _CONDUCTOR,
        "agent": _blank_to_none(agent),
        "model": _blank_to_none(model),
        "effort": _blank_to_none(effort),
        "transcript": _blank_to_none(transcript),
        "usage_remaining": normalize_usage_remaining(usage_remaining),
    }
    if truncated:
        extra["truncated"] = True
    return hook(root, "conductor", text, instance_id=_blank_to_none(instance_id), extra=extra)


def neuron_note(root: Path, summary: str, instance_id: str | None = None, to: str | None = None) -> dict[str, Any]:
    """One compact neuron line into the thread feed (kind=note).

    Honest `from` is required: the writing seat's instance_id, never grok-bot
    (conductor lines are stamp-only). Same one-line ≤ STAMP_MAX_CHARS clamp as
    conductor_stamp; `to` is an optional addressee (a seat id or grok-bot).
    """
    author = _blank_to_none(instance_id)
    if not author:
        raise ValueError("refuse anonymous note: instance_id (the writing seat) is required")
    text, truncated = _compact(summary, "note")
    extra: dict[str, Any] = {"truncated": True} if truncated else {}
    return hook(root, "note", text, instance_id=author, extra=extra or None, to=_blank_to_none(to))


_RELATIVE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_since(value: Any, now: str | None = None) -> str:
    """`--since` in the storyboard's own words: `10m`, `2h`, `1d`, `45s`, or an
    ISO UTC timestamp passed through untouched. Anything else is refused,
    never guessed: a bare number has no unit and a decimal has no clock."""
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError("refuse empty --since: give 10m | 2h | 1d | 45s or an ISO UTC timestamp")
    m = _RELATIVE.fullmatch(text)
    if m:
        secs = int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
        base = datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ") if now else datetime.now(timezone.utc).replace(tzinfo=None)
        return (base - timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # ISO: starts with a 4-digit year and a dash; the feed compares strings
    # lexically, so the shape must be the feed's own or the window is wrong.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z?)?", text):
        return text
    raise ValueError("refuse --since " + repr(text) + ": give 10m | 2h | 1d | 45s or an ISO UTC timestamp")


def feed_since(root: Path, since: str) -> list[dict[str, Any]]:
    since_iso = parse_since(since)
    path = feed_path(root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                # One bad line (a neuron's stray stdout, a torn write) must not
                # take the whole bus down for every reader (live 2026-09-05:
                # feed, rail, await-seated all crashed on one row). The line is
                # kept on disk and surfaced as a row, never dropped silently.
                row = {"ts": None, "kind": "malformed", "instance_id": None,
                       "summary": "feed line " + str(lineno) + " is not JSON: " + str(e)[:80],
                       "raw": line[:200]}
                if not isinstance(row, dict):
                    continue
                out.append(row)
                continue
            if not isinstance(row, dict):
                row = {"ts": None, "kind": "malformed", "instance_id": None,
                       "summary": "feed line " + str(lineno) + " is not an object", "raw": line[:200]}
                out.append(row)
                continue
            if str(row.get("ts") or "") >= since_iso:
                out.append(row)
    return out
