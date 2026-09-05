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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = ("convoy_id", "thread", "root", "updated_at")


def index_path() -> Path:
    home = os.environ.get("CONVOY_HOME")
    base = Path(home) if home else Path.home() / ".convoy"
    return base / "threads.json"


def is_temp_root(root: str | Path) -> bool:
    """True when root sits under the OS temp dir (test residue, mkdtemp)."""
    text = str(root or "").strip()
    if not text:
        return False
    try:
        resolved = Path(text).resolve()
        tmp = Path(tempfile.gettempdir()).resolve()
        return resolved == tmp or resolved.is_relative_to(tmp)
    except (OSError, ValueError):
        return False


def _load() -> list[dict[str, Any]]:
    path = index_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "[]")
    except json.JSONDecodeError:
        return []
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("convoy_id"), str)] if isinstance(data, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def record(root: str | Path, convoy_id: str, thread: str | None) -> dict[str, Any]:
    """Upsert this root's row. Best-effort: an unwritable home never breaks a
    thread write (the root stays the source of truth)."""
    row = {"convoy_id": convoy_id, "thread": thread, "root": str(Path(root)),
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")}
    try:
        rows = [r for r in _load() if r.get("convoy_id") != convoy_id]
        rows.append(row)
        _save(rows)
    except OSError:
        pass
    return row


def _disk_id(root: Path) -> str | None:
    p = root / ".convoy" / "id"
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8-sig").strip() or None


def list_threads() -> list[dict[str, Any]]:
    """Every index row, newest first. present=false is kept (never dropped here)."""
    out: list[dict[str, Any]] = []
    for r in _load():
        root = Path(str(r.get("root") or ""))
        present = bool(r.get("root")) and _disk_id(root) == r.get("convoy_id")
        out.append({**{k: r.get(k) for k in FIELDS}, "present": present})
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


def recent(limit: int) -> list[dict[str, Any]]:
    """Newest N present rows excluding temp roots, for the thread picker."""
    n = max(0, int(limit))
    out: list[dict[str, Any]] = []
    for r in list_threads():
        if len(out) >= n:
            break
        if not r.get("present"):
            continue
        if is_temp_root(str(r.get("root") or "")):
            continue
        out.append(r)
    return out


def _prune_reason(raw: object) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return "absent"
    root = Path(text)
    try:
        exists = root.exists()
    except OSError:
        return "absent"
    if not exists:
        return "absent"
    if is_temp_root(root):
        return "temp"
    return None


def prune_threads() -> dict[str, Any]:
    """Drop rows whose root is under the OS temp dir or is absent. Always
    reports what was dropped (empty list if nothing matched). list_threads
    itself stays honest: present=false is only removed here, never silently."""
    rows = _load()
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for r in rows:
        reason = _prune_reason(r.get("root"))
        if reason:
            dropped.append({**{k: r.get(k) for k in FIELDS}, "reason": reason})
        else:
            kept.append(r)
    card: dict[str, Any] = {
        "ok": True,
        "index": str(index_path()),
        "dropped": dropped,
        "n_dropped": len(dropped),
        "kept": len(kept),
    }
    if dropped:
        try:
            _save(kept)
        except OSError as e:
            card["ok"] = False
            card["error"] = str(e)
            card["threads"] = list_threads()
            return card
    card["threads"] = list_threads()
    return card


def find_root(start: str | Path) -> Path | None:
    """Walk up from a project subfolder to the nearest root holding .convoy/id."""
    cur = Path(start).resolve()
    for cand in (cur, *cur.parents):
        if (cand / ".convoy" / "id").is_file():
            return cand
    return None
