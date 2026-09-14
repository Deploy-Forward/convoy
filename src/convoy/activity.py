"""Who is active on this thread, and how do I reach them.

Marco 2026-09-03: "We should be able to see active neurons in this Terminal
tab and send messages." Convoy had two views and neither answered it. `panes`
reads the OS process table, which on Windows cannot place a codex or claude
body (no token and no worktree in the command line, no cwd from stdlib), so
it said `unknown` for eight chairs while two of them were plainly running in
adjacent tabs. `graph` describes structure, not recency.

The evidence Convoy actually holds is the bus. A chair that AUTHORED a row
six minutes ago is alive, whatever the process table can see; that is
attested by the chair itself, which is the same standard the delivery ladder
uses for receipts. So activity leads with the bus, carries process evidence
beside it as a second opinion, and never downgrades one to the other.

Never prints a token. `send_command` is the exact line that messages a chair.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .cmd import convoy_root_command
from .convoy import list_seats, read_thread, read_id
from .inbox import pending
from .layer import feed_path, feed_since
from .panes import match_processes

EPOCH = "1970-01-01T00:00:00.000000Z"
DEFAULT_WINDOW_MIN = 90


def _age(ts: str | None, now: datetime) -> str | None:
    if not ts:
        return None
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    secs = int((now - then).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return str(secs) + "s ago"
    if secs < 3600:
        return str(secs // 60) + "m ago"
    if secs < 86400:
        return str(secs // 3600) + "h ago"
    return str(secs // 86400) + "d ago"


def neuron_activity(
    root: Path,
    since: str | None = None,
    procs: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One card per chair: is it active, on what evidence, what is waiting for
    it, and the command that messages it. Most recently active first."""
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    if since is None:
        since = (now - timedelta(minutes=DEFAULT_WINDOW_MIN)).isoformat(timespec="microseconds").replace("+00:00", "Z")

    rows = feed_since(root, EPOCH) if feed_path(root).exists() else []
    seats = list_seats(root, require_session=True)
    view = match_processes(root, procs) if procs is not None else None
    proc_by_chair: dict[str, Any] = {}
    if view is not None:
        proc_by_chair = {c["session_id"]: c["live"] for c in view["chairs"]}

    authored: dict[str, dict[str, Any]] = {}
    addressed: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        f = r.get("from")
        if isinstance(f, str) and f:
            prev = authored.get(f)
            if prev is None or str(r.get("ts") or "") > str(prev.get("ts") or ""):
                authored[f] = r
        t = r.get("to")
        if isinstance(t, str) and t and r.get("kind") in ("note", "conductor"):
            addressed.setdefault(t, []).append(r)

    out: list[dict[str, Any]] = []
    for s in seats:
        sid = s["session_id"]
        last = authored.get(sid)
        last_ts = str(last.get("ts")) if last else None
        # Rows addressed to it after its own last word: what it has not answered.
        waiting = [r for r in addressed.get(sid, []) if not last_ts or str(r.get("ts") or "") > last_ts]
        try:
            inbox_n = len(pending(root, sid))
        except (OSError, ValueError):
            inbox_n = 0
        proc = proc_by_chair.get(sid) if view is not None else None
        spoke_in_window = bool(last_ts and last_ts >= since)
        active = bool(spoke_in_window or proc is True)
        if spoke_in_window and proc is True:
            evidence = "authored+process"
        elif spoke_in_window:
            evidence = "authored"
        elif proc is True:
            evidence = "process"
        elif last_ts:
            evidence = "quiet"          # spoke, but not inside the window
        else:
            evidence = "silent"         # never authored a row on this thread
        out.append({
            "session_id": sid,
            "harness": s.get("to"),
            "model": s.get("model"),
            "where": s.get("where"),
            "worktree": s.get("worktree"),
            "active": active,
            "evidence": evidence,
            "process": proc,
            "last_authored": last_ts,
            "last_authored_age": _age(last_ts, now),
            "last_said": (last.get("summary") or "")[:120] if last else None,
            "unread": len(waiting),
            "last_addressed_by": (waiting[-1].get("from") if waiting else None),
            "inbox_pending": inbox_n,
            "send_command": convoy_root_command(root) + ' hook note "<text>" --as-me --to ' + sid,
        })

    out.sort(key=lambda n: (n["last_authored"] or ""), reverse=True)
    return {
        "ok": True,
        "convoy_id": read_id(root),
        "thread": read_thread(root),
        "since": since,
        "active_count": sum(1 for n in out if n["active"]),
        "neurons": out,
        "note": ("active means the chair authored a row inside the window, or a process was placed. "
                 "A chair Convoy cannot place is never reported dead."),
    }


