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

import time
from typing import Callable

from .bringup import Runner, bring_up, is_conductor, resume_target
from .convoy import list_seats, read_id, read_lead, read_thread, update_seat
from .lifecycle import convoy_root_command
from .crew import await_seated
from .inbox import enqueue, pending
from .layer import feed_since, hook, utc_now
from .pane_host import _read_state, pid_alive, request_close
from .pulse import pulse_is_fresh, read_pulse

EPOCH = "1970-01-01T00:00:00.000000Z"
# How long take-over waits for the host to report the body gone. The host
# polls its child every 200 ms, so this is generous; a body that outlasts it
# is reported, never assumed dead.
EVICT_TIMEOUT_SEC = 30.0
# Host statuses that mean the body this host owned is finished.
_HOST_GONE = ("child-exited", "close-request-acknowledged")


def chair_occupancy(root: Path, row: dict[str, Any], *,
                    alive: Callable[[Any], bool] = pid_alive,
                    now: str | None = None) -> dict[str, Any]:
    """Is this chair occupied, and what says so?

    Recorded, never inferred. The seat row carries the body the pane host
    stamped (incarnation, harness_pid, process_state); the host's own state
    file says how that host ended; the pulse says when something last spoke
    for the chair. `alive` is injected so this is testable without a process
    table, and so a caller can supply a richer prober later.

    `occupied` is True only when a pid of the CURRENT incarnation answers.
    Absence of evidence is not evidence of absence: with nothing recorded at
    all the answer is False with evidence ['no-host'], because a chair nobody
    ever hosted has no body to protect.
    """
    sid = str(row.get("session_id") or "")
    incarnation = row.get("incarnation")
    pid = row.get("harness_pid")
    state = _read_state(Path(root), sid)
    pulse = read_pulse(root, sid)
    evidence: list[str] = []
    if state is None:
        evidence.append("no-host")
    elif str(state.get("status") or "") in _HOST_GONE:
        evidence.append("host-exited")
    occupied = False
    if pid is not None and str(row.get("process_state") or "") != "exited":
        if alive(pid):
            occupied = True
        else:
            evidence.append("pid-dead")
    if pulse is not None and not pulse_is_fresh(pulse, now=now):
        evidence.append("pulse-stale")
    return {
        "chair": sid,
        "incarnation": int(incarnation) if incarnation is not None else None,
        "pid": int(pid) if pid is not None else None,
        "occupied": occupied,
        "evidence": evidence,
        "process_state": row.get("process_state"),
    }


def _unreachable_row(rows: list[dict[str, Any]], sid: str, incarnation: Any) -> dict[str, Any] | None:
    """The `kind=unreachable` row for THIS life, if anyone wrote one. An
    unreachable row from an earlier incarnation says nothing about this body;
    matching it loosely is how an automatic eviction would kill the wrong
    one."""
    found = None
    for r in rows:
        if r.get("kind") != "unreachable" or r.get("chair") != sid:
            continue
        if r.get("incarnation") != incarnation:
            continue
        found = r
    return found


def _evict(root: Path, occupancy: dict[str, Any], *, reason: str,
           sleep: Callable[[float], None], timeout: float) -> dict[str, Any]:
    """Write the eviction row, ask the host to close THAT life, and wait for
    the body to be recorded as gone. Never a kill from here: the host owns the
    process tree and terminal input is not a control surface."""
    sid = occupancy["chair"]
    hook(root, "evicted", "evicted chair " + sid + " incarnation " + str(occupancy["incarnation"]),
         instance_id=sid, author=None,
         extra={"chair": sid, "incarnation": occupancy["incarnation"], "pid": occupancy["pid"],
                "evidence": occupancy["evidence"], "reason": reason})
    try:
        request_close(root, sid, incarnation=occupancy["incarnation"], reason=reason)
    except FileExistsError:
        pass   # a close is already queued for this chair; one is enough
    deadline = time.monotonic() + float(timeout)
    while True:
        latest = [s for s in list_seats(root, require_session=True) if s.get("session_id") == sid]
        if latest and str(latest[-1].get("process_state") or "") == "exited":
            return {"evicted": True, "exited": True}
        if time.monotonic() >= deadline:
            # Reported, never assumed: the caller must see that the body
            # outlived its close rather than read a launch as a clean one.
            return {"evicted": True, "exited": False,
                    "error": "chair " + sid + " did not report exited within " + str(timeout) + "s"}
        sleep(0.2)


def _last_seen(rows: list[dict[str, Any]], sid: str) -> str | None:
    last = None
    for r in rows:
        if r.get("instance_id") == sid or r.get("from") == sid:
            ts = str(r.get("ts") or "")
            if ts and (last is None or ts > last):
                last = ts
    return last



