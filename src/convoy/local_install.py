"""`convoy install --local`: this machine's Convoy supervisors as one verb with a
verify card. Marco 2026-09-12, productize move 1.

Live 2026-09-08 to 2026-09-11 the public edge went down three times because the
origin and the tunnel connector were hand-started processes owned by nobody, and
each repair was a PowerShell window. This verb plans and, with --live --opt-in,
registers what those windows did, then proves it by reading it back:

  origin   ConvoyBotMcp     at-logon task, restart 99x/1 min, no time limit:
                            <this interpreter> -m convoy.cli --root <root> mcp --port <port>
  tunnel   ConvoyBotTunnel  same shape, running Convoy's own wrapper under CONVOY_HOME
                            which reads the token FILE at run time (the token is never
                            in a task definition, a card, or a log line)
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


def _wrapper_text(token_file: Path, log_dir: Path, exe_hint: str, metrics: str) -> str:
    return "\n".join([
        "# Run-ConvoyBotTunnel.ps1 - written by `convoy install --local`. Supervised cloudflared for the Convoy origin.",
        "# Reads the tunnel token from a FILE at run time; the token is never in this script, the task, or a log.",
        '$ErrorActionPreference = "Stop"',
        "$log = '" + str(log_dir / "cloudflared.log").replace("'", "''") + "'",
        "$tokFile = '" + str(token_file).replace("'", "''") + "'",
        "$exe = '" + exe_hint.replace("'", "''") + "'",
        "if (-not (Test-Path $exe)) { $exe = (Get-Command cloudflared.exe -ErrorAction Stop).Source }",
        'if (-not (Test-Path $tokFile)) { throw "missing tunnel token file: $tokFile" }',
        "$token = (Get-Content -Raw $tokFile).Trim()",
        'if ([string]::IsNullOrWhiteSpace($token)) { throw "empty tunnel token" }',
        "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force",
        "Start-Sleep -Seconds 1",
        "$argList = @('tunnel', '--no-autoupdate', '--metrics', '" + metrics + "', '--logfile', $log, '--loglevel', 'info', 'run', '--token', $token)",
        "$p = Start-Process -FilePath $exe -ArgumentList $argList -WindowStyle Hidden -PassThru",
        "$p.WaitForExit()",
        "exit $p.ExitCode",
    ]) + "\n"


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
    wrapper = log_dir / "Run-ConvoyBotTunnel.ps1"
    cf_exe = cloudflared or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    card: dict[str, Any] = {"ok": True, "root": str(r), "dry_run": not live and not verify_only, "live": bool(live),
                            "verify_only": bool(verify_only), "warnings": [], "plan": [], "verify": [],
                            "next": "convoy install --local --verify to re-check any time"}
    if not is_win:
        card.update({"ok": False, "error": "install --local is Windows-only today (scheduled tasks); a systemd user unit and a launchd agent are the missing adapters, not built"})
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
        {"name": "origin", "task": ORIGIN_TASK, "execute": sys.executable,
         "arguments": "-m convoy.cli --root " + _ps_dq(str(r)) + " mcp --host 127.0.0.1 --port " + str(int(port)),
         "workdir": str(r), "trigger": "at-logon", "restart": "99x / 1 min", "time_limit": "none"},
        {"name": "tunnel", "task": TUNNEL_TASK, "execute": "powershell.exe",
         "arguments": "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " + _ps_dq(str(wrapper)),
         "workdir": str(log_dir), "wrapper": str(wrapper), "token_file": str(tok), "metrics": metrics,
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
            wrapper.write_text(_wrapper_text(tok, log_dir, cf_exe, metrics), encoding="utf-8")
        except OSError as e:
            card.update({"ok": False, "error": "could not write the tunnel wrapper: " + str(e)})
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


def _ps_dq(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'
