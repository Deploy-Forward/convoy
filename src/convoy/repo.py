"""The repository step: gh lists, git clones, git mints one worktree per seat.

Every shell call goes through a runner argument (default: subprocess) so the
suite never reaches GitHub. Unknown is null: a missing gh is ok=false with an
install hint, never a guessed list; a non-zero exit carries the tool's own
stderr, never an invented reason.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import signal
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

Runner = Callable[..., subprocess.CompletedProcess]
# A seat name is one path segment (<checkout>-wt-<name>) and one ref segment
# (convoy/<name>); the cap is per thread, not a resource limit.
_SEAT_NAME = re.compile(r"[A-Za-z0-9._-]+")
MAX_SEATS = 64

# Quoted from gh version 2.83.2 --help: `gh repo list [<owner>] [flags]`,
# `--json fields  Output JSON with the specified fields`,
# `-L, --limit int  Maximum number of repositories to list (default 30)`;
# JSON FIELDS lists nameWithOwner, url, isPrivate, updatedAt.
LIST_FIELDS = "nameWithOwner,url,isPrivate,updatedAt"
GH_INSTALL_HINT = "install GitHub CLI from https://cli.github.com, then `gh auth login`"
# Written to <checkout>/.git/info/exclude so the bind never becomes a tracked
# file of the user's repo. info/exclude is git's per-clone ignore, not content.
# Anchored to the work tree's root: a docs/thread.md of the person's is never hidden.
EXCLUDE_LINES = ("/.convoy/", "/thread.md")
# Written by mint_worktrees into a worktree it creates, and only then: the one record that Convoy
# made the folder, so a launch may write every repo file there. Under .convoy/, so excluded.
MINTED_MARKER = Path(".convoy") / "minted.json"


def run_argv(argv: list[str], cwd: str | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    """Bound helper lifetime, including Windows remote/auth descendants.

    Files, not pipes: a grandchild inheriting stdout cannot keep communicate()
    blocked after the parent dies. Helpers never open visible console windows.
    """
    from .cmd import quiet_spawn_kwargs
    env = dict(os.environ)
    if Path(argv[0]).stem.lower() == "git" and len(argv) > 1 and argv[1] in ("fetch", "ls-remote"):
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_ASKPASS="")
    spawn = quiet_spawn_kwargs()
    if os.name == "nt":
        spawn["creationflags"] |= subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        spawn["start_new_session"] = True
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        # Clone/worktree retain normal credential/input policy; refresh cannot prompt.
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL if argv[1:2] in (["fetch"], ["ls-remote"]) else None, stdout=stdout,
                                stderr=stderr, env=env, **spawn)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=.5, **quiet_spawn_kwargs())
                except (OSError, subprocess.SubprocessError):
                    proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise subprocess.TimeoutExpired(argv, timeout) from None
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(argv, proc.returncode,
            stdout.read().decode(errors="replace").replace("\r\n", "\n"),
            stderr.read().decode(errors="replace").replace("\r\n", "\n"))


def redact_credentials(value):
    """Public start cards/CLI output never echo URL credentials or token values."""
    if isinstance(value, dict):
        receipt = {"from", "to", "age_s", "claimed_answer"}.issubset(value) or value.get("kind") == "synapse"
        return {key: ("[redacted]" if re.fullmatch(r"(?i)(?:.*_)?(?:token|password|secret|authorization|api_key)", str(key))
                      and not (key == "token" and receipt and re.fullmatch(r"[0-9a-f]{32}", str(item)))
                      else redact_credentials(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_credentials(item) for item in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1[redacted]@", value)
    value = re.sub(r"(?i)((?:access_token|token|password|secret|api_key)=)[^&\s\"']+", r"\1[redacted]", value)
    value = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)\b", "[redacted]", value)
    return re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[redacted]", value)


def checkouts_root() -> Path:
    """Convoy-owned checkout root, beside the thread index (index.py:27)."""
    home = os.environ.get("CONVOY_HOME")
    base = Path(home) if home else Path.home() / ".convoy"
    return base / "checkouts"


def _option_shaped(text: str) -> bool:
    """'--upload-pack=calc x://h/o/r' contains '://' and git reads it as an
    option. Nothing starting with '-' is a url here."""
    return text.strip().startswith("-")


def is_repo_url(text: str | None) -> bool:
    t = (text or "").strip()
    return not _option_shaped(t) and ("://" in t or t.startswith("git@"))


def checkout_path_for(url: str) -> Path:
    """<checkouts_root>/<owner>/<repo> from an https or scp-style git URL."""
    t = url.strip()
    if _option_shaped(t):
        raise ValueError("refuse url starting with '-': " + t)
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


def git_common_dir(root: Path | str) -> Path | None:
    """The directory git reads info/exclude from, or None when `root` is not a
    checkout. A primary checkout's `.git` is that directory. A worktree's
    `.git` is a one-line pointer file (`gitdir: <main>/.git/worktrees/<n>`)
    and that gitdir's `commondir` file names the shared `.git`. Pure file
    reads: bind must not spawn git to stay honest about its record."""
    dot = Path(root) / ".git"
    if dot.is_dir():
        return dot
    if not dot.is_file():
        return None
    try:
        text = dot.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (Path(root) / gitdir).resolve()
    common = gitdir / "commondir"
    if common.is_file():
        try:
            rel = common.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return gitdir
        target = Path(rel)
        return (gitdir / target).resolve() if not target.is_absolute() else target
    return gitdir


def exclude_convoy_files(root: Path | str) -> bool:
    """Write EXCLUDE_LINES into git's per-clone ignore so `.convoy/` and
    `thread.md` never become tracked files of the user's repo (an untracked
    record is one `git add -A` away from a commit). True when a
    checkout was found and the lines are present; False for a plain folder.
    Idempotent: present lines are never duplicated. A write that fails never fails the bind."""
    try:
        return exclude_paths(root, EXCLUDE_LINES)
    except OSError:
        return False


def exclude_paths(root: Path | str, lines: Iterable[str]) -> bool:
    """Add these paths to git's per-clone ignore (info/exclude), once each. It hides untracked files
    only, never a tracked one, and it is shared by every worktree of the clone, so a caller passes
    anchored paths ("/x") that only Convoy names. True when a checkout was found; False for a plain
    folder. An OSError on the write is the caller's to report."""
    lines = list(lines)
    common = git_common_dir(root)
    if common is None:
        return False
    info = common / "info"
    try:
        info.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    path = info / "exclude"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    missing = [line for line in lines if line not in text.splitlines()]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "".join(line + "\n" for line in missing), encoding="utf-8")
    return True


