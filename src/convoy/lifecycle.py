"""Seat lifecycle: join + swap + seated (ratified 2026-09-02, LIVE_SEAT_SPEC).

The seat is the chair; the neuron is the occupant. Chair identity is
session_id, full stop. swap replaces the occupant and NEVER reuses a vendor
resume token (Marco's ordering lock + the no-steal lock forbid two live
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

from .cmd import convoy_root_command
from .convoy import list_seats, read_thread, seat as write_seat, set_lead, update_seat
from .layer import hook


def _mint_token() -> str:
    return uuid.uuid4().hex


def _require_seat(root: Path, session_id: str) -> dict[str, Any]:
    for row in list_seats(root):
        if row.get("session_id") == session_id:
            return row
    raise ValueError("unknown seat: " + str(session_id))


def _boot_prompt(root: Path, session_id: str, token: str, handoff: str) -> str:
    # The seated-ack delivery mechanism (opus-2): an initial positional prompt
    # — NOT -p print mode; the session stays interactive. One line: read, ack,
    # continue. bring_up never packs, so the handoff pointer rides here.
    thread_path = Path(root) / "thread.md"
    handoff_path = Path(handoff)
    if not handoff_path.is_absolute():
        handoff_path = Path(root) / handoff_path
    return (
        "You are the new occupant of Convoy seat '" + session_id + "'. "
        "Read " + str(thread_path) + " and " + str(handoff_path) + ". Then run: "
        + convoy_root_command(root) + " seated --seat " + session_id +
        " --token " + token + " — then continue the seat's work."
    )


def join(
    root: Path,
    to: str,
    session_id: str | None = None,
    worktree: str | None = None,
    model: str | None = None,
    title: str | None = None,
    effort: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Add a new chair: seat + boot prompt + kind=join row (token minted)."""
    sid = (session_id or "").strip() or ((title or to) + "-" + (read_thread(root) or "thread"))
    if any(row.get("session_id") == sid for row in list_seats(root)):
        raise ValueError("refuse join: chair already exists: " + sid)
    token = _mint_token()
    write_seat(root, to, sid, worktree=worktree, model=model, title=title, effort=effort)
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
    every swap, boot prompt carries token + handoff path. effort is validated
    for the INCOMING harness (update_seat); unset, the old declaration
    survives only if that harness takes it."""
    hp = Path(handoff)
    if not hp.is_file():
        raise ValueError("refuse swap: handoff file missing: " + handoff)
    _require_seat(root, session_id)
    token = _mint_token()
    row = hook(
        root, "swap", "swap " + session_id + " -> " + to + ((" (" + model + ")") if model else ""),
        instance_id=session_id, author=author, to=session_id,
        extra={"swap_to": to, "handoff": str(hp), "token": token, "memory": "convoy-state"},
    )
    # Both tokens null on EVERY swap, same harness included: update_seat only
    # nulls vendor_session_id on a harness change, which left a grok->grok
    # swap resumable and made `launch` refuse it as "not fresh" (2026-09-03).
    changes: dict[str, Any] = {"to": to, "resume": None, "vendor_session_id": None,
                               "boot_prompt": _boot_prompt(root, session_id, token, str(hp))}
    if model:
        changes["model"] = model
    if effort:
        changes["effort"] = effort
    seat_row = update_seat(root, session_id, **changes)
    return {"ok": True, "seat": seat_row, "token": token, "row": row, "next": "bring-up"}


def pass_lead(root: Path, session_id: str, author: str) -> dict[str, Any]:
    """Pass lead status to an IDENTIFIED neuron (a chair), neuron-authored.

    Stamps kind=lead (from=author, to=chair) so the graph can mark the lead
    and every neuron's place card can name it; then writes the legacy
    `.convoy/lead` harness file so bring-up keeps its meaning. The conductor
    asks for a lead change via stamp; it never authors one (hook refuses)."""
    sid = str(session_id or "").strip()
    who = str(author or "").strip()
    if not who:
        raise ValueError("refuse lead pass without an author")
    target = _require_seat(root, sid)
    harness = str(target.get("to") or "").strip().lower()
    row = hook(
        root, "lead", "lead -> " + sid + " (" + harness + ")",
        instance_id=sid, author=who, to=sid,
        extra={"lead": sid, "harness": harness},
    )
    out = set_lead(root, harness)
    return {"ok": True, "lead_chair": sid, "lead": harness, "convoy_id": out.get("convoy_id"), "row": row}


def seated_ack(root: Path, session_id: str, token: str) -> dict[str, Any]:
    """Proof-of-life: the new occupant echoes the token (kind=seated) and the
    one-shot boot prompt clears. The latest seated row per session_id names
    the chair's current occupant."""
    _require_seat(root, session_id)
    if not (isinstance(token, str) and token.strip()):
        raise ValueError("refuse seated ack without token")
    row = hook(
        root, "seated", "seated " + session_id,
        instance_id=session_id, author=session_id,
        extra={"token": token.strip()},
    )
    update_seat(root, session_id, boot_prompt=None)
    return {"ok": True, "row": row}
