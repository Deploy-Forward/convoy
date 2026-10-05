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

from .convoy import list_seats, observe_resume
from .filelock import append_line, exclusive
from .index import find_root
from .layer import utc_now


POINTER_RELS = (
    Path(".grok") / "convoy-root",
    Path(".claude") / "convoy-root",
    Path(".codex") / "convoy-root",
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
    A label, not a connection: only the chair's own kind=seated row proves one."""
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
    # Synced: a sent message is the thing that must survive a power loss. `durable` false means the
    # row is written but the disk did not confirm it.
    durable = append_line(dest, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"), fsync=True)
    return {**row, "file": str(dest), "durable": durable}


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


def reply_index(feed_rows) -> dict[str, dict[str, str]]:
    """One pass, proven authors only. Keep the latest receipt per chair/token.

    Proven means conductor.RECEIPT_PROOF (environment, token or pane-host), the same set that
    counts delivery, so clearing a pending row and counting a receipt never disagree. A
    citation is either spelling, `token=<t>` or `re token <t>` (wake_dispatch.cited_tokens)."""
    from .conductor import RECEIPT_PROOF
    from .wake_dispatch import cited_tokens
    answers = {}
    for reply in feed_rows:
        author = reply.get("from")
        if (not isinstance(author, str) or not author or reply.get("author_claimed") or
            reply.get("verified_by") not in RECEIPT_PROOF or
            reply.get("kind") not in ("note", "synapse", "send")):
            continue
        tokens = set(cited_tokens(str(reply.get("summary") or "")))
        extra = reply.get("reply_tokens")
        if isinstance(extra, list):
            tokens.update(t for t in extra if isinstance(t, str))
        dest = answers.setdefault(author, {})
        for token in tokens:
            dest[token] = max(dest.get(token, ""), str(reply.get("ts") or ""))
    return answers


def pending(root: Path, session_id: str, *, replies=None) -> list[dict[str, Any]]:
    rows = _load(root, session_id)
    taken = _consumed_tokens(rows)
    from .layer import feed_since
    if replies is None:
        replies = reply_index(feed_since(root, "1970-01-01T00:00:00.000000Z"))
    receipts = replies.get(session_id, {})
    out: list[dict[str, Any]] = []
    for row in rows:
        tok = row.get("token")
        if row.get("status") == "pending" and isinstance(tok, str) and tok and tok not in taken:
            if receipts.get(tok, "") <= str(row.get("ts") or ""):
                out.append(row)
    return out


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Inter-process lock around one inbox file (filelock.exclusive, the one lock
    every append also takes). First-marker-wins is the correctness rule; the lock
    only shrinks the race window."""
    with exclusive(path, timeout=5):
        yield


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
        markers = "".join(json.dumps({
            "ts": now,
            "kind": "consumed-marker",
            "token": row.get("token"),
            "session_id": sid,
            "status": "consumed",
            "consumed_at": now,
            "drain_id": drain_id,
        }, separators=(",", ":")) + "\n" for row in waiting)
        # A failed write raises and marks nothing, so the drain is retried. A failed sync after the
        # write still hands the rows over below: they are marked consumed, so this drain owns them.
        append_line(dest, markers.encode("utf-8"), fsync=True)
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


def _hook_payload_from_stdin() -> dict[str, Any]:
    """The harness's hook payload, or {}. Read ONCE per process: stdin is a
    stream, not a file, and a second read returns nothing."""
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return {}
    try:
        if stdin.isatty():
            return {}
    except (OSError, ValueError):
        return {}
    try:
        raw = stdin.read()
    except OSError:
        return {}
    if not (raw or "").strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hook_event_name(payload: dict[str, Any] | None) -> str:
    name = (payload or {}).get("hook_event_name") or (payload or {}).get("hookEventName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "PreToolUse"


def _hook_event_from_stdin() -> str:
    return _hook_event_name(_hook_payload_from_stdin())


USAGE_ROW_MIN_S = 300.0


def last_usage_row(root: Path, session_id: str) -> dict[str, Any] | None:
    from .layer import feed_since
    last = None
    for r in feed_since(root, "1970-01-01T00:00:00.000000Z"):
        if r.get("kind") == "usage" and r.get("instance_id") == session_id:
            last = r
    return last


def stamp_usage_row(root: Path, session_id: str, harness: str, *, probe_fn=None, now: str | None = None,
                    require_source: bool = False) -> dict[str, Any] | None:
    """One kind=usage row for this chair from its vendor's own reading, at
    most every USAGE_ROW_MIN_S. Returns the row, or None when skipped.
    require_source=True skips the row when the vendor gave no reading (a
    launch heartbeat must not write "unknown" rows)."""
    from datetime import datetime, timezone
    from .index import home_dir
    from .layer import hook, utc_now
    from .usage import probe, surface
    stamp = now or utc_now()
    prev = last_usage_row(root, session_id)
    if prev is not None:
        try:
            a = datetime.fromisoformat(str(prev.get("stamped_at") or prev.get("ts")).replace("Z", "+00:00"))
            b = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if (b - a).total_seconds() < USAGE_ROW_MIN_S:
                return None
        except ValueError:
            pass
    if probe_fn is not None:
        got = probe_fn(harness)
    else:
        # From CONVOY_HOME, never from the chair's worktree. The probe
        # shells out to the harness, and `claude -p /usage` leaves a stub
        # session record in whatever directory it runs in; run from the
        # chair's worktree, the stubs pile up in its project directory.
        home = home_dir()
        try:
            home.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        got = probe(harness, cwd=home if home.is_dir() else None)
    if require_source and not got.get("source"):
        return None
    # A reading the vendor has not restamped is the same reading, and writing
    # it again says the quota moved when it did not. The numbers are compared
    # too: as_of alone would hide a reading that DID move under a stamp the
    # vendor forgot to bump, and a hidden number is worse than a repeated one.
    if prev is not None and got.get("as_of") and prev.get("as_of") == got.get("as_of"):
        same = (prev.get("session_pct") == got.get("session_pct")
                and prev.get("week_pct") == got.get("week_pct")
                and bool(prev.get("limited")) == bool(got.get("limited")))
        if same:
            return None
    view = surface(harness, got)
    extra = {"harness": harness, "stamped_at": stamp,
             "session_pct": view.get("session_pct"), "week_pct": view.get("week_pct"),
             "resets": view.get("resets"), "limited": bool(view.get("limited")),
             "source": got.get("source"), "as_of": got.get("as_of"), "tier": got.get("tier")}
    text = harness + " usage: " + (str(100 - view["session_pct"]) + "% left 5h" if isinstance(view.get("session_pct"), int) else "session unknown") + \
           ", " + (str(100 - view["week_pct"]) + "% left week" if isinstance(view.get("week_pct"), int) else "week unknown")
    return hook(root, "usage", text, instance_id=session_id, author=session_id, extra=extra)


def delivery_context(messages: list[dict[str, Any]]) -> str:
    """The rows as one framed body, bounded. The only place this text is
    built: the Stop block and the context card must read identically, and
    Claude's Stop path (end.py) needs the same framing Grok's already had."""
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
    return context


def stop_block(root: Path, session_id: str) -> dict[str, Any] | None:
    """The Stop-hook block for a chair with rows waiting, or None.

    grok-build 10-hooks.md: a Stop hook may return decision=block and the
    reason is fed to the model as a user message, keeping the turn alive. So a
    neuron never goes idle while rows are waiting: the queue is the reason to
    keep working. Grok had this first (without it a chair sat idle with rows
    waiting, because PreToolUse only fires while the agent is already using
    tools); Claude and Codex reach it through end.py, which is where their
    Stop hook lands.

    Draining here is deliberate: a block that re-served the same rows at every
    Stop would be a loop, not a delivery.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return None
    messages = drain(root, sid)
    if not messages:
        return None
    return {"decision": "block", "reason": delivery_context(messages)}


STAMP_DECISIONS_RELATIVE = Path(".convoy") / "hook-stamps.json"
STAMP_RETRY_S = 600      # a decision that can change (a failed read, a refused replace) is retried after this
STAMP_KEEP = 256         # newest decisions kept


def _stamp_decisions(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((Path(root) / STAMP_DECISIONS_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _seat_state(seat: dict[str, Any]) -> str:
    """What a decision depended on in the seat: a recorded id or a pane-host body changing makes
    the decision stale, including a hosted pid that stopped answering (one cheap handle probe,
    never a process-table read)."""
    hosted = seat.get("harness_pid") is not None and str(seat.get("process_state") or "") != "exited"
    if hosted:
        from .pane_host import pid_alive
        hosted = pid_alive(seat.get("harness_pid"))
    return "|".join([str(seat.get("resume") or ""), str(seat.get("harness_pid") or ""), "live" if hosted else ""])


def _record_stamp_decision(root: Path, key: str, decision: str, retry_s: float | None,
                           seat_state: str = "", budget: float | None = None) -> None:
    now = time.time()
    data = _stamp_decisions(root)
    data[key] = {"decision": decision, "ts": now, "until": now + retry_s if retry_s else None,
                 "seat": seat_state}
    if budget is not None:
        data[key]["budget"] = float(budget)
    keep = sorted(data.items(), key=lambda kv: (kv[1] or {}).get("ts") or 0 if isinstance(kv[1], dict) else 0)
    data = dict(keep[-STAMP_KEEP:])
    path = Path(root) / STAMP_DECISIONS_RELATIVE
    try:
        tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass   # a lost decision costs one more read, never a wrong stamp


def _within_budget(budget: float, failed_budget: Any) -> bool:
    """A failed read suppresses a later hook only when that hook's budget is no larger: a failed
    2 s inbox read must never stop the Stop hook's longer read. A decision with no recorded
    budget is unknown, never zero, so it suppresses nothing."""
    try:
        return failed_budget is not None and budget <= float(failed_budget)
    except (TypeError, ValueError):
        return False


def stamp_from_hook(root: Path, seat: dict[str, Any], observed: Any, *, allow_replace: bool = False,
                    procs: list[dict[str, Any]] | None = None, read_error: str | None = None,
                    timeout: float | None = None) -> dict[str, Any] | None:
    """The one gate every hook stamps a chair's resume through. Returns the updated seat or None.

    The harness is the body that runs this hook, read from its own ancestry; a nested body (a
    `codex exec` run by a neuron) or no body stamps nothing. The table is read only for an id the
    seat does not hold, once, with one attempt bounded by timeout (`procs` / `read_error` reuse
    the table or the failure of a read the hook already made, so it never reads twice), and each refusal is remembered per (chair, hash of the id) in .convoy/hook-stamps.json:
    while the seat's recorded id and pane-host body are unchanged, for good when it cannot change
    and for STAMP_RETRY_S when it can (a failed read, a refused replace). A failed read records its
    budget and holds only against a hook whose budget is no larger, so the Stop hook still reads
    after a failed inbox read. allow_replace: the Stop hook's exact-worktree case; observe_resume adds the
    pane-host and cooldown refusals."""
    import hashlib
    from .harness_contract import canonical_harness_id
    from .panes import HOOK_PROBE_TIMEOUT_S, hook_body
    sid = str(seat.get("session_id") or "").strip()
    new_id = str(observed or "").strip() if isinstance(observed, str) else ""
    if not sid or not new_id or new_id == str(seat.get("resume") or "").strip():
        return None
    key = sid + ":" + hashlib.sha256(new_id.encode("utf-8")).hexdigest()[:16]
    known = _stamp_decisions(root).get(key)
    state = _seat_state(seat)
    budget = HOOK_PROBE_TIMEOUT_S if timeout is None else float(timeout)
    if isinstance(known, dict) and known.get("seat", "") == state and (
            known.get("until") is None or time.time() < float(known["until"])) and (
            known.get("decision") != "no-read" or _within_budget(budget, known.get("budget"))):
        return None
    body = hook_body(procs=procs, read_error=read_error, timeout=budget)
    if body.get("error"):
        _record_stamp_decision(root, key, "no-read", STAMP_RETRY_S, state, budget=budget)
        return None
    harness = canonical_harness_id(body["harness"]) if body.get("harness") else None
    if not harness or body.get("nested") is not False:
        _record_stamp_decision(root, key, "no-top-level-body", None, state)
        return None
    replace = allow_replace and harness == "codex" and canonical_harness_id(seat.get("to")) == "codex"
    updated = observe_resume(root, sid, new_id, to=harness, replace=replace)
    if updated is None:
        _record_stamp_decision(root, key, "refused", STAMP_RETRY_S if replace else None, state)
    return updated


def hook_pretooluse(cwd: str | Path | None = None) -> dict[str, Any]:
    """Drain this worktree's inbox into a PreToolUse/UserPromptSubmit card.

    Same JSON for Grok and Claude: allowing-hook additionalContext. Honest
    limit: mid-turn / turn-start, never idle-wake.
    """
    start = Path(cwd) if cwd is not None else Path.cwd()
    root = resolve_root(start) or start
    # Read the payload once: stdin is a stream and the second read is empty.
    payload = _hook_payload_from_stdin()
    from .panes import HOOK_PROBE_TIMEOUT_S
    from .sessions import proven_session_chair
    seen: dict[str, Any] = {}
    try:
        proven_root, proven_seat = proven_session_chair(start, seen=seen, probe_timeout=HOOK_PROBE_TIMEOUT_S)
    except ValueError as exc:
        return {"hookSpecificOutput": {"hookEventName": _hook_event_name(payload), "additionalContext": "Convoy inbox refuses: " + str(exc)}}
    if proven_root is not None:
        root, matches = proven_root, [proven_seat]
    else:
        matches = seats_for_worktree(root, start)
    if len(matches) > 1:
        chairs = [str(r.get("session_id") or "") for r in matches]
        event = _hook_event_name(payload)
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
    if seat and seat.get("detached"):
        return {}
    sid = str((seat or {}).get("session_id") or "").strip()
    event = _hook_event_name(payload)
    if sid:
        # Every Grok and Claude hook payload carries the session id, and
        # Grok also exports GROK_SESSION_ID (user guide 10-hooks.md:256, :492).
        # Stamp it on the chair this cwd matched, through the same gate as
        # the Stop hook (stamp_from_hook). Null until observed; an id already
        # on the row is never overwritten here, and the feed never sees it.
        observed = payload.get("session_id") or payload.get("sessionId")
        if not observed and str((seat or {}).get("to") or "").strip().startswith("grok"):
            observed = os.environ.get("GROK_SESSION_ID")
        try:
            stamp_from_hook(root, seat or {}, observed, procs=seen.get("procs"),
                            read_error=seen.get("error"), timeout=HOOK_PROBE_TIMEOUT_S)
        except Exception:   # an id stamp must never break a hook
            pass
    if event == "PostToolUse" and sid:
        # A user may log in with another account when usage
        # is low, so the meter is per PANE, not per machine. After a tool
        # call the pane stamps its OWN vendor reading (the snapshot its login
        # produced) as kind=usage, at most every USAGE_ROW_MIN_S. The widget
        # reads it per chair. Never a number the vendor did not give.
        try:
            stamp_usage_row(root, sid, str((seat or {}).get("to") or ""))
        except Exception:  # a usage stamp must never break a hook
            pass
    messages = drain(root, sid) if sid else []
    if messages and event == "Stop":
        return {"decision": "block", "reason": delivery_context(messages)}
    if not messages:
        # An empty object is the only universally safe no-op. A top-level
        # "decision" is the LEGACY approve|block field: Claude Code rejects
        # "allow" outright ("Hook JSON output validation failed", seen
        # live in a pane), and a context-adding hook has no
        # business voting on permissions at all.
        return {}
    context = delivery_context(messages)
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
        detached = any(s.get("session_id") == sid and s.get("detached") for s in list_seats(root))
        if detached:
            return {"ok": False, "session_id": sid, "error": "detached; attach again", "pending": [], "n": 0}
        waiting = pending(root, sid)
        waited = max(0.0, clk() - start)
        if waiting or waited >= budget:
            return {"ok": True, "session_id": sid, "pending": waiting, "n": len(waiting),
                    "waited_s": round(waited, 3), "timed_out": not waiting,
                    "next": "inbox --drain --seat " + sid if waiting else "inbox --wait --seat " + sid}
        slp(min(step, budget - waited))
