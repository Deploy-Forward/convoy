"""Git provenance on the existing append-only Convoy feed."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .convoy import list_seats
from .cmd import quiet_spawn_kwargs
from .layer import SCHEMA_VERSION, feed_path, hook, parse_since


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
REBASE_NOTE = "committed refs only; a sibling's uncommitted work is invisible to git by design"


def _git(args: Sequence[str], cwd: Path | str) -> tuple[int | None, str]:
    """Return ``(returncode, stdout)``; execution failures are ``(None, '')``.

    The return code is retained because successful empty output and a failed
    command have different provenance meanings.
    """
    try:
        run = subprocess.run(
            ["git", *args],
            cwd=str(Path(cwd)),
            capture_output=True,
            text=True,
            timeout=10,
            **quiet_spawn_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return run.returncode, (run.stdout or "").rstrip()


def _call(cwd: Path | str, *args: str) -> tuple[int | None, str]:
    return _git(list(args), cwd)


def _feed_rows(root: Path | str) -> list[dict[str, Any]]:
    """Read valid rows without turning a malformed fragment into truth."""
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


def commit_rows(root: Path | str, *, since: str | None = None) -> list[dict[str, Any]]:
    since_iso = parse_since(since) if since is not None else None
    rows = [row for row in _feed_rows(root) if row.get("kind") == "commit"]
    if since_iso is not None:
        rows = [row for row in rows if str(row.get("ts") or "") >= since_iso]
    return rows


def _seat(root: Path | str, chair: str) -> dict[str, Any] | None:
    for row in list_seats(Path(root)):
        if row.get("session_id") == chair:
            return row
    return None


def commit_row(
    root: Path | str,
    instance_id: str,
    worktree: Path | str | None = None,
    rev: str = "HEAD",
) -> dict[str, Any]:
    """Append one exact ``kind=commit`` row, or return its duplicate."""
    root_path = Path(root)
    chair = str(instance_id or "").strip()
    if not chair:
        raise ValueError("refuse committed without a chair")
    seat = _seat(root_path, chair)
    if seat is None:
        raise ValueError("refuse committed for unknown chair " + chair)
    raw_worktree = worktree if worktree is not None else seat.get("worktree")
    if not raw_worktree:
        raise ValueError("refuse committed without a worktree for chair " + chair)
    tree = Path(raw_worktree).resolve()

    sha_rc, sha_out = _call(tree, "rev-parse", rev)
    sha = sha_out.splitlines()[0].strip() if sha_rc == 0 and sha_out else ""
    if not sha:
        raise ValueError("refuse committed without a sha for rev " + repr(rev))
    for row in commit_rows(root_path):
        if row.get("instance_id") == chair and row.get("sha") == sha:
            return {"ok": True, "duplicate": True, "row": row}

    branch_rc, branch_out = _call(tree, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_out or None if branch_rc == 0 else None
    parent_rc, parent_out = _call(tree, "rev-parse", f"{rev}^")
    parent = parent_out.splitlines()[0].strip() if parent_rc == 0 and parent_out else None
    files_rc, files_out = _call(
        tree,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        rev,
    )
    files = sorted({line.strip() for line in files_out.splitlines() if line.strip()}) if files_rc == 0 else None
    subject_rc, subject_out = _call(tree, "log", "-1", "--format=%s", rev)
    subject = " ".join(subject_out.split()) if subject_rc == 0 else ""
    summary = "commit " + sha[:7]
    if branch:
        summary += " on " + branch
    if subject:
        summary += ": " + subject
    row = hook(
        root_path,
        "commit",
        summary[:500],
        instance_id=chair,
        author=chair,
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


def record_commit(
    root: Path | str,
    chair: str,
    *,
    rev: str = "HEAD",
    worktree: Path | str | None = None,
) -> dict[str, Any]:
    """Compatibility name for the CLI implementation."""
    return commit_row(root, chair, worktree=worktree, rev=rev)


def summarize(root: Path | str, since: str | None = None) -> dict[str, Any]:
    """Fold latest seats and commit rows into per-chair provenance."""
    root_path = Path(root)
    chairs: dict[str, dict[str, Any]] = {}
    touched: dict[str, set[str]] = {}
    for seat in list_seats(root_path):
        chair = str(seat.get("session_id") or "").strip()
        if not chair:
            continue
        chairs[chair] = {
            "chair": chair,
            "harness": str(seat.get("to") or "").strip() or None,
            "worktree": str(seat.get("worktree") or "").strip() or None,
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
                "worktree": None,
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
        files = row.get("files")
        if isinstance(files, list):
            touched[chair].update(path for path in files if isinstance(path, str) and path)

    for chair, card in chairs.items():
        card["files_touched"] = sorted(touched[chair])
    return {
        "schema_version": SCHEMA_VERSION,
        "since": since,
        "chairs": [chairs[chair] for chair in sorted(chairs)],
    }


def build_provenance(root: Path | str, *, since: str | None = None) -> dict[str, Any]:
    """Compatibility name retained for callers added with the first slice."""
    return summarize(root, since=since)


def rail_provenance(root: Path | str, *, since: str | None = None) -> dict[str, Any]:
    chairs = summarize(root, since=since)["chairs"]
    tips = [
        {
            "chair": row["chair"],
            "branch": row["branch"],
            "sha7": row["sha"][:7] if isinstance(row.get("sha"), str) else None,
            "ts": row["last_commit_ts"],
        }
        for row in chairs
        if row["commits"] > 0
    ]
    return {"chairs": len(chairs), "with_commits": len(tips), "tips": tips}


def _paths(worktree: Path, *args: str) -> list[str] | None:
    rc, out = _call(worktree, *args)
    if rc != 0:
        return None
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def _status_paths(worktree: Path) -> list[str] | None:
    rc, out = _call(worktree, "status", "--porcelain")
    if rc != 0:
        return None
    paths: set[str] = set()
    for line in out.splitlines():
        path = line[3:].strip() if len(line) >= 4 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.add(path.strip('"'))
    return sorted(paths)


def _merge_base(worktree: Path, left: str, right: str = "HEAD") -> str | None:
    rc, out = _call(worktree, "merge-base", left, right)
    return out.splitlines()[0].strip() if rc == 0 and out else None


def _branch_files(worktree: Path, common: str | None, branch: str) -> list[str] | None:
    if common is None:
        return None
    return _paths(worktree, "diff", "--name-only", f"{common}..{branch}")


def _chair_for_branch(root: Path | str | None, branch: str) -> str | None:
    if root is None:
        return None
    for seat in list_seats(Path(root)):
        worktree = str(seat.get("worktree") or "").strip()
        if not worktree:
            continue
        rc, found = _call(Path(worktree), "branch", "--show-current")
        if rc == 0 and found == branch:
            return str(seat.get("session_id") or "").strip() or None
    return None


def rebase_check(
    worktree: Path | str,
    base: str = "feat/happy-path-proof",
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Report overlap with committed sibling refs without mutating Git."""
    tree = Path(worktree).resolve()
    base_ref = str(base or "").strip()
    empty = {
        "ok": False,
        "base": base_ref or None,
        "base_sha": None,
        "merge_base": None,
        "behind": None,
        "my_files": None,
        "uncommitted": None,
        "siblings": [],
        "note": REBASE_NOTE,
        "action": None,
    }
    base_rc, base_out = _call(tree, "rev-parse", base_ref)
    base_sha = base_out.splitlines()[0].strip() if base_rc == 0 and base_out else ""
    if not base_sha:
        return {**empty, "error": "base ref absent: " + repr(base_ref)}
    head_rc, head_out = _call(tree, "rev-parse", "HEAD")
    head = head_out.splitlines()[0].strip() if head_rc == 0 and head_out else ""
    if not head:
        return {**empty, "base_sha": base_sha, "error": "HEAD absent"}

    branch_rc, branch_out = _call(tree, "branch", "--show-current")
    branch = branch_out if branch_rc == 0 and branch_out else None
    common = _merge_base(tree, base_sha, head)
    committed = _branch_files(tree, common, head)
    uncommitted = _status_paths(tree)
    mine = None if committed is None or uncommitted is None else set(committed) | set(uncommitted)
    behind_rc, behind_out = _call(tree, "rev-list", "--count", f"{head}..{base_sha}")
    try:
        behind = int(behind_out) if behind_rc == 0 else None
    except ValueError:
        behind = None

    refs_rc, refs_out = _call(tree, "for-each-ref", "--format=%(refname:short)", "refs/heads/convoy/")
    local_refs = sorted(set(refs_out.splitlines())) if refs_rc == 0 else []
    siblings: list[dict[str, Any]] = []
    represented: set[str] = set()
    for sibling_branch in local_refs:
        if sibling_branch == branch:
            continue
        sha_rc, sha_out = _call(tree, "rev-parse", sibling_branch)
        sibling_sha = sha_out.splitlines()[0].strip() if sha_rc == 0 and sha_out else None
        sibling_base = _merge_base(tree, sibling_branch, head)
        files = _branch_files(tree, sibling_base, sibling_branch)
        overlap = sorted(mine.intersection(files)) if mine is not None and files is not None else None
        chair = _chair_for_branch(root, sibling_branch)
        if chair:
            represented.add(chair)
        siblings.append({
            "chair": chair,
            "branch": sibling_branch,
            "sha": sibling_sha,
            "source": "git",
            "files": files,
            "overlapping_files": overlap,
        })

    feed_by_chair: dict[str, list[dict[str, Any]]] = {}
    if root is not None:
        for row in commit_rows(root):
            chair = str(row.get("instance_id") or row.get("from") or "").strip()
            row_branch = str(row.get("branch") or "").strip()
            if not chair or chair in represented or row_branch in local_refs:
                continue
            feed_by_chair.setdefault(chair, []).append(row)
    for chair, rows in sorted(feed_by_chair.items()):
        outside: list[dict[str, Any]] = []
        files: set[str] = set()
        for row in rows:
            sha = str(row.get("sha") or "").strip()
            if not sha:
                continue
            ancestor_rc, _ = _call(tree, "merge-base", "--is-ancestor", sha, head)
            if ancestor_rc == 0:
                continue
            outside.append(row)
            if isinstance(row.get("files"), list):
                files.update(path for path in row["files"] if isinstance(path, str) and path)
        if not outside:
            continue
        latest = max(outside, key=lambda row: str(row.get("ts") or ""))
        paths = sorted(files)
        overlap = sorted(mine.intersection(paths)) if mine is not None else None
        siblings.append({
            "chair": chair,
            "branch": str(latest.get("branch") or "").strip() or None,
            "sha": str(latest.get("sha") or "").strip() or None,
            "source": "feed",
            "files": paths,
            "overlapping_files": overlap,
        })

    siblings.sort(key=lambda row: (str(row.get("branch") or ""), str(row.get("chair") or "")))
    has_overlap = any(bool(row.get("overlapping_files")) for row in siblings)
    return {
        "ok": True,
        "base": base_ref,
        "base_sha": base_sha,
        "merge_base": common,
        "behind": behind,
        "my_files": committed,
        "uncommitted": uncommitted,
        "siblings": siblings,
        "note": REBASE_NOTE,
        "action": "rebase" if (isinstance(behind, int) and behind > 0) or has_overlap else "clean",
    }


def check_rebase(
    root: Path | str,
    *,
    base: str | None = None,
    worktree: Path | str | None = None,
) -> dict[str, Any]:
    """Compatibility name for the CLI implementation."""
    return rebase_check(worktree or Path.cwd(), base=base or "feat/happy-path-proof", root=root)
