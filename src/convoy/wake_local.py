"""What a wake leaves on this machine: the opt-in switch, and the waiter's pointer folder.

`.convoy/wake/enabled` is the switch. A person writes it with `convoy wake enable`; until then the
dispatcher does not run on the root and the waiter keeps its old behaviour, so nothing changes for
a root that never opted in.

On an enabled root a waiter wake is a pointer file, `.convoy/wake/inbox/<digest>/<wake_id>.json`,
dropped by the dispatcher and nothing else. A pointer names the wake (token, sender, where to read
it), never the body. A refire of the same wake rewrites the same file; a reader holding the old
one open can make that replace fail for a moment on Windows, so it is retried briefly. The
session's own waiter takes a pointer by moving it to `notified/`, which keeps it beside the ack
timer as evidence. A take is exactly once: the taker first claims the pointer with an exclusive
create of `<name>.claim` holding its own nonce, and only the claimant moves it (two concurrent
moves of one file can both succeed on Windows). A claim left by a taker that died is cleared after
CLAIM_STALE_S; a taker re-reads its nonce before the move and releases only its own claim, so one
that stalled past that never moves or releases another taker's claim.

Slim on purpose: the waiter imports this, and the waiter must stay a small process (see wait.py).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pulse import chair_digest

# A claim older than this belongs to a taker that died between its claim and its move.
CLAIM_STALE_S = 60.0
# A refire's replace onto a pointer a reader holds open: tries, the first wait, doubled each time.
REPLACE_TRIES = 6
REPLACE_WAIT_S = 0.02


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_atomic(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


# The switch

def enabled_path(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wake" / "enabled"


def is_enabled(root: Path | str) -> bool:
    return enabled_path(root).is_file()


def enabled_row(root: Path | str) -> dict[str, Any] | None:
    return _read(enabled_path(root)) if is_enabled(root) else None


def enable(root: Path | str, *, by: str, ts: str | None = None) -> dict[str, Any]:
    """Turn wakes on for this root. `by` names who did it; it is a claim, not a proof."""
    who = str(by or "").strip()
    if not who:
        raise ValueError("refuse to enable wakes with no author")
    row = {"enabled_by": who, "enabled_at": ts or _stamp()}
    _write_atomic(enabled_path(root), row)
    return row


def disable(root: Path | str) -> bool:
    """Turn wakes off for this root. True when they were on."""
    try:
        enabled_path(root).unlink()
    except FileNotFoundError:
        return False
    return True


# The pointer folder

def pointer_dir(root: Path | str, chair: str) -> Path:
    return Path(root) / ".convoy" / "wake" / "inbox" / chair_digest(chair)


def drop_pointer(root: Path | str, pointer: dict[str, Any]) -> Path:
    """Write the wake's pointer where the target's waiter looks. The same wake is the same file."""
    target = pointer.get("target")
    wake_id = pointer.get("wake_id")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("refuse a pointer with no target")
    if not isinstance(wake_id, str) or not wake_id.startswith("wk_") or not wake_id[3:].isalnum():
        raise ValueError("refuse a pointer with no wake id")
    path = pointer_dir(root, target) / (wake_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(pointer, separators=(",", ":")) + "\n", encoding="utf-8")
    wait = REPLACE_WAIT_S
    try:
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(temporary, path)
                return path
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(wait)
                wait *= 2
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass  # replaced: nothing is left behind
    return path


def _pointer_files(root: Path | str, chair: str) -> list[Path]:
    folder = pointer_dir(root, chair)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("wk_*.json") if p.is_file())


def pending_pointers(root: Path | str, chair: str) -> list[dict[str, Any]]:
    """The pointers waiting for this chair, oldest name first; unreadable files are skipped."""
    return [row for row in (_read(p) for p in _pointer_files(root, chair)) if row is not None]


def _claim(path: Path) -> tuple[Path, str] | None:
    claim = path.with_name(path.name + ".claim")
    nonce = uuid.uuid4().hex
    try:
        fd = os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        try:
            if time.time() - claim.stat().st_mtime > CLAIM_STALE_S:
                claim.unlink()  # its taker died; the next take claims it
        except OSError:
            pass
        return None
    except OSError:
        return None
    try:
        os.write(fd, nonce.encode("ascii"))
    finally:
        os.close(fd)
    return claim, nonce


def _still_mine(claim: Path, nonce: str) -> bool:
    try:
        return claim.read_bytes().decode("ascii", "replace") == nonce
    except OSError:
        return False


def _release(claim: Path, nonce: str) -> None:
    if _still_mine(claim, nonce):
        try:
            claim.unlink()
        except OSError:
            pass


def take_pointers(root: Path | str, chair: str) -> list[dict[str, Any]]:
    """Claim, read and move each of this chair's pointers to notified/: the session's waiter has
    them now. A pointer another taker claimed is skipped, so each is taken exactly once."""
    taken = []
    for path in _pointer_files(root, chair):
        claimed = _claim(path)
        if claimed is None:
            continue  # another waiter is taking it
        claim, nonce = claimed
        try:
            if not _still_mine(claim, nonce):
                continue  # stalled past CLAIM_STALE_S: another taker has it now
            row = _read(path)
            notified = path.parent / "notified" / path.name
            notified.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, notified)
        except OSError:
            continue  # gone already (taken before this claim), or it cannot be moved
        finally:
            _release(claim, nonce)
        if row is not None:
            taken.append(row)
    return taken
