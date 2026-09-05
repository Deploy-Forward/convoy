"""Convoy widget model: one always-on-top strip over the terminal.

`build_widget_model` is pure (no Tk). It folds rail, panes, seats, recent(),
feed, and inbox into the shape the window draws. No store of its own.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .bringup import is_conductor
from .cmd import convoy_root_command
from .convoy import list_seats, read_github, read_id, read_lead, read_thread
from .crew import _seated_states
from .gitstate import git_remote, git_state
from .inbox import pending
from .index import recent
from .layer import feed_since
from .panes import bodies
from .rail import build_rail
from .usage import probe

ProbeFn = Callable[[str], dict[str, Any]]
EPOCH = "1970-01-01T00:00:00.000000Z"


def _usage_display(surfaced: dict[str, Any]) -> str:
    """Vendor % when present; 'unknown' for null; never invent 0."""
    remaining = surfaced.get("usage_remaining")
    if remaining is None:
        return "unknown"
    pct = surfaced.get("session_pct")
    if isinstance(pct, int):
        return str(pct) + "%"
    if isinstance(remaining, (int, float)) and remaining != 0:
        return str(remaining)
    if remaining == 0:
        # a real vendor zero is a number; still say unknown when the probe
        # gave us nothing else to hang a percent on
        if isinstance(pct, int):
            return "0%"
        return "unknown"
    return "unknown"


def _tune_commands(root: Path, seat: dict[str, Any]) -> dict[str, str]:
    sid = str(seat.get("session_id") or "")
    harness = str(seat.get("to") or "")
    base = convoy_root_command(root)
    seat_cmd = base + " seat --to " + harness + " --session-id " + sid
    model = seat.get("model")
    effort = seat.get("effort")
    wt = seat.get("worktree")
    if isinstance(model, str) and model.strip():
        seat_cmd += " --model " + model.strip()
    if isinstance(effort, str) and effort.strip():
        seat_cmd += " --effort " + effort.strip()
    if isinstance(wt, str) and wt.strip():
        seat_cmd += " --worktree " + wt.strip()
    swap_cmd = (
        base + " swap --seat " + sid + " --to " + harness
        + " --handoff .convoy/handoff/" + sid + "-<ts>.md --as " + sid
    )
    return {"seat": seat_cmd, "swap": swap_cmd}


def _last_row_for(root: Path, session_id: str) -> dict[str, Any] | None:
    last = None
    for row in feed_since(root, EPOCH):
        if row.get("instance_id") == session_id:
            last = {"ts": row.get("ts"), "kind": row.get("kind"), "summary": row.get("summary")}
    return last


def _repo_block(root: Path) -> dict[str, Any]:
    github = read_github(root)
    url = git_remote(root) if github == "yes" else None
    if not (isinstance(url, str) and url.strip()):
        url = None
    return {
        "connected": bool(url),
        "url": url,
        "root": str(root),
        "thread": read_thread(root),
        "github": github,
    }


def _chair_row(
    root: Path,
    seat: dict[str, Any],
    state: dict[str, Any] | None,
    live: bool,
) -> dict[str, Any]:
    sid = str(seat.get("session_id") or "")
    wt = seat.get("worktree")
    branch = None
    if isinstance(wt, str) and wt.strip():
        branch = git_state(wt).get("git_branch")
    inbox = Path(root) / ".convoy" / "inbox"
    if not inbox.is_dir():
        unread = 0
    else:
        try:
            unread = len(pending(root, sid))
        except ValueError:
            unread = 0
    return {
        "session_id": sid,
        "harness": seat.get("to"),
        "model": seat.get("model"),
        "effort": seat.get("effort"),
        "tune": _tune_commands(root, seat),
        "state": (state or {}).get("state") or "pending",
        "live_body": bool(live),
        "worktree": wt,
        "branch": branch,
        "last_row": _last_row_for(root, sid),
        "unread": unread,
        "focus": "focus --seat " + sid,
    }


def _thread_card(
    root: Path,
    *,
    n: int,
    index_row: dict[str, Any] | None,
    probe_fn: ProbeFn | None,
    enumerate_fn: Callable[[], list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    root = Path(root)
    rail = build_rail(root, probe_fn=probe_fn)
    seats = [s for s in list_seats(root) if not is_conductor(s.get("to"))]
    sids = [str(s.get("session_id") or "") for s in seats]
    states = {st["session_id"]: st for st in (_seated_states(root, sids) if sids else [])}
    roster = bodies(root, enumerate_fn=enumerate_fn)
    live: set[str] = set()
    for c in roster.get("chairs") or []:
        if c.get("live") is True and c.get("session_id"):
            live.add(str(c["session_id"]))
    usage_out: dict[str, Any] = {}
    for harness, raw in (rail.get("usage") or {}).items():
        usage_out[harness] = {**raw, "display": _usage_display(raw)}
    chairs = [_chair_row(root, s, states.get(str(s.get("session_id") or "")), str(s.get("session_id") or "") in live)
              for s in seats]
    return {
        "n": n,
        "dot": "·" + str(n),
        "convoy_id": read_id(root),
        "thread": read_thread(root),
        "root": str(root),
        "updated_at": (index_row or {}).get("updated_at"),
        "lead": read_lead(root),
        "repo": _repo_block(root),
        "usage": usage_out,
        "chairs": chairs,
        "last_stamp": rail.get("last_stamp"),
        "seats": rail.get("seats"),
    }


def build_widget_model(
    roots: list[Path | str] | None = None,
    *,
    probe_fn: ProbeFn | None = None,
    enumerate_fn: Callable[[], list[dict[str, Any]]] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Fold shipped reads into the widget shape. No Tk. No store."""
    fn = probe_fn or probe
    index_rows: list[dict[str, Any]] = []
    paths: list[Path] = []
    if roots is None:
        index_rows = recent(limit)
        paths = [Path(str(r["root"])) for r in index_rows]
    else:
        paths = [Path(r) for r in roots]
    threads: list[dict[str, Any]] = []
    for i, path in enumerate(paths, start=1):
        if read_id(path) is None:
            continue
        row = index_rows[i - 1] if i <= len(index_rows) else None
        threads.append(_thread_card(path, n=i, index_row=row, probe_fn=fn, enumerate_fn=enumerate_fn))
    return {"ok": True, "threads": threads}


