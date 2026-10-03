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

On a root that opted in to wakes (.convoy/wake/enabled, see wake_local), a
waiter wakes only on a dispatcher fire: a pointer in the chair's wake folder,
never a bare inbox row, so the dispatcher's budget, holds and dedupe govern
every wake. Only a waiter the session runs itself, as a background command,
wakes the session when it exits; the Stop hook's detached waiter cannot. So the
wait file names its owner. The session's waiter writes <digest>.session.json,
beats in it, takes the pointers (moving them to notified/) and marks the file
ended when it exits; the hook's keeps today's file and leaves the pointers for
the session. Only an unexpired, beating, session-owned waiter is armed. An armed
waiter waits hours by default, so an idle neuron does not spend a turn every
ten minutes re-arming. It asks on every poll whether the root is still
enabled: the moment a person disables wakes, it watches the inbox again, as
today, so a disable never leaves a chair deaf. A root that never opted in keeps
all of today's behaviour. Surfaces that ask who is listening between turns
(panes, the rail, the origin loop) read `listening_wait_file`, the same
answer the wake directory gives.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .inbox import pending
from .layer import utc_now
from .pulse import chair_digest, write_pulse
from .wake_local import is_enabled, pending_pointers, take_pointers

POLL_S = 2.0
PULSE_EVERY_S = 30.0
DEFAULT_TIMEOUT_S = 600.0
# How long a session's own waiter waits on an enabled root, unless --timeout says otherwise.
ARMED_TIMEOUT_S = 4 * 3600.0
# A session waiter that has not beaten for this long is gone, whatever its expiry says.
ARMED_FRESH_S = 90.0
OWNERS = ("session", "hook")


