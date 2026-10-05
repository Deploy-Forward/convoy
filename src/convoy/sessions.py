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


def proven_session_chairs(cwd: Path, root: Path | None = None, *, seen: dict | None = None,
                          probe_timeout: float | None = None) -> list:
    """Every active (root, seat) this calling session is proven to hold, one per thread.

    A session may sit on several threads at once (one chair on each). Native ids are
    checked first; a single native link corroborated by a unique cwd chair needs no
    process scan. Otherwise ONE process-table read proves the session on every candidate
    thread. seen: when given, that read (or its failure in seen["error"]) is left in
    seen["procs"] for the caller's hook to reuse, so one hook reads the table at most once.
    probe_timeout: a hook's budget; the read is then one attempt bounded by it. None (a
    caller outside a hook) keeps the long default. Detached links are never returned."""
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
        # Native-id + unique cwd corroboration needs no machine-wide process
        # scan. Outside/foreign-cwd links, and a session on several threads, use
        # the real identify veto on every candidate from one read below.
        from .inbox import seats_for_worktree
        if len(active_native) == 1:
            candidate, s = active_native[0]
            cwd_seats = seats_for_worktree(candidate, cwd)
            if len(cwd_seats) == 1 and cwd_seats[0]["session_id"] == s["session_id"]:
                return [(candidate, s)]
    if not candidates:
        return []
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
            return []  # The legacy unique cwd route remains available.
        raise ValueError("cannot prove calling session: process table unavailable: " + error)
    hits = []
    for candidate, recorded in candidates:
        me = panes.identify(candidate, cwd=str(cwd), procs=processes, env=os.environ)
        if me.get("ok") and me.get("chair") and me.get("via") in ("environment", "token"):
            seats = [s for s in recorded if s.get("session_id") == me["chair"]]
            if len(seats) == 1:
                hits.append((candidate, seats[0]))
    # An old detached link must not veto the cwd's chair.
    return [hit for hit in hits if not hit[1].get("detached")]


def several_threads_error(hits: list) -> str:
    names = sorted({str(read_id(candidate)) for candidate, _ in hits})
    return ("calling session matches several threads: " + ", ".join(names) +
            "; pass --root or --thread to choose one")


def proven_session_chair(cwd: Path, root: Path | None = None, *, seen: dict | None = None,
                         probe_timeout: float | None = None):
    """The one (root, seat) a caller that needs exactly one thread acts on, or (None, None).
    Several threads refuse with their list: pass --root or --thread."""
    hits = proven_session_chairs(cwd, root, seen=seen, probe_timeout=probe_timeout)
    if len(hits) > 1:
        raise ValueError(several_threads_error(hits))
    return hits[0] if hits else (None, None)


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
    """The first other thread this native session holds a chair on, or None. Reporting
    only: a session may hold one chair on each of any number of threads."""
    hits = attached_threads(root, harness, native_id, skipped=skipped)
    return str(hits[0].get("thread") or hits[0]["convoy_id"]) if hits else None


def attached_threads(root: Path, harness: str, native_id: str, *, skipped=None) -> list[dict]:
    """Every other thread this native session holds an active chair on: {convoy_id, thread}.
    Never infers identity from a path."""
    found: list[dict] = []
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
                found.append({"convoy_id": thread.get("convoy_id"), "thread": thread.get("thread")})
                break
    return found


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
    stamp the seated row, and take a lead that is none or dangling. A session may hold a
    chair on several threads: the card lists the others in `also_on`."""
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
        try:
            also_on = attached_threads(root, harness, native["id"], skipped=skipped)
        except ValueError as exc:   # an unreadable root: reported, never a refusal
            also_on = []
            skipped.append({"reason": str(exc)})
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
                "root": str(root), "seat": row, "also_on": also_on, "ownership_skipped": skipped}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def detach_session(*, root: Path, cwd: Path | None = None, thread: str | None = None):
    try:
        root = resolve_thread(thread) if thread else Path(root)
        if not thread and not read_id(root):
            # A worktree-less attachment cannot install a cwd pointer. Find
            # it only by whoami proof across usable roots, not by recency.
            hits = proven_session_chairs(Path(cwd or Path.cwd()))
            if len(hits) > 1:
                return {"ok": False, "error": "choose --thread: " + several_threads_error(hits)}
            if not hits:
                return {"ok": False, "error": "choose --thread: calling session matches no thread"}
            root = hits[0][0]
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
