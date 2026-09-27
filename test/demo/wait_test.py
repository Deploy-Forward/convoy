"""The waiter is slim by construction, and its death is visible.

A waiter started as `convoy inbox --wait` is `python -m convoy.cli`, which
imports crew, bringup, panes, widget and mcp_http before it can poll a
directory. Under memory pressure the OS kills such a process, and the chair
goes deaf while the feed still looks healthy:
nothing on disk said a waiter had ever existed, so nothing could say one was
gone.

Three guarantees:

1. Importing `convoy.wait` never pulls a heavy module into the process. The
   import list is the guarantee, not a comment at the top of the file.
2. The waiter touches the chair's pulse on a fixed cadence with
   pulse_source 'wait', on an injected clock - never a real sleep in a suite.
3. `.convoy/wait/<chair>.json` records the pid, when it started, when it
   expires and the incarnation it waits for. A killed waiter leaves it behind
   stale, on purpose: a stale pulse beside a live-looking wait file IS the
   diagnosis.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[2] / "src")
sys.path.insert(0, SRC)

from convoy.convoy import bind, seat  # noqa: E402
from convoy.inbox import enqueue  # noqa: E402
from convoy.pulse import read_pulse  # noqa: E402
from convoy.wait import read_wait_file, run  # noqa: E402

HEAVY = ("convoy.cli", "convoy.widget", "convoy.widget_web", "convoy.widget_service",
         "convoy.mcp_http", "convoy.bringup", "convoy.panes", "convoy.graph",
         "convoy.crew", "convoy.relaunch", "convoy.targeted_launch")


class SlimWaiter(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-wait-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-wait-wt-"))
        bind(self.root, "wait-test")
        seat(self.root, "codex", "w1", worktree=str(self.wt))

    def test_wait_module_imports_no_widget_or_cli(self):
        code = ("import sys; sys.path.insert(0, %r); import convoy.wait; "
                "print(sorted(m for m in sys.modules if m.startswith('convoy.')))" % SRC)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        loaded = set(json.loads(out.stdout.strip().replace("'", '"')))
        for heavy in HEAVY:
            self.assertNotIn(heavy, loaded,
                             heavy + " rides into every waiter; that is what the OS killed")

    def test_wait_writes_pulse_each_30s(self):
        ticks = iter([0.0, 10.0, 20.0, 31.0, 40.0, 61.0, 700.0])
        stamps = iter(["2026-09-17T00:00:00.000000Z", "2026-09-17T00:00:31.000000Z",
                       "2026-09-17T00:01:01.000000Z", "2026-09-17T00:11:40.000000Z"])
        written = []

        def fake_write(root, chair, **kw):
            row = {"chair": chair, **kw}
            written.append(row)
            return row

        card = run(self.root, "w1", timeout=600.0, incarnation=3,
                   clock=lambda: next(ticks), sleep=lambda _s: None,
                   now=lambda: next(stamps), pid=4321, write=fake_write)
        self.assertTrue(card["timed_out"], card)
        # One at start, then only when 30 s has passed on the injected clock.
        self.assertEqual(len(written), 3, written)
        self.assertEqual([r["pulse_source"] for r in written], ["wait", "wait", "wait"])
        self.assertEqual(written[0]["incarnation"], 3)

    def test_wait_file_records_pid_expiry_and_incarnation(self):
        run(self.root, "w1", timeout=600.0, incarnation=3, clock=iter([0.0, 700.0]).__next__,
            sleep=lambda _s: None, now=lambda: "2026-09-17T00:00:00.000000Z", pid=4321)
        row = read_wait_file(self.root, "w1")
        self.assertEqual(row["pid"], 4321)
        self.assertEqual(row["incarnation"], 3)
        self.assertEqual(row["started"], "2026-09-17T00:00:00.000000Z")
        self.assertEqual(row["expires"], "2026-09-17T00:10:00.000000Z")
        self.assertTrue(read_pulse(self.root, "w1"), "the waiter's own pulse must exist")

    def test_wait_returns_when_a_row_lands(self):
        enqueue(self.root, "w1", "a row", to="codex", label="synapse")
        card = run(self.root, "w1", timeout=600.0, incarnation=1,
                   clock=iter([0.0, 2.0]).__next__, sleep=lambda _s: None,
                   now=lambda: "2026-09-17T00:00:00.000000Z", pid=1)
        self.assertFalse(card["timed_out"], card)
        self.assertEqual(card["n"], 1)
        self.assertEqual(card["next"], "inbox --drain --seat w1")


if __name__ == "__main__":
    unittest.main()
