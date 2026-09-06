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
                **quiet_spawn_kwargs(),   # a probe timeout popped a 'taskkill' console every minute (live 2026-09-05)
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


_RESET = re.compile(r"(?:Current session|Current week[^:\n]*)?:?[^\n]*?\bResets?\s+(in|at)\s+([^\n)]+?)\s*\)?\s*$", re.I | re.M)


def parse_resets(text: str) -> dict[str, str | None]:
    """{'session': 'in 3h 53m', 'week': 'in 3d 20h'} from the vendor's own
    lines, verbatim; None when the text does not say. Never computed."""
    out: dict[str, str | None] = {"session": None, "week": None}
    for line in (text or "").splitlines():
        m = re.search(r"\bResets?\s+((?:in|at)\s+[^)\n]+)", line, re.I)
        if not m:
            continue
        when = m.group(1).strip()
        low = line.lower()
        if "week" in low and out["week"] is None:
            out["week"] = when
        elif "session" in low and out["session"] is None:
            out["session"] = when
        elif out["session"] is None:
            out["session"] = when
    return out


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
        # grok's TUI "Usage limit" tab is a billing fetch the shell logs into
        # ~/.grok/logs/unified.jsonl ("billing: fetched credits config",
        # ctx.config.creditUsagePercent + currentPeriod, grok-build
        # xai-grok-shell/src/extensions/billing.rs). Read the newest one.
        # grok has a WEEKLY cap only; its session tab is tokens and cost, not
        # a limit, so the session bar stays unknown with that reason.
        snap = grok_unified_billing()
        if snap is not None:
            return snap
        return {"usage_remaining": None, "limited": False, "raw": None}
    if name == "claude":
        bin = shutil.which("claude") or "claude"
        code, raw = _run([bin, "-p", "/usage"], timeout=15)
        remaining, limited = _parse_claude(raw)
        return {"usage_remaining": remaining, "limited": limited, "raw": raw or None, "exit_code": code}
    if name == "codex":
        # codex's /status is an in-TUI command ("stdin is not a terminal"
        # headless) and `codex exec /status` times out here, but codex writes
        # its rate limits into every session rollout it runs: read the newest
        # snapshot and say how old it is (live 2026-09-06, Marco: "check codex
        # status ... these reveal what's left").
        snap = codex_rollout_rate_limits()
        if snap is not None:
            return snap
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


def _find_rate_limits(node: Any, depth: int = 0) -> dict[str, Any] | None:
    """The first dict under key 'rate_limits' that has a 'primary' window,
    wherever codex nested it (payload.rate_limits, payload.info..., ...)."""
    if depth > 6 or not isinstance(node, dict):
        return None
    rl = node.get("rate_limits")
    if isinstance(rl, dict) and "primary" in rl:
        return rl
    for v in node.values():
        if isinstance(v, dict):
            found = _find_rate_limits(v, depth + 1)
            if found is not None:
                return found
    return None


