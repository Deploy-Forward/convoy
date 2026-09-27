"""Lifecycle host for one native harness process inside one terminal pane.

The host never reads or writes TUI bytes. It owns the child process handle so a
separately consented Convoy close request can terminate that exact child tree;
the host then exits zero, allowing graceful Windows Terminal profiles to remove
the pane instead of retaining an abnormal-exit panel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .consent import consume_consent, request_consent
from .convoy import list_seats, update_seat
from .layer import hook
from .pulse import write_pulse

# How often the host says the body is still up. Well inside the ten-minute
# freshness window, so one missed beat is noise and two are a signal.
HOST_PULSE_EVERY_S = 60.0

# How much of the child's dying words ride the feed row. A boot failure says
# what it needs in a line or two; the whole log is on disk beside the state.
STDERR_TAIL_CHARS = 2000


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pid_alive(pid: Any) -> bool:
    """True when that process id is still running.

    Never `os.kill(pid, 0)` on Windows: CPython maps os.kill to
    TerminateProcess for any signal but CTRL_C/CTRL_BREAK, so the "probe"
    would kill the body it asked about. Query the handle instead.
    """
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32   # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, value)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            # STILL_ACTIVE is also a legal exit code; a process that exited
            # with 259 reads as alive. Rare, and erring towards "occupied"
            # refuses a launch rather than adding a second body.
            return int(code.value) == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True            # someone else's process: alive, not ours
    except OSError:
        return False
    return True


_NO_REQUEST = object()


def _close_request_incarnation(request: Path) -> Any:
    """The incarnation a close request cites: _NO_REQUEST when there is no
    request, None when the file cannot be read or names no life. None is not
    'current' — an unreadable request is never honoured."""
    if not request.is_file():
        return _NO_REQUEST
    try:
        value = json.loads(request.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    cited = value.get("incarnation")
    try:
        return int(cited)
    except (TypeError, ValueError):
        return None


def stderr_log_path(root: Path, session_id: str) -> Path:
    return host_state_path(root, session_id).with_suffix(".stderr")


def _stderr_tail(path: Path, limit: int = STDERR_TAIL_CHARS) -> str | None:
    """The child's last words, or None when it said nothing. Never an
    invented reason: an unreadable log is None, not an empty string."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    return text[-limit:]


def request_beat(root: Path) -> None:
    """Touch the file the origin loop watches, so a local transition beats now
    instead of waiting out the idle backoff. Best effort: a beat that cannot
    be requested must never take the body's exit row down with it."""
    try:
        path = Path(root) / ".convoy" / "beat-request"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_stamp() + "\n", encoding="utf-8")
    except OSError:
        pass


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def host_state_path(root: Path, session_id: str) -> Path:
    return Path(root) / ".convoy" / "pane-hosts" / (_digest(session_id) + ".json")


def launch_argv_path(root: Path, session_id: str) -> Path:
    """The pane's launch record: the exact harness argv bring_up validated for this chair.
    Written by isolated_wt_argv when it hands the pane to the host; consumed once by run_host."""
    return Path(root) / ".convoy" / "panes" / (_digest(session_id) + ".launch.json")


