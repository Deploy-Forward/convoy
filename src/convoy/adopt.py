"""`convoy adopt`: make the proven caller an existing neuron's launcher.

A neuron needs a launcher so its results have somewhere to go (`convoy report` routes to it).
Every launch records one; a neuron from before that, or one whose launcher has gone, is adopted:

- the caller must be proven (environment, token or pane-host); a caller not seated on the
  thread is attached first, as a launch does (it takes the lead only if none or dangling);
- launched_by is set to the caller when it is missing, null, or names a chair that is gone or
  detached. A live recorded launcher is replaced only by the thread's lead;
- the neuron is then sent one message from the caller naming its new launcher and the commands
  to report and to answer, so the return path exists at once.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .convoy import list_seats, read_id


def _caller(root: Path, me: dict[str, Any] | None, launcher: dict[str, Any] | None) -> dict[str, Any]:
    """{chair, via, attached, lead_taken} for the proven caller, or {error}."""
    from .conductor import RECEIPT_PROOF
    from .launcher import UNPROVEN_NEXT, refusal, seat_launcher
    me = me or {}
    seats = {s.get("session_id"): s for s in list_seats(root)}
    if me.get("ok") and me.get("chair") and me.get("via") in RECEIPT_PROOF:
        if not (seats.get(me["chair"]) or {}).get("detached"):
            return {"chair": me["chair"], "via": me["via"], "attached": False, "lead_taken": False}
    refused = refusal(launcher) if launcher is not None else {
        "error": "cannot prove who is adopting", "next": UNPROVEN_NEXT}
    if refused:
        return {"error": "cannot prove who is adopting", "why": refused.get("why"), "next": refused["next"]}
    try:
        info = seat_launcher(root, launcher)
    except ValueError as exc:
        return {"error": str(exc), "next": UNPROVEN_NEXT}
    return {"chair": info["chair"], "via": info.get("via"), "attached": bool(info.get("attached")),
            "lead_taken": bool(info.get("lead_taken"))}


def _current_launcher(root: Path, session_id: str) -> Any:
    """The seat's launched_by as it is on disk now (None when missing)."""
    row = next((s for s in list_seats(root) if s.get("session_id") == session_id), {})
    return row.get("launched_by")


def _before_write(root: Path, session_id: str) -> None:
    """The moment between deciding and writing: nothing happens here. Another adopt or
    launch may land in this window, which is why the write re-reads under the lock."""


def adopt(root: Path, session_id: str, *, me: dict[str, Any] | None,
          launcher: dict[str, Any] | None = None, runner=None) -> dict[str, Any]:
    from .activity import neuron_id
    from .cmd import convoy_root_command
    from .filelock import exclusive
    from .launcher import launcher_of
    from .lifecycle import lead_state, record_launcher
    from .synapse import fake_runner, send_one
    from .targeted_launch import _claim_path
    root = Path(root)
    sid = str(session_id or "").strip()
    seats = {s.get("session_id"): s for s in list_seats(root)}
    target = seats.get(sid)
    if target is None:
        return {"ok": False, "error": "unknown seat: " + sid}
    if str(target.get("boot_prompt") or "").strip():
        # Not launched yet: the launch that spawns it records who launched it.
        return {"ok": False, "session_id": sid,
                "error": "this chair has not launched yet; its launch will record its launcher"}
    if target.get("detached"):
        # The message could not reach it: refuse before anything is written.
        return {"ok": False, "session_id": sid,
                "error": "chair " + sid + " is detached; it must attach again before it can be adopted"}
    # The lead override counts only a lead held before this adopt began: an outsider
    # attached by this call may take a dangling lead, but that never lets it replace a
    # live launcher in the same call.
    state = lead_state(root)
    lead_before = state["chair"] if state["status"] == "held" else None
    caller = _caller(root, me, launcher)
    if caller.get("error"):
        return {"ok": False, "session_id": sid, **caller}
    chair = caller["chair"]
    if chair == sid:
        return {"ok": False, "session_id": sid, "error": "a chair cannot adopt itself"}
    seats = {s.get("session_id"): s for s in list_seats(root)}   # the attach may have added the caller
    previous = seats[sid].get("launched_by")
    kind, name = launcher_of(previous)
    # A conductor launcher (an MCP launch) is live: its mail is its replies cursor.
    live = kind == "conductor" or (name and name in seats and not seats[name].get("detached") and name != chair)
    if live and lead_before != chair:
        return {"ok": False, "session_id": sid, "previous_launched_by": previous,
                "error": ("chair " + sid + " already has a live launcher, " +
                          (("conductor " + str(name)) if kind == "conductor" else str(name)) +
                          "; only the thread's lead may replace it")}
    _before_write(root, sid)
    # Compare and set, under the lock every launcher record takes: a launch or another
    # adopt that recorded a launcher since the decision wins, and this one refuses.
    with exclusive(_claim_path(root, sid)):
        if _current_launcher(root, sid) != previous:
            return {"ok": False, "session_id": sid, "previous_launched_by": previous,
                    "error": "launcher changed while adopting; run adopt again"}
        record_launcher(root, sid, chair)
    cid = read_id(root)
    cmd = convoy_root_command(root)
    message = ("Your launcher is now " + chair + " (neuron " + str(neuron_id(cid, chair)) + "). "
               "Report with: " + cmd + " report \"...\"; answer messages with convoy reply <token>.")
    sent = send_one(root, sid, message, runner=runner or fake_runner, allow_interactive_resume=True,
                    sender={"chair": chair, "verified_by": caller.get("via")})
    if not sent.get("ok"):
        # The return path was not told: put the previous launcher back, under the same lock.
        with exclusive(_claim_path(root, sid)):
            if _current_launcher(root, sid) == chair:
                record_launcher(root, sid, previous)
        return {"ok": False, "session_id": sid, "previous_launched_by": previous,
                "error": "the message to " + sid + " could not be sent: " + str(sent.get("error") or sent.get("delivery")),
                "delivery": sent.get("delivery")}
    return {"ok": True, "session_id": sid, "neuron_id": neuron_id(cid, sid),
            "previous_launched_by": previous, "launched_by": chair,
            "launcher_neuron_id": neuron_id(cid, chair), "attached": caller["attached"],
            "lead_taken": caller["lead_taken"], "message": message, "token": sent.get("token"),
            "delivery": sent.get("delivery"), "delivered": False}
