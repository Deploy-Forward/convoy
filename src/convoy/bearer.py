"""The conductor bearer: identity on the wire (Marco 2026-09-12, step 3 of the
grok-bot rebase, amendment move 2).

Until this landed the only way a public caller wrote to a thread was a global
process flag, CONVOY_MCP_WRITE_TOOLS=1, which exposed every write tool to
anyone who could reach the origin and left a stamp indistinguishable from a
forged one. Now:

  convoy conductor mint      prints a bearer ONCE (cvb_...); only its sha256
                             lands in <CONVOY_HOME>/conductors.jsonl
  Authorization: Bearer ...  on the MCP request opens the write tools for
                             that call, and `from` on conductor rows comes
                             from the bearer's record, never from an argument
  convoy conductor revoke    appends a revocation; the bearer is anonymous again

Nothing here prints, logs, or stores the bearer. The hash is compared in
constant time. One conductor id today (grok-bot); the tenant record that maps
a bearer to threads is move 4, not this file.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .convoy import CONDUCTOR

PREFIX = "cvb_"
FILE = "conductors.jsonl"


def conductors_path() -> Path:
    home = Path(os.environ.get("CONVOY_HOME") or (Path.home() / ".convoy"))
    return home / FILE


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha(bearer: str) -> str:
    return hashlib.sha256(bearer.encode("utf-8")).hexdigest()


def _rows() -> list[dict[str, Any]]:
    p = conductors_path()
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(row: dict[str, Any]) -> None:
    p = conductors_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _state() -> dict[str, dict[str, Any]]:
    """id -> record with `revoked` folded in. Mint rows carry sha256; revoke rows only an id."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in _rows():
        rid = str(row.get("id") or "")
        if not rid:
            continue
        if row.get("revoked_at"):
            if rid in by_id:
                by_id[rid]["revoked"] = True
                by_id[rid]["revoked_at"] = row["revoked_at"]
            continue
        if row.get("sha256"):
            by_id[rid] = {**row, "revoked": False}
    return by_id


def mint(conductor: str = CONDUCTOR, label: str | None = None) -> dict[str, Any]:
    """Mint one bearer. The card carries it exactly once; the file never does."""
    bearer = PREFIX + secrets.token_urlsafe(32)
    digest = _sha(bearer)
    rid = digest[:12]
    row = {"id": rid, "conductor": conductor, "label": label or None, "sha256": digest, "minted_at": _now()}
    try:
        _append(row)
    except OSError as e:
        return {"ok": False, "error": type(e).__name__ + ": " + str(e)}
    return {"ok": True, "id": rid, "conductor": conductor, "label": row["label"], "bearer": bearer,
            "path": str(conductors_path()), "minted_at": row["minted_at"],
            "next": ("send `Authorization: Bearer <this>` on every MCP request; it is shown once and never stored; "
                     "`convoy conductor revoke " + rid + "` closes it")}


def check(bearer: Any) -> dict[str, Any] | None:
    """{id, conductor, label} for a live bearer, else None. Constant-time on the hash."""
    if not isinstance(bearer, str) or not bearer.startswith(PREFIX):
        return None
    digest = _sha(bearer)
    for rid, rec in _state().items():
        if rec.get("revoked"):
            continue
        if hmac.compare_digest(str(rec.get("sha256") or ""), digest):
            return {"id": rid, "conductor": str(rec.get("conductor") or CONDUCTOR), "label": rec.get("label")}
    return None


def revoke(rid: str) -> dict[str, Any]:
    st = _state()
    rec = st.get(str(rid or ""))
    if rec is None:
        return {"ok": False, "id": rid, "error": "no bearer with that id"}
    if rec.get("revoked"):
        return {"ok": True, "id": rid, "revoked": True, "already": True}
    try:
        _append({"id": rid, "revoked_at": _now()})
    except OSError as e:
        return {"ok": False, "id": rid, "error": type(e).__name__ + ": " + str(e)}
    return {"ok": True, "id": rid, "revoked": True}


def list_conductors() -> list[dict[str, Any]]:
    """Every minted bearer without its hash: id, conductor, label, minted_at, revoked."""
    return [{"id": rid, "conductor": rec.get("conductor"), "label": rec.get("label"), "minted_at": rec.get("minted_at"),
             "revoked": bool(rec.get("revoked")), "revoked_at": rec.get("revoked_at")}
            for rid, rec in _state().items()]


def live_count() -> int:
    return sum(1 for rec in _state().values() if not rec.get("revoked"))


def parse_authorization(header: Any) -> str | None:
    """`Bearer <token>` -> token, else None. Any other scheme is not ours."""
    if not isinstance(header, str):
        return None
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
