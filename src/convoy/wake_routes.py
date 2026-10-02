"""The wake directory: the route that wakes each chair, and whether it can be reached now.

`.convoy/wake_routes.jsonl` is append-only, and the last row per chair wins, like seats.jsonl. A row
names its route and the references that route needs (a channel server's name, a queue's thread, a
board subscription), never a secret. Its status is not stored: `reachability()` derives it from the
chair's pulses each time it is asked, so a row can never claim a liveness it no longer has.

Reachability reads the pulses by source (pulse.py). A channel route needs the channel's own pulse:
a session that is alive but whose channel is not loaded, or whose channel stopped, is degraded, not
live. Every other local route needs any fresh pulse. A board webhook is woken by the board, so it is
live until a fault says otherwise.

A fault is recorded, never inferred: `record_fault` names it (a queue too old or not running, a
harness out of credits, a parked board subscription, a wake dropped unread), with its reason, when it
was seen and by whom. Reachability reads it as down whatever the pulses say, except a dropped wake,
which degrades a route the pulses would call live. A later verified wake clears it, so a
re-enabled subscription or a topped-up account does not stay down forever. Unknown is never down: a
chair with no registered route answers None.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pulse import PULSE_SOURCES, pulse_age_seconds, read_pulse_by_source

ROUTES = ("channel", "codex-queue", "board-webhook", "waiter", "none")
# The references each route may carry. Anything else is refused, so a secret cannot ride in.
CONFIG_KEYS: dict[str, frozenset[str]] = {
    "channel": frozenset({"server"}),
    "codex-queue": frozenset({"thread_id"}),
    "board-webhook": frozenset({"subscription_id", "agent_id"}),
    "waiter": frozenset(),
    "none": frozenset(),
}
# Faults a wake attempt, or the board's reader, names on the route. Each is down until a verified wake.
FAULTS = (
    "codex-too-old",        # the harness has no native queue (unrecognized subcommand)
    "codex-not-running",    # the queue exited non-zero: nothing is there to take the turn
    "out-of-credits",       # turns end at once with a usage-limit error, though the harness pulses
    "subscription-parked",  # the board parked its webhook subscription after repeated failures
    "wake-dropped",         # a wake went unread twice; the route still pulses, so it is degraded, not down
)
# Faults that degrade a route that would otherwise read live. Every other fault reads as down.
DEGRADING_FAULTS = frozenset(("wake-dropped",))
# No pulse from any source for this long: the session or the device is gone.
REACH_FRESH_SEC = 90
# A config value is a reference: a short, plain string. Anything shaped like a credential is refused.
CONFIG_VALUE_MAX = 200
_SECRET_SHAPED = re.compile("(?i)(" + "|".join((
    r"\bbearer\s",                              # an Authorization value
    r"(?:^|[^A-Za-z0-9_-])sk-",                 # an sk- key after any separator, not a name like my-desk-sk-1 or my_sk-1
    r"\bsk_(?:live|test)_",                     # live and test secret keys of the sk_ family
    r"token=|secret=|password=|api[_-]?key=",   # a credential passed as a parameter
    r"\bgh[pos]_[A-Za-z0-9]",                   # GitHub personal, OAuth and server tokens
    r"\bgithub_pat_",                           # GitHub fine-grained tokens
    r"\bxox[abprs]-",                           # Slack tokens
    r"\beyJ[\w-]+\.eyJ",                        # a JWT: two base64url JSON segments
    r"(?-i:\b(?:AKIA|ASIA)[0-9A-Z]{16}\b)",     # an AWS access key id, long-term or temporary: upper case only
)) + ")")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def wake_routes_path(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wake_routes.jsonl"


def _append(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    path = wake_routes_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def register_route(root: Path | str, chair: str, route: str, *, registered_by: str,
                   neuron: str | None = None, device: str | None = None,
                   config: dict[str, Any] | None = None, verified_at: str | None = None,
                   ts: str | None = None) -> dict[str, Any]:
    """Append the chair's route, with no fault. Refuses an unknown route, a config key that route
    does not take, and an empty chair or author."""
    chair = str(chair or "").strip()
    if not chair:
        raise ValueError("refuse an empty chair")
    if route not in ROUTES:
        raise ValueError("refuse route " + repr(route) + "; one of " + ", ".join(ROUTES))
    by = str(registered_by or "").strip()
    if not by:
        raise ValueError("refuse a route with no registered_by")
    cfg = dict(config or {})
    extra = sorted(set(cfg) - CONFIG_KEYS[route])
    if extra:
        raise ValueError("refuse config " + ", ".join(extra) + " for route " + route
                         + "; it takes " + (", ".join(sorted(CONFIG_KEYS[route])) or "nothing"))
    for key, value in cfg.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("refuse config " + key + ": a reference is a non-empty string")
        if len(value) > CONFIG_VALUE_MAX:
            raise ValueError("refuse config " + key + ": longer than " + str(CONFIG_VALUE_MAX) + " characters")
        if _SECRET_SHAPED.search(value):
            raise ValueError("refuse config " + key + ": it looks like a secret; a route names references only")
    row: dict[str, Any] = {
        "chair": chair,
        "neuron": neuron,
        "device": device,
        "route": route,
        "config": cfg,
        "verified_at": verified_at,
        "fault": None,
        "registered_by": by,
        "ts": ts or _stamp(),
    }
    return _append(root, row)


def read_routes(root: Path | str) -> dict[str, dict[str, Any]]:
    """The last row per chair. A line that does not parse, names no chair or names a route no reader
    knows is skipped, and a store that cannot be read at all reads as no routes: one bad file must
    never break the neurons view."""
    path = wake_routes_path(root)
    routes: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return routes
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return routes
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(row, dict) and isinstance(row.get("chair"), str) and row["chair"].strip()
                and row.get("route") in ROUTES):
            routes[row["chair"]] = row
    return routes


def read_route(root: Path | str, chair: str) -> dict[str, Any] | None:
    return read_routes(root).get(str(chair))


def record_fault(root: Path | str, chair: str, name: str, *, reason: str, by: str,
                 seen_at: str | None = None) -> dict[str, Any]:
    """Record a named fault on the chair's route, as a new row that keeps the route. Refuses a
    fault that is not named, an empty reason or author, and a chair with no route."""
    if name not in FAULTS:
        raise ValueError("refuse fault " + repr(name) + "; one of " + ", ".join(FAULTS))
    why = str(reason or "").strip()
    who = str(by or "").strip()
    if not why or not who:
        raise ValueError("refuse a fault with no reason or no author")
    last = read_route(root, chair)
    if last is None:
        raise ValueError("refuse a fault for " + repr(chair) + ": no wake route registered")
    when = seen_at or _stamp()
    row = dict(last)
    row["fault"] = {"name": name, "reason": why, "seen_at": when, "by": who}
    row["ts"] = when
    return _append(root, row)


def mark_verified(root: Path | str, chair: str, *, ts: str | None = None) -> dict[str, Any]:
    """Record a successful wake receipt, as a new row that keeps the route and clears any fault:
    the wake that just landed is the evidence the fault is over."""
    last = read_route(root, chair)
    if last is None:
        raise ValueError("refuse to verify " + repr(chair) + ": no wake route registered")
    row = dict(last)
    row["verified_at"] = ts or _stamp()
    row["fault"] = None
    row["ts"] = row["verified_at"]
    return _append(root, row)


def reachability_detail(root: Path | str, chair: str, *, now: str | None = None) -> dict[str, Any]:
    """{reachable: live | degraded | down | None, reason, route}. None is unknown: no route."""
    route = read_route(root, chair)
    if route is None:
        return {"reachable": None, "reason": "no wake route registered", "route": None}
    kind = route.get("route")

    def answer(state: str, reason: str) -> dict[str, Any]:
        return {"reachable": state, "reason": reason, "route": kind}

    if kind == "none":
        return answer("down", "the route is none")
    fault = route.get("fault")
    named = None
    if isinstance(fault, dict) and fault.get("name"):
        named = (str(fault["name"]) + " (" + str(fault.get("reason") or "no reason") + ", seen "
                 + str(fault.get("seen_at") or "at an unknown time") + " by " + str(fault.get("by") or "unknown") + ")")
        if fault["name"] not in DEGRADING_FAULTS:
            return answer("down", named)
    found = _from_pulses(root, chair, kind, now)
    if named and found[0] != "down":
        return answer("degraded", named)
    return answer(*found)


def _from_pulses(root: Path | str, chair: str, kind: str, now: str | None) -> tuple[str, str]:
    """(state, reason) for a route with no fault that downs it."""
    if kind == "board-webhook":
        return ("live", "the board queues its wakes; no fault is recorded")
    ages = {s: pulse_age_seconds(read_pulse_by_source(root, chair, s), now=now) for s in PULSE_SOURCES}
    fresh = [s for s, a in ages.items() if a is not None and a <= REACH_FRESH_SEC]
    if not fresh:
        return ("down", "no pulse from any source within " + str(REACH_FRESH_SEC) + " s")
    if kind == "channel":
        if "channel" in fresh:
            return ("live", "the channel pulsed within " + str(REACH_FRESH_SEC) + " s")
        if ages.get("channel") is None:
            return ("degraded", "channel not loaded: the session pulses from " + ", ".join(fresh)
                          + " but the channel never has")
        return ("degraded", "channel stopped: its pulse is stale beside a live session ("
                      + ", ".join(fresh) + ")")
    return ("live", "a pulse from " + ", ".join(fresh) + " within " + str(REACH_FRESH_SEC) + " s")


def reachability(root: Path | str, chair: str, *, now: str | None = None) -> str | None:
    """live | degraded | down, or None when the chair has no registered wake route."""
    return reachability_detail(root, chair, now=now)["reachable"]
