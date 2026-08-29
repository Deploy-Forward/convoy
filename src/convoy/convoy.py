"""Durable convoy_id. Keys harness + model + thread + worktree to one convoy."""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from .context import pack
from .layer import feed_since, hook
from .registry import register
from .usage import probe, surface

def _id_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "id"

def _seats_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "seats.jsonl"

def _thread_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "thread"

CONDUCTOR = "grok-bot"

def _lead_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "lead"

def make_resume_key(convoy_id: str | None, thread: str | None, to: str | None) -> str:
    """Map key for (convoy, thread, harness). Not a session_id. Never invent resume."""
    blob = (convoy_id or "") + "\0" + (thread or "") + "\0" + (to or "")
    return "cvr_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def read_id(root: Path) -> str | None:
    path = _id_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def ensure_id(root: Path) -> str:
    existing = read_id(root)
    if existing:
        return existing
    cid = "cvy_" + secrets.token_urlsafe(16)
    path = _id_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cid + "\n", encoding="utf-8")
    return cid

def read_lead(root: Path) -> str | None:
    path = _lead_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def set_lead(root: Path, to: str) -> dict[str, Any]:
    if not to or not str(to).strip():
        raise ValueError("refuse empty lead")
    harness = str(to).strip().lower()
    cid = ensure_id(root)
    path = _lead_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(harness + "\n", encoding="utf-8")
    return {"ok": True, "convoy_id": cid, "conductor": CONDUCTOR, "lead": harness}

def read_thread(root: Path) -> str | None:
    path = _thread_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def bind(root: Path, thread: str) -> dict[str, Any]:
    if not thread or not str(thread).strip():
        raise ValueError("refuse empty thread")
    key = str(thread).strip()
    cid = ensure_id(root)
    path = _thread_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    md = Path(root) / "thread.md"
    md.write_text(cid + "\n" + key + "\n", encoding="utf-8")
    return {"ok": True, "convoy_id": cid, "thread": key}

def seat(root: Path, to: str, session_id: str, worktree: str | None = None, model: str | None = None, resume: str | None = None) -> dict[str, Any]:
    if not session_id:
        raise ValueError("refuse empty session_id")
    cid = ensure_id(root)
    wt = str(worktree) if worktree is not None else None
    thread = read_thread(root) or ""
    resume_val = resume if (isinstance(resume, str) and resume) else session_id
    rkey = make_resume_key(cid, thread, to)
    row: dict[str, Any] = {
        "convoy_id": cid,
        "to": to,
        "session_id": session_id,
        "worktree": wt,
        "model": model,
        "resume": resume_val,
        "resume_key": rkey,
    }
    path = _seats_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    register(root, session_id, to, extra={"convoy_id": cid, "worktree": wt, "model": model, "to": to, "resume": resume_val, "resume_key": rkey})
    return row

def list_seats(root: Path, convoy_id: str | None = None, require_session: bool = True) -> list[dict[str, Any]]:
    path = _seats_path(root)
    if not path.is_file():
        return []
    found: dict[str, dict[str, Any]] = {}
    blanks: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if convoy_id is not None and row.get("convoy_id") != convoy_id:
                continue
            sid = row.get("session_id")
            if isinstance(sid, str) and sid:
                found[sid] = row
            else:
                blanks.append(row)
    if require_session:
        return list(found.values())
    return list(found.values()) + blanks

def lookup_resume(root: Path, thread: str, to: str) -> str | None:
    """Return stored resume for thread+to. Hash is the map key. Never invent a session_id."""
    cid = read_id(root)
    if not cid:
        return None
    key = make_resume_key(cid, thread, to)
    for row in list_seats(root, convoy_id=cid):
        if row.get("resume_key") == key and row.get("to") == to:
            r = row.get("resume") or row.get("vendor_session_id") or row.get("session_id")
            if isinstance(r, str) and r:
                return r
    return None


def _seats_with_usage(seats: list[dict[str, Any]], probe_fn=None) -> list[dict[str, Any]]:
    fn = probe_fn or probe
    cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for s in seats:
        row = dict(s)
        to = row.get("to")
        if not isinstance(to, str) or not to:
            out.append(row)
            continue
        if to not in cache:
            cache[to] = fn(to)
        row.update(surface(to, cache[to]))
        out.append(row)
    return out

def _last_attach_ts(root: Path) -> str | None:
    path = Path(root) / ".convoy" / "feed.jsonl"
    if not path.is_file():
        return None
    last = None
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "attach" and row.get("ts"):
                last = row["ts"]
    return last

def attach(root: Path, convoy_id: str | None = None, probe_fn=None) -> dict[str, Any]:
    disk = read_id(root)
    if convoy_id is not None:
        if disk != convoy_id:
            return {"ok": False, "error": "convoy_id mismatch", "convoy_id": disk, "seats": []}
        cid = convoy_id
    else:
        if disk is None:
            return {"ok": False, "error": "no convoy_id"}
        cid = disk
    thread = read_thread(root)
    since = _last_attach_ts(root)
    event = hook(root, kind="attach", summary="attach " + cid, extra={"convoy_id": cid, "thread": thread})
    feed = feed_since(root, since) if since is not None else []
    seats = _seats_with_usage(list_seats(root, convoy_id=cid), probe_fn=probe_fn)
    return {
        "ok": True,
        "convoy_id": cid,
        "seats": seats,
        "pointers": pack(root),
        "thread": thread,
        "conductor": CONDUCTOR,
        "lead": read_lead(root),
        "ts": event["ts"],
        "since": since,
        "feed": feed,
    }
