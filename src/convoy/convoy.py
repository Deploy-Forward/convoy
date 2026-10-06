"""Durable convoy_id. Keys harness + model + thread + worktree to one convoy."""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import secrets
from pathlib import Path
from typing import Any

from .context import pack
from .filelock import append_line
from .harness_contract import effort_applied, validate_effort, validate_model, validate_where
from .index import claim as index_claim, record as index_record
from .layer import SCHEMA_VERSION, feed_since, hook
from .registry import register
from .repo import exclude_convoy_files
from .usage import probe, surface

def _id_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "id"

def _seats_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "seats.jsonl"

def _thread_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "thread"

CONDUCTOR = "grok-bot"


def broad_worktree(worktree: str | None) -> bool:
    """A drive/share root or user home cannot identify one neuron by path."""
    if not worktree:
        return False
    value = ntpath.normpath(str(worktree))
    drive, tail = ntpath.splitdrive(value)
    if (drive and tail in ("", "\\")) or value in ("/", "\\"):
        return True
    return ntpath.normcase(value) == ntpath.normcase(ntpath.normpath(str(Path.home())))

def _lead_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "lead"

def make_resume_key(convoy_id: str | None, thread: str | None, to: str | None, worktree: str | None = None) -> str:
    """Map key for (convoy, thread, harness, worktree). Not a session_id."""
    blob = (convoy_id or "") + "\0" + (thread or "") + "\0" + (to or "") + "\0" + (worktree or "")
    return "cvr_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def read_id(root: Path) -> str | None:
    path = _id_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def ensure_id(root: Path) -> str:
    """This root's convoy id, minted once. An existing id is claimed in the machine index:
    indexed when it is not, refused (ValueError) when it is another live thread's id."""
    existing = read_id(root)
    if existing:
        index_claim(root, existing, read_thread(root))
        return existing
    return _mint_id(root)


def remint_id(root: Path) -> str:
    """Give a copied root its own id (`init --new-id`); the original keeps the old one."""
    return _mint_id(root)


def _mint_id(root: Path) -> str:
    cid = "cvy_" + secrets.token_urlsafe(16)
    path = _id_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cid + "\n", encoding="utf-8")
    # The record is excluded the moment an id exists, before anything
    # else (seat rows, later a vendor session id) lands under .convoy/.
    exclude_convoy_files(root)
    index_record(root, cid, read_thread(root))
    return cid

def read_lead(root: Path) -> str | None:
    path = _lead_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def set_lead(root: Path, to: str) -> dict[str, Any]:
    if not to or not str(to).strip():
        raise ValueError("refuse empty lead")
    harness = str(to).strip().lower()
    cid = ensure_id(root)
    path = _lead_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(harness + "\n", encoding="utf-8")
    return {"ok": True, "convoy_id": cid, "conductor": lead_conductor(root), "lead": harness}


def lead_conductor(root: Path) -> str | None:
    """A card's `conductor`: the thread's lead chair, or null. The hosted conductor
    (CONDUCTOR) is named only where that hosted identity is meant."""
    from .lifecycle import lead_state
    return lead_state(root)["chair"]

def read_thread(root: Path) -> str | None:
    path = _thread_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or None

def _github_path(root: Path) -> Path:
    return Path(root) / ".convoy" / "github"

def read_github(root: Path) -> str | None:
    """The wizard's 'GitHub?' answer on this bind: 'yes' | 'no' | None when
    never asked. Null is never upgraded to a guess."""
    path = _github_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig").strip().lower()
    return text if text in ("yes", "no") else None

def set_github(root: Path, yes: bool) -> str:
    answer = "yes" if yes else "no"
    path = _github_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(answer + "\n", encoding="utf-8")
    return answer

def bind(root: Path, thread: str) -> dict[str, Any]:
    if not thread or not str(thread).strip():
        raise ValueError("refuse empty thread")
    key = str(thread).strip()
    cid = ensure_id(root)
    path = _thread_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    md = Path(root) / "thread.md"
    md.write_text(cid + "\n" + key + "\n", encoding="utf-8")
    excluded = exclude_convoy_files(root)
    index_record(root, cid, key)
    return {"ok": True, "convoy_id": cid, "thread": key, "excluded": excluded}

