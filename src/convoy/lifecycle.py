"""Seat lifecycle: join + swap + seated (LIVE_SEAT_SPEC).

The seat is the chair; the neuron is the occupant. Chair identity is
session_id, full stop. swap replaces the occupant and NEVER reuses a vendor
resume token (the ordering lock + the no-steal lock forbid two live
processes on one vendor session): every replacement starts a fresh vendor
session and rehydrates from the handoff + thread state — memory is Convoy
state, always, and the swap row records that so no reader upgrades the claim.

Verbs are neuron-authored: the conductor ASKS for a swap via stamp, it never
performs one (hook refuses conductor aliases as author).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .refusal import next_step
from .cmd import convoy_root_command
from .convoy import list_seats, read_lead, read_thread, seat as write_seat, set_lead, update_seat
from .harness_contract import validate_effort, validate_model, validate_where
from .layer import feed_since, hook


def _mint_token() -> str:
    return uuid.uuid4().hex


def _require_seat(root: Path, session_id: str) -> dict[str, Any]:
    for row in list_seats(root):
        if row.get("session_id") == session_id:
            return row
    raise ValueError("unknown seat: " + str(session_id))


_UNSET: Any = object()
SWAP_LAUNCHER_WHY = "recorded when this chair is launched"


def _boot_prompt(root: Path, session_id: str, token: str, handoff: str) -> str:
    # The seated-ack delivery mechanism: an initial positional prompt
    # — NOT -p print mode; the session stays interactive. One line: read, ack,
    # continue. bring_up never packs, so the handoff pointer rides here.
    # It names only files that exist: a thread started without a name has no
    # thread.md, and a prompt pointing at one made the neuron's first command fail.
    # Then who leads and who launched this chair (information, not rules), and the
    # two commands that route in code: report and reply.
    from .launcher import identity_tail
    thread_path = Path(root) / "thread.md"
    handoff_path = Path(handoff)
    if not handoff_path.is_absolute():
        handoff_path = Path(root) / handoff_path
    same = False
    try:
        same = handoff_path.resolve() == thread_path.resolve()
    except OSError:
        same = str(handoff_path) == str(thread_path)
    files = [p for p in ([thread_path] if same else [thread_path, handoff_path]) if p.is_file()]
    reads = ("Read " + " and ".join(str(p) for p in files) + ". ") if files else ""
    cmd = convoy_root_command(root)
    return (
        "You are the new occupant of Convoy seat '" + session_id + "'. "
        + reads + "Then run: "
        + cmd + " seated --seat " + session_id +
        " --token " + token + " — then continue the seat's work. "
        + identity_tail(root, session_id)
    )


def refresh_identity(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Recompose the identity tail of a pending boot prompt from the thread as it is now,
    right before a launch spawns it: the lead may have moved, or a swap changed the
    chair's harness, since the prompt was written. Any prompt carrying the tail (join,
    swap, relaunch) keeps its head. Returns the row with the prompt the spawn will use."""
    from .launcher import identity_tail, tail_start
    prompt = str(row.get("boot_prompt") or "")
    sid = str(row.get("session_id") or "")
    at = tail_start(prompt)
    if not sid or at is None:
        return row
    fresh = prompt[:at] + identity_tail(root, sid)
    if fresh != prompt:
        update_seat(root, sid, boot_prompt=fresh)
    return {**row, "boot_prompt": fresh}


def record_launcher(root: Path, session_id: str, launched_by: Any, why: str | None = None) -> dict[str, Any]:
    """Record who launched a chair joined without one (`join` then `launch`/`bring-up`),
    and recompose its one-shot boot prompt with the token its join or swap minted, so the
    prompt names the launcher too. A chair with no token on the feed keeps its prompt."""
    from .filelock import exclusive
    from .targeted_launch import _claim_path
    _require_seat(root, session_id)
    changes: dict[str, Any] = {"launched_by": launched_by, "launched_by_why": why if launched_by is None else None}
    # One lock per chair for every launcher record (launch, settle, adopt), so a launch and
    # an adopt never interleave a write.
    with exclusive(_claim_path(Path(root), session_id)):
        row = update_seat(root, session_id, **changes)
    return refresh_identity(root, row)