def wait_dir(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wait"


def wait_path(root: Path | str, chair: str, owner: str | None = None) -> Path:
    """Today's file, which the hook's waiter keeps; the session's own waiter has its own."""
    suffix = ".session.json" if owner == "session" else ".json"
    return wait_dir(root) / (chair_digest(chair) + suffix)


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
                    timeout: float, incarnation: int | None, owner: str | None = None,
                    beat: str | None = None, ended: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "chair": str(chair),
        "pid": int(pid),
        "started": started,
        "expires": _expires(started, timeout),
        "incarnation": int(incarnation) if incarnation is not None else None,
    }
    if owner is not None:  # only on an enabled root: today's file stays as it was
        if owner not in OWNERS:
            raise ValueError("refuse wait owner " + repr(owner) + "; one of " + ", ".join(OWNERS))
        row.update({"owner": owner, "beat": beat or started, "ended": ended})
    path = wait_path(root, chair, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return row


def read_wait_file(root: Path | str, chair: str, owner: str | None = None) -> dict[str, Any] | None:
    path = wait_path(root, chair, owner)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        value = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def listening_wait_file(root: Path | str, chair: str) -> dict[str, Any] | None:
    """The wait file of whoever listens for this chair between turns: on an enabled root, the
    session's own waiter (None once it ended); elsewhere, today's file."""
    if is_enabled(root):
        row = read_wait_file(root, chair, owner="session")
        return None if not row or row.get("ended") else row
    return read_wait_file(root, chair)


_UNSAFE_ON_A_COMMAND_LINE = ('"', "`", "$", "%", "\n", "\r")


def wait_command(root: Path | str, chair: str, python: str | None = None) -> str | None:
    """The waiter's command line, run as written in bash and in PowerShell: the interpreter first,
    unquoted with forward slashes (a quoted path first is a PowerShell parse error), then the root and
    the chair quoted. The interpreter defaults to the one running now, so the line runs the same
    Convoy. None when any part cannot be put on a command line safely (a chair is free text)."""
    exe = (python or sys.executable).replace("\\", "/")
    if " " in exe or any(c in exe for c in _UNSAFE_ON_A_COMMAND_LINE):
        return None
    if any(c in str(root) or c in str(chair) for c in _UNSAFE_ON_A_COMMAND_LINE):
        return None
    return exe + ' -m convoy.wait --root "' + str(root) + '" --seat "' + str(chair) + '"'


def session_waiter_armed(root: Path | str, chair: str, *, now: str | None = None) -> bool:
    """True when the session's own waiter is running: its file is not ended, not expired, and has
    beaten within ARMED_FRESH_S. The hook's waiter never counts."""
    row = read_wait_file(root, chair, owner="session")
    if not row or row.get("owner") != "session" or row.get("ended"):
        return False
    at = _parse(now) if now else datetime.now(timezone.utc)
    beat, expires = _parse(row.get("beat")), _parse(row.get("expires"))
    if at is None or beat is None or expires is None:
        return False
    return expires > at and (at - beat).total_seconds() <= ARMED_FRESH_S


def run(root: Path | str, chair: str, *, timeout: float | None = None,
        incarnation: int | None = None, interval: float = POLL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        now: Callable[[], str] = utc_now,
        pid: int | None = None,
        write: Callable[..., Any] = write_pulse,
        owner: str = "session") -> dict[str, Any]:
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
    if owner not in OWNERS:
        return {"ok": False, "error": "wait owner is one of " + ", ".join(OWNERS)}
    if is_enabled(root):
        return _run_enabled(root, sid, timeout=ARMED_TIMEOUT_S if timeout is None else timeout,
                            incarnation=incarnation, interval=interval, clock=clock, sleep=sleep,
                            now=now, pid=pid, write=write, owner=owner)
    if timeout is None:
        timeout = DEFAULT_TIMEOUT_S
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


def _run_enabled(root: Path, sid: str, *, timeout: float, incarnation: int | None, interval: float,
                 clock: Callable[[], float], sleep: Callable[[float], Any], now: Callable[[], str],
                 pid: int | None, write: Callable[..., Any], owner: str) -> dict[str, Any]:
    """Wait for a pointer in the chair's wake folder. The session's waiter takes it; the hook's
    leaves it for the session. Either way the wait file says who waited, and ends when it does."""
    started = now()
    budget = max(0.0, float(timeout))
    beat = started

    def record(ended: str | None = None) -> None:
        write_wait_file(root, sid, pid=int(pid if pid is not None else os.getpid()), started=started,
                        timeout=budget, incarnation=incarnation, owner=owner, beat=beat, ended=ended)

    record()
    step = max(0.05, float(interval))
    start = clock()
    last_pulse = None
    try:
        while True:
            elapsed = max(0.0, clock() - start)
            if last_pulse is None or elapsed - last_pulse >= PULSE_EVERY_S:
                stamp = now()
                try:
                    write(root, sid, pulse_source="wait", incarnation=incarnation, ts=stamp)
                except (OSError, ValueError):
                    pass   # a pulse that cannot be written must not end the wait
                if last_pulse is not None:
                    beat = stamp
                    try:
                        record()
                    except OSError:
                        pass
                last_pulse = elapsed
            rearm = wait_command(root, sid)
            again = ("re-arm: " + rearm) if rearm else "re-arm your waiter"
            if not is_enabled(root):
                # Wakes were turned off while this waiter was armed: no pointer will come, so listen
                # to the inbox again, as on any root that never opted in.
                waiting = pending(root, sid)
                if waiting or elapsed >= budget:
                    return {"ok": True, "chair": sid, "owner": owner, "pointers": [], "pending": waiting,
                            "n": len(waiting), "waited_s": round(elapsed, 3), "timed_out": not waiting,
                            "next": ("inbox --drain --seat " + sid) if waiting else again}
            else:
                pointers = take_pointers(root, sid) if owner == "session" else pending_pointers(root, sid)
                if pointers or elapsed >= budget:
                    return {"ok": True, "chair": sid, "owner": owner,
                            "pointers": [{k: p.get(k) for k in ("wake_id", "reason", "token", "from", "read_with")}
                                         for p in pointers],
                            "pending": [], "n": len(pointers), "waited_s": round(elapsed, 3), "timed_out": not pointers,
                            "next": ("inbox --drain --seat " + sid) if pointers else again}
            sleep(min(step, budget - elapsed))
    finally:
        try:
            record(ended=now())  # no longer armed, however it ended
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convoy.wait",
                                     description="poll one chair's inbox; pulse while waiting")
    parser.add_argument("--root", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--timeout", type=float, default=None,
                        help="seconds; default " + str(int(DEFAULT_TIMEOUT_S)) + ", or "
                        + str(int(ARMED_TIMEOUT_S)) + " for a session's waiter on a root with wakes enabled")
    parser.add_argument("--incarnation", type=int, default=None)
    parser.add_argument("--owner", choices=OWNERS, default="session",
                        help="session: run by the session itself (the one that wakes it); hook: the Stop hook's")
    args = parser.parse_args(argv)
    card = run(Path(args.root), args.seat, timeout=args.timeout, incarnation=args.incarnation,
               owner=args.owner)
    print(json.dumps(card))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
