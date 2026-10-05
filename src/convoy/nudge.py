"""nudge --seat: wake one idle neuron on the user's own machine.

A wake is a per-harness FACT, not an assumption. A successful nudge returns
`delivery: nudged` and `delivered: false` — only the occupant's ack proves
receipt. Refuse when the pane cannot be proven to be that chair: a keystroke
into the wrong pane is worse than idle.

Write-gated on MCP. Consent names the pane and the exact keys. Never on the
public wire. Never a WM_CHAR / SendInput without that proof.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from .consent import consume_consent, request_consent
from .convoy import list_seats
from .harness_contract import canonical_harness_id
from .pane_host import host_state_path, pid_alive, read_host_records, request_nudge
from .panes import bodies as panes_bodies
from .wt_walk import BUSY_RE, WtWalkAdapter
from .synapse import try_codex_queue

Runner = Callable[[list[str]], dict[str, Any]]
WindowsFn = Callable[[], list[dict[str, Any]]]
PanesFn = Callable[[Path], dict[str, Any]]
QueueFn = Callable[[str, str], dict[str, Any] | None]
LeaderFn = Callable[[], dict[str, Any]]
SendFn = Callable[[dict[str, Any], str], dict[str, Any]]
HostRecordsFn = Callable[[Path], list[dict[str, Any]]]
PidAliveFn = Callable[[Any], bool]

GENERIC_TITLES = frozenset({
    "grok", "codex", "claude", "claude code", "cursor", "cursor-agent",
    "agy", "hermes", "pi", "windows terminal", "powershell", "pwsh", "cmd",
})

# harness_effort.json-style notes from the wake matrix (docs/audits/WAKE_MATRIX_2026-09-05.md).
WAKE_EVIDENCE = [
    {
        "command": "grok --help",
        "ts": "2026-09-05T06:03:21Z",
        "observed": (
            "no `queue` subcommand; has `leader`, `agent` (stdio/headless/serve/"
            "leader), --resume/-r, -p/--single, -c/--continue. grok help queue: "
            "unrecognized subcommand 'queue'."
        ),
    },
    {
        "command": "grok leader list",
        "ts": "2026-09-05T06:03:21Z",
        "observed": "exit 0; stdout 'No leader candidates found.' ~/.grok/leader.sock missing.",
    },
    {
        "command": "grok agent --help",
        "ts": "2026-09-05T06:03:21Z",
        "observed": (
            "stdio / --leader / --no-leader. Live TUI session/prompt needs a "
            "leader; a second --no-leader agent against a pid-held TUI is a steal."
        ),
    },
    {
        "command": "codex queue --help",
        "ts": "2026-09-05T06:03:21Z",
        "observed": "exists: `codex queue --thread <UUID or exact session name> --message <TEXT>`.",
    },
    {
        "command": "codex queue --thread 00000000-0000-0000-0000-000000000000 --message convoy-wake-matrix-probe",
        "ts": "2026-09-05T06:07:27Z",
        "observed": (
            "rc 1; stderr: thread/queue/add failed: no rollout found for thread id "
            "(code -32603). Queue without a proven vendor session id does not no-op "
            "quietly — it errors. Seats on this thread have resume=null."
        ),
    },
    {
        "command": "list WT CASCADIA_HOSTING_WINDOW_CLASS titles",
        "ts": "2026-09-05T06:03:21Z",
        "observed": (
            "3 windows, all one WT process. Titles: the conductor's session; this grok "
            "user-prompt (not the worktree, not the seat title); "
            "'<checkout>-wt-<seat>' (unique worktree folder). A busy grok "
            "title is the prompt, so worktree-matching cannot identify the grok chairs. "
            "Idle title 'grok' is generic and never unique with two grok chairs."
        ),
    },
    {
        "command": "live keystroke from the conductor's session (cited, not re-run)",
        "ts": "2026-09-05T05:57:00Z",
        "observed": (
            "title-verified SendInput into an idle grok pane DID wake it (the chair "
            "drained its rows). Alt+Arrow without a title re-check delivered to "
            "the wrong pane. Adapter here never Alt+Arrows: send only when the "
            "currently focused window title uniquely names the chair."
        ),
    },
]


def _seat_row(root: Path, session_id: str) -> dict[str, Any] | None:
    """The chair's seat row, with `pane_title`: the exact title Convoy gave its pane in the
    thread window (`<thread label> - <chair title>`), the only composed title that proves it."""
    sid = str(session_id or "").strip()
    for row in list_seats(root):
        if row.get("session_id") == sid:
            from .targeted_launch import root_thread_label, thread_pane_title
            try:
                return {**row, "pane_title": thread_pane_title(root_thread_label(root), row)}
            except (OSError, ValueError):
                return row
    return None


def _contains_token(text: str, token: str) -> bool:
    raw = str(text or "")
    tok = str(token or "").strip()
    if not tok:
        return False
    if tok.lower() in GENERIC_TITLES:
        return False
    return tok.lower() in raw.lower()


def _window_names_chair(text: str, worktree_name: str, seat_title: str, pane_title: str | None = None) -> bool:
    """Worktree folder names are unique and long. Short seat titles ('g2')
    appear inside prompts; only an exact/prefix pane title counts. A title in a
    Convoy thread window (`<label>-<4 hex> - <title>`) proves only the chair whose own
    composed title it is exactly (pane_title), never through the prefix rule."""
    raw = str(text or "")
    name = str(worktree_name or "").strip()
    if name and len(name) >= 8 and _contains_token(raw, name):
        return True
    s = str(seat_title or "").strip()
    if not s or s.lower() in GENERIC_TITLES:
        return False
    t = raw.strip()
    sl, low = s.lower(), t.lower()
    if pane_title and low == str(pane_title).strip().lower():
        return True
    if is_thread_pane_title(low):
        return False   # another chair's (or thread's) composed title: never by prefix
    if low == sl:
        return True
    if low.startswith(sl + " - ") or low.startswith(sl + " | "):
        return True
    return False


def is_thread_pane_title(low: str) -> bool:
    """The shape Convoy gives a pane in a thread window: `<name>-<4 hex> - <title>` (or the
    bare 8-hex label). Such a title is proof only as one chair's exact own title."""
    import re as _re
    return bool(_re.fullmatch(r"(?:[a-z0-9._-]{1,19}-[0-9a-f]{4}|[0-9a-f]{8}) - .+", low.strip().lower()))


