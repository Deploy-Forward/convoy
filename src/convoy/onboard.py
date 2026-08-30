"""Onboard declared harnesses after MCP attach. BYO harness, no wraps."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .bringup import ensure_first_run, ensure_interactive_path
from .convoy import bind, ensure_id, read_id, read_thread
from .install import HARNESSES, _which
from .usage import normalize_usage_remaining, probe

REFUSED_HARNESSES = frozenset({
    "gemini",
    "gemini-cli",
    "grok-cli",
    "ultracode-shim",
    "ola-brain",
})


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for val in values:
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _normalize_harnesses(harnesses: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
    named: list[str] = []
    unknown: list[str] = []
    refused: list[str] = []
    for raw in harnesses:
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if not text:
            continue
        for piece in text.replace(",", " ").split():
            hid = piece.strip().lower()
            if not hid:
                continue
            if hid in REFUSED_HARNESSES:
                refused.append(hid)
                continue
            if hid not in HARNESSES:
                unknown.append(hid)
                continue
            named.append(hid)
    return _dedupe(named), _dedupe(unknown), _dedupe(refused)


def _resolve_root(root: Path, checkout_root: str | None) -> tuple[Path, bool]:
    if checkout_root is None:
        return Path(root).resolve(), False
    target = Path(checkout_root).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("checkout_root missing: " + str(target))
    return target, True


def _thread_bind(root: Path, thread: str | None) -> tuple[str | None, str | None, dict[str, Any]]:
    requested = (thread or "").strip() or None
    bound = read_thread(root)
    convoy_id = read_id(root)
    status: dict[str, Any] = {
        "requested": requested,
        "bound": bound,
        "changed": False,
    }
    if requested is None:
        return convoy_id, bound, status
    if bound is not None and bound != requested:
        status["error"] = "thread already bound to " + bound
        return convoy_id, bound, status
    if bound is None:
        row = bind(root, requested)
        convoy_id = row["convoy_id"]
        bound = row["thread"]
        status["bound"] = bound
        status["changed"] = True
        return convoy_id, bound, status
    if convoy_id is None:
        convoy_id = ensure_id(root)
    return convoy_id, bound, status


def _install_hint(hid: str) -> dict[str, Any]:
    spec = HARNESSES[hid]
    return {
        "tool": "install",
        "to": hid,
        "dry_run_default": True,
        "opt_in_required": True,
        "page": spec.get("page"),
        "host": spec.get("host"),
    }


def _first_run_card(hid: str, root: Path) -> dict[str, Any]:
    row = ensure_first_run({"to": hid, "worktree": str(root)})
    out: dict[str, Any] = {
        "prepared": bool(row.get("prepared")),
        "wrote": bool(row.get("wrote")),
        "settings": row.get("settings"),
        "home_written": bool(row.get("home_written")),
        "settings_home": row.get("settings_home"),
    }
    if row.get("error"):
        out["error"] = row["error"]
    return out


def _harness_card(hid: str, target_root: Path, run_first_run: bool) -> dict[str, Any]:
    path = _which(hid)
    present = path is not None
    usage_remaining = None
    limited = False
    availability = "missing"
    if present:
        probed = probe(hid)
        usage_remaining = normalize_usage_remaining(probed.get("usage_remaining"))
        if usage_remaining == 0 and probed.get("raw") is None:
            usage_remaining = None
        limited = bool(probed.get("limited"))
        availability = "limited" if limited else "available"
    out: dict[str, Any] = {
        "to": hid,
        "present": present,
        "wired": bool(present),
        "path": path,
        "availability": availability,
        "usage_remaining": usage_remaining,
        "limited": limited,
    }
    if run_first_run:
        out["first_run"] = _first_run_card(hid, target_root)
    if not present:
        out["install"] = _install_hint(hid)
    return out


def onboard(
    root: Path,
    harnesses: Iterable[str],
    *,
    thread: str | None = None,
    checkout_root: str | None = None,
) -> dict[str, Any]:
    named, unknown, refused = _normalize_harnesses(harnesses)
    if not named:
        return {
            "ok": False,
            "error": "name at least one harness you already have",
            "allowed": list(HARNESSES.keys()),
        }
    if unknown or refused:
        return {
            "ok": False,
            "error": "refuse unknown or wrapped harness",
            "allowed": list(HARNESSES.keys()),
            "unknown": unknown,
            "refused": refused,
        }

    try:
        target_root, declared_checkout = _resolve_root(root, checkout_root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    path_card = ensure_interactive_path()
    convoy_id, bound_thread, bind_status = _thread_bind(target_root, thread)
    if bind_status.get("error"):
        return {
            "ok": False,
            "error": str(bind_status["error"]),
            "convoy_id": convoy_id,
            "thread": bound_thread,
            "thread_bind": bind_status,
            "root": str(target_root),
            "path": path_card,
        }
    if declared_checkout and convoy_id is None:
        convoy_id = ensure_id(target_root)

    harness_cards = [_harness_card(hid, target_root, declared_checkout) for hid in named]
    missing = [h["to"] for h in harness_cards if not h.get("present")]
    return {
        "ok": True,
        "convoy_id": convoy_id,
        "thread": bound_thread,
        "thread_bind": bind_status,
        "root": str(target_root),
        "named": named,
        "harnesses": harness_cards,
        "missing": missing,
        "path": path_card,
        "notes": {
            "byo_harness": True,
            "no_wrap": True,
            "vendor_login_required": True,
            "install_tool": "Use install with opt_in=true for missing named harnesses.",
        },
    }
