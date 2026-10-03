"""Bounded project discovery and fast-forward-only refresh. Never infer absence from an error."""
from __future__ import annotations

import json
import configparser
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .index import list_threads
from .repo import checkouts_root, checkout_path_for, git_common_dir, is_repo_url, run_argv, redact_credentials

_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


def normalized_remote(value: str, *, repo=None, rewrites=()) -> str | None:
    text = value.strip()
    # Git uses the longest matching insteadOf prefix, not repeated rewriting.
    for prefix, base in sorted(rewrites, key=lambda pair: -len(pair[0])):
        if text.startswith(prefix):
            text = base + text[len(prefix):]
            break
    if not text or text.startswith("-"):
        return None
    scp = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):([^\s]+)", text)
    if scp and "://" not in text and not re.match(r"^[A-Za-z]:", text):
        host, path = scp.groups()
    else:
        parsed = urlsplit(text)
        if not parsed.scheme:
            local = Path(text)
            if repo is not None and not local.is_absolute():
                local = Path(repo) / local
            return "file/" + str(local.resolve()).replace("\\", "/")
        host, path = parsed.hostname or "file", parsed.path
    path = path.strip("/")
    path = path[:-4] if path.lower().endswith(".git") else path
    if not path or any(p in (".", "..") for p in path.split("/")):
        return None
    return host.lower() + "/" + (path.lower() if host.lower() == "github.com" else path)


def _run(runner, argv, cwd=None, timeout=20):
    return runner(argv, str(cwd) if cwd is not None else None, timeout=timeout)


def _global_rewrites(runner):
    explicit = os.environ.get("GIT_CONFIG_GLOBAL")
    paths = [Path(explicit).expanduser()] if explicit else [
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "git" / "config",
        Path.home() / ".gitconfig"]
    rules = []
    try:
        for path in paths:
            if not path.is_file():
                continue
            config = configparser.RawConfigParser(strict=True, allow_no_value=True)
            config.read_string(path.read_text(encoding="utf-8-sig"))
            if any(s.lower() == "include" or s.lower().startswith("includeif ") for s in config.sections()):
                raise configparser.Error("global includes need Git")
            for section in config.sections():
                match = re.fullmatch(r'(?i)url\s+"(.*)"', section)
                prefix = config.get(section, "insteadof", fallback=None)
                if match and prefix:
                    rules.append((prefix.strip('"'), match[1]))
        return rules
    except configparser.Error:
        result = _run(runner, ["git", "config", "--global", "--get-regexp", r"^url\..*\.insteadof$"], timeout=.5)
        if result.returncode not in (0, 1):
            raise ValueError("global remote rewrite state unreadable")
        rules = []
        for line in result.stdout.splitlines():
            key, _, prefix = line.partition(" ")
            if key.lower().startswith("url.") and key.lower().endswith(".insteadof") and prefix:
                rules.append((prefix, key[4:-10]))
        return rules


def _remotes(path, runner, timeout=20, rewrites=()):
    """Ordinary repositories cost file reads, not two child processes each.

    Let Git resolve includes/conditional includes, worktree overrides and
    exotic config syntax rather than pretending this is a second Git parser.
    """
    common = git_common_dir(path)
    if common is not None:
        config = common / "config"
        try:
            text = config.read_text(encoding="utf-8-sig")
            parsed = configparser.RawConfigParser(strict=True, allow_no_value=True,
                inline_comment_prefixes=("#", ";"))
            parsed.read_string(text)
            dot = Path(path) / ".git"
            admin = dot
            if dot.is_file():
                pointer = dot.read_text(encoding="utf-8-sig").strip().removeprefix("gitdir:").strip()
                admin = Path(pointer)
                if not admin.is_absolute():
                    admin = Path(path) / admin
            complex_config = any(s.lower() == "include" or s.lower().startswith("includeif ") for s in parsed.sections())
            complex_config |= (common / "config.worktree").exists() or (admin / "config.worktree").exists()
            if not complex_config:
                urls = [parsed.get(s, "url", fallback="") or "" for s in parsed.sections()
                        if re.fullmatch(r'(?i)remote\s+".*"', s)]
                if not any("\\" in url for url in urls):
                    return sorted({key for url in urls if (key := normalized_remote(url.strip('"'), repo=path, rewrites=rewrites))})
        except (FileNotFoundError, configparser.Error, UnicodeError):
            pass  # Git is the authority for missing/unsupported config.
    result = _run(runner, ["git", "remote", "-v"], path, timeout)
    if result.returncode:
        raise ValueError("git remote failed at " + str(path))
    return sorted({key for line in result.stdout.splitlines() if len(line.split()) >= 2
                   if (key := normalized_remote(line.split()[1], repo=path, rewrites=rewrites))})