def _pane_label(window: dict[str, Any] | None, tmux_target: str | None) -> str:
    if tmux_target:
        return "tmux:" + tmux_target
    if window and "host_pid" in window and "hwnd" not in window:
        return "pane-host host_pid=" + str(window.get("host_pid")) + " child_pid=" + str(window.get("child_pid"))
    if window and window.get("walk"):
        # names the PANE the focus-only probe found, not just the window
        return ("wt-walk HWND " + str(window.get("hwnd")) + " pane title=" + repr(window.get("title"))
                + " rule=" + str(window.get("rule")) + " (title re-read before typing; refuse if changed)")
    if window:
        return "HWND " + str(window.get("hwnd")) + " title=" + str(window.get("title") or "")
    return "unidentified"


def list_wt_windows() -> list[dict[str, Any]]:
    """Visible Windows Terminal windows: hwnd, pid, title (focused pane)."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []
    user32 = ctypes.windll.user32
    found: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value != "CASCADIA_HOSTING_WINDOW_CLASS":
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title.value})
        return True

    user32.EnumWindows(_cb, 0)
    return found


def grok_leader_status(*, exe: str | None = None) -> dict[str, Any]:
    bin_path = exe or shutil.which("grok") or shutil.which("grok.exe")
    card: dict[str, Any] = {
        "ok": bool(bin_path),
        "available": False,
        "raw": None,
        "error": None,
        "command": "grok leader list",
    }
    if not bin_path:
        card["error"] = "grok not on PATH"
        return card
    try:
        result = subprocess.run(
            [bin_path, "leader", "list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        card["error"] = type(e).__name__ + ": " + str(e)
        return card
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    card["raw"] = text[-1500:] if text else ""
    card["exit_code"] = result.returncode
    if result.returncode == 0 and text and "no leader" not in text.lower():
        card["available"] = True
    return card


def _default_runner(argv: list[str]) -> dict[str, Any]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "returncode": 127, "error": str(e), "argv": argv}
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "argv": argv,
    }


def _match_window(seat: dict[str, Any], windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One WT window whose focused-pane title uniquely names this chair."""
    wt = str(seat.get("worktree") or "")
    name = Path(wt).name if wt else ""
    title = str(seat.get("title") or "").strip()
    hits: list[dict[str, Any]] = []
    seen: set[int] = set()
    for w in windows:
        hwnd = int(w.get("hwnd") or 0)
        text = str(w.get("title") or "")
        ok = _window_names_chair(text, name, title, seat.get("pane_title"))
        if ok and hwnd not in seen:
            hits.append(w)
            seen.add(hwnd)
    if len(hits) == 1:
        return hits[0]
    return None   # none, or several: ambiguous, never pick one


