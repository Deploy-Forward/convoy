"""Live-seat inbox: queue a body for an already-running neuron.

A successful *enqueue* is not delivery. Delivery is when the occupant drains
the row (Grok/Claude hook additionalContext, Codex `queue`, or an explicit
`convoy inbox --drain`). Fake send ACKs must not claim this path.

Consumption is append-only: a consumed-marker row per token. Pending lines
are never rewritten. Concurrent drains: first marker for a token wins.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .convoy import list_seats
from .index import find_root
from .layer import utc_now


POINTER_RELS = (
    Path(".grok") / "convoy-root",
    Path(".claude") / "convoy-root",
)

# Proven vendor hook files vs honest cli-drain. Never invent iTerm/Terminal.app
# adapters. Same command string everywhere a vendor hook exists.
HARNESS_INBOX = {
    "grok": "grok-hooks",
    "claude": "claude-settings",
    "codex": "native-queue-or-cli-drain",
    "cursor-agent": "cli-drain",
    "agy": "cli-drain",
    "hermes": "cli-drain",
    "pi": "cli-drain",
}


def connect_mode(harness: Any) -> str | None:
    """How a launched neuron RECEIVES, for the card: 'hook' where a proven
    vendor hook file drains the inbox mid-turn (grok, claude), else the
    HARNESS_INBOX word itself - codex 'native-queue-or-cli-drain', and
    'cli-drain' for cursor-agent/agy/hermes/pi, whose hooks cannot fire until
    the model runs `convoy inbox --drain` by hand. None for an unknown harness.
    A label, not a connection: only the chair's own kind=seated row proves one
    (2026-09-04, item E)."""
    from .harness_contract import canonical_harness_id

    kind = HARNESS_INBOX.get(canonical_harness_id(harness))
    if kind in ("grok-hooks", "claude-settings"):
        return "hook"
    return kind


def inbox_dir(root: Path) -> Path:
    path = Path(root) / ".convoy" / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inbox_path(root: Path, session_id: str) -> Path:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("inbox requires a seat session_id")
    safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in sid)
    return inbox_dir(root) / (safe + ".jsonl")


def enqueue(
    root: Path,
    session_id: str,
    body: str,
    *,
    to: str | None = None,
    label: str | None = None,
    path_name: str = "inbox",
    token: str | None = None,
) -> dict[str, Any]:
    """Append one pending message. Token is for the receiver's ack, not a resume.

    A caller may mint the token first when it needs to put that token INSIDE
    the body it hands to a vendor transport, so the receiver can cite it and
    prove which channel delivered (codex 2026-09-03: a native queue push is
    indistinguishable from a human typing unless the token rides along)."""
    sid = str(session_id or "").strip()
    text = str(body or "")
    if not sid:
        raise ValueError("inbox requires a seat session_id")
    if not text.strip():
        raise ValueError("inbox refuses an empty body")
    row = {
        "ts": utc_now(),
        "token": str(token) if token else uuid.uuid4().hex,
        "session_id": sid,
        "to": str(to or "").strip() or None,
        "label": str(label).strip() if isinstance(label, str) and label.strip() else None,
        "body": text,
        "path": path_name,
        "status": "pending",
    }
    dest = inbox_path(root, sid)
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {**row, "file": str(dest)}


def _load(root: Path, session_id: str) -> list[dict[str, Any]]:
    dest = inbox_path(root, session_id)
    if not dest.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in dest.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _consumed_tokens(rows: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        tok = row.get("token")
        if not isinstance(tok, str) or not tok:
            continue
        # Old rewrite-in-place drains set status=consumed on the original line.
        # New drains append a consumed-marker. Both mean the token is taken.
        if row.get("status") == "consumed":
            found.add(tok)
    return found


def pending(root: Path, session_id: str) -> list[dict[str, Any]]:
    rows = _load(root, session_id)
    taken = _consumed_tokens(rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        tok = row.get("token")
        if row.get("status") == "pending" and isinstance(tok, str) and tok and tok not in taken:
            out.append(row)
    return out


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Inter-process lock around one inbox file. First-marker-wins is the
    correctness rule; the lock only shrinks the race window."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    locked = False
    try:
        deadline = time.time() + 5
        if os.name == "nt":
            import msvcrt
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b"0")
                fh.flush()
            while True:
                fh.seek(0)
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.time() > deadline:
                        raise TimeoutError("inbox lock")
                    time.sleep(0.01)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.time() > deadline:
                        raise TimeoutError("inbox lock")
                    time.sleep(0.01)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()


def drain(root: Path, session_id: str) -> list[dict[str, Any]]:
    """Append a consumed-marker per pending token. Never rewrite existing lines.

    Concurrent drains: the first consumed-marker for a token wins; losers
    return that token as not taken.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return []
    dest = inbox_path(root, sid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive(dest):
        waiting = pending(root, sid)
        if not waiting:
            return []
        drain_id = uuid.uuid4().hex
        now = utc_now()
        with dest.open("a", encoding="utf-8") as handle:
            for row in waiting:
                marker = {
                    "ts": now,
                    "kind": "consumed-marker",
                    "token": row.get("token"),
                    "session_id": sid,
                    "status": "consumed",
                    "consumed_at": now,
                    "drain_id": drain_id,
                }
                handle.write(json.dumps(marker, separators=(",", ":")) + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        first: dict[str, str] = {}
        for row in _load(root, sid):
            tok = row.get("token")
            if row.get("status") == "consumed" and isinstance(tok, str) and tok and tok not in first:
                first[tok] = str(row.get("drain_id") or "")
        taken: list[dict[str, Any]] = []
        for row in waiting:
            tok = row.get("token")
            if isinstance(tok, str) and first.get(tok) == drain_id:
                taken.append(row)
        return taken


def seats_for_worktree(root: Path, worktree: str | Path | None) -> list[dict[str, Any]]:
    """Every chair whose worktree resolves to this path. Ambiguous is >1."""
    if worktree is None:
        return []
    try:
        want = os.path.normcase(str(Path(worktree).resolve()))
    except OSError:
        return []
    found: list[dict[str, Any]] = []
    for row in list_seats(root, require_session=True):
        raw = row.get("worktree")
        if not raw:
            continue
        try:
            have = os.path.normcase(str(Path(str(raw)).resolve()))
        except OSError:
            continue
        if have == want:
            found.append(row)
    return found


def seat_for_worktree(root: Path, worktree: str | Path | None) -> dict[str, Any] | None:
    """Unique chair for this worktree, or None when zero or more than one match."""
    found = seats_for_worktree(root, worktree)
    if len(found) != 1:
        return None
    return found[0]


def resolve_root(start: str | Path) -> Path | None:
    """Thread root from CONVOY_ROOT, a worktree pointer, or walking up."""
    env = os.environ.get("CONVOY_ROOT")
    if env:
        cand = Path(env)
        if (cand / ".convoy" / "id").is_file():
            return cand
    here = Path(start)
    for rel in POINTER_RELS:
        pointer = here / rel
        if pointer.is_file():
            raw = pointer.read_text(encoding="utf-8-sig").strip()
            if raw:
                cand = Path(raw)
                if (cand / ".convoy" / "id").is_file():
                    return cand
    return find_root(here)


def write_root_pointer(worktree: Path, root: Path) -> None:
    text = str(Path(root).resolve()) + "\n"
    for rel in POINTER_RELS:
        dest = Path(worktree) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def _hook_event_from_stdin() -> str:
    event = "PreToolUse"
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return event
    try:
        if stdin.isatty():
            return event
    except (OSError, ValueError):
        return event
    try:
        raw = stdin.read()
    except OSError:
        return event
    if not (raw or "").strip():
        return event
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return event
    if isinstance(payload, dict):
        name = payload.get("hook_event_name") or payload.get("hookEventName")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return event


def hook_pretooluse(cwd: str | Path | None = None) -> dict[str, Any]:
    """Drain this worktree's inbox into a PreToolUse/UserPromptSubmit card.

    Same JSON for Grok and Claude: allowing-hook additionalContext. Honest
    limit: mid-turn / turn-start, never idle-wake.
    """
    start = Path(cwd) if cwd is not None else Path.cwd()
    root = resolve_root(start) or start
    matches = seats_for_worktree(root, start)
    if len(matches) > 1:
        chairs = [str(r.get("session_id") or "") for r in matches]
        event = _hook_event_from_stdin()
        ctx = (
            "Convoy inbox refuse (C8): cwd " + str(start) +
            " matches more than one chair (" + ", ".join(chairs) +
            "). Drain none rather than guess. Each chair needs its own worktree."
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": ctx,
            }
        }
    seat = matches[0] if matches else None
    sid = str((seat or {}).get("session_id") or "").strip()
    messages = drain(root, sid) if sid else []
    event = _hook_event_from_stdin()
    if not messages:
        # An empty object is the only universally safe no-op. A top-level
        # "decision" is the LEGACY approve|block field: Claude Code rejects
        # "allow" outright ("Hook JSON output validation failed", live in
        # Marco's own pane 2026-09-03), and a context-adding hook has no
        # business voting on permissions at all.
        return {}
    chunks = []
    for item in messages:
        label = item.get("label") or "synapse"
        chunks.append(
            "Convoy inbox (" + str(label) + ") token=" + str(item.get("token") or "") +
            "\n" + str(item.get("body") or "")
        )
    context = (
        "Queued Convoy message(s) for this live seat. "
        "This is delivery into the existing session, not a second --resume.\n\n"
        + "\n\n---\n\n".join(chunks)
    )
    if len(context) > 10000:
        context = context[:9997] + "..."
    if event == "Stop":
        # grok-build 10-hooks.md: a Stop hook may return decision=block and
        # the reason is fed to the model as a user message, keeping the turn
        # alive. So a neuron never goes idle while rows are waiting: the
        # queue is the reason to keep working. (Fable, 2026-09-05, after g1
        # sat idle with 4 rows for an hour because PreToolUse only fires
        # while the agent is already using tools.)
        return {"decision": "block", "reason": context}
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        },
    }


def wait_for_pending(root: Path, session_id: str, *, timeout: float = 3600.0, interval: float = 2.0,
                     clock=None, sleep=None) -> dict[str, Any]:
    """Block until this chair has a pending row, or timeout. A neuron runs
    `convoy inbox --wait --seat <me>` as a BACKGROUND command at the end of
    its turn: grok-build 20-background-tasks.md says a completing background
    command wakes the parent automatically, so the row that ends this wait
    is the row that wakes the idle neuron. Vendor-native; no keystroke, no
    second session. Returns the pending rows without draining them (the
    neuron drains, so the consumed marker is its own)."""
    import time as _t
    clk = clock or _t.monotonic
    slp = sleep or _t.sleep
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "wait requires --seat"}
    budget = max(0.0, float(timeout))
    step = max(0.05, float(interval))
    start = clk()
    while True:
        waiting = pending(root, sid)
        waited = max(0.0, clk() - start)
        if waiting or waited >= budget:
            return {"ok": True, "session_id": sid, "pending": waiting, "n": len(waiting),
                    "waited_s": round(waited, 3), "timed_out": not waiting,
                    "next": "inbox --drain --seat " + sid if waiting else "inbox --wait --seat " + sid}
        slp(min(step, budget - waited))
