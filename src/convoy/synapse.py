"""Phase 1 synapse: pointers in stdin, real session_id or null, dry-run cannot mint an id."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .context import pack, stdin_for
from .gitstate import git_state
from .inbox import enqueue
from .layer import _VERIFIED_METHODS, hook
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


def is_wrapper_name(name: str) -> bool:
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
    if is_wrapper_name(harness):
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
        elif harness == "agy":
            # agy --help has no --resume; it resumes via --conversation <ID>
            cmd.extend(["--conversation", rid.strip()])
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


def runner_kind(run: Runner) -> str | None:
    """Identity-based runner discriminator stamped on every synapse row so the
    SoT can distinguish a native vendor send from a fake ACK."""
    if run is native_runner:
        return "native"
    if run is fake_runner:
        return "fake"
    return getattr(run, "__name__", None)


CODEX_NO_SESSION_WHY = "no Codex session id recorded (Convoy's Codex hooks not trusted or not yet run)"
# `codex queue` exiting 0 means the queue accepted the message, not that a turn started: a row was
# once found in Codex's own store for a dead pane. Only the neuron's own receipt proves delivery.
CODEX_QUEUE_ACCEPTED_WHY = ("codex queue accepted the message; that is not proof a turn started, "
                            "and only the neuron's own receipt proves delivery")
CODEX_QUEUE_FAILED_WHY = "codex queue did not run or exited non-zero; the row waits in the inbox"


def try_codex_queue(thread: str, body: str) -> dict[str, Any] | None:
    """Native Codex live-seat notify. Surface proven; delivery unproven."""
    exe = shutil.which("codex") or shutil.which("codex.CMD") or shutil.which("codex.cmd")
    if not exe:
        return None
    tid = str(thread or "").strip()
    if not tid:
        return None
    try:
        result = subprocess.run(
            [exe, "queue", "--thread", tid, "--message", str(body)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}


def proven_sender(sender: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(author, verified_by) for a synapse row: the sender only with its proof's method.

    `sender` is {chair, verified_by} from the caller's own proof: the chair whoami proves for
    a CLI body, or the conductor of a checked bearer. A sender without a verified method is
    a claim, and a synapse row records the sender as unknown rather than a claim."""
    if not isinstance(sender, dict):
        return None, None
    chair = sender.get("chair")
    method = sender.get("verified_by")
    if not isinstance(chair, str) or not chair.strip() or method not in _VERIFIED_METHODS:
        return None, None
    return chair.strip(), method