def _roots(configured):
    if configured is not None:
        return [Path(p).expanduser() for p in configured]
    env = os.environ.get("CONVOY_SEARCH_ROOTS")
    return [Path(p).expanduser() for p in env.split(os.pathsep) if p] if env else [checkouts_root().parent, Path.home() / "ola"]


def _locals(search_roots, runner, budget, clock, canonical=None, *, deadline=None, rewrites=()):
    deadline = deadline if deadline is not None else clock() + max(0, budget)
    paths = {}
    warnings = []
    owned = checkouts_root().resolve()
    home = owned.parent
    def internal(path):
        p = Path(path).resolve()
        if p.is_relative_to(owned) and p != owned:
            return False  # Explicit owned owner/repo discovery remains supported.
        return p.is_relative_to(home) or any(part.lower() == ".convoy" for part in p.parts)
    def add(path, title=None, updated_at=None, indexed=False):
        p = Path(path).resolve()
        if internal(p):
            return
        paths.setdefault(str(p), {"path": p, "title": title, "updated_at": updated_at, "indexed_thread": indexed})
    for row in list_threads():
        if row.get("present") and row.get("root") and not row.get("skip_reason"):
            add(row["root"], row.get("thread"), row.get("updated_at"), True)
    if canonical and canonical.exists():
        add(canonical)
    # The owned store has a known owner/repo layout. Inspect it without
    # recursively crawling arbitrary search roots or matching folder names
    # as remote identity.
    if owned.is_dir():
        try:
            for owner in owned.iterdir():
                if clock() >= deadline:
                    warnings.append("local scan timed out")
                    break
                if owner.is_dir():
                    for repo in owner.iterdir():
                        if clock() >= deadline:
                            warnings.append("local scan timed out")
                            break
                        if repo.is_dir() and (repo / ".git").exists():
                            add(repo)
        except OSError:
            warnings.append("owned checkout scan unreadable")
    for base in _roots(search_roots):
        if clock() >= deadline:
            warnings.append("local scan timed out")
            break
        if not base.is_dir() or internal(base):
            continue
        try:
            if (base / ".git").exists():
                add(base)
            for child in base.iterdir():
                if clock() >= deadline:
                    warnings.append("local scan timed out")
                    break
                if child.is_dir():
                    add(child)
        except OSError:
            warnings.append("local scan unreadable: " + str(base))
    out = []
    for item in paths.values():
        if clock() >= deadline:
            warnings.append("local scan timed out")
            break
        p = item["path"]
        row = {"kind": "local", "path": str(p), "name": p.name, "title": item["title"],
               "remotes": [], "last_commit": None, "indexed_thread": item["indexed_thread"],
               "updated_at": item["updated_at"], "main_checkout": (p / ".git").is_dir(),
               "linked_worktree": (p / ".git").is_file()}
        if (p / ".git").exists():
            try:
                row["remotes"] = _remotes(p, runner, min(.5, max(.01, deadline - clock())), rewrites)
            except (OSError, ValueError, subprocess.SubprocessError):
                warnings.append("local repository read failed: " + str(p))
        out.append(row)
    return out, sorted(set(warnings))


