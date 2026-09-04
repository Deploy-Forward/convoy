"""crew: N neurons -> N chairs -> ONE window -> they all connect, observed.

The wizard's old sequence (join + launch for chair 1, `seat` for chairs 2..N,
bring_up) left chairs 2..N with no boot prompt - `seat` never writes one - so
those panes came up with a bare harness argv and nobody told them to connect
(reader 4, 2026-09-04). crew joins EVERY chair (boot prompt + token), mints
one worktree per local chair from the checkout, and launches once through
bring_up: one wt window, N panes, never launch_seat per chair.

Launched is not connected. await_seated reads kind=seated rows back and calls
a chair connected only when its ack cites the token this mint issued; the
time waited is measured on an injectable clock so the suite never sleeps.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .bringup import Runner, bring_up
from .convoy import list_seats, read_id, read_thread
from .harness_contract import canonical_harness_id, harness_entries, validate_effort, validate_model, validate_where
from .inbox import connect_mode
from .layer import feed_since
from .lifecycle import join
from .repo import Runner as GitRunner, mint_worktrees

EPOCH = "1970-01-01T00:00:00.000000Z"
STATES = ("connected", "pending", "stale")


def _plan(root: Path, seats: list[dict[str, Any]], bound: str | None) -> list[dict[str, Any]]:
    """Validate every seat before anything is written. A refusal here names
    the field in the harness's own words (validate_* do that) and leaves the
    thread untouched."""
    if not isinstance(seats, list) or not seats:
        raise ValueError("crew requires seats: a non-empty list of {harness, model?, effort?, where?, title?}")
    known = {row["id"] for row in harness_entries()}
    existing = {str(s.get("session_id") or "") for s in list_seats(root)}
    plan: list[dict[str, Any]] = []
    names: set[str] = set()
    for i, raw in enumerate(seats):
        spec = raw if isinstance(raw, dict) else {}
        harness = canonical_harness_id(spec.get("harness") or spec.get("to"))
        if harness not in known:
            raise ValueError("refuse seat " + str(i + 1) + ": unknown harness " + repr(spec.get("harness")) +
                             "; choices.harnesses lists " + ", ".join(sorted(known)))
        where = validate_where(harness, spec.get("where"))
        model = validate_model(harness, spec.get("model"))
        effort = validate_effort(harness, spec.get("effort"))
        title = str(spec.get("title") or "").strip()
        name = title or (harness + "-" + str(i + 1))
        if name in names:
            raise ValueError("refuse seat " + str(i + 1) + ": name " + repr(name) + " used twice in this crew")
        names.add(name)
        sid = name + "-" + (bound or "thread")
        if sid in existing:
            raise ValueError("refuse seat " + str(i + 1) + ": chair already exists: " + sid)
        plan.append({"harness": harness, "where": where, "model": model, "effort": effort,
                     "title": name, "session_id": sid})
    return plan


def crew(
    root: Path,
    seats: list[dict[str, Any]],
    *,
    thread: str | None = None,
    checkout: Path | str | None = None,
    runner: Runner | None = None,
    mint_runner: GitRunner | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Validate -> mint -> join each -> bring_up once. runner=None joins the
    chairs and shows the argv without spawning; live_runner pops the window.
    checkout defaults to the root (onboard binds the thread there)."""
    root = Path(root)
    bound = read_thread(root)
    card: dict[str, Any] = {"ok": False, "convoy_id": read_id(root), "thread": bound, "seats": [], "launched": runner is not None}
    if card["convoy_id"] is None:
        card["error"] = "crew requires a bound thread root (onboard, or init + bind)"
        return card
    if thread is not None and bound != thread:
        card["error"] = "thread mismatch: root is bound to " + repr(bound) + ", not " + repr(thread)
        return card
    try:
        plan = _plan(root, seats, bound)
    except ValueError as e:
        card["error"] = str(e)
        return card
    base = Path(checkout) if checkout else root
    card["checkout"] = str(base)
    local = [p for p in plan if p["where"] == "local"]
    minted: dict[str, str] = {}
    if local:
        mint = mint_worktrees(base, len(local), names=[p["title"] for p in local], runner=mint_runner)
        card["mint"] = mint
        if not mint.get("ok"):
            card["error"] = "mint refused: " + str(mint.get("error"))
            return card
        minted = {row["name"]: row["path"] for row in mint["worktrees"]}
    else:
        card["mint"] = {"ok": True, "checkout": str(base), "worktrees": []}
    for p in plan:
        try:
            joined = join(root, p["harness"], session_id=p["session_id"], worktree=minted.get(p["title"]),
                          model=p["model"], title=p["title"], effort=p["effort"], author=author, where=p["where"])
        except ValueError as e:
            card["error"] = "join refused for " + p["session_id"] + ": " + str(e) + " (" + str(len(card["seats"])) + " chairs already joined)"
            return card
        card["seats"].append({**joined["seat"], "token": joined["token"], "connect_mode": connect_mode(p["harness"])})
    sids = [s["session_id"] for s in card["seats"]]
    up = bring_up(root, thread=bound, runner=runner, session_ids=sids)
    card["windows"] = up.get("windows") or []
    card["cloud"] = up.get("cloud") or []
    if up.get("error"):
        card["error"] = str(up["error"])
    # A snapshot, not a wait: right after launch every chair is pending, and
    # the card says so instead of implying the panes connected.
    card["seated"] = await_seated(root, sids, timeout=0)
    card["ok"] = bool(up.get("ok"))
    card["next"] = "await_seated"
    return card


