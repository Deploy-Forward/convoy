"""The repository step: gh lists, git clones, git mints one worktree per seat.

Every shell call goes through a runner argument (default: subprocess) so the
suite never reaches GitHub. Unknown is null: a missing gh is ok=false with an
install hint, never a guessed list; a non-zero exit carries the tool's own
stderr, never an invented reason.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

Runner = Callable[..., subprocess.CompletedProcess]

# live 2026-09-04: gh version 2.83.2 `gh repo list [<owner>] [flags]`,
# `--json fields  Output JSON with the specified fields`,
# `-L, --limit int  Maximum number of repositories to list (default 30)`;
# JSON FIELDS lists nameWithOwner, url, isPrivate, updatedAt.
LIST_FIELDS = "nameWithOwner,url,isPrivate,updatedAt"
GH_INSTALL_HINT = "install GitHub CLI from https://cli.github.com, then `gh auth login`"
# Written to <checkout>/.git/info/exclude so the bind never becomes a tracked
# file of the user's repo. info/exclude is git's per-clone ignore, not content.
EXCLUDE_LINES = (".convoy/", "thread.md")


def run_argv(argv: list[str], cwd: str | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout)


def checkouts_root() -> Path:
    """Convoy-owned checkout root, beside the thread index (index.py:27)."""
    home = os.environ.get("CONVOY_HOME")
    base = Path(home) if home else Path.home() / ".convoy"
    return base / "checkouts"


def is_repo_url(text: str | None) -> bool:
    t = (text or "").strip()
    return "://" in t or t.startswith("git@")


def checkout_path_for(url: str) -> Path:
    """<checkouts_root>/<owner>/<repo> from an https or scp-style git URL."""
    t = url.strip()
    tail = t.split("://", 1)[1] if "://" in t else t.split(":", 1)[-1]
    parts = [p for p in tail.replace("\\", "/").split("/") if p]
    if "://" in t:
        parts = parts[1:]  # drop the host
    if len(parts) < 2:
        raise ValueError("cannot derive owner/repo from url: " + t)
    owner, repo = parts[-2], parts[-1].removesuffix(".git")
    for seg in parts[:-2] + [owner, repo]:
        if not seg or seg in (".", "..") or any(c in seg for c in ':*?"<>|'):
            raise ValueError("refuse url path segment: " + repr(seg))
    return checkouts_root() / owner / repo


def _fail(exc: BaseException) -> str:
    return type(exc).__name__ + ": " + str(exc)


def list_repos(runner: Runner | None = None, limit: int = 30) -> dict[str, Any]:
    run = runner or run_argv
    argv = ["gh", "repo", "list", "--json", LIST_FIELDS, "--limit", str(int(limit))]
    try:
        r = run(argv, None, timeout=60)
    except FileNotFoundError:
        return {"ok": False, "gh_present": False, "repos": None, "count": None,
                "error": "gh not found on PATH", "hint": GH_INSTALL_HINT}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "gh_present": None, "repos": None, "count": None, "error": _fail(exc)}
    if r.returncode != 0:
        return {"ok": False, "gh_present": True, "repos": None, "count": None,
                "error": "gh repo list exited " + str(r.returncode) + ": " + (r.stderr or "").strip()}
    try:
        raw = json.loads(r.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {"ok": False, "gh_present": True, "repos": None, "count": None, "error": _fail(exc)}
    rows = [{"name": x.get("nameWithOwner"), "url": x.get("url"), "private": x.get("isPrivate"),
             "updated_at": x.get("updatedAt")} for x in raw if isinstance(x, dict)]
    return {"ok": True, "gh_present": True, "repos": rows, "count": len(rows)}


def _exclude_convoy_files(dest: Path) -> bool:
    info = dest / ".git" / "info"
    if not info.is_dir():
        return False
    path = info / "exclude"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    missing = [line for line in EXCLUDE_LINES if line not in text.splitlines()]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "".join(line + "\n" for line in missing), encoding="utf-8")
    return True


def clone(url: str, dest: Path | str, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or run_argv
    target = Path(dest)
    card: dict[str, Any] = {"ok": False, "url": url, "dest": str(target), "cloned": False}
    if target.exists() and any(target.iterdir()):
        card["error"] = "dest is not empty: " + str(target)
        return card
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = run(["git", "clone", url, str(target)], None)
    except (OSError, subprocess.SubprocessError) as exc:
        card["error"] = _fail(exc)
        return card
    if r.returncode != 0:
        card["error"] = "git clone exited " + str(r.returncode) + ": " + (r.stderr or "").strip()
        return card
    card["ok"] = True
    card["cloned"] = True
    card["excluded"] = _exclude_convoy_files(target)
    return card


def mint_worktrees(checkout: Path | str, n: int, names: list[str] | None = None,
                   runner: Runner | None = None) -> dict[str, Any]:
    """One worktree per seat, DERIVED from the checkout: a sibling directory
    <checkout>-wt-<name> on branch convoy/<name>, the way this repo's own
    worktrees are laid out (convoy-wt-fable). Stops at the first git failure
    and reports what was minted; an existing sibling is reused, not re-added."""
    run = runner or run_argv
    base = Path(checkout)
    count = int(n)
    seat_names = list(names) if names is not None else ["neuron-" + str(i + 1) for i in range(count)]
    card: dict[str, Any] = {"ok": False, "checkout": str(base), "worktrees": []}
    if count < 1:
        card["error"] = "n must be at least 1"
        return card
    if len(seat_names) != count:
        card["error"] = "names has " + str(len(seat_names)) + " entries for n=" + str(count)
        return card
    if not (base / ".git").exists():
        card["error"] = "not a git checkout: " + str(base)
        return card
    for name in seat_names:
        path = base.parent / (base.name + "-wt-" + name)
        branch = "convoy/" + name
        row = {"name": name, "path": str(path), "branch": branch, "created": False}
        if (path / ".git").exists():
            card["worktrees"].append(row)
            continue
        try:
            r = run(["git", "-C", str(base), "worktree", "add", "-b", branch, str(path)], None)
        except (OSError, subprocess.SubprocessError) as exc:
            card["error"] = _fail(exc)
            return card
        if r.returncode != 0:
            card["error"] = "git worktree add exited " + str(r.returncode) + ": " + (r.stderr or "").strip()
            return card
        row["created"] = True
        card["worktrees"].append(row)
    card["ok"] = True
    return card
