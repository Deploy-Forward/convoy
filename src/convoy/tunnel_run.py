"""`pythonw -m convoy.tunnel_run`: the supervised cloudflared runner.

Started by the ConvoyBotTunnel scheduled task. Reads the tunnel token from a
FILE at run time (utf-8-sig: a PowerShell-written BOM would otherwise become the
first byte of the token), spawns cloudflared with no console window, waits, and
exits with cloudflared's own exit code so Task Scheduler's restart-on-failure
sees the truth. The token is never printed, logged, or put on this process's
own command line.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

CREATE_NO_WINDOW = 0x08000000
DEFAULT_EXE = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"


def _spawn(argv: list[str], **kw: Any) -> int:
    return subprocess.run(argv, **kw).returncode


def main(argv: list[str] | None = None, spawn: Callable[..., int] = _spawn) -> int:
    ap = argparse.ArgumentParser(prog="convoy.tunnel_run")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--metrics", default="127.0.0.1:20241")
    ap.add_argument("--exe", default=DEFAULT_EXE)
    a = ap.parse_args(argv)
    tok_path = Path(a.token_file)
    if not tok_path.is_file():
        return 2
    token = tok_path.read_text(encoding="utf-8-sig").strip()
    if not token:
        return 2
    cmd = [a.exe, "tunnel", "--no-autoupdate", "--metrics", a.metrics, "--logfile", a.log, "--loglevel", "info",
           "run", "--token", token]
    try:
        return int(spawn(cmd, creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0))
    except OSError:
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
