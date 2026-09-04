"""Targeted launch: add exactly one fresh Convoy chair to the caller's pane host.

Harness construction and terminal placement are separate contracts.  The
terminal adapter is allowlisted and must be able to name the active context;
there is deliberately no keyboard injection or generic shell fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .bringup import (
    _harness_bin,
    _is_abs_exe,
    _pane_title,
    _seat_with_agent,
    ensure_first_run,
    resume_argv,
    resume_target,
)
from .consent import consume_consent, request_consent
from .convoy import list_seats, update_seat
from .harness_contract import effort_contract, harness_entries, harness_exec

Which = Callable[[str], str | None]
Runner = Callable[[list[str]], dict[str, Any]]
GitWorktrees = Callable[[Iterable[Path]], list[str]]


def terminal_capability(
    *,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Return the safe active-pane adapter, or an explicit refusal.

    tmux is checked first because a tmux pane can be nested inside another
    terminal and TMUX_PANE names the caller's exact pane.  Windows Terminal's
    CLI can target only its most-recently-used window (``-w 0``), so the card
    states that weaker targeting rule rather than claiming an exact window id.
    """
    values = os.environ if env is None else env
    platform = os.name if platform_name is None else platform_name

    tmux_session = str(values.get("TMUX") or "").strip()
    tmux_pane = str(values.get("TMUX_PANE") or "").strip()
    tmux = which("tmux") if tmux_session and tmux_pane else None
    if tmux:
        return {
            "can_split": True,
            "adapter": "tmux",
            "executable": str(tmux),
            "target": tmux_pane,
            "target_semantics": "exact-caller-pane",
            "can_close_exact": False,
            "close_reason": "created-pane-id-not-yet-captured",
        }

    wt_session = str(values.get("WT_SESSION") or "").strip()
    wt = which("wt") if platform == "nt" and wt_session else None
    if wt:
        return {
            "can_split": True,
            "adapter": "windows-terminal",
            "executable": str(wt),
            "target": "most-recent-window",
            "target_semantics": "mru-window-active-pane",
            "can_close_exact": False,
            "close_reason": "windows-terminal-cli-has-no-close-pane-command",
        }

    return {
        "can_split": False,
        "adapter": None,
        "target": None,
        "reason": "no-supported-active-terminal",
        "supported_adapters": ["tmux", "windows-terminal"],
        "can_close_exact": False,
        "close_reason": "no-supported-active-terminal",
    }


def pane_child_argv(seat: dict[str, Any]) -> list[str]:
    """Native harness argv executed by the lifecycle host."""
    inner = resume_argv(seat)
    if _harness_bin(str(seat.get("to") or "")) == "grok" and seat.get("trust_worktree"):
        if "--trust" not in inner:
            inner.insert(1, "--trust")
    return inner


def managed_host_argv(root: Path, seat: dict[str, Any]) -> list[str]:
    sid = str(seat.get("session_id") or "").strip()
    if not sid:
        raise ValueError("managed pane host requires a chair session_id")
    return [
        str(Path(sys.executable).resolve()),
        "-m",
        "convoy.pane_host",
        "--root",
        str(Path(root).resolve()),
        "--seat",
        sid,
    ]


def active_pane_argv(
    seat: dict[str, Any],
    capability: dict[str, Any],
    *,
    root: Path | None = None,
) -> list[str]:
    """Build one terminal split command containing one harness invocation."""
    if not capability.get("can_split"):
        raise ValueError(str(capability.get("reason") or "terminal cannot split"))
    worktree = str(seat.get("worktree") or "").strip()
    if not worktree:
        raise ValueError("refuse targeted launch without a worktree")
    harness_argv = pane_child_argv(seat)
    if not harness_argv or not _is_abs_exe(str(harness_argv[0])):
        raise ValueError("refuse targeted launch without an absolute harness executable")
    inner = managed_host_argv(root, seat) if root is not None else harness_argv

    terminal = str(capability.get("executable") or "").strip()
    if not terminal:
        raise ValueError("terminal adapter has no executable")
    adapter = capability.get("adapter")
    if adapter == "windows-terminal":
        return [
            terminal,
            "-w",
            "0",
            "split-pane",
            "-V",
            "--title",
            _pane_title(seat),
            "-d",
            worktree,
            *inner,
        ]
    if adapter == "tmux":
        pane = str(capability.get("target") or "").strip()
        if not pane:
            raise ValueError("tmux adapter has no caller pane")
        return [
            terminal,
            "split-window",
            "-t",
            pane,
            "-v",
            "-c",
            worktree,
            shlex.join(inner),
        ]
    raise ValueError("unsupported terminal adapter: " + str(adapter))