def _github(runner):
    try:
        auth = _run(runner, ["gh", "auth", "status"], timeout=5)
        if auth.returncode:
            text = (auth.stderr or "").lower()
            if "not logged into any github hosts" in text:
                return [], "local only: gh not authenticated", None, None
            return [], None, "github unknown: authentication check failed", None
        user = _run(runner, ["gh", "api", "user"])
        if user.returncode:
            return [], None, "github unknown: user lookup failed", None
        login = json.loads(user.stdout).get("login")
        if not isinstance(login, str) or not _OWNER.fullmatch(login):
            raise ValueError("invalid gh login")
        orgs = _run(runner, ["gh", "api", "user/orgs", "--paginate", "--jq", ".[].login"])
        if orgs.returncode:
            return [], None, "github unknown: org lookup failed", login
        owners = sorted({login, *[s.strip() for s in orgs.stdout.splitlines() if s.strip()]})
        if any(not _OWNER.fullmatch(owner) for owner in owners):
            raise ValueError("invalid gh owner")
        rows = []
        for owner in owners:
            got = _run(runner, ["gh", "repo", "list", owner, "--limit", "200", "--json", "nameWithOwner,updatedAt"])
            if got.returncode:
                return rows, None, "github unknown: repository listing failed; results incomplete", login
            raw = json.loads(got.stdout)
            if not isinstance(raw, list):
                raise ValueError("invalid gh repo list")
            for r in raw:
                name = r.get("nameWithOwner") if isinstance(r, dict) else None
                if not isinstance(name, str) or not _SLUG.fullmatch(name) or not _OWNER.fullmatch(name.split('/')[0]):
                    raise ValueError("invalid gh repository")
                rows.append({"kind": "github", "nameWithOwner": name, "last_commit": r.get("updatedAt"),
                             "last_commit_source": "github updatedAt",
                             "remotes": ["github.com/" + name.lower()]})
            if len(raw) >= 200:
                return rows, None, "github unknown: listing capped at 200; results incomplete", login
        return rows, None, None, login
    except FileNotFoundError:
        return [], "local only: gh missing", None, None
    except (OSError, ValueError, subprocess.SubprocessError):
        return [], None, "github unknown: read failed or timed out", None


def _matches(target, row):
    compact = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    needle = compact(target)
    labels = [row.get("name"), row.get("title"), str(row.get("nameWithOwner") or "").split("/")[-1],
              *[s.split("/")[-1] for s in row.get("remotes", [])]]
    return bool(needle and any(needle in compact(label or "") for label in labels))


def _exact(target, row):
    # Titles and punctuation-folded similarity are suggestions, never authority.
    labels = [row.get("name"), str(row.get("nameWithOwner") or "").split("/")[-1],
              *[s.split("/")[-1] for s in row.get("remotes", [])]]
    return any(target.casefold() == str(label or "").casefold() for label in labels)


def _dates(rows, git, deadline, clock):
    warnings = []
    for row in rows:
        if row["kind"] != "local" or not (Path(row["path"]) / ".git").exists():
            continue
        remaining = deadline - clock()
        if remaining <= 0:
            warnings.append("local scan timed out while reading candidate dates")
            break
        try:
            got = _run(git, ["git", "log", "-1", "--format=%cI"], row["path"], min(.5, remaining))
            if not got.returncode:
                date = got.stdout.strip()
                row["last_commit"] = date if date and date != "null" else None
        except (OSError, subprocess.SubprocessError):
            warnings.append("local candidate date unavailable: " + row["path"])
        if clock() >= deadline:
            warnings.append("local scan timed out while reading candidate dates")
            break
    return warnings


