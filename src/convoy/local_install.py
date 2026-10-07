"""`convoy install --local`: this machine's Convoy supervisors as one verb with a
verify card.

An origin started by hand is a process owned by nobody: when it dies nothing
restarts it, and each repair is a PowerShell window. This verb plans and, with
--live --opt-in, registers what that window did, then proves it by reading it
back:

  origin   ConvoyBotMcp     at-logon task, restart 99x/1 min, no time limit:
                            <this interpreter's pythonw> -m convoy.cli mcp --port <port>
                            (serves every thread in the machine index on loopback;
                            --bound pins --root)
  console  `convoy` on PATH must be Convoy (cmd._is_convoy_itself), not a stranger

Convoy 1.3.2 removed the tunnel supervisor. Remote access to your loopback MCP
is not a Convoy feature; if you build it, put it behind your own access
control. --verify reports what an older install left behind (the removed
tunnel's scheduled task and its files) with the command that removes each one,
and deletes nothing.

Windows only today (schtasks via PowerShell). Other OSes are refused naming the
missing adapter (systemd user unit, launchd agent); nothing is faked.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[str], dict[str, Any]]

# The name predates 1.3.2 and is kept so existing installs are found and
# updated in place; it names the local loopback MCP task, not a hosted one.
ORIGIN_TASK = "ConvoyBotMcp"
# Every supervised process runs on the WINDOWLESS interpreter. A console program
# started by Task Scheduler has no parent console, and when Windows Terminal is
# the default terminal each one gets its own blank window (two cascaded
# cmd windows, one per task). conhost --headless hides the
# window but returns 0 whatever the child did (measured), which would blind the
# restart-on-failure supervision; pythonw.exe keeps the exit code.
DEFAULT_PORT = 8788
# What an install before 1.3.2 left behind: the tunnel supervisor and its files
# under CONVOY_HOME/tunnel. Reported by name and path, never read, never deleted.
LEGACY_TUNNEL_TASK = "ConvoyBotTunnel"
LEGACY_TUNNEL_FILES = ("run.token", "Run-ConvoyBotTunnel.ps1", "cloudflared.log")


def _home() -> Path:
    return Path(os.environ.get("CONVOY_HOME") or (Path.home() / ".convoy"))


def _powershell(script: str) -> dict[str, Any]:
    """Run one PowerShell script. Output is captured; the token never rides here."""
    exe = shutil.which("powershell") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": r.returncode == 0, "stdout": r.stdout or "", "stderr": r.stderr or ""}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "stdout": "", "stderr": type(e).__name__ + ": " + str(e)}


def _console_script_ok() -> tuple[bool, str | None]:
    """Is the `convoy` on PATH Convoy itself? (cmd.convoy_command's proof, reused.)"""
    from .cmd import _is_convoy_itself
    exe = shutil.which("convoy")
    if not exe:
        return False, None
    return bool(_is_convoy_itself("convoy")), exe




def _windowless_interpreter() -> str:
    """pythonw.exe beside this interpreter when it exists, else this interpreter."""
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw) if pw.is_file() else str(exe)


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _register_script(task: str, execute: str, arguments: str, workdir: str) -> str:
    return "; ".join([
        "$a = New-ScheduledTaskAction -Execute " + _ps_quote(execute) + " -Argument " + _ps_quote(arguments) + " -WorkingDirectory " + _ps_quote(workdir),
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME",
        "$s = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -DisallowStartIfOnBatteries $false -StopIfGoingOnBatteries $false",
        "Register-ScheduledTask -TaskName " + _ps_quote(task) + " -Action $a -Trigger $t -Settings $s -Force | Select-Object TaskName, State | ConvertTo-Json -Compress",
    ])


def _readback_script(task: str) -> str:
    return ("$t = Get-ScheduledTask -TaskName " + _ps_quote(task) + " -ErrorAction Stop; "
            "[pscustomobject]@{ TaskName=$t.TaskName; State=[string]$t.State; Execute=$t.Actions[0].Execute; Arguments=$t.Actions[0].Arguments; "
            "RestartCount=$t.Settings.RestartCount; RestartInterval=$t.Settings.RestartInterval; "
            "Trigger=(($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ',') } | ConvertTo-Json -Compress")


