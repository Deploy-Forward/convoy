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

First-run Claude bypass warning is ungated by ensure_first_run.
Anthropic ignores skipDangerousModePermissionPrompt in project
{worktree}/.claude/settings.json — that key only works in the user file
~/.claude/settings.json. Merge skipDangerousModePermissionPrompt: true
into ~/.claude/settings.json (create ~/.claude/ if missing). Do not set
permissions.defaultMode on the user global file (that would make ALL
Claude sessions on the machine bypass). Still write the project settings
(skipDangerousModePermissionPrompt + permissions.defaultMode
bypassPermissions) as a record. Also persist ~/.claude.json
projects[worktree].hasTrustDialogAccepted=true for both slash spellings
of the worktree path. Never write ~/.claude if worktree IS the home dir.
Grok/codex no-op. Not a user paste. Not a TUI guide.
Persona is role.md.

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
from pathlib import Path
from typing import Any, Callable

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
    "codex": "codex",
    "codex.exe": "codex",
    "agy": "agy",
    "agy.exe": "agy",
    "cursor-agent": "cursor-agent",
    "cursor-agent.exe": "cursor-agent",
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
    """One pane per hop seat. Conductor is never a window. Empty to skipped.

    Dedup key: worktree if set, else resume_key, else session_id, else to.
    Same seat twice is collapsed (same worktree+to, or same resume_key/session_id).
    Two grok hops on different worktrees both appear. Not one pane per harness name.
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


def _live_argv(argv: list[str]) -> list[str]:
    """Popen argv for ONE isolated wt.exe spawn. FileName is wt. ArgumentList is the rest.

    Never per-seat CREATE_NEW_CONSOLE. Never `--` before the harness exe (pops Help).
    Never -w 0 / -w <thread>. Never ola-brain / side-chat / UltraCode-Shim.
    """
    if not argv:
        raise ValueError("refuse empty argv")
    parts = [str(a) for a in argv]
    # Do not scan -d DIR / --title / --resume values: worktree may be .../ola-brain.
    skip_next = False
    for a in parts:
        if skip_next:
            skip_next = False
            continue
        if a in ("-d", "--title", "--window", "--resume", "--permission-mode"):
            skip_next = True
            continue
        if _is_wrapper_text(a) or _basename_lower(a) in _WRAPPER_EXES:
            raise ValueError("refuse ola-brain / side-chat / UltraCode-Shim wrap")
        if a.lower() == "wm_close":
            raise ValueError("refuse WM_CLOSE")
    if "--" in parts:
        raise ValueError("refuse -- before harness exe")
    if "-w" in parts:
        raise ValueError("refuse -w; use --window new")
    if any(a == "^;" for a in parts):
        raise ValueError("refuse cmd ^; — use literal ; in argv")
    base0 = _basename_lower(parts[0])
    if base0 not in ("wt", "wt.exe"):
        raise ValueError("refuse per-seat spawn; use isolated_wt_argv")
    if len(parts) < 4 or parts[1] != "--window" or parts[2] != "new":
        raise ValueError("refuse wt wrap")
    first_cmd = parts[3]
    if first_cmd in ("nw", "new-window", "rename-window"):
        raise ValueError("refuse nw/rename-window as first command")
    if first_cmd not in ("nt", "new-tab"):
        raise ValueError("first command must be nt/new-tab")
    wt = _resolve_wt_bin(parts[0])
    return [wt, *parts[1:]]


def is_conductor(to: Any) -> bool:
    return str(to or "").strip().lower() in _CONDUCTORS


def resume_target(seat: dict[str, Any]) -> str | None:
    """Vendor id passed to --resume/resume subcommand. Never invent."""
    for key in ("vendor_session_id", "resume"):
        val = seat.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def resume_argv(seat: dict[str, Any]) -> list[str]:
    """Argv we WOULD exec. No spawn. Native harness resume only.

    FileName is shutil.which absolute path when found, else the bare harness name.
    Grok keeps seat identity flags:
        [exe, '-m', MODEL?, '--agent', PATH?, '--resume', sid]
    Codex resume shape:
        [exe, 'resume', sid]
    Other harnesses:
        [exe, '--resume', sid]
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
    if _harness_bin(to) == "grok":
        model = seat.get("model")
        if isinstance(model, str) and model.strip():
            argv.extend(["-m", model.strip()])
        agent = seat.get("agent")
        if isinstance(agent, str) and agent.strip():
            argv.extend(["--agent", agent.strip()])
    # First-run seat: no vendor UUID yet. Do not pass --resume.
    if sid:
        if _harness_bin(to) == "codex":
            argv.extend(["resume", sid])
        else:
            argv.extend(["--resume", sid])
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
    return Path(worktree) / ".claude" / "settings.json"


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


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_dict(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_claude_trust_projects(worktree: Path) -> Path:
    """Persist hasTrustDialogAccepted for both slash spellings of worktree."""
    state_path = _claude_home_state_path()
    data = _read_json_dict(state_path)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    for key in _project_path_variants(worktree):
        node = projects.get(key)
        if not isinstance(node, dict):
            node = {}
        node["hasTrustDialogAccepted"] = True
        projects[key] = node
    data["projects"] = projects
    _write_json_dict(state_path, data)
    return state_path


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


def ensure_interactive_path(home: Path | None = None) -> dict[str, Any]:
    """Ungate harness bins for interactive non-login bash (desktop terminals).

    roster.present is shutil.which on the MCP/agent process PATH. That is not
    the PATH of an already-open desktop terminal. Interactive bash reads
    ~/.bashrc and skips ~/.profile, so ~/.local/bin (claude, codex) can be
    installed and still command-not-found. Grok's installer writes .bashrc;
    Debian/Ubuntu put ~/.local/bin only in .profile.

    Writes an idempotent block into ~/.bashrc. No-op on Windows (WT inherits
    user PATH). Does not clobber vendor installer blocks. Does not source
    the file into a foreign PID.
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


def ensure_first_run(seat: dict[str, Any]) -> dict[str, Any]:
    """Ungate first-run Claude bypass warning for the thread worktree.

    Project {worktree}/.claude/settings.json: merge skipDangerousModePermissionPrompt
    + permissions.defaultMode bypassPermissions (record; Anthropic ignores this
    copy for the Bypass Permissions dialog).
    User ~/.claude/settings.json: merge ONLY skipDangerousModePermissionPrompt
    true (required — Anthropic reads this file for the dialog). Do not set
    permissions.defaultMode on the user global file. Create ~/.claude/ if missing.
    User ~/.claude.json: set projects[worktree].hasTrustDialogAccepted=true
    for both slash spellings of the worktree key.
    Never write ~/.claude if worktree IS the home dir.
    Grok/codex: no-op. Persona is role.md, not CLI.
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
    }
    path_card = ensure_interactive_path()
    out["path_written"] = bool(path_card.get("path_written"))
    out["path_bashrc"] = path_card.get("path_bashrc")
    out["path_ok"] = bool(path_card.get("path_ok"))
    out["path_host"] = path_card.get("path_host")
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
        data = _read_json_dict(settings_path)
        data["skipDangerousModePermissionPrompt"] = True
        perms = data.get("permissions")
        if not isinstance(perms, dict):
            perms = {}
        perms["defaultMode"] = "bypassPermissions"
        data["permissions"] = perms
        _write_json_dict(settings_path, data)
        out["wrote"] = True
        out["settings"] = str(settings_path)
        home_path = _claude_home_settings_path()
        home_data = _read_json_dict(home_path)
        home_data["skipDangerousModePermissionPrompt"] = True
        _write_json_dict(home_path, home_data)
        out["home_written"] = True
        out["settings_home"] = str(home_path)
        trust_path = _write_claude_trust_projects(wt_path)
        out["trust_written"] = True
        out["trust_settings_home"] = str(trust_path)
        return out
    except Exception as e:
        out["ok"] = False
        out["prepared"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def _with_claude_live_flags(argv: list[str], to: Any) -> list[str]:
    """Live Claude argv includes --permission-mode bypassPermissions and --allow-dangerously-skip-permissions. Dry resume_argv does not."""
    parts = [str(a) for a in argv]
    if not _is_claude(to):
        return parts
    if "--permission-mode" not in parts:
        parts.extend(["--permission-mode", "bypassPermissions"])
    if "--allow-dangerously-skip-permissions" not in parts:
        parts.append("--allow-dangerously-skip-permissions")
    if "--append-system-prompt" in parts:
        raise ValueError("refuse --append-system-prompt")
    return parts


def isolated_wt_argv(thread: str | int, seats: list[dict[str, Any]], *, wt: str | None = None) -> list[str]:
    """Pure Windows Terminal argv for n hop seats. Does not spawn.

    Live GREEN on WT 1.24.11911.0 (Aether 2026-08-29 TDD):
      --window new  nt --title T -d DIR EXE ...  ;  split-pane -V ...
    Never -w 0 (injects into focused WT). Never -w <thread-name> (pops Help).
    Never `--` before the harness exe (pops Help). Never nw / rename-window.
    n=3: nt, then split-pane -V, then split-pane -H.
    Literal ';' WT separators via Start-Process -ArgumentList, not cmd ^;.
    No --append-system-prompt. Claude live flags on the inner argv.
    """
    name = str(thread if thread is not None else "").strip()
    if name == "0":
        raise ValueError("refuse -w 0")
    panes = _pane_seats(list(seats or []))
    if not panes:
        raise ValueError("refuse empty seats")
    wt_bin = str(wt or "wt")
    argv: list[str] = [wt_bin, "--window", "new"]
    for i, seat in enumerate(panes):
        if i == 0:
            argv.append("nt")
        else:
            argv.append(";")
            split = "-V" if i == 1 else "-H"
            argv.extend(["split-pane", split])
        cwd = seat.get("worktree") or seat.get("cwd") or ""
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
        low = " ".join(inner).lower()
        if _is_wrapper_text(low):
            raise ValueError("refuse ola-brain / side-chat / UltraCode-Shim wrap")
        title = _pane_title(seat)
        argv.extend(["--title", title])
        if cwd:
            argv.extend(["-d", str(cwd)])
        argv.extend([str(a) for a in inner])
    if "-w" in argv:
        widx = argv.index("-w")
        if widx + 1 < len(argv) and str(argv[widx + 1]) == "0":
            raise ValueError("refuse -w 0")
        raise ValueError("refuse -w; use --window new")
    first_cmd = argv[3] if len(argv) > 3 else ""
    if first_cmd in ("nw", "new-window", "rename-window"):
        raise ValueError("refuse nw/rename-window as first command")
    if first_cmd not in ("nt", "new-tab"):
        raise ValueError("first command must be nt/new-tab")
    if "--append-system-prompt" in argv:
        raise ValueError("refuse --append-system-prompt")
    if "--" in argv:
        raise ValueError("refuse -- before harness exe")
    if any(a == "^;" for a in argv):
        raise ValueError("refuse cmd ^; — use literal ; in argv")
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


def live_runner(argv: list[str], cwd: str | None = None, rect: dict[str, int] | None = None, **_k: Any) -> dict[str, Any]:
    """ONE isolated wt.exe spawn for a named thread. Not called from unit tests.

    FileName is wt. ArgumentList is isolated_wt_argv[1:] (--window new, nt / split-pane).
    Never per-seat CREATE_NEW_CONSOLE. Never MoveWindow. Never WM_CLOSE.
    Isolated spawn is a new WINDOW not a new PROCESS; do not close WT windows.
    cwd and rect are ignored: each pane has -d DIR; WT split-pane tiles.
    """
    argv = _live_argv(list(argv))
    # Do not pass CREATE_NEW_CONSOLE / startupinfo / MoveWindow / WM_CLOSE.
    proc = subprocess.Popen(argv, env=os.environ.copy())
    return {"ok": True, "pid": proc.pid, "argv": argv}


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
    return [s for s in seats if not is_conductor(s.get("to"))]


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


def bring_up(root: Path, convoy_id: str | None = None, thread: str | None = None, runner: Runner | None = None, tiler: Tiler | None = None) -> dict[str, Any]:
    """Resume hop seats in ONE isolated wt.exe window. Conductor grok-bot is not a window.

    Default runner is None (dry / no-op). Dry-run still calls ensure_first_run and
    must not Popen wt. Pass live_runner only for a real TUI pop (one isolated_wt_argv).
    Unit tests must not pass live_runner without mocking Popen.
    """
    resolved = _resolve(root, convoy_id, thread)
    if not resolved.get("ok"):
        resolved["conductor"] = CONDUCTOR
        resolved["lead"] = read_lead(root)
        return resolved
    cid = resolved["convoy_id"]
    bound = resolved["thread"]
    hops = _pane_seats(_hop_seats(root, cid))
    tile_fn = tiler or tile_rects
    rects = tile_fn(len(hops))
    windows: list[dict[str, Any]] = []
    for i, s in enumerate(hops):
        rect = rects[i] if i < len(rects) else None
        win = _window_for(root, s, rect, cid, bound)
        try:
            fr = ensure_first_run(s)
        except Exception as e:
            fr = {"ok": False, "prepared": False, "wrote": False, "settings": None, "error": str(e), "home_written": False, "settings_home": None}
        win["first_run"] = {
            "prepared": bool(fr.get("prepared")),
            "wrote": bool(fr.get("wrote")),
            "settings": fr.get("settings"),
            "home_written": bool(fr.get("home_written")),
            "settings_home": fr.get("settings_home"),
            "trust_written": bool(fr.get("trust_written")),
            "trust_settings_home": fr.get("trust_settings_home"),
        }
        if fr.get("error"):
            win["first_run"]["error"] = fr["error"]
        windows.append(win)
    if runner is not None:
        ready: list[dict[str, Any]] = []
        ready_idx: list[int] = []
        for i, s in enumerate(hops):
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
                wt_argv = isolated_wt_argv(bound or "", ready, wt=_resolve_wt_bin())
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
    overall = all(w.get("ok") for w in windows) if windows else True
    return {
        "ok": overall,
        "convoy_id": cid,
        "thread": bound,
        "conductor": CONDUCTOR,
        "lead": read_lead(root),
        "windows": windows,
    }


def terminals(root: Path, convoy_id: str | None = None, thread: str | None = None) -> dict[str, Any]:
    """Metadata of windows for that thread. No PTY dump. Desktop access is this + bring_up."""
    card = bring_up(root, convoy_id=convoy_id, thread=thread, runner=None)
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
    """ShowWindow on hop hwnds whose argv contains --resume/--session-id {resume}. Never kills.

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
    """Minimize or hide hop TUI windows. Sessions keep running. Never taskkill.

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
