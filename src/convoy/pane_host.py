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


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def host_state_path(root: Path, session_id: str) -> Path:
    return Path(root) / ".convoy" / "pane-hosts" / (_digest(session_id) + ".json")


def close_request_path(root: Path, session_id: str) -> Path:
    return host_state_path(root, session_id).with_suffix(".close")


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
) -> int:
    """Run one native harness, acknowledging exact close requests with exit 0."""
    root = Path(root).resolve()
    row = _seat(root, session_id)
    worktree = str(row.get("worktree") or "").strip()
    if not worktree or not Path(worktree).is_dir():
        raise ValueError("managed pane requires an existing worktree")
    # Delayed import avoids a module cycle: targeted_launch only names this
    # module in the argv executed by the terminal.
    from .targeted_launch import pane_child_argv

    child_argv = pane_child_argv(row)
    process = popen(child_argv, cwd=worktree, **_popen_kwargs())
    state = {
        "session_id": session_id,
        "status": "running",
        "host_pid": os.getpid(),
        "child_pid": int(process.pid),
        "started_at": _stamp(),
        "worktree": worktree,
        "to": row.get("to"),
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
        )
    except ValueError:
        pass

    request = close_request_path(root, session_id)
    while True:
        if request.is_file():
            terminate(process)
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
            return 0
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
            try:
                update_seat(root, session_id, process_state="exited", pane_state="child-exited")
            except ValueError:
                pass
            return int(return_code)
        sleep(0.2)


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
        request = close_request_path(root, session_id)
        request.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(request), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            payload = json.dumps({"session_id": session_id, "requested_at": _stamp()}) + "\n"
            os.write(descriptor, payload.encode("utf-8"))
        finally:
            os.close(descriptor)
        update_seat(root, session_id, close_state="requested")
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
