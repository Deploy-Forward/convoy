"""Convoy layer: timestamped hook events. Not vendor --resume."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEED_NAME = "feed.jsonl"

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
