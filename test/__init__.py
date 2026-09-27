"""Test package.

Importing this package redirects CONVOY_HOME to a throwaway directory so
`python -m unittest` cannot write the machine index at ~/.convoy. test/run.py
uses the same guard; this is the belt for every other invocation.
It also installs test/harness_guard.py: no test may start a real harness CLI.
"""
from __future__ import annotations

from . import harness_guard
from .home_guard import ensure_throwaway_home


ensure_throwaway_home()
harness_guard.install()