def _verify_task(task: str, runner: Runner) -> dict[str, Any]:
    r = runner(_readback_script(task))
    if not r.get("ok"):
        return {"ok": False, "task": task, "error": (r.get("stderr") or "read-back failed").strip()[:200]}
    try:
        info = json.loads(r.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "task": task, "error": "unreadable task card"}
    state = str(info.get("State") or "")
    mirrored = str(info.get("RestartCount")) == "99" and "PT1M" in str(info.get("RestartInterval") or "") and "Logon" in str(info.get("Trigger") or "")
    return {"ok": state in ("Running", "Ready") and mirrored, "task": task, "state": state or None,
            "execute": info.get("Execute"), "arguments": info.get("Arguments"), "mirrored": mirrored}


def _legacy_leftovers(home: Path, run: Runner) -> list[dict[str, Any]]:
    """What a pre-1.3.2 install left behind, each with the command that removes it.
    The task is read back by name; the files are checked for existence only (a
    token file is never opened). Nothing is removed here."""
    out: list[dict[str, Any]] = []
    probe = run("Get-ScheduledTask -TaskName " + _ps_quote(LEGACY_TUNNEL_TASK) + " -ErrorAction Stop | "
                "Select-Object TaskName, @{n='State';e={[string]$_.State}} | ConvertTo-Json -Compress")
    if probe.get("ok"):
        try:
            info = json.loads(probe.get("stdout") or "{}")
        except json.JSONDecodeError:
            info = {}
        if str(info.get("TaskName") or "") == LEGACY_TUNNEL_TASK:
            out.append({"name": LEGACY_TUNNEL_TASK, "kind": "scheduled-task", "state": str(info.get("State") or "") or None,
                        "remove": "Unregister-ScheduledTask -TaskName " + LEGACY_TUNNEL_TASK + " -Confirm:$false"})
    folder = home / "tunnel"
    for name in LEGACY_TUNNEL_FILES:
        path = folder / name
        if path.is_file():
            out.append({"name": name, "kind": "file", "path": str(path),
                        "remove": "Remove-Item -LiteralPath " + _ps_quote(str(path))})
    return out