def _prefer_checkouts(rows):
    """Collapse same-remote alternatives by the documented checkout priority.
    Never use this when discovery is incomplete or to pick between remote identities.
    """
    remaining = list(rows)
    out = []
    while remaining:
        row = remaining.pop(0)
        group = [row]
        keys = set(row.get("remotes", [])) if row["kind"] == "local" else set()
        changed = True
        while changed and keys:
            changed = False
            for other in list(remaining):
                if other["kind"] == "local" and keys.intersection(other["remotes"]):
                    group.append(other)
                    keys.update(other["remotes"])
                    remaining.remove(other)
                    changed = True
        indexed = []
        now = time.time()
        for r in group:
            if not r.get("indexed_thread"):
                continue
            try:
                stamp = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))
                age = now - stamp.timestamp()
                if stamp.tzinfo is not None and 0 <= age <= 14 * 86400:
                    indexed.append(r)
            except (AttributeError, KeyError, TypeError, ValueError):
                pass  # Missing/future/unknown dates cannot prove fresh ownership.
        mains = [r for r in group if r.get("main_checkout")]
        try:
            indexed.sort(key=lambda r: datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")).timestamp(), reverse=True)
            chosen = indexed[0] if indexed else mains[0] if len(mains) == 1 else None
        except (AttributeError, KeyError, TypeError, ValueError):
            chosen = indexed[0] if len(indexed) == 1 else None
        out.extend([chosen] if chosen else group)
    return out


def _pick(rows, note=None, warnings=(), all_worktrees=False):
    only_linked = bool(rows) and all(r.get("linked_worktree") for r in rows)
    def order(row):
        stamp = row.get("updated_at") or row.get("last_commit")
        try:
            newest = -datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except (AttributeError, TypeError, ValueError):
            newest = float("inf")
        return (bool(row.get("linked_worktree")), newest if only_linked else 0,
                row["kind"], row.get("path") or row.get("nameWithOwner") or "")
    rows = sorted(rows, key=order)
    linked = [r for r in rows if r.get("linked_worktree")]
    visible = rows if all_worktrees or only_linked else [r for r in rows if not r.get("linked_worktree")]
    card = {"ok": False, "ask": "pick", "candidates": [{**r, "pick": i + 1} for i, r in enumerate(visible)], "note": note}
    if linked:
        card["linked_worktrees"] = {"count": len(linked), "summary": "+" + str(len(linked)) + " worktrees",
                                    "next": "start <target> --all"}
    if warnings:
        card.update(incomplete=True, warnings=list(warnings), error="local scan incomplete: " + "; ".join(warnings))
        card["note"] = (note + "; " if note else "") + "list may be incomplete"
    return card


def resolve_target(target: str, **kwargs):
    """Read-only public resolution card; start uses the private raw result
    for an authenticated clone, then redacts the entire returned start card."""
    return redact_credentials(_resolve_target(target, **kwargs))


def _resolve_target(target: str, *, search_roots=None, git_runner=None, gh_runner=None,
                   scan_budget=5.0, clock=time.monotonic, create=False, all_worktrees=False):
    git, gh = git_runner or run_argv, gh_runner or run_argv
    want = target.strip()
    if not want or want.startswith("-"):
        return {"ok": False, "error": "refuse target starting with '-' or empty", "ask": "unknown"}
    path = Path(want).expanduser()
    if path.exists():
        if not path.is_dir():
            return {"ok": False, "error": "target is not a directory", "ask": "unknown"}
        remotes = []
        try:
            remotes = _remotes(path.resolve(), git) if (path / ".git").exists() else []
        except (OSError, ValueError, subprocess.SubprocessError):
            return {"ok": False, "ask": "unknown", "error": "local remote state unreadable"}
        return {"ok": True, "checkout": str(path.resolve()), "github": False, "refresh": False,
                "note": None if remotes else "local only: checkout has no remote"}
    # Missing explicit paths preserve the local-folder workflow. Bare names
    # and owner/repo slugs are resolved, never implicitly mkdir'd.
    if not is_repo_url(want) and (path.is_absolute() or want.startswith(("./", "../", "~", ".\\", "..\\")) or "\\" in want):
        return {"ok": True, "checkout": str(path.resolve()), "github": False,
                "refresh": False, "note": "local only: explicit local folder"}
    cloud = is_repo_url(want) or bool(_SLUG.fullmatch(want))
    url = want if is_repo_url(want) else "https://github.com/" + want + ".git" if cloud else None
    try:
        deadline = clock() + max(0, scan_budget)
        rewrites = _global_rewrites(git)
        canonical = checkout_path_for(url) if url else None
        key = normalized_remote(url, rewrites=rewrites) if url else None
        if url and not key:
            raise ValueError("invalid remote URL")
        locals_, warnings = _locals(search_roots, git, scan_budget, clock, canonical, deadline=deadline, rewrites=rewrites)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"ok": False, "ask": "unknown", "error": str(exc)}
    note, login, gh_error = None, None, None
    if cloud:
        candidates = [r for r in locals_ if key in r["remotes"]]
    else:
        gh_began = clock()
        github, note, gh_error, login = _github(gh)
        deadline += max(0, clock() - gh_began)  # GH has its own timeouts, not the local scan budget.
        candidates = [r for r in locals_ if _matches(want, r)]
        for row in github:
            if _matches(want, row) and not any(set(row["remotes"]) & set(r["remotes"]) for r in candidates):
                candidates.append(row)
    exact = candidates if cloud else [r for r in candidates if _exact(want, r)]
    local_exact = [r for r in exact if r["kind"] == "local"]
    # Offline exact local selection is allowed; an incomplete LOCAL scan never
    # proves uniqueness. Preserve its warnings, including after a partial match.
    if gh_error and not local_exact:
        return {"ok": False, "ask": "unknown", "error": "; ".join(warnings + ([gh_error] if gh_error else [])),
                "candidates": candidates, "note": note}
    if gh_error:
        note = gh_error
        candidates = local_exact
        exact = local_exact
    if exact:
        candidates = exact
    if warnings:
        if candidates:
            return _pick(candidates, note, warnings, all_worktrees)
        return {"ok": False, "ask": "unknown", "incomplete": True, "warnings": warnings,
                "error": "local scan incomplete: " + "; ".join(warnings), "note": "list may be incomplete"}
    candidates = _prefer_checkouts(candidates)
    candidates.sort(key=lambda r: (r["kind"], r.get("path") or r.get("nameWithOwner") or ""))
    warnings = _dates(candidates, git, deadline, clock)
    if warnings:
        return _pick(candidates, note, warnings, all_worktrees)
    if len(candidates) > 1 or (candidates and not exact):
        return _pick(candidates, note, all_worktrees=all_worktrees)
    if candidates:
        row = candidates[0]
        checkout = row.get("path") or "https://github.com/" + row["nameWithOwner"] + ".git"
        remote = bool(row["remotes"])
        return {"ok": True, "checkout": checkout, "github": remote and not bool(note),
                "refresh": remote and not bool(note), "candidate": row,
                "note": note or ("local only: checkout has no remote" if not remote else None)}
    if cloud:
        if canonical.exists() and any(canonical.iterdir()):
            return {"ok": False, "ask": "unknown", "error": "owned checkout destination exists but its remote does not match"}
        return {"ok": True, "checkout": url, "github": True, "refresh": True, "note": None}
    if create:
        if note or not login or not re.fullmatch(r"[A-Za-z0-9_.-]+", want):
            return {"ok": False, "ask": "unknown", "error": "--create requires an authenticated GitHub user and a repository name"}
        name = login + "/" + want
        try:
            result = _run(gh, ["gh", "repo", "create", name, "--private"])
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "ask": "unknown", "error": "GitHub create failed; remote state unknown"}
        if result.returncode:
            return {"ok": False, "ask": "unknown", "error": "GitHub create failed; remote state unknown"}
        return {"ok": True, "checkout": "https://github.com/" + name + ".git", "github": True,
                "refresh": True, "note": "created private GitHub repository by explicit --create"}
    return {"ok": False, "ask": "new", "note": note,
            "choices": ["local folder " + want, "create on GitHub"], "candidates": []}


