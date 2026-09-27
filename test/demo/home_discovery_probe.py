"""Imported only by the no-PYTHONPATH direct-discovery contract test."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.local_install import _home
from convoy.index import home_dir


class DirectDiscoveryHomeProbe(unittest.TestCase):
    def test_home_is_throwaway_before_index_use(self):
        # This accessor bypasses index.home_dir. Importing any Convoy module
        # must already have established the safe test home.
        home = _home().resolve()
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertNotEqual(home, temp)
        self.assertTrue(home.is_relative_to(temp), home)
        self.assertEqual(os.environ.get("CONVOY_HOME"), str(home))
        self.assertEqual(home_dir().resolve(), home)
