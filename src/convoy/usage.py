"""Live harness usage probes. Never invent 0. Grok has no usage limit."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from typing import Any, Callable

from .cmd import quiet_spawn_kwargs

ProbeFn = Callable[[str], dict[str, Any]]
_ALIASES = {
    "antigravity": "agy",
    "antigravity-cli": "agy",
    "claude-code": "claude",
    "cursor_agent": "cursor-agent",
}
def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | quiet_spawn_kwargs()["creationflags"]
    try:
        p = subprocess.Popen(cmd, **kwargs)
    except OSError as e:
        return 127, str(e)
    try:
        out, err = p.communicate(input="", timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                capture_output=True,
                timeout=5,
            )
        else:
            p.kill()
        try:
            p.communicate(timeout=3)
        except Exception:
            pass
        return 124, "probe timeout"
    text = ((out or "") + (err or "")).strip()
    return p.returncode if p.returncode is not None else 1, text


def normalize_usage_remaining(value: Any) -> Any:
    """SPEC clamp: number|object|null only for usage_remaining."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, dict):
        return value
    return None


def _jsonish(text: str) -> Any:
    raw = text or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _coerce_pct(val: Any) -> int | None:
    try:
        pct = int(float(val))
    except (TypeError, ValueError):
        return None
    if 0 <= pct <= 100:
        return pct
    return None


def _parse_claude_progress(data: Any, text: str) -> tuple[int | None, int | None]:
    session_pct: int | None = None
    week_pct: int | None = None
    if isinstance(data, dict):
        for key in ("session_pct", "session_percent", "pct"):
            if key in data:
                session_pct = _coerce_pct(data.get(key))
                if session_pct is not None:
                    break
        sess = data.get("session")
        if session_pct is None and isinstance(sess, dict):
            for key in ("pct", "percent", "used"):
                if key in sess:
                    session_pct = _coerce_pct(sess.get(key))
                    if session_pct is not None:
                        break
        for key in ("week_pct", "week_percent"):
            if key in data:
                week_pct = _coerce_pct(data.get(key))
                if week_pct is not None:
                    break
        week = data.get("week")
        if week_pct is None and isinstance(week, dict):
            for key in ("pct", "percent", "used"):
                if key in week:
                    week_pct = _coerce_pct(week.get(key))
                    if week_pct is not None:
                        break
    if text:
        m = re.search(r"Current session:\s*(\d+)%", text, re.I)
        if m:
            session_pct = _coerce_pct(m.group(1))
        w = re.search(r"Current week \(all models\):\s*(\d+)%", text, re.I)
        if w:
            week_pct = _coerce_pct(w.group(1))
    return session_pct, week_pct


def _parse_claude(raw: str) -> tuple[Any, bool]:
    text = raw or ""
    data = _jsonish(text)
    remaining = normalize_usage_remaining(data)
    session_pct, _week_pct = _parse_claude_progress(data, text)
    if session_pct is not None:
        # A parsed session percentage is the answer. Do not second-guess it.
        limited = session_pct >= 100
    else:
        # Fallback only when nothing parsed, and only for a session line that
        # is itself at 100%. The old test was `"100%" in text and "session" in
        # text`, so ANY 100% in the blob — a per-model weekly cap sitting
        # beside a session at 8% — refused every send to that harness (live
        # 2026-09-03: blocked the whole receive path on any machine with
        # Claude Code installed).
        limited = bool(re.search(r"session[^\n%]{0,40}?100\s*%", text, re.I))
    return remaining, limited


