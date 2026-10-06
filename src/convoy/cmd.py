"""The one place Convoy decides how to spell its own command line.

Boot prompts, asks, and rendered resume
commands hardcoded `python -m convoy`, which fails for a pipx / console-script
install and on hosts without a `python` alias. Every command Convoy hands to
a neuron or a human goes through here: the console script `convoy` when it
is on PATH, else this interpreter with `-m convoy` (resolved, quoted).
Hook files are the exception: they only ever carry the bare `convoy`, and a
writer refuses when that name does not resolve where the hook runs.
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
HOOK_PATH_ERROR = (
    "the bare `convoy` command does not answer as a Convoy CLI in the hook shell, so no hook "
    "was written: put the directory holding the convoy console script first on PATH "
    "(`convoy --version` names the executable that runs); "
)


def _fwd(path: str) -> str:
    """Forward slashes: the one spelling both cmd.exe and Git Bash execute.
    Backslashes are escape characters in bash (a backslash interpreter path
    collapses to `C:Python314python.exe`)."""
    return str(path).replace("\\", "/")


def _quote(path: str) -> str:
    path = _fwd(path)
    return '"' + path.replace('"', '\\"') + '"' if any(ch in path for ch in ' "') else path


def quiet_spawn_kwargs() -> dict:
    """Never open a console for a helper child. The widget service starts
    with CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (see
    `widget_service.detached_spawn`), so it runs without a console window.
    A parent with no console at all (a DETACHED_PROCESS spawn, pythonw)
    would give every Windows child (PowerShell pane scan, `codex exec
    /status`, `claude -p /usage`, git) a brand-new visible console window:
    black panes all over the screen, one per 3 s tick (seen live).
    CREATE_NO_WINDOW on the child stops that whatever the parent; on other
    OSes there is nothing to add."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


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
    `--hook-pretooluse` usage. An unrelated shim (for example a
    `convoy.cmd` that exits 0 with its own help) fails; so does a name Git
    Bash cannot see (`.cmd` shims, exit 127)."""
    head = command.rsplit(hook_args, 1)[0].strip()
    if not head:
        return False
    verb = hook_args.split()[0]
    line = head + " " + verb + " --help"
    # The hook shell inherits NOTHING from this process: a PYTHONPATH set for
    # the caller can make a dead `python -m convoy` look alive, and the probe
    # would then overwrite a working hook. Scrub it.
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    shells: list[list[str] | None] = [hook_shell(), None] if hook_shell() else [None]
    for shell in shells:
        try:
            if shell:
                r = subprocess.run(shell + [line], capture_output=True, text=True, env=env,
                                   encoding="utf-8", errors="replace", timeout=25, **quiet_spawn_kwargs())
            else:
                r = subprocess.run(line, shell=True, capture_output=True, text=True, env=env,
                                   encoding="utf-8", errors="replace", timeout=25, **quiet_spawn_kwargs())
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and marker in (r.stdout or ""):
            return True
        # A command Convoy writes must pass the primary (bash) hook shell.
        break
    return False


def _probe_inbox_command(command: str) -> bool:
    return _probe_command(command, INBOX_HOOK_ARGS, "--hook-pretooluse")


def _probe_end_command(command: str) -> bool:
    return _probe_command(command, END_HOOK_ARGS, "--hook")


_RESOLVED: dict | None = None
_END_RESOLVED: dict | None = None


def _resolve_bare(command: str, probe) -> dict:
    if probe(command):
        return {"command": command, "resolved_via": "console-script", "error": None}
    return {"command": None, "resolved_via": None, "error": HOOK_PATH_ERROR + INBOX_HOOK_INSTALL_HINT}


def resolve_inbox_hook_command(refresh: bool = False) -> dict:
    """The command a hook file carries: the bare `convoy inbox --hook-pretooluse`, PROBED in the
    hook shell. Never an interpreter path: a baked `<python> -m convoy` or a `sys.path.insert`
    command line pins one machine's interpreter into the worktree and keeps a retired install
    alive. When the bare name does not answer as a Convoy CLI (missing from PATH, or shadowed
    by an unrelated shim), the result has no command and the error names the PATH problem;
    the writer then writes nothing and the launch refuses. Successes are memoized per
    process; a failure is not, so a later write re-probes. The probe reads the help text only:
    it does not prove which Convoy version answers (`convoy --version` names it)."""
    global _RESOLVED
    if _RESOLVED is not None and not refresh:
        return dict(_RESOLVED)
    out = _resolve_bare(INBOX_HOOK_COMMAND, _probe_inbox_command)
    _RESOLVED = dict(out) if out["command"] else None
    return out


def resolve_end_hook_command(refresh: bool = False) -> dict:
    """The Stop-heartbeat command, `convoy end --hook`, resolved the same way."""
    global _END_RESOLVED
    if _END_RESOLVED is not None and not refresh:
        return dict(_END_RESOLVED)
    out = _resolve_bare(END_HOOK_COMMAND, _probe_end_command)
    _END_RESOLVED = dict(out) if out["command"] else None
    return out


_CONVOY_COMMAND: str | None = None


def _is_convoy_itself(name: str) -> bool:
    """Does `<name> inbox --help` answer as this package? A stranger by the
    same name fails: an unrelated `convoy` script earlier on PATH would
    otherwise be handed to every seat in its boot prompt, and the seats would
    only work by falling back to `python -m convoy`."""
    return _probe_command(name + " " + INBOX_HOOK_ARGS, INBOX_HOOK_ARGS, "--hook-pretooluse")


def convoy_command() -> str:
    """The one spelling of Convoy's own command line for neuron-facing text.
    The bare word `convoy` only when the thing on PATH by that name PROVES it
    is this package; otherwise this interpreter, `-m convoy`. Name is not
    proof. Cached per process (the proof spawns a shell)."""
    global _CONVOY_COMMAND
    if _CONVOY_COMMAND is not None:
        return _CONVOY_COMMAND
    exe = shutil.which("convoy")
    if exe and _is_convoy_itself("convoy"):
        _CONVOY_COMMAND = "convoy"
        return _CONVOY_COMMAND
    _CONVOY_COMMAND = _quote(sys.executable or "python") + " -m convoy"
    return _CONVOY_COMMAND


def convoy_root_command(root: os.PathLike | str) -> str:
    """`<convoy> --root <root>` with forward slashes, which cmd.exe and Git Bash both run."""
    return convoy_command() + " --root " + _quote(str(root))


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