def _seated_states(root: Path, session_ids: list[str]) -> list[dict[str, Any]]:
    seats = {str(s.get("session_id") or ""): s for s in list_seats(root)}
    unknown = [sid for sid in session_ids if sid not in seats]
    if unknown:
        raise ValueError("unknown seat: " + ", ".join(unknown))
    rows = feed_since(root, EPOCH)
    out: list[dict[str, Any]] = []
    for sid in session_ids:
        mint = None
        seated = None
        for r in rows:
            if r.get("instance_id") != sid:
                continue
            if r.get("kind") in ("join", "swap"):
                mint = r
            elif r.get("kind") == "seated":
                seated = r
        # connected: the ack cites the token THIS mint issued. seated_ack
        # itself accepts any non-empty token (lifecycle.py), so the comparison
        # is made here, where the claim is read back, not trusted.
        if seated is None:
            state = "pending"
        elif mint is not None and seated.get("token") == mint.get("token"):
            state = "connected"
        else:
            state = "stale"
        out.append({
            "session_id": sid,
            "to": seats[sid].get("to"),
            "where": seats[sid].get("where"),
            "state": state,
            "connect_mode": connect_mode(seats[sid].get("to")),
            "minted_at": mint.get("ts") if mint else None,
            "seated_at": seated.get("ts") if seated else None,
        })
    return out


def await_seated(
    root: Path,
    session_ids: list[str],
    *,
    timeout: float = 120.0,
    interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Poll kind=seated rows until every chair is connected or timeout passes.
    Returns per chair connected | pending | stale and the seconds waited on
    `clock`. timeout=0 is one pass (a snapshot). Never a token on the card."""
    sids = [str(s) for s in session_ids]
    budget = max(0.0, float(timeout))
    step = max(0.0, float(interval))
    start = clock()
    while True:
        chairs = _seated_states(Path(root), sids)
        waited = max(0.0, clock() - start)
        if all(c["state"] == "connected" for c in chairs) or waited >= budget:
            break
        sleep(min(step, budget - waited) if step else budget - waited)
    by_state = {state: [c["session_id"] for c in chairs if c["state"] == state] for state in STATES}
    return {
        "ok": bool(chairs) and not by_state["pending"] and not by_state["stale"],
        "waited_s": round(waited, 3),
        "timeout_s": budget,
        "chairs": chairs,
        **by_state,
    }
