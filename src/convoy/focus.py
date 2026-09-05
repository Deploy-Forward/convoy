"""focus --seat: ask the pane host to highlight one chair.

tmux: `select-pane -t` is proven via an injectable runner.
Windows Terminal: `wt focus-pane` is NOT evidenced on this machine
(2026-09-05: wt.exe is the WindowsApps stub; `wt.exe --help` and
`wt.exe focus-pane --help` produced no targeting documentation). The card
stays `{focused: false, reason}` until an adapter is evidenced.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .convoy import list_seats

Runner = Callable[[list[str]], dict[str, Any]]

# harness_effort.json-style notes: host adapters, evidenced or not.
WT_FOCUS_EVIDENCE = {
    "command": "wt focus-pane",
    "evidenced": False,
    "observed": (
        "2026-09-05 this machine: wt.exe is "
        r"C:\Users\marco\AppData\Local\Microsoft\WindowsApps\wt.exe "
        "(WindowsApps stub). `wt.exe --help` and `wt.exe focus-pane --help` "
        "produced no output and no pane-target documentation. No adapter."
    ),
}
WT_FOCUS_REASON = "windows-terminal: no evidenced pane-target adapter (wt focus-pane undocumented on this host)"


def _require_seat(root: Path, session_id: str) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    for row in list_seats(root):
        if row.get("session_id") == sid:
            return row
    raise ValueError("unknown seat: " + sid)


def _default_runner(argv: list[str]) -> dict[str, Any]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "returncode": 127, "error": str(e), "argv": argv}
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "argv": argv,
    }


def focus_seat(
    root: Path | str,
    session_id: str,
    *,
    runner: Runner | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    """Focus the pane for one chair. Never a token. focused is false until
    a host adapter is evidenced and actually ran."""
    root = Path(root)
    sid = str(session_id or "").strip()
    card: dict[str, Any] = {
        "ok": True,
        "seat": sid,
        "focused": False,
        "reason": None,
        "host": None,
    }
    try:
        _require_seat(root, sid)
    except ValueError as e:
        return {"ok": False, "seat": sid, "focused": False, "reason": str(e), "error": str(e)}

    run = runner or _default_runner
    pane = (target or "").strip() or None

    if os.environ.get("TMUX"):
        card["host"] = "tmux"
        if not pane:
            card["reason"] = "tmux: no pane target for this chair"
            return card
        argv = ["tmux", "select-pane", "-t", pane]
        result = run(argv)
        card["argv"] = argv
        if result.get("ok") or result.get("returncode") == 0:
            card["focused"] = True
            card["reason"] = None
            return card
        card["reason"] = "tmux select-pane failed: " + str(result.get("error") or result.get("stderr") or result.get("returncode"))
        return card

    if os.name == "nt" and (shutil.which("wt") or shutil.which("wt.exe")):
        card["host"] = "windows-terminal"
        card["reason"] = WT_FOCUS_REASON
        card["evidence"] = WT_FOCUS_EVIDENCE
        return card

    card["host"] = None
    card["reason"] = "no evidenced pane-host adapter"
    return card