def identify_target(
    root: Path,
    session_id: str,
    *,
    panes_fn: PanesFn | None = None,
    windows_fn: WindowsFn | None = None,
    target: str | None = None,
    leader_fn: LeaderFn | None = None,
    host_records_fn: HostRecordsFn | None = None,
    pid_alive_fn: PidAliveFn | None = None,
) -> dict[str, Any]:
    """Prove the pane is this chair, or say why not. Never sends keys.

    `panes` cannot place a claude body on this OS (no
    process cwd, and a busy pane's title is its prompt, never the chair), so
    the window-title path below refuses every claude neuron at its prompt.
    The pane host already proved this exact body at launch (`host_pid`,
    `child_pid` on its own state row, written by the process that spawned the
    child — never a command-line guess). A RUNNING host record for this chair
    is checked first and, when present, wins outright: it is strictly better
    proof than a window title, and it is the only proof that exists at all
    for a harness `panes` cannot place.
    """
    sid = str(session_id or "").strip()
    card: dict[str, Any] = {
        "ok": True,
        "seat": sid,
        "identified": False,
        "reason": None,
        "host": None,
        "body": None,
        "pane": None,
        "adapter": None,
        "leader": None,
        "evidence": WAKE_EVIDENCE,
        "delivered": False,
        "delivery": None,
    }
    seat = _seat_row(root, sid)
    if seat is None:
        return {"ok": False, "seat": sid, "identified": False, "delivered": False,
                "delivery": None, "reason": "unknown seat: " + sid, "error": "unknown seat: " + sid}

    harness = canonical_harness_id(seat.get("to")) or str(seat.get("to") or "")
    card["harness"] = harness
    card["worktree"] = seat.get("worktree")
    card["resume_available"] = bool(str(seat.get("resume") or "").strip())

    alive = pid_alive_fn or pid_alive
    for record in (host_records_fn or read_host_records)(root):
        if record.get("session_id") != sid:
            continue
        if record.get("status") != "running":
            continue
        if not alive(record.get("host_pid")):
            continue
        card["host"] = "pane-host"
        card["identified"] = True
        card["adapter"] = "pane-host"
        card["pane"] = {
            "host_pid": record.get("host_pid"),
            "child_pid": record.get("child_pid"),
            "terminal_session": record.get("terminal_session"),
        }
        return card

    view = (panes_fn or panes_bodies)(root)
    chair = None
    for row in view.get("chairs") or []:
        if row.get("session_id") == sid:
            chair = row
            break
    if chair is None:
        card["reason"] = "seat not in panes view"
        return card
    live_bodies = list(chair.get("bodies") or [])
    card["body"] = live_bodies[0] if len(live_bodies) == 1 else None
    if chair.get("duplicate") or len(live_bodies) > 1:
        card["reason"] = "duplicate bodies; refuse rather than pick a pane"
        return card
    if not live_bodies:
        card["reason"] = chair.get("live_reason") or "no proven live body for this chair"
        return card

    leader = (leader_fn or grok_leader_status)() if harness == "grok" else {"available": False}
    card["leader"] = {"available": bool(leader.get("available")), "raw": leader.get("raw")}

    tmux_target = str(target or "").strip() or None
    if os.environ.get("TMUX"):
        card["host"] = "tmux"
        if not tmux_target:
            card["reason"] = "tmux: no pane target for this chair"
            return card
        card["identified"] = True
        card["pane"] = {"target": tmux_target}
        card["adapter"] = "tmux-send-keys"
        return card

    if os.name == "nt" and (shutil.which("wt") or shutil.which("wt.exe") or windows_fn is not None):
        card["host"] = "windows-terminal"
        windows = (windows_fn or list_wt_windows)()
        window = _match_window(seat, windows)
        if window is None:
            card["reason"] = (
                "windows-terminal: no unique title match for worktree/seat title "
                "(generic titles like 'grok' never count; a prompt-titled grok pane "
                "is not proven)"
            )
            return card
        card["identified"] = True
        card["pane"] = {"hwnd": window.get("hwnd"), "title": window.get("title"), "pid": window.get("pid")}
        if harness == "codex" and card["resume_available"]:
            card["adapter"] = "codex-queue"
        elif harness == "grok" and leader.get("available"):
            card["adapter"] = "grok-acp-unshipped"
            card["reason"] = (
                "grok leader is up; ACP session/prompt is the wake, not a keystroke. "
                "Adapter not shipped on this branch; refuse rather than steal via --no-leader."
            )
            card["identified"] = True
            return card
        else:
            card["adapter"] = "wt-sendinput"
        return card

    card["host"] = None
    card["reason"] = "no evidenced pane-host adapter"
    return card


