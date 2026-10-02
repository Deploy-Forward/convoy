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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .convoy import observe_resume, read_id
from .inbox import _exclusive, pending, resolve_root, seats_for_worktree, stop_block
from .layer import STAMP_MAX_CHARS, feed_path, feed_since, hook, utc_now
from .pulse import write_pulse


GitRunner = Callable[..., subprocess.CompletedProcess[str]]

EPOCH = "1970-01-01T00:00:00.000000Z"
# At or above this on either window the chair stops taking new work and asks
# for an intent handoff instead. 95 leaves room to write one.
QUOTA_THRESHOLD_PCT = 95
# The rolling handoff is read by a machine on relaunch, not by a human over
# coffee: bounded, derivable, rewritten whole.
ROLLING_HANDOFF_MAX_BYTES = 4096
WAIT_TIMEOUT_S = 600.0


def _one_line(value: Any, default: str) -> tuple[str, bool]:
    text = " ".join(str(value or "").split()) or default
    truncated = len(text) > STAMP_MAX_CHARS
    return text[:STAMP_MAX_CHARS], truncated


def _event_key(root: Path, chair: str, payload: dict[str, Any]) -> str | None:
    session = payload.get("session_id") or payload.get("sessionId")
    turn = payload.get("turn_id") or payload.get("turnId")
    event = payload.get("hook_event_name") or payload.get("hookEventName") or "Stop"
    if not session:
        return None
    if turn:
        discriminator = "turn\0" + str(turn)
    else:
        # Claude Stop does not expose a turn id. Use private hook inputs only
        # as hash material so project + plugin hooks for the same Stop collapse
        # without persisting a transcript path or assistant message.
        message = payload.get("last_assistant_message") or payload.get("lastAssistantMessage")
        transcript = payload.get("transcript_path") or payload.get("transcriptPath")
        transcript_state = ""
        if transcript:
            try:
                stat = Path(str(transcript)).stat()
                transcript_state = str(transcript) + "\0" + str(stat.st_size) + "\0" + str(stat.st_mtime_ns)
            except OSError:
                transcript_state = str(transcript)
        if not message and not transcript_state:
            return None
        discriminator = "fallback\0" + str(message or "") + "\0" + transcript_state
    raw = "\0".join((str(read_id(root) or ""), chair, str(event), str(session), discriminator))
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


def _last_note(root: Path, chair: str) -> str | None:
    """The chair's last written note. Derivable: nobody is asked for it."""
    last = None
    try:
        rows = feed_since(root, EPOCH)
    except (OSError, ValueError):
        return None
    for row in rows:
        if row.get("kind") == "note" and (row.get("instance_id") == chair or row.get("from") == chair):
            last = row
    if last is None:
        return None
    return " ".join(str(last.get("summary") or "").split()) or None


def rolling_handoff_path(root: Path, chair: str) -> Path:
    return Path(root) / ".convoy" / "handoff" / (str(chair) + ".rolling.md")


