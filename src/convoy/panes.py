"""panes: every body of every neuron in a session, from the OS process table.

Marco 2026-09-03: "you should be able to see all associated panes in a
session; within a session you should be able to close, identify, or
understand what is occurring; ensure this exists across all neurons."

The registry only knows what Convoy launched. A neuron opened by hand, by a
vendor picker, or by another tool is invisible to it — and that blindness
produced a second body on a live codex thread today (codex refused: "already
has an active writer"). So liveness here comes from the process table:

  via "token"  — the chair's vendor token appears in a process command line
                 (portable: Windows CIM, POSIX ps).
  via "cwd"    — the process cwd equals the chair's worktree and the exe is
                 that chair's harness (Linux /proc, macOS lsof; Windows
                 exposes no cwd from stdlib, so this rung is null there).
  unassigned   — a harness process Convoy cannot place. Listed with pid and
                 exe, never hidden, so a human can identify it.

The view never prints a token: bodies say via, pid, exe. Close stays what it
is: managed panes close through the consented pane host; an unmanaged body
is `manual-close-required` with its pid shown.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .convoy import list_seats
from .harness_contract import canonical_harness_id

HARNESS_EXES = {
    "codex": ("codex", "codex.js", "codex.cmd", "codex.exe"),
    "claude": ("claude", "claude.exe", "claude.cmd", "cli.js"),
    "grok": ("grok", "grok.exe", "grok.cmd"),
    "cursor-agent": ("cursor-agent", "cursor-agent.exe"),
    "agy": ("agy", "agy.exe"),
    "hermes": ("hermes", "hermes.exe"),
    "pi": ("pi", "pi.exe"),
}


def enumerate_processes() -> list[dict[str, Any]]:
    """{pid, ppid, cmdline, cwd|None} for every process the OS will show."""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine "
              "| ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=20, check=True).stdout
        data = json.loads(out or "[]")
        if isinstance(data, dict):
            data = [data]
        return [{"pid": int(d.get("ProcessId") or 0), "ppid": int(d.get("ParentProcessId") or 0),
                 "cmdline": str(d.get("CommandLine") or ""), "cwd": None} for d in data]
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True,
                         timeout=20, check=True).stdout
    procs: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        cmd = parts[2] if len(parts) > 2 else ""
        cwd = None
        if sys.platform.startswith("linux"):
            try:
                cwd = os.readlink("/proc/" + str(pid) + "/cwd")
            except OSError:
                cwd = None
        procs.append({"pid": pid, "ppid": ppid, "cmdline": cmd, "cwd": cwd})
    if sys.platform == "darwin":
        _fill_cwd_lsof(procs)
    return procs


def _fill_cwd_lsof(procs: list[dict[str, Any]]) -> None:
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return
    cur = None
    cwds: dict[int, str] = {}
    for line in out.splitlines():
        if line.startswith("p"):
            cur = int(line[1:])
        elif line.startswith("n") and cur is not None:
            cwds[cur] = line[1:]
    for p in procs:
        if p["pid"] in cwds:
            p["cwd"] = cwds[p["pid"]]


def _exe_harness(cmdline: str) -> str | None:
    """Which harness a command line runs, by executable/script basename."""
    toks = cmdline.replace('"', " ").split()
    for tok in toks[:3]:
        base = os.path.basename(tok).lower()
        for hid, names in HARNESS_EXES.items():
            if base in names:
                return hid
    return None


def _same_path(a: Any, b: Any) -> bool:
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))
    except (TypeError, ValueError):
        return False


def match_processes(root: Path, procs: list[dict[str, Any]]) -> dict[str, Any]:
    seats = list_seats(Path(root), require_session=True)
    claimed: set[int] = set()
    chairs: list[dict[str, Any]] = []
    for s in seats:
        sid = s["session_id"]
        harness = canonical_harness_id(s.get("to")) or str(s.get("to") or "")
        tokens = [t for t in (s.get("resume"), s.get("vendor_session_id")) if isinstance(t, str) and t.strip()]
        found: list[dict[str, Any]] = []
        for p in procs:
            cmd = str(p.get("cmdline") or "")
            exe = _exe_harness(cmd)
            if any(t in cmd for t in tokens):
                found.append({"pid": p["pid"], "via": "token", "exe": exe or harness})
                claimed.add(p["pid"])
            elif exe == harness and _same_path(p.get("cwd"), s.get("worktree")):
                found.append({"pid": p["pid"], "via": "cwd", "exe": exe})
                claimed.add(p["pid"])
        chairs.append({
            "session_id": sid, "harness": harness, "worktree": s.get("worktree"),
            "live": bool(found), "bodies": found, "duplicate": len(found) > 1,
            "close": "managed-or-manual" if found else None,
        })
    unassigned = []
    for p in procs:
        exe = _exe_harness(str(p.get("cmdline") or ""))
        if exe and p["pid"] not in claimed:
            unassigned.append({"pid": p["pid"], "harness": exe, "cwd": p.get("cwd"), "close": "manual-close-required"})
    return {"ok": True, "chairs": chairs, "unassigned": unassigned}


def bodies(root: Path, enumerate_fn: Callable[[], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    fn = enumerate_fn or enumerate_processes
    try:
        procs = fn()
        source = "cim" if os.name == "nt" else "ps"
    except (OSError, subprocess.SubprocessError, ValueError):
        procs, source = [], None
    out = match_processes(Path(root), procs)
    out["source"] = source
    out["cwd_visible"] = os.name != "nt"
    return out


_TEST_PROCS: list[dict[str, Any]] | None = None   # test seam for the CLI path
_TEST_PID: int | None = None


def identify(root: Path, pid: int | None = None, procs: list[dict[str, Any]] | None = None,
             cwd: str | None = None) -> dict[str, Any]:
    """Which chair is the CALLER? Detect -> identify -> only then send.

    Walks the caller's ancestry (shell -> harness) in the process table. A
    chair's vendor token in an ancestor's command line wins (via "token");
    else an ancestor harness exe plus cwd == a chair's worktree (via "cwd");
    else null with an `ask` (join, or seat this worktree). Never a token in
    the result."""
    root = Path(root)
    procs = procs if procs is not None else (_TEST_PROCS if _TEST_PROCS is not None else _safe_enumerate())
    me = pid if pid is not None else (_TEST_PID if _TEST_PID is not None else os.getpid())
    here = cwd if cwd is not None else os.getcwd()
    by_pid = {p["pid"]: p for p in procs}
    chain: list[dict[str, Any]] = []
    cur = by_pid.get(me)
    hops = 0
    while cur is not None and hops < 32:
        chain.append(cur)
        cur = by_pid.get(cur.get("ppid"))
        hops += 1
    seats = list_seats(root, require_session=True)
    for p in chain:
        cmd = str(p.get("cmdline") or "")
        for s in seats:
            toks = [t for t in (s.get("resume"), s.get("vendor_session_id")) if isinstance(t, str) and t.strip()]
            if any(t in cmd for t in toks):
                return {"ok": True, "chair": s["session_id"], "via": "token", "harness": s.get("to"),
                        "harness_pid": p["pid"], "on_thread": True}
    for p in chain:
        exe = _exe_harness(str(p.get("cmdline") or ""))
        if not exe:
            continue
        for s in seats:
            if canonical_harness_id(s.get("to")) == exe and _same_path(here, s.get("worktree")):
                return {"ok": True, "chair": s["session_id"], "via": "cwd", "harness": s.get("to"),
                        "harness_pid": p["pid"], "on_thread": True}
    return {"ok": False, "chair": None, "via": None, "harness": None, "harness_pid": None, "on_thread": False,
            "ask": "no chair on this thread matches your body: join (python -m convoy --root " + str(root) +
                   " join --to <harness> --worktree " + str(here) + ") or seat this worktree, then retry"}


def _safe_enumerate() -> list[dict[str, Any]]:
    try:
        return enumerate_processes()
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def chair_live(root: Path, session_id: str, procs: list[dict[str, Any]] | None = None) -> bool:
    view = match_processes(Path(root), procs) if procs is not None else bodies(Path(root))
    return any(c["session_id"] == session_id and c["live"] for c in view["chairs"])
