"""Live harness usage probes. Never invent 0. Grok has no usage limit."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable

ProbeFn = Callable[[str], dict[str, Any]]


def normalize_usage_remaining(value: Any) -> Any:
    """Allow only number|object|null for surfaced usage_remaining."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return value
    return None


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
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
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

def _parse_claude(raw: str) -> tuple[Any, bool]:
    text = raw or ""
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                data = None
    pct = None
    if isinstance(data, dict):
        for key in ("session_pct", "session_percent", "pct"):
            if key in data:
                try:
                    pct = float(data[key])
                except (TypeError, ValueError):
                    pct = None
                break
        sess = data.get("session") if isinstance(data.get("session"), dict) else None
        if pct is None and sess is not None:
            for key in ("pct", "percent", "used"):
                if key in sess:
                    try:
                        pct = float(sess[key])
                    except (TypeError, ValueError):
                        pct = None
                    break
        remaining: Any = data
    else:
        remaining = text or None
        m = re.search(r"Current session:\s*(\d+)%", text, re.I)
        if m:
            pct = float(m.group(1))
        elif "100%" in text.lower() and "session" in text.lower():
            pct = 100.0
    limited = pct == 100 or pct == 100.0
    return remaining, limited

def probe(harness: str, runner: ProbeFn | None = None) -> dict[str, Any]:
    if runner is not None:
        return runner(harness)
    name = (harness or "").strip().lower()
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
        limited = timed_out or ("out of credits" in low)
        remaining = None if limited or not raw else raw
        return {"usage_remaining": remaining, "limited": limited, "raw": raw or None, "exit_code": code}
    return {"usage_remaining": None, "limited": False, "raw": None}

def surface(harness: str, probed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact per-harness usage for seats/chips. Never invent 0. Grok has no meter."""
    name = (harness or "").strip().lower()
    p = probed if probed is not None else probe(harness)
    if name == "grok":
        return {"usage_remaining": None, "limited": False}
    out: dict[str, Any] = {"limited": bool(p.get("limited")), "usage_remaining": None}
    raw = p.get("raw")
    if raw is None:
        raw = p.get("usage_remaining")
    blob = raw if isinstance(raw, str) else json.dumps(raw) if raw is not None else ""
    m = re.search(r"Current session:\s*(\d+)%", blob, re.I)
    w = re.search(r"Current week \(all models\):\s*(\d+)%", blob, re.I)
    if m:
        out["session_pct"] = int(m.group(1))
    if w:
        out["week_pct"] = int(w.group(1))
    if name == "codex":
        out["usage_remaining"] = normalize_usage_remaining(p.get("usage_remaining"))
    return out

