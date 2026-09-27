"""Demo test package.

Importing this package redirects CONVOY_HOME to a throwaway so bare
`python -m unittest` cannot write ~/.convoy/threads.json. Duplicated in
`test/__init__.py` so either import path guards the real home. Both also
install test/harness_guard.py: no test may start a real harness CLI.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from .. import harness_guard  # imported as test.demo
except ImportError:  # imported as a top-level `demo` (discovery from test/)
    import harness_guard

_TEST_HOME_PREFIX = "convoy-test-home-"


def _is_throwaway(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        tmp = Path(tempfile.gettempdir()).resolve()
        return resolved == tmp or resolved.is_relative_to(tmp)
    except (OSError, ValueError):
        return False


def ensure_throwaway_home() -> str:
    current = os.environ.get("CONVOY_HOME")
    if current and _is_throwaway(current):
        return current
    home = tempfile.mkdtemp(prefix=_TEST_HOME_PREFIX)
    os.environ["CONVOY_HOME"] = home
    return home


ensure_throwaway_home()
harness_guard.install()