def seat(
    root: Path,
    to: str,
    session_id: str,
    worktree: str | None = None,
    model: str | None = None,
    resume: str | None = None,
    title: str | None = None,
    agent: str | None = None,
    effort: str | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    if not session_id:
        raise ValueError("refuse empty session_id")
    cid = ensure_id(root)
    wt = str(worktree) if worktree is not None else None
    if broad_worktree(wt):
        raise ValueError("refuse seat: broad worktree cannot identify one neuron: " + str(wt))
    # where: local (default) or cloud. cloud is refused unless this harness's
    # cloud block evidences an interactive attach (harness_effort.json). A
    # cloud chair has no local checkout, so a worktree is refused, not
    # dropped; C8 below is a local rule and never sees a cloud chair.
    where_val = validate_where(to, where)
    if where_val == "cloud" and wt:
        raise ValueError("refuse seat: where='cloud' takes no worktree (a cloud neuron has no local checkout); got " + wt)
    # A worktree bound to ANOTHER thread shadows this root for every CLI call
    # made without --root (a codex chair sat in a worktree carrying another
    # thread's .convoy/id and heard nothing). Refuse.
    if wt:
        foreign = _id_path(Path(wt))
        if foreign.is_file() and Path(wt).resolve() != Path(root).resolve():
            other = foreign.read_text(encoding="utf-8-sig").strip()
            if other and other != cid:
                other_thread = read_thread(Path(wt)) or "?"
                raise ValueError(
                    "refuse seat: worktree " + wt + " is bound to thread " + other_thread + " (" + other +
                    "), not this root's " + (read_thread(root) or "?") + " (" + cid + "); use a worktree without"
                    " its own .convoy, or bind it to this thread")
        # A worktree serves one thread: its root pointer (what every rootless hook in it
        # resolves) already naming another thread's root refuses a chair of this one.
        from .inbox import POINTER_RELS
        for rel in POINTER_RELS:
            pointer = Path(wt) / rel
            try:
                named = pointer.read_text(encoding="utf-8-sig").strip() if pointer.is_file() else ""
            except OSError:
                named = ""
            if not named:
                continue
            other = read_id(Path(named)) if Path(named).is_dir() else None
            if other and other != cid:
                raise ValueError(
                    "refuse seat: worktree " + wt + " serves thread " + (read_thread(Path(named)) or "?") +
                    " (" + other + ") through its root pointer; a worktree serves one thread, so use"
                    " another worktree for this thread")
        if session_id != CONDUCTOR and to != CONDUCTOR:
            holder = chair_holding_worktree(root, wt, except_session=session_id)
            if holder is not None:
                raise ValueError(
                    "refuse seat: worktree " + wt + " is already held by chair " +
                    str(holder.get("session_id")) + "; cannot also seat " + str(session_id) +
                    " on it (C8: one worktree, one chair; hook drain is by worktree)")
    thread = read_thread(root) or ""
    resume_val = resume.strip() if isinstance(resume, str) and resume.strip() else None
    rkey = make_resume_key(cid, thread, to, wt)
    title_val = title.strip() if isinstance(title, str) and title.strip() else None
    agent_val = agent.strip() if isinstance(agent, str) and agent.strip() else None
    # Effort is the seat's declared level, real-or-null (chip front matter),
    # validated against THIS harness's keys (harness_effort.json). Convoy
    # sets the vendor flag — exactly when
    # the contract carries cli_flag + evidence; effort_applied records which.
    effort_val = validate_effort(to, effort)
    # Model likewise: refused only against a NON-null catalog (harness_effort.json
    # models); null there means no local --help lists one, and null accepts.
    model_val = validate_model(to, model)
    row: dict[str, Any] = {
        "convoy_id": cid,
        "to": to,
        "session_id": session_id,
        "where": where_val,
        "worktree": wt,
        "model": model_val,
        "effort": effort_val,
        "effort_applied": effort_applied(to, effort_val, model_val),
        "resume": resume_val,
        # Token-to-harness binding: resume_for records
        # the harness this token is claimed for; resume_target refuses on
        # mismatch, so a stale token can never ride another harness's argv.
        "resume_for": to if resume_val else None,
        "title": title_val,
        "agent": agent_val,
        "resume_key": rkey,
    }
    path = _seats_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_line(path, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
    index_record(root, cid, thread or None)
    register(
        root,
        session_id,
        to,
        extra={
            "convoy_id": cid,
            "where": where_val,
            "worktree": wt,
            "model": model_val,
            "to": to,
            "resume": resume_val,
            "title": title_val,
            "agent": agent_val,
            "resume_key": rkey,
        },
    )
    return row

def list_seats(root: Path, convoy_id: str | None = None, require_session: bool = True) -> list[dict[str, Any]]:
    path = _seats_path(root)
    if not path.is_file():
        return []
    found: dict[str, dict[str, Any]] = {}
    blanks: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if convoy_id is not None and row.get("convoy_id") != convoy_id:
                continue
            sid = row.get("session_id")
            if isinstance(sid, str) and sid:
                found[sid] = row
            else:
                blanks.append(row)
    if require_session:
        return list(found.values())
    return list(found.values()) + blanks


def _resolved_worktree(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except OSError:
        return None


def chair_holding_worktree(
    root: Path,
    worktree: str | Path | None,
    *,
    except_session: str | None = None,
) -> dict[str, Any] | None:
    """Latest other chair whose worktree resolves to the same path, or None."""
    want = _resolved_worktree(worktree)
    if not want:
        return None
    skip = str(except_session or "").strip()
    holder = None
    for row in list_seats(root, require_session=True):
        sid = str(row.get("session_id") or "").strip()
        to = str(row.get("to") or "").strip()
        if not sid or sid == skip:
            continue
        if sid == CONDUCTOR or to == CONDUCTOR:
            continue
        have = _resolved_worktree(row.get("worktree"))
        if have and have == want:
            holder = row
    return holder


def set_seat_agent(root: Path, session_id: str, agent: str) -> dict[str, Any] | None:
    """Persist agent on an existing seat row. Append-only; last row wins.

    No-op (None) when the seat is unknown or already carries that agent —
    repeated bring_up must not grow seats.jsonl.
    """
    sid = str(session_id or "").strip()
    val = str(agent or "").strip()
    if not sid or not val:
        return None
    rows = list_seats(root, require_session=True)
    row = None
    for r in rows:
        if r.get("session_id") == sid:
            row = r
    if row is None or row.get("agent") == val:
        return None
    updated = {**row, "agent": val}
    path = _seats_path(root)
    append_line(path, (json.dumps(updated, separators=(",", ":")) + "\n").encode("utf-8"))
    return updated


def update_seat(root: Path, session_id: str, **changes: Any) -> dict[str, Any]:
    """Field-preserving seat update ({**row, ...changes}, the set_seat_agent
    pattern) — bare seat() writes whole rows last-wins and silently blanks
    unpassed fields. A harness change nulls resume AND
    vendor_session_id unless explicitly re-provided (no swap ever carries a
    vendor session). resume_key is recomputed
    (to/worktree are hashed: it is a resume MAP key, not chair identity)."""
    sid = str(session_id or "").strip()
    row = None
    for r in list_seats(root, require_session=True):
        if r.get("session_id") == sid:
            row = r
    if row is None:
        raise ValueError("unknown seat: " + sid)
    if "worktree" in changes:
        if broad_worktree(changes.get("worktree")):
            raise ValueError("refuse seat: broad worktree cannot identify one neuron: " + str(changes.get("worktree")))
        holder = chair_holding_worktree(root, changes.get("worktree"), except_session=sid)
        if holder is not None:
            raise ValueError(
                "refuse seat: worktree " + str(changes.get("worktree")) +
                " is already held by chair " + str(holder.get("session_id")) +
                "; cannot also move " + sid +
                " onto it (C8: one worktree, one chair; hook drain is by worktree)")
    harness_changed = "to" in changes and changes["to"] != row.get("to")
    updated: dict[str, Any] = {**row, **changes}
    if harness_changed:
        if "resume" not in changes:
            updated["resume"] = None
        if "vendor_session_id" not in changes:
            updated["vendor_session_id"] = None
    if "effort" in changes:
        updated["effort"] = validate_effort(str(updated.get("to") or ""), changes["effort"])
    elif harness_changed:
        # A declaration is per harness: claude's max does not follow the chair
        # onto grok. It is dropped, not refused — a swap is not the place to
        # relitigate an old declaration; pass effort= to set a new one.
        try:
            updated["effort"] = validate_effort(str(updated.get("to") or ""), row.get("effort"))
        except ValueError:
            updated["effort"] = None
    if "model" in changes:
        updated["model"] = validate_model(str(updated.get("to") or ""), changes["model"])
    elif harness_changed:
        # same rule as effort: a model the incoming harness's catalog lacks is
        # dropped, not refused; a null catalog lets it ride
        try:
            updated["model"] = validate_model(str(updated.get("to") or ""), row.get("model"))
        except ValueError:
            updated["model"] = None
    # A model-id harness carries effort inside the model id, so a model change alone can
    # flip whether the effort is applied. Computed after validation, from the stored model.
    if "effort" in changes or "model" in changes or harness_changed:
        updated["effort_applied"] = effort_applied(str(updated.get("to") or ""), updated.get("effort"), updated.get("model"))
    # where is re-validated for the harness it now sits on: a cloud chair
    # cannot swap onto a harness with no evidenced cloud attach (refused, not
    # dropped — there is no local fallback for a chair that has no worktree).
    # A row from before the axis has no field and validates as local.
    updated["where"] = validate_where(str(updated.get("to") or ""), changes.get("where", row.get("where")))
    if updated["where"] == "cloud" and updated.get("worktree"):
        raise ValueError("refuse seat: where='cloud' takes no worktree; got " + str(updated.get("worktree")))
    if updated.get("resume"):
        if "resume" in changes and changes["resume"]:
            updated["resume_for"] = updated.get("to")
    else:
        updated["resume_for"] = None
    cid = row.get("convoy_id") or ensure_id(root)
    thread = read_thread(root) or ""
    updated["resume_key"] = make_resume_key(cid, thread, str(updated.get("to") or ""), updated.get("worktree"))
    path = _seats_path(root)
    append_line(path, (json.dumps(updated, separators=(",", ":")) + "\n").encode("utf-8"))
    register(
        root,
        sid,
        str(updated.get("to") or ""),
        extra={"convoy_id": cid, "where": updated.get("where"), "worktree": updated.get("worktree"), "model": updated.get("model"),
               "to": updated.get("to"), "resume": updated.get("resume"), "title": updated.get("title"),
               "agent": updated.get("agent"), "resume_key": updated.get("resume_key")},
    )
    return updated


def observe_resume(root: Path, session_id: str, vendor_id: Any, *, to: str | None = None,
                   replace: bool = False) -> dict[str, Any] | None:
    """Stamp the vendor session id the harness itself just reported, onto the
    seat that has none. Returns the updated row, or None when nothing changed.

    Null until observed. Convoy has held this id in its hand at every Stop
    since the beginning and dropped it on purpose - the rule was written for
    the FEED and is right for the feed (`end.py` hashes it and never writes
    it), but nobody wrote the seat-side counterpart, so every seat row
    carried resume null and every relaunch booted a first run.

    Two refusals make this safe. An existing id is never overwritten: a second
    hook from the same life must not churn the row, and a later life's id
    arrives through a launch, not through here. And the source is always the
    harness's own payload for THIS chair, matched by cwd - never the newest
    file in a log directory, which is often one of Convoy's own `/usage`
    probe stubs.

    replace=True is the one exception, and end.py passes it only for a Stop
    from a top-level codex body (never a nested `codex exec`) in the chair's
    exact worktree: a different id there is a Codex restarted by hand, and
    keeping the dead id would `codex queue` every later send into it. Even
    then the id is kept while a pane host owns a live body for the chair (the
    host owns that chair's life), and within REPLACE_COOLDOWN_S of the last
    replace (two bodies in one worktree would flap the chair on every turn;
    one `resume-flap` row says so). A replace writes a `resume-changed` row
    with hashes of both ids; the feed never carries a vendor id. The
    incarnation is the pane host's and is never touched here.
    """
    sid = str(session_id or "").strip()
    value = vendor_id.strip() if isinstance(vendor_id, str) else ""
    if not sid or not value:
        return None
    row = None
    for r in list_seats(root, require_session=True):
        if r.get("session_id") == sid:
            row = r
    if row is None:
        return None
    current = str(row.get("resume") or "").strip()
    if current == value or (current and not replace):
        return None
    harness = str(row.get("to") or "").strip()
    if not harness:
        return None
    if to is not None and str(to).strip() and str(to).strip() != harness:
        # The payload came from a different harness than the chair sits on.
        # A token bound to the wrong harness is exactly what resume_for
        # exists to refuse; do not create one.
        return None
    # update_seat derives resume_for from the row's own harness, which is the
    # binding resume_target checks.
    if not current:
        return update_seat(root, sid, resume=value)
    from .pane_host import host_alive
    if row.get("harness_pid") is not None and str(row.get("process_state") or "") != "exited" \
            and host_alive(row.get("harness_pid"), row.get("harness_started"), launched_at=row.get("launched_at")):
        return None  # the pane host's live body is the chair; a different id beside it is a second body
    rows = [r for r in feed_since(root, "1970-01-01T00:00:00.000000Z")
            if r.get("instance_id") == sid and r.get("kind") in ("resume-changed", "resume-flap")]
    changed = [r for r in rows if r.get("kind") == "resume-changed"]
    if changed and _seconds_since(changed[-1].get("ts")) < REPLACE_COOLDOWN_S:
        if not any(r.get("kind") == "resume-flap" and str(r.get("ts") or "") >= str(changed[-1].get("ts") or "")
                   for r in rows):
            hook(root, "resume-flap", "chair " + sid + ": two codex bodies in one worktree? its resume changed "
                 "under " + str(REPLACE_COOLDOWN_S // 60) + " minutes ago; keeping the recorded id",
                 instance_id=sid, author=None, extra={"chair": sid, "harness": harness})
        return None
    updated = update_seat(root, sid, resume=value)

    def digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    hook(root, "resume-changed", "chair " + sid + ": a new " + harness + " session took its worktree",
         instance_id=sid, author=None,
         extra={"chair": sid, "harness": harness, "old_sha256": digest(current), "new_sha256": digest(value)})
    return updated


REPLACE_COOLDOWN_S = 600


def _seconds_since(ts: Any) -> float:
    """Seconds since an ISO feed timestamp; infinity when it does not parse."""
    from datetime import datetime, timezone
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds()


def lookup_resume(root: Path, thread: str, to: str, worktree: str | None = None) -> str | None:
    """Return stored vendor resume id for thread+to(+worktree when provided)."""
    cid = read_id(root)
    if not cid:
        return None
    key = make_resume_key(cid, thread, to, worktree)
    seats = list_seats(root, convoy_id=cid)
    if worktree is not None:
        for row in seats:
            if row.get("resume_key") == key and row.get("to") == to:
                r = row.get("resume") or row.get("vendor_session_id")
                if isinstance(r, str) and r:
                    return r
        return None
    for row in seats:
        if row.get("resume_key") == key and row.get("to") == to:
            r = row.get("resume") or row.get("vendor_session_id")
            if isinstance(r, str) and r:
                return r
    # Legacy fallback when seats are keyed per-worktree.
    for row in reversed(seats):
        if row.get("to") == to:
            r = row.get("resume") or row.get("vendor_session_id")
            if isinstance(r, str) and r:
                return r
    return None


def _seats_with_usage(seats: list[dict[str, Any]], probe_fn=None) -> list[dict[str, Any]]:
    fn = probe_fn or probe
    cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for s in seats:
        row = dict(s)
        to = row.get("to")
        if not isinstance(to, str) or not to:
            out.append(row)
            continue
        if to not in cache:
            cache[to] = fn(to)
        row.update(surface(to, cache[to]))
        out.append(row)
    return out

def _last_attach_ts(root: Path, session_id: str | None = None) -> str | None:
    path = Path(root) / ".convoy" / "feed.jsonl"
    if not path.is_file():
        return None
    last = None
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "attach" and row.get("ts") and (session_id is None or row.get("from") == session_id):
                last = row["ts"]
    return last

def attach(root: Path, convoy_id: str | None = None, probe_fn=None, *, session_id: str | None = None) -> dict[str, Any]:
    disk = read_id(root)
    if convoy_id is not None:
        if disk != convoy_id:
            return {"ok": False, "error": "convoy_id mismatch", "convoy_id": disk, "seats": []}
        cid = convoy_id
    else:
        if disk is None:
            return {"ok": False, "error": "no convoy_id"}
        cid = disk
    thread = read_thread(root)
    since = _last_attach_ts(root, session_id=session_id)
    event = hook(root, kind="attach", summary="attach " + cid, author=session_id,
                 extra={"convoy_id": cid, "thread": thread})
    feed = feed_since(root, since or "1970-01-01T00:00:00.000000Z") if since is not None or session_id else []
    seats = _seats_with_usage(list_seats(root, convoy_id=cid), probe_fn=probe_fn)
    return {
        "ok": True,
        "convoy_id": cid,
        "schema_version": SCHEMA_VERSION,
        "seats": seats,
        "pointers": pack(root),
        "thread": thread,
        "conductor": lead_conductor(root),
        "lead": read_lead(root),
        "ts": event["ts"],
        "since": since,
        "feed": feed,
    }
