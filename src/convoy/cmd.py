"""The one place Convoy decides how to spell its own command line.

Stranger-eyes finding (2026-09-03): boot prompts, asks, and rendered resume
commands hardcoded `python -m convoy`, which fails for a pipx / console-script
install and on hosts without a `python` alias. Every command Convoy hands to
a neuron or a human goes through here: the console script `convoy` when it
is on PATH, else this interpreter with `-m convoy` (resolved, quoted).
"""
from __future__ import annotations

import os
import shutil
import sys


# Travel-capable hook files must spell this exactly. Never sys.executable.
# The interpreter fallback in convoy_command() is for machine-local prompts
# only; a hook JSON that travels with a worktree fails closed instead.
INBOX_HOOK_COMMAND = "convoy inbox --hook-pretooluse"
INBOX_HOOK_INSTALL_HINT = (
    "install the convoy console script so `convoy` is on PATH: "
    "pipx install git+https://github.com/Deploy-Forward/convoy.git"
)


def convoy_command() -> str:
    exe = shutil.which("convoy")
    if exe:
        return "convoy"
    py = sys.executable or "python"
    if any(ch in py for ch in ' "'):
        py = '"' + py.replace('"', '\\"') + '"'
    return py + " -m convoy"


def convoy_root_command(root: os.PathLike | str) -> str:
    r = str(root)
    if any(ch in r for ch in ' "'):
        r = '"' + r.replace('"', '\\"') + '"'
    return convoy_command() + " --root " + r


def inbox_hook_command() -> str:
    """Bare console script. Travel-capable. Never an absolute interpreter."""
    return INBOX_HOOK_COMMAND


def command_bakes_interpreter(command: str) -> bool:
    """True when a hook command would pin a machine-local interpreter path."""
    text = str(command or "").strip()
    if not text:
        return True
    compact = text.replace('"', "").replace("'", "")
    if "-m convoy" in compact:
        return True
    first = compact.split()[0]
    if first.startswith("/") or first.startswith("\\\\"):
        return True
    if len(first) >= 3 and first[1] == ":" and first[2] in "\\/":
        return True
    return False
