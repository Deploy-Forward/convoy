"""WtWalkAdapter: the Windows Terminal pane walk, reconciled from two live runs.

g2 (06:03-06:17Z) proved that a WT window title names the chair only when it
carries the worktree folder name or an exact/prefix seat title; a generic idle
title ("grok") is never unique with two grok chairs, so `nudge` refuses.
Fable (05:57-06:00Z) proved that Alt+Arrow (WT default move-focus) plus a
RE-READ of the window title does reach an idle grok pane, and that the second
copy landed in the same pane because Alt+Left from the right-most pane moved
nothing. Both are true. This adapter keeps both:

  * exactly one candidate window, or fail before any window action;
  * foreground verified, or fail;
  * after each Alt+Arrow the title is re-read and the step is SKIPPED when
    the title did not change (that is the double-fire guard);
  * type only when the title matches idle_title_re, does not match busy_re,
    and pane_belongs_to(seat, title) names a rule; the rule is recorded.

Every OS call goes through one injectable `os_` object (enum_windows, title,
take_foreground, send_keys, sleep). The real user32 implementation exists
only on os.name == 'nt' and is never constructed in tests. Opt-in from
`nudge --seat ... --walk`; the default nudge keeps g2's refusal.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

BUSY_RE = re.compile(r"Waiting for response|Running:|Thinking")
DEFAULT_DIRECTIONS: tuple[str, ...] = ("none", "Alt+Right", "Alt+Left", "Alt+Down", "Alt+Up")
WT_CLASS = "CASCADIA_HOSTING_WINDOW_CLASS"

GENERIC_TITLES = frozenset({
    "grok", "codex", "claude", "claude code", "cursor", "cursor-agent",
    "agy", "hermes", "pi", "windows terminal", "powershell", "pwsh", "cmd",
})


def pane_belongs_to(
    seat: dict[str, Any],
    title: str,
    *,
    hwnd: int | None = None,
    crew_hwnd: int | None = None,
    idle_chairs: Iterable[str] | None = None,
) -> str | None:
    """Which rule proves this pane is the chair; None when none does.

    'worktree'              the worktree folder name (>= 8 chars) is in the title
    'seat-title'            the title IS the seat title or starts with it + ' - ' / ' | '
    'crew-window+sole-idle' the window is the crew window recorded for this thread
                            AND this chair is the only idle chair of its harness
    """
    text = str(title or "")
    low = text.strip().lower()
    wt = str(seat.get("worktree") or "")
    name = Path(wt).name if wt else ""
    if name and len(name) >= 8 and name.lower() not in GENERIC_TITLES and name.lower() in low:
        return "worktree"
    s = str(seat.get("title") or "").strip().lower()
    if s and s not in GENERIC_TITLES:
        if low == s or low.startswith(s + " - ") or low.startswith(s + " | "):
            return "seat-title"
    if crew_hwnd is not None and hwnd is not None and int(hwnd) == int(crew_hwnd):
        idle = [str(c) for c in (idle_chairs or [])]
        sid = str(seat.get("session_id") or "")
        if len(idle) == 1 and idle[0] == sid:
            return "crew-window+sole-idle"
    return None


class WtWalkAdapter:
    def __init__(self, os_: Any | None = None) -> None:
        self._os = os_

    def _host(self) -> Any | None:
        if self._os is not None:
            return self._os
        if os.name != "nt":
            return None
        return _User32()

    def walk(
        self,
        seat: dict[str, Any],
        text: str,
        *,
        idle_title_re: str,
        busy_re: Any = BUSY_RE,
        directions: Sequence[str] = DEFAULT_DIRECTIONS,
        crew_hwnd: int | None = None,
        idle_chairs: Iterable[str] | None = None,
        settle_s: float = 0.7,
    ) -> dict[str, Any]:
        card: dict[str, Any] = {
            "ok": False,
            "hwnd": None,
            "pane_title_before": None,
            "pane_title_after": None,
            "rule": None,
            "error": None,
            "steps": [],
            "crew_hwnd": crew_hwnd,
        }
        host = self._host()
        if host is None:
            card["error"] = "wt-walk needs Windows (user32); no host injected"
            return card
        idle_rx = re.compile(idle_title_re) if isinstance(idle_title_re, str) else idle_title_re
        busy_rx = re.compile(busy_re) if isinstance(busy_re, str) else busy_re
        idle = list(idle_chairs or [])

        candidates = []
        for w in host.enum_windows():
            hwnd = int(w.get("hwnd") or 0)
            title = str(w.get("title") or "")
            if pane_belongs_to(seat, title, hwnd=hwnd, crew_hwnd=crew_hwnd, idle_chairs=idle) or (
                crew_hwnd is not None and hwnd == int(crew_hwnd)
            ):
                candidates.append(w)
        if len(candidates) != 1:
            card["error"] = "expected exactly one candidate window, found " + str(len(candidates)) + "; nothing focused, nothing typed"
            card["candidates"] = [str(c.get("title") or "") for c in candidates]
            return card
        hwnd = int(candidates[0]["hwnd"])
        card["hwnd"] = hwnd
        card["pane_title_before"] = host.title(hwnd)

        if not host.take_foreground(hwnd):
            card["error"] = "could not take the foreground (SetForegroundWindow refused); nothing typed"
            return card

        previous = card["pane_title_before"]
        for direction in directions:
            step: dict[str, Any] = {"direction": direction, "title": None, "skip": None}
            if direction != "none":
                host.send_keys(hwnd, direction)
                host.sleep(settle_s)
            title = host.title(hwnd)
            step["title"] = title
            if direction != "none" and title == previous:
                step["skip"] = "focus did not move"
                card["steps"].append(step)
                continue
            previous = title
            if busy_rx.search(title):
                step["skip"] = "busy pane"
            elif not idle_rx.search(title):
                step["skip"] = "title does not match idle_title_re"
            else:
                rule = pane_belongs_to(seat, title, hwnd=hwnd, crew_hwnd=crew_hwnd, idle_chairs=idle)
                if rule is None:
                    step["skip"] = "idle, but no rule proves the pane belongs to this chair"
                else:
                    # one send: the text and its Enter; a second send is a second chance to misfire
                    host.send_keys(hwnd, text if text.endswith("\n") else text + "\n")
                    step["typed"] = True
                    card["steps"].append(step)
                    card["ok"] = True
                    card["rule"] = rule
                    card["pane_title_after"] = title
                    return card
            card["steps"].append(step)
        card["pane_title_after"] = previous
        card["error"] = "no pane matched: idle title, not busy, and belongs to the chair; nothing typed"
        return card


class _User32:
    """Real Windows Terminal host. Ported from scripts/wt-nudge.ps1. nt only."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

    def enum_windows(self) -> list[dict[str, Any]]:
        ctypes, wintypes, user32 = self.ctypes, self.wintypes, self.user32
        found: list[dict[str, Any]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd: int, _lp: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value != WT_CLASS:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": self.title(int(hwnd))})
            return True

        user32.EnumWindows(_cb, 0)
        return found

    def title(self, hwnd: int) -> str:
        buf = self.ctypes.create_unicode_buffer(512)
        self.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def take_foreground(self, hwnd: int) -> bool:
        user32, kernel32 = self.user32, self.kernel32
        VK_MENU, KEYEVENTF_KEYUP, SW_RESTORE = 0x12, 0x0002, 9
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        me = kernel32.GetCurrentThreadId()
        other = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(me, other, True)
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        finally:
            user32.AttachThreadInput(me, other, False)
        self.sleep(0.4)
        return int(user32.GetForegroundWindow()) == int(hwnd)

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)

    # -- keys ---------------------------------------------------------------
    _VK = {"Right": 0x27, "Left": 0x25, "Up": 0x26, "Down": 0x28, "Enter": 0x0D, "Alt": 0x12}

    def send_keys(self, hwnd: int, keys: str) -> bool:
        if keys.startswith("Alt+"):
            arrow = self._VK.get(keys[4:])
            if arrow is None:
                return False
            self._vk_down(self._VK["Alt"])
            self._vk_tap(arrow)
            self._vk_up(self._VK["Alt"])
            return True
        if keys in ("Enter", "\n"):
            self._vk_tap(self._VK["Enter"])
            return True
        for ch in keys:
            if ch == "\n":
                self._vk_tap(self._VK["Enter"])
            else:
                self._unicode(ch)
        return True

    def _input(self):
        ctypes, wintypes = self.ctypes, self.wintypes
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

        inp = INPUT()
        inp.type = 1
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return INPUT, inp

    def _send(self, INPUT, inp) -> None:
        self.user32.SendInput(1, self.ctypes.byref(inp), self.ctypes.sizeof(INPUT))

    def _vk_down(self, vk: int) -> None:
        INPUT, inp = self._input()
        inp.ki.wVk, inp.ki.wScan, inp.ki.dwFlags = vk, 0, 0
        self._send(INPUT, inp)

    def _vk_up(self, vk: int) -> None:
        INPUT, inp = self._input()
        inp.ki.wVk, inp.ki.wScan, inp.ki.dwFlags = vk, 0, 0x0002
        self._send(INPUT, inp)

    def _vk_tap(self, vk: int) -> None:
        self._vk_down(vk)
        self._vk_up(vk)

    def _unicode(self, ch: str) -> None:
        INPUT, inp = self._input()
        inp.ki.wVk, inp.ki.wScan, inp.ki.dwFlags = 0, ord(ch), 0x0004
        self._send(INPUT, inp)
        inp.ki.dwFlags = 0x0004 | 0x0002
        self._send(INPUT, inp)
