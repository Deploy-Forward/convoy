"""The convoy widget as a web page in a native window.

Marco, 2026-09-05, seeing the Tk strip: "looks like shit ... make it look like a
polished product with real connectivity", and the reference apps (Claude's
quick-ask bar, the ChatGPT desktop app) are web UIs in native shells with the
OS's own translucency and rounded corners. Tk cannot get there, so the strip
is now HTML/CSS/JS (src/convoy/site/widget) served from a loopback HTTP server
inside the widget process, in a pywebview window when pywebview is importable
(WebView2 on Windows, with DWM acrylic + rounded corners applied to the HWND),
else Microsoft Edge in --app mode, else the default browser.

Everything on the page is the same model the Tk strip drew (widget.build_widget_model),
refreshed by the page every N seconds; actions POST to the same Python functions
the CLI runs (focus_seat, nudge_seat, start/onboard, crew). No second store, no
invented values: unknown stays null and renders "unknown".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .cmd import quiet_spawn_kwargs
from .index import recent
from .usage import CachedProbe, probe

SITE = Path(__file__).resolve().parent / "site"
PAGE = SITE / "widget"
ASSETS = {
    "/assets/logo.svg": (Path(__file__).resolve().parents[2] / "plugin" / "convoy" / "assets" / "logo.svg", "image/svg+xml"),
    "/assets/fonts/work-sans-latin.woff2": (SITE / "fonts" / "work-sans-latin.woff2", "font/woff2"),
    "/assets/fonts/jetbrains-mono-latin.woff2": (SITE / "fonts" / "jetbrains-mono-latin.woff2", "font/woff2"),
}
_LOGO_FALLBACK = SITE / "favicon.svg"

ENGINES = ("auto", "webview", "edge", "browser", "tk")


def choose_engine(requested: str = "auto", *, has_webview: bool | None = None, edge_path: str | None = None) -> str:
    """auto -> webview when importable, else edge --app when Edge exists, else browser."""
    want = (requested or "auto").strip().lower()
    if want not in ENGINES:
        raise ValueError("engine must be one of " + ", ".join(ENGINES))
    if want != "auto":
        return want
    if has_webview is None:
        try:
            import webview  # noqa: F401
            has_webview = True
        except Exception:
            has_webview = False
    if has_webview:
        return "webview"
    if edge_path if edge_path is not None else find_edge():
        return "edge"
    return "browser"


def find_edge() -> str | None:
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(p).is_file():
            return p
    return None


class WidgetApi:
    """The Python side of every page action. Pure functions in, JSON out."""

    def __init__(self, roots: list[Path] | None, *, probe_fn: Callable[[str], dict[str, Any]] | None = None,
                 refresh_s: float = 3.0, on_pin: Callable[[bool], bool] | None = None):
        self.roots = roots
        self.probe = probe_fn or CachedProbe(probe)
        self.refresh_s = float(refresh_s)
        self.on_pin = on_pin
        self.pinned = True
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._built_at = float("-inf")
        self._building = False
        self.sync_build = False   # tests: build inline so a GET sees the model

    def _build(self) -> dict[str, Any]:
        from .widget import build_widget_model
        m = build_widget_model(self.roots, probe_fn=self.probe)
        m["refresh_ms"] = int(self.refresh_s * 1000)
        return m

    def model(self) -> dict[str, Any]:
        """The LAST built model, instantly; a rebuild runs on a background
        thread at most every refresh_s (live: pane scan ~3 s, git provenance
        per chair, so building on the request path left the page on 'reading
        the thread' for 10-30 s). The first call returns a loading card."""
        import time as _t
        now = _t.monotonic()
        with self._lock:
            cached = self._cached
            due = (now - self._built_at) >= self.refresh_s
            kick = due and not self._building
            if kick:
                self._building = True
        if kick:
            def work() -> None:
                try:
                    m = self._build()
                except Exception as e:  # the page shows the failure, never a stale success
                    m = {"ok": False, "error": type(e).__name__ + ": " + str(e), "threads": []}
                with self._lock:
                    self._cached = m
                    self._built_at = _t.monotonic()
                    self._building = False
            if self.sync_build:
                work()
                with self._lock:
                    return dict(self._cached or {})
            threading.Thread(target=work, daemon=True).start()
        if cached is None:
            return {"ok": True, "loading": True, "threads": [], "refresh_ms": int(self.refresh_s * 1000), "now": None}
        return dict(cached)

    def focus(self, root: str, seat: str) -> dict[str, Any]:
        from .focus import focus_seat
        try:
            return focus_seat(Path(root), seat)
        except (ValueError, OSError) as e:
            return {"ok": False, "focused": False, "reason": str(e)}

    def nudge(self, root: str, seat: str, dry_run: bool = True, consent: str | None = None, force: bool = False) -> dict[str, Any]:
        from .nudge import nudge_seat
        try:
            return nudge_seat(Path(root), seat, dry_run=bool(dry_run), consent=consent, force=bool(force))
        except (ValueError, OSError) as e:
            return {"ok": False, "delivery": "refused", "error": str(e)}

    def pin(self, on: bool) -> dict[str, Any]:
        self.pinned = bool(on)
        applied = self.on_pin(self.pinned) if self.on_pin else None
        return {"ok": True, "on": self.pinned, "applied": applied}

    def card(self, root: str | None = None) -> dict[str, Any]:
        """The @convoy card: installed harnesses, where/models/effort/usage,
        recent threads for the picker. This is the '+' flow's source of truth."""
        from .card import build_card
        from .mcp_http import TOOLS
        base = Path(root) if root else Path(self.roots[0]) if self.roots else Path.cwd()
        try:
            c = build_card(base, listed=[str(t["name"]) for t in TOOLS], probe_fn=self.probe)
        except Exception as e:  # a card that cannot be built is a card that says so
            c = {"ok": False, "error": type(e).__name__ + ": " + str(e), "rows": []}
        c["recent"] = recent(10)
        return c

    def start(self, repo: str | None, harnesses: list[str], thread: str | None, github: bool | None,
              seats: list[dict[str, Any]], launch: bool) -> dict[str, Any]:
        """Original spec: GitHub? -> repo -> harnesses -> N seats (harness, model,
        effort, where) -> launch. onboard binds (URL cloned once), crew mints
        one worktree per seat, joins with boot prompts, brings ONE window up.
        Every refusal comes back as the card it is; nothing is retried blindly."""
        from .onboard import onboard
        from .crew import crew
        from .bringup import live_runner
        target = (repo or "").strip() or None
        base = Path(self.roots[0]) if self.roots else Path.cwd()
        gh = github if github is not None else None
        ob = onboard(base, harnesses, thread=(thread or None), checkout_root=target, github=gh)
        out: dict[str, Any] = {"ok": bool(ob.get("ok")), "onboard": ob}
        if not ob.get("ok"):
            return out
        root = Path(str(ob.get("root") or base))
        specs = [{k: v for k, v in s.items() if k in ("harness", "model", "effort", "where", "title") and v not in (None, "")} for s in seats if s.get("harness")]
        if specs:
            cw = crew(root, specs, thread=ob.get("thread"), runner=live_runner if launch else None)
            out["crew"] = cw
            out["ok"] = bool(cw.get("ok"))
        out["root"] = str(root)
        return out

    def plus(self) -> dict[str, Any]:
        return {"ok": True, "text": "open the start panel", "recent": recent(10)}


def make_handler(api: WidgetApi):
    class H(BaseHTTPRequestHandler):
        server_version = "convoy-widget"

        def log_message(self, *_a: Any) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            p = self.path.split("?", 1)[0]
            if p in ("/", "/index.html"):
                html = (PAGE / "index.html").read_text(encoding="utf-8")
                glass = "glass=1" in self.path
                html = html.replace("<body>", '<body class="%s" data-refresh="%d">' % ("glass" if glass else "opaque", int(api.refresh_s * 1000)), 1)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if p == "/widget.js":
                return self._send(200, (PAGE / "widget.js").read_bytes(), "text/javascript; charset=utf-8")
            if p == "/api/model":
                return self._json(api.model())
            if p == "/api/card":
                return self._json(api.card())
            if p in ASSETS:
                path, ctype = ASSETS[p]
                if not path.is_file() and p.endswith("logo.svg"):
                    path = _LOGO_FALLBACK
                if path.is_file():
                    return self._send(200, path.read_bytes(), ctype)
            return self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"ok": False, "error": "bad json"}, 400)
            p = self.path.split("?", 1)[0]
            if p == "/api/focus":
                return self._json(api.focus(str(body.get("root") or "."), str(body.get("seat") or "")))
            if p == "/api/nudge":
                return self._json(api.nudge(str(body.get("root") or "."), str(body.get("seat") or ""),
                                            dry_run=body.get("dry_run", True), consent=body.get("consent"), force=bool(body.get("force"))))
            if p == "/api/pin":
                return self._json(api.pin(bool(body.get("on"))))
            if p == "/api/plus":
                return self._json(api.plus())
            if p == "/api/card":
                return self._json(api.card(body.get("root")))
            if p == "/api/start":
                return self._json(api.start(body.get("repo"), list(body.get("harnesses") or []), body.get("thread"),
                                            body.get("github"), list(body.get("seats") or []), bool(body.get("launch"))))
            if p == "/api/open":
                url = str(body.get("url") or "")
                if url.startswith("https://"):
                    webbrowser.open(url)
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "https only"})
            return self._json({"ok": False, "error": "not found"}, 404)

    return H