# A duplicate join names the two ways to a new chair (linted by printed_commands_test).
JOIN_NEW_CHAIR_TITLE = next_step("join", "--to", "<harness>", "--title", "<name>")
JOIN_NEW_CHAIR_ID = next_step("join", "--to", "<harness>", "--session-id", "<id>")


def join(
    root: Path,
    to: str,
    session_id: str | None = None,
    worktree: str | None = None,
    model: str | None = None,
    title: str | None = None,
    effort: str | None = None,
    author: str | None = None,
    where: str | None = None,
    calling_session: bool = False,
    launched_by: Any = _UNSET,
    launched_by_why: str | None = None,
) -> dict[str, Any]:
    """Add a new chair: seat + boot prompt + kind=join row (token minted).
    where is local (default) or cloud; write_seat refuses a cloud chair the
    harness cannot attach, before any token is minted.

    launched_by: the launcher's chair (a launch path resolved it), or None with
    launched_by_why when the launcher could not be proven. Left unset, nothing is
    recorded (a chair that joins itself, or a join that a later launch records)."""
    from .panes import identify
    from .harness_contract import canonical_harness_id
    # MCP callers and conductor-created crew chairs cannot borrow the
    # server/conductor's native identity. Only a local session joins itself.
    self_request = (calling_session and not session_id and not title and
                    (not worktree or Path(worktree).resolve() == Path.cwd().resolve()))
    me = identify(root, allow_unseated=True) if self_request else {}
    native = me.get("native_session") or {}
    skipped = []
    # A session may hold one chair on each of several threads: joining this one is not
    # refused because it sits on another.
    if me.get("ok") and me.get("chair") and me.get("via") in ("environment", "token"):
        existing = _require_seat(root, me["chair"])
        if canonical_harness_id(existing.get("to")) == canonical_harness_id(to):
            if existing.get("detached"):
                raise ValueError("detached; attach again")
            return {"ok": True, "already": True, "chair": me["chair"], "seat": existing, "next": "receive", "ownership_skipped": skipped}
    sid = (session_id or "").strip() or ((title or to) + "-" + (read_thread(root) or "thread"))
    if any(row.get("session_id") == sid for row in list_seats(root)):
        raise ValueError("refuse join: chair already exists: " + sid + "; pass --title <name> or --session-id <id> ("
                         + JOIN_NEW_CHAIR_TITLE.replace("<harness>", to) + ", or "
                         + JOIN_NEW_CHAIR_ID.replace("<harness>", to) + ")")
    token = _mint_token()
    write_seat(root, to, sid, worktree=worktree, model=model, title=title, effort=effort, where=where)
    if launched_by is not _UNSET:
        update_seat(root, sid, launched_by=launched_by,
                    **({"launched_by_why": launched_by_why} if launched_by is None else {}))
    seat_row = update_seat(root, sid, boot_prompt=_boot_prompt(root, sid, token, "thread.md"))
    hook(
        root, "join", "join " + sid + " (" + to + ")",
        instance_id=sid, author=author, to=sid,
        extra={"harness": to, "model": model, "token": token},
    )
    return {"ok": True, "seat": seat_row, "token": token, "next": "bring-up"}