def probe(harness: str, runner: ProbeFn | None = None) -> dict[str, Any]:
    if runner is not None:
        return runner(harness)
    name = (harness or "").strip().lower()
    name = _ALIASES.get(name, name)
    if name in ("grok-bot", "grok_bot"):
        # Public OSS contract: conductor probe hook exists, but has no live
        # Cursor billing scraper in this repository yet.
        return {
            "usage_remaining": None,
            "week_pct": None,
            "resets_at": None,
            "on_demand_spent": None,
            "on_demand_limit": None,
            "limited": False,
            "raw": None,
        }
    if name == "grok":
        return {"usage_remaining": None, "limited": False, "raw": None}
    if name == "claude":
        bin = shutil.which("claude") or "claude"
        code, raw = _run([bin, "-p", "/usage"], timeout=15)
        remaining, limited = _parse_claude(raw)
        return {"usage_remaining": remaining, "limited": limited, "raw": raw or None, "exit_code": code}
    if name == "codex":
        bin = shutil.which("codex") or "codex"
        code, raw = _run([bin, "exec", "/status"], timeout=15)
        low = (raw or "").lower()
        timed_out = code == 124 or low == "probe timeout"
        # A probe that TIMED OUT measured nothing. Unknown is null; it is not
        # "out of quota". Treating it as limited refused every send to a codex
        # chair on this machine for a full day (live 2026-09-03: the codex
        # probe times out here, so the neuron could never be reached at all).
        # If the vendor really is out of credits it says so, and it will
        # refuse the work itself - that refusal is evidence, ours was a guess.
        limited = "out of credits" in low
        remaining = None if (limited or timed_out) else normalize_usage_remaining(raw)
        return {"usage_remaining": remaining, "limited": limited, "raw": raw or None,
                "exit_code": code, "probe_timed_out": timed_out,
                "quota": None if timed_out else ("exhausted" if limited else "available")}
    return {"usage_remaining": None, "limited": False, "raw": None}


def surface(harness: str, probed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact per-harness usage for seats/chips. Never invent 0. Grok has no meter."""
    name = (harness or "").strip().lower()
    p = probed if probed is not None else probe(harness)
    if name == "grok":
        return {"usage_remaining": None, "limited": False}
    out: dict[str, Any] = {
        "limited": bool(p.get("limited")),
        "usage_remaining": normalize_usage_remaining(p.get("usage_remaining")),
    }
    raw = p.get("raw")
    if raw is None:
        raw = p.get("usage_remaining")
    text = raw if isinstance(raw, str) else json.dumps(raw) if raw is not None else ""
    session_pct, week_pct = _parse_claude_progress(out["usage_remaining"], text)
    if session_pct is not None:
        out["session_pct"] = session_pct
    if week_pct is not None:
        out["week_pct"] = week_pct
    if name == "grok":
        out["usage_remaining"] = None
    return out



class CachedProbe:
    """A probe_fn for long-lived readers (the widget): never blocks the caller.

    The first ask for a harness returns {usage_remaining: null, limited: false,
    probing: true} and starts ONE background probe; later asks return the
    cached vendor answer until ttl_s passes, then refresh once in the
    background again. Live 2026-09-05: codex's probe times out at ~17 s and
    claude's takes ~10 s, so probing on the paint path froze the strip for
    30 s at start and on every tick. Unknown stays null, never 0.
    """

    def __init__(self, probe_fn: ProbeFn | None = None, *, ttl_s: float = 60.0,
                 clock=None, start_thread=None):
        import threading
        import time as _t
        self._probe = probe_fn or probe
        self._ttl = float(ttl_s)
        self._clock = clock or _t.monotonic
        self._start = start_thread or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._inflight: set[str] = set()

    def _refresh(self, name: str) -> None:
        try:
            got = self._probe(name)
        except Exception as e:  # a failed probe is unknown, never a number
            got = {"usage_remaining": None, "limited": False, "raw": None, "error": type(e).__name__}
        with self._lock:
            self._cache[name] = (self._clock(), dict(got))
            self._inflight.discard(name)

    def __call__(self, harness: str) -> dict[str, Any]:
        name = (harness or "").strip().lower()
        with self._lock:
            hit = self._cache.get(name)
            stale = hit is None or (self._clock() - hit[0]) >= self._ttl
            kick = stale and name not in self._inflight
            if kick:
                self._inflight.add(name)
        if kick:
            self._start(lambda: self._refresh(name))
        if hit is None:
            return {"usage_remaining": None, "limited": False, "raw": None, "probing": True}
        return dict(hit[1])
