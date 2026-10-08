"""Phase 7 bring-up: one isolated Windows Terminal window per named thread. Not ola-brain.

Grok Bot (conductor grok-bot) has no harness chip and is not a window.
A named thread is ONE wt.exe spawn via isolated_wt_argv (Start-Process FilePath=wt.exe,
ArgumentList string[]; FileName is wt, not in the list). Never per-seat CREATE_NEW_CONSOLE
+ MoveWindow. Never WM_CLOSE (isolated spawn is a new WINDOW not a new PROCESS).
Lead neurons resume with that harness's own CLI:

    grok --resume <session_id>     cwd=worktree
    claude --resume <session_id>   cwd=worktree
      (live also --permission-mode bypassPermissions
       and --allow-dangerously-skip-permissions)

First-run Claude bypass warning is ungated by ensure_first_run. A Convoy-launched
neuron gets its permission mode from the launch argv and from nothing else: a
permissions.defaultMode in a project .claude/settings.json is honoured by Claude
Code, so every Claude session in that repo, launched by Convoy or not, would run
without prompts. No settings file Convoy writes carries permissions or
skipDangerousModePermissionPrompt. The user file ~/.claude/settings.json gets
skipDangerousModePermissionPrompt: true only when the key is missing (Anthropic
reads it there for the dialog), and an unchanged file is never rewritten.
Hooks and autoCompactEnabled: true (an unattended neuron compacts on its own) go
to the worktree's .claude/settings.local.json, which Claude Code keeps out of git,
never the tracked settings file. ~/.claude.json gets
projects[worktree].hasTrustDialogAccepted=true for both slash spellings. Never
write ~/.claude if worktree IS the home dir. Grok/codex: no Claude settings write.
write_repo_files=False (start on a repo root) writes nothing into the worktree
and lists what it would write as would_write. A launch (write_repo_files=None)
writes every file only into a worktree Convoy minted (repo.is_minted_worktree);
in the person's repo it writes only the Convoy-named files git excludes, and
lists AGENTS.md as would_write until --write-repo-files. No .codex/hooks.json: the
convoy plugin carries Codex's hooks.
Not a user paste.
Not a TUI guide. Persona is role.md.

Hypothesis: Claude Code accepts the same `--resume` flag as grok (native resume).
Not grok `-p` (headless), not grok `-c` (continue latest cwd), not `--output-format`.
Not ola-brain, not side-chat, not cli-chat-proxy.

resume is the vendor session_id argument. resume_key is the hash map key:
    cvr_ + sha256(convoy_id + "\0" + thread + "\0" + to + "\0" + worktree).hexdigest()[:16]
Never invent a session_id. Default runner is a no-op (dry). Live runner is not
called from unit tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from .identity import ensure_inbox_hooks, install_neuron_identity
from .index import is_temp_root
from .harness_contract import effective_model, effort_argv, model_argv, session_id_flag, validate_launch_eligibility
from .convoy import (
    CONDUCTOR,
    list_seats,
    lookup_resume,
    make_resume_key,
    read_id,
    read_lead,
    read_thread,
)

Tiler = Callable[..., list[dict[str, int]]]
Runner = Callable[..., Any]
Applier = Callable[..., Any]

_CONDUCTORS = frozenset({CONDUCTOR, "grok-bot", "grok_bot"})

_BIN = {
    "grok": "grok",
    "grok.exe": "grok",
    "claude": "claude",
    "claude.exe": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "codex.exe": "codex",
    "agy": "agy",
    "agy.exe": "agy",
    "antigravity": "agy",
    "antigravity-cli": "agy",
    "hermes": "hermes",
    "hermes.exe": "hermes",
    "pi": "pi",
    "pi.exe": "pi",
    "cursor-agent": "cursor-agent",
    "cursor-agent.exe": "cursor-agent",
    "cursor_agent": "cursor-agent",
}


def _harness_bin(to: str) -> str:
    key = (to or "").strip().lower()
    if key in _BIN:
        return _BIN[key]
    if key.endswith(".exe"):
        return key[:-4]
    return (to or "").strip()


_WRAPPER_EXES = frozenset({
    "ola-brain",
    "ola-brain.exe",
    "side-chat",
    "side-chat.exe",
    "ultracode-shim",
    "ultracode-shim.exe",
})


def _basename_lower(path: str) -> str:
    return os.path.basename(str(path or "").replace("\\", "/")).lower()


def _is_wrapper_text(text: str) -> bool:
    low = (text or "").lower()
    return (
        "ola-brain" in low
        or "side-chat" in low
        or "ultracode-shim" in low
        or "ultracodeshim" in low
    )


def _is_wrapper_exe(program: str) -> bool:
    """A wrapper program by its basename (ola-brain.exe, side-chat.cmd), never by its folder."""
    base = _basename_lower(program)
    return base in _WRAPPER_EXES or _is_wrapper_text(base)


# wt options that take a value, and the subcommands that open a pane: neither is a program.
# Flags with no value (--suppressApplicationTitle, --useApplicationTitle, -V, -H) are not
# listed: the word after a flag is the pane's program.
_WT_VALUE_OPTIONS = frozenset({"-w", "--window", "-d", "--startingdirectory", "--title", "-p", "--profile",
                               "-s", "--size", "--tabcolor", "--colorscheme", "--pos"})
_WT_SUBCOMMANDS = frozenset({"new-tab", "nt", "split-pane", "sp", "focus-tab", "ft", "move-focus", "mf"})


def _exe_positions(parts: list[str]) -> list[int]:
    """Indexes of the programs a wt argv runs: parts[0], then the first word of each pane
    command (after its subcommand and options; panes are separated by a literal ';')."""
    out = [0] if parts else []
    i, n = 1, len(parts)
    while i < n:
        while i < n and parts[i] != ";":
            a = parts[i].lower()   # wt documents camelCase spellings (--startingDirectory)
            if a in _WT_VALUE_OPTIONS:
                i += 2
                continue
            if a in ("move-focus", "mf"):
                i += 2   # its direction (left/right/up/down) is not a program
                continue
            if a in _WT_SUBCOMMANDS or a.startswith("-"):
                i += 1
                continue
            out.append(i)
            break
        while i < n and parts[i] != ";":
            i += 1
        i += 1
    return out


_SHELL_EXES = frozenset({"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "wsl"})


def _is_shell_exe(program: str) -> bool:
    base = _basename_lower(program)
    return (base[:-4] if base.endswith(".exe") else base) in _SHELL_EXES


# Interpreters and launchers: the program they run is their script or package argument.
_INTERPRETER_EXES = frozenset({"python", "py", "pythonw", "node", "npx", "uvx", "uv", "pipx",
                               "deno", "bun", "ruby", "perl"})
# Words a launcher takes before its script or package (uv run, uv tool run, bun x).
_LAUNCHER_SUBCOMMANDS = frozenset({"run", "tool", "x", "exec"})
# Options whose value IS the package or module run (python -m, npx -p, uvx --from).
_PACKAGE_OPTIONS = frozenset({"-m", "-p", "--package", "--from", "--spec"})
# Options whose value is neither the script nor a package.
_INTERPRETER_VALUE_OPTIONS = frozenset({"-W", "-X", "-r", "--require", "--import", "--loader",
                                        "--with", "--python"})
# Options that run inline code: no script argument follows.
_INLINE_CODE_OPTIONS = frozenset({"-c", "-e", "--eval"})


def _is_interpreter_exe(program: str) -> bool:
    base = _basename_lower(program)
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return re.sub(r"[\d.]+$", "", base) in _INTERPRETER_EXES   # python3.12, python3


def _script_arguments(words: list[str]) -> list[str]:
    """The script or package an interpreter runs, from the words after it: each package
    option's value, then the first word that is not an option or launcher subcommand.
    Later words are the script's own arguments (a root, a --seat value, a boot prompt)."""
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        key, eq, val = w.partition("=")
        if key in _PACKAGE_OPTIONS:
            if eq:
                out.append(val)
                i += 1
            else:
                out.extend(words[i + 1:i + 2])
                i += 2
            continue
        if key in _INLINE_CODE_OPTIONS:
            break
        if key in _INTERPRETER_VALUE_OPTIONS:
            i += 1 if eq else 2
            continue
        if w.startswith("-") or w.lower() in _LAUNCHER_SUBCOMMANDS:
            i += 1
            continue
        out.append(w)
        break
    return out


def _script_names(arg: str) -> list[str]:
    """A script is named by its file and by the folder holding it (ola-brain/main.py,
    side-chat/index.js); a module or package by its name (ola_brain, side-chat@latest)."""
    path = arg.replace("\\", "/").rstrip("/")
    names = [path, path.replace("_", "-")]
    parent = os.path.dirname(path)
    if parent:
        names.append(parent)
    return names


def _pane_programs(parts: list[str]) -> list[str]:
    """Every word a wt argv may run as a program. A plain pane runs its first word. A
    shell's command line can chain programs, so under a shell every later word of that
    pane counts, split on whitespace; Convoy's own panes never run through a shell. An
    interpreter or launcher runs its script or package argument, so that counts too."""
    out: list[str] = []
    for i in _exe_positions(parts):
        j = i + 1
        while j < len(parts) and parts[j] != ";":
            j += 1
        words = [parts[i]]
        if _is_shell_exe(parts[i]):
            for a in parts[i + 1:j]:
                words.extend(a.split())
            out.extend(words)
        else:
            words.extend(parts[i + 1:j])
            out.append(parts[i])
        # A plain pane runs only its first word; under a shell any word may start a program.
        starts = range(len(words)) if _is_shell_exe(parts[i]) else range(1)
        for k in starts:
            if _is_interpreter_exe(words[k]):
                for arg in _script_arguments(words[k + 1:]):
                    out.extend(_script_names(arg))
    return out


def _is_abs_exe(exe: str) -> bool:
    """POSIX abs or Windows drive-letter abs. Linux os.path.isabs does not treat C:\\foo as abs."""
    s = str(exe or "")
    if os.path.isabs(s):
        return True
    return len(s) >= 3 and s[1] == ":" and s[2] in "\\/"


def _coerce_abs(path: str) -> str:
    """Keep Windows drive-letter abs paths intact on POSIX (unit tests mock C:\\...)."""
    s = str(path or "")
    if _is_abs_exe(s):
        return s
    return os.path.abspath(s) if s else s


def _absolute_harness(binary: str) -> str:
    """Resolve FileName via shutil.which to an absolute path when found.

    Never ola-brain / side-chat / UltraCode-Shim. Bare names stay bare when not on PATH (dry cards).
    """
    name = (binary or "").strip()
    if not name:
        raise ValueError("refuse empty harness")
    base = _basename_lower(name)
    if base in _WRAPPER_EXES or _is_wrapper_text(base):
        raise ValueError("refuse wrapper binary")
    if _is_abs_exe(name):
        return name
    found = shutil.which(name)
    if not found and not name.lower().endswith(".exe"):
        found = shutil.which(name + ".exe")
    if found:
        return _coerce_abs(found)
    return name


def _resolve_wt_bin(wt: str | None = None) -> str:
    """FileName for the isolated spawn. Never -w 0. Bare 'wt' if not on PATH."""
    name = str(wt or "").strip()
    if name and _is_abs_exe(name):
        return name
    found = shutil.which(name or "wt") or shutil.which("wt") or shutil.which("wt.exe")
    if found:
        return _coerce_abs(found)
    return name or "wt"


def pane_host_available() -> bool:
    """True when a pane host (wt) is actually on PATH, not just a bare name."""
    found = shutil.which("wt") or shutil.which("wt.exe")
    return bool(found)


