"""Convoy widget model: one always-on-top strip over the terminal.

`build_widget_model` is pure (no Tk). It folds rail, panes, seats, recent(),
feed, and inbox into the shape the window draws. No store of its own.
"""
from __future__ import annotations

import gc
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .bringup import is_conductor
from .cmd import convoy_root_command
from .convoy import list_seats, read_github, read_id, read_lead, read_thread
from .crew import _seated_states
from .gitstate import git_remote, git_state
from .harness_contract import effort_contract, model_catalog
from .inbox import _load, pending
from .index import index_path, recent
from .layer import feed_since, utc_now
from .panes import bodies
from .rail import build_rail
from .usage import probe

ProbeFn = Callable[[str], dict[str, Any]]
NowFn = Callable[[], str]
EPOCH = "1970-01-01T00:00:00.000000Z"
IDLE_FLAG = "CONVOY_STALE_IDLE_S"
IDLE_DEFAULT = 300.0
WORDMARK = "convoy.bot"
DEPLOY_FORWARD = "Deploy Forward"


def idle_threshold_s(value: Any = None) -> float:
    """Stale/working threshold in seconds. Flag, not a constant."""
    raw = value if value is not None else os.environ.get(IDLE_FLAG, str(int(IDLE_DEFAULT)))
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return IDLE_DEFAULT
    return n if n >= 0 else IDLE_DEFAULT


def chip_state(*, body: bool, waiting: int, idle_s: float | None, threshold_s: float) -> str:
    """working | idle | stale | gone from the tape + a live body, never a guess."""
    if not body:
        return "gone"
    idle = float("inf") if idle_s is None else float(idle_s)
    if idle <= threshold_s:
        return "working"
    if waiting > 0 and idle > threshold_s:
        return "stale"
    return "idle"


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


def _pct_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value and abs(value) != float("inf"):
        return int(value)
    return None


def _usage_block(harness: str, surfaced: dict[str, Any]) -> dict[str, Any]:
    session = _pct_or_none(surfaced.get("session_pct"))
    week = _pct_or_none(surfaced.get("week_pct"))
    footnote = None
    if str(harness).strip().lower() == "grok":
        raw = surfaced.get("raw")
        if isinstance(raw, str) and raw.strip():
            footnote = raw.strip().splitlines()[0][:160]
        else:
            footnote = "grok reports no meter"
    return {
        **surfaced,
        "display": _usage_display(surfaced),
        "display_session": (str(session) + "%") if session is not None else "unknown",
        "display_week": (str(week) + "%") if week is not None else "unknown",
        "bar_session": session,
        "bar_week": week,
        "footnote": footnote,
    }


def _tune_commands(
    root: Path,
    seat: dict[str, Any],
    *,
    model: Any = None,
    effort: Any = None,
) -> dict[str, str]:
    sid = str(seat.get("session_id") or "")
    harness = str(seat.get("to") or "")
    base = convoy_root_command(root)
    seat_cmd = base + " seat --to " + harness + " --session-id " + sid
    model_v = model if model is not None else seat.get("model")
    effort_v = effort if effort is not None else seat.get("effort")
    wt = seat.get("worktree")
    if isinstance(model_v, str) and model_v.strip():
        seat_cmd += " --model " + model_v.strip()
    if isinstance(effort_v, str) and effort_v.strip():
        seat_cmd += " --effort " + effort_v.strip()
    if isinstance(wt, str) and wt.strip():
        seat_cmd += " --worktree " + wt.strip()
    swap_cmd = (
        base + " swap --seat " + sid + " --to " + harness
        + " --handoff .convoy/handoff/" + sid + "-<ts>.md --as " + sid
    )
    return {"seat": seat_cmd, "swap": swap_cmd}


