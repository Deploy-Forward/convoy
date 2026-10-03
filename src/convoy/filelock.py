"""One short OS lock per file, and the one way to append a row to a JSONL store.

Every store Convoy appends to (the feed, inboxes, seats, the registry, consents, bearers, the
origin queue, the wake outbox, holds, routes and alerts) appends through `append_line`. Many
processes write the same file at once: each chair's Stop hook, the origin, the CLI. On Windows the C
runtime emulates O_APPEND as seek-then-write, which is not atomic across processes, so two writers
can land on the same offset and one row silently overwrites the other. Under concurrent writers
that lost rows, and feed rows are receipts.

So an append holds an OS lock on a sidecar `<file>.lock` (msvcrt.locking on Windows, flock
elsewhere) for the length of one write: it closes a torn tail with a newline (a writer that died
mid-row leaves the file without its last newline, and the next row must not be glued to it), then
writes the row in one call, then lets go. The lock is re-entrant within a thread, so a caller that
already holds it (an inbox drain, the Stop hook) appends without waiting on itself. A writer that
cannot get the lock in LOCK_TIMEOUT_S raises TimeoutError, an OSError: a row is never written
unlocked.

Slim on purpose: the waiter imports this through layer.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_TIMEOUT_S = 10.0
_POLL_S = 0.005
_held = threading.local()


def _held_paths() -> set[str]:
    paths = getattr(_held, "paths", None)
    if paths is None:
        paths = _held.paths = set()
    return paths


def _try_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def exclusive(path: Path | str, *, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Hold the inter-process lock for `path` (its sidecar `<name>.lock`). Re-entrant per thread."""
    path = Path(path)
    key = os.path.normcase(os.path.abspath(str(path)))
    held = _held_paths()
    if key in held:
        yield
        return
    lock_file = path.with_name(path.name + ".lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    locked = False
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() > deadline:
                raise TimeoutError("could not lock " + lock_file.name + " within " + str(timeout) + " s")
            time.sleep(_POLL_S)
        locked = True
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
    finally:
        if locked:
            _unlock(fd)
        os.close(fd)


def append_line(path: Path | str, data: bytes, *, fsync: bool = False) -> bool:
    """Append whole line(s) under the file's lock, closing a torn tail first. `data` ends in a
    newline. A text-mode write, as every store here has always been: CRLF on Windows.

    A write that fails raises: nothing was appended, and the caller retries. With `fsync`, a sync
    that fails after the write does not raise, because the rows are already in the file and a
    caller that acted on them (a drain marking rows consumed) must still hand them over; it
    returns False. True otherwise."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive(path):
        fd = os.open(str(path), os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            size = os.fstat(fd).st_size
            if size:
                os.lseek(fd, size - 1, os.SEEK_SET)
                if os.read(fd, 1) != b"\n":
                    data = b"\n" + data
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            if fsync:
                try:
                    os.fsync(fd)
                except OSError:
                    return False
        finally:
            os.close(fd)
    return True