def _wt_send_keys(window: dict[str, Any], keys: str) -> dict[str, Any]:
    """Foreground the proven HWND, re-check title, SendInput. No Alt+Arrow."""
    if os.name != "nt":
        return {"ok": False, "error": "wt-sendinput is Windows only"}
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return {"ok": False, "error": "ctypes unavailable"}

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = int(window["hwnd"])
    want = str(window.get("title") or "")
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002

    foreground = user32.GetForegroundWindow()
    this = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(hwnd, None)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.AttachThreadInput(this, other, True)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(this, other, False)

    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    if title.value != want:
        return {
            "ok": False,
            "error": "title changed before send (now " + repr(title.value) + ", wanted " + repr(want) + ")",
        }

    # KEYBDINPUT unicode path: send each character, then Enter if keys is 'Enter'.
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", PUL)]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _I)]

    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1
    extra = ctypes.c_ulong(0)

    def _send_unicode(ch: str) -> None:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = 0
        inp.ki.wScan = ord(ch)
        inp.ki.dwFlags = KEYEVENTF_UNICODE
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(extra)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        inp.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _send_vk(vk: int) -> None:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.wScan = 0
        inp.ki.dwFlags = 0
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(extra)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        inp.ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    payload = keys
    if payload.lower() in ("enter", "return", "c-m"):
        _send_vk(0x0D)
    else:
        for ch in payload:
            if ch == "\n":
                _send_vk(0x0D)
            else:
                _send_unicode(ch)
    _ = foreground
    return {"ok": True, "hwnd": hwnd, "title": want}


IdleChairsFn = Callable[[Path, str], list[str]]


def _idle_title_re(harness: str) -> str:
    """An idle TUI pane's WT title is the bare harness name (grok: 'grok')."""
    return "^" + (harness or "grok") + "$"


def crew_window_hwnd(root: Path) -> int | None:
    """The WT window recorded for this thread (newest kind=crew-window row with
    an hwnd). None when nothing was recorded: never guessed."""
    from .layer import feed_since
    hwnd = None
    for row in feed_since(root, "1970-01-01T00:00:00Z"):
        if row.get("kind") == "crew-window" and row.get("hwnd") is not None:
            try:
                hwnd = int(row["hwnd"])
            except (TypeError, ValueError):
                continue
    return hwnd


def idle_chairs(root: Path, harness: str) -> list[str]:
    """Chairs of this harness whose widget chip reads 'idle' (widget.py)."""
    from .widget import build_widget_model
    model = build_widget_model([root])
    out: list[str] = []
    for thread in model.get("threads") or []:
        for chair in thread.get("chairs") or []:
            if chair.get("chip") == "idle" and canonical_harness_id(chair.get("harness")) == canonical_harness_id(harness):
                out.append(str(chair.get("session_id")))
    return out


