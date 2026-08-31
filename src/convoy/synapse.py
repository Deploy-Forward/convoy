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
from .convoy import list_seats, read_id
from .registry import live_on_branch, lookup, parse_agents_jsonl, parse_session_id, register

Runner = Callable[..., dict[str, Any]]

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

def send_one(root: Path, to: str, body: str, instance_id: str | None = None, label: str | None = None, runner: Runner | None = None, dry_run: bool = False, worktree: str | None = None, probe_fn=None) -> dict[str, Any]:
    cwd_root = Path(worktree).resolve() if worktree else Path(root).resolve()
    packed = pack(cwd_root, instance_id=instance_id)
    packed["worktree"] = str(cwd_root) if worktree else packed.get("worktree")
    message = stdin_for(packed, body)
    cid = read_id(root)
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
    elif runner is ola_runner:
        usage = probe(to)
    else:
        usage = {"usage_remaining": None, "limited": False, "raw": None}
    if usage.get("limited"):
        hook(root, kind="refuse", summary=to + " limited", instance_id=instance_id, extra={"to": to, "raw": usage.get("raw")})
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "model": None,
            "usage_remaining": normalize_usage_remaining(usage.get("usage_remaining")),
            "refused": True,
            "error": to + " limited",
            "body": usage.get("raw"),
            "pointers": packed,
            "convoy_id": cid,
        }
    if instance_id and lookup(root, instance_id) is None:
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "error": "instance_id not in registry",
            "pointers": packed,
            "convoy_id": cid,
        }
    if not instance_id:
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
    if not instance_id and not worktree:
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
    card = run(to, message, instance_id=instance_id, label=label, cwd=str(cwd_root), worktree=worktree)
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

def send_many(root: Path, targets: list[str], body: str, runner: Runner | None = None, worktrees: list[str] | None = None, label: str | None = None, dry_run: bool = False, probe_fn=None) -> list[dict[str, Any]]:
    if len(targets) < 1:
        raise ValueError("need at least one --to")
    wts: list[str | None] = list(worktrees) if worktrees else [None] * len(targets)
    if len(wts) != len(targets):
        raise ValueError("need one worktree per --to")
    cards: list[dict[str, Any] | None] = [None] * len(targets)
    def job(i: int, to: str, wt: str | None):
        lbl = (str(label) + "-" + to) if label and len(targets) > 1 else label
        return i, send_one(root, to, body, label=lbl, runner=runner, dry_run=dry_run, worktree=wt, probe_fn=probe_fn)
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = [pool.submit(job, i, t, wts[i]) for i, t in enumerate(targets)]
        for fut in as_completed(futs):
            i, card = fut.result()
            cards[i] = card
    return [c for c in cards if c is not None]