def write_launch_argv(root: Path, session_id: str, argv: list[str], cwd: str | None) -> Path:
    path = launch_argv_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"session_id": session_id, "argv": [str(a) for a in argv], "cwd": cwd, "written_at": _stamp()}) + "\n"
    # owner-only: the boot prompt on argv carries the single-use seated token
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def read_launch_argv(root: Path, session_id: str) -> dict[str, Any] | None:
    path = launch_argv_path(root, session_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def close_request_path(root: Path, session_id: str) -> Path:
    return host_state_path(root, session_id).with_suffix(".close")


def nudge_request_path(root: Path, session_id: str) -> Path:
    return host_state_path(root, session_id).with_suffix(".nudge")


def request_nudge(root: Path, session_id: str, *, text: str, nudge_id: str, consent: str) -> Path:
    """Write the one live nudge request for a chair. O_EXCL: exactly one
    in flight, so two callers cannot queue two keystrokes for the host to race.
    The host's own poll loop consumes it; this never types anything itself."""
    request = nudge_request_path(Path(root), session_id)
    request.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "text": text,
        "nudge_id": nudge_id,
        "consent": consent,
        "requested_at": _stamp(),
    }
    descriptor = os.open(str(request), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (json.dumps(payload) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return request


def _read_nudge_request(request: Path) -> dict[str, Any] | None:
    if not request.is_file():
        return None
    try:
        value = json.loads(request.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


ConsoleWriter = Callable[[str], dict[str, Any]]

VK_RETURN = 0x0D
_NAMED_KEYS = frozenset({"enter", "return", "c-m"})


def console_key_records(text: str) -> list[tuple[int, str]]:
    """What the host types for one nudge, as (virtual key, char) pairs.

    A bare key name (Enter / Return / C-m) is ONE VK_RETURN event and no
    characters: typed as text, the name arrives as the letters E-n-t-e-r and
    the chair never sees a submit. Typed text is its characters with
    no key code, then a VK_RETURN event; a '\\r' character with key code 0 is not
    a submit to a TUI reader, which is why earlier nudges sat in the prompt."""
    if text.strip().lower() in _NAMED_KEYS:
        return [(VK_RETURN, "\r")]
    return [(0, ch) for ch in text] + [(VK_RETURN, "\r")]


def write_console_input(text: str) -> dict[str, Any]:
    """Inject `text` plus Enter into the console THIS process shares with its
    child. The child was spawned with a process-group flag, not
    CREATE_NEW_CONSOLE (`_popen_kwargs`), so it inherits this host's console
    and is its foreground reader; WriteConsoleInputW on this process's own
    STD_INPUT_HANDLE is therefore the child's stdin, with no window, no
    title, and no focus theft involved."""
    if os.name != "nt":
        return {"ok": False, "error": "console injection is Windows only"}
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    STD_INPUT_HANDLE = -10
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if not handle or int(handle) in (0, -1):
        return {"ok": False, "error": "no console input handle on this host"}

    KEY_EVENT = 0x0001

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", wintypes.BOOL),
            ("wRepeatCount", wintypes.WORD),
            ("wVirtualKeyCode", wintypes.WORD),
            ("wVirtualScanCode", wintypes.WORD),
            ("uChar", wintypes.WCHAR),
            ("dwControlKeyState", wintypes.DWORD),
        ]

    class _EventUnion(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", _EventUnion)]

    keys = console_key_records(text)
    records = (INPUT_RECORD * (len(keys) * 2))()
    i = 0
    for vk, ch in keys:
        for down in (True, False):
            records[i].EventType = KEY_EVENT
            records[i].Event.KeyEvent.bKeyDown = down
            records[i].Event.KeyEvent.wRepeatCount = 1
            records[i].Event.KeyEvent.wVirtualKeyCode = vk
            records[i].Event.KeyEvent.wVirtualScanCode = 0x1C if vk == VK_RETURN else 0
            records[i].Event.KeyEvent.uChar = ch
            records[i].Event.KeyEvent.dwControlKeyState = 0
            i += 1
    written = wintypes.DWORD(0)
    ok = kernel32.WriteConsoleInputW(handle, records, len(records), ctypes.byref(written))
    if not ok:
        return {"ok": False, "error": "WriteConsoleInputW failed: GetLastError=" + str(ctypes.get_last_error())}
    return {"ok": True, "count": int(written.value)}


def _write_state(root: Path, session_id: str, state: dict[str, Any]) -> None:
    path = host_state_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(state, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_state(root: Path, session_id: str) -> dict[str, Any] | None:
    path = host_state_path(root, session_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_host_records(root: Path) -> list[dict[str, Any]]:
    """Every pane-host record on this thread, newest-agnostic, one per chair.

    The record is how Convoy knows which body belongs to which chair
    without reading a command line. A pid someone wrote down at launch cannot
    be forged by a prompt string; a path in argv can.
    """
    directory = Path(root) / ".convoy" / "pane-hosts"
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("session_id"):
            out.append(value)
    return out


def _seat(root: Path, session_id: str) -> dict[str, Any]:
    for row in list_seats(root):
        if row.get("session_id") == session_id:
            return row
    raise ValueError("unknown seat: " + session_id)


def _popen_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        # A process group does not create a new console. The native harness
        # remains attached to this pane while giving the host an owned tree.
        return {"creationflags": 0x00000200}
    return {"start_new_session": True}


def terminate_child_tree(process: Any) -> None:
    """Terminate only the child tree owned by this host."""
    pid = int(process.pid)
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode not in (0, 128):
            raise RuntimeError("taskkill failed for managed child")
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def run_host(
    root: Path,
    session_id: str,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    terminate: Callable[[Any], None] = terminate_child_tree,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    console_writer: "ConsoleWriter" = write_console_input,
) -> int:
    """Run one native harness, acknowledging exact close requests with exit 0."""
    root = Path(root).resolve()
    row = _seat(root, session_id)
    worktree = str(row.get("worktree") or "").strip()
    if not worktree or not Path(worktree).is_dir():
        raise ValueError("managed pane requires an existing worktree")
    # Delayed import avoids a module cycle: targeted_launch only names this
    # module in the argv executed by the terminal.
    from .targeted_launch import pane_child_argv, take_launch_claim

    # The claim is taken BEFORE anything is spawned, so two relaunches racing
    # for one chair produce one body and one refusal, not two bodies. Crew
    # and relaunch reach this line too now.
    take_launch_claim(root, session_id, host_pid=os.getpid())
    # root=: this is the one place a session id may be minted, because it is
    # the only place that both spawns the body and can record the id.
    child_argv = pane_child_argv(row, root=root)
    # The launch record holds the argv bring_up validated for THIS pane (boot prompt
    # with the seated token, live flags, effort, relaunch prompt). It wins over the argv
    # rebuilt from the seat row, and it is consumed so one record launches one body.
    launch = read_launch_argv(root, session_id)
    if launch and launch.get("argv"):
        child_argv = [str(a) for a in launch["argv"]]
    if launch:
        launch_argv_path(root, session_id).unlink(missing_ok=True)
    # The child's stderr goes to a file this host owns rather than to the
    # pane, which scrolls it away and then closes. A file cannot deadlock the
    # way an undrained pipe can, and it is what makes the exit row honest.
    log = stderr_log_path(root, session_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    sink = open(log, "wb")
    launched_at = _stamp()
    incarnation = int(row.get("incarnation") or 0) + 1
    try:
        process = popen(child_argv, cwd=worktree, stderr=sink, **_popen_kwargs())
    except BaseException:
        sink.close()
        from .targeted_launch import release_launch_claim as _release

        _release(root, session_id)
        raise
    state = {
        "session_id": session_id,
        "status": "running",
        "host_pid": os.getpid(),
        "child_pid": int(process.pid),
        "child_exe": str(child_argv[0]) if child_argv else None,
        "incarnation": incarnation,
        "started_at": launched_at,
        "worktree": worktree,
        "to": row.get("to"),
        "stderr_log": str(log),
        "terminal_session": os.environ.get("WT_SESSION") or os.environ.get("TMUX_PANE"),
    }
    _write_state(root, session_id, state)
    try:
        update_seat(
            root,
            session_id,
            process_state="running",
            pane_state="managed",
            pane_host_pid=state["host_pid"],
            harness_pid=state["child_pid"],
            incarnation=incarnation,
            launched_at=launched_at,
        )
    except ValueError:
        pass
    request_beat(root)

    from .targeted_launch import release_launch_claim

    request = close_request_path(root, session_id)
    # A close request left behind by a PREVIOUS body of this chair must not
    # kill a fresh occupant (a relaunched agent could be terminated two
    # seconds after start by the request that closed its predecessor).
    # Anything on disk before this host started belongs to the past.
    if request.is_file():
        request.unlink(missing_ok=True)
    nudge_request = nudge_request_path(root, session_id)
    if nudge_request.is_file():
        nudge_request.unlink(missing_ok=True)  # same rule: a stale request predates this body
    # The host is the third voice on a chair's pulse, and the only one
    # that speaks while the body is mid-turn. A cold `stop` pulse beside a
    # warm `host` pulse is a chair that stopped ending turns; a cold host
    # pulse is a chair with no body at all. They fail differently, so they are
    # recorded separately.
    last_host_pulse: float | None = None
    try:
        while True:
            beat_at = clock()
            if last_host_pulse is None or beat_at - last_host_pulse >= HOST_PULSE_EVERY_S:
                try:
                    write_pulse(root, session_id, pulse_source="host", incarnation=incarnation)
                except (OSError, ValueError):
                    pass    # a pulse must never take the body down
                last_host_pulse = beat_at
            cited = _close_request_incarnation(request)
            if cited is not _NO_REQUEST and cited != incarnation:
                # A request addressed to an earlier life. Consume it so it
                # cannot fire again, and say so — silently deleting it would
                # leave a human's consented close looking as if it worked.
                request.unlink(missing_ok=True)
                try:
                    hook(
                        root,
                        "close-ignored",
                        "close request for chair " + session_id + " cited incarnation " + str(cited),
                        instance_id=session_id,
                        extra={"chair": session_id, "incarnation": incarnation, "cited": cited},
                    )
                except (OSError, ValueError):
                    pass
                continue
            if cited is not _NO_REQUEST:
                terminate(process)
                request.unlink(missing_ok=True)        # consumed: exactly one close per request
                release_launch_claim(root, session_id)  # the pane is going away
                state.update({"status": "close-request-acknowledged", "closed_at": _stamp()})
                _write_state(root, session_id, state)
                try:
                    update_seat(
                        root,
                        session_id,
                        process_state="exited",
                        pane_state="close-dispatched",
                        launch_state="closed-by-consent",
                    )
                except ValueError:
                    pass
                request_beat(root)
                return 0
            nudge = _read_nudge_request(nudge_request)
            if nudge is not None:
                nudge_id = str(nudge.get("nudge_id") or "")
                text = str(nudge.get("text") or "")
                result = console_writer(text)
                typed_at = _stamp() if result.get("ok") else None
                state["last_nudge"] = {
                    "nudge_id": nudge_id,
                    "typed_at": typed_at,
                    "ok": bool(result.get("ok")),
                    "error": result.get("error"),
                }
                _write_state(root, session_id, state)
                nudge_request.unlink(missing_ok=True)  # consumed: exactly one type per request
                try:
                    hook(
                        root,
                        "nudge-typed" if result.get("ok") else "nudge-failed",
                        ("typed into " if result.get("ok") else "failed to type into ") + session_id + " nudge=" + nudge_id,
                        instance_id=session_id,
                        extra={"nudge_id": nudge_id, "ok": bool(result.get("ok")), "error": result.get("error")},
                    )
                except (OSError, ValueError):
                    pass
                request_beat(root)
                continue
            return_code = process.poll()
            if return_code is not None:
                state.update(
                    {
                        "status": "child-exited",
                        "child_returncode": int(return_code),
                        "closed_at": _stamp(),
                    }
                )
                _write_state(root, session_id, state)
                release_launch_claim(root, session_id)  # no body left; the chair may be launched again
                try:
                    update_seat(root, session_id, process_state="exited", pane_state="child-exited")
                except ValueError:
                    pass
                sink.close()
                # Death is a row. Before this, a body that failed at boot
                # left the feed showing a chair that simply never acked.
                tail = _stderr_tail(log)
                summary = "chair " + session_id + " exited " + str(int(return_code))
                try:
                    hook(
                        root,
                        "pane",
                        summary,
                        instance_id=session_id,
                        extra={
                            "chair": session_id,
                            "incarnation": incarnation,
                            "exit": int(return_code),
                            "stderr_tail": tail,
                        },
                    )
                except (OSError, ValueError):
                    pass
                request_beat(root)
                return int(return_code)
            sleep(0.2)
    finally:
        if not sink.closed:
            sink.close()


def request_close(root: Path, session_id: str, *, incarnation: Any = None,
                  reason: str | None = None) -> Path:
    """Write the one close request for a chair, naming the life it closes.

    O_EXCL: exactly one request per close, so two callers cannot queue two
    terminations. The host honours it only when it cites the body actually
    running, which is why `incarnation` is not optional in practice - a
    request that names no life is consumed and recorded as close-ignored.
    """
    request = close_request_path(Path(root), session_id)
    request.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "session_id": session_id,
        "incarnation": int(incarnation) if incarnation is not None else None,
        "requested_at": _stamp(),
    }
    if reason:
        payload["reason"] = str(reason)
    descriptor = os.open(str(request), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (json.dumps(payload) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return request


def close_managed_pane(
    root: Path,
    session_id: str,
    *,
    consent: str | None = None,
) -> dict[str, Any]:
    """Request close for an exact managed chair; never inject terminal input."""
    root = Path(root).resolve()
    try:
        row = _seat(root, session_id)
    except ValueError as exc:
        return {"ok": False, "session_id": session_id, "error": str(exc)}
    state = _read_state(root, session_id)
    if state is None or state.get("status") != "running":
        return {
            "ok": False,
            "session_id": session_id,
            "state": "manual-close-required",
            "error": "chair was not launched by a live Convoy pane host",
            "remedy": "Focus the exited pane and press Ctrl+D (or the terminal's closePane binding).",
        }
    worktree = str(row.get("worktree") or "")
    to = str(row.get("to") or "")
    if not consent:
        waiting = request_consent(
            root,
            "close-chair",
            session_id=session_id,
            to=to,
            worktree=worktree,
        )
        return {"session_id": session_id, **waiting}
    try:
        consume_consent(
            root,
            consent,
            "close-chair",
            session_id=session_id,
            to=to,
            worktree=worktree,
        )
        incarnation = state.get("incarnation")
        if incarnation is None:
            incarnation = row.get("incarnation")
        request_close(root, session_id, incarnation=incarnation, reason="close-chair")
        update_seat(root, session_id, close_state="requested")
        # The launch claim says "a pane exists for this chair". Once close is
        # requested it must not block the next launch (2026-09-03: relaunch of
        # a closed chair refused "already claimed" until the file was removed).
        from .targeted_launch import release_launch_claim
        release_launch_claim(root, session_id)
        return {
            "ok": True,
            "session_id": session_id,
            "state": "close-requested",
            "host_pid": state.get("host_pid"),
            "child_pid": state.get("child_pid"),
            "pane_closed": None,
            "next": "Verify the pane disappeared; process exit alone is not pane proof.",
        }
    except (OSError, ValueError) as exc:
        return {"ok": False, "session_id": session_id, "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m convoy.pane_host")
    parser.add_argument("--root", required=True)
    parser.add_argument("--seat", required=True)
    args = parser.parse_args(argv)
    try:
        return run_host(Path(args.root), args.seat)
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
