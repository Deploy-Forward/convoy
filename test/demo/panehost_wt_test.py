"""WtWalkAdapter: Alt+Arrow walk with title re-read; typed only into a proven idle pane.

Every OS call is a fake here. No real keystroke, no window action, ever.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.consent import grant_consent
from convoy.convoy import bind, ensure_id, seat
from convoy.layer import hook
from convoy.nudge import nudge_seat
from convoy.panehost import BUSY_RE, WtWalkAdapter, pane_belongs_to


class FakeOS:
    """Scripted WT: one title per hwnd; Alt+Arrow moves via a transition table."""

    def __init__(self, windows, moves=None, foreground_ok=True):
        # windows: {hwnd: title}; moves: {(hwnd, direction): new_title}
        self.windows = dict(windows)
        self.moves = dict(moves or {})
        self.foreground_ok = foreground_ok
        self.typed = []
        self.keys = []
        self.foregrounded = []

    def enum_windows(self):
        return [{"hwnd": h, "pid": 1, "title": t} for h, t in self.windows.items()]

    def title(self, hwnd):
        return self.windows.get(hwnd, "")

    def take_foreground(self, hwnd):
        self.foregrounded.append(hwnd)
        return self.foreground_ok

    def send_keys(self, hwnd, keys):
        self.keys.append((hwnd, keys))
        if keys.startswith("Alt+"):
            new = self.moves.get((hwnd, keys))
            if new is not None:
                self.windows[hwnd] = new
        else:
            self.typed.append((hwnd, keys))
        return True

    def sleep(self, _s):
        return None


def _seat(worktree="C:/x/convoy-wt-happy-wt-g2", title="g2", to="grok"):
    return {"session_id": "g2", "worktree": worktree, "title": title, "to": to}


class BelongsTo(unittest.TestCase):
    def test_worktree_folder_name_rule(self):
        self.assertEqual(pane_belongs_to(_seat(), "convoy-wt-happy-wt-g2"), "worktree")

    def test_seat_title_exact_or_prefix_rule(self):
        self.assertEqual(pane_belongs_to(_seat(), "g2"), "seat-title")
        self.assertEqual(pane_belongs_to(_seat(), "g2 - grok"), "seat-title")
        self.assertIsNone(pane_belongs_to(_seat(), "Dry-run nudge identity for g2 - grok"))

    def test_generic_title_alone_is_not_identity(self):
        self.assertIsNone(pane_belongs_to(_seat(), "grok"))

    def test_crew_window_plus_sole_idle_chair_rule(self):
        rule = pane_belongs_to(_seat(), "grok", hwnd=11, crew_hwnd=11, idle_chairs=["g2"])
        self.assertEqual(rule, "crew-window+sole-idle")
        # two idle grok chairs: ambiguous, refuse
        self.assertIsNone(pane_belongs_to(_seat(), "grok", hwnd=11, crew_hwnd=11, idle_chairs=["g1", "g2"]))
        # other window than the recorded one
        self.assertIsNone(pane_belongs_to(_seat(), "grok", hwnd=12, crew_hwnd=11, idle_chairs=["g2"]))
        # no crew window recorded: null, never assumed
        self.assertIsNone(pane_belongs_to(_seat(), "grok", hwnd=11, crew_hwnd=None, idle_chairs=["g2"]))


class Walk(unittest.TestCase):
    def _walk(self, fake, **kw):
        kw.setdefault("idle_title_re", r"^grok$")
        kw.setdefault("crew_hwnd", 11)
        kw.setdefault("idle_chairs", ["g2"])
        return WtWalkAdapter(os_=fake).walk(_seat(), "hello", **kw)

    def test_requires_exactly_one_candidate_window(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        card = self._walk(fake, crew_hwnd=None)
        self.assertFalse(card["ok"])
        self.assertIn("candidate", card["error"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(fake.foregrounded, [])
        self.assertIsNone(card["rule"])

    def test_foreground_refused_types_nothing(self):
        fake = FakeOS({11: "grok"}, foreground_ok=False)
        card = self._walk(fake)
        self.assertFalse(card["ok"])
        self.assertIn("foreground", card["error"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(fake.keys, [])

    def test_busy_pane_is_never_typed(self):
        fake = FakeOS({11: "Waiting for response..."})
        card = self._walk(fake, directions=("none",))
        self.assertFalse(card["ok"])
        self.assertEqual(fake.typed, [])
        self.assertIn("busy", card["steps"][0]["skip"])
        for busy in ("Running: bash", "Thinking about it", "Waiting for response..."):
            self.assertTrue(BUSY_RE.search(busy), busy)

    def test_focus_did_not_move_is_skipped(self):
        # right-most pane: Alt+Right moves nothing; title unchanged -> skip, no type
        fake = FakeOS({11: "? - a prompt - grok"}, moves={})
        card = self._walk(fake, directions=("none", "Alt+Right"))
        self.assertFalse(card["ok"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(card["steps"][1]["skip"], "focus did not move")

    def test_double_fire_scenario_types_exactly_once(self):
        # 05:57Z live: focused pane idle -> typed; Alt+Left did not move -> the
        # walk must NOT type again; Alt+Right reaches a busy pane -> not typed.
        fake = FakeOS(
            {11: "grok"},
            moves={(11, "Alt+Right"): "Running: bash"},  # Alt+Left absent = no move
        )
        card = self._walk(fake, directions=("none", "Alt+Left", "Alt+Right"))
        self.assertTrue(card["ok"], card)
        self.assertEqual(len(fake.typed), 1)
        self.assertEqual(fake.typed[0], (11, "hello\n"))
        self.assertEqual(card["pane_title_before"], "grok")
        self.assertEqual(card["pane_title_after"], "grok")
        self.assertEqual(card["rule"], "crew-window+sole-idle")
        self.assertEqual([k for _, k in fake.keys if k.startswith("Alt+")], [])

    def test_walk_reaches_idle_pane_after_move(self):
        fake = FakeOS(
            {11: "Waiting for response..."},
            moves={(11, "Alt+Right"): "grok"},
        )
        card = self._walk(fake, directions=("none", "Alt+Right"))
        self.assertTrue(card["ok"], card)
        self.assertEqual(fake.typed, [(11, "hello\n")])
        self.assertEqual(card["pane_title_before"], "Waiting for response...")
        self.assertEqual(card["pane_title_after"], "grok")
        self.assertEqual(fake.keys[0], (11, "Alt+Right"))

    def test_idle_title_that_belongs_to_nobody_is_not_typed(self):
        fake = FakeOS({11: "grok"})
        card = self._walk(fake, crew_hwnd=11, idle_chairs=["g1", "g2"])
        self.assertFalse(card["ok"])
        self.assertEqual(fake.typed, [])
        self.assertIn("belongs", card["steps"][0]["skip"])

    def test_no_real_os_outside_windows(self):
        with mock.patch("convoy.panehost.os.name", "posix"):
            card = WtWalkAdapter().walk(_seat(), "x", idle_title_re="^grok$")
        self.assertFalse(card["ok"])
        self.assertIn("Windows", card["error"])


def _panes(sid, bodies):
    return lambda _root: {"ok": True, "chairs": [{"session_id": sid, "bodies": bodies, "duplicate": False, "live": True}], "unassigned": []}


class NudgeWalkOptIn(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "walk-t")
        self.wt = Path(tempfile.mkdtemp()) / "convoy-wt-happy-wt-g2"
        self.wt.mkdir()
        seat(self.root, "grok", "g2", worktree=str(self.wt), title="g2")
        hook(self.root, "crew-window", "wt window for this crew", None, extra={"hwnd": 11})
        self.body = {"pid": 101288, "via": "worktree", "exe": "grok"}
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("TMUX", None)
        self.addCleanup(self.env.stop)
        self.windows = lambda: [{"hwnd": 11, "pid": 99004, "title": "grok"}, {"hwnd": 12, "pid": 99004, "title": "grok"}]

    def test_default_nudge_still_refuses_without_walk(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                self.root, "g2", keys="hello",
                panes_fn=_panes("g2", [self.body]), windows_fn=self.windows,
                leader_fn=lambda: {"available": False}, walk_adapter=WtWalkAdapter(os_=fake),
            )
        self.assertFalse(card["identified"])
        self.assertIn("no unique title", card["reason"])
        self.assertIsNone(card["delivery"])
        self.assertEqual(fake.typed, [])

    def test_walk_opt_in_consents_then_types_once(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = dict(
            keys="hello", walk=True,
            panes_fn=_panes("g2", [self.body]), windows_fn=self.windows,
            leader_fn=lambda: {"available": False},
            walk_adapter=WtWalkAdapter(os_=fake), idle_chairs_fn=lambda _r, _h: ["g2"],
        )
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            self.assertEqual(waiting["state"], "awaiting-user-consent")
            self.assertIn("wt-walk", waiting["consent_request"]["prompt"])
            self.assertEqual(fake.typed, [])
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(self.root, "g2", consent=token, **kw)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["adapter"], "wt-walk")
        self.assertEqual(card["delivery"], "nudged")
        self.assertFalse(card["delivered"])
        self.assertEqual(card["walk"]["rule"], "crew-window+sole-idle")
        self.assertEqual(fake.typed, [(11, "hello\n")])

    def test_walk_without_crew_window_row_refuses(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "walk-u")
        seat(root, "grok", "g2", worktree=str(self.wt), title="g2")
        fake = FakeOS({11: "grok", 12: "grok"})
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(
                root, "g2", keys="hello", walk=True, dry_run=True,
                panes_fn=_panes("g2", [self.body]), windows_fn=self.windows,
                leader_fn=lambda: {"available": False}, walk_adapter=WtWalkAdapter(os_=fake),
                idle_chairs_fn=lambda _r, _h: ["g2"],
            )
        self.assertFalse(card["identified"])
        self.assertIsNone(card["walk"]["crew_hwnd"])
        self.assertEqual(fake.typed, [])


if __name__ == "__main__":
    unittest.main()
