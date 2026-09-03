"""Durable convoy_id. Keys harness + model + thread + worktree to one convoy."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .context import pack
from .index import record as index_record
from .layer import SCHEMA_VERSION, feed_since, hook
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

def make_resume_key(convoy_id: str | None, thread: str | None, to: str | None, worktree: str | None = None) -> str:
    """Map key for (convoy, thread, harness, worktree). Not a session_id."""
    blob = (convoy_id or "") + "\0" + (thread or "") + "\0" + (to or "") + "\0" + (worktree or "")
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
    index_record(root, cid, read_thread(root))
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
    index_record(root, cid, key)
    return {"ok": True, "convoy_id": cid, "thread": key}

def seat(
    root: Path,
    to: str,
    session_id: str,
    worktree: str | None = None,
    model: str | None = None,
    resume: str | None = None,
    title: str | None = None,
    agent: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    if not session_id:
        raise ValueError("refuse empty session_id")
    cid = ensure_id(root)
    wt = str(worktree) if worktree is not None else None
    # A worktree bound to ANOTHER thread shadows this root for every CLI call
    # made without --root (2026-09-03: a codex chair on fable-opus sat in a
    # worktree carrying fable-luna's .convoy/id and heard nothing). Refuse.
    if wt:
        foreign = _id_path(Path(wt))
        if foreign.is_file() and Path(wt).resolve() != Path(root).resolve():
            other = foreign.read_text(encoding="utf-8-sig").strip()
            if other and other != cid:
                other_thread = read_thread(Path(wt)) or "?"
                raise ValueError(
                    "refuse seat: worktree " + wt + " is bound to thread " + other_thread + " (" + other +
                    "), not this root's " + (read_thread(root) or "?") + " (" + cid + "); use a worktree without"
                    " its own .convoy, or bind it to this thread")
        if session_id != CONDUCTOR and to != CONDUCTOR:
            holder = chair_holding_worktree(root, wt, except_session=session_id)
            if holder is not None:
                raise ValueError(
                    "refuse seat: worktree " + wt + " is already held by chair " +
                    str(holder.get("session_id")) + " on this thread; two chairs on one "
                    "worktree makes inbox drain ambiguous")
    thread = read_thread(root) or ""
    resume_val = resume.strip() if isinstance(resume, str) and resume.strip() else None
    rkey = make_resume_key(cid, thread, to, wt)
    title_val = title.strip() if isinstance(title, str) and title.strip() else None
    agent_val = agent.strip() if isinstance(agent, str) and agent.strip() else None
    row: dict[str, Any] = {
        "convoy_id": cid,
        "to": to,
        "session_id": session_id,
        "worktree": wt,
        "model": model,
        # Effort is the seat's declared level, real-or-null (chip front matter).
        # Convoy stores it; it never sets vendor effort flags.
        "effort": effort.strip() if isinstance(effort, str) and effort.strip() else None,
        "resume": resume_val,
        # Token-to-harness binding (opus-2 RED at baa6a55): resume_for records
        # the harness this token is claimed for; resume_target refuses on
        # mismatch, so a stale token can never ride another harness's argv.
        "resume_for": to if resume_val else None,
        "title": title_val,
        "agent": agent_val,
        "resume_key": rkey,
    }
    path = _seats_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    index_record(root, cid, thread or None)
    register(
        root,
        session_id,
        to,
        extra={
            "convoy_id": cid,
            "worktree": wt,
            "model": model,
            "to": to,
            "resume": resume_val,
            "title": title_val,
            "agent": agent_val,
            "resume_key": rkey,
        },
    )
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


def _resolved_worktree(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except OSError:
        return None


def chair_holding_worktree(
    root: Path,
    worktree: str | Path | None,
    *,
    except_session: str | None = None,
) -> dict[str, Any] | None:
    """Latest other chair whose worktree resolves to the same path, or None."""
    want = _resolved_worktree(worktree)
    if not want:
        return None
    skip = str(except_session or "").strip()
    holder = None
    for row in list_seats(root, require_session=True):
        sid = str(row.get("session_id") or "").strip()
        to = str(row.get("to") or "").strip()
        if not sid or sid == skip:
            continue
        if sid == CONDUCTOR or to == CONDUCTOR:
            continue
        have = _resolved_worktree(row.get("worktree"))
        if have and have == want:
            holder = row
    return holder


def set_seat_agent(root: Path, session_id: str, agent: str) -> dict[str, Any] | None:
    """Persist agent on an existing seat row. Append-only; last row wins.

    No-op (None) when the seat is unknown or already carries that agent —
    repeated bring_up must not grow seats.jsonl.
    """
    sid = str(session_id or "").strip()
    val = str(agent or "").strip()
    if not sid or not val:
        return None
    rows = list_seats(root, require_session=True)
    row = None
    for r in rows:
        if r.get("session_id") == sid:
            row = r
    if row is None or row.get("agent") == val:
        return None
    updated = {**row, "agent": val}
    path = _seats_path(root)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(updated, separators=(",", ":")) + "\n")
    return updated


def update_seat(root: Path, session_id: str, **changes: Any) -> dict[str, Any]:
    """Field-preserving seat update ({**row, ...changes}, the set_seat_agent
    pattern) — bare seat() writes whole rows last-wins and silently blanks
    unpassed fields (opus-1 AMBER-4). A harness change nulls resume AND
    vendor_session_id unless explicitly re-provided (no swap ever carries a
    vendor session — ratified RED-2 resolution). resume_key is recomputed
    (to/worktree are hashed: it is a resume MAP key, not chair identity)."""
    sid = str(session_id or "").strip()
    row = None
    for r in list_seats(root, require_session=True):
        if r.get("session_id") == sid:
            row = r
    if row is None:
        raise ValueError("unknown seat: " + sid)
    if "worktree" in changes:
        holder = chair_holding_worktree(root, changes.get("worktree"), except_session=sid)
        if holder is not None:
            raise ValueError(
                "refuse seat: worktree " + str(changes.get("worktree")) +
                " is already held by chair " + str(holder.get("session_id")) +
                " on this thread; two chairs on one worktree makes inbox drain ambiguous")
    harness_changed = "to" in changes and changes["to"] != row.get("to")
    updated: dict[str, Any] = {**row, **changes}
    if harness_changed:
        if "resume" not in changes:
            updated["resume"] = None
        if "vendor_session_id" not in changes:
            updated["vendor_session_id"] = None
    if updated.get("resume"):
        if "resume" in changes and changes["resume"]:
            updated["resume_for"] = updated.get("to")
    else:
        updated["resume_for"] = None
    cid = row.get("convoy_id") or ensure_id(root)
    thread = read_thread(root) or ""
    updated["resume_key"] = make_resume_key(cid, thread, str(updated.get("to") or ""), updated.get("worktree"))
    path = _seats_path(root)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(updated, separators=(",", ":")) + "\n")
    register(
        root,
        sid,
        str(updated.get("to") or ""),
        extra={"convoy_id": cid, "worktree": updated.get("worktree"), "model": updated.get("model"),
               "to": updated.get("to"), "resume": updated.get("resume"), "title": updated.get("title"),
               "agent": updated.get("agent"), "resume_key": updated.get("resume_key")},
    )
    return updated


def lookup_resume(root: Path, thread: str, to: str, worktree: str | None = None) -> str | None:
    """Return stored vendor resume id for thread+to(+worktree when provided)."""
    cid = read_id(root)
    if not cid:
        return None
    key = make_resume_key(cid, thread, to, worktree)
    seats = list_seats(root, convoy_id=cid)
    if worktree is not None:
        for row in seats:
            if row.get("resume_key") == key and row.get("to") == to:
                r = row.get("resume") or row.get("vendor_session_id")
                if isinstance(r, str) and r:
                    return r
        return None
    for row in seats:
        if row.get("resume_key") == key and row.get("to") == to:
            r = row.get("resume") or row.get("vendor_session_id")
            if isinstance(r, str) and r:
                return r
    # Legacy fallback when seats are keyed per-worktree.
    for row in reversed(seats):
        if row.get("to") == to:
            r = row.get("resume") or row.get("vendor_session_id")
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
        "schema_version": SCHEMA_VERSION,
        "seats": seats,
        "pointers": pack(root),
        "thread": thread,
        "conductor": CONDUCTOR,
        "lead": read_lead(root),
        "ts": event["ts"],
        "since": since,
        "feed": feed,
    }
