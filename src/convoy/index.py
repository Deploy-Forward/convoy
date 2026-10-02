"""Machine-level thread index: where every Convoy thread on this machine is.

Chats launch from project folders, not from one central place, so `.convoy`
must be findable globally (the /resume analogy). This file
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
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = ("convoy_id", "thread", "root", "updated_at", "hidden")


def home_dir() -> Path:
    """$CONVOY_HOME, else ~/.convoy. The machine's own directory: the index
    lives here, and so does any process that must run somewhere that belongs
    to Convoy rather than to a chair (the usage probe)."""
    home = os.environ.get("CONVOY_HOME")
    main = sys.modules.get("__main__")
    # Match unittest's executable module exactly, not any process that merely
    # imports unittest: CLI and MCP entrypoints must retain the operator home.
    if getattr(getattr(main, "__spec__", None), "name", None) == "unittest.__main__":
        # Direct `python -m unittest discover -s test/demo` imports test
        # modules as top-level names and bypasses their package initializers.
        # Its home must be safe even when checkout-local sitecustomize was not
        # imported at interpreter startup (no PYTHONPATH).
        try:
            resolved = Path(home).resolve() if home else None
            temp_root = Path(tempfile.gettempdir()).resolve()
            throwaway = bool(resolved and resolved != temp_root
                             and resolved.is_relative_to(temp_root))
        except (OSError, ValueError):
            throwaway = False
        if not throwaway:
            home = tempfile.mkdtemp(prefix="convoy-test-home-")
            os.environ["CONVOY_HOME"] = home
    return Path(home) if home else Path.home() / ".convoy"


def index_path() -> Path:
    return home_dir() / "threads.json"


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


def _load_checked() -> tuple[list[dict[str, Any]], str | None]:
    """(rows, error): error is "unparseable" when the index exists but is not a JSON list, and then
    no writer may replace it, or every other thread's row would be lost."""
    path = index_path()
    if not path.is_file():
        return [], None
    try:
        text = path.read_text(encoding="utf-8-sig")
        if not text.strip():
            return [], "unparseable"  # an empty file is a write cut short, not an empty index
        data = json.loads(text)
    except (OSError, ValueError):
        return [], "unparseable"
    if not isinstance(data, list):
        return [], "unparseable"
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("convoy_id"), str)], None


def _load() -> list[dict[str, Any]]:
    return _load_checked()[0]


def index_error() -> str | None:
    """"unparseable" when the machine index cannot be read (and so is never rewritten), else None."""
    return _load_checked()[1]


def _save(rows: list[dict[str, Any]]) -> None:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: a reader never sees a truncated file, and a crash leaves the old one whole.
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def record(root: str | Path, convoy_id: str, thread: str | None) -> dict[str, Any]:
    """Upsert this root's row. Best-effort: an unwritable home never breaks a
    thread write (the root stays the source of truth)."""
    row = {"convoy_id": convoy_id, "thread": thread, "root": str(Path(root)),
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")}
    try:
        loaded, error = _load_checked()
        if error:
            row["index_error"] = error  # never rewrite an index that cannot be read
            return row
        prev = [r for r in loaded if r.get("convoy_id") == convoy_id]
        if prev and prev[0].get("hidden"):
            row["hidden"] = True   # a thread you archived stays archived across writes
        rows = [r for r in loaded if r.get("convoy_id") != convoy_id]
        rows.append(row)
        _save(rows)
    except OSError:
        pass
    return row


def set_hidden(convoy_id: str, hidden: bool) -> dict[str, Any]:
    """Archive (hide) or unarchive a thread on the widget strip. The index
    row, the root, and every seat stay exactly as they are; only the strip
    stops showing it. The strip clipped past four threads and offered no
    way to put one away."""
    rows, error = _load_checked()
    if error:
        return {"ok": False, "error": "thread index " + error + "; left alone: " + str(index_path()),
                "index_error": error}
    hit = [r for r in rows if r.get("convoy_id") == convoy_id]
    if not hit:
        return {"ok": False, "error": "unknown thread: " + str(convoy_id)}
    for r in hit:
        r["hidden"] = bool(hidden)
    _save(rows)
    return {"ok": True, "convoy_id": convoy_id, "hidden": bool(hidden), "thread": hit[0].get("thread")}


def hidden_threads() -> list[dict[str, Any]]:
    """Present, non-temp rows that are hidden, newest first (stubs for the strip)."""
    return [r for r in list_threads() if r.get("hidden") and r.get("present") and not is_temp_root(str(r.get("root") or ""))]


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
        skip_reason = ("root gone" if not present else
                       "temp" if is_temp_root(root) else
                       "hidden" if r.get("hidden") else None)
        out.append({**{k: r.get(k) for k in FIELDS}, "present": present,
                    "skip_reason": skip_reason})
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


def is_routable_thread(row: dict[str, Any]) -> bool:
    """Present, non-Temp threads route even when hidden from pickers."""
    return bool(row.get("present") and not is_temp_root(str(row.get("root") or "")))


def routable_threads() -> list[dict[str, Any]]:
    """Index-backed routing only; hidden is a view preference, not a deny."""
    return [r for r in list_threads() if is_routable_thread(r)]


def is_discoverable_thread(row: dict[str, Any]) -> bool:
    """A row visible in implicit lists and pickers, not all routable rows."""
    return bool(is_routable_thread(row) and not row.get("hidden"))


def discoverable_threads() -> list[dict[str, Any]]:
    """Present user threads for implicit views and pickers.

    Keep list_threads() lossless for audit and explicit-root operations; old
    Temp rows remain in the index until a person explicitly prunes them.
    """
    return [r for r in list_threads() if is_discoverable_thread(r)]


def recent(limit: int) -> list[dict[str, Any]]:
    """Newest N present rows excluding temp roots, for the thread picker."""
    n = max(0, int(limit))
    return discoverable_threads()[:n]


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
