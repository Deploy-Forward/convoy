"""End-of-turn heartbeats and explicit task completion.

Harness Stop hooks call :func:`end_task` with a vendor payload.  That path is
advisory and never mutates git.  A human/model may separately invoke
``convoy end --push``; that exact flag is the authorization boundary for a
plain ``git push`` of an already-clean branch with an existing upstream.

Vendor session ids, turn ids, transcripts, and assistant messages are never
written to the Convoy feed.  They are used only to derive an opaque duplicate
key so that a plugin hook and a project hook do not emit the same heartbeat
twice.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from .convoy import read_id
from .inbox import _exclusive, resolve_root, seats_for_worktree
from .layer import STAMP_MAX_CHARS, feed_path, hook


GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def _one_line(value: Any, default: str) -> tuple[str, bool]:
    text = " ".join(str(value or "").split()) or default
    truncated = len(text) > STAMP_MAX_CHARS
    return text[:STAMP_MAX_CHARS], truncated


def _event_key(root: Path, chair: str, payload: dict[str, Any]) -> str | None:
    session = payload.get("session_id") or payload.get("sessionId")
    turn = payload.get("turn_id") or payload.get("turnId")
    event = payload.get("hook_event_name") or payload.get("hookEventName") or "Stop"
    if not session or not turn:
        return None
    raw = "\0".join((str(read_id(root) or ""), chair, str(event), str(session), str(turn)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _seen(root: Path, event_key: str | None) -> bool:
    if not event_key:
        return False
    path = feed_path(root)
    if not path.is_file():
        return False
    # A duplicate hook is adjacent in practice.  Bound the read so Stop stays
    # fast even when a long-lived thread has a very large feed.
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - 131_072))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in tail.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("event_key") == event_key:
            return True
    return False


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, check=False,
    )


def _git_value(cwd: Path, args: list[str], runner: GitRunner) -> tuple[bool, str]:
    try:
        result = runner(args, cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__ + ": " + str(exc)
    text = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, text


def _git_snapshot(cwd: Path, runner: GitRunner) -> dict[str, Any]:
    inside, inside_text = _git_value(cwd, ["rev-parse", "--is-inside-work-tree"], runner)
    if not inside or inside_text.lower() != "true":
        return {"ok": False, "error": "cwd is not a git worktree"}
    branch_ok, branch = _git_value(cwd, ["symbolic-ref", "--quiet", "--short", "HEAD"], runner)
    sha_ok, sha = _git_value(cwd, ["rev-parse", "HEAD"], runner)
    status_ok, status = _git_value(cwd, ["status", "--porcelain"], runner)
    upstream_ok, upstream = _git_value(
        cwd, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], runner
    )
    return {
        # Detached HEAD is a valid snapshot but an invalid push state; keep
        # those facts separate so the refusal can name the exact condition.
        "ok": bool(sha_ok and status_ok),
        "branch": branch if branch_ok else None,
        "git_sha": sha if sha_ok else None,
        "dirty": bool(status) if status_ok else None,
        "upstream": upstream if upstream_ok else None,
        "error": None if sha_ok and status_ok else "cannot inspect the current git worktree",
    }


def _resolve_identity(
    *, root: Path | str | None, cwd: Path, allow_missing_root: bool,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    resolved: Path | None
    if root is not None:
        resolved = Path(root).resolve()
        if not read_id(resolved):
            return None, None, "explicit --root is not a Convoy thread"
    else:
        resolved = resolve_root(cwd)
    if resolved is None:
        if allow_missing_root:
            return None, None, None
        return None, None, "no Convoy thread root resolves from cwd"
    matches = seats_for_worktree(resolved, cwd)
    if len(matches) != 1:
        chairs = [str(row.get("session_id") or "") for row in matches]
        detail = ", ".join(chairs) if chairs else "none"
        return resolved, None, "end refuses ambiguous/unseated cwd; matching chairs: " + detail
    return resolved, matches[0], None


def end_task(
    *,
    root: Path | str | None = None,
    cwd: Path | str | None = None,
    summary: str | None = None,
    push: bool = False,
    hook_payload: dict[str, Any] | None = None,
    git_runner: GitRunner = _run_git,
) -> dict[str, Any]:
    """Record one heartbeat/task-end row and optionally run plain git push.

    ``hook_payload is not None`` is the automatic path.  It never pushes,
    even if a hostile payload contains a field named ``push``.
    """
    automatic = hook_payload is not None
    payload = hook_payload or {}
    raw_cwd = payload.get("cwd") if automatic else cwd
    worktree = Path(raw_cwd or cwd or Path.cwd()).resolve()

    if automatic:
        event = payload.get("hook_event_name") or payload.get("hookEventName") or "Stop"
        if str(event).lower() != "stop":
            return {"ok": True, "skipped": True, "reason": "not a Stop hook"}
        push = False

    thread_root, seat, error = _resolve_identity(
        root=root, cwd=worktree, allow_missing_root=automatic,
    )
    if error:
        return {"ok": False, "skipped": automatic, "error": error}
    if thread_root is None or seat is None:
        return {"ok": True, "skipped": True, "reason": "not in a Convoy worktree"}

    chair = str(seat.get("session_id") or "").strip()
    harness = str(seat.get("to") or "").strip() or None
    key = _event_key(thread_root, chair, payload) if automatic else None
    if _seen(thread_root, key):
        return {"ok": True, "deduplicated": True, "chair": chair, "event_key": key}

    git: dict[str, Any] | None = None
    push_status = "not-requested"
    ok = True
    command_error: str | None = None
    feed_error: str | None = None
    if not automatic:
        git = _git_snapshot(worktree, git_runner)
        if push:
            if not git.get("ok"):
                push_status = "refused"
                ok = False
                command_error = str(git.get("error") or "git state unavailable")
                feed_error = "git state unavailable"
            elif git.get("dirty"):
                push_status = "refused"
                ok = False
                command_error = "refuse --push: worktree has uncommitted changes"
                feed_error = command_error
            elif not git.get("branch"):
                push_status = "refused"
                ok = False
                command_error = "refuse --push: HEAD is detached"
                feed_error = command_error
            elif not git.get("upstream"):
                push_status = "refused"
                ok = False
                command_error = "refuse --push: current branch has no configured upstream"
                feed_error = command_error
            else:
                try:
                    result = git_runner(["push"], worktree)
                except (OSError, subprocess.SubprocessError) as exc:
                    result = None
                    command_error = type(exc).__name__ + ": " + str(exc)
                    feed_error = "git push could not start"
                if result is not None and result.returncode == 0:
                    push_status = "pushed"
                else:
                    push_status = "failed"
                    ok = False
                    if command_error is None:
                        command_error = ((result.stderr or result.stdout or "git push failed").strip())
                    feed_error = "git push failed"

    default_summary = (
        "heartbeat: " + (harness or "neuron") + " turn ended"
        if automatic else "task ended"
    )
    text, truncated = _one_line(summary, default_summary)
    extra: dict[str, Any] = {
        "event": "turn-end" if automatic else "task-end",
        "automatic": automatic,
        "harness": harness,
        "push_requested": bool(push),
        "push_status": push_status,
    }
    if truncated:
        extra["truncated"] = True
    if key:
        extra["event_key"] = key
    if git:
        extra.update({
            "branch": git.get("branch"),
            "git_sha": git.get("git_sha"),
            "dirty": git.get("dirty"),
            "upstream": git.get("upstream"),
        })
    if feed_error:
        extra["error"] = feed_error[:STAMP_MAX_CHARS]

    # Codex loads project and plugin hooks together. Serialize our own Stop
    # writers so both sources cannot win the event-key check concurrently.
    with _exclusive(feed_path(thread_root)):
        if _seen(thread_root, key):
            return {"ok": True, "deduplicated": True, "chair": chair, "event_key": key}
        row = hook(
            thread_root, "heartbeat", text, instance_id=chair,
            extra=extra, author=chair,
        )
    card: dict[str, Any] = {
        "ok": ok,
        "chair": chair,
        "root": str(thread_root),
        "heartbeat": row,
        "push_requested": bool(push),
        "push_status": push_status,
    }
    if command_error:
        card["error"] = command_error
    return card
