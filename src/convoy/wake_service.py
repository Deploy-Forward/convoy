"""The wake service: the dispatcher, running inside the supervised MCP origin.

`serve()` starts it after the listener binds and stops it when serving ends, so it lives and dies
with the origin and its restart supervision. It runs one dispatcher thread per root that opted in
(.convoy/wake/enabled): the origin's bound root, or every present root in the machine index. It
looks again every `rescan_s`, so `convoy wake enable` and `disable` take effect without a restart.
A root that never opted in costs one file check per rescan and is never read.

One dispatcher per root, ever: before it runs, a thread takes an OS lock on an open handle to
`.convoy/wake/dispatcher.lock` (msvcrt.locking on Windows, flock elsewhere) and holds it for its
whole life. However many processes race for it, one holds it; a second origin, a pinned test server
or a manual run gets nothing and runs no loop. The OS releases it when the holder's process dies,
even killed with no finally, so a dead holder never blocks a root and a reused pid means nothing.
The file's {pid, started, host} is for `convoy wake status` only; the lock is the handle, never the
file's content. The lock byte sits far past the content, so a reader can always read the content.
A loop that raises
is logged and started again after `backoff_s`, never taking the HTTP server down; `start()` runs
catch-up each time, and the cursor is written only after dispatch, so a restart replays and the
dedupe key absorbs it.

The routes on this host (LocalRoutes): the waiter route drops a pointer in the target's wake
folder (wake_local). The channel, codex-queue and board-webhook routes are not wired on this host
yet and raise RouteError, so the dispatcher holds the wake and takes its ladder. An alert is a row
in `.convoy/wake/alerts.jsonl` that `convoy wake status` shows.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .filelock import append_line
from .wake_dispatch import Dispatcher, RouteError, cursor_path, read_outbox
from .wake_local import drop_pointer, enabled_row, is_enabled, pointer_dir
from .wake_routes import reachability_detail, read_routes

RESCAN_S = 60.0
BACKOFF_S = 30.0


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# The lock

def lock_path(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wake" / "dispatcher.lock"


# The byte the OS lock covers: far past the content, so readers of {pid, started, host} never touch it.
_LOCK_AT = 1 << 30
# lock_info answers by taking the lock for an instant. An acquire that meets that instant tries again
# a few times before it calls the root held, so a status poll never costs a dispatcher a rescan.
_ACQUIRE_TRIES = 10
_ACQUIRE_WAIT_S = 0.003


def _try_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, _LOCK_AT, os.SEEK_SET)
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
            os.lseek(fd, _LOCK_AT, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _open(root: Path | str) -> int:
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(str(path), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)


class RootLock:
    """The root's dispatcher lock, held on an open handle until `release()` or the process ends."""

    def __init__(self, root: Path | str, fd: int):
        self.root = Path(root)
        self._fd: int | None = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            _unlock(fd)
            os.close(fd)


def acquire_lock(root: Path | str) -> RootLock | None:
    """Take the root's dispatcher lock, or None while any handle anywhere holds it."""
    fd = _open(root)
    for attempt in range(_ACQUIRE_TRIES):
        if _try_lock(fd):
            break
        if attempt == _ACQUIRE_TRIES - 1:
            os.close(fd)
            return None
        time.sleep(_ACQUIRE_WAIT_S)
    row = {"pid": os.getpid(), "started": _stamp(), "host": socket.gethostname()}
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
    except OSError:
        pass  # the content is for status only; the handle is the lock
    return RootLock(root, fd)


