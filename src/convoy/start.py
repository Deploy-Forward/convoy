"""Thin `convoy start [<repo>]`: clone / onboard / picker / attach. Never bring_up."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .convoy import attach, read_id
from .index import recent
from .install import _which
from .onboard import SUPPORTED_HARNESSES, onboard
from .panes import bodies, identify
from .repo import checkout_path_for, is_repo_url, redact_credentials
from .start_card import TRUST_NOTE, build_start_card
from .project_resolve import _resolve_target as resolve_target, update_checkout

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


def start(root: Path, repo: str | None = None, **kwargs) -> dict[str, Any]:
    """Sanitize every public field, including nested onboarding error cards."""
    return redact_credentials(_start(root, repo, **kwargs))


def _start(
    root: Path,
    repo: str | None = None,
    *,
    harnesses: Iterable[str] | None = None,
    thread: str | None = None,
    cancel: bool = False,
    clone_runner=None,
    identify_fn: IdentifyFn | None = None,
    bodies_fn: BodiesFn | None = None,
    write_repo_files: bool = False,
    search_roots=None,
    git_runner=None,
    gh_runner=None,
    scan_budget: float = 5.0,
    create: bool = False,
    all_worktrees: bool = False,
) -> dict[str, Any]:
    """Compose existing verbs. Never auto-picks newest. Never bring_up. Writes nothing into the
    repo outside .convoy/ unless write_repo_files (see onboard)."""
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
    resolution = resolve_target(want, search_roots=search_roots, git_runner=git_runner,
                                gh_runner=gh_runner, scan_budget=scan_budget, create=create, all_worktrees=all_worktrees)
    if not resolution.get("ok"):
        return {**resolution, "bound": False, "brought_up": False}
    want = resolution["checkout"]
    github = bool(resolution["github"])

    try:
        existing = checkout_path_for(want) if is_repo_url(want) else Path(want).expanduser().resolve()
    except ValueError as e:
        return {"ok": False, "error": str(e), "bound": False, "brought_up": False}

    notes = [] if write_repo_files else [TRUST_NOTE]
    if resolution.get("note"):
        notes.append(resolution["note"])
    pulled = update_checkout(existing, runner=git_runner) if resolution["refresh"] and (existing / ".git").exists() else {"pulled": "kept: no network for explicit/local-only path"}
    notes.append("pulled: " + pulled["pulled"])
    def annotate(card):
        card["resolution"] = resolution
        card.update(pulled)
        if resolution.get("note"):
            card["local_note"] = resolution["note"]
        return card
    if existing.exists() and read_id(existing) is not None and _live_on_root(existing, who, roster):
        card = attach(existing)
        card["attached"] = True
        card["brought_up"] = False
        card["start_card"] = build_start_card(existing, notes=notes)
        return annotate(card)

    card = onboard(
        Path(root),
        named,
        thread=thread,
        checkout_root=want,
        github=github,
        clone_runner=clone_runner,
        write_repo_files=write_repo_files,
    )
    card["brought_up"] = False
    if card.get("ok") and read_id(Path(str(card.get("root") or root))) is not None:
        dest = Path(str(card["root"]))
        if card.get("repo", {}) and card["repo"].get("cloned") and resolution["refresh"]:
            pulled = update_checkout(dest, runner=git_runner)
            notes[-1] = "pulled: " + pulled["pulled"]
        notes = notes + _first_run_notes(card)
        if _live_on_root(dest, who, roster):
            attached = attach(dest)
            attached["attached"] = True
            attached["brought_up"] = False
            attached["onboard"] = card
            attached["start_card"] = build_start_card(dest, notes=notes)
            return annotate(attached)
        card["start_card"] = build_start_card(dest, notes=notes)
    return annotate(card)


def _first_run_notes(card: dict[str, Any]) -> list[str]:
    """One note per kind across every harness: what the first runs could not exclude, and the files
    they wrote that git still shows (a file the person could own is never hidden)."""
    errors, visible = [], set()
    for harness in card.get("harnesses") or []:
        first = harness.get("first_run") or {}
        if first.get("exclude_error") and first["exclude_error"] not in errors:
            errors.append(first["exclude_error"])
        visible.update(first.get("left_visible") or [])
    notes = ["info/exclude not written: " + str(e) for e in errors]
    if visible:
        notes.append("written and left visible to git: " + ", ".join(sorted(visible)))
    return notes
