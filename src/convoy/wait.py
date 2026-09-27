"""The waiter: one slim process per chair, and nothing else in it.

A waiter started as `convoy inbox --wait` is `python -m convoy.cli`, which
imports crew, bringup, panes, widget, graph and mcp_http before it can poll a
directory. Under memory pressure the OS kills such a process silently, and
the chair goes deaf while the feed still looks healthy. Nothing on disk said a waiter had ever existed, so nothing
could say one was gone.

This module polls a directory. It imports inbox, layer and pulse, and that
import list is the guarantee - wait_test asserts that importing it never
pulls a heavy module into the process.

Two files speak for it:

  - the chair's pulse, touched every PULSE_EVERY_S with pulse_source 'wait';
  - .convoy/wait/<digest>.json {pid, started, expires, incarnation}.

A killed waiter leaves both behind, stale, on purpose. A wait file that has
not expired beside a pulse that has gone cold is a waiter the machine killed,
and that is precisely the diagnosis silence alone cannot make.

The file is named by digest for the same reason the pulse is: a chair name is
free text and a path is not.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .inbox import pending
from .layer import utc_now
from .pulse import chair_digest, write_pulse

POLL_S = 2.0
PULSE_EVERY_S = 30.0
DEFAULT_TIMEOUT_S = 600.0


def wait_dir(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wait"


def wait_path(root: Path | str, chair: str) -> Path:
    return wait_dir(root) / (chair_digest(chair) + ".json")


def _expires(started: str, timeout: float) -> str:
    try:
        then = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    except ValueError:
        then = datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    # Microseconds always, so an expiry sorts against the feed's own stamps as
    # a string. isoformat() drops them on a round second.
    return (then + timedelta(seconds=float(timeout))).isoformat(timespec="microseconds").replace("+00:00", "Z")


def write_wait_file(root: Path | str, chair: str, *, pid: int, started: str,
                    timeout: float, incarnation: int | None) -> dict[str, Any]:
    row = {
        "chair": str(chair),
        "pid": int(pid),
        "started": started,
        "expires": _expires(started, timeout),
        "incarnation": int(incarnation) if incarnation is not None else None,
    }
    path = wait_path(root, chair)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return row


def read_wait_file(root: Path | str, chair: str) -> dict[str, Any] | None:
    path = wait_path(root, chair)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run(root: Path | str, chair: str, *, timeout: float = DEFAULT_TIMEOUT_S,
        incarnation: int | None = None, interval: float = POLL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        now: Callable[[], str] = utc_now,
        pid: int | None = None,
        write: Callable[..., Any] = write_pulse) -> dict[str, Any]:
    """Poll this chair's inbox until a row lands or the budget runs out.

    Returns the rows WITHOUT draining them: the neuron drains, so the consumed
    marker is its own. `timed_out` true is a clean exit and leaves the pulse to
    go stale by design - the next Stop re-arms a fresh waiter, and a chair that
    never Stops again is exactly the chair whose pulse should go cold.
    """
    root = Path(root)
    sid = str(chair or "").strip()
    if not sid:
        return {"ok": False, "error": "wait requires a chair"}
    started = now()
    write_wait_file(root, sid, pid=int(pid if pid is not None else os.getpid()),
                    started=started, timeout=timeout, incarnation=incarnation)
    budget = max(0.0, float(timeout))
    step = max(0.05, float(interval))
    start = clock()
    last_pulse = None
    while True:
        elapsed = max(0.0, clock() - start)
        if last_pulse is None or elapsed - last_pulse >= PULSE_EVERY_S:
            try:
                write(root, sid, pulse_source="wait", incarnation=incarnation, ts=now())
            except (OSError, ValueError):
                pass   # a pulse that cannot be written must not end the wait
            last_pulse = elapsed
        waiting = pending(root, sid)
        if waiting or elapsed >= budget:
            return {"ok": True, "chair": sid, "pending": waiting, "n": len(waiting),
                    "waited_s": round(elapsed, 3), "timed_out": not waiting,
                    "next": ("inbox --drain --seat " + sid) if waiting else ("inbox --wait --seat " + sid)}
        sleep(min(step, budget - elapsed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convoy.wait",
                                     description="poll one chair's inbox; pulse while waiting")
    parser.add_argument("--root", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--incarnation", type=int, default=None)
    args = parser.parse_args(argv)
    card = run(Path(args.root), args.seat, timeout=args.timeout, incarnation=args.incarnation)
    print(json.dumps(card))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
