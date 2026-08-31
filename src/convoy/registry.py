"""Instance registry. No printed session_id without a row."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

def registry_path(root: Path) -> Path:
    p = Path(root) / ".convoy" / "registry.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def register(root: Path, session_id: str, to: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if not session_id:
        raise ValueError("refuse to register empty session_id")
    row = {"session_id": session_id, "to": to}
    if extra:
        row.update(extra)
    path = registry_path(root)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + chr(10))
    return row

def lookup(root: Path, session_id: str) -> dict[str, Any] | None:
    path = registry_path(root)
    if not path.exists() or not session_id:
        return None
    found = None
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("session_id") == session_id:
                found = row
    return found


def lookup_any(root: Path, token: str, to: str | None = None, worktree: str | None = None) -> dict[str, Any] | None:
    """Lookup by convoy session_id or stored vendor resume id."""
    path = registry_path(root)
    if not path.exists() or not token:
        return None
    wanted_to = str(to).strip().lower() if isinstance(to, str) and to.strip() else None
    wanted_wt = str(worktree).strip() if isinstance(worktree, str) and worktree.strip() else None
    found = None
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            candidates = (
                row.get("session_id"),
                row.get("resume"),
                row.get("vendor_session_id"),
            )
            if token not in candidates:
                continue
            row_to = str(row.get("to") or "").strip().lower()
            row_wt = str(row.get("worktree") or "").strip()
            if wanted_to is not None and row_to != wanted_to:
                continue
            if wanted_wt is not None and row_wt != wanted_wt:
                continue
            found = row
    return found

def parse_session_id(stdout: str) -> str | None:
    """JSON card first. Else ola-brain instance_id: reply. Never a UUID regex guess."""
    text = (stdout or "").strip()
    if not text:
        return None
    from_json = _from_json(text)
    if from_json:
        return from_json
    return _from_ola_prefix(text)

def _from_json(text: str) -> str | None:
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                payload = None
    if not isinstance(payload, dict):
        return None
    sid = payload.get("session_id") or payload.get("instance_id")
    if isinstance(sid, str) and sid:
        return sid
    return None

def _from_ola_prefix(text: str) -> str | None:
    first = text.splitlines()[0].strip()
    if ": " not in first:
        return None
    prefix, _rest = first.split(": ", 1)
    if " " in prefix or "-session-" not in prefix:
        return None
    return prefix

def parse_agents_jsonl(root: Path, to: str, label: str | None = None) -> str | None:
    path = Path(root) / ".ola" / "agent-chat" / "agents.jsonl"
    if not path.is_file():
        return None
    want = None
    if label:
        want = to + "-session-" + label.replace("-", "")
    found = None
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = row.get("instance_id") or row.get("session_id")
            if not isinstance(iid, str) or not iid:
                continue
            if want and iid == want:
                found = iid
            elif not want and "-session-" in iid and iid.startswith(to + "-"):
                found = iid
    return found


def live_on_branch(root: Path, branch: str | None) -> list[dict[str, Any]]:
    if not branch:
        return []
    path = registry_path(root)
    if not path.exists():
        return []
    found: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("git_branch") == branch:
                found.append(row)
    return found