def _pane_dedup_key(seat: dict[str, Any]) -> str:
    """worktree if set, else resume_key, else session_id, else to."""
    s = seat or {}
    wt = str(s.get("worktree") or "").strip()
    if wt:
        return wt
    rkey = str(s.get("resume_key") or "").strip()
    if rkey:
        return rkey
    sid = str(s.get("session_id") or "").strip()
    if sid:
        return sid
    return str(s.get("to") or "").strip().lower()


def _pane_seats(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One pane per seated neuron. Conductor is never a window. Empty to skipped.

    Dedup key: worktree if set, else resume_key, else session_id, else to.
    Same seat twice is collapsed (same worktree+to, or same resume_key/session_id).
    Two grok neurons on different worktrees both appear. Not one pane per harness name.
    """
    seen: set[str] = set()
    out_rev: list[dict[str, Any]] = []
    # Newer seats win for the same pane key (worktree/resume/session).
    for s in reversed(seats or []):
        to = str((s or {}).get("to") or "").strip()
        if is_conductor(to):
            continue
        if not to:
            continue
        key = _pane_dedup_key(s)
        if not key or key in seen:
            continue
        seen.add(key)
        out_rev.append(s)
    return list(reversed(out_rev))


def _prepare_wt_seat(seat: dict[str, Any]) -> dict[str, Any]:
    """Copy seat with absolute harness exe for isolated_wt_argv."""
    out = dict(seat)
    override = out.get("exe")
    if override:
        exe = str(override)
    else:
        exe = _absolute_harness(_harness_bin(str(out.get("to") or "")))
    if not _is_abs_exe(exe):
        raise ValueError("refuse non-absolute exe")
    out["exe"] = exe
    return out


def _live_argv(argv: list[str], *, here: bool = False) -> list[str]:
    """Popen argv for ONE isolated wt.exe spawn. FileName is wt. ArgumentList is the rest.

    Never per-seat CREATE_NEW_CONSOLE. Never `--` before the harness exe (pops Help).
    Only -w convoy-<8 hex> (the thread's own window); never -w 0. Never ola-brain / side-chat / UltraCode-Shim.
    """
    if not argv:
        raise ValueError("refuse empty argv")
    parts = [str(a) for a in argv]
    # Only exe positions are read: the spawned program and each pane's program. A root,
    # worktree, title or boot prompt may carry a wrapper's name and is not a wrap.
    for program in _pane_programs(parts):
        if _is_wrapper_exe(program):
            raise ValueError("refuse ola-brain / side-chat / UltraCode-Shim wrap")
    if any(a.lower() == "wm_close" for a in parts):
        raise ValueError("refuse WM_CLOSE")
    if "--" in parts:
        raise ValueError("refuse -- before harness exe")
    if any(a == "^;" for a in parts):
        raise ValueError("refuse cmd ^; — use literal ; in argv")
    base0 = _basename_lower(parts[0])
    if base0 not in ("wt", "wt.exe"):
        raise ValueError("refuse per-seat spawn; use isolated_wt_argv")
    _check_thread_window(parts, here=here)
    wt = _resolve_wt_bin(parts[0])
    # wt.exe splits ITS OWN command line on ';' (that is how nt ; split-pane
    # chains). A boot prompt or title carrying a literal ';' therefore became
    # a second wt command: relaunching a chair opened a tab
    # reading `error 0x80070002 when launching '" at the end of every turn
    # start convoy ...'`. WT's documented escape is `\;`. Everything after
    # `-w <window>` is a pane argument; escape it there, never in the exe.
    # A bare ";" argument IS the separator (nt ... ; split-pane ...); only a
    # ';' inside an argument is escaped.
    return [wt, *[a if a == ";" else a.replace(";", "\\;") for a in parts[1:]]]


_THREAD_WINDOW = re.compile(r"^convoy-[0-9a-f]{8}$")


def _window_holds_another(root: Path, launching: set[str]) -> bool:
    """A chair of this thread outside this launch has a live pane host: the thread's
    window is open, so this launch splits inside it instead of opening it."""
    from .targeted_launch import hosted_live
    return any(hosted_live(root, str(s["session_id"])) for s in list_seats(root)
               if s.get("session_id") and str(s["session_id"]) not in launching)


def _check_thread_window(argv: list[str], *, here: bool = False) -> None:
    """A wt command targets the thread's own window and nothing else: `-w convoy-<8 hex>`
    as its first argument, never `-w 0` (the most recently used window, i.e. wherever the
    person last clicked) and never a second -w; then new-tab or split-pane.

    `here` is the one exception: the person's explicit opt-in to split the window they
    are working in, which is what `-w 0` names; then the command must be `-w 0
    split-pane`, never new-tab."""
    parts = [str(a) for a in argv]
    if here:
        if len(parts) < 4 or parts[1] != "-w" or parts[2] != "0":
            raise ValueError("refuse a here launch outside window 0 (-w 0 split-pane)")
        if parts[3] not in ("split-pane", "sp"):
            raise ValueError("a here launch is a split-pane, never new-tab")
    elif len(parts) < 4 or parts[1] != "-w" or not _THREAD_WINDOW.match(parts[2]):
        raise ValueError("refuse wt outside the thread's own window (-w convoy-<8 hex>)")
    if parts.count("-w") != 1 or "--window" in parts:
        raise ValueError("refuse a second window target")
    if parts[3] in ("nw", "new-window", "rename-window"):
        raise ValueError("refuse nw/rename-window as first command")
    if parts[3] not in ("nt", "new-tab", "split-pane", "sp"):
        raise ValueError("first command must be new-tab or split-pane")


def is_conductor(to: Any) -> bool:
    return str(to or "").strip().lower() in _CONDUCTORS


def resume_target(seat: dict[str, Any]) -> str | None:
    """Vendor id passed to --resume/resume subcommand. Never invent.

    Token-to-harness binding: a token is returned only
    when the row's resume_for matches its current `to` — BOTH keys guarded, so
    nulling `resume` on swap cannot leave a vendor_session_id shadow riding
    another harness's argv. Rows without resume_for predate the field: their
    whole-row write means the token was minted under the row's own `to`."""
    rf = seat.get("resume_for")
    if isinstance(rf, str) and rf.strip():
        to = str(seat.get("to") or "").strip()
        if rf.strip() != to:
            return None
    for key in ("vendor_session_id", "resume"):
        val = seat.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def session_store_has(to: Any, worktree: Any, sid: str) -> bool:
    """Whether the harness's own store already holds conversation `sid` for this worktree.
    Read, never written. Only the two harnesses whose --session-id Convoy
    passes have a store to read here; every other harness answers False.

    claude: ~/.claude/projects/<worktree, each non-alphanumeric as ->/<sid>.jsonl. claude
            --resume looks in the project folder of the cwd it starts in, so only this
            worktree's folder counts.
    grok:   ~/.grok/sessions/<worktree, URL-encoded>/<sid>/
    """
    if not isinstance(worktree, str) or not worktree.strip() or not sid:
        return False
    home = Path.home()
    bin_ = _harness_bin(to)
    if bin_ == "claude":
        slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in worktree)
        return (home / ".claude" / "projects" / slug / f"{sid}.jsonl").is_file()
    if bin_ == "grok":
        return (home / ".grok" / "sessions" / quote(worktree, safe="") / sid).is_dir()
    return False


def _is_convoy_grok_agent(agent: str) -> bool:
    """The agent file earlier Convoy versions wrote into a worktree and stored on the seat row.
    Convoy no longer writes it, so it is not passed: only an agent the person chose rides argv."""
    norm = "/" + agent.strip().replace("\\", "/").lower().lstrip("/")
    return norm.endswith("/.grok/agents/convoy-neuron.md")


def resume_argv(seat: dict[str, Any]) -> list[str]:
    """Argv we WOULD exec. No spawn. Native harness resume only.

    FileName is shutil.which absolute path when found, else the bare harness name.
    Grok keeps seat identity flags:
        [exe, '-m', MODEL?, '--agent', PATH?, EFFORT_FLAG?, '--resume', sid]
    Codex resume shape:
        [exe, '-m', MODEL?, '-c', 'model_reasoning_effort=V'?, 'resume', sid]
    Other harnesses:
        [exe, MODEL_FLAG, MODEL?, EFFORT_FLAG?, '--resume', sid]
    MODEL_FLAG and EFFORT_FLAG are the contract's evidenced flags for the seat's
    declared model and effort (grok --reasoning-effort, claude --effort, agy
    --effort, pi --thinking, codex -c model_reasoning_effort=); absent when the
    contract has no evidenced flag (cursor-agent, hermes effort).
    First-run seat with no vendor UUID: no resume token is passed.
    Never -d, never `--` separator, never -p/-c, never ola-brain, never side-chat, never wt.
    """
    sid = resume_target(seat)
    to = str(seat.get("to") or "").strip()
    if is_conductor(to):
        raise ValueError("conductor grok-bot is not a window")
    binary = _absolute_harness(_harness_bin(to))
    if not binary:
        raise ValueError("refuse empty harness")
    argv = [binary]
    # The seat's declared model rides argv through the contract's evidenced
    # flag (grok/codex/hermes -m, claude/agy/pi --model). Without it the
    # vendor's config default wins: a relaunched codex seat declared with one
    # model and effort boots with whatever config.toml names instead.
    argv.extend(model_argv(to, effective_model(to, seat.get("model"), seat.get("effort"))))
    if _harness_bin(to) == "grok":
        agent = seat.get("agent")
        if isinstance(agent, str) and agent.strip() and not _is_convoy_grok_agent(agent):
            argv.extend(["--agent", agent.strip()])
    # Declared effort rides argv only through the contract's evidenced flag,
    # and only as a value that harness's --help lists (effort_argv re-checks).
    argv.extend(effort_argv(to, seat.get("effort")))
    # A minted id names a conversation that does not exist yet, so the
    # first launch DECLARES it (--session-id) and every later one resumes it
    # (--resume). claude and grok both refuse --session-id for an id that
    # already exists, so the flag is passed exactly once. The pane host's
    # `incarnations` never reached a row, so every relaunch re-declared; the
    # harness's own session store is the fact that decides.
    if (
        sid
        and seat.get("resume_minted")
        and not seat.get("incarnations")
        and not session_store_has(to, seat.get("worktree"), sid)
    ):
        flag = session_id_flag(to)
        if flag:
            argv.extend([flag, sid])
            sid = None
    # First-run seat: no vendor UUID yet. Do not pass --resume.
    if sid:
        if _harness_bin(to) == "codex":
            argv.extend(["resume", sid])
        elif _harness_bin(to) == "agy":
            # agy --help has no --resume; it resumes via --conversation <ID>
            argv.extend(["--conversation", sid])
        else:
            argv.extend(["--resume", sid])
    # Deliberate exception (seat lifecycle): join/swap set a
    # one-shot boot_prompt delivered as an initial POSITIONAL prompt — every
    # harness documents one; the session stays interactive (this is not -p).
    # It is the seated-ack delivery mechanism; seated_ack clears the field.
    bp = seat.get("boot_prompt")
    if isinstance(bp, str) and bp.strip():
        if _harness_bin(to) == "agy":
            argv.extend(["--prompt-interactive", bp])
        else:
            argv.append(bp)
    return argv


def _is_claude(to: Any) -> bool:
    key = str(to or "").strip().lower()
    if key in ("claude", "claude.exe"):
        return True
    base = _basename_lower(key)
    return base in ("claude", "claude.exe") or _harness_bin(str(to or "")) == "claude"


def _sanitize_title_token(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    leaf = text.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", leaf).strip("-")
    return cleaned[:32]


def _pane_title(seat: dict[str, Any]) -> str:
    explicit = seat.get("title")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    to = str(seat.get("to") or "seat").strip() or "seat"
    for key in ("resume", "vendor_session_id", "session_id", "resume_key", "worktree"):
        token = _sanitize_title_token(seat.get(key))
        if token:
            return to + "-" + token
    return to + "-pane"


def _claude_settings_path(worktree: Path) -> Path:
    """The worktree file Convoy writes: the local one, which Claude Code keeps out of git."""
    return Path(worktree) / ".claude" / "settings.local.json"


def _convoy_named(rel: str) -> bool:
    """A worktree path only Convoy names: its convoy-* files, and Claude's local settings file,
    which is never committed by convention. Anything else could be the person's own."""
    return "convoy" in rel.lower() or rel == ".claude/settings.local.json"


TRACKED_SETTINGS_NOTE = (".claude/settings.local.json is tracked in git; Convoy did not write its hooks "
                         "or auto-compact there")


def dry_opt_in_refusal(verb: str, *, cli: bool = False) -> str:
    """Refuse the person-ownable repo-file opt-in on a dry launch, before those writes.

    A dry launch writes nothing at all (home files, trust stores, worktree files and
    .git/info/exclude included); its first_run card lists what a live run would write.
    """
    ask = "--write-repo-files needs a live run, not --dry-run" if cli else "write_repo_files=true needs dry_run=false"
    return ask + ": a dry " + verb + " writes no person file"


# The home key Convoy may add to ~/.claude/settings.json, when it is missing.
HOME_SETTINGS_KEY = "skipDangerousModePermissionPrompt"


def repo_files_for(to: Any) -> list[str]:
    """The files a first run would write into a worktree for this harness, relative and sorted."""
    from .identity import CLAUDE_SETTINGS_RELATIVE, GROK_INBOX_HOOK_RELATIVE
    from .inbox import POINTER_RELS
    # The pointer, the hooks and the root pointers, for every harness. Skills ship from the
    # convoy plugin, and Codex's hooks come from it too.
    files = {Path("AGENTS.md"), *POINTER_RELS, CLAUDE_SETTINGS_RELATIVE, GROK_INBOX_HOOK_RELATIVE}
    return sorted(f.as_posix() for f in files)


def _claude_home_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _claude_home_state_path() -> Path:
    return Path.home() / ".claude.json"


def _is_windows_like_path(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", text or ""))


def _project_path_variants(worktree: Path) -> list[str]:
    """Path spellings for ~/.claude.json projects keys (slashes + backslashes)."""
    try:
        base = str(worktree.resolve())
    except Exception:
        base = str(worktree)
    variants = [base]
    if _is_windows_like_path(base) or "\\" in base:
        slash = base.replace("\\", "/")
        back = base.replace("/", "\\")
        if slash not in variants:
            variants.append(slash)
        if back not in variants:
            variants.append(back)
    return variants


def _is_home_claude_settings(path: Path) -> bool:
    """True if path is the user's global ~/.claude/settings.json.

    Refuse project-write when worktree is home (that path would also set
    permissions.defaultMode). Dedicated home merge writes only
    skipDangerousModePermissionPrompt.
    """
    try:
        home = Path.home().resolve()
        resolved = path.resolve()
    except Exception:
        return False
    return resolved == (home / ".claude" / "settings.json")


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """The file's JSON object; {} when the file is missing; None when it exists but is not a JSON
    object, so a caller refuses to write rather than replace a file it cannot read."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_json_dict(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _claude_trust_accepted(projects: dict[str, Any], worktree: Path) -> bool:
    """True when ANY spelling of worktree already carries hasTrustDialogAccepted."""
    for key in _project_path_variants(worktree):
        node = projects.get(key)
        if isinstance(node, dict) and node.get("hasTrustDialogAccepted") is True:
            return True
    return False


def _write_claude_trust_projects(worktree: Path, home: Path | None = None) -> tuple[Path, bool]:
    """Persist hasTrustDialogAccepted for both slash spellings of worktree.

    The ONE writer of ~/.claude.json projects trust (first-run prepare and the
    hooks-trust pass both call it). Returns (store, written); an already-accepted
    store (any spelling) is read, never rewritten.
    """
    state_path = _claude_home_state_path() if home is None else home / ".claude.json"
    data = _read_json_object(state_path)
    if data is None:
        return state_path, False  # a store that cannot be read is never replaced
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    if _claude_trust_accepted(projects, worktree):
        return state_path, False
    for key in _project_path_variants(worktree):
        node = projects.get(key)
        if not isinstance(node, dict):
            node = {}
        node["hasTrustDialogAccepted"] = True
        projects[key] = node
    data["projects"] = projects
    _write_json_dict(state_path, data)
    return state_path, True


# --- hooks-trust dialog: never shown again ---------------------------------
# The answer is always "2. Trust all and continue". Each
# store below was read on a live machine (read-only) before any
# write; the format written is the format found, appended, never rewritten.
#   grok   ~/.grok/trusted_folders.toml   [folders.'<path>'] trusted = true / decided_at = <epoch>
#          named by ~/.grok/docs/user-guide/10-hooks.md as the unified folder-trust store
#   codex  ~/.codex/config.toml           [projects.'<path>'] trust_level = "trusted"
#          [hooks.state.'<file>:<event>:<i>:<j>'] trusted_hash = "sha256:..." exists too, but
#          the hash input is not derivable from the hook file -> never written ("format unverified");
#          `codex --help` offers only --dangerously-bypass-hook-trust per invocation.
#   claude ~/.claude.json                 projects[<path>].hasTrustDialogAccepted = true
# Anything else: store null, written false; the human answers the dialog.

GROK_TRUST_STORE = (".grok", "trusted_folders.toml")
CODEX_CONFIG = (".codex", "config.toml")
CLAUDE_STATE = (".claude.json",)


def _toml_key(text: str) -> str:
    """Quoted TOML key for a filesystem path: literal when it can be, else escaped basic."""
    if "'" not in text:
        return "'" + text + "'"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_load(path: Path) -> dict[str, Any] | None:
    """Parsed dict, {} when absent, None when unparseable (then we write nothing)."""
    if not path.is_file():
        return {}
    try:
        import tomllib
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _same_path_key(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _toml_append(path: Path, block: str) -> bool:
    """Append a table to a person's TOML store, keeping its byte order mark. The result must still
    parse, or nothing is written; False then."""
    import tomllib
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.read_bytes() if path.is_file() else b""
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    existing = raw[len(bom):].decode("utf-8")
    sep = "" if (not existing or existing.endswith("\n\n")) else ("\n" if existing.endswith("\n") else "\n\n")
    text = existing + sep + block
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    path.write_bytes(bom + text.encode("utf-8"))
    return True


def _trust_row(vendor: str | None, store: Path | None, *, written: bool, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {"vendor": vendor, "store": str(store) if store else None, "written": written, "reason": reason, **extra}


def _trust_grok(wt: str, home: Path, now: int) -> list[dict[str, Any]]:
    store = home.joinpath(*GROK_TRUST_STORE)
    data = _toml_load(store)
    if data is None:
        return [_trust_row("grok", store, written=False, reason="store unparseable; left alone")]
    folders = data.get("folders") if isinstance(data.get("folders"), dict) else {}
    mine = [v for k, v in folders.items() if _same_path_key(k, wt)]
    if any(isinstance(v, dict) and v.get("trusted") is True for v in mine):
        return [_trust_row("grok", store, written=False, reason="already trusted")]
    if mine:
        # The person decided for this folder; a second table of the same name would not parse.
        return [_trust_row("grok", store, written=False, reason="table exists with another trust; left alone")]
    if not _toml_append(store, "[folders." + _toml_key(wt) + "]\ntrusted = true\ndecided_at = " + str(int(now)) + "\n"):
        return [_trust_row("grok", store, written=False, reason="the result would not parse; left alone")]
    return [_trust_row("grok", store, written=True, reason=None)]


def _trust_codex(wt: str, home: Path) -> list[dict[str, Any]]:
    store = home.joinpath(*CODEX_CONFIG)
    hooks = _trust_row("codex", store, written=False, reason="format unverified", key="hooks.state",
                       evidence="trusted_hash = sha256 of an input not derivable from the hook file")
    data = _toml_load(store)
    if data is None:
        return [_trust_row("codex", store, written=False, reason="store unparseable; left alone", key="projects"), hooks]
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    mine = [v for k, v in projects.items() if _same_path_key(k, wt)]
    if any(isinstance(v, dict) and v.get("trust_level") == "trusted" for v in mine):
        return [_trust_row("codex", store, written=False, reason="already trusted", key="projects"), hooks]
    if mine:
        # The person decided for this project; a second table of the same name would not parse.
        return [_trust_row("codex", store, written=False, reason="table exists with another trust; left alone",
                           key="projects"), hooks]
    if not _toml_append(store, "[projects." + _toml_key(wt) + "]\ntrust_level = \"trusted\"\n"):
        return [_trust_row("codex", store, written=False, reason="the result would not parse; left alone",
                           key="projects"), hooks]
    return [_trust_row("codex", store, written=True, reason=None, key="projects"), hooks]


# Codex keys a plugin hook "{plugin_id}:{relative_path}:{event}:{group}:{handler}"; the convoy
# plugin (Deploy-Forward/plugins) declares `hooks: ./codex-hooks.json`, and plugin_id is
# convoy@<marketplace> (convoy@deploy-forward from the published one). One review by the person covers every project,
# where a project `.codex/hooks.json` is keyed by its absolute path and so is new in every worktree.
CODEX_DEFAULT_PLUGIN_ID = "convoy@deploy-forward"
CODEX_PLUGIN_HOOK_EVENTS = ("stop", "post_tool_use")
_CODEX_HOOK_TAIL = ("until then this neuron cannot be woken by a send and its identity rests on its folder")
CODEX_HOOKS_WARNINGS = {
    "untrusted": "codex hooks not trusted: run /hooks in Codex and trust the two {plugin} hooks; " + _CODEX_HOOK_TAIL,
    "disabled": "codex hooks disabled: run /hooks in Codex and enable the two {plugin} hooks; " + _CODEX_HOOK_TAIL,
    "plugin-disabled": ("codex convoy plugin disabled: enable {plugin} in Codex "
                        "([plugins.\"{plugin}\"] enabled = true); " + _CODEX_HOOK_TAIL),
    "unknown": "codex hook trust unknown: {reason}",
}
_TRUST_ORDER = ("trusted", "disabled", "untrusted")


def codex_plugin_hook_keys(plugin_id: str) -> tuple[str, ...]:
    return tuple(plugin_id + ":codex-hooks.json:" + event + ":0:0" for event in CODEX_PLUGIN_HOOK_EVENTS)


def _codex_config_path(home: Path | str | None) -> Path:
    """$CODEX_HOME/config.toml as Codex reads it; an explicit home wins (tests, a named machine)."""
    if home is not None:
        return Path(home).joinpath(*CODEX_CONFIG)
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home) / CODEX_CONFIG[-1] if codex_home else Path.home().joinpath(*CODEX_CONFIG)


def codex_hooks_trusted(home: Path | str | None = None) -> dict[str, Any]:
    """Read-only: will Codex run the convoy plugin's two hooks, by its own config?

    The plugin ids are the enabled `convoy@*` entries under [plugins] (convoy@deploy-forward when
    none is listed; disabled when every listed one is). Per key: disabled when its hook-state row says `enabled = false`, trusted
    when it records a trusted_hash, else untrusted. state is the best plugin's worst key, or
    unknown (with `reason`) when the config cannot be read or parsed. A recorded hash is all this
    reads; whether it still matches the installed plugin's hook is Codex's check. Never writes."""
    store = _codex_config_path(home)
    out: dict[str, Any] = {"state": "untrusted", "keys": {}, "store": str(store), "plugin": CODEX_DEFAULT_PLUGIN_ID}
    data: dict[str, Any] = {}
    if store.is_file():
        try:
            import tomllib
            data = tomllib.loads(store.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            out.update({"state": "unknown", "reason": "could not read " + str(store) + ": " + str(e),
                        "keys": {k: "unknown" for k in codex_plugin_hook_keys(CODEX_DEFAULT_PLUGIN_ID)}})
            return out
    plugins = data.get("plugins") if isinstance(data.get("plugins"), dict) else {}
    listed = sorted(k for k in plugins if k.startswith("convoy@"))
    ids = [k for k in listed if not (isinstance(plugins[k], dict) and plugins[k].get("enabled") is False)]
    if listed and not ids:
        # Every listed convoy plugin is disabled: Codex runs none of its hooks, whatever hashes remain.
        out.update({"state": "disabled", "plugin": listed[0], "plugin_disabled": True,
                    "keys": {k: "disabled" for k in codex_plugin_hook_keys(listed[0])}})
        return out
    ids = ids or [CODEX_DEFAULT_PLUGIN_ID]
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    state = hooks.get("state") if isinstance(hooks.get("state"), dict) else {}
    best = None
    for plugin_id in ids:
        for k in codex_plugin_hook_keys(plugin_id):
            row = state.get(k) if isinstance(state.get(k), dict) else {}
            h = row.get("trusted_hash")
            out["keys"][k] = ("disabled" if row.get("enabled") is False
                              else "trusted" if isinstance(h, str) and h.strip() else "untrusted")
        worst = max((out["keys"][k] for k in codex_plugin_hook_keys(plugin_id)), key=_TRUST_ORDER.index)
        if best is None or _TRUST_ORDER.index(worst) < _TRUST_ORDER.index(best[1]):
            best = (plugin_id, worst)
    out["plugin"], out["state"] = best
    return out


def codex_hooks_warning(harnesses: Iterable[Any], home: Path | str | None = None) -> str | None:
    """The card warning, in the state's own words, when any of these harnesses is codex and Codex
    will not run (or may not run) the plugin's hooks."""
    if not any(_harness_bin(str(h or "")) == "codex" for h in harnesses):
        return None
    trust = codex_hooks_trusted(home)
    if trust["state"] == "trusted":
        return None
    state = "plugin-disabled" if trust.get("plugin_disabled") else trust["state"]
    return CODEX_HOOKS_WARNINGS[state].format(plugin=trust["plugin"], reason=trust.get("reason"))


def _trust_claude(wt: str, home: Path) -> list[dict[str, Any]]:
    store = home.joinpath(*CLAUDE_STATE)
    if store.is_file():
        try:
            json.loads(store.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return [_trust_row("claude", store, written=False, reason="store unparseable; left alone")]
    # reuse the existing writer: one code path for ~/.claude.json projects trust
    store, written = _write_claude_trust_projects(Path(wt), home=home)
    return [_trust_row("claude", store, written=written, reason=None if written else "already trusted")]


def ensure_hook_trust(
    seat: dict[str, Any],
    *,
    home: Path | str | None = None,
    now_fn: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Pre-trust the seat's worktree in its vendor's evidenced trust store.

    Returns {ok, worktree, trust: [{vendor, store, written, reason, ...}]}.
    Unknown vendor -> store null, nothing written. Temp worktree (test
    residue) -> never trusted machine-wide. Unparseable store -> left alone.
    """
    to = str((seat or {}).get("to") or "").strip()
    vendor = _harness_bin(to) if to else ""
    wt_raw = (seat or {}).get("worktree")
    out: dict[str, Any] = {"ok": True, "worktree": None, "trust": []}
    if not ((isinstance(wt_raw, str) and wt_raw.strip()) or isinstance(wt_raw, Path)):
        out["ok"] = False
        out["error"] = "no worktree"
        return out
    try:
        wt = str(Path(wt_raw).resolve())
    except OSError:
        wt = str(wt_raw)
    out["worktree"] = wt
    base = Path(home) if home is not None else Path.home()
    if is_temp_root(wt):
        out["trust"] = [_trust_row(vendor or to or None, None, written=False, reason="temp worktree; never trusted machine-wide")]
        return out
    now = int((now_fn or (lambda: int(time.time())))())
    try:
        if vendor == "grok":
            out["trust"] = _trust_grok(wt, base, now)
        elif vendor == "codex":
            out["trust"] = _trust_codex(wt, base)
        elif _is_claude(to):
            out["trust"] = _trust_claude(wt, base)
        else:
            out["trust"] = [_trust_row(to or None, None, written=False, reason="no evidenced trust store for " + (to or "unknown"))]
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
    return out


CONVOY_PATH_BEGIN = "# >>> convoy harness PATH >>>"
CONVOY_PATH_END = "# <<< convoy harness PATH <<<"
CONVOY_PATH_BLOCK = (
    "# >>> convoy harness PATH >>>\n"
    "# Interactive non-login bash skips .profile. Desktop terminals then miss\n"
    "# ~/.local/bin (claude, codex) even when the MCP process PATH has them.\n"
    'if [ -d "$HOME/.local/bin" ]; then export PATH="$HOME/.local/bin:$PATH"; fi\n'
    'if [ -d "$HOME/.grok/bin" ]; then export PATH="$HOME/.grok/bin:$PATH"; fi\n'
    "# <<< convoy harness PATH <<<\n"
)


def ensure_interactive_path(home: Path | None = None, *, write: bool = True) -> dict[str, Any]:
    """Ungate harness bins for interactive non-login bash (desktop terminals).

    roster.present is shutil.which on the MCP/agent process PATH. That is not
    the PATH of an already-open desktop terminal. Interactive bash reads
    ~/.bashrc and skips ~/.profile, so ~/.local/bin (claude, codex) can be
    installed and still command-not-found. Grok's installer writes .bashrc;
    Debian/Ubuntu put ~/.local/bin only in .profile.

    Writes an idempotent block into ~/.bashrc. No-op on Windows (WT inherits
    user PATH). Does not clobber vendor installer blocks. Does not source
    the file into a foreign PID. write=False (a read verb) writes nothing and
    names the file in would_write instead.
    """
    out: dict[str, Any] = {
        "ok": True,
        "path_written": False,
        "path_bashrc": None,
        "path_ok": False,
        "path_host": "bash-interactive",
    }
    if os.name == "nt":
        out["path_ok"] = True
        out["path_host"] = "windows-user"
        return out
    home_path = Path(home) if home is not None else Path.home()
    bashrc = home_path / ".bashrc"
    out["path_bashrc"] = str(bashrc)
    try:
        text = bashrc.read_text(encoding="utf-8") if bashrc.is_file() else ""
        if CONVOY_PATH_BEGIN in text:
            out["path_ok"] = True
            return out
        if not write:
            out["would_write"] = [str(bashrc)]
            return out
        prefix = text.rstrip()
        new = (prefix + "\n\n" if prefix else "") + CONVOY_PATH_BLOCK
        if not new.endswith("\n"):
            new += "\n"
        bashrc.write_text(new, encoding="utf-8")
        out["path_written"] = True
        out["path_ok"] = True
        return out
    except Exception as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


# The test guard sets this to a reading with no source for a whole run: a live launch under
# test then probes no vendor CLI for its heartbeat. None in production (the vendor's reading).
TEST_LAUNCH_USAGE_READING: Callable[[str], dict[str, Any]] | None = None


def _first_run_plan(out: dict[str, Any], to: str, wt: Any, write_repo_files: bool | None) -> dict[str, Any]:
    """What a live first run would write, read from disk and never written (a dry run).

    dry_run_writes: the worktree files a live run would write (relative); would_write keeps
    its live meaning (person files only an opt-in writes); would_write_home: the home files
    and trust stores."""
    out["dry_run"] = True
    out["prepared"] = False
    out["would_write_home"] = []
    out["hook_trust_skipped"] = "dry-run"
    if os.name != "nt":
        bashrc = Path.home() / ".bashrc"
        try:
            has_block = bashrc.is_file() and CONVOY_PATH_BEGIN in bashrc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            has_block = False
        out["path_bashrc"] = str(bashrc)
        out["path_ok"] = has_block
        if not has_block:
            out["would_write_home"].append(str(bashrc))
    else:
        out["path_ok"] = True
        out["path_host"] = "windows-user"
    has_wt = (isinstance(wt, str) and wt.strip()) or isinstance(wt, Path)
    if has_wt:
        wt_path = Path(wt)
        try:
            home_worktree = wt_path.resolve() == Path.home().resolve()
        except OSError:
            home_worktree = False
        if not home_worktree:
            from . import repo as _repo
            person_files = write_repo_files is True or (write_repo_files is None and (
                _repo.repo_files_opted_in(wt_path) or _repo.is_minted_worktree(wt_path)))
            out["write_repo_files"] = bool(person_files)
            files = repo_files_for(to)
            if write_repo_files is False:
                out["would_write"] = files
                live_writes: list[str] = []
            else:
                # would_write keeps its live meaning (person files only an opt-in writes).
                from .identity import CLAUDE_SETTINGS_RELATIVE, CODEX_HOOKS_MIGRATION_NOTE, person_files_missing, stale_codex_hooks
                local_rel = CLAUDE_SETTINGS_RELATIVE.as_posix()
                skip = {local_rel} if _repo.is_tracked(wt_path, local_rel) else set()
                if skip:
                    out["would_write"].append(local_rel)
                    out["notes"].append(TRACKED_SETTINGS_NOTE)
                if not person_files:
                    out["would_write"] = sorted(set(out["would_write"]) | set(person_files_missing(wt_path)))
                if _harness_bin(to) == "codex" and stale_codex_hooks(wt_path):
                    out["notes"].append(CODEX_HOOKS_MIGRATION_NOTE)
                live_writes = [f for f in files if (person_files or _convoy_named(f)) and f not in skip]
            # dry_run_writes: what the live run would write into this worktree.
            out["dry_run_writes"] = sorted(set(live_writes) | ({".git/info/exclude"} if live_writes else set()))
    if not _is_claude(to):
        return out
    if not has_wt:
        out["ok"] = False
        out["error"] = "no worktree"
        return out
    wt_path = Path(wt)
    if _is_home_claude_settings(_claude_settings_path(wt_path)):
        out["ok"] = False
        out["error"] = "refuse home ~/.claude/settings.json"
        return out
    try:
        if wt_path.resolve() == Path.home().resolve():
            out["ok"] = False
            out["error"] = "refuse home dir"
            return out
    except OSError:
        pass
    out["home_key"] = HOME_SETTINGS_KEY
    home_path = _claude_home_settings_path()
    out["settings_home"] = str(home_path)
    home_data = _read_json_object(home_path)
    if home_data is None:
        out["home_error"] = "unparseable"  # a live run leaves it alone too
    elif HOME_SETTINGS_KEY not in home_data:
        out["would_write_home"].append(str(home_path))
    if write_repo_files is not False:
        out["settings"] = str(_claude_settings_path(wt_path))
        state = _claude_home_state_path()
        out["trust_settings_home"] = str(state)
        if _read_json_object(state) is None:
            out["trust_error"] = "unparseable"
        else:
            out["would_write_home"].append(str(state))
    return out


def ensure_first_run(seat: dict[str, Any], root: Path | str | None = None, live: bool = True, *,
                     write_repo_files: bool | None = None) -> dict[str, Any]:
    """Ungate first-run Claude bypass warning for the thread worktree.

    Project {worktree}/.claude/settings.local.json: autoCompactEnabled true (a
    neuron runs unattended and must compact on its own) beside the hooks, written
    only when it changes. Never permissions or skipDangerousModePermissionPrompt in
    any project file: the launch argv carries the mode.
    User ~/.claude/settings.json: add ONLY skipDangerousModePermissionPrompt true,
    and only when the key is missing; home_written and home_key say so.
    write_repo_files False: nothing is written into the worktree (no pointer, hooks,
    agent, settings or trust); would_write lists what would be. True: every file.
    None (a launch): every file in a minted worktree, or where the person opted in before
    (repo.repo_files_opted_in; True records it); in the person's repo only the Convoy-named
    ones. would_write and the Codex migration note are read from disk. A
    .claude/settings.local.json git tracks is never written. trust_stores_written names each
    home trust store this call wrote.
    User ~/.claude.json: set projects[worktree].hasTrustDialogAccepted=true
    for both slash spellings of the worktree key.
    Never write ~/.claude if worktree IS the home dir.
    Grok/codex: no Claude settings write. All harnesses with a non-home
    worktree get the AGENTS.md pointer to the Convoy plugin skills. No skill text is
    written and nothing is removed; identity_removed stays empty. Persona is role.md, not CLI.
    Never ola-brain, side-chat, grok -p/-c, --append-system-prompt.
    """
    to = str((seat or {}).get("to") or "").strip()
    wt = (seat or {}).get("worktree")
    out: dict[str, Any] = {
        "ok": True,
        "to": to or None,
        "worktree": str(wt) if wt else None,
        "prepared": True,
        "wrote": False,
        "settings": None,
        "home_written": False,
        "settings_home": None,
        "trust_written": False,
        "trust_settings_home": None,
        "path_written": False,
        "path_bashrc": None,
        "path_ok": False,
        "path_host": None,
        # identity_* names kept for callers: the pointer write, not an identity skill.
        # identity_removed stays empty: Convoy deletes nothing in a worktree.
        "identity_written": False,
        "identity_removed": [],
        "identity_agents": None,
        "inbox_hook_written": False,
        "inbox_hook": None,
        "hook_trust": [],
        "write_repo_files": bool(write_repo_files),
        "would_write": [],
        "left_visible": [],
        "notes": [],
        "trust_stores_written": [],
        "home_key": None,
    }
    if not live:
        return _first_run_plan(out, to, wt, write_repo_files)
    settings_tracked = False
    path_card = ensure_interactive_path()
    out["path_written"] = bool(path_card.get("path_written"))
    out["path_bashrc"] = path_card.get("path_bashrc")
    out["path_ok"] = bool(path_card.get("path_ok"))
    out["path_host"] = path_card.get("path_host")
    has_wt = (isinstance(wt, str) and wt.strip()) or isinstance(wt, Path)
    home_worktree = False
    if has_wt:
        wt_path = Path(wt)
        try:
            home_worktree = wt_path.resolve() == Path.home().resolve()
        except Exception:
            home_worktree = False
        from . import repo as _repo
        from .identity import CLAUDE_SETTINGS_RELATIVE, CODEX_HOOKS_MIGRATION_NOTE, person_files_missing, stale_codex_hooks
        person_files = write_repo_files is True or (write_repo_files is None and (
            _repo.repo_files_opted_in(wt_path) or _repo.is_minted_worktree(wt_path)))
        out["write_repo_files"] = person_files
        if not home_worktree and write_repo_files is False:
            out["would_write"] = repo_files_for(to)
        elif not home_worktree:
            if write_repo_files is True:
                _repo.record_repo_files_opt_in(wt_path)
            # info/exclude never hides a tracked file: a settings.local.json the person commits is theirs.
            local_rel = CLAUDE_SETTINGS_RELATIVE.as_posix()
            settings_tracked = _repo.is_tracked(wt_path, local_rel)
            skip: set[str] = set()
            if settings_tracked:
                skip.add(local_rel)
                out["would_write"].append(local_rel)
                out["notes"].append(TRACKED_SETTINGS_NOTE)
            if not person_files:
                out["would_write"] = sorted(set(out["would_write"]) | set(person_files_missing(wt_path)))
            if _harness_bin(to) == "codex" and stale_codex_hooks(wt_path):
                out["notes"].append(CODEX_HOOKS_MIGRATION_NOTE)
            ident = install_neuron_identity(wt_path, person_files=person_files)
            out["identity_written"] = bool(ident.get("written"))
            out["identity_removed"] = list(ident.get("removed") or [])
            out["identity_agents"] = ident.get("agents")
            if ident.get("error"):
                out["identity_error"] = ident["error"]
            out["notes"].extend(ident.get("warnings") or [])
            # Hook files only matter to a launched pane, and resolving the hook
            # command probes a shell; a dry bring-up (no runner) skips it.
            if live:
                hook_card = ensure_inbox_hooks(wt_path, root=root, harness=to, skip=skip)
                # Launch heartbeat: the chair's vendor reading
                # lands as its own kind=usage row at launch, so the thread tab
                # is explicit before the first tool call. Only a reading the
                # vendor gave (require_source); never blocks the launch.
                out["usage_heartbeat"] = None
                sid = (seat or {}).get("session_id")
                if root is not None and isinstance(sid, str) and sid.strip():
                    try:
                        from .inbox import stamp_usage_row
                        hb = stamp_usage_row(Path(root), sid.strip(), to, require_source=True,
                                             probe_fn=TEST_LAUNCH_USAGE_READING)
                        out["usage_heartbeat"] = hb.get("ts") if hb else None
                    except Exception as e:  # noqa: BLE001 - a heartbeat must never break a launch
                        # Any error, expected or not, is recorded on the card and the launch goes on.
                        out["usage_heartbeat_error"] = type(e).__name__ + ": " + str(e)
            else:
                hook_card = {"ok": True, "written": False, "command": None, "kinds": None, "skipped": "dry-run"}
            out["inbox_hook_written"] = bool(hook_card.get("written"))
            out["inbox_hook"] = hook_card.get("command")
            out["inbox_hook_kinds"] = hook_card.get("kinds")
            grok_hook = (hook_card.get("grok_hook") or {}).get("hook")
            claude_hook = (hook_card.get("claude_hook") or {}).get("hook")
            out["inbox_grok_hook"] = grok_hook
            out["inbox_claude_hook"] = claude_hook
            if hook_card.get("error"):
                out["inbox_hook_error"] = hook_card["error"]
            if hook_card.get("unresolved"):
                # The bare `convoy` does not resolve where the hooks run: refuse the launch rather
                # than start a pane whose hooks cannot fire, or bake an interpreter path instead.
                out.update({"ok": False, "hook_refused": True, "error": hook_card.get("error")})
                return out
            # Vendor trust stores are machine-wide: written only on a live
            # bring-up, never on --dry-run / crew without --launch.
            if live:
                out["hook_trust"] = ensure_hook_trust(seat).get("trust") or []
                out["trust_stores_written"] = [r["store"] for r in out["hook_trust"] if r.get("written") and r.get("store")]
            else:
                out["hook_trust"] = []
                out["hook_trust_skipped"] = "dry-run"
            # Keep Convoy's machine state out of git, so a neuron's `git add -A` cannot commit it. The
            # exclude is shared by every worktree of the clone, so only Convoy-named paths go in,
            # anchored; a file the person could own (AGENTS.md, a hooks.json, an end command) stays
            # visible and is named in left_visible instead.
            written = [f for f in repo_files_for(to) if (person_files or _convoy_named(f)) and f not in skip]
            out["left_visible"] = [f for f in written if not _convoy_named(f)]
            try:
                record = ["/" + _repo.REPO_FILES_RECORD.as_posix()] if write_repo_files is True else []
                out["excluded"] = _repo.exclude_paths(wt_path, ["/" + f for f in written if _convoy_named(f)] + record)
            except OSError as e:
                out["excluded"] = False
                out["exclude_error"] = type(e).__name__ + ": " + str(e)
    if not _is_claude(to):
        return out
    if not (isinstance(wt, str) and wt.strip()) and not isinstance(wt, Path):
        out["ok"] = False
        out["prepared"] = False
        out["error"] = "no worktree"
        return out
    wt_path = Path(wt)
    settings_path = _claude_settings_path(wt_path)
    if _is_home_claude_settings(settings_path):
        out["ok"] = False
        out["prepared"] = False
        out["error"] = "refuse home ~/.claude/settings.json"
        return out
    try:
        if wt_path.resolve() == Path.home().resolve():
            out["ok"] = False
            out["prepared"] = False
            out["error"] = "refuse home dir"
            return out
    except Exception:
        pass
    try:
        home_path = _claude_home_settings_path()
        home_data = _read_json_object(home_path)
        out["home_key"] = HOME_SETTINGS_KEY
        out["settings_home"] = str(home_path)
        if home_data is None:
            out["home_error"] = "unparseable"  # never replace a file that cannot be read
        elif HOME_SETTINGS_KEY not in home_data:
            home_data[HOME_SETTINGS_KEY] = True
            _write_json_dict(home_path, home_data)
            out["home_written"] = True
        if write_repo_files is False:
            return out
        data = None if settings_tracked else _read_json_object(settings_path)
        if settings_tracked:
            pass
        elif data is None:
            out["settings_error"] = "unparseable"
        # A neuron runs unattended: it must compact on its own even when the
        # person turned auto-compact off in their own user settings.
        elif data.get("autoCompactEnabled") is not True or not settings_path.is_file():
            data["autoCompactEnabled"] = True
            _write_json_dict(settings_path, data)
            out["wrote"] = True
        out["settings"] = str(settings_path)
        if _read_json_object(_claude_home_state_path()) is None:
            out["trust_error"] = "unparseable"
            out["trust_settings_home"] = str(_claude_home_state_path())
            return out
        trust_path, trust_rewritten = _write_claude_trust_projects(wt_path)
        # trust_written: the key is present after this call (read back);
        # trust_rewritten: this call actually wrote (False when hook trust or a prior run already did)
        out["trust_written"] = True
        out["trust_rewritten"] = trust_rewritten
        out["trust_settings_home"] = str(trust_path)
        if trust_rewritten and str(trust_path) not in out["trust_stores_written"]:
            out["trust_stores_written"].append(str(trust_path))
        return out
    except Exception as e:
        out["ok"] = False
        out["prepared"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def _with_claude_live_flags(argv: list[str], to: Any) -> list[str]:
    """Live Claude argv includes --permission-mode bypassPermissions and --allow-dangerously-skip-permissions. Dry resume_argv does not.
    Other harnesses take their live-only flags from the contract's `live_flags`
    (cursor-agent: --trust --force, quoted from its --help)."""
    parts = [str(a) for a in argv]
    if not _is_claude(to):
        from .harness_contract import live_flags
        extra = [f for f in live_flags(to) if f not in parts]
        if extra:
            # before the positional boot prompt, which is always last when present
            bp = parts[-1] if len(parts) > 1 and not parts[-1].startswith("-") and parts[-1] != parts[0] and " " in parts[-1] else None
            if bp is not None:
                parts = parts[:-1] + extra + [bp]
            else:
                parts = parts + extra
        return parts
    if "--permission-mode" not in parts:
        parts.extend(["--permission-mode", "bypassPermissions"])
    if "--allow-dangerously-skip-permissions" not in parts:
        parts.append("--allow-dangerously-skip-permissions")
    if "--append-system-prompt" in parts:
        raise ValueError("refuse --append-system-prompt")
    return parts


# A window takes panes in tabs of at most this many, each tiled 2x2.
TAB_PANES = 4
HERE_MAX_PANES = 4


def _tile_step(i: int, first: bool) -> list[str]:
    """The wt commands that open pane i (0-based) of a tiled launch: tabs of four,
    each a 2x2 grid. Pane 1 of a tab is new-tab (the launch's first pane keeps the
    `first` rule: split-pane -V when the window already holds neurons), pane 2
    split-pane -V (right column), pane 3 move-focus left ; split-pane -H (bottom
    left), pane 4 move-focus right ; split-pane -H (bottom right). Pane 5 opens the
    next tab in the same window (the argv's one -w names it).

    Live-verified on Windows Terminal 1.24.11911.0: ten panes gave three tabs (4, 4, 2), each
    tab four equal quadrants in order 1 top-left, 2 top-right, 3 bottom-left, 4 bottom-right."""
    pos = i % TAB_PANES
    if pos == 0:
        if i == 0:
            return ["new-tab"] if first else ["split-pane", "-V"]
        return [";", "new-tab"]
    if pos == 1:
        return [";", "split-pane", "-V"]
    if pos == 2:
        return [";", "move-focus", "left", ";", "split-pane", "-H"]
    return [";", "move-focus", "right", ";", "split-pane", "-H"]


def isolated_wt_argv(thread: str | int, seats: list[dict[str, Any]], *, wt: str | None = None,
                     root: Path | str | None = None, raw: bool = False, window: str | None = None,
                     first: bool = True, here: bool = False, tile_offset: int = 0,
                     tile_total: int | None = None) -> list[str]:
    """Pure Windows Terminal argv for n seated neurons. Does not spawn.

    Every launch is an owned body: with `root` each pane runs
    `convoy.pane_host` instead of the harness exe, so the body's pid,
    incarnation and exit are recorded. The harness argv is still built and
    validated exactly as before (absolute exe, no wrapper, no `--`, no
    --append-system-prompt) and only then handed to the host, so nothing the
    gates refuse can ride in behind the interpreter. `raw=True` is the escape
    hatch for one release; without a root there is nothing to host against and
    the pure form is unchanged.

    One window per thread: every pane goes into the
    thread's own named window, `-w convoy-<8 hex of sha256(convoy_id)>`
    (targeted_launch.thread_window_name; `window` overrides it). The first command
    is new-tab when the window does not hold a live neuron yet (`first`), else
    split-pane; then split-pane -V / -H. wt splits the target window's focused pane,
    which inside the thread's own window is one of this thread's neurons.
    Never -w 0 (the most recently used window: wherever the person clicked last),
    except `here=True`: the person's explicit opt-in (`add --here`, `launch --here`)
    to a split of the window they are working in, which is exactly what -w 0 names.
    A here build is always split-pane, never new-tab.
    Live-verified 2026-10-04 on WT 1.24.11911.0: `-w convoy-<name> new-tab ...`
    then `-w convoy-<name> split-pane -V ...` gave one separate window with both
    panes, the working window untouched, no Help. The older `-w <thread-name>` Help
    note was a different argv shape. Never `--` before the harness exe (pops Help).
    Never nw / rename-window.
    Literal ';' WT separators via Start-Process -ArgumentList, not cmd ^;.
    No --append-system-prompt. Claude live flags on the inner argv.
    More than four panes tile: tabs of four, each a 2x2 grid (_tile_step, live-verified
    on WT 1.24.11911.0); four or fewer keep the new-tab / -V / -H chain.
    A here build takes at most four panes (the person's one window, no new tabs).
    tile_offset continues a layout another argv began (crew's canary is pane 1 of
    tab 1, the rest start at pane 2): panes are placed as if they followed
    tile_offset earlier ones, in a window that already holds them (first=False),
    and tile_total (default offset + n) decides whether the whole launch tiles.
    """
    name = str(thread if thread is not None else "").strip()
    # -w 0 is the most recently used window, i.e. where the person is. Only the
    # here placement may name it, because that is what --here means; every other
    # placement keeps the refusal.
    if here:
        window = "0"
        first = False
    elif name == "0" or str(window or "").strip() == "0":
        raise ValueError("refuse -w 0")
    panes = _pane_seats(list(seats or []))
    if not panes:
        raise ValueError("refuse empty seats")
    offset = max(0, int(tile_offset or 0))
    total = int(tile_total) if tile_total is not None else offset + len(panes)
    if here and total > HERE_MAX_PANES:
        raise ValueError("--here takes at most " + str(HERE_MAX_PANES) +
                         " neurons; drop --here to open them in the thread's window in tabs")
    tiled = total > TAB_PANES
    if offset:
        first = False   # the earlier panes are already in the window
    from .targeted_launch import root_thread_label, thread_pane_title, thread_window_name
    label = root_thread_label(root, name or None)
    if window is None:
        # The thread's convoy_id names its window; a rootless pure build falls back to the thread name.
        key = read_id(Path(root)) if root is not None else None
        window = thread_window_name(key or name or "thread")
    wt_bin = str(wt or "wt")
    argv: list[str] = [wt_bin, "-w", str(window)]
    records: list[tuple[str, list[str], str | None]] = []
    for i, seat in enumerate(panes):
        g = i + offset   # the pane's place in the whole launch
        if tiled:
            step = _tile_step(g, first)
            argv.extend(step[1:] if i == 0 and step[0] == ";" else step)
        elif i == 0 and first:
            argv.append("new-tab")
        else:
            if i > 0:
                argv.append(";")
            split = "-V" if g <= 1 else "-H"
            argv.extend(["split-pane", split])
        cwd = seat.get("worktree") or seat.get("cwd") or ""
        # Mint BEFORE the argv is built, because the launch record written
        # below is what run_host actually executes - it WINS over the argv
        # pane_child_argv rebuilds from the row. Minting only there left the
        # id on the row and off the command line, so the vendor made its own
        # session and the row named one that does not exist. Same condition
        # as the record: a raw or rootless build is a pure builder and writes
        # nothing, so it mints nothing either.
        if root is not None and not raw:
            from .resume_first import ensure_session_id
            seat = dict(ensure_session_id(Path(root), seat))
        inner = resume_argv(seat)
        override = seat.get("exe")
        if override:
            inner = [str(override), *inner[1:]]
        else:
            inner = [_absolute_harness(inner[0]), *inner[1:]]
        inner = _with_claude_live_flags(inner, seat.get("to"))
        exe = str(inner[0]) if inner else ""
        if not inner or not _is_abs_exe(exe):
            raise ValueError("refuse non-absolute exe")
        if "--append-system-prompt" in inner:
            raise ValueError("refuse --append-system-prompt")
        if "--" in inner:
            raise ValueError("refuse -- before harness exe")
        if _is_wrapper_exe(exe):   # the program, never its arguments (a root may name a wrapper)
            raise ValueError("refuse ola-brain / side-chat / UltraCode-Shim wrap")
        if root is not None and not raw:
            # The pane runs the Convoy pane host, which spawns the harness
            # as its owned child and records host_pid/child_pid, so close, nudge and relaunch can
            # reach the body. The launch record is written from the argv validated just above
            # (absolute exe, no wrapper, no --append-system-prompt, live flags, boot prompt) and
            # BEFORE the swap, so the host executes exactly what the terminal would have.
            from .targeted_launch import managed_host_argv
            # Recorded only after every pane passes: a refused second pane leaves no record for the first.
            records.append((str(seat.get("session_id") or ""), inner, str(cwd) if cwd else None))
            inner = managed_host_argv(Path(root), seat)
        title = thread_pane_title(label, seat)
        argv.extend(["--title", title])
        if cwd:
            argv.extend(["-d", str(cwd)])
        argv.extend([str(a) for a in inner])
    _check_thread_window(argv, here=here)
    if "--append-system-prompt" in argv:
        raise ValueError("refuse --append-system-prompt")
    if "--" in argv:
        raise ValueError("refuse -- before harness exe")
    if any(a == "^;" for a in argv):
        raise ValueError("refuse cmd ^; — use literal ; in argv")
    if records:
        from .pane_host import write_launch_argv
        for sid, inner_argv, cwd_s in records:
            write_launch_argv(Path(root), sid, inner_argv, cwd_s)
    return argv


def tile_rects(n: int, screen: tuple[int, int] = (1920, 1080)) -> list[dict[str, int]]:
    """Even split. Integers. No overlap except shared edges. On-screen.

    1 = almost full with 24px margin.
    2 = left/right.
    3 = left + two stacked right.
    n>=4 = two columns, stacked.
    """
    sw, sh = int(screen[0]), int(screen[1])
    n = int(n)
    if n <= 0:
        return []
    if n == 1:
        m = 24
        return [{"x": m, "y": m, "w": sw - 2 * m, "h": sh - 2 * m}]
    if n == 3:
        w = sw // 2
        h = sh // 2
        return [
            {"x": 0, "y": 0, "w": w, "h": sh},
            {"x": w, "y": 0, "w": sw - w, "h": h},
            {"x": w, "y": h, "w": sw - w, "h": sh - h},
        ]
    left_n = (n + 1) // 2
    right_n = n - left_n
    rects: list[dict[str, int]] = []

    def _stack(x: int, w: int, count: int) -> None:
        y = 0
        base_h = sh // count
        for i in range(count):
            h = sh - y if i == count - 1 else base_h
            rects.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})
            y += h

    left_w = sw // 2
    _stack(0, left_w, left_n)
    if right_n:
        _stack(left_w, sw - left_w, right_n)
    return rects


def dry_runner(*_a: Any, **_k: Any) -> dict[str, Any]:
    """No-op. Default in tests. Does not exec a TUI."""
    return {"ok": True, "dry": True}


# Windows CREATE_NEW_CONSOLE. Literal 0x10 so POSIX imports do not touch
# subprocess.CREATE_NEW_CONSOLE (that attribute does not exist on Linux).
CREATE_NEW_CONSOLE = 0x00000010


# Process-only variables Windows sets at logon that the registry does not carry.
_WIN_PROCESS_VARS = (
    "SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "OS",
    "USERPROFILE", "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "TEMP", "TMP", "PUBLIC", "ALLUSERSPROFILE", "ProgramData", "ProgramFiles", "ProgramFiles(x86)",
    "ProgramW6432", "CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432",
    "COMPUTERNAME", "LOGONSERVER", "SESSIONNAME", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "DriverData", "OneDrive",
)


def _registry_env() -> dict[str, str]:
    """The user's environment as Explorer would build it: machine scope, then
    user scope, PATH concatenated machine;user, REG_EXPAND_SZ expanded."""
    import winreg  # type: ignore[import-not-found]
    out: dict[str, str] = {}
    path_parts: list[str] = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                i = 0
                while True:
                    try:
                        name, value, kind = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not isinstance(value, str):
                        continue
                    if kind == winreg.REG_EXPAND_SZ:
                        value = os.path.expandvars(value)
                    if name.upper() == "PATH":
                        path_parts.append(value)
                    else:
                        out[name] = value
        except OSError:
            continue
    if path_parts:
        out["PATH"] = ";".join(p for p in path_parts if p)
    return out


def pane_env(base: dict[str, str] | None = None, *, registry: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for a pane Convoy opens. On Windows: the user's registry
    environment plus the logon-time process variables and Convoy's own
    CONVOY_* settings; never the launcher's shell identity or PATH.

    Observed with cursor-agent 2026.09.02-2026.09.08: the
    hook runner builds a PowerShell pipeline (`Get-Content -LiteralPath ...
    -Raw | & { $input | <hook> }`) and runs it in the shell it picks from the
    environment. Panes launched from a Git Bash tool call inherited
    SHELL=bash and a PATH with Git's usr/bin first; removing SHELL alone still
    failed (`eval: syntax error near unexpected token '&'`), and the same
    pane launched with the registry-built environment ran the hook and
    printed `hookcheck`. A pane sees what a user launching the harness by
    hand would see. Windows Terminal is single-instance: wt.exe hands the
    command to the running host, which spawns the pane with the environment
    the launcher passed, so this is the one place it can be set."""
    src = dict(os.environ if base is None else base)
    if os.name != "nt":
        return src
    env = dict(_registry_env() if registry is None else registry)
    # os.environ on Windows uppercases its keys (SYSTEMROOT), while the
    # registry and the harness launchers spell them mixed-case (SystemRoot);
    # a case-sensitive copy drops SystemRoot and every
    # cursor-agent.CMD dies with "The system cannot find the path specified".
    upper = {k.upper(): v for k, v in src.items()}
    present = {k.upper() for k in env}
    for name in _WIN_PROCESS_VARS:
        if name.upper() not in present and name.upper() in upper:
            env[name] = upper[name.upper()]
    for name, value in src.items():
        if name.upper().startswith("CONVOY_"):
            env[name] = value
    env.pop("SHELL", None)
    return env


def live_spawn_kwargs() -> dict[str, Any]:
    """Popen kwargs for a visible TUI. No spawn. Safe to unit-test with mocked os.name."""
    if os.name == "nt":
        return {"creationflags": CREATE_NEW_CONSOLE}
    return {"start_new_session": True}


def _find_hwnd_for_pids(user32: Any, pids: set[int]) -> Any:
    """Best-effort visible hwnd whose process id is in pids. Windows only."""
    import ctypes
    from ctypes import wintypes

    found: list[Any] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):  # type: ignore[misc]
        if not user32.IsWindowVisible(hwnd):
            return True
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if proc.value in pids:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(_enum, 0)
    return found[0] if found else None


def _child_pids(pid: int) -> set[int]:
    """Toolhelp snapshot of pid plus children (conhost). Windows only; empty on failure."""
    pids = {int(pid)}
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return pids
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
                return pids
            while True:
                if entry.th32ParentProcessID == pid:
                    pids.add(int(entry.th32ProcessID))
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        return pids
    return pids


def _tile_console(pid: int, rect: dict[str, int], title: str | None) -> str | None:
    """Position the new console. Best-effort. Returns a note if skipped; never raises."""
    try:
        import time
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        x = int(rect["x"])
        y = int(rect["y"])
        w = int(rect["w"])
        h = int(rect["h"])
        hwnd = None
        pids = _child_pids(pid)
        for _ in range(8):
            if title:
                hwnd = user32.FindWindowW(None, title)
            if not hwnd:
                hwnd = _find_hwnd_for_pids(user32, pids)
            if hwnd:
                break
            time.sleep(0.12)
            pids = _child_pids(pid)
        if not hwnd:
            return "visible console spawned; tile skipped (hwnd not found)"
        if not user32.MoveWindow(hwnd, x, y, w, h, True):
            SWP_SHOWWINDOW = 0x0040
            if not user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_SHOWWINDOW):
                return "visible console spawned; tile skipped (SetWindowPos/MoveWindow failed)"
        return None
    except Exception as e:
        return "visible console spawned; tile skipped (" + type(e).__name__ + ")"


def live_runner(argv: list[str], cwd: str | None = None, rect: dict[str, int] | None = None, *, here: bool = False,
                **_k: Any) -> dict[str, Any]:
    """ONE isolated wt.exe spawn for a named thread. Not called from unit tests.

    FileName is wt. ArgumentList is isolated_wt_argv[1:] (-w convoy-<8 hex>, new-tab / split-pane).
    Never per-seat CREATE_NEW_CONSOLE. Never MoveWindow. Never WM_CLOSE.
    Isolated spawn is a new WINDOW not a new PROCESS; do not close WT windows.
    cwd and rect are ignored: each pane has -d DIR; WT split-pane tiles.
    """
    argv = _live_argv(list(argv), here=here)
    # Do not pass CREATE_NEW_CONSOLE / startupinfo / MoveWindow / WM_CLOSE.
    proc = subprocess.Popen(argv, env=pane_env())
    return {"ok": True, "pid": proc.pid, "argv": argv}


def live_here_runner(argv: list[str], cwd: str | None = None, rect: dict[str, int] | None = None,
                     **_k: Any) -> dict[str, Any]:
    """live_runner for the person's explicit --here: the argv targets `-w 0 split-pane`."""
    return live_runner(argv, cwd, rect, here=True)


def _resolve(root: Path, convoy_id: str | None, thread: str | None) -> dict[str, Any]:
    disk = read_id(root)
    bound = read_thread(root)
    if convoy_id is not None:
        if disk != convoy_id:
            return {"ok": False, "error": "convoy_id mismatch", "convoy_id": disk, "thread": bound, "windows": []}
        cid = convoy_id
    else:
        if disk is None:
            return {"ok": False, "error": "no convoy_id", "convoy_id": None, "thread": bound, "windows": []}
        cid = disk
    if thread is not None:
        if bound != thread:
            return {"ok": False, "error": "thread mismatch", "convoy_id": cid, "thread": bound, "windows": []}
    return {"ok": True, "convoy_id": cid, "thread": bound}


def _hop_seats(root: Path, cid: str) -> list[dict[str, Any]]:
    seats = list_seats(root, convoy_id=cid, require_session=False)
    return [s for s in seats if not is_conductor(s.get("to")) and s.get("where") != "cloud"]


def _cloud_seats(root: Path, cid: str, session_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Chairs bring_up must NOT make a pane: a cloud neuron is not a local
    process. No cloud launcher exists; its connected proof will
    be an MCP attach, and the card says so instead of spawning."""
    return [
        {"session_id": s.get("session_id"), "to": s.get("to"), "where": "cloud", "pane": False,
         "reason": "no cloud launcher exists; a cloud neuron proves it is connected by MCP attach, not a pane"}
        for s in _only(list_seats(root, convoy_id=cid, require_session=False), session_ids)
        if s.get("where") == "cloud" and not is_conductor(s.get("to"))
    ]


def _only(seats: list[dict[str, Any]], session_ids: list[str] | None) -> list[dict[str, Any]]:
    """None means every seat (the bulk show); a list names exactly the chairs
    a caller minted. crew launches its own N chairs this way, so
    an older chair with a live body is never handed a second --resume."""
    if session_ids is None:
        return seats
    wanted = {str(s) for s in session_ids}
    return [s for s in seats if str(s.get("session_id") or "") in wanted]


def _window_for(root: Path, seat: dict[str, Any], rect: dict[str, int] | None, cid: str, thread: str | None) -> dict[str, Any]:
    to = seat.get("to")
    sid = seat.get("session_id")
    if not (isinstance(sid, str) and sid):
        sid = None
    wt = seat.get("worktree")
    rkey = seat.get("resume_key")
    if not (isinstance(rkey, str) and rkey):
        rkey = make_resume_key(cid, thread or "", str(to or ""), str(wt) if wt is not None else None)
    target = resume_target(seat)
    win: dict[str, Any] = {
        "to": to,
        "session_id": sid,
        "resume": None,
        "resume_key": rkey,
        "worktree": wt,
        "cwd": wt,
        "argv": [],
        "rect": rect,
        "ok": False,
        "headless": False,
    }
    try:
        argv = resume_argv(seat)
    except ValueError as e:
        win["error"] = str(e)
        return win
    win["argv"] = argv
    win["resume"] = target
    win["ok"] = True
    return win


def bring_up(root: Path, convoy_id: str | None = None, thread: str | None = None, runner: Runner | None = None, tiler: Tiler | None = None, session_ids: list[str] | None = None, *, allow_unverified_launch: bool = False, write_repo_files: bool | None = None, exclude: dict[str, str] | None = None, here: bool = False, plan_argv: bool = False, tile_offset: int = 0, tile_total: int | None = None) -> dict[str, Any]:
    """Resume seated neurons in ONE isolated wt.exe window. Conductor grok-bot is not a window.

    write_repo_files None writes every repo file only into a minted worktree (ensure_first_run);
    True is the person's --write-repo-files.
    Default runner is None (dry / no-op). A dry run writes nothing: first_run is the plan
    (would_write, would_write_home) and it must not Popen wt. Pass live_runner only for a real TUI pop (one isolated_wt_argv).
    Unit tests must not pass live_runner without mocking Popen.
    session_ids=None is the bulk show; a list restricts the window to those chairs.
    plan_argv=True on a dry run adds `planned_argv`: the one wt argv a live run would
    spawn, built raw (no session minted, no launch record written).
    """
    resolved = _resolve(root, convoy_id, thread)
    if not resolved.get("ok"):
        resolved["conductor"] = CONDUCTOR
        resolved["lead"] = read_lead(root)
        return resolved
    cid = resolved["convoy_id"]
    bound = resolved["thread"]
    if session_ids is not None:
        # A named chair that does not exist is a typo, not an empty success.
        known = {str(s.get("session_id") or "") for s in list_seats(root, convoy_id=cid, require_session=False)}
        unknown = [str(s) for s in session_ids if str(s) not in known]
        if unknown:
            return {"ok": False, "convoy_id": cid, "thread": bound, "windows": [],
                    "error": "unknown seat: " + ", ".join(unknown)}
    hops = _pane_seats(_only(_hop_seats(root, cid), session_ids))
    # A chair whose pane host is alive already has its body (another launch spawned it):
    # never a second pane (no-steal). The card names it under `skipped`.
    from .targeted_launch import hosted_live
    skipped = [{"session_id": s.get("session_id"), "to": s.get("to"),
                "reason": "a live pane host already holds this chair"}
               for s in hops if s.get("session_id") and hosted_live(root, str(s["session_id"]))]
    # exclude: chairs the caller found claimed by another launch in flight, with the reason.
    for s in hops:
        sid = str(s.get("session_id") or "")
        if sid in (exclude or {}) and sid not in {x["session_id"] for x in skipped}:
            skipped.append({"session_id": sid, "to": s.get("to"), "reason": (exclude or {})[sid]})
    held = {x["session_id"] for x in skipped}
    hops = [s for s in hops if s.get("session_id") not in held]
    if runner is not None:
        try:
            for s in hops:
                validate_launch_eligibility(s.get("to"), allow_unverified_launch=allow_unverified_launch)
        except ValueError as exc:
            return {"ok": False, "convoy_id": cid, "thread": bound, "windows": [], "error": str(exc)}
        # A pending boot prompt's lead and launcher line is the thread as it is now.
        from .lifecycle import refresh_identity
        hops = [refresh_identity(root, s) for s in hops]
    tile_fn = tiler or tile_rects
    rects = tile_fn(len(hops))
    if runner is not None:   # a dry run writes nothing, not even the mirror
        try:
            from .conductor import ensure_contract_copy
            ensure_contract_copy(root)   # the conductor's counterpart to the seats' AGENTS block
        except Exception:  # a missing mirror must never block a launch
            pass
    windows: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    for i, s in enumerate(hops):
        rect = rects[i] if i < len(rects) else None
        try:
            fr = ensure_first_run(s, root=root, live=runner is not None, write_repo_files=write_repo_files)
        except Exception as e:
            fr = {"ok": False, "prepared": False, "wrote": False, "settings": None, "error": str(e), "home_written": False, "settings_home": None}
        effective.append(s)
        win = _window_for(root, s, rect, cid, bound)
        win["first_run"] = {
            "prepared": bool(fr.get("prepared")),
            "wrote": bool(fr.get("wrote")),
            "settings": fr.get("settings"),
            "home_written": bool(fr.get("home_written")),
            "settings_home": fr.get("settings_home"),
            "trust_written": bool(fr.get("trust_written")),
            "trust_settings_home": fr.get("trust_settings_home"),
            "would_write": list(fr.get("would_write") or []),
            "would_write_home": list(fr.get("would_write_home") or []),
            "dry_run_writes": list(fr.get("dry_run_writes") or []),
            "dry_run": bool(fr.get("dry_run")),
            "notes": list(fr.get("notes") or []),
            "trust_stores_written": list(fr.get("trust_stores_written") or []),
        }
        if fr.get("error"):
            win["first_run"]["error"] = fr["error"]
        if fr.get("hook_refused"):
            win["ok"] = False
            win["error"] = str(fr.get("error"))
        windows.append(win)
    if runner is not None:
        ready: list[dict[str, Any]] = []
        ready_idx: list[int] = []
        for i, s in enumerate(effective):
            win = windows[i]
            if not win.get("ok"):
                continue
            try:
                ready.append(_prepare_wt_seat(s))
                ready_idx.append(i)
            except Exception as e:
                win["ok"] = False
                win["error"] = str(e)
        ready = _pane_seats(ready)
        if ready:
            try:
                # root=: every pane is an owned body, not a raw exe the
                # terminal owns and nobody counts.
                launching = {str(s.get("session_id")) for s in ready}
                wt_argv = isolated_wt_argv(bound or "", ready, wt=_resolve_wt_bin(), root=root,
                                           first=not _window_holds_another(root, launching), here=here,
                                           tile_offset=tile_offset, tile_total=tile_total)
                result = runner(wt_argv)
                if isinstance(result, dict):
                    for i in ready_idx:
                        w = windows[i]
                        if result.get("pid") is not None:
                            w["pid"] = result["pid"]
                        if result.get("note") is not None:
                            w["note"] = result["note"]
                        if result.get("ok") is False:
                            w["ok"] = False
                            err = result.get("error")
                            if err:
                                w["error"] = str(err)
            except Exception as e:
                for i in ready_idx:
                    windows[i]["ok"] = False
                    windows[i]["error"] = str(e)
    planned: dict[str, Any] = {}
    if runner is None and plan_argv:
        try:
            ready = _pane_seats([_prepare_wt_seat(s) for i, s in enumerate(effective) if windows[i].get("ok")])
            if ready:
                launching = {str(s.get("session_id")) for s in ready}
                planned["planned_argv"] = isolated_wt_argv(bound or "", ready, wt=_resolve_wt_bin(), root=root, raw=True,
                                                           first=not _window_holds_another(root, launching), here=here)
        except Exception as e:
            planned["planned_argv_error"] = str(e)
    overall = all(w.get("ok") for w in windows) if windows else True
    card: dict[str, Any] = {
        "ok": overall,
        "convoy_id": cid,
        "thread": bound,
        "conductor": CONDUCTOR,
        "lead": read_lead(root),
        "windows": windows,
        "skipped": skipped,
        # The chairs a pane was actually spawned for; a dry run spawns none.
        "launched": [str(w.get("session_id")) for w in windows
                     if runner is not None and w.get("ok") and w.get("session_id")],
        "cloud": _cloud_seats(root, cid, session_ids),
        **planned,
    }
    if skipped and not hops:
        # ok stays true (nothing failed), but a caller reading ok alone must not think a pane opened.
        card["note"] = ("nothing launched: every chair named is already held (" +
                        ", ".join(str(x["session_id"]) for x in skipped) + "); see skipped")
    return card


def terminals(root: Path, convoy_id: str | None = None, thread: str | None = None) -> dict[str, Any]:
    """Metadata of windows for that thread. No PTY dump. Desktop access is this + bring_up.
    A listing: no first run, so it writes no file anywhere."""
    card = _resolve(root, convoy_id, thread)
    if card.get("ok"):
        hops = _pane_seats(_hop_seats(root, card["convoy_id"]))
        rects = tile_rects(len(hops))
        card["windows"] = [_window_for(root, s, rects[i] if i < len(rects) else None, card["convoy_id"], card["thread"])
                           for i, s in enumerate(hops)]
        card["ok"] = all(w.get("ok") for w in card["windows"])
    card["lead"] = read_lead(root)
    windows = []
    for w in card.get("windows") or []:
        resume = w.get("resume")
        pids = _pids_for_resume(str(resume)) if isinstance(resume, str) and resume.strip() else set()
        windows.append({
            "to": w.get("to"),
            "session_id": w.get("session_id"),
            "resume": resume,
            "resume_key": w.get("resume_key"),
            "worktree": w.get("worktree"),
            "rect": w.get("rect"),
            "live": bool(pids),
            "headless": False,
        })
    return {
        "ok": card.get("ok"),
        "convoy_id": card.get("convoy_id"),
        "thread": card.get("thread"),
        "conductor": CONDUCTOR,
        "lead": card.get("lead"),
        "windows": windows,
        "error": card.get("error"),
    }


SW_HIDE = 0
SW_MINIMIZE = 6
HIDE_MODES = frozenset({"minimize", "hide"})
_CONDUCTOR_EXES = frozenset({"grok bot.exe", "grok-bot.exe", "grok_bot.exe"})


def dry_applier(*_a: Any, **_k: Any) -> dict[str, Any]:
    """No-op. Default in tests. Does not ShowWindow or kill."""
    return {"ok": True, "dry": True}


def _show_cmd(mode: str) -> int:
    return SW_HIDE if (mode or "").strip().lower() == "hide" else SW_MINIMIZE


def _iter_processes() -> list[tuple[int, str]]:
    """Windows Toolhelp (pid, exe). Empty on POSIX/failure. Never invent pids."""
    if os.name != "nt":
        return []
    rows: list[tuple[int, str]] = []
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return []
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
                return []
            while True:
                rows.append((int(entry.th32ProcessID), str(entry.szExeFile or "")))
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        return []
    return rows


def _read_command_line(pid: int) -> str | None:
    """Windows: ProcessCommandLineInformation. None on failure. Never invent."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ProcessCommandLineInformation = 60
        kernel32 = ctypes.windll.kernel32
        ntdll = ctypes.windll.ntdll
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            retlen = wintypes.ULONG()
            ntdll.NtQueryInformationProcess(handle, ProcessCommandLineInformation, None, 0, ctypes.byref(retlen))
            if not retlen.value:
                return None
            buf = ctypes.create_string_buffer(retlen.value)
            status = ntdll.NtQueryInformationProcess(
                handle, ProcessCommandLineInformation, buf, retlen.value, ctypes.byref(retlen)
            )
            if status != 0:
                return None
            raw = bytes(buf)
            slen = int.from_bytes(raw[0:2], "little")
            ptr_size = ctypes.sizeof(ctypes.c_void_p)
            off = 8 if ptr_size == 8 else 4
            ptr = int.from_bytes(raw[off:off + ptr_size], "little")
            base = ctypes.addressof(buf)
            if ptr and base <= ptr < base + len(raw):
                start = ptr - base
                return raw[start:start + slen].decode("utf-16-le", errors="replace")
            hdr = 8 + ptr_size if ptr_size == 8 else 8
            return raw[hdr:hdr + slen].decode("utf-16-le", errors="replace")
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _pids_for_resume(resume: str) -> set[int]:
    """PIDs whose command line contains --resume/--session-id {resume}. Empty if none."""
    if os.name != "nt" or not resume:
        return set()
    token = re.escape(str(resume))
    pat = re.compile(r'(^|\s)--(?:resume|session-id)(?:\s+|=)["\']?' + token + r'["\']?(?=\s|$)')
    found: set[int] = set()
    for pid, exe in _iter_processes():
        if pid <= 0:
            continue
        if (exe or "").strip().lower() in _CONDUCTOR_EXES:
            continue
        cl = _read_command_line(pid)
        if cl and pat.search(cl):
            found.add(pid)
    return found


def _hwnds_for_pids(pids: set[int], include_hidden: bool = True) -> list[Any]:
    """Top-level hwnds for pids. Windows only. Empty on POSIX/failure."""
    if os.name != "nt" or not pids:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        target = {int(p) for p in pids}
        found: list[Any] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):  # type: ignore[misc]
            if not include_hidden and not user32.IsWindowVisible(hwnd):
                return True
            proc = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
            if proc.value in target:
                found.append(hwnd)
            return True

        user32.EnumWindows(_enum, 0)
        return found
    except Exception:
        return []


def live_applier(resume: str, mode: str = "minimize", **_k: Any) -> dict[str, Any]:
    """ShowWindow on neuron hwnds whose argv contains --resume/--session-id {resume}. Never kills.

    POSIX: no-op (unit tests / daemons). Windows: find hwnds, SW_MINIMIZE or SW_HIDE.
    If no hwnd, ok false error 'no window'. Do not invent pids. restore is bring_up.
    """
    if os.name != "nt":
        return {"ok": True, "dry": True}
    pids = _pids_for_resume(resume)
    if not pids:
        return {"ok": False, "error": "no window"}
    search: set[int] = set()
    for pid in pids:
        search |= _child_pids(pid)
    hwnds = _hwnds_for_pids(search, include_hidden=True)
    if not hwnds:
        return {"ok": False, "error": "no window"}
    try:
        import ctypes

        user32 = ctypes.windll.user32
        show = _show_cmd(mode)
        for hwnd in hwnds:
            user32.ShowWindow(hwnd, show)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def hide_windows(
    root: Path,
    convoy_id: str | None = None,
    thread: str | None = None,
    mode: str = "minimize",
    applier: Applier | None = None,
) -> dict[str, Any]:
    """Minimize or hide neuron TUI windows. Sessions keep running. Never taskkill.

    Default applier is None (dry / no-op). Pass live_applier only for real ShowWindow.
    Unit tests must pass a mock applier; never ShowWindow in tests.
    mode=minimize (SW_MINIMIZE=6, default) or hide (SW_HIDE=0). restore is bring_up.
    Conductor grok-bot is not a window. Never kills grok.exe/claude.exe/Grok Bot.exe.
    """
    action = (mode or "minimize").strip().lower()
    resolved = _resolve(root, convoy_id, thread)
    if not resolved.get("ok"):
        resolved["conductor"] = CONDUCTOR
        resolved["lead"] = read_lead(root)
        return resolved
    cid = resolved["convoy_id"]
    bound = resolved["thread"]
    lead = read_lead(root)
    if action not in HIDE_MODES:
        return {
            "ok": False,
            "error": "mode must be minimize or hide",
            "convoy_id": cid,
            "thread": bound,
            "conductor": CONDUCTOR,
            "lead": lead,
            "windows": [],
        }
    hops = _hop_seats(root, cid)
    windows: list[dict[str, Any]] = []
    for s in hops:
        to = s.get("to")
        sid = s.get("session_id")
        if not (isinstance(sid, str) and sid):
            sid = None
        target = resume_target(s)
        wt = s.get("worktree")
        win: dict[str, Any] = {
            "to": to,
            "session_id": sid,
            "resume": target,
            "worktree": wt,
            "action": action,
            "ok": False,
        }
        if not target:
            win["error"] = "refuse empty session_id"
            windows.append(win)
            continue
        win["ok"] = True
        if applier is not None:
            try:
                result = applier(target, action, to=to, worktree=wt)
                if isinstance(result, dict):
                    if result.get("ok") is False:
                        win["ok"] = False
                        err = result.get("error") or "no window"
                        win["error"] = err
            except Exception as e:
                win["ok"] = False
                win["error"] = str(e)
        windows.append(win)
    overall = all(w.get("ok") for w in windows) if windows else True
    return {
        "ok": overall,
        "convoy_id": cid,
        "thread": bound,
        "conductor": CONDUCTOR,
        "lead": lead,
        "windows": windows,
    }



# re-export hash/lookup so MCP cards and CLI share one module
resume_key = make_resume_key
lookup = lookup_resume
