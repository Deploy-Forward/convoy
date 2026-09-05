"""Git commit provenance on the Convoy thread feed.

Commit rows are part of the existing append-only feed.  There is no second
history store: this module resolves Git facts, then delegates the write to
``layer.hook`` just like every other thread event.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .convoy import list_seats
from .convoy import read_id
from .layer import feed_path, hook, parse_since


COMMIT_ROW_KEYS = (
    "ts",
    "kind",
    "instance_id",
    "from",
    "summary",
    "branch",
    "sha",
    "parent",
    "files",
    "worktree",
)


def _git(worktree: Path | str, *args: str) -> tuple[int, str]:
    """Run Git and retain its return code even when stdout is empty.

    ``gitstate._run`` deliberately maps both cases to ``None``.  Provenance
    must instead distinguish an empty successful diff (``files: []``) from a
    failed ``diff-tree`` (``files: null``).
    """
    try:
        run = subprocess.run(
            ["git", *args],
            cwd=str(Path(worktree)),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return run.returncode, (run.stdout or "").strip()


def _feed_rows(root: Path | str) -> list[dict[str, Any]]:
    """Read valid feed rows without making a malformed fragment authoritative."""
    path = feed_path(Path(root))
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _known_chair(root: Path | str, chair: str) -> bool:
    return any(row.get("session_id") == chair for row in list_seats(Path(root)))


def commit_rows(root: Path | str, *, since: str | None = None) -> list[dict[str, Any]]:
    """Return valid commit rows, optionally inside a Convoy time window."""
    since_iso = parse_since(since) if since is not None else None
    rows = [row for row in _feed_rows(root) if row.get("kind") == "commit"]
    if since_iso is not None:
        rows = [row for row in rows if str(row.get("ts") or "") >= since_iso]
    return rows


def build_provenance(root: Path | str, *, since: str | None = None) -> dict[str, Any]:
    """Fold seats plus commit rows into one read-only per-chair view."""
    root_path = Path(root)
    cid = read_id(root_path)
    if cid is None:
        return {
            "ok": False,
            "convoy_id": None,
            "since": since,
            "provenance": [],
            "error": "no thread at " + str(root_path),
        }

    chairs: dict[str, dict[str, Any]] = {}
    touched: dict[str, set[str]] = {}
    for seat in list_seats(root_path, convoy_id=cid):
        chair = str(seat.get("session_id") or "").strip()
        if not chair:
            continue
        worktree = str(seat.get("worktree") or "").strip() or None
        chairs[chair] = {
            "chair": chair,
            "harness": str(seat.get("to") or "").strip() or None,
            "worktree": worktree,
            "branch": None,
            "sha": None,
            "last_commit_ts": None,
            "commits": 0,
            "files_touched": [],
        }
        touched[chair] = set()

    for row in commit_rows(root_path, since=since):
        chair = str(row.get("instance_id") or row.get("from") or "").strip()
        if not chair:
            continue
        if chair not in chairs:
            chairs[chair] = {
                "chair": chair,
                "harness": None,
                "worktree": str(row.get("worktree") or "").strip() or None,
                "branch": None,
                "sha": None,
                "last_commit_ts": None,
                "commits": 0,
                "files_touched": [],
            }
            touched[chair] = set()
        card = chairs[chair]
        card["commits"] += 1
        ts = str(row.get("ts") or "") or None
        if card["last_commit_ts"] is None or (ts is not None and ts >= card["last_commit_ts"]):
            card["last_commit_ts"] = ts
            card["branch"] = str(row.get("branch") or "").strip() or None
            card["sha"] = str(row.get("sha") or "").strip() or None
            row_worktree = str(row.get("worktree") or "").strip() or None
            if row_worktree is not None:
                card["worktree"] = row_worktree
        files = row.get("files")
        if isinstance(files, list):
            touched[chair].update(str(path) for path in files if isinstance(path, str) and path)

    for chair, card in chairs.items():
        card["files_touched"] = sorted(touched[chair])
    return {
        "ok": True,
        "convoy_id": cid,
        "since": since,
        "provenance": [chairs[chair] for chair in sorted(chairs)],
    }


def record_commit(
    root: Path | str,
    chair: str,
    *,
    rev: str = "HEAD",
    worktree: Path | str | None = None,
) -> dict[str, Any]:
    """Resolve ``rev`` and append exactly one ``kind=commit`` row."""
    root_path = Path(root)
    author = str(chair or "").strip()
    if not author:
        raise ValueError("refuse committed without a chair")
    if not _known_chair(root_path, author):
        raise ValueError("refuse committed for unknown chair " + author)

    tree = Path(worktree or Path.cwd()).resolve()
    rc, sha_out = _git(tree, "rev-parse", "--verify", f"{rev}^{{commit}}")
    sha = sha_out.splitlines()[0].strip() if rc == 0 and sha_out else ""
    if not sha:
        raise ValueError("refuse committed without a sha for rev " + repr(rev))

    for row in _feed_rows(root_path):
        if row.get("kind") == "commit" and row.get("instance_id") == author and row.get("sha") == sha:
            return {"ok": True, "duplicate": True, "row": row}

    branch_rc, branch_out = _git(tree, "branch", "--show-current")
    branch = branch_out or None if branch_rc == 0 else None

    parent_rc, parent_out = _git(tree, "rev-list", "--parents", "-n", "1", sha)
    parent: str | None = None
    if parent_rc == 0 and parent_out:
        parts = parent_out.split()
        if len(parts) > 1:
            parent = parts[1]

    files_rc, files_out = _git(
        tree,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        sha,
    )
    files = sorted({line.strip() for line in files_out.splitlines() if line.strip()}) if files_rc == 0 else None

    subject_rc, subject_out = _git(tree, "show", "-s", "--format=%s", sha)
    subject = " ".join(subject_out.split()) if subject_rc == 0 else ""
    summary = "commit " + sha[:12] + ((": " + subject) if subject else "")
    summary = summary[:500]
    row = hook(
        root_path,
        "commit",
        summary,
        instance_id=author,
        author=author,
        extra={
            "branch": branch,
            "sha": sha,
            "parent": parent,
            "files": files,
            "worktree": str(tree),
        },
    )
    if set(row) != set(COMMIT_ROW_KEYS):
        raise RuntimeError("commit row shape drifted")
    return {"ok": True, "duplicate": False, "row": row}
