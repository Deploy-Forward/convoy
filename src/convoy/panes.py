"""panes: every body of every neuron in a session, from the OS process table.

Marco 2026-09-03: "you should be able to see all associated panes in a
session; within a session you should be able to close, identify, or
understand what is occurring; ensure this exists across all neurons."

The registry only knows what Convoy launched. A neuron opened by hand, by a
vendor picker, or by another tool is invisible to it — and that blindness
produced a second body on a live codex thread today (codex refused: "already
has an active writer"). So liveness here comes from the process table:

  via "token"    — the chair's vendor token appears in a process command line
                   (portable: Windows CIM, Linux /proc, macOS ps).
  via "worktree" — the chair's worktree path appears in the command line
                   (grok `--agent <worktree>/.grok/...`, `--cwd`, etc.); this
                   is the Windows substitute for cwd.
  via "cwd"      — the process cwd equals the chair's worktree and the exe is
                   that chair's harness (Linux /proc, macOS lsof; Windows
                   exposes no cwd from stdlib, so that rung is null there).
  unassigned     — a harness process Convoy cannot place. Listed with pid and
                   exe, never hidden, so a human can identify it.

Helper processes are folded away: a vendor's pty host, daemon, app-server,
MCP child, or Electron utility is not a body; and a matched process whose
ancestor already matched the same chair is the same body, not a duplicate.

The view never prints a token: bodies say via, pid, exe. Close stays what it
is: managed panes close through the consented pane host; an unmanaged body
is `manual-close-required` with its pid shown.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .cmd import quiet_spawn_kwargs
from typing import Any, Callable

from .cmd import convoy_root_command
from .convoy import list_seats, read_id, read_thread
from .index import find_root
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

# Command-line fragments that mark a helper, not a body.
_HELPER_MARKS = ("--type=", "daemon run", "--bg-pty-host", "app-server", "mcp-server", " mcp ",
                 "--mcp", "language-server", "crashpad", "--utility")


def enumerate_processes() -> list[dict[str, Any]]:
    """{pid, ppid, cmdline, cwd|None} for every process the OS will show.
    Raises on failure; callers turn that into source=null + error."""
    if os.name == "nt":
        return _enumerate_windows()
    if sys.platform.startswith("linux") and Path("/proc").is_dir():
        return _enumerate_proc()
    return _enumerate_ps()


def _enumerate_windows() -> list[dict[str, Any]]:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        raise OSError("neither powershell nor pwsh on PATH")
    # The encoding set can throw on a redirected console; CIM can answer
    # "Call cancelled" transiently under load (seen live 2026-09-03). Guard
    # the first, retry the second once, and put stderr on the error.
    # -OperationTimeoutSec: without it CIM answered "Call cancelled"
    # (0x80041032) on a loaded host with ~1000 processes (live 2026-09-03).
    ps = ("try { [Console]::OutputEncoding=[Text.Encoding]::UTF8 } catch { }; "
          "Get-CimInstance Win32_Process -OperationTimeoutSec 120 "
          "| Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
    last: Exception | None = None
    out = ""
    for attempt in range(3):
        if attempt:
            time.sleep(1.0)
        proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", ps],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150,
                              **quiet_spawn_kwargs())
        if proc.returncode == 0 and proc.stdout.strip():
            out = proc.stdout
            last = None
            break
        last = OSError("powershell exit " + str(proc.returncode) + ": " + (proc.stderr or "").strip()[-300:])
    if last is not None:
        raise last
    data = json.loads(out or "[]")
    if isinstance(data, dict):
        data = [data]
    return [{"pid": int(d.get("ProcessId") or 0), "ppid": int(d.get("ParentProcessId") or 0),
             "cmdline": str(d.get("CommandLine") or ""), "cwd": None} for d in data]


def _enumerate_proc() -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open("/proc/" + entry + "/stat", "r", encoding="utf-8", errors="replace") as f:
                stat = f.read()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            with open("/proc/" + entry + "/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            try:
                cwd = os.readlink("/proc/" + entry + "/cwd")
            except OSError:
                cwd = None
        except (OSError, ValueError, IndexError):
            continue
        procs.append({"pid": pid, "ppid": ppid, "cmdline": cmd, "cwd": cwd})
    return procs


def _enumerate_ps() -> list[dict[str, Any]]:
    out = subprocess.run(["ps", "-eww", "-o", "pid=,ppid=,args="], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=20, check=True, **quiet_spawn_kwargs()).stdout
    procs: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        procs.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                      "cmdline": parts[2] if len(parts) > 2 else "", "cwd": None})
    if sys.platform == "darwin":
        _fill_cwd_lsof(procs)
    return procs


def _fill_cwd_lsof(procs: list[dict[str, Any]]) -> None:
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20, **quiet_spawn_kwargs()).stdout
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
        base = os.path.basename(tok.replace("\\", "/")).lower()
        for hid, names in HARNESS_EXES.items():
            if base in names:
                return hid
    return None


def _is_helper(cmdline: str) -> bool:
    low = " " + cmdline.lower() + " "
    return any(mark in low for mark in _HELPER_MARKS)


def _norm(p: Any) -> str | None:
    if not p:
        return None
    try:
        s = os.path.realpath(str(p))
    except (OSError, ValueError):
        s = os.path.normpath(str(p))
    s = os.path.normcase(s)
    if sys.platform == "darwin":
        s = s.casefold()
    return s


def _same_path(a: Any, b: Any) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na and nb and na == nb)


def _mentions_path(cmdline: str, worktree: Any) -> bool:
    """Does the command line carry the worktree path (any separator/case)?"""
    if not worktree or not cmdline:
        return False
    w = os.path.normcase(str(worktree)).replace("\\", "/").rstrip("/")
    c = os.path.normcase(cmdline).replace("\\", "/")
    return bool(w) and (w + "/" in c or c.endswith(w) or (w + " ") in c or (w + '"') in c)


def _collapse(found: list[dict[str, Any]], by_pid: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """One body per ancestor chain: drop a match whose ancestor also matched."""
    pids = {b["pid"] for b in found}
    out = []
    for b in found:
        cur = by_pid.get(b["pid"])
        hops, dup = 0, False
        while cur is not None and hops < 32:
            cur = by_pid.get(cur.get("ppid"))
            hops += 1
            if cur is not None and cur["pid"] in pids:
                dup = True
                break
        if not dup:
            out.append(b)
    return out


def match_processes(root: Path, procs: list[dict[str, Any]]) -> dict[str, Any]:
    seats = list_seats(Path(root), require_session=True)
    by_pid = {p["pid"]: p for p in procs}
    bodies_only = [p for p in procs if not _is_helper(str(p.get("cmdline") or ""))]
    claimed: set[int] = set()
    chairs: list[dict[str, Any]] = []
    for s in seats:
        sid = s["session_id"]
        harness = canonical_harness_id(s.get("to")) or str(s.get("to") or "")
        tokens = [t for t in (s.get("resume"), s.get("vendor_session_id")) if isinstance(t, str) and t.strip()]
        found: list[dict[str, Any]] = []
        for p in bodies_only:
            cmd = str(p.get("cmdline") or "")
            exe = _exe_harness(cmd)
            if any(t in cmd for t in tokens):
                found.append({"pid": p["pid"], "via": "token", "exe": exe or harness})
            elif exe == harness and _mentions_path(cmd, s.get("worktree")):
                found.append({"pid": p["pid"], "via": "worktree", "exe": exe})
            elif exe == harness and _same_path(p.get("cwd"), s.get("worktree")):
                found.append({"pid": p["pid"], "via": "cwd", "exe": exe})
        found = _collapse(found, by_pid)
        for b in found:
            claimed.add(b["pid"])
        chairs.append({
            "session_id": sid, "harness": harness, "worktree": s.get("worktree"),
            "live": bool(found) or None, "bodies": found, "duplicate": len(found) > 1,
            "close": "managed-or-manual" if found else None,
        })
    # a helper whose ancestor is claimed belongs to that body; everything else
    # that runs a harness exe and is nobody's is unassigned.
    unassigned = []
    for p in bodies_only:
        exe = _exe_harness(str(p.get("cmdline") or ""))
        if not exe or p["pid"] in claimed:
            continue
        cur, hops, owned = by_pid.get(p.get("ppid")), 0, False
        while cur is not None and hops < 32:
            if cur["pid"] in claimed:
                owned = True
                break
            cur = by_pid.get(cur.get("ppid"))
            hops += 1
        if not owned:
            unassigned.append({"pid": p["pid"], "harness": exe, "cwd": p.get("cwd"), "close": "manual-close-required"})
    # A chair with no matched body is only NOT LIVE when no process of its
    # harness is running unplaced. If unplaceable candidates exist, liveness
    # is UNKNOWN (null), never false: on Windows a codex pane carries neither
    # a token nor its worktree in the command line and the OS exposes no cwd,
    # so eight live codex processes sat beside a chair reporting live=false
    # (live 2026-09-03 — and this session reported that as "not live" to the
    # user, which was inventing a fact).
    by_harness: dict[str, int] = {}
    for u in unassigned:
        by_harness[u["harness"]] = by_harness.get(u["harness"], 0) + 1
    for c in chairs:
        if c["live"]:
            c["live_reason"] = "matched " + str(len(c["bodies"])) + " body/bodies"
            continue
        n = by_harness.get(c["harness"], 0)
        if n:
            c["live"] = None
            c["live_reason"] = (str(n) + " " + c["harness"] + " process(es) are running but could not be "
                                "placed (no token or worktree in the command line" +
                                ("; this OS exposes no process cwd" if os.name == "nt" else "") +
                                "): liveness unknown, not false")
        else:
            c["live"] = False
            c["live_reason"] = "no " + c["harness"] + " process is running"
    return {"ok": True, "chairs": chairs, "unassigned": unassigned}


def bodies(root: Path, enumerate_fn: Callable[[], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    fn = enumerate_fn or enumerate_processes
    error = None
    try:
        procs = fn()
        source = ("cim" if os.name == "nt" else "proc" if sys.platform.startswith("linux") else "ps")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        procs, source, error = [], None, type(e).__name__ + ": " + str(e)
    out = match_processes(Path(root), procs)
    out["source"] = source
    out["error"] = error
    out["cwd_visible"] = source in ("proc", "ps")
    return out


_TEST_PROCS: list[dict[str, Any]] | None = None   # test seam for the CLI path
_TEST_PID: int | None = None


def identify(root: Path, pid: int | None = None, procs: list[dict[str, Any]] | None = None,
             cwd: str | None = None) -> dict[str, Any]:
    """Which chair is the CALLER? Detect -> identify -> only then send.

    Walks the caller's ancestry (shell -> harness) in the process table. A
    chair's vendor token in an ancestor's command line wins (via "token");
    else an ancestor harness exe whose command line names a chair's worktree
    (via "worktree"); else an ancestor harness exe plus cwd == worktree (via
    "cwd"); else null with an `ask`. Never a token in the result."""
    root = Path(root)
    enum_error = None
    if procs is not None:
        pass
    elif _TEST_PROCS is not None:
        procs = _TEST_PROCS
    else:
        procs, enum_error = _safe_enumerate()
    me = pid if pid is not None else (_TEST_PID if _TEST_PID is not None else os.getpid())
    here = cwd if cwd is not None else os.getcwd()
    # Which thread does the cwd walk up to, and is it this root's thread? A
    # worktree with its own .convoy from another thread silently answers for
    # that thread on every call made without --root.
    root_thread = read_thread(root)
    root_id = read_id(root)
    cwd_root = find_root(here)
    cwd_id = read_id(cwd_root) if cwd_root else None
    cwd_thread = read_thread(cwd_root) if cwd_root else None
    conflict = bool(cwd_id) and cwd_id != root_id
    ctx = {"root_thread": root_thread, "cwd_thread": cwd_thread, "conflict": conflict}
    if conflict:
        ctx["ask"] = ("your cwd walks up to thread " + str(cwd_thread) + " (" + str(cwd_id) + ") but this root is " +
                      str(root_thread) + " (" + str(root_id) + "): always pass --root " + str(root) +
                      " from this worktree, or move the chair to a worktree without a foreign .convoy")
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
                        "harness_pid": p["pid"], "on_thread": True, **ctx}
    for p in chain:
        cmd = str(p.get("cmdline") or "")
        exe = _exe_harness(cmd)
        if not exe:
            continue
        for s in seats:
            if canonical_harness_id(s.get("to")) == exe and _mentions_path(cmd, s.get("worktree")):
                return {"ok": True, "chair": s["session_id"], "via": "worktree", "harness": s.get("to"),
                        "harness_pid": p["pid"], "on_thread": True, **ctx}
    for p in chain:
        exe = _exe_harness(str(p.get("cmdline") or ""))
        if not exe:
            continue
        for s in seats:
            if canonical_harness_id(s.get("to")) == exe and _same_path(here, s.get("worktree")):
                return {"ok": True, "chair": s["session_id"], "via": "cwd", "harness": s.get("to"),
                        "harness_pid": p["pid"], "on_thread": True, **ctx}
    out = {"ok": False, "chair": None, "via": None, "harness": None, "harness_pid": None, "on_thread": False,
           "ask": "no chair on this thread matches your body: join (" + convoy_root_command(root) +
                  " join --to <harness> --worktree " + str(here) + ") or seat this worktree, then retry"}
    out.update(ctx)   # a conflict ask replaces the join ask: fix the root first
    if enum_error:
        out["error"] = enum_error
        out["ask"] = "process table unreadable (" + enum_error + "); retry whoami"
    return out


def _safe_enumerate() -> tuple[list[dict[str, Any]], str | None]:
    try:
        return enumerate_processes(), None
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return [], type(e).__name__ + ": " + str(e)


def chair_live(root: Path, session_id: str, procs: list[dict[str, Any]] | None = None) -> bool:
    """True when the chair is live OR its liveness is UNKNOWN. Callers are
    no-steal guards: refusing on unknown is the safe answer, and inventing
    `not live` is how a second body got launched on a live codex thread
    (2026-09-03). Use chair_liveness() when you need the three states."""
    return chair_liveness(root, session_id, procs) is not False


def chair_liveness(root: Path, session_id: str, procs: list[dict[str, Any]] | None = None) -> bool | None:
    """True / False / None(unknown) for one chair."""
    view = match_processes(Path(root), procs) if procs is not None else bodies(Path(root))
    for c in view["chairs"]:
        if c["session_id"] == session_id:
            return c["live"]
    return False