def install_local(root: Path | str, *, port: int = DEFAULT_PORT, live: bool = False, opt_in: bool = False,
                  verify_only: bool = False, runner: Runner | None = None, windows: bool | None = None,
                  bound: bool = False) -> dict[str, Any]:
    """Plan (default), register (--live --opt-in), or verify (--verify) this machine's
    Convoy supervisor. Every claim in the card comes from a read-back."""
    r = Path(root).resolve()
    run = runner or _powershell
    is_win = (os.name == "nt") if windows is None else bool(windows)
    home = _home()
    card: dict[str, Any] = {"ok": True, "root": str(r), "dry_run": not live and not verify_only, "live": bool(live),
                            "verify_only": bool(verify_only), "warnings": [], "plan": [], "verify": [],
                            "next": "convoy install --local --verify to re-check any time"}
    if not is_win:
        card.update({"ok": False, "error": "install --local is Windows-only today (scheduled tasks); a systemd user unit and a launchd agent are the missing adapters, not built"})
        return card
    # Default: the origin serves every thread the machine
    # index knows and each call names its thread; nothing is pointed. --bound
    # pins it to --root, which must then be a thread and never CONVOY_HOME
    # (run from the home directory, the pinned form would bind the origin to
    # the home directory, and the conductor's first authenticated stamp would
    # land in CONVOY_HOME/feed.jsonl, a place no seat reads).
    card["bound"] = bool(bound)
    if bound:
        try:
            same_as_home = r == home.resolve() or r == home.resolve().parent
        except OSError:
            same_as_home = False
        if same_as_home:
            card.update({"ok": False, "error": "root " + str(r) + " is CONVOY_HOME or its parent, not a thread; pass --root <a bound thread> or drop --bound"})
            card["known_roots"] = _known_roots()
            return card
        if not (r / ".convoy" / "id").is_file():
            card.update({"ok": False, "error": "root " + str(r) + " is not a Convoy thread (no .convoy/id); pass --root <a bound thread> or drop --bound"})
            card["known_roots"] = _known_roots()
            return card
    plan = [
        {"name": "origin", "task": ORIGIN_TASK, "execute": _windowless_interpreter(),
         "arguments": ("-m convoy.cli --root " + _ps_dq(str(r)) + " mcp" if bound else "-m convoy.cli mcp") + " --host 127.0.0.1 --port " + str(int(port)),
         "serves": _thread_key(r) if bound else "all threads",
         "workdir": str(r), "trigger": "at-logon", "restart": "99x / 1 min", "time_limit": "none"},
        {"name": "console-script", "check": "`convoy` on PATH answers `convoy inbox --help` as this package",
         "fix": "pip install <this checkout> into the interpreter whose Scripts dir is first on PATH, and rename any other program called convoy"},
    ]
    card["plan"] = plan
    if live and not opt_in:
        card.update({"ok": False, "error": "install --local --live requires --opt-in: it registers a scheduled task under your user"})
        return card
    if live:
        for item in plan[:1]:
            res = run(_register_script(item["task"], item["execute"], item["arguments"], item["workdir"]))
            item["registered"] = bool(res.get("ok"))
            if not res.get("ok"):
                card["ok"] = False
                item["error"] = (res.get("stderr") or "register failed").strip()[:200]
            else:
                run("Start-ScheduledTask -TaskName " + _ps_quote(item["task"]))
    if live or verify_only:
        for item in plan[:1]:
            v = _verify_task(item["task"], run)
            v["name"] = item["name"]
            card["verify"].append(v)
            if not v.get("ok"):
                card["ok"] = False
        ok, exe = _console_script_ok()
        cs: dict[str, Any] = {"name": "console-script", "ok": ok, "path": exe}
        if not ok:
            card["ok"] = False
            cs["hint"] = ("no `convoy` on PATH" if not exe else "the `convoy` on PATH (" + str(exe) + ") is not Convoy") + \
                         "; pip install this checkout so convoy.exe lands in a Scripts dir on PATH"
        card["verify"].append(cs)
        # Reported, never removed: the person runs each `remove` command.
        card["leftovers"] = _legacy_leftovers(home, run)
        if card["leftovers"]:
            card["warnings"].append("an older install left the tunnel behind; Convoy 1.3.2 no longer uses it. "
                                    "Run each leftover's `remove` command in PowerShell to clear it")
    return card


def _thread_key(r: Path) -> str | None:
    try:
        return (r / ".convoy" / "thread").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _known_roots() -> list[dict[str, Any]]:
    """Threads the machine index knows and that still exist, so a refused root
    comes with the choices instead of a bare no."""
    try:
        from .index import discoverable_threads
        rows = discoverable_threads()
    except Exception:  # noqa: BLE001 - a broken index must not hide the refusal
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        root = row.get("root") if isinstance(row, dict) else None
        if root and Path(str(root), ".convoy", "id").is_file() and not row.get("hidden"):
            out.append({"thread": row.get("thread"), "root": str(root)})
    return out[:20]


