"""The one way a test folder counts as a worktree Convoy minted.

A launch writes every repo file only into a worktree `repo.mint_worktrees` created: a linked git
worktree of the checkout its `.convoy/minted.json` names, at the path the marker records. Anywhere
else it writes only the files Convoy names. A test that brings up a temp folder and expects every
file opts in here: the folder becomes a real linked worktree of a scratch checkout, with the marker.
"""
import json
import subprocess
import tempfile
from pathlib import Path


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def mark_minted(worktree) -> Path:
    """Make an empty temp folder a linked worktree of a scratch checkout, and mark it. Returns it."""
    wt = Path(worktree)
    if (wt / ".git").exists() or (wt.exists() and any(wt.iterdir())):
        raise ValueError("mark_minted wants an empty folder: " + str(wt))
    checkout = Path(tempfile.mkdtemp(prefix="convoy-test-checkout-"))
    _git(checkout, "init", "-q")
    (checkout / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "init")
    branch = "convoy/test-" + wt.name
    _git(checkout, "worktree", "add", "-q", "-b", branch, str(wt))
    common = _git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    marker = wt / ".convoy" / "minted.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"minted_by": "convoy", "worktree": str(wt.resolve()), "checkout": str(checkout),
                                  "common_dir": common, "branch": branch,
                                  "minted_at": "2026-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
    return wt
