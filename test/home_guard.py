"""Keep every supported test entrypoint off the operator's Convoy home."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def is_throwaway_home(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        return resolved != temp_root and resolved.is_relative_to(temp_root)
    except (OSError, ValueError):
        return False


def ensure_throwaway_home() -> str:
    """Preserve an isolated home, otherwise replace it before tests import code."""
    current = os.environ.get("CONVOY_HOME")
    if current and is_throwaway_home(current):
        return current
    home = tempfile.mkdtemp(prefix="convoy-test-home-")
    os.environ["CONVOY_HOME"] = home
    return home