def codex_rollout_rate_limits(home: "Path | None" = None, now: float | None = None) -> dict[str, Any] | None:
    """codex writes a `rate_limits` snapshot into every session rollout
    (~/.codex/sessions/**/rollout-*.jsonl): primary = the 5 h window,
    secondary = the weekly window, each with used_percent and resets_at. Its
    /status is TUI-only and codex itself warns its limits may be stale, so:

    - snapshots are grouped by their weekly resets_at (to the minute): two
      different reset instants on one machine are two codex LOGINS (live
      2026-09-06: Marco's Business login resets 09-12 07:46Z at 86% left while
      the login the codex chairs used resets 09-12 05:04Z at 0% left);
    - the freshest snapshot by ITS OWN timestamp is the headline, and every
      other login seen in the last 7 days rides along in `logins`;
    - every number carries its own timestamp and age. Nothing is derived.
    Returns None when no rollout carries a number."""
    import glob
    import time as _t
    from datetime import datetime, timezone
    from pathlib import Path as _P
    base = _P(home) if home is not None else _P(os.environ.get("CODEX_HOME") or (_P.home() / ".codex"))
    files = sorted(glob.glob(str(base / "sessions" / "**" / "rollout-*.jsonl"), recursive=True), key=os.path.getmtime, reverse=True)
    t_now = now if now is not None else _t.time()

    def pct(v: Any) -> int | None:
        try:
            x = int(round(float(v)))
        except (TypeError, ValueError):
            return None
        return x if 0 <= x <= 100 else None

    def at(v: Any) -> str | None:
        try:
            return datetime.fromtimestamp(float(v), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OSError):
            return None

    seen: list[dict[str, Any]] = []
    for path in files[:400]:
        if t_now - os.path.getmtime(path) > 14 * 86400:
            break
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rl = _find_rate_limits(row)
                    if not rl:
                        continue
                    prim = rl.get("primary") or {}
                    sec = rl.get("secondary") or {}
                    sp, wp = pct(prim.get("used_percent")), pct(sec.get("used_percent"))
                    if sp is None and wp is None:
                        continue
                    ts = str(row.get("timestamp") or row.get("ts") or "")
                    try:
                        snap_t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        snap_t = os.path.getmtime(path)
                        ts = datetime.fromtimestamp(snap_t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    try:
                        family = int(float(sec.get("resets_at") or 0)) // 60
                    except (TypeError, ValueError):
                        family = 0
                    seen.append({"t": snap_t, "ts": ts, "family": family, "session_pct": sp, "week_pct": wp,
                                 "resets": {"session": ("at " + at(prim.get("resets_at"))) if at(prim.get("resets_at")) else None,
                                            "week": ("at " + at(sec.get("resets_at"))) if at(sec.get("resets_at")) else None},
                                 "window_minutes": {"session": prim.get("window_minutes"), "week": sec.get("window_minutes")},
                                 "rollout": os.path.basename(path)})
        except OSError:
            continue
    if not seen:
        return None
    seen.sort(key=lambda x: x["t"], reverse=True)
    freshest_by_family: dict[int, dict[str, Any]] = {}
    for x in seen:
        freshest_by_family.setdefault(x["family"], x)
    head = seen[0]

    def card(x: dict[str, Any]) -> dict[str, Any]:
        limited = (x["session_pct"] is not None and x["session_pct"] >= 100) or (x["week_pct"] is not None and x["week_pct"] >= 100)
        return {"usage_remaining": {"session_pct": x["session_pct"], "week_pct": x["week_pct"]} if x["session_pct"] is not None else None,
                "session_pct": x["session_pct"], "week_pct": x["week_pct"], "resets": x["resets"], "limited": limited,
                "raw": None, "source": "codex rollout snapshot", "as_of": x["ts"], "age_s": round(max(0.0, t_now - x["t"])),
                "rollout": x["rollout"], "window_minutes": x["window_minutes"],
                "quota": "exhausted" if limited else "available"}

    out = card(head)
    others = [card(x) for fam, x in freshest_by_family.items() if fam != head["family"] and t_now - x["t"] <= 7 * 86400]
    out["logins"] = [{k: v for k, v in o.items() if k in ("session_pct", "week_pct", "resets", "limited", "as_of", "age_s")} for o in others]
    return out


def grok_unified_billing(home: "Path | None" = None, now: float | None = None) -> dict[str, Any] | None:
    """The newest `billing: fetched credits config` row in grok's unified log:
    creditUsagePercent (weekly, used) and currentPeriod.end (the reset), the
    subscription tier, stamped with the row's own ts and its age. None when
    the log or the row is absent. The number is the vendor's, never derived."""
    import time as _t
    from datetime import datetime, timezone
    from pathlib import Path as _P
    base = _P(home) if home is not None else _P(os.environ.get("GROK_HOME") or (_P.home() / ".grok"))
    path = base / "logs" / "unified.jsonl"
    if not path.is_file():
        return None
    last: dict[str, Any] | None = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "billing: fetched credits config" not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cfg = ((row.get("ctx") or {}).get("config")) or {}
                if isinstance(cfg, dict) and cfg.get("creditUsagePercent") is not None:
                    last = row
    except OSError:
        return None
    if last is None:
        return None
    ctx = last.get("ctx") or {}
    cfg = ctx.get("config") or {}
    try:
        used = int(round(float(cfg.get("creditUsagePercent"))))
    except (TypeError, ValueError):
        return None
    used = max(0, min(100, used))
    period = cfg.get("currentPeriod") or {}
    end = period.get("end") or cfg.get("billingPeriodEnd")
    ts = str(last.get("ts") or "")
    age = None
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = max(0.0, (now if now is not None else _t.time()) - when.timestamp())
    except ValueError:
        pass
    ptype = str(period.get("type") or "")
    window = "week" if "WEEK" in ptype.upper() or not ptype else "period"
    return {"usage_remaining": {"week_pct": used}, "session_pct": None, "week_pct": used,
            "resets": {"session": None, "week": ("at " + str(end)[:16].replace("T", " ") + "Z") if end else None},
            "limited": used >= 100, "raw": None, "source": "grok billing log", "as_of": ts or None,
            "age_s": round(age) if age is not None else None, "tier": ctx.get("subscriptionTier"),
            "window": window, "session_cap": False, "quota": "exhausted" if used >= 100 else "available"}


def surface(harness: str, probed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact per-harness usage for seats/chips. Never invent 0. Grok has no meter."""
    name = (harness or "").strip().lower()
    p = probed if probed is not None else probe(harness)
    if name == "grok" and not p.get("source"):
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
    if session_pct is None and isinstance(p.get("session_pct"), int):
        session_pct = p["session_pct"]
    if week_pct is None and isinstance(p.get("week_pct"), int):
        week_pct = p["week_pct"]
    if session_pct is not None:
        out["session_pct"] = session_pct
    if week_pct is not None:
        out["week_pct"] = week_pct
    resets = parse_resets(text)
    if isinstance(p.get("resets"), dict):
        resets = {"session": p["resets"].get("session") or resets["session"], "week": p["resets"].get("week") or resets["week"]}
    if resets["session"] or resets["week"]:
        out["resets"] = resets
    for k in ("source", "as_of", "age_s", "logins"):
        if p.get(k) is not None:
            out[k] = p[k]
    if p.get("probe_timed_out"):
        out["probe_timed_out"] = True
    if p.get("error"):
        out["error"] = p.get("error")
    if name == "grok" and not p.get("source"):
        out["usage_remaining"] = None
    for k in ("tier", "session_cap", "window"):
        if p.get(k) is not None:
            out[k] = p[k]
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
