#!/usr/bin/env python3
"""Run demo tests. unittest default pattern test*.py misses *_test.py."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    # Tests mint temp roots; keep their index rows out of the real ~/.convoy.
    os.environ.setdefault("CONVOY_HOME", tempfile.mkdtemp(prefix="convoy-test-home-"))
    # The operator's machine may carry the legacy write flag at User scope
    # (2026-09-17: four "hidden by default" tests failed for that reason alone).
    # The suite starts with it unset; a test that wants it sets it explicitly.
    os.environ.pop("CONVOY_MCP_WRITE_TOOLS", None)
    start = ROOT / "test" / "demo"
    guard = os.environ["CONVOY_HOME"]
    suite = unittest.defaultTestLoader.discover(str(start), pattern="*_test.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if os.environ.get("CONVOY_HOME") != guard:
        print("FAIL: a test changed CONVOY_HOME; later tests may have written the real ~/.convoy index", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