def write_rolling_handoff(root: Path, chair: str, *, seat: dict[str, Any], git: dict[str, Any],
                          pending_count: int, now: str) -> Path:
    """Rewrite the chair's rolling handoff from facts nobody had to author.

    Every relaunch before this booted a neuron that knew where it was and not
    when it left off, because the only handoff was one a model remembered to
    write. Branch, sha, dirtiness, the last note, the queue depth, the life
    and whether a resume exists are all on disk already; a Stop is simply the
    moment they are all true at once.

    Rewritten whole, never appended, and bounded: this file is read on boot,
    and an unbounded file read on boot is a context bill.
    """
    incarnation = seat.get("incarnation")
    body = [
        "# rolling handoff (machine-written, rewritten at every Stop)",
        "",
        "## chair " + str(chair),
        "",
        "- as of: " + now,
        "- harness: " + str(seat.get("to") or "unknown"),
        "- incarnation " + (str(incarnation) if incarnation is not None else "null (never hosted)"),
        # Presence only. The id itself is a vendor secret and never rides in prose.
        "- resume: " + ("present" if str(seat.get("resume") or "").strip() else "null until observed"),
        "- worktree: " + str(seat.get("worktree") or "unknown"),
        "- branch: " + str(git.get("branch") or "detached or unknown"),
        "- HEAD: " + str(git.get("git_sha") or "unknown"),
        "- dirty: " + ("yes" if git.get("dirty") else "no" if git.get("dirty") is False else "unknown"),
        "- inbox rows pending: " + str(int(pending_count)),
        "- last note: " + (_last_note(root, chair) or "none"),
        "",
        "Nothing here was authored: every line is read back from the record.",
    ]
    text = "\n".join(body) + "\n"
    raw = text.encode("utf-8")
    if len(raw) > ROLLING_HANDOFF_MAX_BYTES:
        text = raw[:ROLLING_HANDOFF_MAX_BYTES - 4].decode("utf-8", errors="ignore") + "\n...\n"
    path = rolling_handoff_path(root, chair)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _seat_quota(seat: dict[str, Any]) -> dict[str, Any] | None:
    """This chair's own quota reading, or None.

    Codex only, and only through the rollout the seat's OWN resume id names
    (usage.rollout_rate_limits_for_session). Claude and Grok stay null until a
    source is verified: `claude -p /usage` is a machine-wide probe, not a
    pane's, and Grok publishes nothing per session. Null, never a guess - a
    number from another chair's conversation would block this one on a
    stranger's ceiling.
    """
    harness = str(seat.get("to") or "").strip().lower()
    if not harness.startswith("codex"):
        return None
    if str(seat.get("resume_for") or "codex").strip().lower() not in ("", "codex"):
        return None
    from .usage import rollout_rate_limits_for_session
    try:
        return rollout_rate_limits_for_session(seat.get("resume"))
    except OSError:
        return None


def _crossed(reading: dict[str, Any] | None) -> tuple[str, int, str | None] | None:
    """The window at or over the ceiling, worst first, or None."""
    if not isinstance(reading, dict):
        return None
    resets = reading.get("resets") or {}
    worst = None
    for window, key in (("session", "session_pct"), ("week", "week_pct")):
        value = reading.get(key)
        if not isinstance(value, int) or value < QUOTA_THRESHOLD_PCT:
            continue
        if worst is None or value > worst[1]:
            worst = (window, value, resets.get(window))
    return worst


def _threshold_seen(root: Path, chair: str, incarnation: Any, resets_at: Any, window: str) -> bool:
    """Once per (chair, incarnation, resets_at). The ceiling does not move
    inside a window, so a row per Stop would be a row per turn."""
    try:
        rows = feed_since(root, EPOCH)
    except (OSError, ValueError):
        return False
    for row in rows:
        if row.get("kind") != "threshold" or row.get("chair") != chair:
            continue
        if row.get("incarnation") == incarnation and row.get("resets_at") == resets_at \
                and row.get("window") == window:
            return True
    return False


def _spawn_waiter(root: Path, chair: str, incarnation: Any) -> dict[str, Any]:
    """Start the slim waiter, detached. Never through the CLI: that import
    graph is what the OS killed under memory pressure (see wait.py)."""
    argv = [sys.executable, "-m", "convoy.wait", "--root", str(root), "--seat", str(chair),
            "--timeout", str(WAIT_TIMEOUT_S)]
    if incarnation is not None:
        argv.extend(["--incarnation", str(int(incarnation))])
    try:
        from .cmd import quiet_spawn_kwargs
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **quiet_spawn_kwargs())
    except (OSError, ValueError) as exc:
        return {"spawned": False, "error": type(exc).__name__ + ": " + str(exc)}
    return {"spawned": True, "pid": int(process.pid)}


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
    if automatic:
        # This payload is where Convoy has held the vendor session id
        # at every turn end since the beginning, and dropped it. The feed rule
        # below is unchanged - the id is still only hash material there - but
        # the SEAT learns it, matched by this cwd, never by recency. Null
        # until observed; an id already on the row is never overwritten.
        observe_resume(
            thread_root, chair,
            payload.get("session_id") or payload.get("sessionId"),
            to=harness,
        )
    key = _event_key(thread_root, chair, payload) if automatic else None
    if _seen(thread_root, key):
        return {"ok": True, "deduplicated": True, "chair": chair, "event_key": key, "hook": {}}

    git: dict[str, Any] | None = None
    convoy_files: list[str] = []
    push_status = "not-requested"
    ok = True
    command_error: str | None = None
    feed_error: str | None = None
    # The automatic path READS git now (branch, HEAD, dirty) because the
    # rolling handoff and the pulse's last_commit are derived from it. It
    # still never MUTATES git: `push` is forced False above and the only
    # writing command in this module sits behind the explicit --push flag.
    git = _git_snapshot(worktree, git_runner)
    if not automatic:
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
                    names = git_runner(["diff", "--name-only", "@{upstream}...HEAD"], worktree)
                    if names.returncode == 0:
                        from .identity import is_convoy_written
                        convoy_files = sorted(p for p in names.stdout.splitlines() if p.strip() and is_convoy_written(p))
                except (OSError, subprocess.SubprocessError):
                    convoy_files = []  # the warning is advice; it never blocks the push
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
    if convoy_files:
        card["convoy_files"] = convoy_files
        card["warning"] = ("these commits carry files Convoy writes into a worktree (" + ", ".join(convoy_files)
                           + "); check they were meant to be committed")
    if automatic:
        card.update(_stop_work(thread_root, chair, seat, git or {}))
    return card


