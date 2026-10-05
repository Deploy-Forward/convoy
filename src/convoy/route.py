"""report and reply: routing in code, not in a prompt.

report  the caller's proven chair sends its result to the chair that launched it
        (`launched_by`); when that is null or the chair is gone (detached, or no
        longer a seat), to the lead. The lead with no launcher refuses, and so does a
        chair with neither: ok false with why, never a guess. The send itself is the
        ordinary send path (fake runner: a feed row, plus the inbox for a live chair),
        so wake and delivery semantics are those of `send`.
reply   the caller's proven chair answers one send by its token: a note addressed to
        that send's proven sender, citing the token, which is the receipt the sender's
        `replies` counts as delivered. An unknown token refuses, and so does a caller
        that was not that send's recipient.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .convoy import list_seats

# The identity proof report and reply accept: the caller's own native session.
from .conductor import RECEIPT_PROOF as VERIFIED  # one bar for reply and for a counted receipt


def _caller(me: dict[str, Any] | None) -> tuple[str | None, str | None]:
    me = me or {}
    if me.get("ok") and me.get("chair"):
        if me.get("via") in VERIFIED:
            return str(me["chair"]), me.get("via")
        # A cwd or path match is not authorship: its rows would be claimed, a report
        # would carry no sender to answer, and a reply would be no receipt.
        return None, ("your chair " + str(me["chair"]) + " is matched only by " + str(me.get("via")) +
                      "; report and reply need environment, token or pane-host proof of your session")
    return None, "cannot prove your chair on this thread: " + str(me.get("ask") or "no chair matches this body")


def report(root: Path, text: str, *, me: dict[str, Any] | None, runner=None) -> dict[str, Any]:
    from .lifecycle import lead_state
    from .synapse import fake_runner, send_one
    root = Path(root)
    chair, why = _caller(me)
    refused = {"ok": False, "routed_to": None, "route": None, "delivered": False}
    if chair is None:
        return {**refused, "why": why}
    seats = {s.get("session_id"): s for s in list_seats(root)}
    launcher = (seats.get(chair) or {}).get("launched_by")
    if launcher and launcher != chair and launcher in seats and not seats[launcher].get("detached"):
        target, route, note = launcher, "launcher", None
    else:
        if not launcher:
            note = "no launcher recorded for " + chair
        elif launcher == chair:
            note = "you launched yourself"
        elif launcher not in seats:
            note = "the launcher " + str(launcher) + " is no longer a seat on this thread"
        else:
            note = "the launcher " + str(launcher) + " is detached"
        lead = lead_state(root)["chair"]
        if lead == chair:
            return {**refused, "why": note + ", and you are the lead: there is no one to report to"}
        if not lead:
            return {**refused, "why": note + ", and no lead on this thread"}
        target, route = lead, "lead"
    card = send_one(root, target, text, runner=runner or fake_runner, allow_interactive_resume=True,
                    sender={"chair": chair, "verified_by": via_of(me)})
    card["routed_to"] = target
    card["route"] = route
    if note:
        card["route_why"] = note
    return card


def via_of(me: dict[str, Any] | None) -> str | None:
    return (me or {}).get("via")


def reply(root: Path, token: str, text: str, *, me: dict[str, Any] | None) -> dict[str, Any]:
    from .layer import feed_path, feed_since, hook
    from .wake_dispatch import proven_author, receipt_address
    root = Path(root)
    chair, why = _caller(me)
    if chair is None:
        return {"ok": False, "why": why}
    tok = str(token or "").strip()
    rows = feed_since(root, "1970-01-01T00:00:00.000000Z") if feed_path(root).exists() else []
    sends = [r for r in rows if r.get("kind") == "synapse" and tok and r.get("token") == tok]
    if not sends:
        return {"ok": False, "why": "unknown token: no send on this thread carries " + repr(tok)}
    send = sends[-1]
    if send.get("instance_id") != chair:
        return {"ok": False, "why": "you were not this send's recipient (it went to " + str(send.get("instance_id")) + ")"}
    sender = proven_author(send)
    if not sender or sender == chair:
        return {"ok": False, "why": "the send has no proven sender to reply to"}
    summary = "token=" + tok + " " + str(text or "")
    try:
        to = receipt_address(root, summary, chair, sender)
        row = hook(root, "note", summary, instance_id=chair, to=to, verified_by=via_of(me))
    except ValueError as exc:
        return {"ok": False, "why": str(exc)}
    return {"ok": True, "to": to, "token": tok, "row": row}
