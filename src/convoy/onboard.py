"""Onboard declared harnesses after MCP attach. BYO harness, no wraps."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .bringup import ensure_first_run, ensure_interactive_path
from .convoy import bind, ensure_id, read_github, read_id, read_lead, read_thread, set_github, set_lead
from .harness_contract import canonical_harness_id, harness_entries
from .install import HARNESSES, _which
from .repo import Runner, checkout_path_for, clone, is_repo_url
from .usage import normalize_usage_remaining, probe

REFUSED_HARNESSES = frozenset({
    "gemini",
    "gemini-cli",
    "grok-cli",
    "ultracode-shim",
    "ola-brain",
})
SUPPORTED_HARNESSES = tuple(row["id"] for row in harness_entries(mcp_supported_only=True))
SUPPORTED_SET = frozenset(SUPPORTED_HARNESSES)


class CloneFailed(Exception):
    """A URL checkout could not be cloned; carries the repo card (url, dest, error)."""

    def __init__(self, repo: dict[str, Any]):
        super().__init__(repo.get("error") or "git clone failed")
        self.repo = repo


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
            canon = canonical_harness_id(hid)
            if canon in REFUSED_HARNESSES:
                refused.append(hid)
                continue
            if canon not in SUPPORTED_SET:
                unknown.append(hid)
                continue
            named.append(canon)
    return _dedupe(named), _dedupe(unknown), _dedupe(refused)


def _resolve_root(root: Path, checkout_root: str | None,
                  clone_runner: Runner | None = None) -> tuple[Path, bool, dict[str, Any] | None]:
    """A path must already exist. A URL (the wizard's 'repository path or
    URL', SKILL.md step 2) is cloned into the Convoy-owned checkout root,
    <CONVOY_HOME>/checkouts/<owner>/<repo>; an existing clone there is reused.
    A failed clone raises before anything is bound."""
    if checkout_root is None:
        return Path(root).resolve(), False, None
    if is_repo_url(checkout_root):
        dest = checkout_path_for(checkout_root)
        repo: dict[str, Any] = {"url": checkout_root.strip(), "dest": str(dest), "cloned": False}
        if not (dest / ".git").exists():
            card = clone(repo["url"], dest, runner=clone_runner)
            if not card.get("ok"):
                # A failed clone (no gh auth, offline, not found) binds NOTHING:
                # a thread bound on a failed clone is a silent write. The "soft
                # continue-local" the design asks for (2026-09-05) is an ASK on
                # the refusal card: the exact onboard that binds this root with
                # github=no, for the human to run. No owner/repo is invented.
                repo["error"] = str(card.get("error") or "git clone failed")
                raise CloneFailed(repo)
            repo["cloned"] = True
        return dest.resolve(), True, repo
    target = Path(checkout_root).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("checkout_root missing: " + str(target))
    return target, True, None


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


def _install_hint(hid: str) -> dict[str, Any] | None:
    if hid not in HARNESSES:
        return None
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
    out["identity_written"] = bool(row.get("identity_written"))
    if row.get("identity_paths"):
        out["identity_paths"] = row["identity_paths"]
    if row.get("identity_agents"):
        out["identity_agents"] = row["identity_agents"]
    out["agent_written"] = bool(row.get("agent_written"))
    if row.get("agent_path"):
        out["agent_path"] = row["agent_path"]
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
        hint = _install_hint(hid)
        if hint is not None:
            out["install"] = hint
    return out


def onboard(
    root: Path,
    harnesses: Iterable[str],
    *,
    thread: str | None = None,
    checkout_root: str | None = None,
    github: bool | None = None,
    clone_runner: Runner | None = None,
) -> dict[str, Any]:
    named, unknown, refused = _normalize_harnesses(harnesses)
    if not named:
        return {
            "ok": False,
            "error": "name at least one harness you already have",
            "allowed": list(SUPPORTED_HARNESSES),
        }
    if unknown or refused:
        return {
            "ok": False,
            "error": "refuse unknown or wrapped harness",
            "allowed": list(SUPPORTED_HARNESSES),
            "unknown": unknown,
            "refused": refused,
        }

    try:
        target_root, declared_checkout, repo = _resolve_root(root, checkout_root, clone_runner)
    except CloneFailed as e:
        failed = e.repo
        local = Path(root).resolve()
        return {
            "ok": False,
            "error": failed["error"],
            "repo": failed,
            "github": None,
            "root": None,
            "ask": {
                "continue_local": True,
                "text": "the clone failed, so nothing was bound. Continue on this machine instead? That binds "
                        + str(local) + " to thread " + repr(thread) + " with github=no.",
                "next": "onboard --to " + " --to ".join(named) + (" --thread " + thread if thread else "")
                        + " --checkout-root " + str(local) + " --github no",
            },
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    path_card = ensure_interactive_path()
    convoy_id, bound_thread, bind_status = _thread_bind(target_root, thread)
    if bind_status.get("error"):
        # Refused: this root belongs to another thread. Nothing below is
        # written onto it, the GitHub answer included (review 2026-09-04).
        return {
            "ok": False,
            "error": str(bind_status["error"]),
            "convoy_id": convoy_id,
            "thread": bound_thread,
            "thread_bind": bind_status,
            "root": str(target_root),
            "path": path_card,
        }
    # A URL is a GitHub answer in itself; otherwise record only what was said.
    if repo is not None or github is not None:
        set_github(target_root, True if repo is not None else bool(github))
    if declared_checkout and convoy_id is None:
        convoy_id = ensure_id(target_root)
    # Frame 1 of the happy path: whoever launched first conducts. The first
    # harness named on the FIRST onboard of this root becomes lead; a later
    # onboard reports the standing lead and never steals it (lead passes are
    # neuron-authored via `lead --to <chair> --as`).
    standing = read_lead(target_root) if convoy_id is not None else None
    if standing is None and convoy_id is not None:
        lead_card = {"harness": set_lead(target_root, named[0])["lead"], "set": True}
    else:
        lead_card = {"harness": standing, "set": False}

    harness_cards = [_harness_card(hid, target_root, declared_checkout) for hid in named]
    missing = [h["to"] for h in harness_cards if not h.get("present")]
    return {
        "ok": True,
        "convoy_id": convoy_id,
        "thread": bound_thread,
        "thread_bind": bind_status,
        "root": str(target_root),
        "github": read_github(target_root),
        "lead": lead_card,
        "repo": repo,
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
