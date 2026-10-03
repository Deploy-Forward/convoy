"""Deterministic, lossless local thread picker. No process or vendor launches."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .activity import neuron_activity, neuron_id
from .index import is_temp_root, list_threads
from .layer import parse_since


def _home_relative(raw: str) -> str:
    path = Path(raw)
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def thread_list(*, all_threads: bool = False, since: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = parse_since(since or "14d", now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    threads, skipped = [], []
    rows = sorted(list_threads(), key=lambda r: (str(r.get("updated_at") or ""),
                                                str(r.get("convoy_id") or "")), reverse=True)
    for row in rows:
        root = str(row.get("root") or "")
        block = {"convoy_id": row.get("convoy_id"), "thread": row.get("thread"),
                 "root": _home_relative(root), "updated_at": row.get("updated_at"),
                 "pick": None, "reason": None, "neurons": []}
        reason = ("temp" if root and is_temp_root(root) else
                  row.get("skip_reason") if row.get("present") is None else
                  "root gone" if not row.get("present") else None)
        if reason:
            skipped.append({**block, "reason": reason})
            continue
        try:
            activity = neuron_activity(Path(root), now=now)
        except (OSError, ValueError) as exc:
            skipped.append({**block, "reason": "unreadable: " + type(exc).__name__})
            continue
        neurons = [{"id": neuron_id(row.get("convoy_id"), n.get("session_id")),
                    "harness": n.get("harness"), "model": n.get("model"),
                    "neuron": n.get("session_id"), "active": n.get("active"),
                    "detached": n.get("detached", False), "last_seen": n.get("last_authored"),
                    "inbox": n.get("inbox_pending")} for n in activity["neurons"]]
        neurons.sort(key=lambda n: str(n.get("id") or ""))
        last = max([str(row.get("updated_at") or ""),
                    *[str(n.get("last_seen") or "") for n in neurons]])
        reason = "hidden" if row.get("hidden") else "inactive since " + cutoff if last < cutoff else None
        block.update(neurons=neurons, reason=reason)
        if reason and not all_threads:
            skipped.append(block)
        else:
            block["pick"] = len(threads) + 1
            threads.append(block)
    return {"ok": True, "since": cutoff, "threads": threads, "skipped": skipped}


def format_list(card: dict[str, Any]) -> str:
    def cell(value):
        if value is None:
            return "unknown"
        # Preserve the whole value but escape line breaks and separators so
        # a neuron can never collapse another row or forge a picker header.
        return json.dumps(str(value), ensure_ascii=False)[1:-1].replace("|", "\\u007c")
    lines = []
    for t in card["threads"]:
        lines.append(f"{t['pick']}. {cell(t['convoy_id'])} | {cell(t['thread'])} | {cell(t['root'])} | {cell(t['updated_at'])}")
        lines.append("   convoy attach " + cell(t["convoy_id"]))
        if t.get("reason"):
            lines.append("   included: " + cell(t["reason"]))
        lines.append("   id | harness | model | neuron | active | last seen | inbox")
        for n in t["neurons"]:
            state = "detached" if n["detached"] else "active" if n["active"] else "quiet"
            lines.append("   " + " | ".join(cell(v) for v in
                         (n["id"], n["harness"], n["model"], n["neuron"], state, n["last_seen"], n["inbox"])))
    if not card["threads"]:
        lines.append("No selectable threads.")
    for t in card["skipped"]:
        lines.append("skipped: " + " | ".join(cell(t.get(k)) for k in
                                              ("convoy_id", "thread", "root", "reason")))
    return "\n".join(lines)
