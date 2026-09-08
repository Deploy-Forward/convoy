"""cursor-agent's effort rides its model id, never a flag.

Live 2026-09-08 (cursor-agent 2026.08.11-e8db854, Pro+ login): the --help's
bracket override ('claude-opus-4-8[effort=high]') is refused by this build
("Cannot use this model"), and the refusal prints the account's catalog: 223
ids shaped <family>-<effort>[-fast], e.g. gpt-5.6-luna-high, gpt-5.6-luna-xhigh,
claude-opus-5-low, gpt-5.5-extra-high, muse-spark-1.3-minimal, gpt-5.6-sol-none.
`cursor-agent models` prints the same 223. So a declared effort is applied by
COMPOSING the id and checking it against that list; a name the vendor did not
list is never emitted (the seat keeps its bare model, effort recorded, not
applied).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

EFFORT_TOKENS = ("none", "minimal", "low", "medium", "high", "xhigh", "extra-high", "max")
_ALIASES = {"extra-high": ("xhigh", "extra-high"), "xhigh": ("xhigh", "extra-high")}
_CACHE_TTL_S = 3600.0
_cache: dict[str, Any] = {"at": 0.0, "ids": None}


def _cache_file() -> Path:
    home = os.environ.get("CONVOY_HOME") or str(Path.home() / ".convoy")
    return Path(home) / "cursor-agent-models.txt"


def parse_catalog(text: str) -> list[str]:
    """ids from `cursor-agent models` ("id - Display Name" per line)."""
    ids: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if " - " in line and not line.lower().startswith("available"):
            ids.append(line.split(" - ", 1)[0].strip())
    return ids


def read_catalog(runner: Callable[[list[str]], str] | None = None, *, now: float | None = None) -> list[str] | None:
    """The account's model ids, from CONVOY_CURSOR_MODELS_FILE (tests, offline),
    else the on-disk cache (1 h), else `cursor-agent models` live. None when
    nothing answers; Convoy never invents the list it checks against."""
    fixture = os.environ.get("CONVOY_CURSOR_MODELS_FILE")
    if fixture:
        try:
            return parse_catalog(Path(fixture).read_text(encoding="utf-8"))
        except OSError:
            return None
    t = now if now is not None else time.time()
    if _cache["ids"] is not None and t - _cache["at"] < _CACHE_TTL_S:
        return list(_cache["ids"])
    cf = _cache_file()
    try:
        if cf.is_file() and t - cf.stat().st_mtime < _CACHE_TTL_S:
            ids = parse_catalog(cf.read_text(encoding="utf-8"))
            if ids:
                _cache.update(at=t, ids=ids)
                return list(ids)
    except OSError:
        pass
    text = None
    if runner is not None:
        text = runner(["cursor-agent", "models"])
    else:
        exe = shutil.which("cursor-agent")
        if not exe:
            return None
        kw: dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            text = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=30, **kw).stdout
        except (OSError, subprocess.SubprocessError):
            return None
    ids = parse_catalog(text or "")
    if not ids:
        return None
    try:
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(text or "", encoding="utf-8")
    except OSError:
        pass
    _cache.update(at=t, ids=ids)
    return list(ids)


def has_effort_suffix(model: str) -> bool:
    m = model[:-5] if model.endswith("-fast") else model
    return any(m.endswith("-" + tok) for tok in EFFORT_TOKENS)


def compose(model: Any, effort: Any, catalog: list[str] | None) -> dict[str, Any]:
    """{model, applied, reason}. applied is None when no effort is declared,
    True when the composed id is in the catalog, False otherwise (bare model
    is emitted, effort stays recorded)."""
    m = str(model).strip() if isinstance(model, str) else ""
    e = str(effort).strip().lower() if isinstance(effort, str) else ""
    if not m:
        return {"model": None, "applied": None if not e else False, "reason": "no model declared"}
    if not e:
        return {"model": m, "applied": None, "reason": "no effort declared"}
    if has_effort_suffix(m):
        return {"model": m, "applied": m.endswith("-" + e) or m.endswith("-" + e + "-fast"),
                "reason": "the model id already carries an effort"}
    if catalog is None:
        return {"model": m, "applied": False, "reason": "cursor-agent catalog unavailable; bare model emitted"}
    fast = m.endswith("-fast")
    base = m[:-5] if fast else m
    for tok in _ALIASES.get(e, (e,)):
        cand = base + "-" + tok + ("-fast" if fast else "")
        if cand in catalog:
            return {"model": cand, "applied": True, "reason": "composed from the account's catalog"}
    return {"model": m, "applied": False, "reason": "no catalog id " + base + "-" + e + "; bare model emitted"}