def lock_info(root: Path | str) -> dict[str, Any] | None:
    """{held, pid, started, host} for status, or None when no dispatcher ever ran here. `held` is
    asked of the OS; the rest is what the last holder wrote, and says nothing about liveness."""
    path = lock_path(root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    try:
        fd = _open(root)
    except OSError:
        held = None
    else:
        try:
            held = not _try_lock(fd)
            if not held:
                _unlock(fd)
        finally:
            os.close(fd)
    return {"held": held, "pid": value.get("pid"), "started": value.get("started"), "host": value.get("host")}


# The routes on this host

def alerts_path(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wake" / "alerts.jsonl"


class LocalRoutes:
    """The waiter route as a pointer drop; the rest are not wired here yet."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def fire(self, route: str, pointer: dict[str, Any], route_row: dict[str, Any]) -> None:
        if route != "waiter":
            raise RouteError("route " + str(route) + " is not wired on this host yet")
        try:
            drop_pointer(self.root, pointer)
        except OSError as e:
            target = str(pointer.get("target") or "")
            if target and (pointer_dir(self.root, target) / (str(pointer.get("wake_id")) + ".json")).is_file():
                return  # a refire that could not rewrite its pointer: the pointer is still there, so is the wake
            raise RouteError("could not write the pointer: " + type(e).__name__) from e

    def alert(self, target: str, text: str) -> None:
        path = alerts_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"target": target, "text": text, "ts": _stamp()}
        append_line(path, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))


# The service

def _index_roots() -> list[Path]:
    from .index import list_threads
    return [Path(r["root"]) for r in list_threads() if r.get("present") and r.get("root")]


class _Loop:
    def __init__(self, root: Path, lock: RootLock):
        self.root = root
        self.lock = lock
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None


class WakeService:
    def __init__(self, bound: Path | str | None = None, *,
                 routes_for: Callable[[Path], Any] = LocalRoutes,
                 roots: Callable[[], Iterable[Path | str]] | None = None,
                 rescan_s: float = RESCAN_S, poll_s: float = 1.0, backoff_s: float = BACKOFF_S,
                 log: Callable[[str], Any] = lambda line: None):
        self.bound = Path(bound) if bound is not None else None
        self.routes_for = routes_for
        self.roots = roots or ((lambda: [self.bound]) if self.bound is not None else _index_roots)
        self.rescan_s = rescan_s
        self.poll_s = poll_s
        self.backoff_s = backoff_s
        self.log = log
        self._loops: dict[str, _Loop] = {}
        self._halt = threading.Event()
        self._guard = threading.Lock()
        self._scanner: threading.Thread | None = None

    def start(self) -> "WakeService":
        self._scanner = threading.Thread(target=self._scan_forever, name="convoy-wake-scan", daemon=True)
        self._scanner.start()
        return self

    def running(self) -> list[str]:
        with self._guard:
            return sorted(key for key, loop in self._loops.items() if loop.thread and loop.thread.is_alive())

    def _scan_forever(self) -> None:
        while not self._halt.is_set():
            try:
                self.scan()
            except Exception as e:  # a scan that fails is logged and tried again
                self.log("convoy wake scan failed: " + type(e).__name__)
            self._halt.wait(self.rescan_s)

    def scan(self) -> None:
        """Start a loop for each enabled root that has none, and stop each loop whose root is off."""
        if self._halt.is_set():
            return
        wanted = {}
        for root in self.roots():
            path = Path(root)
            try:
                if is_enabled(path):
                    wanted[str(path)] = path
            except OSError:
                continue
        with self._guard:
            for key in [k for k in self._loops if k not in wanted]:
                loop = self._loops.pop(key)
                loop.stop.set()
            for key, path in wanted.items():
                current = self._loops.get(key)
                if current and current.thread and current.thread.is_alive():
                    continue
                lock = acquire_lock(path)
                if lock is None:
                    continue  # another handle, in this process or another, dispatches this root
                loop = _Loop(path, lock)
                loop.thread = threading.Thread(target=self._run, args=(loop,), name="convoy-wake " + key,
                                               daemon=True)
                self._loops[key] = loop
                loop.thread.start()

    def _run(self, loop: _Loop) -> None:
        try:
            while not loop.stop.is_set() and not self._halt.is_set():
                try:
                    Dispatcher(loop.root, self.routes_for(loop.root)).run(
                        poll_s=self.poll_s, should_stop=lambda: loop.stop.is_set() or self._halt.is_set(),
                        sleep=loop.stop.wait)
                except Exception as e:  # a loop that raises starts again, after a back-off
                    self.log("convoy wake loop for " + str(loop.root) + " raised " + type(e).__name__
                             + "; restarting in " + str(self.backoff_s) + " s")
                    loop.stop.wait(self.backoff_s)
        finally:
            loop.lock.release()

    def stop(self, timeout: float | None = None) -> None:
        """Stop every loop and wait for each, then release the locks they hold."""
        self._halt.set()
        with self._guard:
            loops = list(self._loops.values())
            self._loops.clear()
        for loop in loops:
            loop.stop.set()
        wait = self.poll_s + 1.0 if timeout is None else timeout
        for loop in loops:
            if loop.thread:
                loop.thread.join(wait)
        if self._scanner:
            self._scanner.join(wait)


def start_daemon(bound: Path | str | None) -> WakeService:
    """The service the origin runs: its bound root, or every root in the machine index."""
    from .mcp_http import _log_line
    return WakeService(bound, log=_log_line).start()


# Status

def wake_status(root: Path | str) -> dict[str, Any]:
    """Read-only: the switch, the lock, how far the dispatcher has read, and what it decided."""
    root = Path(root)
    row = enabled_row(root)
    feed = root / ".convoy" / "feed.jsonl"
    try:
        cursor = int(cursor_path(root).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        cursor = 0
    try:
        feed_bytes = feed.stat().st_size
    except OSError:
        feed_bytes = 0
    latest: dict[str, dict[str, Any]] = {}
    for r in read_outbox(root):
        if isinstance(r.get("dedupe_key"), str) and r.get("result") != "error":
            latest[r["dedupe_key"]] = r
    outbox: dict[str, int] = {}
    for r in latest.values():
        outbox[str(r.get("result"))] = outbox.get(str(r.get("result")), 0) + 1
    alerts = []
    try:
        for line in alerts_path(root).read_text(encoding="utf-8-sig").splitlines()[-5:]:
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    routes = {}
    for chair, route in sorted(read_routes(root).items()):
        state = reachability_detail(root, chair)
        routes[chair] = {"route": route.get("route"), "reachable": state["reachable"], "reason": state["reason"]}
    return {
        "ok": True, "root": str(root),
        "enabled": row is not None,
        "enabled_by": (row or {}).get("enabled_by"), "enabled_at": (row or {}).get("enabled_at"),
        "lock": lock_info(root),
        "cursor": cursor, "feed_bytes": feed_bytes, "lag_bytes": max(0, feed_bytes - cursor),
        "outbox": outbox, "alerts": alerts, "routes": routes,
    }
