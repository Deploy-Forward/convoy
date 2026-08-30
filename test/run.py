#!/usr/bin/env python3
"""Run customer1 tests. unittest default pattern test*.py misses *_test.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    start = ROOT / "test" / "customer1"
    suite = unittest.defaultTestLoader.discover(str(start), pattern="*_test.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
