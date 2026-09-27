"""The chair's pulse: one small file per chair, and who last wrote it.

Liveness is recorded, never inferred. Before this, a deaf chair and a
busy one looked identical from outside and `neurons` faded a chair to quiet
only after ninety minutes. Three processes can speak for a body and the file
says which one did: the Stop hook at a turn end (`stop`), the waiter while it
polls (`wait`), and the pane host while the body is up (`host`). That matters
because they fail differently - a missing `stop` pulse with a live `host`
pulse is a chair that stopped ending turns, not a chair that died.

The file is named by digest, not by chair name: a chair name is free text and
a path is not. Nothing here reads a lane or a vendor session id; the pulse is
timing and provenance only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# A pulse older than this is not evidence of life. Ten minutes matches the
# re-armed wait: one missed window is noticed, not one missed hour.
PULSE_FRESH_SEC = 600
PULSE_SOURCES = ("stop", "wait", "host")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def chair_digest(chair: str) -> str:
    """The chair's file name. A chair name is free text and a path is not."""
    return hashlib.sha256(str(chair).encode("utf-8")).hexdigest()


def _digest(chair: str) -> str:
    return chair_digest(chair)


def pulse_dir(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "pulse"


def pulse_path(root: Path | str, chair: str) -> Path:
    return pulse_dir(root) / (_digest(chair) + ".json")


def write_pulse(root: Path | str, chair: str, *, pulse_source: str,
                incarnation: int | None = None, last_commit: dict[str, Any] | None = None,
                rate_pct: float | None = None, ts: str | None = None) -> dict[str, Any]:
    """Stamp the pulse. The source is required and checked: a pulse whose
    writer is unknown cannot be read as evidence of anything."""
    source = str(pulse_source or "").strip()
    if source not in PULSE_SOURCES:
        raise ValueError("refuse pulse_source " + repr(pulse_source) + "; one of " + ", ".join(PULSE_SOURCES))
    row: dict[str, Any] = {
        "ts": ts or _stamp(),
        "chair": str(chair),
        "incarnation": int(incarnation) if incarnation is not None else None,
        "pulse_source": source,
        "last_commit": last_commit,
        "rate_pct": rate_pct,
    }
    path = pulse_path(root, chair)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return row


def read_pulse(root: Path | str, chair: str) -> dict[str, Any] | None:
    """The pulse, or None. Unreadable is None: a file nobody can parse is not
    a heartbeat."""
    path = pulse_path(root, chair)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse(ts: Any) -> datetime | None:
    text = str(ts or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def pulse_age_seconds(row: dict[str, Any] | None, *, now: str | None = None) -> float | None:
    """Seconds since the pulse, or None when there is no readable timestamp."""
    if not isinstance(row, dict):
        return None
    then = _parse(row.get("ts"))
    if then is None:
        return None
    current = _parse(now) or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - then).total_seconds()


def pulse_is_fresh(row: dict[str, Any] | None, *, window: float = PULSE_FRESH_SEC,
                   now: str | None = None) -> bool:
    age = pulse_age_seconds(row, now=now)
    return age is not None and age <= float(window)


def chair_reachable(pulse: dict[str, Any] | None, wait_row: dict[str, Any] | None,
                    now: str) -> str:
    """waiter-alive | waiter-dead | no-waiter | unknown, from two files.

    Is anyone listening for this chair between turns? No wait file: nobody is,
    which is a fact and not a failure. A wait file past its expiry: the waiter
    finished its window and exited, also not a failure. A wait file still
    inside its window beside a cold pulse is the one bad case - something
    killed the waiter - and it is exactly the case silence cannot name,
    because every surface shows silence and silence from a laptop means
    sleep, crash and a closed lid equally.

    Takes the rows, not the paths: the caller owns where files live, and this
    stays a pure decision with fixed clocks in its tests.
    """
    if not isinstance(wait_row, dict):
        return "no-waiter"
    expires = str(wait_row.get("expires") or "")
    if not expires:
        return "unknown"
    if str(now) > expires:
        return "no-waiter"
    return "waiter-alive" if pulse_is_fresh(pulse, now=now) else "waiter-dead"