def serve(api: WidgetApi, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _apply_windows_glass(title: str) -> dict[str, Any]:
    """DWM acrylic backdrop + rounded corners on the pywebview HWND (Win11)."""
    if os.name != "nt":
        return {"applied": False, "reason": "not windows"}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        import time as _t
        hwnd = 0
        for _ in range(40):                      # the HWND appears shortly after webview.start
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                break
            _t.sleep(0.1)
        if not hwnd:
            return {"applied": False, "reason": "window not found"}
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        corner = wintypes.INT(2)      # DWMWCP_ROUND
        backdrop = wintypes.INT(3)    # DWMSBT_TRANSIENTWINDOW (acrylic)
        dark = wintypes.INT(1)
        r1 = dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        r2 = dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        r3 = dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))
        return {"applied": r1 == 0 and r2 == 0, "hwnd": int(hwnd), "corner": r1, "backdrop": r2, "dark": r3}
    except Exception as e:  # pragma: no cover - platform specific
        return {"applied": False, "reason": type(e).__name__ + ": " + str(e)}


def run_web_widget(roots: list[Path | str] | None = None, *, engine: str = "auto", topmost: bool = True,
                   refresh: float = 3.0, width: int = 560, height: int = 760, probe_fn=None,
                   block: bool = True, glass: bool = True) -> dict[str, Any]:
    chosen = choose_engine(engine)
    roots_p = [Path(r) for r in roots] if roots else None
    pin_state: dict[str, Any] = {"win": None}

    def on_pin(on: bool) -> bool | None:
        w = pin_state.get("win")
        if w is not None:
            try:
                w.on_top = bool(on)
                return bool(on)
            except Exception:
                return None
        return None

    api = WidgetApi(roots_p, probe_fn=probe_fn, refresh_s=refresh, on_pin=on_pin)
    httpd = serve(api)
    api.model()   # kick the first build now, so it overlaps the window coming up (live: ~10 s, 3 s of it the pane scan)
    url = "http://127.0.0.1:%d/" % httpd.server_address[1] + ("?glass=1" if glass and chosen == "webview" else "")
    card: dict[str, Any] = {"ok": True, "engine": chosen, "url": url, "port": httpd.server_address[1], "glass": None}
    if not block:
        card["httpd"] = httpd
        return card
    if chosen == "webview":
        import webview
        title = "convoy"
        win = webview.create_window(title, url, width=width, height=height, frameless=True, easy_drag=True,
                                    on_top=bool(topmost), transparent=bool(glass), background_color="#17181C", min_size=(420, 520))
        pin_state["win"] = win

        def after_start() -> None:
            card["glass"] = _apply_windows_glass(title)
        webview.start(after_start, private_mode=True)
        httpd.shutdown()
        return card
    if chosen == "edge":
        edge = find_edge()
        argv = [edge, "--app=" + url, "--window-size=%d,%d" % (width, height), "--user-data-dir=" + str(Path.home() / ".convoy" / "widget-edge")]
        p = subprocess.Popen(argv, **quiet_spawn_kwargs())
        card["pid"] = p.pid
        p.wait()
        httpd.shutdown()
        return card
    webbrowser.open(url)
    card["note"] = "opened in the default browser; close the widget with Ctrl+C"
    try:
        threading.Event().wait()
    finally:
        httpd.shutdown()
    return card
