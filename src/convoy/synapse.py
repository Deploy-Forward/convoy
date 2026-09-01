"""Phase 1 synapse: pointers in stdin, real session_id or null, dry-run cannot mint an id."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .context import pack, stdin_for
from .gitstate import git_state
from .layer import hook
from .usage import normalize_usage_remaining, probe
from .convoy import list_seats, read_id, read_thread
from .registry import live_on_branch, lookup, lookup_any, parse_agents_jsonl, parse_session_id, register

Runner = Callable[..., dict[str, Any]]

_WRAPPER_NAMES = frozenset({
    "ola-brain",
    "ola-brain.exe",
    "ola_brain",
    "ola_brain.exe",
    "side-chat",
    "side-chat.exe",
    "ultracode-shim",
    "ultracode-shim.exe",
    "ultracodeshim",
    "ultracodeshim.exe",
})

_NATIVE_BIN = {
    "grok": "grok",
    "grok.exe": "grok",
    "claude": "claude",
    "claude.exe": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "codex.exe": "codex",
    "cursor-agent": "cursor-agent",
    "cursor-agent.exe": "cursor-agent",
    "cursor_agent": "cursor-agent",
    "agy": "agy",
    "agy.exe": "agy",
    "antigravity": "agy",
    "antigravity-cli": "agy",
    "hermes": "hermes",
    "hermes.exe": "hermes",
    "pi": "pi",
    "pi.exe": "pi",
}


def _normalize_target_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def _is_wrapper_name(name: str) -> bool:
    key = _normalize_target_name(name)
    return key in _WRAPPER_NAMES


def _native_harness_bin(to: str) -> str:
    key = _normalize_target_name(to)
    if key in _NATIVE_BIN:
        return _NATIVE_BIN[key]
    if key.endswith(".exe"):
        return key[:-4]
    return key


def fake_runner(to: str, body: str, instance_id: str | None = None, label: str | None = None, **_k: Any) -> dict[str, Any]:
    sid = instance_id or ("spawned-" + to + (("-" + label) if label else ""))
    return {
        "ok": True,
        "to": to,
        "session_id": sid,
        "model": None,
        "usage_remaining": None,
        "body": "ACK " + to + ": " + body,
        "label": label,
    }

def ola_runner(to: str, body: str, instance_id: str | None = None, label: str | None = None, cwd: str | None = None, worktree: str | None = None, **_k: Any) -> dict[str, Any]:
    target = instance_id or to
    brain = os.environ.get("OLA_BRAIN") or shutil.which("ola-brain") or r"C:\Users\marco\.local\bin\ola-brain.exe"
    cmd = [brain, "side-chat", "send"]
    if label and not instance_id:
        cmd.extend(["--label", label])
    cmd.extend([target, body])
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=cwd,
    )
    text = (r.stdout or "") + (r.stderr or "")
    session_id = parse_session_id(r.stdout or "") or parse_session_id(text)
    if not session_id and cwd:
        session_id = parse_agents_jsonl(Path(cwd), to, label=label)
    if instance_id:
        session_id = instance_id
    return {
        "ok": r.returncode == 0,
        "to": to,
        "session_id": session_id,
        "model": None,
        "usage_remaining": None,
        "body": text.strip()[-2000:] if text.strip() else None,
        "exit_code": r.returncode,
        "label": label,
    }


def native_runner(
    to: str,
    body: str,
    instance_id: str | None = None,
    label: str | None = None,
    cwd: str | None = None,
    worktree: str | None = None,
    resume: str | None = None,
    **_k: Any,
) -> dict[str, Any]:
    harness = _native_harness_bin(to)
    if _is_wrapper_name(harness):
        return {
            "ok": False,
            "to": to,
            "session_id": instance_id,
            "model": None,
            "usage_remaining": None,
            "body": "refuse wrapper target: " + str(to),
            "exit_code": 2,
            "label": label,
            "argv": [harness],
        }
    exe = shutil.which(harness) or (shutil.which(harness + ".exe") if not harness.endswith(".exe") else None) or harness
    cmd = [exe]
    rid = resume if isinstance(resume, str) and resume.strip() else instance_id
    if isinstance(rid, str) and rid.strip():
        if harness == "codex":
            cmd.extend(["resume", rid.strip()])
        else:
            cmd.extend(["--resume", rid.strip()])
    try:
        r = subprocess.run(
            cmd,
            input=body,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=cwd,
        )
    except OSError as e:
        return {
            "ok": False,
            "to": to,
            "session_id": instance_id,
            "model": None,
            "usage_remaining": None,
            "body": str(e),
            "exit_code": 127,
            "label": label,
            "argv": cmd,
        }
    text = (r.stdout or "") + (r.stderr or "")
    session_id = parse_session_id(r.stdout or "") or parse_session_id(text)
    if not session_id and cwd:
        session_id = parse_agents_jsonl(Path(cwd), to, label=label)
    if instance_id:
        session_id = instance_id
    return {
        "ok": r.returncode == 0,
        "to": to,
        "session_id": session_id,
        "model": None,
        "usage_remaining": None,
        "body": text.strip()[-2000:] if text.strip() else None,
        "exit_code": r.returncode,
        "label": label,
        "argv": cmd,
    }


def send_one(
    root: Path,
    to: str,
    body: str,
    instance_id: str | None = None,
    label: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    worktree: str | None = None,
    probe_fn=None,
    resume: str | None = None,
    allow_interactive_resume: bool = True,
) -> dict[str, Any]:
    cwd_root = Path(worktree).resolve() if worktree else Path(root).resolve()
    cid = read_id(root)
    target_name = str(to or "").strip()
    resume_token = resume.strip() if isinstance(resume, str) and resume.strip() else None
    resolved_instance_id = instance_id.strip() if isinstance(instance_id, str) and instance_id.strip() else None

    home_thread = read_thread(root)

    def _pack_message(current_instance_id: str | None) -> tuple[dict[str, Any], str]:
        packed_row = pack(cwd_root, instance_id=current_instance_id)
        packed_row["worktree"] = str(cwd_root) if worktree else packed_row.get("worktree")
        # Seat worktrees have no .convoy; the home --root layer owns thread
        # identity. Overlay only real values — null never clobbers a seat id.
        if cid:
            packed_row["convoy_id"] = cid
        if home_thread:
            packed_row["thread_key"] = home_thread
        return packed_row, stdin_for(packed_row, body)

    packed, message = _pack_message(resolved_instance_id)
    if _is_wrapper_name(target_name):
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "model": None,
            "usage_remaining": None,
            "error": "refuse wrapper target: " + target_name,
            "pointers": packed,
            "convoy_id": cid,
        }
    if dry_run:
        card = {
            "ok": True,
            "to": to,
            "session_id": None,
            "model": None,
            "usage_remaining": None,
            "body": None,
            "dry_run": True,
            "stdin": message,
            "pointers": packed,
            "convoy_id": cid,
        }
        return card
    if probe_fn is not None:
        usage = probe_fn(to)
    elif runner in (ola_runner, native_runner):
        usage = probe(to)
    else:
        usage = {"usage_remaining": None, "limited": False, "raw": None}
    if usage.get("limited"):
        # Grok has no meter; even a lying probe must not surface one.
        limited_remaining = None if _normalize_target_name(target_name) == "grok" else normalize_usage_remaining(usage.get("usage_remaining"))
        ask = {
            "action": "bring_up",
            "handoff": ".ola/*handoff*",
            "text": to + " limited: ASK the user to bring_up / open a pane, or write a .ola/*handoff* file; do not steal a TUI, do not mint a sibling session, do not guess remaining quota",
        }
        # v2: the feed row carries the whole ask card so siblings pulling
        # feed --since see the remedy, not just the caller.
        hook(root, kind="refuse", summary=to + " limited", instance_id=resolved_instance_id, extra={"to": to, "raw": usage.get("raw"), "ask": ask})
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "model": None,
            "usage_remaining": limited_remaining,
            "refused": True,
            "error": to + " limited",
            "ask": ask,
            "body": usage.get("raw"),
            "pointers": packed,
            "convoy_id": cid,
        }
    if not allow_interactive_resume and (resolved_instance_id or resume_token):
        # No-steal outranks registry resolution: a live send that names any
        # resume token refuses before lookups can mask it as "not in registry".
        hook(
            root,
            kind="refuse",
            summary=to + " live resume refused",
            instance_id=resolved_instance_id,
            extra={"to": to, "reason": "no-steal-live-resume"},
        )
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "model": None,
            "usage_remaining": normalize_usage_remaining(usage.get("usage_remaining")),
            "refused": True,
            "error": "live send resume refused: would spawn a second interactive session",
            "body": "RED: convoy send --live does not steal/resume an active TUI session",
            "pointers": packed,
            "convoy_id": cid,
        }
    seat_row = None
    if resolved_instance_id:
        seat_row = lookup_any(root, resolved_instance_id, to=target_name, worktree=worktree)
        if seat_row is None and lookup(root, resolved_instance_id) is None:
            return {
                "ok": False,
                "to": to,
                "session_id": None,
                "error": "instance_id not in registry",
                "pointers": packed,
                "convoy_id": cid,
            }
        if isinstance(seat_row, dict):
            sid = seat_row.get("session_id")
            if isinstance(sid, str) and sid.strip():
                resolved_instance_id = sid.strip()
            if not resume_token:
                vendor_resume = seat_row.get("resume") or seat_row.get("vendor_session_id")
                if isinstance(vendor_resume, str) and vendor_resume.strip():
                    resume_token = vendor_resume.strip()
    elif resume_token:
        seat_row = lookup_any(root, resume_token, to=target_name, worktree=worktree)
        if isinstance(seat_row, dict):
            sid = seat_row.get("session_id")
            if isinstance(sid, str) and sid.strip():
                resolved_instance_id = sid.strip()

    packed, message = _pack_message(resolved_instance_id)
    if resolved_instance_id and lookup(root, resolved_instance_id) is None:
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "error": "instance_id not in registry",
            "pointers": packed,
            "convoy_id": cid,
        }
    if not resolved_instance_id and not resume_token:
        cid = read_id(root)
        if cid:
            for s in list_seats(root, convoy_id=cid):
                if s.get("to") == to:
                    return {
                        "ok": False,
                        "to": to,
                        "session_id": None,
                        "error": "seat exists; attach and resume session_id",
                        "pointers": packed,
                        "convoy_id": cid,
                    }
    branch = packed.get("branch")
    if not resolved_instance_id and not resume_token and not worktree:
        siblings = live_on_branch(root, branch)
        if siblings:
            return {
                "ok": False,
                "to": to,
                "session_id": None,
                "error": "two agents on one branch without a worktree is a bug",
                "branch": branch,
                "worktree": packed.get("worktree"),
                "pointers": packed,
                "convoy_id": cid,
            }
    run = runner or fake_runner
    card = run(
        to,
        message,
        instance_id=resolved_instance_id,
        label=label,
        cwd=str(cwd_root),
        worktree=worktree,
        resume=resume_token,
    )
    sid = card.get("session_id")
    state = git_state(cwd_root)
    extra = {"label": label, "worktree": str(cwd_root), **state}
    if sid and lookup(root, sid) is None:
        register(root, sid, to, extra=extra)
    hook(root, kind="synapse", summary="send " + to, instance_id=sid, extra={"to": to, "ok": card.get("ok"), "dry_run": False, **extra})
    card["pointers"] = packed
    card["stdin"] = message
    card["usage_remaining"] = normalize_usage_remaining(usage.get("usage_remaining"))
    card["convoy_id"] = cid
    return card

def send_many(
    root: Path,
    targets: list[str],
    body: str,
    runner: Runner | None = None,
    worktrees: list[str] | None = None,
    label: str | None = None,
    dry_run: bool = False,
    probe_fn=None,
    allow_interactive_resume: bool = True,
) -> list[dict[str, Any]]:
    if len(targets) < 1:
        raise ValueError("need at least one --to")
    wts: list[str | None] = list(worktrees) if worktrees else [None] * len(targets)
    if len(wts) != len(targets):
        raise ValueError("need one worktree per --to")
    cards: list[dict[str, Any] | None] = [None] * len(targets)
    def job(i: int, to: str, wt: str | None):
        lbl = (str(label) + "-" + to) if label and len(targets) > 1 else label
        return i, send_one(
            root,
            to,
            body,
            label=lbl,
            runner=runner,
            dry_run=dry_run,
            worktree=wt,
            probe_fn=probe_fn,
            allow_interactive_resume=allow_interactive_resume,
        )
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = [pool.submit(job, i, t, wts[i]) for i, t in enumerate(targets)]
        for fut in as_completed(futs):
            i, card = fut.result()
            cards[i] = card
    return [c for c in cards if c is not None]
