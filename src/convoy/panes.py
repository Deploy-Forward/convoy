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
        value_flags = {"-m", "--model", "-c", "--config", "-C", "--cd",
                       "-a", "--ask-for-approval", "--enable", "--disable",
                       "--remote", "--remote-auth-token-env", "-i", "--image",
                       "--local-provider", "-p", "--profile", "-s", "--sandbox",
                       "--add-dir"}
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
            "reachable": chair_reachable(pulse, read_wait_file(root, sid), now or utc_now()),
        })
    # a helper whose ancestor is claimed belongs to that body; everything else
    # that runs a harness exe and is nobody's is unassigned.
    unassigned = []
    for p in bodies_only:
        exe = _liveness_harness(str(p.get("cmdline") or ""))
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
             cwd: str | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
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
    chain: list[dict[str, Any]] = []
    cur = by_pid.get(me)
    hops = 0
    while cur is not None and hops < 32:
        chain.append(cur)
        cur = by_pid.get(cur.get("ppid"))
        hops += 1
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
        same_body = (bool(near_ids) and near_ids == outer_ids) or (
            node[2] == "codex" and (
                "app-server" in _argv_tokens(near_cmd)[1:] or
                (not near_ids and not outer_ids)
            )
        )
        if not same_body:
            break
        body_nodes.append(node)
    outer_nodes = harness_nodes[len(body_nodes):]
    body_pids = {node[1]["pid"] for node in body_nodes}
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
                # pid, this caller is not that body. The no-steal matcher is
                # deliberately conservative here: uncertainty refuses.
                view = match_processes(root, procs)
                elsewhere = [b["pid"] for c in view["chairs"]
                             if c["session_id"] == hits[0]["session_id"]
                             for b in c["bodies"]
                             if b["pid"] not in body_pids and
                             _exe_harness(str(by_pid.get(b["pid"], {}).get("cmdline") or "")) == harness]
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
