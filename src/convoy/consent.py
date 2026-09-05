"""Two-turn, scoped, one-time consent receipts for risky Convoy actions."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ACTIONS = frozenset({"trust-worktree", "close-chair", "nudge-pane"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _path(root: Path) -> Path:
    return Path(root) / ".convoy" / "consents.jsonl"


def _scope(
    *,
    session_id: str | None,
    to: str | None,
    worktree: str | None,
    keys: str | None = None,
    pane: str | None = None,
) -> dict[str, Any]:
    wt = None
    if isinstance(worktree, str) and worktree.strip():
        wt = str(Path(worktree).resolve())
    out: dict[str, Any] = {
        "session_id": str(session_id or "").strip() or None,
        "to": str(to or "").strip().lower() or None,
        "worktree": wt,
    }
    if keys is not None:
        out["keys"] = str(keys)
    if pane is not None:
        out["pane"] = str(pane)
    return out


def _append(root: Path, row: dict[str, Any]) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _latest(root: Path) -> dict[str, dict[str, Any]]:
    path = _path(root)
    found: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return found
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            request_id = row.get("request_id") if isinstance(row, dict) else None
            if isinstance(request_id, str) and request_id:
                found[request_id] = row
    return found


def _prompt(action: str, scope: dict[str, Any]) -> str:
    if action == "trust-worktree":
        return (
            "Trust worktree " + str(scope.get("worktree")) + " for " +
            str(scope.get("to") or "the harness") + "? Trust permits repo-local "
            "configuration, hooks, MCP, and LSP code to run with your privileges."
        )
    if action == "nudge-pane":
        return (
            "Nudge Convoy chair " + str(scope.get("session_id"))
            + " (" + str(scope.get("to") or "harness") + ") in pane "
            + str(scope.get("pane") or "unidentified")
            + " with keys " + repr(scope.get("keys"))
            + "? A keystroke into the wrong pane is worse than idle. "
            "Grant only if this names the pane you can see."
        )
    return (
        "Close Convoy chair " + str(scope.get("session_id")) + "? This terminates "
        "its managed harness process and asks its pane host to exit; unsaved TUI "
        "input may be lost."
    )


def request_consent(
    root: Path,
    action: str,
    *,
    session_id: str | None = None,
    to: str | None = None,
    worktree: str | None = None,
    keys: str | None = None,
    pane: str | None = None,
    ttl_minutes: int = 10,
) -> dict[str, Any]:
    """Create a request only. Granting must happen in a later user-approved turn."""
    verb = str(action or "").strip().lower()
    if verb not in _ACTIONS:
        raise ValueError("unsupported consent action: " + verb)
    scope = _scope(session_id=session_id, to=to, worktree=worktree, keys=keys, pane=pane)
    if verb == "trust-worktree" and (not scope["to"] or not scope["worktree"]):
        raise ValueError("trust-worktree consent requires harness and worktree")
    if verb == "close-chair" and not scope["session_id"]:
        raise ValueError("close-chair consent requires seat")
    if verb == "nudge-pane" and (not scope["session_id"] or not scope.get("keys") or not scope.get("pane")):
        raise ValueError("nudge-pane consent requires seat, pane, and keys")
    created = _now()
    row = {
        "request_id": "cns_" + uuid.uuid4().hex,
        "action": verb,
        "scope": scope,
        "status": "requested",
        "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(minutes=max(1, int(ttl_minutes)))),
    }
    _append(root, row)
    return {
        "ok": False,
        "state": "awaiting-user-consent",
        "consent_request": {
            "request_id": row["request_id"],
            "action": verb,
            "scope": scope,
            "prompt": _prompt(verb, scope),
            "expires_at": row["expires_at"],
            "next": "Ask the user verbatim; only after explicit approval run `convoy consent --grant <request_id>`."
        },
    }


def _not_expired(row: dict[str, Any]) -> None:
    raw = str(row.get("expires_at") or "")
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid consent expiry") from exc
    if _now() >= expires:
        raise ValueError("consent request expired")


def grant_consent(root: Path, request_id: str) -> dict[str, Any]:
    """Grant a prior request. Call only after the user explicitly approves it."""
    rid = str(request_id or "").strip()
    row = _latest(root).get(rid)
    if row is None:
        raise ValueError("unknown consent request: " + rid)
    if row.get("status") != "requested":
        raise ValueError("consent request is not pending")
    _not_expired(row)
    token = secrets.token_urlsafe(24)
    granted = {
        **row,
        "status": "granted",
        "granted_at": _iso(_now()),
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
    }
    _append(root, granted)
    return {
        "ok": True,
        "state": "consent-granted",
        "request_id": rid,
        "action": row.get("action"),
        "consent": token,
        "expires_at": row.get("expires_at"),
        "next": "Pass this one-time consent only to the exact pending Convoy command.",
    }


def consume_consent(
    root: Path,
    token: str,
    action: str,
    *,
    session_id: str | None = None,
    to: str | None = None,
    worktree: str | None = None,
    keys: str | None = None,
    pane: str | None = None,
) -> dict[str, Any]:
    """Validate exact action/scope and atomically consume a grant once."""
    raw_token = str(token or "").strip()
    if not raw_token:
        raise ValueError("missing consent")
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    row = None
    for candidate in _latest(root).values():
        if candidate.get("token_hash") == digest:
            row = candidate
            break
    if row is None:
        raise ValueError("unknown consent")
    if row.get("status") == "consumed":
        raise ValueError("consent already consumed")
    if row.get("status") != "granted":
        raise ValueError("consent is not granted")
    _not_expired(row)
    wanted_scope = _scope(session_id=session_id, to=to, worktree=worktree, keys=keys, pane=pane)
    if row.get("action") != action or row.get("scope") != wanted_scope:
        raise ValueError("consent scope mismatch")

    claim = Path(root) / ".convoy" / "consent-claims" / (digest + ".claim")
    claim.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("consent already consumed") from exc
    os.close(descriptor)
    consumed = {**row, "status": "consumed", "consumed_at": _iso(_now())}
    _append(root, consumed)
    return consumed
