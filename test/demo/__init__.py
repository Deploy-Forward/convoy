"""Demo test package.

Importing this package redirects CONVOY_HOME to a throwaway so bare
`python -m unittest` cannot write ~/.convoy/threads.json. Duplicated in
`test/__init__.py` so either import path guards the real home. Both also
install test/harness_guard.py: no test may start a real harness CLI.
"""
from __future__ import annotations

try:
    from .. import harness_guard  # imported as test.demo
    from ..home_guard import ensure_throwaway_home
except ImportError:  # imported as a top-level `demo` (discovery from test/)
    import harness_guard
    from home_guard import ensure_throwaway_home


ensure_throwaway_home()
harness_guard.install()

