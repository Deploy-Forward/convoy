"""Guard direct unittest discovery from this source checkout.

`python -m unittest discover -s test/demo` imports tests as top-level modules,
bypassing both test package initializers. Python loads this checkout-local
sitecustomize at startup when run from the repository; guard only discovery
under this repository's test tree. Installed Convoy does not package this file.
"""
from __future__ import annotations

from pathlib import Path
import unittest


_TEST_TREE = (Path(__file__).resolve().parent / "test").resolve()
_original_discover = unittest.TestLoader.discover


def _discover_with_safe_home(self, start_dir, *args, **kwargs):
    try:
        under_our_tests = Path(start_dir).resolve().is_relative_to(_TEST_TREE)
    except (OSError, TypeError, ValueError):
        under_our_tests = False
    if under_our_tests:
        # Importing test establishes the throwaway home and harness-spawn guard
        # before discover imports any top-level *_test.py module.
        import test  # noqa: F401
    return _original_discover(self, start_dir, *args, **kwargs)


unittest.TestLoader.discover = _discover_with_safe_home