def _arm_walk(root: Path, session_id: str, card: dict[str, Any], idle_chairs_fn: IdleChairsFn | None) -> None:
    """Opt-in: replace the 'title not unique' refusal with a walk plan when a
    crew window is recorded; still unidentified (with reason) when it is not."""
    harness = str(card.get("harness") or "")
    hwnd = crew_window_hwnd(root)
    idle = (idle_chairs_fn or idle_chairs)(root, harness)
    card["walk"] = {"crew_hwnd": hwnd, "idle_chairs": idle, "harness": harness}
    if hwnd is None:
        card["reason"] = str(card.get("reason") or "") + "; --walk: no crew-window row records an hwnd for this thread"
        return
    if len(idle) != 1 or idle[0] != str(session_id):
        card["reason"] = str(card.get("reason") or "") + "; --walk: idle chairs of " + harness + " per widget chip = " + repr(idle) + ", need exactly this one"
        return
    card["identified"] = True
    card["adapter"] = "wt-walk"
    card["pane"] = {"hwnd": hwnd, "title": None, "walk": True}
    card["reason"] = None


_NAMED_KEYS = frozenset({"enter", "return", "c-m"})


def _nudge_text(keystroke: str, nudge_id: str) -> tuple[str, bool]:
    """The typed text carries the nudge_id (WIDGET.md rule) unless the keystroke
    is a bare key name (Enter): a key carries no text, so the tag cannot ride it;
    the feed row then says tag_in_text=false rather than pretending."""
    if keystroke.lower() in _NAMED_KEYS:
        return keystroke, False
    return keystroke + " nudge=" + nudge_id, True


def last_unacked_nudge(root: Path, session_id: str) -> str | None:
    """nudge_id of this chair's newest kind=nudge row when no later row FROM the
    chair cites it (nudge=<id> in the summary or a nudge_id field); else None."""
    from .layer import feed_since
    rows = feed_since(root, "1970-01-01T00:00:00Z")
    last_id, last_i = None, -1
    for i, row in enumerate(rows):
        if row.get("kind") == "nudge" and str(row.get("instance_id")) == str(session_id) and row.get("nudge_id"):
            last_id, last_i = str(row["nudge_id"]), i
    if last_id is None:
        return None
    for row in rows[last_i + 1:]:
        if str(row.get("from") or "") != str(session_id):
            continue
        if str(row.get("nudge_id") or "") == last_id or ("nudge=" + last_id) in str(row.get("summary") or ""):
            return None
    return last_id


def _record_nudge(root: Path, session_id: str, card: dict[str, Any], nudge_id: str, typed: str, tagged: bool) -> None:
    """Row FIRST: the record exists even if typing fails (pseudocode section 1)."""
    from .layer import hook
    pane = card.get("pane") if isinstance(card.get("pane"), dict) else {}
    hook(root, "nudge", "nudge " + str(session_id) + " nudge=" + nudge_id, str(session_id), author=None,
         extra={"nudge_id": nudge_id, "transport": card.get("adapter"), "text": typed, "tag_in_text": tagged,
                "pane_title_before": pane.get("title"), "hwnd": pane.get("hwnd"), "delivered": False})


PANE_HOST_ACK_TIMEOUT_S = 5.0