def deliver_to_live_seat(
    root: Path,
    to: str,
    body: str,
    *,
    session_id: str,
    resume_token: str | None,
    packed: dict[str, Any],
    cid: str | None,
    label: str | None,
    usage: dict[str, Any],
    extra_state: dict[str, Any] | None = None,
    card: dict[str, Any] | None = None,
    origin: dict[str, Any] | None = None,
    local_writer: bool = True,
    sender: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue a body for an existing occupant. Never spawn --resume.

    card / origin: what this delivery is ON BEHALF OF. A delegation lands
    on a chair through a token, for a card, from an origin, and until now
    none of the three were written down together - the platform could see a
    message and the board could see a delegation with nothing joining them.
    Both are null for an ordinary local send; absence is the honest answer and
    an invented id would be worse than none.
    """
    sid = str(session_id or "").strip()
    # Mint the token BEFORE any vendor push so it can ride inside the body:
    # a `codex queue` message arrives as an ordinary user turn, which the
    # receiver cannot tell from a human typing, so it cannot certify
    # delivery. With the token
    # in the text, an ack citing it is proof only Convoy could have sourced.
    token = uuid.uuid4().hex
    native: dict[str, Any] | None = None
    if _native_harness_bin(to) == "codex" and resume_token:
        framed = (
            "Convoy inbox (" + str(label or "synapse") + ") token=" + token + "\n"
            + str(body) + "\n\n"
            + "Delivered by Convoy `codex queue` into this live session. "
              "Cite the token when you ack so the channel is provable; "
              "this is not a human typing and not a second --resume."
        )
        native = try_codex_queue(resume_token, framed)
    # `codex queue` exiting 0 is NOT proof codex consumed the message (a row
    # can sit in codex's sqlite for a dead pane), so the
    # inbox row stays PENDING until the receiver drains it, exactly as for
    # every other harness. path_name records that a native route was used.
    path_name = "codex-queue" if native else "inbox"
    item = enqueue(root, sid, body, to=to, label=label, path_name=path_name, token=token)
    delivery = native["delivery"] if native else "queued"
    # Codex has no inbox hook that fires while it is idle: only `codex queue` can start a turn.
    # Say what the wake path did, never that the neuron woke.
    wake: dict[str, Any] = {}
    if _native_harness_bin(to) == "codex":
        if native:
            wake = {"wake": "codex-queue-accepted", "why": CODEX_QUEUE_ACCEPTED_WHY}
        else:
            wake = {"wake": "inbox-only", "why": CODEX_NO_SESSION_WHY if not resume_token else CODEX_QUEUE_FAILED_WHY}
    runner = native["runner"] if native else "inbox"
    state = git_state(Path(packed.get("worktree") or root))
    extra = {
        "ok": True,
        "dry_run": False,
        "runner": runner,
        "delivery": delivery,
        "delivered": False,
        "resume_stolen": False,
        "argv0": None,
        "label": label,
        "worktree": packed.get("worktree"),
        # The three that make the row a join, not a note.
        "token": item.get("token"),
        "card": dict(card) if isinstance(card, dict) else None,
        "origin": dict(origin) if isinstance(origin, dict) else None,
        **state,
    }
    if extra_state:
        extra.update(extra_state)
    author, verified_by = proven_sender(sender)
    # Store only referenced receipt tokens, not a second copy of the body.
    # Keep the released caller/bearer proof; recipients never become authors.
    import re
    replies = sorted(set(re.findall(r"\btoken=([a-fA-F0-9]{32})\b", str(body))))
    if replies and author:
        extra["reply_tokens"] = replies
    hook(root, kind="synapse", summary="send " + to, instance_id=sid, author=author,
         to=to, extra=extra, local_writer=local_writer, verified_by=verified_by)
    return {
        "ok": True,
        "to": to,
        "session_id": sid,
        "model": None,
        "usage_remaining": normalize_usage_remaining(usage.get("usage_remaining")),
        "body": None,
        "delivery": delivery,
        "delivered": False,
        "path": runner,
        "inbox": item.get("file"),
        "token": item.get("token"),
        "resume_stolen": False,
        "pointers": packed,
        "stdin": body,
        "convoy_id": cid,
        **wake,
    }


def _resolve_chair_address(root: Path, to: str, instance_id: str | None, worktree: str | None) -> tuple[str, str | None, str | None]:
    """(harness, chair session_id, worktree) when `to` is a chair's
    session_id on this thread; otherwise everything unchanged."""
    want = str(to or "").strip()
    given = instance_id.strip() if isinstance(instance_id, str) and instance_id.strip() else None
    if not want or given:
        return to, instance_id, worktree
    cid = read_id(root)
    if not cid:
        return to, instance_id, worktree
    hits = [s for s in list_seats(root, convoy_id=cid) if s.get("session_id") == want and s.get("to")]
    if len(hits) != 1:
        return to, instance_id, worktree
    seat = hits[0]
    wt = worktree if worktree else (str(seat["worktree"]) if seat.get("worktree") else None)
    return str(seat["to"]), str(seat["session_id"]), wt


def _send_one(
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
    card: dict[str, Any] | None = None,
    origin: dict[str, Any] | None = None,
    local_writer: bool = True,
    allow_unverified_launch: bool = False,
    sender: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Address a CHAIR by its name (`send --to codex-1`): a `to` that is a
    # chair session_id resolves to that chair's harness, id and worktree. A
    # harness name never resolves to a chair, even a lone one: that stays
    # the "seat exists; attach and resume session_id" refusal below, because
    # naming a vendor is not naming a neuron.
    to, instance_id, worktree = _resolve_chair_address(root, to, instance_id, worktree)
    # Check the authoritative seat before probes, packing, dry plans or any
    # native queue. The registry is a resume map, not detach authority.
    from .registry import lookup_any as _lookup_target
    address = instance_id or resume
    target = _lookup_target(root, address, to=to) if address else None
    sid = (target or {}).get("session_id") or instance_id
    seats = list_seats(root)
    harness_seats = [s for s in seats if s.get("to") == to]
    if (any(s.get("session_id") == sid and s.get("detached") for s in seats) or
        (not address and harness_seats and all(s.get("detached") for s in harness_seats))):
        return {"ok": False, "refused": True, "to": to, "session_id": sid,
                "error": "detached; attach again", "delivery": "refused", "delivered": False}
    cwd_root = Path(worktree).resolve() if worktree else Path(root).resolve()
    cid = read_id(root)
    target_name = str(to or "").strip()
    resume_token = resume.strip() if isinstance(resume, str) and resume.strip() else None
    resolved_instance_id = instance_id.strip() if isinstance(instance_id, str) and instance_id.strip() else None

    home_thread = read_thread(root)

    def _pack_message(current_instance_id: str | None) -> tuple[dict[str, Any], str]:
        packed_row = pack(cwd_root, instance_id=current_instance_id, write=not dry_run)
        packed_row["worktree"] = str(cwd_root) if worktree else packed_row.get("worktree")
        # Seat worktrees have no .convoy; the home --root layer owns thread
        # identity. Overlay only real values — null never clobbers a seat id.
        if cid:
            packed_row["convoy_id"] = cid
        if home_thread:
            packed_row["thread_key"] = home_thread
        return packed_row, stdin_for(packed_row, body)

    packed, message = _pack_message(resolved_instance_id)
    if is_wrapper_name(target_name):
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
    if not resolved_instance_id and not resume_token and cid and \
            any(s.get("to") == to for s in list_seats(root, convoy_id=cid)):
        # A harness name is not a neuron: a seated chair of that harness is addressed by its
        # id. Checked before the dry plan, so a dry run refuses exactly as the send would.
        return {
            "ok": False,
            "refused": "occupied",
            "to": to,
            "session_id": None,
            "error": "seat exists; attach and resume session_id",
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
    def _launch_refusal():
        from .harness_contract import validate_launch_eligibility
        try:
            validate_launch_eligibility(to, allow_unverified_launch=allow_unverified_launch)
        except ValueError as exc:
            return {"ok": False, "refused": True, "to": to, "session_id": None,
                    "error": str(exc), "pointers": packed, "convoy_id": cid}
        return None

    # A new headless send must report eligibility before a usage snapshot
    # can refuse or write a misleading limited/bring_up remedy. Existing
    # Registered chair/resume addresses retain their queue and no-steal
    # routing below. An unregistered resume token is not an existing chair.
    if runner is native_runner and not resolved_instance_id:
        if resume_token:
            resume_seat = lookup_any(root, resume_token, to=target_name, worktree=worktree)
            registered_resume = (isinstance(resume_seat, dict) and
                                 isinstance(resume_seat.get("session_id"), str) and
                                 bool(resume_seat["session_id"].strip()))
            needs_early_gate = not registered_resume
        else:
            existing_harness_seat = bool(cid) and any(
                s.get("to") == to for s in list_seats(root, convoy_id=cid))
            needs_early_gate = not existing_harness_seat
        if needs_early_gate:
            refusal = _launch_refusal()
            if refusal is not None:
                return refusal
    if probe_fn is not None:
        usage = probe_fn(to)
    elif runner is native_runner:
        usage = probe(to)
    else:
        usage = {"usage_remaining": None, "limited": False, "raw": None}
    if usage.get("limited") and not resolved_instance_id:
        # A LIVE chair is never refused on a usage snapshot: the queue costs
        # nothing and the vendor's own pane refuses work if it is truly out;
        # snapshots are stale and per-login (a grok pane reading 100% weekly
        # kept working; one machine can carry two codex logins). The refusal
        # stays for spawning a NEW vendor session, which would fail.
        limited_remaining = None if _normalize_target_name(target_name) == "grok" else normalize_usage_remaining(usage.get("usage_remaining"))
        ask = {
            "action": "bring_up",
            "handoff": ".convoy/handoff/<chair>-<ts>.md",
            "text": to + " limited: ASK the user to bring_up / open a pane, or write a .convoy/handoff/<chair>-<ts>.md file; do not steal a TUI, do not mint a sibling session, do not guess remaining quota",
        }
        # v2: the feed row carries the whole ask card so siblings pulling
        # feed --since see the remedy, not just the caller.
        hook(root, kind="refuse", summary=to + " limited", instance_id=resolved_instance_id, author=None,
             to=to, extra={"raw": usage.get("raw"), "ask": ask})
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
    steal_blocked = not allow_interactive_resume and (resolved_instance_id or resume_token)

    def _refuse_steal(instance: str | None) -> dict[str, Any]:
        hook(
            root,
            kind="refuse",
            summary=to + " live resume refused",
            instance_id=instance,
            author=None,
            to=to,
            extra={"reason": "no-steal-live-resume"},
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
        if seat_row is None:
            # The registry is a resume map a send fills in; a chair seated without one is
            # still a known instance: its seats.jsonl row answers before any refusal.
            seat_row = _seated_row(root, resolved_instance_id)
        if seat_row is None and lookup(root, resolved_instance_id) is None:
            if steal_blocked:
                return _refuse_steal(resolved_instance_id)
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
    if steal_blocked and not resolved_instance_id:
        return _refuse_steal(None)
    if resolved_instance_id and lookup(root, resolved_instance_id) is None and \
            _seated_row(root, resolved_instance_id) is None:
        if steal_blocked:
            return _refuse_steal(resolved_instance_id)
        return {
            "ok": False,
            "to": to,
            "session_id": None,
            "error": "instance_id not in registry",
            "pointers": packed,
            "convoy_id": cid,
        }
    if resolved_instance_id and (steal_blocked or runner in (None, fake_runner)):
        return deliver_to_live_seat(
            root,
            to,
            body,
            session_id=resolved_instance_id,
            resume_token=resume_token,
            packed=packed,
            cid=cid,
            label=label,
            usage=usage,
            card=card,
            origin=origin,
            local_writer=local_writer,
            sender=sender,
        )
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
    # Queuing to an existing chair above is not a launch. A native headless
    # invocation here is, even when it resumes a vendor session.
    if runner is native_runner:
        refusal = _launch_refusal()
        if refusal is not None:
            return refusal
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
    argv = card.get("argv")
    argv0 = argv[0] if isinstance(argv, list) and argv else None
    # instance_id here is the TARGET/spawned session (the row's subject), not
    # the sender: the sender is recorded only when proven, else "unknown".
    author, verified_by = proven_sender(sender)
    hook(root, kind="synapse", summary="send " + to, instance_id=sid, author=author, to=to,
         extra={"ok": card.get("ok"), "dry_run": False, "runner": runner_kind(run), "argv0": argv0, **extra},
         local_writer=local_writer, verified_by=verified_by)
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
    allow_unverified_launch: bool = False,
    sender: dict[str, Any] | None = None,
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
            allow_unverified_launch=allow_unverified_launch,
            sender=sender,
        )
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = [pool.submit(job, i, t, wts[i]) for i, t in enumerate(targets)]
        for fut in as_completed(futs):
            i, card = fut.result()
            cards[i] = card
    return [c for c in cards if c is not None]


def _seated_row(root: Path, session_id: str) -> dict[str, Any] | None:
    """The chair's own seat row when seats.jsonl has it, else None."""
    rows = [s for s in list_seats(root, require_session=True) if s.get("session_id") == session_id]
    return rows[-1] if rows else None


def send_one(root, to, body, *args, **kwargs):
    """send_one with an honest delivery label:
    recorded = a feed row exists and nothing reached a neuron (fake runner or
    dry run); executed = a fresh headless vendor session ran the body (not the
    open pane); refused / error = nothing happened; queued = named live seat
    inbox (or Codex native-queue). `delivered` is always False here: only an
    ack row AUTHORED BY THE TARGET proves delivery, and a card cannot author
    that. Queued cards already set delivery and keep delivered=false."""
    card = _send_one(root, to, body, *args, **kwargs)
    if isinstance(card, dict) and "delivery" not in card:
        runner = kwargs.get("runner", args[2] if len(args) > 2 else None)  # (instance_id, label, runner, ...)
        if card.get("refused"):
            card["delivery"] = "refused"
        elif not card.get("ok"):
            card["delivery"] = "error"
        elif card.get("dry_run") or runner is None or runner is fake_runner or getattr(runner, "__name__", "") == "fake_runner":
            card["delivery"] = "recorded"
        else:
            card["delivery"] = "executed"
        card["delivered"] = False
    return card
