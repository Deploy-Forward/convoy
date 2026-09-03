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
