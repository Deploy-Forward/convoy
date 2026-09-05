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
import subprocess
import sys
from pathlib import Path


INBOX_HOOK_ARGS = "inbox --hook-pretooluse"
INBOX_HOOK_COMMAND = "convoy " + INBOX_HOOK_ARGS   # the bare console-script spelling
END_HOOK_ARGS = "end --hook"
END_HOOK_COMMAND = "convoy " + END_HOOK_ARGS
INBOX_HOOK_INSTALL_HINT = (
    "install the convoy console script so `convoy` resolves in the hook shell: "
    "pipx install git+https://github.com/Deploy-Forward/convoy.git (or pip install .), "
    "and make sure no unrelated `convoy` shim shadows it on PATH"
)


def _fwd(path: str) -> str:
    """Forward slashes: the one spelling both cmd.exe and Git Bash execute.
    Backslashes are escape characters in bash (a backslash interpreter path
    collapsed to `C:Python314python.exe` live, 2026-09-03)."""
    return str(path).replace("\\", "/")


def _quote(path: str) -> str:
    path = _fwd(path)
    return '"' + path.replace('"', '\\"') + '"' if any(ch in path for ch in ' "') else path


def _source_dir() -> str:
    """The directory that holds the `convoy` package this process imported."""
    return _fwd(str(Path(__file__).resolve().parent.parent))


def hook_shell() -> list[str] | None:
    """How a harness runs a `type: command` hook. Claude Code and Grok CLI
    hand the string to a POSIX shell (Git Bash on Windows) when one exists;
    `None` means `shell=True` (cmd.exe / /bin/sh) is the best we can do.

    Prefer Git Bash's native Windows process bridge over a generic `bash` on
    PATH. On Windows 11, `C:\\Windows\\System32\\bash.exe` can be WSL bash;
    it cannot execute the Windows interpreter path carried by a hook command.
    """
    if os.name != "nt":
        return None
    for cand in (
        os.environ.get("CONVOY_HOOK_SHELL"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ):
        if cand and Path(cand).is_file():
            return [cand, "-c"]
    return None


def _probe_command(command: str, hook_args: str, marker: str) -> bool:
    """Does this command line, run the way a hook runs it, answer as the
    Python package? `<cmd minus args> inbox --help` must exit 0 and print the
    `--hook-pretooluse` usage. An unrelated shim (audit 2026-09-03: an Aether
    `convoy.cmd` that exits 0 with its own help) fails; so does a name Git
    Bash cannot see (`.cmd` shims, exit 127)."""
    head = command.rsplit(hook_args, 1)[0].strip()
    if not head:
        return False
    verb = hook_args.split()[0]
    line = head + " " + verb + " --help"
    # The hook shell inherits NOTHING from this process: a PYTHONPATH set for
    # the caller made a dead `python -m convoy` look alive (live 2026-09-03,
    # and it overwrote the one working hook on the thread). Scrub it.
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    shells: list[list[str] | None] = [hook_shell(), None] if hook_shell() else [None]
    for shell in shells:
        try:
            if shell:
                r = subprocess.run(shell + [line], capture_output=True, text=True, env=env,
                                   encoding="utf-8", errors="replace", timeout=25)
            else:
                r = subprocess.run(line, shell=True, capture_output=True, text=True, env=env,
                                   encoding="utf-8", errors="replace", timeout=25)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and marker in (r.stdout or ""):
            # Candidates we WRITE must pass the primary (bash) shell; a command
            # we merely KEEP may have been written for cmd.exe, so either
            # shell passing is proof it delivers for its harness.
            return True
        if shell is None or not _PROBE_ANY_SHELL:
            break
    return False


def _probe_inbox_command(command: str) -> bool:
    return _probe_command(command, INBOX_HOOK_ARGS, "--hook-pretooluse")


def _probe_end_command(command: str) -> bool:
    return _probe_command(command, END_HOOK_ARGS, "--hook")


# Writers probe in the primary hook shell only; keep-existing probes any shell.
_PROBE_ANY_SHELL = False


def probe_existing_hook_command(command: str) -> bool:
    global _PROBE_ANY_SHELL
    _PROBE_ANY_SHELL = True
    try:
        return _probe_inbox_command(command)
    finally:
        _PROBE_ANY_SHELL = False


def probe_existing_end_hook_command(command: str) -> bool:
    global _PROBE_ANY_SHELL
    _PROBE_ANY_SHELL = True
    try:
        return _probe_end_command(command)
    finally:
        _PROBE_ANY_SHELL = False


_RESOLVED: dict | None = None
_END_RESOLVED: dict | None = None


def resolve_inbox_hook_command(refresh: bool = False) -> dict:
    """The command a hook file should carry, PROBED in the hook shell.

    Hook files are gitignored per-worktree state and never travel, so an
    absolute interpreter path is not a portability bug; a bare name that
    resolves to nothing (or to a shim) is a delivery bug (audit 2026-09-03:
    every hook written since PR 40 was dead; only a baked path ever fired).
    Order: bare console script if it probes ok; else this interpreter; else
    this interpreter with the source dir on sys.path (checkout-only machine);
    else fail closed with the install hint. Memoized per process."""
    global _RESOLVED
    if _RESOLVED is not None and not refresh:
        return dict(_RESOLVED)
    py = _quote(sys.executable or "python")
    candidates = [
        ("console-script", INBOX_HOOK_COMMAND),
        ("interpreter", py + " -m convoy " + INBOX_HOOK_ARGS),
        ("interpreter+src", py + " -c " + _quote(
            "import sys; sys.path.insert(0, " + repr(_source_dir()) + "); "
            "from convoy.cli import main; sys.exit(main(sys.argv[1:]))") + " " + INBOX_HOOK_ARGS),
    ]
    out = {"command": None, "resolved_via": None,
           "error": "no convoy command resolves in the hook shell; " + INBOX_HOOK_INSTALL_HINT}
    for via, command in candidates:
        if _probe_inbox_command(command):
            out = {"command": command, "resolved_via": via, "error": None}
            break
    # Cache successes only: a transient probe failure (shell busy, PATH
    # changed mid-process) must not poison every later hook write.
    _RESOLVED = dict(out) if out["command"] else None
    return out


def resolve_end_hook_command(refresh: bool = False) -> dict:
    """Resolve and probe the portable Stop-heartbeat command."""
    global _END_RESOLVED
    if _END_RESOLVED is not None and not refresh:
        return dict(_END_RESOLVED)
    py = _quote(sys.executable or "python")
    candidates = [
        ("console-script", END_HOOK_COMMAND),
        ("interpreter", py + " -m convoy " + END_HOOK_ARGS),
        ("interpreter+src", py + " -c " + _quote(
            "import sys; sys.path.insert(0, " + repr(_source_dir()) + "); "
            "from convoy.cli import main; sys.exit(main(sys.argv[1:]))") + " " + END_HOOK_ARGS),
    ]
    out = {"command": None, "resolved_via": None,
           "error": "no convoy command resolves in the hook shell; " + INBOX_HOOK_INSTALL_HINT}
    for via, command in candidates:
        if _probe_end_command(command):
            out = {"command": command, "resolved_via": via, "error": None}
            break
    _END_RESOLVED = dict(out) if out["command"] else None
    return out


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
    """The canonical bare spelling, for docs and cards. Hook FILES get the
    probed result of resolve_inbox_hook_command() instead."""
    return INBOX_HOOK_COMMAND


def end_hook_command() -> str:
    """Canonical portable spelling used by Codex/Claude Stop hooks."""
    return END_HOOK_COMMAND


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
