"""Keep every supported test entrypoint off the operator's Convoy home."""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
# Not a session id, but it routes a hook or a send to a thread: a pane exports it, so a
# test inheriting it could act on the person's real thread.
_ROOT_POINTER = "CONVOY_ROOT"
# The terminal the suite runs in: inherited, these make placement split the person's own
# Windows Terminal or tmux pane (an inherited WT_SESSION would let a test open real panes
# in the developer's window).
# A test that needs a placement sets them itself.
PLACEMENT_ENV = ("WT_SESSION", "WT_PROFILE_ID", "TMUX", "TMUX_PANE")
_held: dict[str, str] | None = None


def is_throwaway_home(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        return resolved != temp_root and resolved.is_relative_to(temp_root)
    except (OSError, ValueError):
        return False


def _native_session_names() -> tuple[str, ...]:
    """The variables Convoy's identity code reads, from its one list (never typed here)."""
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
    from convoy.panes import NATIVE_SESSION_ENV
    return (*NATIVE_SESSION_ENV, _ROOT_POINTER, *PLACEMENT_ENV)


def isolate_native_sessions() -> dict[str, str]:
    """Clear every native session variable, CONVOY_ROOT and the terminal placement
    variables (PLACEMENT_ENV); return what was there.

    The suite runs inside a person's own harness pane. A launch attaches a launcher it
    can prove by environment, so a test inheriting the pane's session id could attach
    that real session to its temp thread. A test that needs a proven session sets the
    variable itself."""
    held = {}
    for name in _native_session_names():
        value = os.environ.pop(name, None)
        if value is not None:
            held[name] = value
    return held


def restore_native_sessions(held: dict[str, str]) -> None:
    for name, value in held.items():
        os.environ[name] = value


def ensure_throwaway_home() -> str:
    """Preserve an isolated home, otherwise replace it before tests import code.
    Also clears the native session variables once per run and restores them at exit."""
    current = os.environ.get("CONVOY_HOME")
    if current and is_throwaway_home(current):
        home = current
    else:
        home = tempfile.mkdtemp(prefix="convoy-test-home-")
        os.environ["CONVOY_HOME"] = home
    # After the home: reading the list imports convoy, which must never see the real home.
    global _held
    if _held is None:
        _held = isolate_native_sessions()
        atexit.register(restore_native_sessions, _held)
        empty_launcher_table()
    return home


def empty_launcher_table() -> None:
    """A launch under test resolves its launcher against an empty process table, never the
    real one: the pane's own argv (`claude --resume <id>`) proves its session by token, which
    clearing the environment cannot stop, and a real table read is slow and can hit a test's
    patched shutil.which. A test that needs a launcher passes procs= or sets panes._TEST_PROCS."""
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
    from convoy import launcher
    launcher.TEST_DEFAULT_PROCS = []