def active_pane_runner(argv: list[str]) -> dict[str, Any]:
    """Launch one allowlisted terminal split without a shell."""
    try:
        proc = subprocess.Popen([str(a) for a in argv])
        return {"ok": True, "pid": int(proc.pid)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}


def _seat_for_launch(root: Path, session_id: str) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    for row in list_seats(root):
        if row.get("session_id") == sid:
            return row
    raise ValueError("unknown seat: " + sid)


def grok_project_trusted(seat: dict[str, Any]) -> bool:
    """Ask Grok's read-only inspect command; never infer or edit its trust store."""
    if _harness_bin(str(seat.get("to") or "")) != "grok":
        return True
    worktree = str(seat.get("worktree") or "").strip()
    executable = pane_child_argv({**seat, "trust_worktree": False})[0]
    try:
        result = subprocess.run(
            [executable, "inspect"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Grok trust preflight failed: " + str(exc)) from exc
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    lowered = combined.lower()
    if "project trusted: yes" in lowered:
        return True
    if "project trusted: no" in lowered:
        return False
    raise ValueError("Grok trust preflight returned no project trust state")


def _claim_path(root: Path, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return Path(root) / ".convoy" / "launch-claims" / (digest + ".json")


def release_launch_claim(root: Path, session_id: str) -> bool:
    """Drop the persistent launch claim for a chair whose pane is being
    closed. Returns True when a claim existed."""
    path = _claim_path(Path(root), session_id)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return existed


def _claim(root: Path, session_id: str) -> Path:
    path = _claim_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("refuse duplicate launch: chair already claimed") from exc
    payload = json.dumps({"session_id": session_id}, separators=(",", ":")) + "\n"
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def launch_seat(
    root: Path,
    session_id: str,
    *,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
    consent: str | None = None,
    trust_probe: Callable[[dict[str, Any]], bool] = grok_project_trusted,
) -> dict[str, Any]:
    """Plan or launch one fresh join/swap chair.

    ``runner=None`` is a read-only dry run. A live call creates an atomic,
    persistent claim before spawning, so two callers cannot split two panes for
    the same chair. A spawn failure removes the claim and leaves the chair
    pending for an explicit retry.
    """
    try:
        row = _seat_for_launch(root, session_id)
        if resume_target(row) is not None or not str(row.get("boot_prompt") or "").strip():
            raise ValueError("refuse launch: chair is not a fresh join/swap")
        worktree = str(row.get("worktree") or "").strip()
        if not worktree:
            raise ValueError("refuse targeted launch without a worktree")
        if not Path(worktree).is_dir():
            raise ValueError("refuse missing worktree: " + worktree)
        if not trust_probe(row) and not row.get("trust_worktree"):
            if not consent:
                waiting = request_consent(
                    root,
                    "trust-worktree",
                    session_id=session_id,
                    to=str(row.get("to") or ""),
                    worktree=worktree,
                )
                return {"session_id": session_id, **waiting}
            consume_consent(
                root,
                consent,
                "trust-worktree",
                session_id=session_id,
                to=str(row.get("to") or ""),
                worktree=worktree,
            )
            row = update_seat(root, session_id, trust_worktree=True)
        capability = terminal_capability(env=env, which=which, platform_name=platform_name)
        if not capability.get("can_split"):
            raise ValueError(
                "no supported active pane; use `convoy choices` and open a pane manually"
            )

        effective = row
        first_run: dict[str, Any] | None = None
        if runner is not None:
            first_run = ensure_first_run(row, root=root)
            if first_run.get("ok") is False:
                raise ValueError(str(first_run.get("error") or "first-run preparation failed"))
            effective = _seat_with_agent(root, row, first_run)
        harness_argv = pane_child_argv(effective)
        argv = active_pane_argv(effective, capability, root=root)
        card: dict[str, Any] = {
            "ok": True,
            "session_id": session_id,
            "to": row.get("to"),
            "worktree": worktree,
            "adapter": capability.get("adapter"),
            "target": capability.get("target"),
            "target_semantics": capability.get("target_semantics"),
            "can_close_exact": bool(capability.get("can_close_exact")),
            "close_reason": capability.get("close_reason"),
            "argv": argv,
            "harness_argv": harness_argv,
            "dry_run": runner is None,
        }
        if runner is None:
            return card

        claim = _claim(root, session_id)
        try:
            result = runner(argv)
        except Exception as exc:
            claim.unlink(missing_ok=True)
            raise ValueError(type(exc).__name__ + ": " + str(exc)) from exc
        if not isinstance(result, dict) or result.get("ok") is False:
            claim.unlink(missing_ok=True)
            error = result.get("error") if isinstance(result, dict) else None
            raise ValueError(str(error or "terminal adapter failed"))
        update_seat(
            root,
            session_id,
            launch_state="launched",
            launch_adapter=capability.get("adapter"),
            launcher_pid=result.get("pid"),
        )
        card["dry_run"] = False
        if result.get("pid") is not None:
            card["pid"] = result["pid"]
        return card
    except (OSError, ValueError) as exc:
        return {"ok": False, "session_id": session_id, "error": str(exc)}


def _discover_git_worktrees(paths: Iterable[Path]) -> list[str]:
    found: list[str] = []
    for candidate in paths:
        try:
            base = Path(candidate).resolve()
        except Exception:
            continue
        if not base.is_dir():
            continue
        try:
            run = subprocess.run(
                ["git", "-C", str(base), "worktree", "list", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if run.returncode != 0:
            continue
        for line in run.stdout.splitlines():
            if line.startswith("worktree "):
                found.append(line.removeprefix("worktree ").strip())
    return found


def launch_choices(
    root: Path,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
    git_worktrees: GitWorktrees = _discover_git_worktrees,
) -> dict[str, Any]:
    """List enough safe facts to choose a harness and worktree without memory."""
    rows = list_seats(root)
    seats = [
        {
            "session_id": row.get("session_id"),
            "to": row.get("to"),
            "model": row.get("model"),
            "title": row.get("title"),
            "worktree": row.get("worktree"),
        }
        for row in rows
    ]
    harnesses = []
    for entry in harness_entries():
        executable = harness_exec(str(entry.get("id") or ""))
        path = which(executable)
        harnesses.append(
            {
                "id": entry.get("id"),
                "name": entry.get("name"),
                "installed": bool(path),
                "executable": str(path) if path else None,
                # Per-harness effort straight from harness_effort.json so a
                # host on the wire can render harness -> effort without the
                # file; null where the contract is silent.
                "effort": effort_contract(str(entry.get("id") or "")),
            }
        )

    current = Path.cwd() if cwd is None else Path(cwd)
    candidates = [Path(root), current]
    registered = [str(row.get("worktree")) for row in rows if row.get("worktree")]
    discovered = git_worktrees(candidates)
    worktrees: list[str] = []
    seen_worktrees: set[str] = set()
    for value in [*registered, *discovered, str(current)]:
        if not value:
            continue
        try:
            rendered = str(Path(value).resolve())
        except Exception:
            rendered = str(value)
        key = os.path.normcase(os.path.normpath(rendered))
        if key not in seen_worktrees:
            seen_worktrees.add(key)
            worktrees.append(rendered)
    return {
        "ok": True,
        "terminal": terminal_capability(env=env, which=which, platform_name=platform_name),
        "harnesses": harnesses,
        "worktrees": worktrees,
        "seats": seats,
        "example": "convoy join --to <harness> --worktree <path> --launch",
    }
