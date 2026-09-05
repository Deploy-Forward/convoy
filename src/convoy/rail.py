"""The thread rail: the strip under the panes.

Marco's happy-path storyboard (2026-09-04, frame 1c) ends with one line under
the terminal: feed events, seats connected, usage per harness, last stamp.
That line is the proof the thread is shared memory - every agent taps it and
every agent reads the same thing. This module builds it from the thread on
disk and nothing else, so a neuron in its worktree, the lead in the checkout,
and a chat over MCP all see one rail.

Honesty: usage remaining is the vendor's number or JSON null (unknown), never
0; connected comes from the seated acks (crew._seated_states), never from a
launch having happened; no token is on the card.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .convoy import list_seats, read_id, read_lead, read_thread
from .crew import _seated_states
from .inbox import resolve_root, seats_for_worktree
from .index import list_threads
from .layer import feed_since, parse_since
from .provenance import rail_provenance
from .bringup import is_conductor
from .usage import probe, surface

ProbeFn = Callable[[str], dict[str, Any]]


def root_for(start: Path | str) -> Path | None:
    """The thread root a rail should read from `start`: the root itself, a
    worktree pointer or a parent (inbox.resolve_root), else the machine's
    thread index: the one present thread that seats a chair in this
    worktree. Two threads seating it is ambiguous, so None, never a pick."""
    here = Path(start)
    found = resolve_root(here)
    if found is not None:
        return found
    hits: list[Path] = []
    for row in list_threads():
        if not row.get("present"):
            continue
        root = Path(str(row["root"]))
        if seats_for_worktree(root, here):
            hits.append(root)
    return hits[0] if len(hits) == 1 else None


def build_rail(root: Path | str, *, since: str = "10m", probe_fn: ProbeFn | None = None) -> dict[str, Any]:
    root = Path(root)
    cid = read_id(root)
    card: dict[str, Any] = {
        "ok": False,
        "convoy_id": cid,
        "thread": read_thread(root),
        "lead": read_lead(root),
        "root": str(root),
    }
    if cid is None:
        card["error"] = "no thread at " + str(root) + ": onboard (or init + bind) first"
        return card
    since_iso = parse_since(since)
    events = feed_since(root, since_iso)
    card["feed"] = {"since": since, "since_iso": since_iso, "events": len(events)}

    chairs = [s for s in list_seats(root) if not is_conductor(s.get("to"))]
    sids = [str(s.get("session_id")) for s in chairs]
    states = _seated_states(root, sids) if sids else []
    counts = {"total": len(states), "connected": 0, "pending": 0, "stale": 0}
    for st in states:
        counts[st["state"]] = counts.get(st["state"], 0) + 1
    card["seats"] = counts
    card["chairs"] = [{"session_id": st["session_id"], "harness": st["to"], "where": st["where"],
                       "state": st["state"]} for st in states]

    fn = probe_fn or probe
    usage: dict[str, Any] = {}
    for harness in sorted({str(s.get("to")) for s in chairs if s.get("to")}):
        usage[harness] = surface(harness, fn(harness))
    card["usage"] = usage

    card["provenance"] = rail_provenance(root, since=since)

    last = None
    for row in reversed(feed_since(root, "1970-01-01T00:00:00.000000Z")):
        if row.get("kind") == "conductor":
            last = {"ts": row.get("ts"), "summary": row.get("summary"), "agent": row.get("agent"),
                    "model": row.get("model"), "effort": row.get("effort")}
            break
    card["last_stamp"] = last
    card["ok"] = True
    return card
