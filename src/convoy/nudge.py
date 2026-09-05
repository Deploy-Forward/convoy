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
from pathlib import Path
from typing import Any, Callable

from .consent import consume_consent, request_consent
from .convoy import list_seats
from .harness_contract import canonical_harness_id
from .panes import bodies as panes_bodies
from .synapse import try_codex_queue

Runner = Callable[[list[str]], dict[str, Any]]
WindowsFn = Callable[[], list[dict[str, Any]]]
PanesFn = Callable[[Path], dict[str, Any]]
QueueFn = Callable[[str, str], dict[str, Any] | None]
LeaderFn = Callable[[], dict[str, Any]]
SendFn = Callable[[dict[str, Any], str], dict[str, Any]]

GENERIC_TITLES = frozenset({
    "grok", "codex", "claude", "claude code", "cursor", "cursor-agent",
    "agy", "hermes", "pi", "windows terminal", "powershell", "pwsh", "cmd",
})

# harness_effort.json-style notes from the slice-5b matrix (g2, this machine).
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
            "3 windows, all WT pid 99004. Titles: Fable conductor; this grok "
            "user-prompt (not the worktree, not seat title 'g2'); "
            "'convoy-wt-happy-wt-luna2' (unique worktree folder). A busy grok "
            "title is the prompt, so worktree-matching cannot identify g1/g2. "
            "Idle title 'grok' is generic and never unique with two grok chairs."
        ),
    },
    {
        "command": "Fable live keystroke 2026-09-05T05:57-06:00Z (cited, not re-run)",
        "ts": "2026-09-05T05:57:00Z",
        "observed": (
            "title-verified SendInput into an idle grok pane DID wake it (g1 "
            "drained 4 rows). Alt+Arrow without a title re-check delivered to "
            "the wrong pane. Adapter here never Alt+Arrows: send only when the "
            "currently focused window title uniquely names the chair."
        ),
    },
]


def _seat_row(root: Path, session_id: str) -> dict[str, Any] | None:
    sid = str(session_id or "").strip()
    for row in list_seats(root):
        if row.get("session_id") == sid:
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


def _window_names_chair(text: str, worktree_name: str, seat_title: str) -> bool:
    """Worktree folder names are unique and long. Short seat titles ('g2')
    appear inside prompts; only an exact/prefix pane title counts."""
    raw = str(text or "")
    name = str(worktree_name or "").strip()
    if name and len(name) >= 8 and _contains_token(raw, name):
        return True
    s = str(seat_title or "").strip()
    if not s or s.lower() in GENERIC_TITLES:
        return False
    t = raw.strip()
    sl, low = s.lower(), t.lower()
    if low == sl:
        return True
    if low.startswith(sl + " - ") or low.startswith(sl + " | "):
        return True
    return False


def _pane_label(window: dict[str, Any] | None, tmux_target: str | None) -> str:
    if tmux_target:
        return "tmux:" + tmux_target
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
        ok = _window_names_chair(text, name, title)
        if ok and hwnd not in seen:
            hits.append(w)
            seen.add(hwnd)
    if len(hits) == 1:
        return hits[0]
    return None


def identify_target(
    root: Path,
    session_id: str,
    *,
    panes_fn: PanesFn | None = None,
    windows_fn: WindowsFn | None = None,
    target: str | None = None,
    leader_fn: LeaderFn | None = None,
) -> dict[str, Any]:
    """Prove the pane is this chair, or say why not. Never sends keys."""
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
) -> dict[str, Any]:
    """Identify, then (unless dry_run) consent, then wake. Never delivered=true."""
    root = Path(root)
    card = identify_target(
        root, session_id,
        panes_fn=panes_fn, windows_fn=windows_fn, target=target, leader_fn=leader_fn,
    )
    card["dry_run"] = bool(dry_run)
    if not card.get("ok"):
        return card
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

    seat = _seat_row(root, session_id) or {}
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

    adapter = card.get("adapter")
    run = runner or _default_runner
    if adapter == "tmux-send-keys":
        argv = ["tmux", "send-keys", "-t", str(target), keystroke]
        result = run(argv)
        card["argv"] = argv
        if result.get("ok") or result.get("returncode") == 0:
            card["delivery"] = "nudged"
            card["delivered"] = False
            return card
        card["ok"] = False
        card["reason"] = "tmux send-keys failed: " + str(
            result.get("error") or result.get("stderr") or result.get("returncode")
        )
        return card

    if adapter == "codex-queue":
        resume = str(seat.get("resume") or "").strip()
        q = queue_fn or try_codex_queue
        native = q(resume, keystroke) if resume else None
        if not native:
            card["ok"] = False
            card["reason"] = "codex queue did not accept the proven vendor session id"
            return card
        card["delivery"] = "nudged"
        card["delivered"] = False
        card["path"] = "codex-queue"
        return card

    if adapter == "wt-sendinput":
        sender = send_fn or _wt_send_keys
        pane_info = card.get("pane") if isinstance(card.get("pane"), dict) else {}
        result = sender(pane_info, keystroke)
        if result.get("ok"):
            card["delivery"] = "nudged"
            card["delivered"] = False
            return card
        card["ok"] = False
        card["reason"] = "wt-sendinput failed: " + str(result.get("error") or result)
        return card

    card["ok"] = False
    card["reason"] = "no adapter to run"
    return card