def run_widget(
    roots: list[Path | str] | None = None,
    *,
    topmost: bool = True,
    refresh: float = 3.0,
    probe_fn: ProbeFn | None = None,
    loop: bool = True,
) -> dict[str, Any]:
    """Open the Tk strip. Tk is optional at import: missing -> card, no crash."""
    try:
        import tkinter as tk
    except Exception as e:  # pragma: no cover - optional on some hosts
        return {"ok": False, "error": "widget requires tkinter", "detail": type(e).__name__}

    from .focus import focus_seat

    interval_ms = max(1, int(float(refresh) * 1000))
    selected = {"n": 1}
    state: dict[str, Any] = {"model": build_widget_model(roots, probe_fn=probe_fn)}

    win = tk.Tk()
    win.title("convoy")
    win.attributes("-topmost", bool(topmost))
    win.resizable(True, True)

    top = tk.Frame(win)
    top.pack(fill="x")
    body = tk.Frame(win)
    body.pack(fill="both", expand=True)
    status = tk.Label(win, text="", anchor="w")
    status.pack(fill="x")

    def _model() -> dict[str, Any]:
        return state["model"]

    def _thread() -> dict[str, Any] | None:
        threads = _model().get("threads") or []
        for t in threads:
            if t.get("n") == selected["n"]:
                return t
        return threads[0] if threads else None

    def _focus(sid: str) -> None:
        t = _thread()
        root = Path(str((t or {}).get("root") or "."))
        card = focus_seat(root, sid)
        status.config(text=("focused" if card.get("focused") else str(card.get("reason") or "focus")))

    def _paint() -> None:
        for child in list(top.winfo_children()) + list(body.winfo_children()):
            child.destroy()
        threads = _model().get("threads") or []
        if not threads:
            tk.Label(top, text="no threads").pack(side="left")
            return
        for t in threads:
            n = t["n"]
            btn = tk.Button(top, text=t.get("dot") or ("·" + str(n)),
                            relief="sunken" if n == selected["n"] else "raised",
                            command=lambda n=n: _select(n))
            btn.pack(side="left")
        t = _thread()
        if t is None:
            return
        repo = t.get("repo") or {}
        connected = "y" if repo.get("connected") else "n"
        tk.Label(body, text="repo connected? " + connected, anchor="w").pack(fill="x")
        if repo.get("connected") and repo.get("url"):
            tk.Label(body, text="  " + str(repo["url"]), anchor="w").pack(fill="x")
        tk.Label(body, text="  " + str(repo.get("root") or "") + "  " + str(repo.get("thread") or ""),
                 anchor="w").pack(fill="x")
        usage = t.get("usage") or {}
        if usage:
            bits = [h + " " + str(u.get("display") or "unknown") for h, u in usage.items()]
            tk.Label(body, text="usage: " + " · ".join(bits), anchor="w").pack(fill="x")
        for c in t.get("chairs") or []:
            live = " ●" if c.get("live_body") else ""
            line = (
                str(c.get("harness") or "") + " | "
                + str(c.get("model") or "null") + " | "
                + str(c.get("effort") or "null")
                + "  [" + str(c.get("state") or "pending") + "]"
                + live
            )
            sid = str(c.get("session_id") or "")
            tk.Button(body, text=line, anchor="w", command=lambda s=sid: _focus(s)).pack(fill="x")
        stamp = t.get("last_stamp")
        if stamp:
            tk.Label(body, text="stamp: " + str(stamp.get("summary") or ""), anchor="w").pack(fill="x")

    def _select(n: int) -> None:
        selected["n"] = n
        _paint()

    def _refresh() -> None:
        state["model"] = build_widget_model(roots, probe_fn=probe_fn)
        _paint()
        if loop:
            win.after(interval_ms, _refresh)

    _paint()
    if loop:
        win.after(interval_ms, _refresh)
        win.mainloop()
        return {"ok": True, "threads": len((_model().get("threads") or []))}
    win.update_idletasks()
    n = len((_model().get("threads") or []))
    win.destroy()
    return {"ok": True, "threads": n, "loop": False}
