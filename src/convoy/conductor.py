"""The conductor's counterpart to the seat's AGENTS block, and its mail.

Marco 2026-09-11 (grok-bot rebase, step 2): the conductor got no contract and
drifted (handoffs under .ola/, typed into panes, polled the feed). The package
ships conductor.md; Convoy mirrors it under <root>/.convoy/, names its path and
sha wherever the conductor looks, and gives it `replies`: rows addressed to it,
read by cursor or by token, without scanning the whole feed for its mail.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from .layer import _is_conductor_alias, feed_since, parse_since

CONTRACT_PATH = Path(__file__).resolve().parent / "conductor.md"
CONTRACT_RELATIVE = Path(".convoy") / "conductor.md"
REPLIES_WAIT_MAX_S = 600.0
EPOCH = "1970-01-01T00:00:00.000000Z"


def contract_text() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def contract_sha() -> str:
    return hashlib.sha256(contract_text().encode("utf-8")).hexdigest()


def contract_pointer(root: Path | str) -> dict[str, Any]:
    """{path, sha, present}: where the root's copy lives and whether it matches the shipped text."""
    dest = Path(root) / CONTRACT_RELATIVE
    sha = contract_sha()
    present = dest.is_file()
    matches = present and hashlib.sha256(dest.read_bytes()).hexdigest() == sha
    return {"path": str(dest), "sha": sha, "present": present, "current": bool(matches)}


def ensure_contract_copy(root: Path | str) -> dict[str, Any]:
    """Mirror the shipped contract under <root>/.convoy/. Idempotent: an identical
    copy is never rewritten (its mtime does not move); a changed shipped text is."""
    dest = Path(root) / CONTRACT_RELATIVE
    text = contract_text()
    out: dict[str, Any] = {"ok": True, "written": False, "path": str(dest), "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    data = text.encode("utf-8")   # bytes, so the copy's sha equals the shipped sha on every OS
    try:
        if dest.is_file() and dest.read_bytes() == data:
            return out
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        out["written"] = True
    except OSError as e:
        out.update({"ok": False, "error": type(e).__name__ + ": " + str(e)})
    return out


def initialize_instructions() -> str:
    """What MCP initialize carries: the ten rules and the pointer, not the whole file.
    A client may ignore `instructions`; the pointer is also on glance, roster, context."""
    text = contract_text()
    start = text.find("## The ten rules")
    end = text.find("## ", start + 5) if start >= 0 else -1
    rules = text[start:end].strip() if start >= 0 and end > start else text[:1500]
    return (rules + "\n\nFull contract: <root>/.convoy/conductor.md (sha " + contract_sha()[:12] + "). "
            "Read it before your first write. Your mail is the `replies` tool. Writes need your identity: "
            "`Authorization: Bearer <bearer>` on every request, minted once by `convoy conductor mint`.")


def _addressed_to(row: dict[str, Any], conductor: str) -> bool:
    to = row.get("to")
    if not isinstance(to, str) or not to.strip():
        return False
    if _is_conductor_alias(conductor):
        return _is_conductor_alias(to)
    return to.strip().lower() == conductor.strip().lower()


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "token"}


def replies(root: Path | str, conductor: str, *, since: str | None = None, token: str | None = None,
            wait: float = 0.0, poll_s: float = 0.5) -> dict[str, Any]:
    """The conductor's mail, filtered from the feed (the source of truth; no second store).

    since: rows addressed to the conductor with ts > since; `cursor` is the newest ts
    returned, else `since` unchanged. token: rows citing that token in their summary,
    with `delivered` = any row is a note from a chair. wait: hold up to wait seconds
    (capped) and return on the first landing row; `waited_s` says how long it held."""
    r = Path(root)
    since_iso = parse_since(since) if since else EPOCH
    wait = max(0.0, min(float(wait or 0.0), REPLIES_WAIT_MAX_S))
    started = time.monotonic()

    def scan() -> list[dict[str, Any]]:
        rows = []
        for row in feed_since(r, since_iso):
            if not isinstance(row, dict) or row.get("kind") == "malformed":
                continue
            if row.get("kind") == "conductor" or _is_conductor_alias(row.get("from")):
                continue
            if not _addressed_to(row, conductor):
                continue
            if token and token not in str(row.get("summary") or ""):
                continue
            if str(row.get("ts") or "") <= since_iso and since:
                continue
            rows.append(_public_row(row))
        return rows

    rows = scan()
    while not rows and wait > 0 and (time.monotonic() - started) < wait:
        time.sleep(min(poll_s, max(0.0, wait - (time.monotonic() - started))))
        rows = scan()
    cursor = rows[-1]["ts"] if rows else (since_iso if since else EPOCH)
    out: dict[str, Any] = {"ok": True, "conductor": conductor, "rows": rows, "cursor": cursor,
                           "waited_s": round(time.monotonic() - started, 3)}
    if token:
        out["token"] = token
        out["delivered"] = any(x.get("kind") == "note" and x.get("from") for x in rows)
    return out
