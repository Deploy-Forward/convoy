"""Widget as a service: one detached `convoy widget` per machine, behind a pidfile.

Pidfile: <CONVOY_HOME>/widget.pid. An alive pid means "already running"; a dead
or garbage pid is replaced. The spawn is injectable so tests never open Tk or a
real process. `started` is true only after the spawner returned a pid.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .index import is_temp_root

PIDFILE = "widget.pid"
Spawner = Callable[[list[str]], int]
AliveFn = Callable[[int], bool]
ImageFn = Callable[[int], str | None]


def convoy_home(home: Path | str | None = None) -> Path:
    """Explicit home, else $CONVOY_HOME, else ~/.convoy (same rule as index_path)."""
    if home is not None:
        return Path(home)
    env = os.environ.get("CONVOY_HOME")
    return Path(env) if env else Path.home() / ".convoy"


def service_argv() -> list[str]:
    """The strip, refreshing every 3 s, pinned. Never -p, never --resume."""
    return [sys.executable, "-m", "convoy", "widget", "--refresh", "3", "--topmost"]


def pid_alive(pid: int) -> bool:
    """Liveness without side effects. On nt os.kill(pid, 0) would TERMINATE; use OpenProcess."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(query, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_image(pid: int) -> str | None:
    """Executable path of pid (nt: QueryFullProcessImageNameW; else /proc). None when unknown."""
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value or None
        finally:
            kernel32.CloseHandle(handle)
    try:
        return os.readlink("/proc/" + str(int(pid)) + "/exe") or None
    except OSError:
        return None


def looks_like_widget(image: str | None) -> bool | None:
    """True when the recorded pid runs our interpreter; False when another image; None when unknown."""
    if not image:
        return None
    return os.path.normcase(os.path.normpath(image)) == os.path.normcase(os.path.normpath(sys.executable))


def detached_spawn(argv: list[str]) -> int:
    """Spawn with no console tie: the strip outlives the terminal that started it."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs).pid


def _read_pid(pidfile: Path) -> int | None:
    if not pidfile.is_file():
        return None
    try:
        return int(pidfile.read_text(encoding="utf-8-sig").strip())
    except (OSError, ValueError):
        return None


def ensure_widget_service(
    home: Path | str | None = None,
    *,
    spawner: Spawner | None = None,
    alive_fn: AliveFn | None = None,
    image_fn: ImageFn | None = None,
) -> dict[str, Any]:
    """Alive pidfile -> already:true, no spawn. Else spawn detached and record the pid.

    A pid can be reused by an unrelated process: `already` is claimed only when
    the live pid's image is our interpreter (image_verified true) or the image
    is unreadable (image_verified null, reported as such). Another image means
    the pid was reused -> stale, respawn.
    """
    base = convoy_home(home)
    pidfile = base / PIDFILE
    card: dict[str, Any] = {
        "ok": True,
        "started": False,
        "already": False,
        "pid": None,
        "stale_pid": None,
        "pidfile": str(pidfile),
        "argv": service_argv(),
        "image": None,
        "image_verified": None,
    }
    known = _read_pid(pidfile)
    alive = alive_fn or pid_alive
    if known is not None and alive(known):
        image = (image_fn or process_image)(known)
        verdict = looks_like_widget(image)
        card["image"] = image
        card["image_verified"] = verdict
        if verdict is not False:
            card["already"] = True
            card["pid"] = known
            return card
        card["pid_reused"] = True
    card["stale_pid"] = known
    try:
        pid = int((spawner or detached_spawn)(card["argv"]))
        base.mkdir(parents=True, exist_ok=True)
        pidfile.write_text(str(pid) + "\n", encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        card["ok"] = False
        card["error"] = type(e).__name__ + ": " + str(e)
        return card
    card["started"] = True
    card["pid"] = pid
    return card


def auto_widget_service(
    *,
    disabled: bool,
    home: Path | str | None = None,
    spawner: Spawner | None = None,
    alive_fn: AliveFn | None = None,
    image_fn: ImageFn | None = None,
) -> dict[str, Any]:
    """The crew/relaunch hook: skip on --no-widget or a throwaway CONVOY_HOME (tests)."""
    base = convoy_home(home)
    if disabled:
        return {"ok": True, "started": False, "already": False, "skipped": "--no-widget"}
    if is_temp_root(base):
        return {"ok": True, "started": False, "already": False, "skipped": "temp CONVOY_HOME"}
    card = ensure_widget_service(base, spawner=spawner, alive_fn=alive_fn, image_fn=image_fn)
    card["skipped"] = None
    return card
