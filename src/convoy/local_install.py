"""`convoy install --local`: this machine's Convoy supervisors as one verb with a
verify card. Marco 2026-09-12, productize move 1.

Live 2026-09-08 to 2026-09-11 the public edge went down three times because the
origin and the tunnel connector were hand-started processes owned by nobody, and
each repair was a PowerShell window. This verb plans and, with --live --opt-in,
registers what those windows did, then proves it by reading it back:

  origin   ConvoyBotMcp     at-logon task, restart 99x/1 min, no time limit:
                            <this interpreter's pythonw> -m convoy.cli --root <root> mcp --port <port>
  tunnel   ConvoyBotTunnel  same shape: pythonw -m convoy.tunnel_run, which reads the
                            token FILE at run time and spawns cloudflared with no window
                            (the token is never in a task definition, a card, or a log line)
  console  `convoy` on PATH must be Convoy (cmd._is_convoy_itself), not a stranger

Windows only today (schtasks via PowerShell). Other OSes are refused naming the
missing adapter (systemd user unit, launchd agent); nothing is faked.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[str], dict[str, Any]]

ORIGIN_TASK = "ConvoyBotMcp"
# Every supervised process runs on the WINDOWLESS interpreter. A console program
# started by Task Scheduler has no parent console, and when Windows Terminal is
# the default terminal each one gets its own blank window (2026-09-14: two
# cascaded cmd windows at 22:59:30, one per task). conhost --headless hides the
# window but returns 0 whatever the child did (measured), which would blind the
# restart-on-failure supervision; pythonw.exe keeps the exit code.
TUNNEL_TASK = "ConvoyBotTunnel"
DEFAULT_PORT = 8788
DEFAULT_METRICS = "127.0.0.1:20241"


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
        "$s = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew",
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


def install_local(root: Path | str, *, token_file: Path | str | None = None, port: int = DEFAULT_PORT,
                  metrics: str = DEFAULT_METRICS, live: bool = False, opt_in: bool = False,
                  verify_only: bool = False, runner: Runner | None = None, windows: bool | None = None,
                  cloudflared: str | None = None, migrate_token: bool = False) -> dict[str, Any]:
    """Plan (default), register (--live --opt-in), or verify (--verify) this machine's
    Convoy supervisors. Every claim in the card comes from a read-back.

    migrate_token: copy the bytes of `token_file` into CONVOY_HOME/tunnel/run.token
    and plan from there, so the live task and the verify card agree on one home
    (grok-bot 2026-09-12: the tunnel still read C:/.grok while the verb planned
    CONVOY_HOME). Bytes only; the token is never read into the card."""
    r = Path(root).resolve()
    run = runner or _powershell
    is_win = (os.name == "nt") if windows is None else bool(windows)
    home = _home()
    log_dir = home / "tunnel"
    default_tok = log_dir / "run.token"
    tok = Path(token_file) if token_file else default_tok
    cf_exe = cloudflared or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    card: dict[str, Any] = {"ok": True, "root": str(r), "dry_run": not live and not verify_only, "live": bool(live),
                            "verify_only": bool(verify_only), "warnings": [], "plan": [], "verify": [],
                            "next": "convoy install --local --verify to re-check any time"}
    if not is_win:
        card.update({"ok": False, "error": "install --local is Windows-only today (scheduled tasks); a systemd user unit and a launchd agent are the missing adapters, not built"})
        return card
    # The origin serves ONE root for its lifetime, so the root must be a bound
    # thread, and never CONVOY_HOME (2026-09-13: run from the home directory this
    # verb bound the public origin to C:/Users/<user> and the conductor's first
    # authenticated stamp landed in CONVOY_HOME/feed.jsonl, a place no seat reads).
    try:
        same_as_home = r == home.resolve() or r == home.resolve().parent
    except OSError:
        same_as_home = False
    if same_as_home:
        card.update({"ok": False, "error": "root " + str(r) + " is CONVOY_HOME or its parent, not a thread; pass --root <a bound thread>"})
        card["known_roots"] = _known_roots()
        return card
    if not (r / ".convoy" / "id").is_file():
        card.update({"ok": False, "error": "root " + str(r) + " is not a Convoy thread (no .convoy/id); pass --root <a bound thread>"})
        card["known_roots"] = _known_roots()
        return card
    if migrate_token:
        mig: dict[str, Any] = {"from": str(tok), "to": str(default_tok), "copied": False}
        if tok.resolve() == default_tok.resolve():
            mig["note"] = "already in CONVOY_HOME"
        elif not tok.is_file():
            card.update({"ok": False, "error": "migrate-token: no token file at " + str(tok)})
            card["migrated"] = mig
            return card
        else:
            try:
                data = tok.read_bytes()
                if default_tok.is_file() and default_tok.read_bytes() == data:
                    mig["note"] = "identical file already there"
                else:
                    log_dir.mkdir(parents=True, exist_ok=True)
                    default_tok.write_bytes(data)
                    mig["copied"] = True
                del data
            except OSError as e:
                card.update({"ok": False, "error": "migrate-token: " + type(e).__name__ + ": " + str(e)})
                card["migrated"] = mig
                return card
        card["migrated"] = mig
        tok = default_tok
    plan = [
        {"name": "origin", "task": ORIGIN_TASK, "execute": _windowless_interpreter(),
         "arguments": "-m convoy.cli --root " + _ps_dq(str(r)) + " mcp --host 127.0.0.1 --port " + str(int(port)),
         "workdir": str(r), "trigger": "at-logon", "restart": "99x / 1 min", "time_limit": "none"},
        {"name": "tunnel", "task": TUNNEL_TASK, "execute": _windowless_interpreter(),
         "arguments": "-m convoy.tunnel_run --token-file " + _ps_dq(str(tok)) + " --log " + _ps_dq(str(log_dir / "cloudflared.log"))
                      + " --metrics " + metrics + " --exe " + _ps_dq(cf_exe),
         "workdir": str(log_dir), "token_file": str(tok), "metrics": metrics,
         "log": str(log_dir / "cloudflared.log"), "trigger": "at-logon", "restart": "99x / 1 min", "time_limit": "none"},
        {"name": "console-script", "check": "`convoy` on PATH answers `convoy inbox --help` as this package",
         "fix": "pip install <this checkout> into the interpreter whose Scripts dir is first on PATH, and rename any other program called convoy"},
    ]
    card["plan"] = plan
    if not tok.is_file():
        card["warnings"].append("tunnel token file not found at " + str(tok) + "; the tunnel task will fail until it exists (write the token there by hand, never paste it)")
    if live and not opt_in:
        card.update({"ok": False, "error": "install --local --live requires --opt-in: it registers two scheduled tasks under your user"})
        return card
    if live:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            card.update({"ok": False, "error": "could not create the tunnel home: " + str(e)})
            return card
        for item in plan[:2]:
            res = run(_register_script(item["task"], item["execute"], item["arguments"], item["workdir"]))
            item["registered"] = bool(res.get("ok"))
            if not res.get("ok"):
                card["ok"] = False
                item["error"] = (res.get("stderr") or "register failed").strip()[:200]
            else:
                run("Start-ScheduledTask -TaskName " + _ps_quote(item["task"]))
    if live or verify_only:
        for item in plan[:2]:
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
    return card


def _known_roots() -> list[dict[str, Any]]:
    """Threads the machine index knows and that still exist, so a refused root
    comes with the choices instead of a bare no."""
    try:
        from .index import list_threads
        rows = list_threads()
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
