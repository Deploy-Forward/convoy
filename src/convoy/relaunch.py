"""Relaunch a thread after the panes died (shutdown, laptop at 1%).

Everything that matters survived on disk: `.convoy/` (id, thread, lead, feed,
seats, inboxes) and every chair's worktree. What died is the panes. Relaunch
brings every chair up again from `seats.jsonl` in its own worktree and, so
each neuron knows WHEN it left off, not only where:

  - reads, per chair, the last feed row it authored or was the subject of
    (`last_seen`) and how many inbox rows it never drained (`unread`);
  - queues one row into each chair's inbox: relaunched at <ts>, your last row
    was <ts>, run `feed --since <that ts>` then `inbox --drain`;
  - proves connected only from seated acks stamped AFTER the relaunch. The
    acks from the chair's previous life are on the feed and would otherwise
    read as connected the instant the window opens.

Nothing here is a second store: the relaunch note is an inbox row, the proof
is a seated row, the timeline is the feed (docs/CONVOY_SOT.md).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .bringup import Runner, bring_up, is_conductor
from .convoy import list_seats, read_id, read_lead, read_thread
from .crew import await_seated
from .inbox import enqueue, pending
from .layer import feed_since, hook, utc_now

EPOCH = "1970-01-01T00:00:00.000000Z"


def _last_seen(rows: list[dict[str, Any]], sid: str) -> str | None:
    last = None
    for r in rows:
        if r.get("instance_id") == sid or r.get("from") == sid:
            ts = str(r.get("ts") or "")
            if ts and (last is None or ts > last):
                last = ts
    return last


def relaunch(root: Path | str, *, thread: str | None = None, runner: Runner | None = None,
             timeout: float = 0.0, seats: list[str] | None = None) -> dict[str, Any]:
    """seats: relaunch only these chairs (their panes died; the others are
    alive and must not be duplicated). Default: every chair."""
    root = Path(root)
    cid = read_id(root)
    bound = read_thread(root)
    card: dict[str, Any] = {"ok": False, "convoy_id": cid, "thread": bound, "lead": read_lead(root),
                            "root": str(root), "relaunched_at": None, "chairs": [], "launched": False}
    if cid is None:
        card["error"] = "no thread at " + str(root) + ": nothing to relaunch"
        return card
    if thread is not None and bound != thread:
        card["error"] = "thread mismatch: root is bound to " + repr(bound) + ", not " + repr(thread)
        return card
    chairs = [s for s in list_seats(root, convoy_id=cid) if not is_conductor(s.get("to"))]
    if seats:
        want = [str(x) for x in seats]
        known = {str(s.get("session_id")) for s in chairs}
        unknown = [x for x in want if x not in known]
        if unknown:
            card["error"] = "unknown seat: " + ", ".join(unknown)
            return card
        chairs = [s for s in chairs if str(s.get("session_id")) in want]
    if not chairs:
        card["error"] = "no chairs on this thread: crew first"
        return card
    rows = feed_since(root, EPOCH)
    now = utc_now()
    card["relaunched_at"] = now
    sids = [str(s["session_id"]) for s in chairs]
    for s in chairs:
        sid = str(s["session_id"])
        card["chairs"].append({"session_id": sid, "harness": s.get("to"), "worktree": s.get("worktree"),
                               "last_seen": _last_seen(rows, sid), "unread": len(pending(root, sid))})
    dry = runner is None
    up = bring_up(root, thread=bound, runner=runner, session_ids=sids)
    card["windows"] = up.get("windows") or []
    if up.get("error"):
        card["error"] = str(up["error"])
    card["launched"] = (not dry) and bool(up.get("ok")) and all(
        bool(w.get("ok", True)) for w in card["windows"] if isinstance(w, dict))
    if not dry:
        # The temporal handoff, one row per chair. Dry never writes.
        for c in card["chairs"]:
            since = c["last_seen"] or EPOCH
            body = ("Relaunched at " + now + " after the panes died. Your last feed row was " +
                    (c["last_seen"] or "never") + "; " + str(c["unread"]) + " inbox row(s) were waiting. "
                    "Run: convoy --root " + str(root) + " feed --since " + since +
                    "  then  convoy --root " + str(root) + " inbox --drain --seat " + c["session_id"] +
                    "  then ack with  convoy --root " + str(root) + " seated --seat " + c["session_id"] +
                    " --token <the token from your boot prompt>. Continue from your worktree " +
                    str(c["worktree"]) + " on its branch; rebase onto the lead branch before pushing.")
            item = enqueue(root, c["session_id"], body, to=str(c.get("harness") or ""), label="relaunch")
            c["relaunch_note"] = item.get("file")
        hook(root, "relaunch", "relaunch " + str(len(sids)) + " chairs", instance_id=None, author=None,
             extra={"chairs": sids, "relaunched_at": now, "launched": card["launched"]})
    # Proof: only acks after this relaunch count. timeout=0 is the snapshot.
    card["seated"] = await_seated(root, sids, timeout=timeout, after=now if not dry else None)
    card["ok"] = bool(up.get("ok"))
    card["next"] = "await_seated" if not dry else "relaunch (live)"
    return card
