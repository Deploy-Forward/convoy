"""panes: every body of every neuron in a session, from the OS process table.

The goal: see every pane associated with a session, and within it close,
identify, or understand what is occurring, for every neuron.

The registry only knows what Convoy launched. A neuron opened by hand, by a
vendor picker, or by another tool is invisible to it — and that blindness
produced a second body on a live codex thread today (codex refused: "already
has an active writer"). So liveness here comes from the process table:

  via "token"    — the chair's native id appears in a possible body command
                   line, including legacy permissive matches. This no-steal
                   hint is not process-ownership proof.
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
from collections.abc import Mapping
from pathlib import Path
from .cmd import quiet_spawn_kwargs
from typing import Any, Callable

from .cmd import convoy_root_command
from .convoy import broad_worktree, list_seats, read_id, read_thread
from .index import find_root
from .harness_contract import canonical_harness_id
from .pane_host import read_host_records, record_matches_start
from .layer import utc_now
from .pulse import chair_reachable, pulse_is_fresh, read_pulse
from .wait import listening_wait_file

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


def enumerate_processes(*, attempts: int = 3, timeout: float = 150) -> list[dict[str, Any]]:
    """{pid, ppid, cmdline, cwd|None, started|None} for every process the OS will show.
    started is the process's creation time (Windows FILETIME, Linux start tick, other POSIX
    Unix seconds), None when it cannot be read; it is what tells a parent from a process that
    reused a dead parent's pid.
    Raises on failure; callers turn that into source=null + error. attempts and
    timeout bound the external call (seconds); a caller on a send's path passes
    one short attempt so a slow process table can never hold the send."""
    if os.name == "nt":
        return _enumerate_windows(attempts=attempts, timeout=timeout)
    if sys.platform.startswith("linux") and Path("/proc").is_dir():
        return _enumerate_proc()
    return _enumerate_ps(timeout=min(float(timeout), 20.0))


def _enumerate_windows(*, attempts: int = 3, timeout: float = 150) -> list[dict[str, Any]]:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        raise OSError("neither powershell nor pwsh on PATH")
    # The encoding set can throw on a redirected console; CIM can answer
    # "Call cancelled" transiently under load. Guard
    # the first, retry the second once, and put stderr on the error.
    # -OperationTimeoutSec: without it CIM answered "Call cancelled"
    # (0x80041032) on a host with ~1000 processes.
    ps = ("try { [Console]::OutputEncoding=[Text.Encoding]::UTF8 } catch { }; "
          "Get-CimInstance Win32_Process -OperationTimeoutSec " + str(max(1, min(120, int(timeout)))) + " "
          "| Select-Object ProcessId,ParentProcessId,CommandLine,"
          "@{n='Started';e={if ($_.CreationDate) { $_.CreationDate.ToFileTime() } else { $null }}} "
          "| ConvertTo-Json -Compress")
    last: Exception | None = None
    out = ""
    for attempt in range(max(1, int(attempts))):
        if attempt:
            time.sleep(1.0)
        proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", ps],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
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
             "cmdline": str(d.get("CommandLine") or ""), "cwd": None,
             "started": _int_or_none(d.get("Started"))} for d in data]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _parse_proc_stat(stat: str) -> tuple[int, int | None]:
    """(ppid, start tick) from /proc/<pid>/stat. The command name may hold spaces and
    parentheses, so fields are counted from the last ')': state is field 3, ppid field 4,
    starttime field 22."""
    fields = stat[stat.rindex(")") + 2:].split()
    return int(fields[1]), (_int_or_none(fields[19]) if len(fields) > 19 else None)


def _enumerate_proc() -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open("/proc/" + entry + "/stat", "r", encoding="utf-8", errors="replace") as f:
                stat = f.read()
            ppid, started = _parse_proc_stat(stat)
            with open("/proc/" + entry + "/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            try:
                cwd = os.readlink("/proc/" + entry + "/cwd")
            except OSError:
                cwd = None
        except (OSError, ValueError, IndexError):
            continue
        procs.append({"pid": pid, "ppid": ppid, "cmdline": cmd, "cwd": cwd, "started": started})
    return procs


def _enumerate_ps(*, timeout: float = 20) -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    try:
        # lstart is five words ("Mon Oct  6 10:00:00 2026") in the C locale.
        out = subprocess.run(["ps", "-eww", "-o", "pid=,ppid=,lstart=,args="], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout, check=True,
                             env={**os.environ, "LC_ALL": "C"}, **quiet_spawn_kwargs()).stdout
        for line in out.splitlines():
            parts = line.strip().split(None, 7)
            if len(parts) < 7:
                continue
            try:
                started: int | None = int(time.mktime(time.strptime(" ".join(parts[2:7]),
                                                                    "%a %b %d %H:%M:%S %Y")))
            except (ValueError, OverflowError):
                started = None
            procs.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                          "cmdline": parts[7] if len(parts) > 7 else "", "cwd": None, "started": started})
    except (OSError, subprocess.SubprocessError, ValueError):
        # A ps without lstart: the table carries no start times at all (no "started" key),
        # and the walk falls back to its cycle check alone.
        procs = []
        out = subprocess.run(["ps", "-eww", "-o", "pid=,ppid=,args="], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout, check=True,
                             **quiet_spawn_kwargs()).stdout
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
    toks = _argv_tokens(cmdline)
    if not toks:
        return None
    executable = os.path.basename(toks[0].replace("\\", "/")).lower()
    # A native harness is argv[0]. The one evidenced wrapper is node running
    # a harness .js entrypoint; arbitrary later words may be shell commands or
    # prompt text, never evidence of which process this is.
    if executable in ("node", "node.exe") and len(toks) > 1:
        executable = os.path.basename(toks[1].replace("\\", "/")).lower()
        if not executable.endswith(".js"):
            return None
    for hid, names in HARNESS_EXES.items():
        if executable in names:
            return hid
    return None


def _liveness_harness(cmdline: str) -> str | None:
    """Conservative possible body for no-steal checks, not identity proof.

    A shell wrapper can keep a real harness body alive without being that
    harness itself. Identity must use _exe_harness; liveness must not turn a
    wrapper the old process matcher saw into a proven dead chair.
    """
    # Keep the base's quote-stripping window: a shell may carry the real
    # harness command as one quoted argument. This is only a no-steal hint.
    for tok in cmdline.replace('"', ' ').split()[:3]:
        executable = os.path.basename(tok.replace("\\", "/")).lower()
        for hid, names in HARNESS_EXES.items():
            if executable in names:
                return hid
    return None


def _liveness_token_match(cmdline: str, tokens: list[str]) -> bool:
    """Union of exact and legacy permissive hints for the no-steal guard.

    A false positive blocks a duplicate launch; a false negative can launch
    a second writer. Identity never uses this matcher.
    """
    args = _argv_tokens(cmdline)
    return any(t in cmdline or t in args or any(arg == "--resume=" + t for arg in args)
               for t in tokens)


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


# Codex options that take a value: the value is never a subcommand, a prompt or a native id.
CODEX_VALUE_FLAGS = frozenset({"-m", "--model", "-c", "--config", "-C", "--cd",
                               "-a", "--ask-for-approval", "--enable", "--disable",
                               "--remote", "--remote-auth-token-env", "-i", "--image",
                               "--local-provider", "-p", "--profile", "-s", "--sandbox",
                               "--add-dir"})
# A hook reads the process table at most once, in one attempt: a slow table must never hold a
# tool call or outlive the plugin's 5 s Stop timeout. The inbox hook (PreToolUse/PostToolUse)
# holds a tool call, so 2 s. The Stop hook's one read is shared by identity and the stamp gate;
# real reads take 1.7-2.0 s, so 3 s (about 1.5x the slowest). The budget must leave room for
# interpreter start and the git snapshot under the 5 s timeout: at 4 s a timed-out read put the
# heartbeat near 4.5 s; at 3 s the worst case is near 3.6 s. A fixed constant, never derived
# from elapsed time.
HOOK_PROBE_TIMEOUT_S = 2.0
STOP_PROBE_TIMEOUT_S = 3.0


def _native_resume_ids(cmdline: str, harness: str) -> set[str]:
    """Exact native ids passed in the harness's evidenced continuation form.

    A prompt that quotes ``--resume id`` is one argument, not two. Codex's
    ``resume`` is a subcommand, so it must be the first non-option word rather
    than text later in an initial prompt. No substring of an id is evidence.
    """
    argv = _argv_tokens(cmdline)
    if not argv or _exe_harness(cmdline) != harness:
        return set()
    start = 2 if os.path.basename(argv[0].replace("\\", "/")).lower() in ("node", "node.exe") else 1
    args = argv[start:]
    if harness == "codex":
        # Only evidenced option forms may be skipped for identity. An unknown
        # switch does not let a later prompt or value become a native id.
        value_flags = CODEX_VALUE_FLAGS
        boolean_flags = {"--approve-for-me", "--dangerously-bypass-approvals-and-sandbox",
                         "--dangerously-bypass-hook-trust", "--search", "--no-alt-screen",
                         "--no-daemon", "--worktree", "--oss", "--strict-config",
                         "--include-non-interactive", "--all"}
        def skip_options(index: int) -> int | None:
            while index < len(args) and args[index].startswith("-"):
                arg = args[index]
                if arg in value_flags:
                    if index + 1 >= len(args):
                        return None
                    index += 2
                elif arg in boolean_flags:
                    index += 1
                elif arg.split("=", 1)[0] in value_flags and "=" in arg:
                    index += 1
                else:
                    return None
            return index
        i = skip_options(0)
        if i is None or i >= len(args) or args[i] != "resume":
            return set()
        i = skip_options(i + 1)
        if i is None or i >= len(args):
            return set()
        return {args[i]} if args[i] else set()
    flag = "--conversation" if harness == "agy" else "--resume"
    found: set[str] = set()
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args) and args[i + 1] and not args[i + 1].startswith("-"):
            found.add(args[i + 1])
        elif harness == "claude" and arg == "-r" and i + 1 < len(args) and args[i + 1] and not args[i + 1].startswith("-"):
            found.add(args[i + 1])
        elif harness == "claude" and arg.startswith("--resume=") and arg != "--resume=":
            found.add(arg.split("=", 1)[1])
        elif harness == "cursor-agent" and arg.startswith("--resume=") and arg != "--resume=":
            found.add(arg.split("=", 1)[1])
    return found


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


ANCESTRY_HOPS = 32


def walk_ancestry(by_pid: Mapping[int, dict[str, Any]], pid: Any,
                  *, limit: int = ANCESTRY_HOPS) -> list[dict[str, Any]]:
    """The process at pid and its ancestors, nearest first.

    The OS reuses pids, so a ppid can name a process that started after its child: the real
    parent died and an unrelated process took its number. That process is not an ancestor.
    The walk stops at a repeated pid (a cycle), at a parent that started after its child, and
    at a start time that cannot be read; each ends the chain, which errs toward "no further
    ancestor" and never toward a second harness outside the caller. A table that carries no
    start times at all (no "started" key) gets the cycle check alone."""
    chain: list[dict[str, Any]] = []
    seen: set[Any] = set()
    cur = by_pid.get(pid) if pid is not None else None
    while cur is not None and len(chain) < limit and cur.get("pid") not in seen:
        chain.append(cur)
        seen.add(cur.get("pid"))
        parent = by_pid.get(cur.get("ppid"))
        if parent is None or parent.get("pid") in seen:
            break
        if "started" in cur and "started" in parent:
            born, parent_born = cur.get("started"), parent.get("started")
            if born is None or parent_born is None:
                break
            try:
                if int(parent_born) > int(born):
                    break
            except (TypeError, ValueError):
                break
        cur = parent
    return chain


def _record_names(by_pid: Mapping[int, dict[str, Any]], pid: int, started: Any, launched_at: Any) -> bool:
    """Does the table's process at pid match a record of it? A pid absent from the table, or
    without a readable start, is not evidence of reuse."""
    proc = by_pid.get(pid)
    if proc is None:
        return True
    return record_matches_start(proc.get("started"), started, launched_at)


def _collapse(found: list[dict[str, Any]], by_pid: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """One body per ancestor chain: drop a match whose ancestor also matched."""
    pids = {b["pid"] for b in found}
    return [b for b in found
            if not any(p["pid"] in pids for p in walk_ancestry(by_pid, b["pid"])[1:])]


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
        if (pid_value is not None and not recorded_gone and pid_value in by_pid and
                _record_names(by_pid, pid_value, s.get("harness_started"), s.get("launched_at"))):
            cmd = str(by_pid[pid_value].get("cmdline") or "")
            found.append({"pid": pid_value, "via": "pid", "exe": _liveness_harness(cmd) or harness})
        if not found:
            for p in bodies_only:
                cmd = str(p.get("cmdline") or "")
                exe = _liveness_harness(cmd)
                if _liveness_token_match(cmd, tokens):
                    found.append({"pid": p["pid"], "via": "token", "exe": exe})
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
            "reachable": chair_reachable(pulse, listening_wait_file(root, sid), now or utc_now()),
        })
    # a helper whose ancestor is claimed belongs to that body; everything else
    # that runs a harness exe and is nobody's is unassigned.
    unassigned = []
    for p in bodies_only:
        exe = _liveness_harness(str(p.get("cmdline") or ""))
        if not exe or p["pid"] in claimed:
            continue
        owned = any(a["pid"] in claimed for a in walk_ancestry(by_pid, p["pid"])[1:])
        if not owned:
            unassigned.append({"pid": p["pid"], "harness": exe, "cwd": p.get("cwd"), "close": "manual-close-required"})
    # A chair with no matched body is only NOT LIVE when no process of its
    # harness is running unplaced. If unplaceable candidates exist, liveness
    # is UNKNOWN (null), never false: on Windows a codex pane carries neither
    # a token nor its worktree in the command line and the OS exposes no cwd,
    # so live codex processes can sit beside a chair that would report
    # live=false; reporting that as "not live" would be inventing a fact.
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


# Every environment variable through which a harness proves its native session to
# Convoy (identify, attach, hook id stamps). The one list: the test guard clears these
# for a whole run, and a test asserts no session variable the code reads is missing.
NATIVE_SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "GROK_SESSION_ID")

_TEST_PROCS: list[dict[str, Any]] | None = None   # test seam for the CLI path
_TEST_PID: int | None = None


def _codex_subcommand(cmdline: str) -> str | None:
    """The first non-option word after a Codex executable (`exec`, `resume`, ...), or None. The
    value of a value-taking option (`-m o3`, `-c x=y`) is skipped, never read as the subcommand."""
    argv = _argv_tokens(cmdline)
    start = 2 if argv and os.path.basename(argv[0].replace("\\", "/")).lower() in ("node", "node.exe") else 1
    args = argv[start:]
    i = 0
    while i < len(args):
        if args[i] in CODEX_VALUE_FLAGS:
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i]
    return None


def _body_and_outer(chain: list[dict[str, Any]]) -> tuple[list[tuple[int, dict[str, Any], str]],
                                                           list[tuple[int, dict[str, Any], str]]]:
    """Split a caller's ancestry (nearest first) into its nearest harness body and the harness
    nodes outside it. A non-empty outer list is a nested harness: a child run by another body."""
    harness_nodes = [(i, p, _exe_harness(str(p.get("cmdline") or "")))
                     for i, p in enumerate(chain)]
    harness_nodes = [(i, p, h) for i, p, h in harness_nodes if h]
    body_nodes = harness_nodes[:1]
    for node in harness_nodes[1:]:
        if not body_nodes or node[2] != body_nodes[-1][2]:
            break
        near_cmd = str(body_nodes[-1][1].get("cmdline") or "")
        outer_cmd = str(node[1].get("cmdline") or "")
        near_ids = _native_resume_ids(near_cmd, node[2])
        outer_ids = _native_resume_ids(outer_cmd, node[2])
        # Codex's npm wrapper, vendored binary and app-server child can all
        # appear in one ancestry. Repeated equal resume ids are one body; a
        # bare Codex launcher pair or its app-server is also one body. A
        # Claude child with no id below a parent resuming another id is not.
        # A `codex exec` below a Codex that is not itself that exec is a
        # nested run (a review, a one-shot), never the same body.
        nested_exec = (node[2] == "codex" and _codex_subcommand(near_cmd) == "exec"
                       and _codex_subcommand(outer_cmd) != "exec")
        same_body = not nested_exec and ((bool(near_ids) and near_ids == outer_ids) or (
            node[2] == "codex" and (
                "app-server" in _argv_tokens(near_cmd)[1:] or
                (not near_ids and not outer_ids)
            )
        ))
        if not same_body:
            break
        body_nodes.append(node)
    return body_nodes, harness_nodes[len(body_nodes):]


def hook_body(pid: int | None = None, procs: list[dict[str, Any]] | None = None, *,
              read_error: str | None = None, timeout: float = HOOK_PROBE_TIMEOUT_S) -> dict[str, Any]:
    """Which harness body runs this hook process, read from its own ancestry.

    {harness, nested, error}: harness is the nearest harness body (None when no harness is an
    ancestor or the table is unavailable); nested is True when another harness body runs that
    one, as for a `codex exec` started by a Codex neuron. Never a chair claim.
    procs / read_error: the table, or the error, of a read this hook already made; given either,
    nothing is read again. Otherwise one attempt bounded by timeout."""
    error = None
    if read_error:
        return {"harness": None, "nested": None, "error": read_error}
    if procs is None:
        if _TEST_PROCS is not None:
            procs = _TEST_PROCS
        else:
            procs, error = _safe_enumerate(attempts=1, timeout=timeout)
    if error:
        return {"harness": None, "nested": None, "error": error}
    me = pid if pid is not None else (_TEST_PID if _TEST_PID is not None else os.getpid())
    by_pid = {p["pid"]: p for p in procs}
    body, outer = _body_and_outer(walk_ancestry(by_pid, me))
    return {"harness": body[0][2] if body else None, "nested": bool(outer), "error": None}


def identify(root: Path, pid: int | None = None, procs: list[dict[str, Any]] | None = None,
             cwd: str | None = None, env: Mapping[str, str] | None = None,
             *, allow_unseated: bool = False, explicit_root: bool = False) -> dict[str, Any]:
    """Which chair is the CALLER on this root? See _identify for the rungs.

    A session may sit on several threads, so acting on thread A with an explicit root from
    thread B's folder is normal. When the caller is proven on this root by environment or
    token, a cwd that walks into another thread is information, `cwd_thread_differs`
    ({cwd_thread, root_thread, hint}), never a conflict. Real disagreements (environment and
    token naming different chairs, or a path chair contradicting an environment chair on
    this root) still refuse with via=conflict. The relaxation needs an explicit root (the
    CLI's --root): an inferred root keeps the visible warning."""
    out = _identify(root, pid, procs, cwd, env, allow_unseated=allow_unseated)
    if explicit_root and out.get("ok") and out.get("via") in ("environment", "token") and out.get("conflict"):
        out["conflict"] = False
        out["cwd_thread_differs"] = {"cwd_thread": out.get("cwd_thread"), "root_thread": out.get("root_thread"),
                                     "hint": out.pop("ask", None)}
    return out


def _native_chair_elsewhere(root: Path, unrecorded: list[tuple[str, str, str]]) -> tuple[str, str] | None:
    """(thread, chair) of another thread where the caller's native id (not recorded on this
    root) is recorded as a chair, or None."""
    ids = {(h, i) for h, i, _via in unrecorded if i}
    if not ids:
        return None
    from .index import list_threads
    here = os.path.normcase(str(Path(root).resolve()))
    for thread in list_threads():
        if not thread.get("present") or not thread.get("root"):
            continue
        other = Path(thread["root"])
        try:
            if os.path.normcase(str(other.resolve())) == here:
                continue
            seats = list_seats(other, require_session=True)
        except (OSError, ValueError):
            continue
        for s in seats:
            harness = canonical_harness_id(s.get("to"))
            recorded = [s.get("vendor_session_id")]
            if s.get("resume_for") in (None, "", harness):
                recorded.append(s.get("resume"))
            if any(h == harness and i in recorded for h, i in ids):
                return str(thread.get("thread") or thread.get("convoy_id")), str(s.get("session_id"))
    return None


def _identify(root: Path, pid: int | None = None, procs: list[dict[str, Any]] | None = None,
              cwd: str | None = None, env: Mapping[str, str] | None = None,
              *, allow_unseated: bool = False) -> dict[str, Any]:
    """Which chair is the CALLER? Detect -> identify -> only then send.

    Walks the caller's ancestry (shell -> harness) in the process table.
    Matching native ids, pane-host records and worktree paths are independent
    positive evidence; sources naming different chairs refuse identity.
    Unrecorded native ids make no chair claim, so a fresh or rotated vendor
    session can fall through to the host/path evidence. A caller's own argv
    or prompt text is never native identity evidence. This E1 local-user
    check guards attribution mistakes, not a malicious same-user process
    able to forge its own environment or edit local Convoy files."""
    root = Path(root)
    enum_error = None
    synthetic_procs = procs is not None or _TEST_PROCS is not None
    if procs is not None:
        pass
    elif _TEST_PROCS is not None:
        procs = _TEST_PROCS
    else:
        procs, enum_error = _safe_enumerate()
    # A supplied process table is a synthetic test fixture. Its environment
    # must be injected too, rather than silently borrowing this test runner's
    # real CODEX_THREAD_ID/CLAUDE_CODE_SESSION_ID.
    env = ({} if synthetic_procs else os.environ) if env is None else env
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
    chain = walk_ancestry(by_pid, me)
    seats = list_seats(root, require_session=True)

    def _refuse(reason: str, chairs: list[str] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": False, "chair": None, "via": "conflict", "harness": None,
                                  "harness_pid": None, "on_thread": bool(chairs), "ask": reason}
        if chairs:
            result["chairs"] = sorted(set(chairs))
        result.update(ctx)
        if ctx.get("ask"):
            result["ask"] = reason + "; " + str(ctx["ask"])
        return result

    def _native_hits(harness: str, native_id: str) -> list[dict[str, Any]]:
        hits = []
        for s in seats:
            if canonical_harness_id(s.get("to")) != harness:
                continue
            recorded = [s.get("vendor_session_id")]
            if s.get("resume_for") in (None, "", harness):
                recorded.append(s.get("resume"))
            if native_id in recorded:
                hits.append(s)
        return hits

    body_nodes, outer_nodes = _body_and_outer(chain)
    body_pids = {node[1]["pid"] for node in body_nodes}
    if allow_unseated and outer_nodes:
        return _refuse("nested harness cannot prove an independent native session; refuse attach")
    if allow_unseated and body_nodes and body_nodes[0][2] == "pi":
        # The current harness contract says --resume opens a picker. Its
        # next argv word is not an evidenced native id. The shared reader
        # must establish direct-session proof before Pi can attach by id.
        return _refuse("Pi native session identity unavailable: --resume is a picker, not session-id proof")
    if outer_nodes:
        # Attribute the caller to its nearest harness body only. A parent
        # harness may still have a recorded native id in argv or a pane-host
        # record; that is evidence the child inherited the parent's env, not
        # that the child owns the parent chair. Repeated same-harness processes
        # without such evidence can be one native session (Codex uses two).
        nearest_harness = body_nodes[0][2]
        host_records = read_host_records(root)
        for _, outer_process, outer_harness in outer_nodes:
            inherited = (str(env.get("CLAUDE_CODE_SESSION_ID") or "").strip()
                         if outer_harness == "claude" else
                         str(env.get("CODEX_THREAD_ID") or "").strip()
                         if outer_harness == "codex" else "")
            hits = _native_hits(outer_harness, inherited) if inherited else []
            outer_argv = _native_resume_ids(str(outer_process.get("cmdline") or ""), outer_harness)
            host_hit = any(str(r.get("status") or "") == "running" and
                           any(r.get(key) == outer_process["pid"] for key in ("child_pid", "host_pid")) and
                           any(r.get("session_id") == s.get("session_id") for s in hits)
                           for r in host_records)
            if hits and (outer_harness != nearest_harness or inherited in outer_argv or host_hit):
                return _refuse("nested harness may have inherited another chair's native id; refuse identity",
                               [str(s.get("session_id")) for s in hits])
        chain = chain[:outer_nodes[0][0]]

    native_claims: list[tuple[str, str, int]] = []
    unrecorded_native: list[tuple[str, str, str]] = []
    for p in chain:
        cmd = str(p.get("cmdline") or "")
        harness = _exe_harness(cmd)
        if harness is None:
            continue
        native_id = None
        if harness == "codex":
            thread_id = str(env.get("CODEX_THREAD_ID") or "").strip()
            session_id = str(env.get("CODEX_SESSION_ID") or "").strip()
            if thread_id and session_id and thread_id != session_id:
                return _refuse("Codex environment session ids disagree; refuse identity")
            native_id = thread_id or None  # CODEX_SESSION_ID only corroborates.
        elif harness == "claude":
            native_id = str(env.get("CLAUDE_CODE_SESSION_ID") or "").strip() or None
        arg_ids = _native_resume_ids(cmd, harness)
        if len(arg_ids) > 1:
            return _refuse("multiple native resume ids in one harness command; refuse identity")
        if allow_unseated and native_id and arg_ids and native_id not in arg_ids:
            return _refuse("native environment and resume arguments disagree; refuse attach")
        for via, claim_id in (("environment", native_id), ("token", next(iter(arg_ids), None))):
            if not claim_id:
                continue
            hits = _native_hits(harness, claim_id)
            if len(hits) > 1:
                return _refuse("native session id matches multiple chairs on this Convoy thread; refuse identity",
                               [str(s.get("session_id")) for s in hits])
            if not hits:
                # A vendor can create or rotate its native id before Convoy
                # records it. No chair is claimed by that id, so independent
                # pane-host/argv/path evidence may still identify the caller.
                unrecorded_native.append((harness, claim_id, via))
                continue
            if via == "environment":
                # An env var can be copied into an unrelated same-user
                # process. If Convoy can place that chair's body at another
                # pid through token or pane-host evidence, this caller is not
                # that body. Path-only liveness is too weak to veto identity:
                # legacy drive-root seats can match unrelated processes.
                # A quoted-prompt token can still veto, conservatively
                # failing closed rather than risking a second writer.
                view = match_processes(root, procs)
                hosted_pids: set[int] = set()
                for record in read_host_records(root):
                    if (record.get("session_id") == hits[0]["session_id"] and
                            record.get("status") == "running"):
                        for key in ("child_pid", "host_pid"):
                            try:
                                value = int(record[key])
                            except (KeyError, TypeError, ValueError):
                                continue
                            if _record_names(by_pid, value, record.get(key[:-4] + "_started"),
                                             record.get("started_at")):
                                hosted_pids.add(value)
                elsewhere = [b["pid"] for c in view["chairs"]
                             if c["session_id"] == hits[0]["session_id"]
                             for b in c["bodies"]
                             if b["via"] in ("token", "pid") or b["pid"] in hosted_pids
                             if b["pid"] not in body_pids and
                             _exe_harness(str(by_pid.get(b["pid"], {}).get("cmdline") or "")) == harness]
                elsewhere.extend(pid for pid in hosted_pids if pid not in body_pids and
                                 _exe_harness(str(by_pid.get(pid, {}).get("cmdline") or "")) == harness)
                if elsewhere:
                    return _refuse("native environment id names a chair with another live body; refuse identity",
                                   [str(hits[0].get("session_id"))])
            native_claims.append((hits[0]["session_id"], via, p["pid"]))
    if len({claim[0] for claim in native_claims}) > 1:
        return _refuse("native environment and resume arguments disagree; refuse identity",
                       [claim[0] for claim in native_claims])
    # Rung 'pane-host': a pid someone wrote down at launch. It is independent
    # evidence, not something a command-line argument can override.
    known = {s["session_id"]: s for s in seats}
    def _with_unrecorded(result: dict[str, Any], sid: str) -> dict[str, Any]:
        harness = canonical_harness_id(known[sid].get("to"))
        candidates = {(h, native_id, via) for h, native_id, via in unrecorded_native
                      if h == harness and via == "environment"}
        if len(candidates) == 1:
            h, native_id, via = next(iter(candidates))
            result["native_session"] = {"id": native_id, "harness": h,
                                        "via": via, "recorded": False}
        elif allow_unseated and native_claims:
            via, native_pid = native_claims[0][1:]
            if via == "environment":
                native_id = env.get("CODEX_THREAD_ID") if harness == "codex" else env.get("CLAUDE_CODE_SESSION_ID")
            else:
                arg_ids = _native_resume_ids(str(by_pid[native_pid].get("cmdline") or ""), harness)
                native_id = next(iter(arg_ids), None)
            if native_id:
                result["native_session"] = {"id": native_id.strip(), "harness": harness,
                                            "via": via, "recorded": True}
        return result
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
            # The record names the process it launched by pid and start time; a pid now held
            # by a process that started later is someone else.
            if _record_names(by_pid, value, record.get(key[:-4] + "_started"), record.get("started_at")):
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
            if (canonical_harness_id(s.get("to")) == exe and
                    not broad_worktree(s.get("worktree")) and _mentions_path(cmd, s.get("worktree"))):
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
                if (canonical_harness_id(s.get("to")) == exe and
                        not broad_worktree(s.get("worktree")) and _same_path(here, s.get("worktree"))):
                    path_hit = (s["session_id"], "cwd", p["pid"])
                    break
            if path_hit:
                break
    # Independent evidence is corroboration, not a ladder that can override a
    # disagreement. In particular an environment id cannot steal a pane-host
    # body, and a copied id in argv cannot outvote the caller's environment.
    if native_claims:
        native_sid, native_via, native_pid = native_claims[0]
        disagree = [sid for sid in (pid_hit[0] if pid_hit else None,
                                     path_hit[0] if path_hit else None) if sid and sid != native_sid]
        if disagree:
            return _refuse("native session and pane/path evidence disagree; refuse identity",
                           [native_sid, *disagree])
        seat_row = known[native_sid]
        return _with_unrecorded({"ok": True, "chair": native_sid, "via": native_via,
                                 "harness": seat_row.get("to"), "harness_pid": native_pid,
                                 "on_thread": True, **ctx}, native_sid)
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
    # A path proof (a pane-host record, a worktree in the argv, the cwd) never identifies a
    # different session than the one the caller's own native id proves: that id recorded as
    # a chair on another thread is a different chair than the path names here.
    path_chair = pid_hit[0] if pid_hit else (path_hit[0] if path_hit else None)
    elsewhere = _native_chair_elsewhere(root, unrecorded_native) if path_chair else None
    if elsewhere is not None:
        other_thread, other_chair = elsewhere
        out = {"ok": False, "chair": None, "via": "conflict", "harness": None, "harness_pid": None,
               "on_thread": True, "chairs": [path_chair],
               "ask": ("your native session is chair " + other_chair + " on thread " + str(other_thread) +
                       ", but the " + ("pane-host record" if pid_hit else path_hit[1] + " path") +
                       " here names chair " + path_chair + ", another session: a path never proves a"
                       " different session; pass --root for your own thread, or attach this session here")}
        reason = out["ask"]
        out.update(ctx)
        if ctx.get("ask"):
            out["ask"] = reason + "; " + str(ctx["ask"])
        return out
    if pid_hit:
        seat_row = known[pid_hit[0]]
        return _with_unrecorded({"ok": True, "chair": pid_hit[0], "via": "pane-host",
                                 "harness": seat_row.get("to"), "harness_pid": pid_hit[1],
                                 "on_thread": True, **ctx}, pid_hit[0])
    if path_hit:
        seat_row = known[path_hit[0]]
        return _with_unrecorded({"ok": True, "chair": path_hit[0], "via": path_hit[1],
                                 "harness": seat_row.get("to"), "harness_pid": path_hit[2],
                                 "on_thread": True, **ctx}, path_hit[0])
    if allow_unseated and body_nodes and not enum_error:
        h = body_nodes[0][2]
        candidates = {(native_id, via) for harness, native_id, via in unrecorded_native if harness == h}
        ids = {native_id for native_id, _ in candidates}
        if len(ids) == 1:
            native_id = next(iter(ids))
            via = "environment" if (native_id, "environment") in candidates else "token"
            return {"ok": True, "chair": None, "via": via, "harness": h,
                    "harness_pid": body_nodes[0][1]["pid"], "on_thread": False,
                    "native_session": {"id": native_id, "harness": h, "via": via, "recorded": False}, **ctx}
    out = {"ok": False, "chair": None, "via": None, "harness": None, "harness_pid": None, "on_thread": False,
           "ask": "no chair on this thread matches your body: join (" + convoy_root_command(root) +
                  " join --to <harness> --worktree " + str(here) + ") or seat this worktree, then retry"}
    out.update(ctx)   # a conflict ask replaces the join ask: fix the root first
    if enum_error:
        out["error"] = enum_error
        out["ask"] = "process table unreadable (" + enum_error + "); retry whoami"
    return out


def _safe_enumerate(*, attempts: int = 3, timeout: float = 150) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return enumerate_processes(attempts=attempts, timeout=timeout), None
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return [], type(e).__name__ + ": " + str(e)


def chair_live(root: Path, session_id: str, procs: list[dict[str, Any]] | None = None) -> bool:
    """True when the chair is live OR its liveness is UNKNOWN. Callers are
    no-steal guards: refusing on unknown is the safe answer, and inventing
    `not live` is how a second body gets launched on a live codex thread.
    Use chair_liveness() when you need the three states."""
    return chair_liveness(root, session_id, procs) is not False


def chair_liveness(root: Path, session_id: str, procs: list[dict[str, Any]] | None = None) -> bool | None:
    """True / False / None(unknown) for one chair."""
    view = match_processes(Path(root), procs) if procs is not None else bodies(Path(root))
    for c in view["chairs"]:
        if c["session_id"] == session_id:
            return c["live"]
    return False