def _await_pane_host_ack(
    root: Path, session_id: str, nudge_id: str,
    *, timeout: float = PANE_HOST_ACK_TIMEOUT_S,
    sleep_fn: Callable[[float], None] | None = None,
    clock_fn: Callable[[], float] | None = None,
    state_reader: Callable[[Path, str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Poll the host's own state row for `last_nudge.nudge_id == nudge_id`,
    written by the host's poll loop once it has actually typed (or tried and
    failed). A timeout is not a failure to type: it means the host has not
    gotten to it yet, and is reported as such, never invented as a typed_at."""
    import time as _time

    sleep = sleep_fn or _time.sleep
    clock = clock_fn or _time.monotonic

    def _read(root_: Path, sid: str) -> dict[str, Any] | None:
        path = host_state_path(root_, sid)
        if not path.is_file():
            return None
        try:
            import json as _json
            value = _json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    read = state_reader or _read
    deadline = clock() + timeout
    while True:
        state = read(root, session_id) or {}
        last = state.get("last_nudge") if isinstance(state.get("last_nudge"), dict) else None
        if last is not None and str(last.get("nudge_id") or "") == nudge_id:
            return {"ok": bool(last.get("ok")), "typed_at": last.get("typed_at"), "error": last.get("error")}
        if clock() >= deadline:
            return {"ok": False, "typed_at": None, "error": "pane host has not consumed the nudge request yet (timeout)"}
        sleep(0.1)


def _record_nudge_result(root: Path, session_id: str, nudge_id: str, result: dict[str, Any]) -> None:
    from .layer import hook
    ok = bool(result.get("ok"))
    hook(root, "nudge-result", "nudge " + str(session_id) + " nudge=" + nudge_id + (" typed" if ok else " failed"),
         str(session_id), author=None,
         extra={"nudge_id": nudge_id, "ok": ok, "error": result.get("error"),
                "pane_title_before": result.get("pane_title_before"), "pane_title_after": result.get("pane_title_after"),
                "delivered": False})


def nudge_seat(
    root: Path | str,
    session_id: str,
    *,
    consent: str | None = None,
    keys: str | None = None,
    dry_run: bool = False,
    target: str | None = None,
    runner: Runner | None = None,
    panes_fn: PanesFn | None = None,
    windows_fn: WindowsFn | None = None,
    queue_fn: QueueFn | None = None,
    leader_fn: LeaderFn | None = None,
    send_fn: SendFn | None = None,
    walk: bool = False,
    walk_adapter: WtWalkAdapter | None = None,
    idle_chairs_fn: IdleChairsFn | None = None,
    force: bool = False,
    host_records_fn: HostRecordsFn | None = None,
    pid_alive_fn: PidAliveFn | None = None,
    ack_fn: Callable[[Path, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Identify, then (unless dry_run) consent, then wake. Never delivered=true.

    Every live wake writes kind=nudge (before typing) and kind=nudge-result
    (after) through layer.hook, carrying one nudge_id that also rides the typed
    text; a chair whose last nudge_id has no ack from the chair is refused
    unless force. `walk=True` (CLI --walk) is the OPT-IN: when the WT title is
    not unique (the default refusal), hand the pane hunt to wt_walk.WtWalkAdapter,
    which Alt+Arrows with a title re-read and types only into a pane a rule
    proves is this chair. Default behaviour is unchanged."""
    root = Path(root)
    card = identify_target(
        root, session_id,
        panes_fn=panes_fn, windows_fn=windows_fn, target=target, leader_fn=leader_fn,
        host_records_fn=host_records_fn, pid_alive_fn=pid_alive_fn,
    )
    card["dry_run"] = bool(dry_run)
    if not card.get("ok"):
        return card
    if walk and not card.get("identified") and card.get("host") == "windows-terminal" \
            and "no unique title" in str(card.get("reason") or ""):
        _arm_walk(root, session_id, card, idle_chairs_fn)
    if dry_run:
        card["next"] = "nudge --seat " + str(session_id) + " --keys <exact> --consent <grant>"
        return card
    if not card.get("identified"):
        return card
    if card.get("adapter") == "grok-acp-unshipped":
        card["ok"] = True
        card["delivery"] = None
        return card

    keystroke = str(keys or "").strip()
    if not keystroke:
        card["ok"] = False
        card["reason"] = "nudge requires --keys (the exact keystroke the consent card names)"
        card["error"] = card["reason"]
        return card

    pending = last_unacked_nudge(root, session_id)
    if pending and not force:
        card["ok"] = False
        card["reason"] = "last nudge " + pending + " has no ack from " + str(session_id) + " yet; --force to repeat"
        card["error"] = card["reason"]
        card["delivery"] = None
        card["delivered"] = False
        card["unacked_nudge_id"] = pending
        return card
    card["forced_over"] = pending if (pending and force) else None

    seat = _seat_row(root, session_id) or {}
    adapter = card.get("adapter")
    walker = walk_adapter or WtWalkAdapter()
    walk_kw: dict[str, Any] = {}
    if adapter == "wt-walk":
        # focus-only probe: the consent card must name the PANE, and only the
        # walk can find it. Same walk, stop at the match, type nothing.
        info = card.get("walk") or {}
        harness = str(card.get("harness") or "")
        walk_kw = dict(idle_title_re=_idle_title_re(harness), busy_re=BUSY_RE,
                       crew_hwnd=info.get("crew_hwnd"), idle_chairs=info.get("idle_chairs") or [])
        probe = walker.walk(seat, "", type_text=False, **walk_kw)
        card["walk"] = {**info, "probe": probe}
        if not probe.get("ok"):
            card["ok"] = False
            card["reason"] = "wt-walk probe found no pane to name on the consent card: " + str(probe.get("error"))
            card["delivery"] = None
            card["delivered"] = False
            return card
        card["pane"] = {"hwnd": probe.get("hwnd"), "title": probe.get("pane_title_after"),
                        "rule": probe.get("rule"), "walk": True}
    pane = _pane_label(card.get("pane") if isinstance(card.get("pane"), dict) else None, target)
    to = str(seat.get("to") or card.get("harness") or "")
    worktree = str(seat.get("worktree") or "")
    if not consent:
        waiting = request_consent(
            root, "nudge-pane",
            session_id=str(session_id), to=to, worktree=worktree,
            keys=keystroke, pane=pane,
        )
        return {**card, **waiting, "ok": False, "delivery": None, "delivered": False}

    try:
        consume_consent(
            root, consent, "nudge-pane",
            session_id=str(session_id), to=to, worktree=worktree,
            keys=keystroke, pane=pane,
        )
    except ValueError as e:
        card["ok"] = False
        card["error"] = str(e)
        card["reason"] = str(e)
        return card

    nudge_id = uuid.uuid4().hex
    typed, tagged = _nudge_text(keystroke, nudge_id)
    card["nudge_id"] = nudge_id
    card["text"] = typed
    card["tag_in_text"] = tagged
    card["delivered"] = False
    card["next"] = "await a row from " + str(session_id) + " citing nudge=" + nudge_id
    run = runner or _default_runner

    def _finish(result: dict[str, Any], fail_prefix: str) -> dict[str, Any]:
        _record_nudge_result(root, session_id, nudge_id, result)
        if result.get("ok"):
            card["delivery"] = "nudged"
            return card
        card["ok"] = False
        card["delivery"] = "failed"
        card["reason"] = fail_prefix + str(result.get("error") or result.get("stderr") or result.get("returncode") or result)
        return card

    if adapter == "tmux-send-keys":
        _record_nudge(root, session_id, card, nudge_id, typed, tagged)
        argv = ["tmux", "send-keys", "-t", str(target), typed]
        result = run(argv)
        card["argv"] = argv
        ok = bool(result.get("ok") or result.get("returncode") == 0)
        return _finish({**result, "ok": ok}, "tmux send-keys failed: ")

    if adapter == "codex-queue":
        resume = str(seat.get("resume") or "").strip()
        q = queue_fn or try_codex_queue
        _record_nudge(root, session_id, card, nudge_id, typed, tagged)
        native = q(resume, typed) if resume else None
        card["path"] = "codex-queue"
        return _finish({"ok": bool(native), "error": None if native else "codex queue did not accept the proven vendor session id"}, "")

    if adapter == "wt-walk":
        _record_nudge(root, session_id, card, nudge_id, typed, tagged)
        result = walker.walk(seat, typed, expect_title=card["pane"].get("title"), **walk_kw)
        card["walk"] = {**card["walk"], **result}
        if result.get("ok"):
            card["pane"] = {**card["pane"], "hwnd": result.get("hwnd"), "title": result.get("pane_title_after")}
        return _finish(result, "wt-walk refused: ")

    if adapter == "wt-sendinput":
        sender = send_fn or _wt_send_keys
        pane_info = card.get("pane") if isinstance(card.get("pane"), dict) else {}
        _record_nudge(root, session_id, card, nudge_id, typed, tagged)
        result = sender(pane_info, typed)
        return _finish(dict(result), "wt-sendinput failed: ")

    if adapter == "pane-host":
        _record_nudge(root, session_id, card, nudge_id, typed, tagged)
        request_nudge(root, session_id, text=typed, nudge_id=nudge_id, consent=consent)
        ack = ack_fn(root, session_id, nudge_id) if ack_fn else _await_pane_host_ack(root, session_id, nudge_id)
        card["typed_at"] = ack.get("typed_at")
        return _finish(ack, "pane-host nudge failed: ")

    card["ok"] = False
    card["reason"] = "no adapter to run"
    return card