def _same_path(a: Path | str, b: Path | str) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def is_minted_worktree(path: Path | str, runner: Runner | None = None) -> bool:
    """True only for a marker Convoy wrote for THIS folder: parseable, minted_by convoy, its
    recorded worktree is this folder, git resolves this folder's common dir to the recorded one, and
    the recorded checkout still lists this worktree. A primary checkout, a plain folder, a reused
    or re-added worktree, a submodule or a copied marker is the person's repo."""
    run = runner or run_argv
    wt = Path(path)
    if not (wt / ".git").is_file():
        return False
    try:
        data = json.loads((wt / MINTED_MARKER).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    if not (isinstance(data, dict) and data.get("minted_by") == "convoy"):
        return False
    if not all(isinstance(data.get(k), str) and data[k] for k in ("worktree", "checkout", "common_dir")):
        return False
    if not _same_path(data["worktree"], wt):
        return False
    try:
        common = run(["git", "-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"], None, timeout=30)
        listed = run(["git", "-C", data["checkout"], "worktree", "list", "--porcelain"], None, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if common.returncode != 0 or not _same_path((common.stdout or "").strip(), data["common_dir"]):
        return False
    if listed.returncode != 0:
        return False
    return any(line.startswith("worktree ") and _same_path(line[len("worktree "):], wt)
               for line in (listed.stdout or "").splitlines())


def _write_minted_marker(path: Path, checkout: Path, branch: str) -> bool:
    from .layer import utc_now
    common = git_common_dir(path)
    if common is None:
        return False
    try:
        dest = path / MINTED_MARKER
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"minted_by": "convoy", "worktree": str(path.resolve()), "checkout": str(checkout),
                                    "common_dir": str(Path(common).resolve()), "branch": branch,
                                    "minted_at": utc_now()}) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


# The person's --write-repo-files, remembered for one folder so a later launch there refreshes what
# they opted into. Bound like the marker (this folder, its git common dir), so a copied or committed
# record opts nothing else in; every writer adds it to info/exclude. --no-write-repo-files removes it.
REPO_FILES_RECORD = Path(".convoy") / "repo-files.json"


def _git_common(path: Path | str, runner: Runner | None = None) -> str | None:
    """git's own answer for the folder's common dir, resolved; None outside a checkout."""
    try:
        r = (runner or run_argv)(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                 None, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "").strip()
    return str(Path(out).resolve()) if r.returncode == 0 and out else None


def record_repo_files_opt_in(path: Path | str, runner: Runner | None = None) -> bool:
    from .layer import utc_now
    try:
        dest = Path(path) / REPO_FILES_RECORD
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"write_repo_files": True, "worktree": str(Path(path).resolve()),
                                    "common_dir": _git_common(path, runner), "at": utc_now()}) + "\n",
                        encoding="utf-8")
        return True
    except OSError:
        return False


