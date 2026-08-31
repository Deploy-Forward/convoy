"""Glance cards: conductor identifier + overall harness usage + by-thread seats.

Honesty lock:
- usage_remaining is only number|object|null from real probes.
- no invented dollars, reset dates, or fake per-thread token splits.
- missing model is omitted (never "unknown").
"""
from __future__ import annotations

from datetime import datetime
import json
import math
import shutil
import threading
from pathlib import Path
from typing import Any, Callable

from .convoy import CONDUCTOR, list_seats, read_id, read_thread
from .gitstate import git_state
from .layer import feed_since
from .usage import normalize_usage_remaining, probe, surface

ProbeFn = Callable[[str], dict[str, Any]]
WhichFn = Callable[[str], str | None]

HARNESSES = ("grok", "claude", "codex", "cursor-agent", "agy")
_CONDUCTORS = frozenset({"grok-bot", "grok_bot"})
_EPOCH = "1970-01-01T00:00:00.000000Z"


def _is_conductor(to: Any) -> bool:
    return str(to or "").strip().lower() in _CONDUCTORS


def _badge(present: bool, limited: bool) -> str:
    if not present:
        return "missing"
    if limited:
        return "limited"
    return "Live"


def _probe_view(harness: str, probe_fn: ProbeFn) -> dict[str, Any]:
    probed = probe_fn(harness)
    compact = surface(harness, probed)
    usage_remaining = normalize_usage_remaining(compact.get("usage_remaining"))
    row: dict[str, Any] = {
        "limited": bool(compact.get("limited")),
        "usage_remaining": usage_remaining,
    }
    session_pct = compact.get("session_pct")
    week_pct = compact.get("week_pct")
    if isinstance(session_pct, int):
        row["session_pct"] = session_pct
    if isinstance(week_pct, int):
        row["week_pct"] = week_pct
    return row


