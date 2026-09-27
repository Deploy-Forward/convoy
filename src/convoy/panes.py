"""panes: every body of every neuron in a session, from the OS process table.

The goal: see every pane associated with a session, and within it close,
identify, or understand what is occurring, for every neuron.

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
from .pane_host import read_host_records
from .layer import utc_now
from .pulse import chair_reachable, pulse_is_fresh, read_pulse
from .wait import read_wait_file

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


def _argv_tokens(cmdline: str) -> list[str]:
    """Split a command line into arguments, honouring double quotes only.

    Backslashes stay literal: these are Windows paths, not POSIX escapes, so
    shlex is the wrong tool here.
    """
    out: list[str] = []
    current: list[str] = []
    quoted = False
    for ch in cmdline:
        if ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            if current:
                out.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        out.append("".join(current))
    return out


def _path_key(value: Any) -> str:
    return os.path.normcase(str(value)).replace("\\", "/").rstrip("/")


def _mentions_path(cmdline: str, worktree: Any) -> bool:
    """Does an ARGUMENT name the worktree - the whole path, never a substring?

    A plain `worktree in cmdline` test is not enough: a crew boot prompt
    carries the thread root inside one quoted argument, so a crew pane would
    answer `whoami` as the root's chair, and `--as-me` would author from it. An argument names the
    worktree when the argument IS that path or sits under it (grok's
    `--agent <worktree>/.grok/...`); text that merely mentions it does not.

    argv[0] is dropped: a harness installed inside a worktree is not a claim
    to that worktree's chair.
    """
    if not worktree or not cmdline:
        return False
    w = _path_key(worktree)
    if not w:
        return False
    for arg in _argv_tokens(cmdline)[1:]:
        a = _path_key(arg)
        if a == w or a.startswith(w + "/"):
            return True
    return False


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


def match_processes(root: Path, procs: list[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
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
        # Rung 'pid': the body the pane host recorded on the seat. A pid
        # someone wrote down beats any substring of a command line, and it is
        # the only rung that works for a codex pane on Windows, which carries
        # neither its token nor its worktree in the command line.
        recorded_pid = s.get("harness_pid")
        recorded_gone = str(s.get("process_state") or "") == "exited"
        pid_value: int | None = None
        try:
            pid_value = int(recorded_pid) if recorded_pid is not None else None
        except (TypeError, ValueError):
            pid_value = None
        if pid_value is not None and not recorded_gone and pid_value in by_pid:
            cmd = str(by_pid[pid_value].get("cmdline") or "")
            found.append({"pid": pid_value, "via": "pid", "exe": _exe_harness(cmd) or harness})
        if not found:
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
        # Rung 'pulse': something spoke for this chair recently. It names
        # no pid, so it is not a body - but it is a recorded answer, and a
        # recorded answer is never 'unknown'.
        pulse = read_pulse(root, sid)
        chairs.append({
            "session_id": sid, "harness": harness, "worktree": s.get("worktree"),
            "live": bool(found) or None, "bodies": found, "duplicate": len(found) > 1,
            "close": "managed-or-manual" if found else None,
            "recorded_pid": pid_value if not recorded_gone else None,
            "pulse": {"ts": pulse.get("ts"), "pulse_source": pulse.get("pulse_source"),
                      "incarnation": pulse.get("incarnation")} if pulse else None,
            "pulse_fresh": pulse_is_fresh(pulse) if pulse else None,
            # Who, if anyone, is listening between turns. A waiter the OS
            # kills leaves every surface showing the chair as normal, because
            # nothing asks. 'waiter-dead' is a word
            # a human can read; silence is something they have to interpret.
            "reachable": chair_reachable(pulse, read_wait_file(root, sid), now or utc_now()),
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
            # live is bool(found) or None, so a truthy live has bodies.
            c["live_reason"] = ("matched " + str(len(c["bodies"])) + " body/bodies by " +
                                str(c["bodies"][0]["via"]))
            continue
        if c["pulse_fresh"]:
            c["live"] = True
            c["live_reason"] = ("pulse from " + str((c["pulse"] or {}).get("pulse_source")) +
                                " at " + str((c["pulse"] or {}).get("ts")))
            continue
        # A record that says the body is gone is an answer. 'Unknown, not
        # false' exists for chairs nobody ever wrote anything down about; it
        # must not outrank a pid the host recorded or a pulse that stopped.
        if c["recorded_pid"] is not None:
            c["live"] = False
            c["live_reason"] = ("the recorded body (pid " + str(c["recorded_pid"]) +
                                ") is not in the process table")
            continue
        if c["pulse"] is not None:
            c["live"] = False
            c["live_reason"] = ("the chair's pulse is stale: last " +
                                str((c["pulse"] or {}).get("pulse_source")) + " at " +
                                str((c["pulse"] or {}).get("ts")))
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
    # Rung 'pane-host': a pid someone wrote down at launch. It beats every
    # path rung because a command line can carry any path a prompt mentions,
    # and the pane host's record cannot be written by the pane's own argv.
    known = {s["session_id"]: s for s in seats}
    by_recorded_pid: dict[int, str] = {}
    for record in read_host_records(root):
        sid = str(record.get("session_id") or "")
        # The OS reuses pids: a record whose child has exited is history, not
        # a claim on whatever holds that pid now.
        if sid not in known or str(record.get("status") or "") != "running":
            continue
        for key in ("child_pid", "host_pid"):
            try:
                value = int(record.get(key))
            except (TypeError, ValueError):
                continue
            by_recorded_pid.setdefault(value, sid)
    pid_hit: tuple[str, int] | None = None
    for p in chain:
        sid = by_recorded_pid.get(p["pid"])
        if sid:
            pid_hit = (sid, p["pid"])
            break
    path_hit: tuple[str, str, int] | None = None
    for p in chain:
        cmd = str(p.get("cmdline") or "")
        exe = _exe_harness(cmd)
        if not exe:
            continue
        for s in seats:
            if canonical_harness_id(s.get("to")) == exe and _mentions_path(cmd, s.get("worktree")):
                path_hit = (s["session_id"], "worktree", p["pid"])
                break
        if path_hit:
            break
    if path_hit is None:
        for p in chain:
            exe = _exe_harness(str(p.get("cmdline") or ""))
            if not exe:
                continue
            for s in seats:
                if canonical_harness_id(s.get("to")) == exe and _same_path(here, s.get("worktree")):
                    path_hit = (s["session_id"], "cwd", p["pid"])
                    break
            if path_hit:
                break
    # Two records disagreeing is not a tie to break: it is a fact to report.
    # Answering the path's chair here is how a crew pane authored as the lead.
    if pid_hit and path_hit and pid_hit[0] != path_hit[0]:
        out = {"ok": False, "chair": None, "via": "conflict", "harness": None, "harness_pid": None,
               "on_thread": True, "chairs": [pid_hit[0], path_hit[0]],
               "ask": ("two records disagree about your body: the pane-host record says " + pid_hit[0] +
                       " (pid " + str(pid_hit[1]) + ") and the " + path_hit[1] + " path says " + path_hit[0] +
                       "; pass the chair explicitly and fix the stale record before authoring")}
        out.update(ctx)
        return out
    if pid_hit:
        seat_row = known[pid_hit[0]]
        return {"ok": True, "chair": pid_hit[0], "via": "pane-host", "harness": seat_row.get("to"),
                "harness_pid": pid_hit[1], "on_thread": True, **ctx}
    if path_hit:
        seat_row = known[path_hit[0]]
        return {"ok": True, "chair": path_hit[0], "via": path_hit[1], "harness": seat_row.get("to"),
                "harness_pid": path_hit[2], "on_thread": True, **ctx}
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