def _ps_dq(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


# --------------------------------------------------------------------------
# Pairing. One file, no secret in it, proved with one beat.
# --------------------------------------------------------------------------

ORIGIN_RECORD = "origin.json"


def _origin_id(org_id: str, user_id: str, machine_id: str) -> str:
    """o_ + the first 20 hex of a digest over (org, user, machine).

    Deterministic on purpose: re-pairing the same machine for the same user
    produces the SAME origin, so the platform's registry does not grow a new
    row every time someone re-runs the verb, and a machine cannot accidentally
    orphan the links addressed to it.
    """
    raw = "\0".join((str(org_id), str(user_id), str(machine_id)))
    return "o_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def default_machine_id() -> str:
    """A stable, local, non-identifying machine key. Hostname and home path
    are hashed rather than sent: the platform needs to tell two machines
    apart, not to learn their names."""
    import socket
    try:
        node = socket.gethostname()
    except OSError:
        node = ""
    return hashlib.sha256((node + "\0" + str(Path.home())).encode("utf-8")).hexdigest()[:16]


def _beat_once(origin: dict[str, Any]) -> dict[str, Any]:
    from .report import ReportClient
    return ReportClient(origin).beat({"originId": origin["origin_id"], "threads": []})


def pair(*, org_id: str, user_id: str, credential_file: Path | str,
         api_base: str, machine_id: str | None = None,
         home: Path | str | None = None,
         beat: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
         now: str | None = None) -> dict[str, Any]:
    """Write origin.json and prove it with one beat.

    The record says WHERE the credential lives and never what it is, so it can
    be read, pasted into a bug report or committed by accident without leaking
    anything. The credential file stays the user's; report.py reads it at call
    time.

    Proved, not declared: the beat goes out BEFORE the file is written, and the
    card prints the schema that came back rather than the word "success". A
    pairing that only wrote a file would be a machine that believes it is
    connected.
    """
    from .layer import utc_now
    base = Path(home) if home is not None else _home()
    credential = Path(credential_file)
    card: dict[str, Any] = {"ok": False, "home": str(base), "origin_id": None, "verified": None}
    for name, value in (("--org", org_id), ("--user", user_id), ("--api-base", api_base)):
        if not str(value or "").strip():
            card["error"] = "pair requires " + name
            return card
    # Read it once here only to refuse early on a credential that could never
    # ride a header. The bytes are not kept and never enter the card.
    try:
        text = credential.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        card["error"] = "cannot read the credential file: " + type(exc).__name__
        return card
    if not text or not text.isascii() or any(ch.isspace() for ch in text):
        card["error"] = "the credential file is empty, non-ASCII or contains whitespace"
        return card
    del text

    origin = {
        "origin_id": _origin_id(org_id, user_id, machine_id or default_machine_id()),
        "org_id": str(org_id),
        "user_id": str(user_id),
        "machine_id": str(machine_id or default_machine_id()),
        "api_base": str(api_base).rstrip("/"),
        "credential_path": str(credential.resolve()),
        "paired_at": now or utc_now(),
    }
    card["origin_id"] = origin["origin_id"]
    try:
        answer = (beat or _beat_once)(origin)
    except Exception as exc:                 # noqa: BLE001 - report.py's own types
        # Nothing is written. A machine that could not beat is not paired, and
        # a half-written record would have it poll with a credential the
        # platform has already refused.
        card["error"] = type(exc).__name__ + ": " + str(exc)
        return card
    status = int((answer or {}).get("status") or 0)
    body = (answer or {}).get("body")
    if not 200 <= status < 300:
        card["error"] = "the pairing beat returned " + str(status)
        card["verified"] = {"status": status}
        return card
    base.mkdir(parents=True, exist_ok=True)
    (base / ORIGIN_RECORD).write_text(json.dumps(origin, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    card.update({
        "ok": True,
        "record": str(base / ORIGIN_RECORD),
        # The schema it answered with, not a success message: that is the
        # evidence a reader can check.
        "verified": {"status": status,
                     "schema": sorted(body.keys()) if isinstance(body, dict) else []},
        "next": "convoy install --local --verify to read the loop back",
    })
    return card


def unpair(home: Path | str | None = None) -> dict[str, Any]:
    """Delete the pairing record. Never the credential: that file is the
    user's, and this verb has no business removing it."""
    base = Path(home) if home is not None else _home()
    path = base / ORIGIN_RECORD
    existed = path.is_file()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
    return {"ok": True, "unpaired": existed, "record": str(path),
            "note": "the credential file was not touched"}
