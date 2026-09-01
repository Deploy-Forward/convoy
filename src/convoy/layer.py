"""Convoy layer: timestamped hook events. Not vendor --resume.

Feed contract v2 (additive; same file, same single writer, same MCP URL):
schema_version rides the feed envelope, kinds stay open (synapse, refuse+ask,
conductor, attach, note, ...). A conductor stamp is ONE compact line — the
Grok Bot bubble history never lands here; a transcript is a pointer at most.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
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

def hook(root: Path, kind: str, summary: str, instance_id: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {"ts": utc_now(), "kind": kind, "instance_id": instance_id, "summary": summary}
    if extra:
        event.update(extra)
    path = feed_path(root)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")
    return event

def _blank_to_none(val: Any) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


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
    text = " ".join(str(summary or "").split())
    if not text:
        raise ValueError("refuse empty conductor summary")
    truncated = len(text) > STAMP_MAX_CHARS
    if truncated:
        text = text[:STAMP_MAX_CHARS]
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


def feed_since(root: Path, since_iso: str) -> list[dict[str, Any]]:
    path = feed_path(root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("ts", "") >= since_iso:
                out.append(row)
    return out