def _normalize_week_pct(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    return None


def _normalize_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    return None


def _normalize_iso_ts(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parse_target = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(parse_target)
    except ValueError:
        return None
    return text


def _conductor_view(probe_fn: ProbeFn) -> dict[str, Any]:
    probed = probe_fn(CONDUCTOR)
    if not isinstance(probed, dict):
        probed = {}
    return {
        "to": CONDUCTOR,
        "badge": "Live",
        "week_pct": _normalize_week_pct(probed.get("week_pct")),
        "usage_remaining": normalize_usage_remaining(probed.get("usage_remaining")),
        "resets_at": _normalize_iso_ts(probed.get("resets_at")),
        "on_demand_spent": _normalize_number(probed.get("on_demand_spent")),
        "on_demand_limit": _normalize_number(probed.get("on_demand_limit")),
    }


def build_overall(root: Path, probe_fn: ProbeFn | None = None, which_fn: WhichFn | None = None) -> dict[str, Any]:
    del root
    fn = probe_fn or probe
    wf = which_fn or shutil.which
    rows: dict[str, Any] = {}
    for harness in HARNESSES:
        present = wf(harness) is not None
        probe_row = {"limited": False, "usage_remaining": None}
        if present:
            probe_row = _probe_view(harness, fn)
        row: dict[str, Any] = {
            "harness": harness,
            "present": present,
            "badge": _badge(present, bool(probe_row.get("limited"))),
            "usage_remaining": normalize_usage_remaining(probe_row.get("usage_remaining")),
        }
        if isinstance(probe_row.get("session_pct"), int):
            row["session_pct"] = probe_row["session_pct"]
        if isinstance(probe_row.get("week_pct"), int):
            row["week_pct"] = probe_row["week_pct"]
        # UI should only draw a progress bar when this field is present.
        if isinstance(probe_row.get("session_pct"), int):
            row["progress_pct"] = probe_row["session_pct"]
        elif isinstance(probe_row.get("week_pct"), int):
            row["progress_pct"] = probe_row["week_pct"]
        rows[harness] = row
    return {"ok": True, "overall": rows}


def _synapse_index(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in feed_since(root, _EPOCH):
        if row.get("kind") != "synapse":
            continue
        sid = row.get("instance_id")
        if not isinstance(sid, str) or not sid:
            continue
        out[sid] = {
            "ts": row.get("ts"),
            "summary": row.get("summary"),
            "to": row.get("to"),
        }
    return out


def _seat_branch_pr(worktree: Any) -> tuple[Any, Any]:
    if not isinstance(worktree, str) or not worktree.strip():
        return None, None
    state = git_state(worktree)
    return state.get("git_branch"), state.get("pr_number")


def build_by_thread(
    root: Path,
    *,
    thread: str | None = None,
    convoy_id: str | None = None,
    probe_fn: ProbeFn | None = None,
    which_fn: WhichFn | None = None,
) -> dict[str, Any]:
    fn = probe_fn or probe
    wf = which_fn or shutil.which
    disk_id = read_id(root)
    bound_thread = read_thread(root)
    wanted_thread = thread.strip() if isinstance(thread, str) and thread.strip() else None
    wanted_cid = convoy_id.strip() if isinstance(convoy_id, str) and convoy_id.strip() else None
    if wanted_thread is not None and bound_thread != wanted_thread:
        return {"ok": False, "error": "thread mismatch", "thread": bound_thread, "convoy_id": disk_id, "seats": []}
    if wanted_cid is None:
        wanted_cid = disk_id
    if wanted_cid is None:
        return {"ok": False, "error": "no convoy_id", "thread": bound_thread, "convoy_id": None, "seats": []}
    seats = list_seats(root, convoy_id=wanted_cid, require_session=False)
    probe_cache: dict[str, dict[str, Any]] = {}
    synapse = _synapse_index(root)
    view_seats: list[dict[str, Any]] = []
    for seat in seats:
        harness = str(seat.get("to") or "").strip().lower()
        if not harness or _is_conductor(harness):
            continue
        present = wf(harness) is not None
        if present and harness not in probe_cache:
            probe_cache[harness] = _probe_view(harness, fn)
        probe_row = probe_cache.get(harness, {"limited": False, "usage_remaining": None})
        worktree = seat.get("worktree")
        branch, pr = _seat_branch_pr(worktree)
        row: dict[str, Any] = {
            "to": harness,
            "session_id": seat.get("session_id"),
            "worktree": worktree,
            "branch": branch,
            "pr": pr,
            "present": present,
            "badge": _badge(present, bool(probe_row.get("limited"))),
            "usage_remaining": normalize_usage_remaining(probe_row.get("usage_remaining")) if present else None,
        }
        model = seat.get("model")
        if isinstance(model, str) and model.strip():
            row["model"] = model
        # Thread rows can show this seat's session meter, but no thread-level week budget.
        if isinstance(probe_row.get("session_pct"), int):
            row["session_pct"] = probe_row["session_pct"]
        sid = seat.get("session_id")
        if isinstance(sid, str) and sid in synapse:
            row["last_synapse"] = synapse[sid]
        view_seats.append(row)
    return {
        "ok": True,
        "convoy_id": wanted_cid,
        "thread": bound_thread if wanted_cid == disk_id else bound_thread if wanted_thread else None,
        "seat_count": len(view_seats),
        "seats": view_seats,
    }


def discover_threads(root: Path) -> list[dict[str, Any]]:
    seats = list_seats(root, require_session=False)
    bound_thread = read_thread(root)
    disk_id = read_id(root)
    grouped: dict[str, dict[str, Any]] = {}
    for row in seats:
        cid = row.get("convoy_id")
        if not isinstance(cid, str) or not cid:
            continue
        group = grouped.setdefault(cid, {"convoy_id": cid, "thread": None, "seat_count": 0, "harnesses": []})
        harness = str(row.get("to") or "").strip().lower()
        if harness and not _is_conductor(harness) and harness not in group["harnesses"]:
            group["harnesses"].append(harness)
        if not _is_conductor(harness):
            group["seat_count"] += 1
    for cid, row in grouped.items():
        if cid == disk_id:
            row["thread"] = bound_thread
        row["harnesses"] = sorted(row["harnesses"])
    return [grouped[cid] for cid in sorted(grouped)]


def build_glance(
    root: Path,
    *,
    thread: str | None = None,
    convoy_id: str | None = None,
    probe_fn: ProbeFn | None = None,
    which_fn: WhichFn | None = None,
) -> dict[str, Any]:
    fn = probe_fn or probe
    wf = which_fn or shutil.which
    conductor = _conductor_view(fn)
    overall = build_overall(root, probe_fn=fn, which_fn=wf)
    if thread is not None or convoy_id is not None:
        by_thread = build_by_thread(
            root,
            thread=thread,
            convoy_id=convoy_id,
            probe_fn=fn,
            which_fn=wf,
        )
        return {"ok": bool(by_thread.get("ok")), "conductor": conductor, "overall": overall["overall"], "by_thread": by_thread}
    return {"ok": True, "conductor": conductor, "overall": overall["overall"], "threads": discover_threads(root)}


def _fmt_remaining(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _tooltip(card: dict[str, Any]) -> str:
    overall = card.get("overall")
    if not isinstance(overall, dict):
        return "Convoy glance"
    bits: list[str] = []
    for harness in HARNESSES:
        row = overall.get(harness)
        if not isinstance(row, dict):
            continue
        badge = row.get("badge")
        pct = row.get("progress_pct")
        if isinstance(pct, int):
            bits.append(f"{harness}:{badge} {pct}%")
        else:
            bits.append(f"{harness}:{badge}")
    return "Convoy glance | " + " | ".join(bits)


def _overall_line(harness: str, row: dict[str, Any]) -> str:
    badge = row.get("badge")
    rem = _fmt_remaining(row.get("usage_remaining"))
    pct = row.get("progress_pct")
    if isinstance(pct, int):
        return f"{harness} [{badge}] {pct}% rem={rem}"
    return f"{harness} [{badge}] rem={rem}"


def _seat_line(seat: dict[str, Any]) -> str:
    to = str(seat.get("to") or "")
    badge = str(seat.get("badge") or "")
    sid = str(seat.get("session_id") or "")
    model = str(seat.get("model") or "") if "model" in seat else ""
    pct = seat.get("session_pct")
    left = f"{to} [{badge}]"
    if model:
        left += " " + model
    if isinstance(pct, int):
        left += f" {pct}%"
    if sid:
        left += f" ({sid})"
    return left


def run_tray(
    root: Path,
    *,
    thread: str | None = None,
    convoy_id: str | None = None,
    refresh_seconds: int = 60,
    probe_fn: ProbeFn | None = None,
    which_fn: WhichFn | None = None,
) -> dict[str, Any]:
    """Best-effort tray/indicator renderer for the glance JSON contract."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as e:  # pragma: no cover - optional dependency path
        return {"ok": False, "error": "tray requires optional pystray + pillow", "detail": type(e).__name__}

    fn = probe_fn or probe
    wf = which_fn or shutil.which
    state: dict[str, Any] = {
        "card": build_glance(root, thread=thread, convoy_id=convoy_id, probe_fn=fn, which_fn=wf)
    }
    stop = threading.Event()

    def on_quit(icon, _item):  # pragma: no cover - GUI callback
        stop.set()
        icon.stop()

    def on_refresh(icon, _item):  # pragma: no cover - GUI callback
        state["card"] = build_glance(root, thread=thread, convoy_id=convoy_id, probe_fn=fn, which_fn=wf)
        icon.title = _tooltip(state["card"])
        icon.menu = _menu(pystray, on_refresh, on_quit, state["card"])
        icon.update_menu()

    icon = pystray.Icon("convoy-glance", _icon(Image, ImageDraw), _tooltip(state["card"]))
    icon.menu = _menu(pystray, on_refresh, on_quit, state["card"])

    if refresh_seconds > 0:
        def loop() -> None:  # pragma: no cover - GUI timing
            while not stop.wait(refresh_seconds):
                state["card"] = build_glance(
                    root,
                    thread=thread,
                    convoy_id=convoy_id,
                    probe_fn=fn,
                    which_fn=wf,
                )
                icon.title = _tooltip(state["card"])
                icon.menu = _menu(pystray, on_refresh, on_quit, state["card"])
                icon.update_menu()
        threading.Thread(target=loop, daemon=True).start()
    try:
        icon.run()
    finally:
        stop.set()
    return {"ok": True}


def _icon(Image, ImageDraw):  # pragma: no cover - GUI helper
    img = Image.new("RGB", (64, 64), color=(20, 20, 20))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((6, 6, 58, 58), radius=14, outline=(150, 150, 150), width=2, fill=(32, 32, 32))
    draw.text((22, 18), "C", fill=(230, 230, 230))
    return img


def _menu(pystray, on_refresh, on_quit, card: dict[str, Any]):  # pragma: no cover - GUI helper
    items: list[Any] = [pystray.MenuItem("Overall", None, enabled=False)]
    overall = card.get("overall")
    if isinstance(overall, dict):
        for harness in HARNESSES:
            row = overall.get(harness)
            if isinstance(row, dict):
                items.append(pystray.MenuItem(_overall_line(harness, row), None, enabled=False))
    by_thread = card.get("by_thread")
    if isinstance(by_thread, dict) and by_thread.get("ok"):
        title = by_thread.get("thread") or by_thread.get("convoy_id") or "thread"
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(f"Thread: {title}", None, enabled=False))
        for seat in by_thread.get("seats") or []:
            if isinstance(seat, dict):
                items.append(pystray.MenuItem(_seat_line(seat), None, enabled=False))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Refresh", on_refresh))
    items.append(pystray.MenuItem("Quit", on_quit))
    return pystray.Menu(*items)