def neuron_id(convoy_id: str | None, session_id: str | None) -> str | None:
    """A short, stable handle for one chair on one thread: `n` + 6 hex of
    sha256(convoy_id:session_id). Derived, never stored, so it cannot drift and
    needs no registry; `send --id` resolves it by walking the machine index."""
    if not convoy_id or not session_id:
        return None
    import hashlib
    return "n" + hashlib.sha256((str(convoy_id) + ":" + str(session_id)).encode("utf-8")).hexdigest()[:6]


def resolve_neuron_id(nid: str) -> dict[str, Any]:
    """{ok, root, thread, convoy_id, session_id, to} for one short id, or an
    error naming the verb that lists them. Two chairs sharing six hex digits is
    reported as ambiguous, never guessed."""
    from .index import list_threads
    from .convoy import list_seats
    want = str(nid or "").strip().lower()
    hits: list[dict[str, Any]] = []
    for t in list_threads():
        if not t.get("present") or t.get("hidden"):
            continue
        root = Path(str(t.get("root")))
        cid = t.get("convoy_id")
        try:
            seats = list_seats(root, convoy_id=cid)
        except (OSError, ValueError):
            continue
        seen: set[str] = set()
        for s in seats:
            sid = s.get("session_id")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            if neuron_id(cid, sid) == want:
                hits.append({"root": str(root.resolve()), "thread": t.get("thread"), "convoy_id": cid,
                             "session_id": sid, "to": s.get("to"), "model": s.get("model")})
    if len(hits) == 1:
        return {"ok": True, "id": want, **hits[0]}
    if not hits:
        return {"ok": False, "id": want, "error": "no neuron with id " + want + " on this machine; see `convoy neurons --all`"}
    return {"ok": False, "id": want, "error": "ambiguous id " + want + ": " + str(len(hits)) + " chairs; address by --root and --instance-id", "hits": hits}


def neurons_everywhere(since: str | None = None) -> dict[str, Any]:
    """One flat table across every thread the machine index knows:
    harness | model | neuron | thread (Marco 2026-09-13, `/convoy-list`).
    Deterministic: the index, then each root's seats and feed. Hidden threads
    and roots that are gone are skipped and named, never silently dropped."""
    from .index import list_threads
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for t in list_threads():
        thread = t.get("thread")
        if t.get("hidden"):
            skipped.append({"thread": thread, "reason": "hidden"})
            continue
        if not t.get("present"):
            skipped.append({"thread": thread, "reason": "root gone", "root": t.get("root")})
            continue
        root = Path(str(t.get("root")))
        try:
            card = neuron_activity(root, since=since)
        except (OSError, ValueError) as e:
            skipped.append({"thread": thread, "reason": type(e).__name__, "root": str(root)})
            continue
        for n in card.get("neurons") or []:
            rows.append({"id": neuron_id(t.get("convoy_id"), n.get("session_id")),
                         "harness": n.get("harness"), "model": n.get("model"), "neuron": n.get("session_id"),
                         "thread": thread, "root": str(root), "active": bool(n.get("active")),
                         "evidence": n.get("evidence"), "last_authored": n.get("last_authored"),
                         "inbox_pending": n.get("inbox_pending"), "send_command": n.get("send_command")})
    rows.sort(key=lambda r: (not r["active"], str(r.get("last_authored") or "")), reverse=False)
    rows.sort(key=lambda r: str(r.get("last_authored") or ""), reverse=True)
    rows.sort(key=lambda r: not r["active"])
    return {"ok": True, "columns": ["id", "harness", "model", "neuron", "thread"], "rows": rows,
            "active_count": sum(1 for r in rows if r["active"]), "skipped": skipped}
