"""Attach/detach the calling native session. Never launch or close a body."""
from __future__ import annotations

import uuid
import os
from pathlib import Path

from .convoy import attach as catch_up, broad_worktree, chair_holding_worktree, list_seats, read_id, seat, update_seat
from .harness_contract import canonical_harness_id
from .index import is_temp_root, list_threads
from .layer import hook, utc_now
from .panes import identify
from .thread_list import thread_list


def proven_session_chair(cwd: Path, root: Path | None = None, *, seen: dict | None = None,
                         probe_timeout: float | None = None):
    """Prefer active native links; keep ordinary cwd hooks cheap and available.
    seen: when given, a process table read here is left in seen["procs"] (or its failure in
    seen["error"]) for the caller's hook to reuse, so one hook reads the table at most once.
    probe_timeout: a hook's budget; the read is then one attempt bounded by it. None (a caller
    outside a hook) keeps the long default."""
    from . import panes
    roots = [root] if root is not None else [Path(t["root"]) for t in list_threads()
        if t.get("present") and not is_temp_root(str(t.get("root") or ""))]
    candidates = [(candidate, list_seats(candidate)) for candidate in roots]
    candidates = [(candidate, seats) for candidate, seats in candidates
                  if any(s.get("resume") or s.get("vendor_session_id") for s in seats)]
    native_ids = {h: str(os.environ.get(key) or "").strip() for h, key in
                  (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"))}
    native_ids = {h: value for h, value in native_ids.items() if value}
    if native_ids:
        def matches_native(s):
            harness = canonical_harness_id(s.get("to"))
            tokens = [s.get("vendor_session_id")]
            resume_for = canonical_harness_id(s.get("resume_for")) if s.get("resume_for") else None
            if resume_for in (None, harness):
                tokens.append(s.get("resume"))
            return native_ids.get(harness) in tokens and harness in native_ids
        candidates = [(candidate, seats) for candidate, seats in candidates
                      if any(matches_native(s) and not s.get("detached") for s in seats)]
        active_native = [(candidate, s) for candidate, seats in candidates
                         for s in seats if matches_native(s) and not s.get("detached")]
        if len({str(candidate) for candidate, _ in active_native}) > 1:
            names = sorted({str(read_id(candidate)) for candidate, _ in active_native})
            raise ValueError("calling session matches multiple threads: " + ", ".join(names) + "; detach --thread <cvy_id> before continuing")
        # Native-id + unique cwd corroboration needs no machine-wide process
        # scan. Outside/foreign-cwd links still use the real identify veto.
        from .inbox import seats_for_worktree
        for candidate, s in active_native:
            cwd_seats = seats_for_worktree(candidate, cwd)
            if len(active_native) == 1 and len(cwd_seats) == 1 and cwd_seats[0]["session_id"] == s["session_id"]:
                return candidate, s
    if not candidates:
        return None, None
    if panes._TEST_PROCS is not None:
        processes, error = panes._TEST_PROCS, None
    elif probe_timeout is not None:
        processes, error = panes._safe_enumerate(attempts=1, timeout=probe_timeout)
    else:
        processes, error = panes._safe_enumerate()
    if seen is not None:
        seen["error" if error else "procs"] = error or processes
    if error:
        from .inbox import resolve_root, seats_for_worktree
        cwd_root = root or resolve_root(cwd)
        if cwd_root is not None and len(seats_for_worktree(cwd_root, cwd)) == 1:
            return None, None  # The legacy unique cwd route remains available.
        raise ValueError("cannot prove calling session: process table unavailable: " + error)
    hits = []
    for candidate, recorded in candidates:
        me = panes.identify(candidate, cwd=str(cwd), procs=processes, env=os.environ)
        if me.get("ok") and me.get("chair") and me.get("via") in ("environment", "token"):
            seats = [s for s in recorded if s.get("session_id") == me["chair"]]
            if len(seats) == 1:
                hits.append((candidate, seats[0]))
    active = [hit for hit in hits if not hit[1].get("detached")]
    if len(active) > 1:
        names = sorted({str(read_id(candidate)) for candidate, _ in active})
        raise ValueError("calling session matches multiple threads: " + ", ".join(names) + "; detach --thread <cvy_id> before continuing")
    if active:
        return active[0] if len(active) == 1 else (None, None)
    return None, None  # An old detached link must not veto the cwd's chair.


PREFIX_MIN = 8  # characters of a cvy_ id, "cvy_" included


def _same_root(raw: str, root: str) -> bool:
    try:
        return os.path.normcase(str(Path(raw).expanduser().resolve())) == os.path.normcase(str(Path(root).resolve()))
    except (OSError, ValueError):
        return False


def resolve_thread(choice: str) -> Path:
    """The one thread resolver (attach, detach --thread, lead --thread): the exact
    cvy_ id, an exact thread name, the thread's root path, or a unique prefix of
    the cvy_ id of at least PREFIX_MIN characters. Temp and absent roots refuse."""
    choice = str(choice or "").strip()
    rows = list_threads()
    if choice.isdigit():
        raise ValueError("pass the cvy_ id from convoy list")
    # An exact id is unique and wins. Every other reading (name, root path, prefix) counts:
    # two threads it could mean refuse, naming both ids.
    hits = [t for t in rows if choice and t.get("convoy_id") == choice]
    if not hits and choice:
        hits = [t for t in rows if t.get("thread") == choice
                or (t.get("root") and _same_root(choice, str(t["root"])))
                or (choice.startswith("cvy_") and len(choice) >= PREFIX_MIN
                    and str(t.get("convoy_id") or "").startswith(choice))]
        if not hits and choice.startswith("cvy_") and len(choice) < PREFIX_MIN:
            raise ValueError("a cvy_ prefix needs at least " + str(PREFIX_MIN) + " characters; choose a thread from convoy list")
    if len(hits) > 1:
        raise ValueError("matches " + str(len(hits)) + " threads: "
                         + ", ".join(sorted(str(t.get("convoy_id")) for t in hits)))
    if not hits:
        raise ValueError("unknown thread; choose a thread from convoy list")
    row = hits[0]
    if not row.get("present") or is_temp_root(str(row.get("root") or "")):
        raise ValueError("thread is skipped: " + ("root gone" if not row.get("present") else "temp"))
    return Path(row["root"])


def attached_elsewhere(root: Path, harness: str, native_id: str, *, skipped=None) -> str | None:
    """Shared join/attach ownership guard; never infer identity from a path."""
    for thread in list_threads():
        if is_temp_root(str(thread.get("root") or "")):
            if skipped is not None:
                skipped.append({"convoy_id": thread.get("convoy_id"), "reason": "temp: not an attachable thread"})
            continue
        if not thread.get("present"):
            if thread.get("skip_reason") == "id changed":
                if skipped is not None:
                    skipped.append({"convoy_id": thread.get("convoy_id"), "reason": "id changed"})
                continue
            raise ValueError("attachment ownership unknown: unavailable root " + str(thread.get("convoy_id")) + "; inspect the root or run convoy threads --prune")
        other = Path(thread["root"])
        if other.resolve() == root.resolve():
            continue
        for existing in list_seats(other):
            tokens = [existing.get("vendor_session_id")]
            resume_for = canonical_harness_id(existing.get("resume_for")) if existing.get("resume_for") else None
            if resume_for in (None, harness):
                tokens.append(existing.get("resume"))
            if (not existing.get("detached") and canonical_harness_id(existing.get("to")) == harness and
                native_id in tokens):
                return str(thread.get("thread") or thread["convoy_id"])
    return None


def attach_session(choice: str | None, *, cwd: Path | None = None, as_harness: str | None = None):
    if not choice:
        return {"ok": False, "error": "choose a thread", "list": thread_list()}
    try:
        root = resolve_thread(str(choice))
        here = Path(cwd or Path.cwd()).resolve()
        me = identify(root, cwd=str(here), allow_unseated=True)
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return attach_proven(root, here, me, as_harness=as_harness)


def attach_proven(root: Path, here: Path, me: dict, *, as_harness: str | None = None):
    """Attach the session `me` proves (identify(..., allow_unseated=True)) to this root.

    The one attach rule, shared by `convoy attach` and by a launch whose launcher is not
    seated yet: refuse without environment or token proof, seat (or re-attach) the chair,
    stamp the seated row, and take a lead that is none or dangling."""
    try:
        root = Path(root)
        here = Path(here).resolve()
        native = me.get("native_session") or {}
        if not me.get("ok") or not native.get("id") or native.get("via") not in ("environment", "token"):
            return {"ok": False, "error": "cannot prove calling native session: " + str(me.get("ask") or "native id unavailable")}
        harness = native["harness"]
        if me.get("chair") and me.get("via") not in ("environment", "token"):
            return {"ok": False, "error": "recorded chair does not match calling native session; refuse attach"}
        if as_harness and canonical_harness_id(as_harness) != harness:
            return {"ok": False, "error": "--as-harness disagrees with calling harness " + harness}
        skipped = []
        elsewhere = attached_elsewhere(root, harness, native["id"], skipped=skipped)
        if elsewhere:
            return {"ok": False, "error": "attached to " + elsewhere + "; detach first"}
        sid = me.get("chair")
        already = bool(sid)
        if not sid:
            sid = harness + "-" + uuid.uuid4().hex[:12]
            # A shared project root, broad cwd, or foreign binding is not a
            # unique worktree. Native identity still allows a worktree-less
            # chair; never overwrite another thread's pointer or seat.
            from .index import find_root
            foreign = find_root(here)
            wt = None if (broad_worktree(str(here)) or chair_holding_worktree(root, str(here)) or
                          (foreign and foreign.resolve() != root.resolve())) else str(here)
            seat(root, harness, sid, worktree=wt, resume=native["id"])
        row = update_seat(root, sid, detached=False, attached_at=utc_now(), verified_by=native["via"])
        hook(root, "seated", "attached calling session", instance_id=sid, author=sid,
             verified_by=native["via"])
        # A lead nobody can reach (unset, or a harness with no seated chair)
        # passes to the chair that just proved itself; a real lead is kept.
        from .lifecycle import lead_state, take_lead
        state = lead_state(root)
        taken = take_lead(root, sid, state) if state["status"] != "held" else None
        # Do not run vendor usage CLIs just to attach. Unknown quota is honest.
        card = catch_up(root, probe_fn=lambda h: {}, session_id=sid)
        return {**card, "chair": sid, "already": already, "verified_by": native["via"], "lead_taken": taken,
                "root": str(root), "seat": row, "ownership_skipped": skipped}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def detach_session(*, root: Path, cwd: Path | None = None, thread: str | None = None):
    try:
        root = resolve_thread(thread) if thread else Path(root)
        if not thread and not read_id(root):
            # A worktree-less attachment cannot install a cwd pointer. Find
            # it only by whoami proof across usable roots, not by recency.
            hits = []
            for t in list_threads():
                if not t.get("present") or is_temp_root(str(t.get("root") or "")):
                    continue
                candidate = Path(t["root"])
                found = identify(candidate, cwd=str(cwd or Path.cwd()))
                if found.get("ok") and found.get("chair") and found.get("via") in ("environment", "token"):
                    rows = [s for s in list_seats(candidate) if s.get("session_id") == found["chair"]]
                    if len(rows) == 1 and not rows[0].get("detached"):
                        hits.append(candidate)
            if len(hits) != 1:
                return {"ok": False, "error": "choose --thread: calling session matches " + str(len(hits)) + " threads"}
            root = hits[0]
        me = identify(root, cwd=str(cwd or Path.cwd()))
        if not me.get("ok") or not me.get("chair") or me.get("via") not in ("environment", "token"):
            return {"ok": False, "error": "cannot prove calling chair: " + str(me.get("ask") or "unknown")}
        sid = me["chair"]
        row = next(s for s in list_seats(root) if s.get("session_id") == sid)
        from .end import _git_snapshot, _run_git, write_rolling_handoff
        from .inbox import pending
        now = utc_now()
        git = _git_snapshot(Path(row.get("worktree") or cwd or root), _run_git)
        path = write_rolling_handoff(root, sid, seat=row, git=git,
                                     pending_count=len(pending(root, sid)), now=now)
        update_seat(root, sid, detached=True, detached_at=now)
        hook(root, "detach", "detached; attach again", instance_id=sid, author=sid, verified_by=me["via"])
        return {"ok": True, "chair": sid, "detached": True, "handoff": str(path), "root": str(root)}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
