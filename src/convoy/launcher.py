"""Launch identity: who launched a neuron, and who leads the thread it joins.

Every path that seats and launches a neuron (add, crew, join --launch, launch,
bring-up) resolves the launching session with the existing identity proof:

  seated     identify names a chair on this thread by environment or token proof:
             the new seat records `launched_by: <that chair>`.
  unseated   no chair yet, but a native session id proves the session (environment
             or token): it is attached first, exactly as `convoy attach` does (so it
             takes the lead when the lead is none or dangling), then recorded.
  unproven   anything weaker (a cwd or worktree path match, a script with no harness,
             an unreadable process table): `launched_by: null` with
             `launched_by_why`, a warning on the card, no attach, no lead change.

Never a guess. The boot prompt and `whoami` read the recorded fields back.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .convoy import list_seats, read_id

# One attempt at the process table on a launch path, this many seconds.
LAUNCHER_PROBE_TIMEOUT_S = 30
STRONG = ("environment", "token")
# The test guard sets this to [] for a whole run: a CLI launch under test then reads no
# real process table (whose argv can prove the pane's own session by token). A test that
# needs a launcher opts in with panes._TEST_PROCS or procs=. None in production.
TEST_DEFAULT_PROCS: list[dict[str, Any]] | None = None


def _unproven(why: str) -> dict[str, Any]:
    return {"kind": "unproven", "chair": None, "via": None, "why": why}


def resolve_launcher(root: Path, *, procs: list[dict[str, Any]] | None = None, env: Mapping[str, str] | None = None,
                     cwd: str | None = None, pid: int | None = None) -> dict[str, Any]:
    """Which session is launching? Read-only: {kind: seated|unseated|unproven, chair, via, why}."""
    from . import panes
    root = Path(root)
    if procs is None:
        if panes._TEST_PROCS is not None:
            procs = panes._TEST_PROCS
        elif TEST_DEFAULT_PROCS is not None:
            procs = list(TEST_DEFAULT_PROCS)
        else:
            procs, error = panes._safe_enumerate(attempts=1, timeout=LAUNCHER_PROBE_TIMEOUT_S)
            if error:
                return _unproven("process table unreadable (" + error + "), so the launcher cannot be proven")
    env = os.environ if env is None else env
    here = str(cwd or os.getcwd())
    try:
        me = panes.identify(root, pid=pid, procs=procs, cwd=here, env=env)
    except (OSError, ValueError) as exc:
        return _unproven("identity failed: " + str(exc))
    if me.get("ok") and me.get("chair"):
        via = me.get("via")
        if via not in STRONG:
            return _unproven("only a " + str(via) + " match names chair " + str(me["chair"]) +
                             "; a launcher needs environment or token proof")
        row = next((s for s in list_seats(root) if s.get("session_id") == me["chair"]), {})
        if not row.get("detached"):
            return {"kind": "seated", "chair": me["chair"], "via": via, "why": None}
    elif me.get("via") == "conflict":
        return _unproven("identity conflict: " + str(me.get("ask") or "sources disagree"))
    try:
        un = panes.identify(root, pid=pid, procs=procs, cwd=here, env=env, allow_unseated=True)
    except (OSError, ValueError) as exc:
        return _unproven("identity failed: " + str(exc))
    native = un.get("native_session") or {}
    if un.get("ok") and native.get("id") and native.get("via") in STRONG:
        return {"kind": "unseated", "chair": un.get("chair"), "via": native["via"], "why": None,
                "me": un, "cwd": here}
    return _unproven("no chair on this thread matches the launching session and no native session id proves it"
                     " (a script, or a cwd match alone, is not proof)")


def seat_launcher(root: Path, resolved: dict[str, Any]) -> dict[str, Any]:
    """Act on a resolved launcher: attach an unseated one. Returns the card's `launcher`
    block, whose launched_by / launched_by_why the new seat records."""
    from .activity import neuron_id
    cid = read_id(root)
    kind = (resolved or {}).get("kind")
    out: dict[str, Any] = {"kind": kind, "chair": None, "neuron_id": None, "via": resolved.get("via"),
                           "attached": False, "lead_taken": False, "launched_by": None,
                           "launched_by_why": None, "warning": None}
    if kind == "seated":
        out.update(chair=resolved["chair"], neuron_id=neuron_id(cid, resolved["chair"]),
                   launched_by=resolved["chair"], line="launcher " + resolved["chair"] + " is seated on this thread")
        return out
    if kind == "unseated":
        from .sessions import attach_proven
        card = attach_proven(Path(root), Path(resolved.get("cwd") or os.getcwd()), resolved.get("me") or {})
        if card.get("ok") and card.get("chair"):
            chair = card["chair"]
            taken = card.get("lead_taken")
            out.update(chair=chair, neuron_id=neuron_id(cid, chair), launched_by=chair, attached=True,
                       lead_taken=bool(taken), lead_was=(taken or {}).get("was"),
                       line=("attached the launcher " + chair + " to this thread; " +
                             ("it took the lead (was " + str(taken.get("was")) + ")" if taken
                              else "the lead stays " + str(_lead_chair(root) or "unchanged"))))
            return out
        why = "the launcher could not attach: " + str(card.get("error") or "attach refused")
    else:
        why = str((resolved or {}).get("why") or "the launcher was not resolved")
    out.update(launched_by_why=why, warning="launcher unknown: " + why + "; launched_by is null")
    return out


def launch_fields(info: dict[str, Any] | None) -> dict[str, Any]:
    """The join kwargs a seat_launcher block records; {} when no launcher was resolved."""
    if not info:
        return {}
    return {"launched_by": info.get("launched_by"), "launched_by_why": info.get("launched_by_why")}


def public_block(info: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in info.items() if k != "warning"}


def _lead_chair(root: Path) -> str | None:
    from .lifecycle import lead_state
    return lead_state(root)["chair"]


def _lead_view(root: Path) -> tuple[dict[str, Any], str | None]:
    """(lead_state, the lead chair a kind=lead row names), the chair None when the
    state's chair only matched the lead file's harness. A harness match is never
    reported as a chair that leads: a new codex chair on a thread whose lead file says
    codex was told it leads."""
    from .graph import _lead_chair as stamped_chair
    from .layer import feed_path, feed_since
    from .lifecycle import lead_state
    state = lead_state(root)
    chair = state["chair"]
    if not chair:
        return state, None
    rows = feed_since(root, "1970-01-01T00:00:00.000000Z") if feed_path(root).exists() else []
    stamped = stamped_chair(rows, {s["session_id"] for s in list_seats(root)})
    return state, (chair if stamped == chair else None)


def _lead_none_reason(state: dict[str, Any]) -> str:
    if state["status"] == "held" and state["chair"]:
        return ("the lead file names " + str(state["lead"]) + ", and no lead row names a chair; "
                "a seated chair passes it with `lead --to <chair>`")
    if state["status"] == "none":
        return "no chair has taken the lead on this thread"
    if state["status"] == "dangling":
        return "the lead " + str(state["lead"]) + " has no seated chair"
    names = ", ".join(sorted(str(s.get("session_id")) for s in state.get("matching") or []))
    return "the lead " + str(state["lead"]) + " is held by several chairs (" + names + ")"


def lead_ref(root: Path) -> dict[str, Any] | None:
    """{chair, neuron_id} of the lead chair, or None."""
    from .activity import neuron_id
    chair = _lead_view(root)[1]
    return {"chair": chair, "neuron_id": neuron_id(read_id(root), chair)} if chair else None


def launched_by_ref(root: Path, session_id: str) -> dict[str, Any] | None:
    """{chair, neuron_id} of the chair that launched this one, or None (unknown or never recorded)."""
    from .activity import neuron_id
    row = next((s for s in list_seats(root) if s.get("session_id") == session_id), {})
    chair = row.get("launched_by")
    return {"chair": chair, "neuron_id": neuron_id(read_id(root), chair)} if chair else None


def whoami_fields(root: Path, session_id: str) -> dict[str, Any]:
    return {"lead": lead_ref(root), "launched_by": launched_by_ref(root, session_id)}


def identity_sentence(root: Path, session_id: str) -> str:
    """The boot prompt's who-is-who: the lead and the launcher, information only."""
    from .activity import neuron_id
    cid = read_id(root)
    seats = {s.get("session_id"): s for s in list_seats(root)}
    me = seats.get(session_id) or {}
    state, lead = _lead_view(root)

    def who(chair: str, harness: bool = True) -> str:
        bits = ["neuron " + str(neuron_id(cid, chair))]
        if harness and (seats.get(chair) or {}).get("to"):
            bits.append(str(seats[chair]["to"]))
        return chair + " (" + ", ".join(bits) + ")"

    if lead == session_id:
        lead_text = "Lead: you (neuron " + str(neuron_id(cid, session_id)) + ")."
    elif lead:
        lead_text = "Lead: " + who(lead) + "."
    else:
        lead_text = "Lead: none (" + _lead_none_reason(state) + ")."
    if "launched_by" not in me:
        return lead_text
    launcher = me.get("launched_by")
    if launcher is None:
        return lead_text + " Launched by: unknown (" + str(me.get("launched_by_why") or "not proven") + ")."
    if launcher == lead and lead != session_id:
        return "Lead and launcher: " + who(lead) + "."
    return lead_text + " Launched by: " + who(launcher, harness=False) + "."


def identity_tail(root: Path, session_id: str) -> str:
    """The end of every boot prompt: who leads and who launched this chair, then the
    two commands that route in code. Composed again right before a spawn
    (lifecycle.refresh_identity), so it is the thread as it is at launch."""
    from .cmd import convoy_root_command
    cmd = convoy_root_command(root)
    return (identity_sentence(root, session_id) +
            " Report results with: " + cmd + " report \"...\"."
            " Answer a message with: " + cmd + " reply <token> \"...\".")


_TAIL_HEADS = (" Lead: ", " Lead and launcher: ")


def tail_start(prompt: str) -> int | None:
    """Where the identity tail begins in a prompt (after the space), or None."""
    hits = [prompt.find(h) for h in _TAIL_HEADS if h in prompt]
    return min(hits) + 1 if hits else None