def withdraw_repo_files_opt_in(path: Path | str) -> bool:
    """Remove the opt-in record; True when one was there."""
    dest = Path(path) / REPO_FILES_RECORD
    try:
        dest.unlink()
        return True
    except FileNotFoundError:
        return False


def repo_files_opted_in(path: Path | str, runner: Runner | None = None) -> bool:
    """True only for a record written for THIS folder: its worktree and git common dir both match."""
    try:
        data = json.loads((Path(path) / REPO_FILES_RECORD).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    if not (isinstance(data, dict) and data.get("write_repo_files") is True):
        return False
    if not (isinstance(data.get("worktree"), str) and _same_path(data["worktree"], path)):
        return False
    common = data.get("common_dir")
    here = _git_common(path, runner)
    return common == here if common is None or here is None else _same_path(common, here)


def is_tracked(path: Path | str, rel: str, runner: Runner | None = None) -> bool:
    """True when git tracks `rel` in the worktree at `path`; False for a plain folder or on any error."""
    if git_common_dir(path) is None:
        return False
    try:
        r = (runner or run_argv)(["git", "-C", str(path), "ls-files", "--error-unmatch", "--", rel], None, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def clone(url: str, dest: Path | str, runner: Runner | None = None) -> dict[str, Any]:
    run = runner or run_argv
    target = Path(dest)
    card: dict[str, Any] = {"ok": False, "url": url, "dest": str(target), "cloned": False}
    if _option_shaped(url):
        card["error"] = "refuse url starting with '-': " + url
        return card
    if target.exists() and any(target.iterdir()):
        card["error"] = "dest is not empty: " + str(target)
        return card
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # `--` ends option parsing: the url is a positional to git, never a flag.
        r = run(["git", "clone", "--", url, str(target)], None)
    except (OSError, subprocess.SubprocessError) as exc:
        card["error"] = _fail(exc)
        return card
    if r.returncode != 0:
        card["error"] = "git clone exited " + str(r.returncode) + ": " + (r.stderr or "").strip()
        return card
    card["ok"] = True
    card["cloned"] = True
    card["excluded"] = exclude_convoy_files(target)
    return card


def minted_worktree_path(checkout: Path | str, name: str) -> Path:
    """Where mint_worktrees puts the worktree for seat `name`: a sibling of the checkout."""
    base = Path(checkout)
    return base.parent / (base.name + "-wt-" + name)


def mint_worktrees(checkout: Path | str, n: int, names: list[str] | None = None,
                   runner: Runner | None = None) -> dict[str, Any]:
    """One worktree per seat, DERIVED from the checkout: a sibling directory
    <checkout>-wt-<name> on branch convoy/<name>, the way this repo's own
    worktrees are laid out. Stops at the first git failure
    and reports what was minted; an existing sibling is reused, not re-added. Only a worktree
    created here gets the minted marker (is_minted_worktree); a reused one does not."""
    run = runner or run_argv
    base = Path(checkout)
    count = int(n)
    card: dict[str, Any] = {"ok": False, "checkout": str(base), "worktrees": []}
    if not 1 <= count <= MAX_SEATS:
        card["error"] = "n must be between 1 and " + str(MAX_SEATS)
        return card
    seat_names = list(names) if names is not None else ["neuron-" + str(i + 1) for i in range(count)]
    if len(seat_names) != count:
        card["error"] = "names has " + str(len(seat_names)) + " entries for n=" + str(count)
        return card
    bad = [x for x in seat_names if not _SEAT_NAME.fullmatch(str(x))]
    if bad:
        # A name is one path segment and one ref segment; '../x' would leave
        # the sibling convention, and git refusing it later is not our honesty.
        card["error"] = "refuse seat name (letters, digits, . _ - only): " + repr(bad)
        return card
    if not (base / ".git").exists():
        card["error"] = "not a git checkout: " + str(base)
        return card
    for name in seat_names:
        path = minted_worktree_path(base, name)
        branch = "convoy/" + name
        row = {"name": name, "path": str(path), "branch": branch, "created": False}
        if (path / ".git").exists():
            row["excluded"] = exclude_convoy_files(path)
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
        # A fake runner creates no folder; the marker never makes one.
        row["marker"] = path.is_dir() and _write_minted_marker(path, base, branch)
        # A worktree shares the checkout's info/exclude through its common
        # dir; writing it per seat keeps crew honest when the checkout was
        # bound before this rule existed.
        row["excluded"] = exclude_convoy_files(path)
        card["worktrees"].append(row)
    card["ok"] = True
    return card
