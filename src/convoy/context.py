"""Packed pointers only. Never file contents. Never a vendor transcript."""
from __future__ import annotations

import json
from pathlib import Path
from .gitstate import git_state
from typing import Any

POINTER_FILES = (
    ("thread", "thread.md"),
    ("role", "role.md"),
    ("brief", ".convoy/brief.md"),
)

def _pointer(path: Path) -> str | None:
    return str(path) if path.is_file() else None


def _one_line(path: Path) -> str | None:
    """SoT id from a one-line file. JSON null if missing. Never invent."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def newest_handoff(root: Path) -> str | None:
    """Newest file under `.convoy/handoff/`. Labelled legacy fallback: an
    old `.ola/*handoff*` is returned only when the new folder is empty."""
    folder = Path(root) / ".convoy" / "handoff"
    if folder.is_dir():
        files = [p for p in folder.iterdir() if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return str(files[0])
    legacy = Path(root) / ".ola"
    if not legacy.is_dir():
        return None
    cands = sorted(legacy.glob("*handoff*"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in cands if p.is_file()]
    return str(files[0]) if files else None

def pack(root: Path, instance_id: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    out: dict[str, Any] = {}
    for key, rel in POINTER_FILES:
        out[key] = _pointer(root / rel)
    out["brief_source"] = "convoy" if out.get("brief") else None
    if out.get("brief") is None:
        # labelled legacy fallback; new writes go to .convoy/brief.md
        out["brief"] = _pointer(root / ".ola" / "brief.md")
        out["brief_source"] = "legacy-ola" if out["brief"] else None
    out["handoff"] = newest_handoff(root)
    out["handoff_source"] = None if out["handoff"] is None else (
        "convoy" if str(out["handoff"]).startswith(str(root / ".convoy")) else "legacy-ola")
    # Marco 2026-09-10: a conductor kept writing briefs and handoffs under .ola/
    # (another product's directory) because the fallback read them silently and
    # nothing said where new writes belong. The record is .convoy/; say so, and
    # name every legacy file still being read so the drift is visible.
    out["canonical"] = {"brief": str(root / ".convoy" / "brief.md"),
                        "handoff_dir": str(root / ".convoy" / "handoff"),
                        "feed": str(root / ".convoy" / "feed.jsonl"),
                        "inbox_dir": str(root / ".convoy" / "inbox")}
    legacy_dir = root / ".ola"
    legacy: list[str] = []
    if legacy_dir.is_dir():
        for cand in sorted(legacy_dir.glob("*")):
            if cand.is_file() and (cand.name == "brief.md" or "handoff" in cand.name):
                legacy.append(str(cand))
    out["legacy_ola"] = legacy
    out["advice"] = ("write briefs to .convoy/brief.md and handoffs to .convoy/handoff/; "
                     ".ola/ is legacy, read only, and will stop being read") if legacy else None
    out["instance_id"] = instance_id
    out["convoy_id"] = _one_line(root / ".convoy" / "id")
    out["thread_key"] = _one_line(root / ".convoy" / "thread")
    state = git_state(root)
    out["worktree"] = str(root) if state["git_branch"] else None
    out["branch"] = state["git_branch"]
    out["pr"] = state["pr_number"]
    out["git_sha"] = state["git_sha"]
    return out

def stdin_for(packed: dict[str, Any], body: str) -> str:
    paths = {k: v for k, v in packed.items() if k != "instance_id"}
    return (
        "read these paths, then do the body. do not expect file contents in this message." + chr(10)
        + json.dumps(paths, separators=(",", ":"))
        + chr(10)
        + body
    )
