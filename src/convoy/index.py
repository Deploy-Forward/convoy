"""Machine-level thread index: where every Convoy thread on this machine is.

Chats launch from project folders, not from one central place, so `.convoy`
must be findable globally (Marco 2026-09-02; the /resume analogy). This file
is an INDEX, not a store: one row per convoy_id — {convoy_id, thread, root,
updated_at} — and nothing else. No tokens, no seats, no feed. The thread's
truth stays under its root; a row whose root is gone or carries a different
id renders present=false and is never dropped silently.

Location: $CONVOY_HOME/threads.json, default ~/.convoy/threads.json. The
user-global write is the one Convoy makes outside a root; it is disclosed in
the skill front matter with the trust binding.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = ("convoy_id", "thread", "root", "updated_at")


def index_path() -> Path:
    home = os.environ.get("CONVOY_HOME")
    base = Path(home) if home else Path.home() / ".convoy"
    return base / "threads.json"


def _load() -> list[dict[str, Any]]:
    path = index_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "[]")
    except json.JSONDecodeError:
        return []
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("convoy_id"), str)] if isinstance(data, list) else []


def record(root: str | Path, convoy_id: str, thread: str | None) -> dict[str, Any]:
    """Upsert this root's row. Best-effort: an unwritable home never breaks a
    thread write (the root stays the source of truth)."""
    row = {"convoy_id": convoy_id, "thread": thread, "root": str(Path(root)),
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")}
    try:
        rows = [r for r in _load() if r.get("convoy_id") != convoy_id]
        rows.append(row)
        path = index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    except OSError:
        pass
    return row


def _disk_id(root: Path) -> str | None:
    p = root / ".convoy" / "id"
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8-sig").strip() or None


def list_threads() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in _load():
        root = Path(str(r.get("root") or ""))
        present = bool(r.get("root")) and _disk_id(root) == r.get("convoy_id")
        out.append({**{k: r.get(k) for k in FIELDS}, "present": present})
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


def find_root(start: str | Path) -> Path | None:
    """Walk up from a project subfolder to the nearest root holding .convoy/id."""
    cur = Path(start).resolve()
    for cand in (cur, *cur.parents):
        if (cand / ".convoy" / "id").is_file():
            return cand
    return None
