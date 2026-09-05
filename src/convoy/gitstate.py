"""Live git probes. Never invent main."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .cmd import quiet_spawn_kwargs

def _run(cmd: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=10, **quiet_spawn_kwargs())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    return out or None

def git_remote(cwd: Path | str, name: str = "origin") -> str | None:
    """The named remote URL, or null. Never invented."""
    return _run(["git", "remote", "get-url", name], Path(cwd))


def git_state(cwd: Path | str) -> dict[str, Any]:
    root = Path(cwd)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    sha = _run(["git", "rev-parse", "HEAD"], root)
    pr_raw = _run(["gh", "pr", "view", "--json", "number", "-q", ".number"], root)
    pr_number = None
    if pr_raw:
        try:
            pr_number = int(pr_raw)
        except ValueError:
            pr_number = None
    return {
        "git_branch": branch,
        "git_sha": sha,
        "pr_number": pr_number,
    }