def _parse_ts(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _idle_s(now: str, *timestamps: Any) -> float | None:
    times = [t for t in (_parse_ts(x) for x in timestamps) if t is not None]
    if not times:
        return None
    now_dt = _parse_ts(now)
    if now_dt is None:
        return None
    return max(0.0, (now_dt - max(times)).total_seconds())


def _tape_index(root: Path) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Newest authored ts and last feed row per chair. Skips malformed lines."""
    authored: dict[str, str] = {}
    last_row: dict[str, dict[str, Any]] = {}
    for row in feed_since(root, EPOCH):
        if not isinstance(row, dict) or row.get("kind") == "malformed":
            continue
        ts = row.get("ts")
        if not isinstance(ts, str) or not ts:
            continue
        for key in ("from", "instance_id"):
            sid = row.get(key)
            if isinstance(sid, str) and sid:
                authored[sid] = ts
        inst = row.get("instance_id")
        if isinstance(inst, str) and inst:
            last_row[inst] = {"ts": ts, "kind": row.get("kind"), "summary": row.get("summary")}
    return authored, last_row


def _last_drained_ts(root: Path, session_id: str) -> str | None:
    last = None
    try:
        rows = _load(root, session_id)
    except ValueError:
        return None
    for row in rows:
        if row.get("status") == "consumed" and isinstance(row.get("ts"), str) and row.get("ts"):
            last = row["ts"]
    return last


def _repo_block(root: Path) -> dict[str, Any]:
    github = read_github(root)
    url = git_remote(root) if github == "yes" else None
    if not (isinstance(url, str) and url.strip()):
        url = None
    convoy_dir = str(Path(root) / ".convoy")
    return {
        "connected": bool(url),
        "chip": "CONNECTED" if url else "LOCAL",
        "url": url,
        "root": str(root),
        "thread": read_thread(root),
        "github": github,
        "local_storage": convoy_dir,
        "index_path": str(index_path()),
        "convoy_id": read_id(root),
    }


def _chair_row(
    root: Path,
    seat: dict[str, Any],
    state: dict[str, Any] | None,
    live: bool,
    *,
    now: str,
    threshold_s: float,
    authored: dict[str, str],
    last_rows: dict[str, dict[str, Any]],
    is_lead: bool,
) -> dict[str, Any]:
    sid = str(seat.get("session_id") or "")
    harness = str(seat.get("to") or "")
    wt = seat.get("worktree")
    branch = None
    if isinstance(wt, str) and wt.strip():
        branch = git_state(wt).get("git_branch")
    try:
        unread = len(pending(root, sid))
    except ValueError:
        unread = 0
    last_authored = authored.get(sid)
    last_drained = _last_drained_ts(root, sid)
    idle = _idle_s(now, last_authored, last_drained)
    body = True if live else None
    chip = chip_state(body=bool(live), waiting=unread, idle_s=idle, threshold_s=threshold_s)
    catalog = model_catalog(harness)
    effort = effort_contract(harness)
    return {
        "session_id": sid,
        "seat_label": "lead" if is_lead else sid,
        "lead": is_lead,
        "harness": seat.get("to"),
        "model": seat.get("model"),
        "effort": seat.get("effort"),
        "models": catalog.get("models"),
        "effort_keys": effort.get("keys"),
        "effort_applied": effort.get("applied"),
        "tune": _tune_commands(root, seat),
        "state": (state or {}).get("state") or "pending",
        "live_body": bool(live),
        "chip": chip,
        "last_authored": last_authored,
        "last_drained": last_drained,
        "waiting": unread,
        "idle_s": None if idle is None else int(idle),
        "body": body,
        "worktree": wt,
        "branch": branch,
        "last_row": last_rows.get(sid),
        "unread": unread,
        "focus": "focus --seat " + sid,
        "nudge_available": chip == "stale",
        "nudge": "nudge --seat " + sid + " --dry-run",
    }


def _thread_card(
    root: Path,
    *,
    n: int,
    index_row: dict[str, Any] | None,
    probe_fn: ProbeFn | None,
    enumerate_fn: Callable[[], list[dict[str, Any]]] | None,
    now: str,
    threshold_s: float,
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
        usage_out[harness] = _usage_block(str(harness), raw)
    authored, last_rows = _tape_index(root)
    lead_val = (read_lead(root) or "").strip().lower()
    lead_assigned = False
    chairs: list[dict[str, Any]] = []
    for s in seats:
        sid = str(s.get("session_id") or "")
        harness = str(s.get("to") or "").strip().lower()
        is_lead = (not lead_assigned) and bool(lead_val) and (sid.lower() == lead_val or harness == lead_val)
        if is_lead:
            lead_assigned = True
        chairs.append(_chair_row(
            root, s, states.get(sid), sid in live,
            now=now, threshold_s=threshold_s, authored=authored,
            last_rows=last_rows, is_lead=is_lead,
        ))
    seated_n = sum(1 for c in chairs if c.get("state") == "connected")
    stale_ring = any(c.get("chip") == "stale" for c in chairs)
    return {
        "n": n,
        "dot": "·" + str(n),
        "stale_ring": stale_ring,
        "convoy_id": read_id(root),
        "thread": read_thread(root),
        "root": str(root),
        "updated_at": (index_row or {}).get("updated_at"),
        "lead": read_lead(root),
        "repo": _repo_block(root),
        "usage": usage_out,
        "chairs": chairs,
        "seated_n": seated_n,
        "idle_s_flag": threshold_s,
        "header": {
            "wordmark": WORDMARK,
            "tag": DEPLOY_FORWARD,
            "plus": convoy_root_command(root) + " start",
        },
        "footer": "every neuron seated in ·" + str(n) + " — model · effort tunable per seat",
        "last_stamp": rail.get("last_stamp"),
        "seats": rail.get("seats"),
    }


def build_widget_model(
    roots: list[Path | str] | None = None,
    *,
    probe_fn: ProbeFn | None = None,
    enumerate_fn: Callable[[], list[dict[str, Any]]] | None = None,
    limit: int = 20,
    now_fn: NowFn | None = None,
    idle_s: Any = None,
) -> dict[str, Any]:
    """Fold shipped reads into the widget shape. No Tk. No store."""
    fn = probe_fn or probe
    now = (now_fn or utc_now)()
    threshold = idle_threshold_s(idle_s)
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
        threads.append(_thread_card(
            path, n=i, index_row=row, probe_fn=fn, enumerate_fn=enumerate_fn,
            now=now, threshold_s=threshold,
        ))
    return {"ok": True, "threads": threads, "now": now, "idle_s_flag": threshold}


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
        from tkinter import font as tkfont
    except Exception as e:  # pragma: no cover - optional on some hosts
        return {"ok": False, "error": "widget requires tkinter", "detail": type(e).__name__}

    import subprocess
    from .focus import focus_seat
    from .nudge import nudge_seat
    from .start import start

    interval_ms = max(1, int(float(refresh) * 1000))
    selected = {"n": 1}
    usage_mode = {"v": "session"}
    pending_cmd = {"text": ""}
    pinned = {"v": bool(topmost)}
    # the nudge the human is confirming: dry card shown first, keys typed only on confirm
    pending_nudge: dict[str, Any] = {}
    state: dict[str, Any] = {"model": build_widget_model(roots, probe_fn=probe_fn)}

    BLUE = "#2f4fd8"
    GREEN = "#2a9a5c"
    GREY = "#6b7280"
    HAIR = "#d8dbe3"
    RED = "#c0392b"
    UNKNOWN = "#9aa3b2"
    BG = "#ffffff"

    try:
        win = tk.Tk()
    except Exception as e:
        return {"ok": False, "error": "widget requires a display", "detail": type(e).__name__}
    win.title("convoy")
    win.configure(bg=BG)
    win.attributes("-topmost", bool(topmost))
    win.resizable(True, True)
    family = "Consolas" if "Consolas" in tkfont.families() else (
        "Menlo" if "Menlo" in tkfont.families() else "TkFixedFont"
    )
    base_font = (family, 10)
    small = (family, 8)
    title_font = (family, 11, "bold")

    header = tk.Frame(win, bg=BG, padx=10, pady=8)
    header.pack(fill="x")
    body = tk.Frame(win, bg=BG, padx=10, pady=4)
    body.pack(fill="both", expand=True)
    confirm = tk.Frame(win, bg=BG, padx=10)
    confirm.pack(fill="x")
    status = tk.Label(win, text="", anchor="w", bg=BG, fg=GREY, font=small)
    status.pack(fill="x", padx=10, pady=(0, 6))

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

    def _plus() -> None:
        t = _thread()
        root = Path(str((t or {}).get("root") or "."))
        card = start(root)
        pending_cmd["text"] = ""
        status.config(text=str(card.get("ask") or card.get("error") or card.get("next") or "start"))

    def _show_cmd(text: str) -> None:
        pending_cmd["text"] = text
        _paint_confirm()
        status.config(text=text)

    def _root() -> Path:
        t = _thread()
        return Path(str((t or {}).get("root") or "."))

    def _nudge(sid: str) -> None:
        """Stage 1: identify only (dry_run). Nothing is typed. The human confirms next."""
        card = nudge_seat(_root(), sid, dry_run=True)
        pending_nudge.clear()
        pending_nudge.update(sid=sid, card=card, consent="", keys="")
        pending_cmd["text"] = ""
        _paint_confirm()
        status.config(text=str(card.get("reason") or card.get("next") or card.get("error") or "nudge"))

    def _nudge_confirm() -> None:
        """Stage 2: the one keystroke, with the consent the human pasted. Never on a timer."""
        sid = str(pending_nudge.get("sid") or "")
        if not sid:
            return
        keys = str(pending_nudge.get("keys") or "").strip() or None
        consent = str(pending_nudge.get("consent") or "").strip() or None
        card = nudge_seat(_root(), sid, keys=keys, consent=consent)
        pending_nudge["card"] = card
        if card.get("request_id"):
            # consent asked, not granted: show the grant command; the human runs it, pastes the token
            status.config(text="grant: " + convoy_root_command(_root()) + " consent --grant " + str(card["request_id"]))
        else:
            status.config(text=str(card.get("delivery") or card.get("reason") or card.get("error") or "nudge"))
            if card.get("delivery") == "nudged":
                pending_nudge.clear()
        _paint_confirm()

    def _nudge_cancel() -> None:
        pending_nudge.clear()
        _paint_confirm()

    def _toggle_pin() -> None:
        pinned["v"] = not pinned["v"]
        win.attributes("-topmost", pinned["v"])
        _paint()

    def _run_cmd() -> None:
        text = pending_cmd.get("text") or ""
        if not text.strip():
            return
        try:
            r = subprocess.run(text, shell=True, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=20)
            out = (r.stdout or r.stderr or "").strip().splitlines()
            status.config(text=(out[-1] if out else ("exit " + str(r.returncode))))
        except (OSError, subprocess.SubprocessError) as e:
            status.config(text=type(e).__name__)
        pending_cmd["text"] = ""
        _paint_confirm()

    def _paint_confirm() -> None:
        for child in list(confirm.winfo_children()):
            child.destroy()
        if pending_nudge.get("sid"):
            card = pending_nudge.get("card") or {}
            head = "nudge " + str(pending_nudge["sid"]) + " · " + str(card.get("adapter") or "no adapter")
            tk.Label(confirm, text=head, anchor="w", bg=BG, fg=RED, font=small).pack(fill="x")
            detail = str(card.get("reason") or card.get("next") or card.get("error") or "")
            if detail:
                tk.Label(confirm, text=detail, anchor="w", bg=BG, fg=GREY, font=small, wraplength=520).pack(fill="x")
            fields = tk.Frame(confirm, bg=BG)
            fields.pack(fill="x")
            keys_var = tk.StringVar(value=str(pending_nudge.get("keys") or ""))
            consent_var = tk.StringVar(value=str(pending_nudge.get("consent") or ""))
            tk.Label(fields, text="keys", bg=BG, fg=GREY, font=small).pack(side="left")
            tk.Entry(fields, textvariable=keys_var, width=18, font=small).pack(side="left", padx=(2, 8))
            tk.Label(fields, text="consent", bg=BG, fg=GREY, font=small).pack(side="left")
            tk.Entry(fields, textvariable=consent_var, width=18, font=small).pack(side="left", padx=(2, 0))
            row = tk.Frame(confirm, bg=BG)
            row.pack(fill="x", pady=(2, 6))
            can_send = bool(card.get("identified")) and card.get("adapter") != "grok-acp-unshipped"

            def _confirm() -> None:
                pending_nudge["keys"] = keys_var.get()
                pending_nudge["consent"] = consent_var.get()
                _nudge_confirm()

            tk.Button(row, text="confirm nudge", command=_confirm, font=small,
                      state="normal" if can_send else "disabled").pack(side="left")
            tk.Button(row, text="cancel", command=_nudge_cancel, font=small).pack(side="left", padx=6)
            return
        text = pending_cmd.get("text") or ""
        if not text:
            return
        tk.Label(confirm, text=text, anchor="w", bg=BG, fg=BLUE, font=small, wraplength=520).pack(fill="x")
        row = tk.Frame(confirm, bg=BG)
        row.pack(fill="x", pady=(2, 6))
        tk.Button(row, text="run", command=_run_cmd, font=small).pack(side="left")
        tk.Button(row, text="cancel", command=lambda: (pending_cmd.update(text=""), _paint_confirm()),
                  font=small).pack(side="left", padx=6)

    def _bar(parent: tk.Widget, pct: int | None, unknown: bool) -> None:
        canvas = tk.Canvas(parent, width=180, height=10, bg=BG, highlightthickness=0)
        canvas.pack(side="left", padx=(8, 8), pady=2)
        canvas.create_rectangle(0, 2, 180, 8, fill="#eceff4", outline="")
        if unknown or pct is None:
            canvas.create_rectangle(0, 2, 180, 8, fill=UNKNOWN, outline="")
        else:
            width = max(0, min(180, int(180 * (max(0, min(100, pct)) / 100.0))))
            canvas.create_rectangle(0, 2, width, 8, fill=BLUE, outline="")

    def _section(parent: tk.Widget, title: str) -> tk.Frame:
        box = tk.Frame(parent, bg=BG, highlightbackground=HAIR, highlightthickness=1)
        box.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(box, bg=BG, padx=10, pady=8)
        inner.pack(fill="x")
        tk.Label(inner, text=title, fg=BLUE, bg=BG, font=small).pack(anchor="w")
        return inner

    def _paint() -> None:
        for child in list(header.winfo_children()) + list(body.winfo_children()):
            child.destroy()
        threads = _model().get("threads") or []
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left")
        mark = tk.Canvas(brand, width=18, height=18, bg=BG, highlightthickness=0)
        mark.pack(side="left", padx=(0, 8))
        mark.create_rectangle(2, 2, 16, 16, outline=BLUE, width=2)
        names = tk.Frame(brand, bg=BG)
        names.pack(side="left")
        tk.Label(names, text=WORDMARK, bg=BG, fg="#111", font=title_font).pack(anchor="w")
        tk.Label(names, text=DEPLOY_FORWARD, bg=BG, fg=BLUE, font=small).pack(anchor="w")
        dots = tk.Frame(header, bg=BG)
        dots.pack(side="right")
        if not threads:
            tk.Label(dots, text="no threads", bg=BG, fg=GREY, font=small).pack(side="left")
            return
        for t in threads:
            n = t["n"]
            selected_dot = n == selected["n"]
            ring = bool(t.get("stale_ring"))
            hold = tk.Frame(dots, bg=BG, padx=2)
            hold.pack(side="left")
            if ring:
                cv = tk.Canvas(hold, width=22, height=22, bg=BG, highlightthickness=0)
                cv.pack()
                cv.create_oval(2, 2, 20, 20, outline=RED, width=2)
                cv.create_text(11, 11, text=str(n), fill=BLUE if selected_dot else GREY, font=small)
                cv.bind("<Button-1>", lambda _e, n=n: _select(n))
            else:
                tk.Button(
                    hold, text=("● " if selected_dot else "· ") + str(n),
                    relief="flat", fg=BLUE if selected_dot else GREY, bg=BG, font=small,
                    command=lambda n=n: _select(n),
                ).pack()
        tk.Button(dots, text="+", relief="solid", fg=GREY, bg=BG, font=small,
                  command=_plus).pack(side="left", padx=(8, 0))
        tk.Button(dots, text="pin" if pinned["v"] else "unpinned", relief="flat",
                  fg=BLUE if pinned["v"] else GREY, bg=BG, font=small,
                  command=_toggle_pin).pack(side="left", padx=(6, 0))

        t = _thread()
        if t is None:
            return
        repo = t.get("repo") or {}
        repo_box = _section(body, "REPO")
        top_r = tk.Frame(repo_box, bg=BG)
        top_r.pack(fill="x")
        chip = str(repo.get("chip") or ("CONNECTED" if repo.get("connected") else "LOCAL"))
        chip_fg = GREEN if chip == "CONNECTED" else GREY
        tk.Label(top_r, text=chip, fg=chip_fg, bg=BG, font=small).pack(side="right")
        if chip == "CONNECTED" and repo.get("url"):
            tk.Label(repo_box, text=str(repo["url"]), anchor="w", bg=BG, font=base_font).pack(fill="x")
        tk.Label(repo_box, text="LOCAL STORAGE  ·  THREAD", fg=BLUE, bg=BG, font=small).pack(anchor="w", pady=(8, 0))
        tk.Label(repo_box, text=str(repo.get("local_storage") or ""), anchor="w", bg=BG, font=base_font).pack(fill="x")
        tk.Label(repo_box, text=str(repo.get("index_path") or ""), anchor="w", bg=BG, fg=GREY, font=small).pack(fill="x")
        ident = "convoy_id " + str(repo.get("convoy_id") or t.get("convoy_id") or "") + " · bound to thread " + str(
            repo.get("thread") or t.get("thread") or ""
        )
        tk.Label(repo_box, text=ident, anchor="w", bg=BG, fg=GREY, font=small).pack(fill="x")

        use_box = _section(body, "USAGE REMAINING")
        toggle = tk.Frame(use_box, bg=BG)
        toggle.pack(anchor="e")
        for mode, label in (("session", "SESSION"), ("week", "WEEK")):
            on = usage_mode["v"] == mode
            tk.Button(
                toggle, text=label, relief="flat",
                bg="#111" if on else "#e5e7eb",
                fg="#fff" if on else "#111",
                font=small,
                command=lambda m=mode: (usage_mode.update(v=m), _paint()),
            ).pack(side="left")
        usage = t.get("usage") or {}
        footnotes: list[str] = []
        mode = usage_mode["v"]
        for harness, u in usage.items():
            row = tk.Frame(use_box, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=str(harness), width=10, anchor="w", bg=BG, font=base_font).pack(side="left")
            pct = u.get("bar_week") if mode == "week" else u.get("bar_session")
            shown = u.get("display_week") if mode == "week" else u.get("display_session")
            unknown = shown == "unknown" or pct is None
            _bar(row, pct if isinstance(pct, int) else None, unknown)
            tk.Label(row, text=str(shown or "unknown"), bg=BG, fg=GREY, font=base_font).pack(side="right")
            if u.get("footnote"):
                footnotes.append(str(u["footnote"]))
        for note in footnotes:
            tk.Label(use_box, text=note, anchor="w", bg=BG, fg=GREY, font=small).pack(fill="x")

        table_wrap = tk.Frame(body, bg=BG, highlightbackground=HAIR, highlightthickness=1)
        table_wrap.pack(fill="x", pady=(0, 8))
        table = tk.Frame(table_wrap, bg=BG, padx=10, pady=8)
        table.pack(fill="x")
        head = tk.Frame(table, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="HARNESSES  ·  NEURONS IN THREAD", fg=BLUE, bg=BG, font=small).pack(side="left")
        tk.Label(head, text=str(t.get("seated_n") or 0) + " SEATED", fg=GREY, bg=BG, font=small).pack(side="right")
        cols = tk.Frame(table, bg=BG)
        cols.pack(fill="x", pady=(6, 2))
        for i, label in enumerate(("SEAT", "HARNESS", "MODEL", "EFFORT", "CHIP")):
            tk.Label(cols, text=label, fg=GREY, bg=BG, font=small, width=12 if i else 14, anchor="w").pack(side="left")
        for c in t.get("chairs") or []:
            row = tk.Frame(table, bg=BG)
            row.pack(fill="x", pady=1)
            if c.get("lead"):
                rule = tk.Frame(row, bg=BLUE, width=3)
                rule.pack(side="left", fill="y", padx=(0, 6))
            else:
                tk.Frame(row, bg=BG, width=9).pack(side="left")
            sid = str(c.get("session_id") or "")
            tk.Button(
                row, text=str(c.get("seat_label") or sid), width=12, anchor="w",
                relief="flat", bg=BG, font=base_font, command=lambda s=sid: _focus(s),
            ).pack(side="left")
            tk.Label(row, text=str(c.get("harness") or ""), width=12, anchor="w", bg=BG, font=base_font).pack(side="left")
            models = c.get("models")
            effort_keys = c.get("effort_keys")
            model_var = tk.StringVar(value=str(c.get("model") or ""))
            effort_var = tk.StringVar(value=str(c.get("effort") or ""))

            def _make_preview(chair, mv, ev):
                def _preview(_v=None):
                    cmd = _tune_commands(
                        Path(str(t.get("root") or ".")),
                        {"session_id": chair.get("session_id"), "to": chair.get("harness"),
                         "worktree": chair.get("worktree"), "model": chair.get("model"),
                         "effort": chair.get("effort")},
                        model=mv.get() or None,
                        effort=ev.get() or None,
                    )["seat"]
                    _show_cmd(cmd)
                return _preview

            preview = _make_preview(c, model_var, effort_var)
            if isinstance(models, list) and models:
                tk.OptionMenu(row, model_var, *models, command=preview).pack(side="left")
            else:
                ent = tk.Entry(row, textvariable=model_var, width=12, font=small)
                ent.pack(side="left")
                ent.bind("<Return>", preview)
            if isinstance(effort_keys, list) and effort_keys:
                om = tk.OptionMenu(row, effort_var, *effort_keys, command=preview)
                om.pack(side="left")
                if c.get("effort_applied") is False:
                    om.bind("<Enter>", lambda _e, h=c.get("harness"): status.config(
                        text=str(h) + " effort is declared, not applied"))
            else:
                ent_e = tk.Entry(row, textvariable=effort_var, width=10, font=small)
                ent_e.pack(side="left")
                ent_e.bind("<Return>", preview)
            tk.Label(row, text=str(c.get("chip") or ""), width=10, anchor="w", bg=BG, fg=GREY, font=small).pack(side="left")
            if c.get("nudge_available") is True:
                # the red ring is the invitation; the human clicks; never a timer
                tk.Button(row, text="nudge", relief="solid", fg=RED, bg=BG, font=small,
                          command=lambda s=sid: _nudge(s)).pack(side="left", padx=(4, 0))
        tk.Label(table, text=str(t.get("footer") or ""), anchor="w", bg=BG, fg=GREY, font=small).pack(fill="x", pady=(6, 0))

    def _select(n: int) -> None:
        selected["n"] = n
        _paint()

    def _refresh() -> None:
        state["model"] = build_widget_model(roots, probe_fn=probe_fn)
        _paint()
        if loop:
            win.after(interval_ms, _refresh)

    _paint()
    _paint_confirm()
    if loop:
        win.after(interval_ms, _refresh)
        win.mainloop()
        return {"ok": True, "threads": len((_model().get("threads") or []))}
    win.update_idletasks()
    n = len((_model().get("threads") or []))
    win.destroy()
    win.quit()
    del win
    gc.collect()
    return {"ok": True, "threads": n, "loop": False}