def _stop_work(root: Path, chair: str, seat: dict[str, Any], git: dict[str, Any]) -> dict[str, Any]:
    """Everything a Stop is good for, in the order it matters.

    A Stop is the one moment Convoy is certain a neuron is listening, and the
    one moment every derivable fact about the chair is true at once. So:
    rewrite the handoff, stamp the pulse, record a quota ceiling if it was
    crossed, and then decide what to hand back - rows to work on, a ceiling to
    hand off at, or a waiter to sleep against.

    Nothing here may raise: a Stop hook that throws traps the agent.
    """
    out: dict[str, Any] = {"hook": {}}
    incarnation = seat.get("incarnation")
    now = utc_now()
    try:
        waiting = pending(root, chair)
    except (OSError, ValueError):
        waiting = []
    try:
        out["rolling_handoff"] = str(write_rolling_handoff(
            root, chair, seat=seat, git=git, pending_count=len(waiting), now=now))
    except (OSError, ValueError):
        pass

    reading = None
    try:
        reading = _seat_quota(seat)
    except Exception:       # a quota reading must never end a turn
        reading = None
    crossed = _crossed(reading)
    rate_pct = None
    if isinstance(reading, dict):
        pcts = [v for v in (reading.get("session_pct"), reading.get("week_pct")) if isinstance(v, int)]
        rate_pct = max(pcts) if pcts else None
    try:
        write_pulse(root, chair, pulse_source="stop", incarnation=incarnation,
                    last_commit=({"sha": git.get("git_sha"), "branch": git.get("branch")}
                                 if git.get("git_sha") else None),
                    rate_pct=rate_pct, ts=now)
    except (OSError, ValueError):
        pass

    if crossed is not None:
        window, used, resets_at = crossed
        if not _threshold_seen(root, chair, incarnation, resets_at, window):
            try:
                hook(root, "threshold",
                     "chair " + chair + " at " + str(used) + "% of its " + window + " window",
                     instance_id=chair, author=chair,
                     extra={"chair": chair, "harness": seat.get("to"), "window": window,
                            "used_percent": used, "resets_at": resets_at, "incarnation": incarnation})
            except (OSError, ValueError):
                pass

    if waiting:
        try:
            block = stop_block(root, chair)
        except (OSError, ValueError):
            block = None
        if block:
            out["hook"] = block
            return out
    if crossed is not None:
        window, used, resets_at = crossed
        stamp = now.replace(":", "-")
        target = Path(root) / ".convoy" / "handoff" / (chair + "-" + stamp + ".md")
        out["hook"] = {"decision": "block", "reason": (
            "Convoy quota gate: this seat is at " + str(used) + "% of its " + window +
            " window (resets " + str(resets_at or "unknown") + "). Do not start new work. "
            "Write the INTENT handoff a successor cannot derive - what you were "
            "about to do and why - to " + str(target) + ", then stop. The facts "
            "(branch, HEAD, dirty, queue, incarnation) are already written to " +
            str(rolling_handoff_path(root, chair)) + "; do not repeat them.")}
        return out

    out["waiter"] = _spawn_waiter(root, chair, incarnation)
    return out
