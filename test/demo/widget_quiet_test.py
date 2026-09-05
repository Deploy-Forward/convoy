"""The widget never opens a console and never waits on a vendor probe.

Live 2026-09-05 04:23-04:28Z: the detached widget service spawned a visible
console for every PowerShell pane scan and vendor probe on each 3 s tick
(black panes across the screen), and the first paint waited ~30 s on the
codex (17 s timeout) and claude (10 s) probes.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cmd import quiet_spawn_kwargs
from convoy.usage import CachedProbe


class QuietSpawn(unittest.TestCase):
    def test_no_window_flag_on_windows_nothing_elsewhere(self):
        with mock.patch("convoy.cmd.os.name", "nt"):
            self.assertEqual(quiet_spawn_kwargs(), {"creationflags": 0x08000000})
        with mock.patch("convoy.cmd.os.name", "posix"):
            self.assertEqual(quiet_spawn_kwargs(), {})

    def test_every_read_path_spawn_passes_the_flag(self):
        """Every subprocess call on the widget's read path carries it (source-level gate)."""
        src = Path(__file__).resolve().parents[2] / "src" / "convoy"
        for name in ("panes.py", "gitstate.py", "provenance.py", "widget.py", "cmd.py", "usage.py"):
            text = (src / name).read_text(encoding="utf-8")
            calls = [i for i in range(len(text)) if text.startswith("subprocess.run(", i)]
            for i in calls:
                window = text[i:i + 700]
                self.assertIn("quiet_spawn_kwargs()", window, name + " spawns a child without CREATE_NO_WINDOW near offset " + str(i))
        usage = (src / "usage.py").read_text(encoding="utf-8")
        self.assertIn('CREATE_NEW_PROCESS_GROUP | quiet_spawn_kwargs()["creationflags"]', usage)


class CachedProbeNeverBlocks(unittest.TestCase):
    def test_first_ask_is_unknown_and_probing_then_cached(self):
        calls = []
        pending = []
        def slow_probe(h):
            calls.append(h); return {"usage_remaining": {"session_pct": 42}, "limited": False, "raw": "x"}
        cp = CachedProbe(slow_probe, ttl_s=60, clock=lambda: 0.0, start_thread=pending.append)
        first = cp("codex")
        self.assertEqual(first, {"usage_remaining": None, "limited": False, "raw": None, "probing": True})
        self.assertEqual(calls, [], "the caller never ran the probe itself")
        self.assertEqual(len(pending), 1)
        # a second ask while in flight does not start a second probe
        cp("codex"); self.assertEqual(len(pending), 1)
        pending[0]()                                   # the worker runs
        self.assertEqual(calls, ["codex"])
        self.assertEqual(cp("codex")["usage_remaining"], {"session_pct": 42})
        self.assertNotIn("probing", cp("codex"))

    def test_ttl_refreshes_in_background_and_keeps_the_old_value_meanwhile(self):
        now = [0.0]; pending = []; n = [0]
        def p(h): n[0] += 1; return {"usage_remaining": n[0], "limited": False}
        cp = CachedProbe(p, ttl_s=10, clock=lambda: now[0], start_thread=pending.append)
        cp("claude"); pending.pop()(); self.assertEqual(cp("claude")["usage_remaining"], 1)
        now[0] = 11.0
        self.assertEqual(cp("claude")["usage_remaining"], 1, "stale value served while refreshing")
        self.assertEqual(len(pending), 1); pending.pop()()
        self.assertEqual(cp("claude")["usage_remaining"], 2)

    def test_probe_exception_is_unknown_never_a_number(self):
        pending = []
        def boom(h): raise RuntimeError("vendor down")
        cp = CachedProbe(boom, ttl_s=60, clock=lambda: 0.0, start_thread=pending.append)
        cp("codex"); pending.pop()()
        got = cp("codex")
        self.assertIsNone(got["usage_remaining"]); self.assertFalse(got["limited"]); self.assertEqual(got["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