def relaunch_prompt(root: Path, sid: str, *, token: str | None, incarnation: Any, now: str, since: str,
                    worktree: Any) -> str:
    """The re-armed boot prompt of a relaunched chair: catch up, drain, ack with the token its
    join minted, continue; then the same identity tail as a join (lead, launcher, report and
    reply). No wait or wake instruction: each harness receives by its own route (a hook, the
    codex queue, or the drain above)."""
    from .launcher import identity_tail
    cmd = convoy_root_command(root)
    return ("You are the occupant of Convoy seat '" + sid + "', relaunched at " + now +
            " after your pane died. Run " + cmd + " feed --since " + since +
            " then " + cmd + " inbox --drain --seat " + sid +
            " and act on every row. Ack with " + cmd + " seated --seat " + sid +
            (" --token " + token if token else " --token <your join token>") +
            " --incarnation " + str(incarnation) +
            ". Then continue the seat's work from " + str(worktree) + ". " + identity_tail(root, sid))


def relaunch(root: Path | str, *, thread: str | None = None, runner: Runner | None = None,
             timeout: float = 0.0, seats: list[str] | None = None, take_over: bool = False,
             alive: Callable[[Any], bool] = pid_alive,
             sleep: Callable[[float], None] = time.sleep,
             evict_timeout: float = EVICT_TIMEOUT_SEC,
             allow_unverified_launch: bool = False, write_repo_files: bool | None = None) -> dict[str, Any]:
    """seats: relaunch only these chairs (their panes died; the others are
    alive and must not be duplicated). Default: every chair.

    take_over: the human's consent to evict a live body. Without it a chair
    whose body of the current incarnation still answers is REFUSED, because
    from the outside a sleeping harness and a crashed one are the same thing
    (relaunching without this check left several live bodies on one chair).
    The one exception is a `kind=unreachable` row for that exact incarnation,
    which is the only evidence that lets Convoy evict on its own.
    """
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
    if runner is not None:
        try:
            from .harness_contract import validate_launch_eligibility
            for s in chairs:
                validate_launch_eligibility(s.get("to"), allow_unverified_launch=allow_unverified_launch)
        except ValueError as exc:
            card["error"] = str(exc)
            return card
    rows = feed_since(root, EPOCH)
    now = utc_now()
    card["relaunched_at"] = now
    dry = runner is None
    for s in chairs:
        sid = str(s["session_id"])
        entry = {"session_id": sid, "harness": s.get("to"), "worktree": s.get("worktree"),
                 "last_seen": _last_seen(rows, sid), "unread": len(pending(root, sid))}
        occupancy = chair_occupancy(root, s, alive=alive, now=now)
        entry["incarnation"] = occupancy["incarnation"]
        entry["pid"] = occupancy["pid"]
        entry["evidence"] = occupancy["evidence"]
        # Read the resume BEFORE anything launches. pane_child_argv mints a
        # fresh id at spawn for a mint-capable chair that has none, so after
        # bring_up every chair holds one and the answer would always be "yes".
        # `resumed` is whether this relaunch CONTINUES a conversation.
        entry["resumed"] = resume_target(s) is not None
        # The life about to boot: pane_host stamps prev + 1 (pane_host.py:227),
        # so the boot prompt can name it before the body exists.
        entry["next_incarnation"] = int(occupancy["incarnation"] or 0) + 1
        if occupancy["occupied"]:
            proof = _unreachable_row(rows, sid, occupancy["incarnation"])
            if not take_over and proof is None:
                # Refuse by name and say what to run. A relaunch that quietly
                # adds a second body leaves orphaned processes holding memory.
                entry["refused"] = "occupied"
                entry["ask"] = "relaunch --take-over"
                entry["reason"] = ("a body of incarnation " + str(occupancy["incarnation"]) +
                                   " (pid " + str(occupancy["pid"]) + ") is alive and no death row exists")
                card["chairs"].append(entry)
                continue
            entry["evicted_for"] = "take-over" if take_over else "unreachable-row"
            if not dry:
                outcome = _evict(root, occupancy, reason=entry["evicted_for"],
                                 sleep=sleep, timeout=evict_timeout)
                entry["evicted"] = True
                entry["exited"] = outcome["exited"]
                if outcome.get("error"):
                    entry["error"] = outcome["error"]
                if not outcome["exited"]:
                    # The host never recorded the body as gone. Launching now would put a
                    # second body beside a live one — the exact failure the occupancy rule
                    # exists to prevent. Refuse, say why, and leave the evicted row
                    # as the record of the attempt.
                    entry["refused"] = "evict_timeout"
                    entry["ask"] = "relaunch --take-over (again, once the body has exited)"
                    entry["reason"] = ("eviction of incarnation " + str(occupancy["incarnation"]) +
                                       " (pid " + str(occupancy["pid"]) + ") timed out; the body is still alive")
        elif not dry:
            # The body is gone. Say why before spawning the next one, so the
            # record can tell a crash from a close from a chair never hosted.
            if _unreachable_row(rows, sid, occupancy["incarnation"]) is None:
                hook(root, "unreachable", "chair " + sid + " has no live body", instance_id=sid, author=None,
                     extra={"chair": sid, "incarnation": occupancy["incarnation"], "since": now,
                            "evidence": occupancy["evidence"] or ["no-host"]})
        card["chairs"].append(entry)
    launchable = [c for c in card["chairs"] if "refused" not in c]
    sids = [c["session_id"] for c in launchable]
    if not sids:
        card["ok"] = True
        card["launched"] = False
        card["windows"] = []
        card["seated"] = await_seated(root, [], timeout=0.0)
        card["next"] = "relaunch --take-over"
        return card
    if not dry:
        # The boot prompt is ONE-SHOT: join sets it, the seated ack clears it
        # (lifecycle.py). A relaunched pane therefore booted to a blank prompt
        # and no turn ever started (seen live: two grok panes at the welcome
        # screen, inbox rows waiting, Stop gate idle). Re-arm one
        # per chair, carrying the token ITS join minted, so the ack that
        # clears it again is the same proof await_seated already reads.
        # Only launchable chairs: a refused chair keeps the boot prompt its
        # live body is still holding.
        for c in launchable:
            sid = c["session_id"]
            tok = None
            for r in rows:
                if r.get("instance_id") == sid and r.get("kind") in ("join", "swap") and r.get("token"):
                    tok = str(r["token"])
            since = c["last_seen"] or EPOCH
            prompt = relaunch_prompt(root, sid, token=tok, incarnation=c["next_incarnation"], now=now,
                                     since=since, worktree=c["worktree"])
            update_seat(root, sid, boot_prompt=prompt)
            c["boot_prompt_rearmed"] = True
            c["token_found"] = tok is not None
    up = bring_up(root, thread=bound, runner=runner, session_ids=sids, allow_unverified_launch=allow_unverified_launch,
                  write_repo_files=write_repo_files)
    card["windows"] = up.get("windows") or []
    if up.get("error"):
        card["error"] = str(up["error"])
    card["launched"] = (not dry) and bool(up.get("ok")) and all(
        bool(w.get("ok", True)) for w in card["windows"] if isinstance(w, dict))
    if not dry:
        # The temporal handoff, one row per launched chair. Dry never writes,
        # and a refused chair was not relaunched, so it gets no note.
        for c in launchable:
            since = c["last_seen"] or EPOCH
            body = ("Relaunched at " + now + " after the panes died. Your last feed row was " +
                    (c["last_seen"] or "never") + ". " + str(c["unread"]) + " inbox row(s) were waiting. "
                    "Run: convoy --root " + str(root) + " feed --since " + since +
                    "  then  convoy --root " + str(root) + " inbox --drain --seat " + c["session_id"] +
                    "  then ack with  convoy --root " + str(root) + " seated --seat " + c["session_id"] +
                    " --token <the token from your boot prompt>. Continue from your worktree " +
                    str(c["worktree"]) + " on its branch; rebase onto the lead branch before pushing.")
            item = enqueue(root, c["session_id"], body, to=str(c.get("harness") or ""), label="relaunch")
            c["relaunch_note"] = item.get("file")
        hook(root, "relaunch", "relaunch " + str(len(sids)) + " chairs", instance_id=None, author=None,
             extra={"chairs": sids, "relaunched_at": now, "launched": card["launched"],
                    # One row per body this relaunch asked for: which life it is
                    # and whether it continues the chair's conversation or starts
                    # a new one. Without it the feed cannot answer "did that
                    # chair lose its context when it came back?".
                    "bodies": [{"chair": c["session_id"], "incarnation": c["next_incarnation"],
                                "resumed": c["resumed"]} for c in launchable]})
    # Proof: only acks after this relaunch count. timeout=0 is the snapshot.
    card["seated"] = await_seated(root, sids, timeout=timeout, after=now if not dry else None)
    card["ok"] = bool(up.get("ok"))
    card["next"] = "await_seated" if not dry else "relaunch (live)"
    return card
