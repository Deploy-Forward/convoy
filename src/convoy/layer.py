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

from .filelock import append_line
from .index import home_dir
from .report import read_origin
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
_VERIFIED_METHODS = frozenset(("environment", "token", "pane-host", "worktree", "bearer"))
STAMPED_KINDS = frozenset(("note", "synapse", "seated"))
_RESERVED_FIELDS = frozenset(("ts", "kind", "summary", "instance_id", "from", "to",
                              "device", "verified_by", "author_claimed"))


def _paired_device() -> str | None:
    """Return only the paired machine id, never a hostname or credential."""
    origin = read_origin(home_dir())
    value = (origin or {}).get("machine_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def hook(root: Path, kind: str, summary: str, instance_id: str | None = None, extra: dict[str, Any] | None = None, to: str | None = None, author: Any = _AUTHOR_IS_INSTANCE, *, verified_by: str | None = None, local_writer: bool = True, allow_conductor_author: bool = False) -> dict[str, Any]:
    # `from` is AUTHORSHIP, `instance_id` is the row's subject. They coincide
    # on note-family rows (default), but a synapse/refuse row's instance_id is
    # the TARGET session — passing author=None there records "sender unknown"
    # instead of promoting the recipient to author (a verified defect).
    # `device` identifies the author's machine: the paired machine for a local
    # CLI row, independent of author proof, but null for an MCP-originated row
    # whose remote caller's machine is unknown (local_writer=False).
    if author is _AUTHOR_IS_INSTANCE:
        author = instance_id
    # The refusal is an AUTHORSHIP rule: it tests author only. instance_id is
    # the row's subject and may legitimately name any seat — refusing it here
    # would raise post-runner on synapse rows, discarding the card and leaving
    # a hop with zero feed rows (a pre-merge review finding). Constraining
    # subject names belongs at seat/register write time, where nothing has run.
    # A conductor authors its stamps, and is the sender of a send it made over a
    # checked bearer (verified_by=bearer, set only by the MCP send from the
    # request's principal). It never authors a note or any other row.
    conductor_ok = ((kind == "conductor" and allow_conductor_author)
                    or (kind == "synapse" and verified_by == "bearer"))
    if _is_conductor_alias(author) and not conductor_ok:
        raise ValueError("refuse grok-bot as author; conductor identity is stamp-only")
    event = {"ts": utc_now(), "kind": kind, "instance_id": instance_id, "summary": summary}
    if author:
        event["from"] = author
    if to:
        event["to"] = to
    if extra:
        # These fields belong to the writer, never to caller-provided row data.
        event.update({key: value for key, value in extra.items()
                      if key not in _RESERVED_FIELDS})
    if kind in STAMPED_KINDS:
        method = verified_by if verified_by in _VERIFIED_METHODS else None
        if event.get("from") and method is None:
            event["author_claimed"] = True
        event["device"] = _paired_device() if local_writer else None
        event["verified_by"] = method
    path = feed_path(root)
    # ONE locked append per row (filelock.append_line). Neurons, the origin and the
    # CLI write this file concurrently; without the lock, Windows' seek-then-write
    # append lets one row overwrite another. The reader still tolerates a tear
    # (feed_since) so the bus never goes down on one.
    append_line(path, (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8"))
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
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One compact conductor line into the thread feed (kind=conductor).

    Front-matter shape ({Agent} | {model} | {effort}): unknown stays JSON
    null, never filled from memory. The summary is clamped to one line of at
    most STAMP_MAX_CHARS (truncated=true marks a clamp — no silent loss).
    transcript is a pointer to where the bubble lives, never its bytes.
    principal: the checked bearer record ({id, conductor, ...}) when the stamp
    arrived over the wire with identity; `from` is read from it and the row
    carries principal={bearer: id}. None (CLI on the box, or the legacy flag)
    leaves principal null: such a stamp cannot be told from a forged one.
    """
    text, truncated = _compact(summary, "conductor")
    if _is_conductor_alias(instance_id):
        raise ValueError("refuse grok-bot as author; conductor identity is stamp-only")
    who = _CONDUCTOR
    if isinstance(principal, dict) and principal.get("conductor"):
        who = str(principal["conductor"])
    extra: dict[str, Any] = {
        "principal": {"bearer": str(principal.get("id"))} if isinstance(principal, dict) and principal.get("id") else None,
        "agent": _blank_to_none(agent),
        "model": _blank_to_none(model),
        "effort": _blank_to_none(effort),
        "transcript": _blank_to_none(transcript),
        "usage_remaining": normalize_usage_remaining(usage_remaining),
    }
    if truncated:
        extra["truncated"] = True
    return hook(root, "conductor", text, instance_id=_blank_to_none(instance_id),
                extra=extra, author=who, allow_conductor_author=True)


def neuron_note(root: Path, summary: str, instance_id: str | None = None, to: str | None = None) -> dict[str, Any]:
    """One compact neuron line into the thread feed (kind=note).

    Claimed `from` is required: the writing seat's instance_id, never grok-bot
    (conductor lines are stamp-only). Same one-line ≤ STAMP_MAX_CHARS clamp as
    conductor_stamp; `to` is an optional addressee (a seat id or grok-bot).
    """
    author = _blank_to_none(instance_id)
    if not author:
        raise ValueError("refuse anonymous note: instance_id (the writing seat) is required")
    text, truncated = _compact(summary, "note")
    extra: dict[str, Any] = {"truncated": True} if truncated else {}
    from .wake_dispatch import receipt_address
    return hook(root, "note", text, instance_id=author, extra=extra or None,
                to=receipt_address(root, text, author, _blank_to_none(to)), local_writer=False)


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