def swap(
    root: Path,
    session_id: str,
    to: str,
    handoff: str,
    author: str,
    model: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    """Replace the occupant of an existing chair. Ordered, fail-closed:
    handoff must exist (FRESH file — newest_handoff selects by mtime), the
    swap row stamps BEFORE the re-seat, resume/vendor_session_id null on
    every swap, boot prompt carries token + handoff path. model and effort
    are validated for the INCOMING harness; unset, the old declaration
    survives only if that harness takes it."""
    hp = Path(handoff)
    if not hp.is_file():
        raise ValueError("refuse swap: handoff file missing: " + handoff)
    chair = _require_seat(root, session_id)
    # Every refusal happens here, before the row stamps: update_seat would
    # refuse these too, but by then a kind=swap row and a minted token were
    # already in the feed asserting a swap that never happened.
    validate_model(to, model)
    validate_effort(to, effort)
    validate_where(to, chair.get("where"))
    token = _mint_token()
    row = hook(
        root, "swap", "swap " + session_id + " -> " + to + ((" (" + model + ")") if model else ""),
        instance_id=session_id, author=author, to=session_id,
        extra={"swap_to": to, "handoff": str(hp), "token": token, "memory": "convoy-state"},
    )
    # Both tokens null on EVERY swap, same harness included: update_seat only
    # nulls vendor_session_id on a harness change, which left a grok->grok
    # swap resumable and made `launch` refuse it as "not fresh".
    # The new occupant has not been launched yet: the launch that spawns it records who
    # launched it, and until then its prompt says so (never the old occupant's launcher).
    changes: dict[str, Any] = {"to": to, "resume": None, "vendor_session_id": None,
                               "launched_by": None, "launched_by_why": SWAP_LAUNCHER_WHY}
    if model:
        changes["model"] = model
    if effort:
        changes["effort"] = effort
    update_seat(root, session_id, **changes)
    # The prompt is composed after the seat changed harness: the lead line reads the
    # thread as it is now (a lead codex chair swapped to claude no longer leads).
    seat_row = update_seat(root, session_id, boot_prompt=_boot_prompt(root, session_id, token, str(hp)))
    return {"ok": True, "seat": seat_row, "token": token, "row": row, "next": "bring-up"}


def _harness(seat_row: dict[str, Any]) -> str:
    return str(seat_row.get("to") or "").strip().lower()


def lead_state(root: Path) -> dict[str, Any]:
    """Who leads, and can anyone reach them.

    A seated chair is a seat on this thread that is not detached. `.convoy/lead`
    names a harness (or, older threads, a chair). status is "none" when it is
    unset. When the latest kind=lead row names a chair that matches the lead,
    that chair leads: "held" while it is seated, "dangling" once it detaches (no
    other chair of its harness inherits it). Otherwise (no stamped chair) the
    lead is "held" by its only matching seated chair, "held" with chair None
    when several match, and "dangling" when none does."""
    from .graph import _lead_chair
    from .layer import feed_path
    lead = read_lead(root)
    seats = list_seats(root)
    seated = [s for s in seats if not s.get("detached")]
    matching = [s for s in seated if lead and lead in (str(s.get("session_id")), _harness(s))]
    chair, status = None, "none"
    if lead is not None:
        rows = feed_since(root, "1970-01-01T00:00:00.000000Z") if feed_path(root).exists() else []
        by_sid = {s["session_id"]: s for s in seats}
        stamped = by_sid.get(_lead_chair(rows, set(by_sid)) or "")
        if stamped is not None and lead in (stamped["session_id"], _harness(stamped)):
            status = "dangling" if stamped.get("detached") else "held"
            chair = None if stamped.get("detached") else stamped["session_id"]
            matching = [stamped] if chair else []
        else:
            status = "held" if matching else "dangling"
            chair = matching[0]["session_id"] if len(matching) == 1 else None
    return {"lead": lead, "status": status, "chair": chair, "matching": matching, "seated": seated}


def take_lead(root: Path, session_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """An attached chair takes a lead that is unset or dangling: a kind=lead
    row from that chair to that chair, then the `.convoy/lead` harness."""
    target = _require_seat(root, session_id)
    harness = _harness(target)
    was = "none" if state["status"] == "none" else "dangling " + str(state["lead"])
    hook(root, "lead", "lead -> " + session_id + " (" + harness + "), was " + was,
         instance_id=session_id, author=session_id, to=session_id,
         extra={"lead": session_id, "harness": harness, "was": was})
    set_lead(root, harness)
    return {"chair": session_id, "harness": harness, "was": was, "line": "lead: taken (was " + was + ")"}


def lead_to_harness(root: Path, harness: str, author: str) -> dict[str, Any]:
    """The legacy `lead --to <harness>`: a pass to that harness's one seated chair,
    under every pass_lead rule (the author must hold the lead unless it is unset or
    dangling). No seated chair of it, or several, refuses."""
    name = str(harness or "").strip().lower()
    if not name:
        raise ValueError("refuse empty lead")
    chairs = sorted(s["session_id"] for s in lead_state(root)["seated"] if _harness(s) == name)
    if not chairs:
        raise ValueError("no chair of " + name + " on this thread")
    if len(chairs) > 1:
        raise ValueError(str(len(chairs)) + " chairs of " + name + " on this thread (" + ", ".join(chairs)
                         + "); pass to one with --to <chair>")
    return pass_lead(root, chairs[0], author=author)


def pass_lead(root: Path, session_id: str, author: str) -> dict[str, Any]:
    """Pass lead status to an IDENTIFIED neuron (a chair), neuron-authored.

    The author must be a seated chair and the current lead chair; while the
    lead is unset or dangling, any seated chair may take it. Stamps kind=lead
    (from=author, to=chair) so the graph can mark the lead and every neuron's
    place card can name it; then writes the legacy `.convoy/lead` harness file
    so bring-up keeps its meaning. The conductor asks for a lead change via
    stamp; it never authors one (hook refuses)."""
    sid = str(session_id or "").strip()
    who = str(author or "").strip()
    if not who:
        raise ValueError("refuse lead pass without an author")
    target = _require_seat(root, sid)
    state = lead_state(root)
    seated = {s["session_id"]: s for s in state["seated"]}
    if who not in seated:
        raise ValueError("refuse lead pass: " + who + " is not a seated chair on this thread")
    if sid not in seated:
        raise ValueError("refuse lead pass: " + sid + " is not a seated chair on this thread")
    # A lead change needs environment or token proof, which rests on the chair's recorded
    # native session id; a chair without one could never pass the lead on.
    if not (target.get("resume") or target.get("vendor_session_id")):
        raise ValueError("refuse lead pass: " + sid + " has no recorded session id, so it could never pass "
                         "the lead on; let it take a turn first")
    if state["status"] == "held":
        chair = state["chair"]
        holds = who == chair if chair else any(s["session_id"] == who for s in state["matching"])
        if not holds:
            raise ValueError("refuse lead pass: " + who + " is not the current lead ("
                             + str(chair or state["lead"]) + ")")
    harness = _harness(target)
    row = hook(
        root, "lead", "lead -> " + sid + " (" + harness + ")",
        instance_id=sid, author=who, to=sid,
        extra={"lead": sid, "harness": harness},
    )
    out = set_lead(root, harness)
    return {"ok": True, "lead_chair": sid, "conductor": sid, "lead": harness, "convoy_id": out.get("convoy_id"),
            "row": row}


def seated_ack(root: Path, session_id: str, token: str,
               incarnation: Any = None, *, verified_by: str | None = None,
               local_writer: bool = True) -> dict[str, Any]:
    """Proof-of-life: the new occupant echoes the token (kind=seated) and the
    one-shot boot prompt clears. The latest seated row per session_id names
    the chair's current occupant.

    `incarnation` is the life the occupant booted as, quoted from its boot
    prompt. The token cannot tell two lives of one chair apart - a relaunch
    re-arms the prompt with the token the chair's original join minted, so a
    previous body's ack cites exactly the right token. Optional: rows without
    it predate the field and crew reads them the way it always did."""
    _require_seat(root, session_id)
    if not (isinstance(token, str) and token.strip()):
        raise ValueError("refuse seated ack without token")
    extra: dict[str, Any] = {"token": token.strip()}
    if incarnation is not None:
        try:
            extra["incarnation"] = int(incarnation)
        except (TypeError, ValueError):
            raise ValueError("refuse seated ack with a non-integer incarnation: " + repr(incarnation))
    row = hook(
        root, "seated", "seated " + session_id,
        instance_id=session_id, author=session_id,
        extra=extra, verified_by=verified_by, local_writer=local_writer,
    )
    update_seat(root, session_id, boot_prompt=None)
    return {"ok": True, "row": row}
