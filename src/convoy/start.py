"""Thin `convoy start [<repo>]`: clone / onboard / picker / attach. Never bring_up."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .convoy import attach, read_id
from .index import recent
from .install import _which
from .onboard import SUPPORTED_HARNESSES, onboard
from .panes import bodies, identify
from .repo import checkout_path_for, is_repo_url

IdentifyFn = Callable[[Path], dict[str, Any]]
BodiesFn = Callable[[Path], dict[str, Any]]
PICKER_LIMIT = 20


def _picker_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": r.get("thread") or "(unbound)",
        "thread": r.get("thread"),
        "root": r.get("root"),
        "updated_at": r.get("updated_at"),
        "convoy_id": r.get("convoy_id"),
    }


def _default_harnesses() -> list[str]:
    return [h for h in SUPPORTED_HARNESSES if _which(h)]


def _live_on_root(root: Path, identify_fn: IdentifyFn, bodies_fn: BodiesFn) -> bool:
    if read_id(root) is None:
        return False
    me = identify_fn(root)
    if me.get("chair"):
        return True
    roster = bodies_fn(root)
    return any(bool(c.get("live")) for c in (roster.get("chairs") or []))


def start(
    root: Path,
    repo: str | None = None,
    *,
    harnesses: Iterable[str] | None = None,
    thread: str | None = None,
    cancel: bool = False,
    clone_runner=None,
    identify_fn: IdentifyFn | None = None,
    bodies_fn: BodiesFn | None = None,
) -> dict[str, Any]:
    """Compose existing verbs. Never auto-picks newest. Never bring_up."""
    if cancel:
        return {"ok": True, "bound": False, "ask": "cancelled", "brought_up": False}

    who = identify_fn or identify
    roster = bodies_fn or bodies
    want = (repo or "").strip() or None
    if want is None:
        rows = [_picker_row(r) for r in recent(PICKER_LIMIT)]
        if not rows:
            return {
                "ok": False,
                "ask": "new thread",
                "threads": [],
                "bound": False,
                "brought_up": False,
                "error": "no present threads; pass a repo path or git URL to start a new one",
            }
        return {
            "ok": False,
            "ask": "pick",
            "threads": rows,
            "bound": False,
            "brought_up": False,
            "next": "start <root-or-url>",
            "error": "pick a thread from threads[] (never auto-picked)",
        }

    if want.startswith("-"):
        return {"ok": False, "error": "refuse url starting with '-': " + want,
                "bound": False, "brought_up": False}

    named = list(harnesses) if harnesses is not None else _default_harnesses()
    github = bool(is_repo_url(want))

    try:
        existing = checkout_path_for(want) if github else Path(want).expanduser().resolve()
    except ValueError as e:
        return {"ok": False, "error": str(e), "bound": False, "brought_up": False}

    if existing.exists() and read_id(existing) is not None and _live_on_root(existing, who, roster):
        card = attach(existing)
        card["attached"] = True
        card["brought_up"] = False
        return card

    card = onboard(
        Path(root),
        named,
        thread=thread,
        checkout_root=want,
        github=github,
        clone_runner=clone_runner,
    )
    card["brought_up"] = False
    if card.get("ok") and read_id(Path(str(card.get("root") or root))) is not None:
        dest = Path(str(card["root"]))
        if _live_on_root(dest, who, roster):
            attached = attach(dest)
            attached["attached"] = True
            attached["brought_up"] = False
            attached["onboard"] = card
            return attached
    return card