def update_checkout(root: Path, *, runner=None):
    run = runner or run_argv
    def git(*args):
        result = _run(run, ["git", *args], root, 60)
        text = result.stdout or ""
        return result.returncode, text if args[0] in ("diff", "ls-files") else text.strip()
    def kept(reason):
        return {"pulled": "kept: " + reason}
    try:
        branch_code, branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
        if branch_code:
            return kept("detached")
        upstream_code, upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if upstream_code or not upstream:
            return kept("no upstream")
        code, _ = git("fetch")
        if code:
            return {"pulled": "fetch failed: git fetch exited " + str(code)}
        code, status = git("status", "--porcelain", "--untracked-files=all")
        if code:
            return kept("status unknown")
        if status:
            return kept("dirty")
        code, counts = git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if code or not re.fullmatch(r"\d+\s+\d+", counts):
            return kept("ahead/behind unknown")
        ahead, behind = map(int, counts.split())
        if ahead:
            return kept(f"diverged {ahead}/{behind}" if behind else "ahead " + str(ahead))
        if not behind:
            return kept("up to date")
        # Fetch/read time is not permission to change a branch another local
        # writer just switched or dirtied. Recheck immediately before pull.
        code, latest_branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
        if code or latest_branch != branch:
            return kept("branch changed during refresh")
        code, latest_status = git("status", "--porcelain", "--untracked-files=all")
        if code or latest_status:
            return kept("dirty or unknown after fetch")
        code, incoming = git("diff", "--name-only", "-z", "HEAD..@{upstream}")
        if code:
            return kept("incoming files unknown")
        local = set()
        for options in (("--others", "--exclude-standard"), ("--others", "--ignored", "--exclude-standard")):
            code, files = git("ls-files", "-z", *options)
            if code:
                return kept("local files unknown")
            local.update(files.split("\0"))
        overlap = sorted((set(incoming.split("\0")) & local) - {""})
        if overlap:
            return kept("would overwrite local file " + redact_credentials(overlap[0]))
        # Already fetched without prompting. Fast-forward locally, with no second
        # network fetch or credential prompt hidden inside `git pull`.
        code, _ = git("merge", "--ff-only", "@{upstream}")
        return {"pulled": "fast-forwarded " + str(behind)} if not code else kept("fast-forward refused")
    except (OSError, subprocess.SubprocessError):
        return {"pulled": "fetch failed: git command unavailable or timed out"}
