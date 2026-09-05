"""WtWalkAdapter: Alt+Arrow walk with title re-read; typed only into a proven idle pane.

Every OS call is a fake here. No real keystroke, no window action, ever.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.consent import grant_consent
from convoy.convoy import bind, ensure_id, seat
from convoy.layer import feed_since, hook
from convoy.nudge import last_unacked_nudge, nudge_seat
from convoy.wt_walk import BUSY_RE, WtWalkAdapter, pane_belongs_to, record_crew_window


class FakeOS:
    """Scripted WT: one title per hwnd; Alt+Arrow moves via a transition table."""

    def __init__(self, windows, moves=None, foreground_ok=True, foreground_hwnd=None):
        # windows: {hwnd: title}; moves: {(hwnd, direction): new_title}
        self.windows = dict(windows)
        self.moves = dict(moves or {})
        self.foreground_ok = foreground_ok
        self.foreground_hwnd = foreground_hwnd
        self.typed = []
        self.keys = []
        self.foregrounded = []

    def enum_windows(self):
        return [{"hwnd": h, "pid": 1, "title": t} for h, t in self.windows.items()]

    def title(self, hwnd):
        return self.windows.get(hwnd, "")

    def foreground(self):
        return self.foreground_hwnd

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


def _rows(root, kind):
    return [r for r in feed_since(root, "1970-01-01T00:00:00Z") if r.get("kind") == kind]


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

    def test_probe_walks_to_the_pane_but_types_nothing(self):
        # pseudocode WtAdapter.focus: same walk, stop at the match, type nothing
        fake = FakeOS({11: "Waiting for response..."}, moves={(11, "Alt+Right"): "grok"})
        card = self._walk(fake, directions=("none", "Alt+Right"), type_text=False)
        self.assertTrue(card["ok"], card)
        self.assertFalse(card["typed"])
        self.assertEqual(card["pane_title_after"], "grok")
        self.assertEqual(card["rule"], "crew-window+sole-idle")
        self.assertEqual(fake.typed, [])
        self.assertEqual(fake.keys, [(11, "Alt+Right")])

    def test_expect_title_refuses_a_pane_that_is_not_the_consented_one(self):
        fake = FakeOS({11: "grok"})
        card = self._walk(fake, directions=("none",), expect_title="g2 - grok")
        self.assertFalse(card["ok"])
        self.assertEqual(fake.typed, [])
        self.assertIn("consented pane", card["steps"][0]["skip"])

    def test_no_real_os_outside_windows(self):
        with mock.patch("convoy.wt_walk.os.name", "posix"):
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
        # the row the product writes via `convoy crew-window` (record_crew_window); no other writer exists
        rec = record_crew_window(self.root, hwnd=11, os_=FakeOS({11: "grok", 12: "grok"}))
        self.assertTrue(rec["ok"], rec)
        self.body = {"pid": 101288, "via": "worktree", "exe": "grok"}
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("TMUX", None)
        self.addCleanup(self.env.stop)
        self.windows = lambda: [{"hwnd": 11, "pid": 99004, "title": "grok"}, {"hwnd": 12, "pid": 99004, "title": "grok"}]

    def _kw(self, fake, **extra):
        kw = dict(
            keys="hello", walk=True,
            panes_fn=_panes("g2", [self.body]), windows_fn=self.windows,
            leader_fn=lambda: {"available": False},
            walk_adapter=WtWalkAdapter(os_=fake), idle_chairs_fn=lambda _r, _h: ["g2"],
        )
        kw.update(extra)
        return kw

    def test_default_nudge_still_refuses_without_walk(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(self.root, "g2", **self._kw(fake, walk=False))
        self.assertFalse(card["identified"])
        self.assertIn("no unique title", card["reason"])
        self.assertIsNone(card["delivery"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(_rows(self.root, "nudge"), [])

    def test_walk_opt_in_consent_names_the_pane_then_types_once_with_rows(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            self.assertEqual(waiting["state"], "awaiting-user-consent")
            prompt = waiting["consent_request"]["prompt"]
            # the card names the PANE the focus-only probe found, and the rule that proved it
            self.assertIn("wt-walk HWND 11 pane title='grok' rule=crew-window+sole-idle", prompt)
            self.assertEqual(fake.typed, [])
            self.assertEqual(_rows(self.root, "nudge"), [])  # a consent request writes no nudge row
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(self.root, "g2", consent=token, **kw)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["adapter"], "wt-walk")
        self.assertEqual(card["delivery"], "nudged")
        self.assertFalse(card["delivered"])
        self.assertEqual(card["walk"]["rule"], "crew-window+sole-idle")
        nid = card["nudge_id"]
        self.assertTrue(card["tag_in_text"])
        self.assertEqual(fake.typed, [(11, "hello nudge=" + nid + "\n")])
        rows = _rows(self.root, "nudge")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nudge_id"], nid)
        self.assertEqual(rows[0]["instance_id"], "g2")
        self.assertEqual(rows[0]["transport"], "wt-walk")
        self.assertIs(rows[0]["delivered"], False)
        self.assertNotIn("from", rows[0])  # author unknown, never promoted to the target
        res = _rows(self.root, "nudge-result")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["nudge_id"], nid)
        self.assertIs(res[0]["ok"], True)
        self.assertEqual(res[0]["pane_title_after"], "grok")
        all_rows = feed_since(self.root, "1970-01-01T00:00:00Z")
        kinds = [r["kind"] for r in all_rows if r["kind"] in ("nudge", "nudge-result")]
        self.assertEqual(kinds, ["nudge", "nudge-result"])  # row first, result after

    def test_second_nudge_refused_until_the_chair_acks_the_id(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            first = nudge_seat(self.root, "g2", consent=token, **kw)
            self.assertTrue(first["ok"], first)
            again = nudge_seat(self.root, "g2", **kw)
            self.assertFalse(again["ok"])
            self.assertIn("has no ack", again["reason"])
            self.assertEqual(again["unacked_nudge_id"], first["nudge_id"])
            self.assertIsNone(again["delivery"])
            self.assertNotIn("consent_request", again)
            self.assertEqual(len(fake.typed), 1)
            # the chair acks by citing the id in its own row; then a nudge may proceed
            hook(self.root, "note", "drained; nudge=" + first["nudge_id"], "g2")
            self.assertIsNone(last_unacked_nudge(self.root, "g2"))
            waiting2 = nudge_seat(self.root, "g2", **kw)
            self.assertEqual(waiting2["state"], "awaiting-user-consent")

    def test_ack_from_another_chair_does_not_count(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            first = nudge_seat(self.root, "g2", consent=token, **kw)
        hook(self.root, "note", "nudge=" + first["nudge_id"], "g1")
        self.assertEqual(last_unacked_nudge(self.root, "g2"), first["nudge_id"])

    def test_force_repeats_over_an_unacked_nudge_and_records_it(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            w = nudge_seat(self.root, "g2", **kw)
            first = nudge_seat(self.root, "g2", consent=grant_consent(self.root, w["consent_request"]["request_id"])["consent"], **kw)
            w2 = nudge_seat(self.root, "g2", force=True, **kw)
            self.assertEqual(w2["state"], "awaiting-user-consent")
            second = nudge_seat(self.root, "g2", force=True, consent=grant_consent(self.root, w2["consent_request"]["request_id"])["consent"], **kw)
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["forced_over"], first["nudge_id"])
        self.assertEqual(len(fake.typed), 2)
        self.assertEqual(len(_rows(self.root, "nudge")), 2)

    def test_pane_changed_between_consent_and_typing_refuses_and_types_nothing(self):
        fake = FakeOS({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            fake.windows[11] = "g2 - grok"  # still this chair by title, but not the consented pane
            card = nudge_seat(self.root, "g2", consent=token, **kw)
        # the probe re-runs at typing time; the consented pane is gone, so it refuses
        # before consent is consumed (probe failure here; a scope mismatch if another
        # pane had matched instead). Either way: nothing typed, no nudge row.
        self.assertFalse(card["ok"])
        self.assertIn("probe", card["reason"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(_rows(self.root, "nudge"), [])

    def test_pane_moved_after_consume_records_a_failed_result(self):
        # the probe and the consent agree, but the typing walk finds the pane changed
        class Flip(FakeOS):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.probes = 0

            def take_foreground(self, hwnd):
                self.probes += 1
                if self.probes == 3:  # first live typing walk after two probes
                    self.windows[11] = "g2 - grok"
                return super().take_foreground(hwnd)

        fake = Flip({11: "grok", 12: "grok"})
        kw = self._kw(fake)
        with mock.patch("convoy.nudge.os.name", "nt"):
            waiting = nudge_seat(self.root, "g2", **kw)
            token = grant_consent(self.root, waiting["consent_request"]["request_id"])["consent"]
            card = nudge_seat(self.root, "g2", consent=token, **kw)
        self.assertFalse(card["ok"], card)
        self.assertEqual(card["delivery"], "failed")
        self.assertIn("wt-walk refused", card["reason"])
        self.assertEqual(fake.typed, [])
        self.assertEqual(len(_rows(self.root, "nudge")), 1)
        res = _rows(self.root, "nudge-result")
        self.assertEqual(len(res), 1)
        self.assertIs(res[0]["ok"], False)

    def test_probe_failure_refuses_before_consent_and_writes_nothing(self):
        fake = FakeOS({11: "grok", 12: "grok"}, foreground_ok=False)
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(self.root, "g2", **self._kw(fake))
        self.assertFalse(card["ok"])
        self.assertIn("probe", card["reason"])
        self.assertNotIn("consent_request", card)
        self.assertEqual(fake.typed, [])
        self.assertEqual(_rows(self.root, "nudge"), [])

    def test_walk_without_crew_window_row_refuses(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "walk-u")
        seat(root, "grok", "g2", worktree=str(self.wt), title="g2")
        fake = FakeOS({11: "grok", 12: "grok"})
        with mock.patch("convoy.nudge.os.name", "nt"):
            card = nudge_seat(root, "g2", dry_run=True, **self._kw(fake))
        self.assertFalse(card["identified"])
        self.assertIsNone(card["walk"]["crew_hwnd"])
        self.assertEqual(fake.typed, [])


class CrewWindowWriter(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "cw-t")

    def test_foreground_records_the_wt_window_via_hook(self):
        fake = FakeOS({11: "grok", 12: "codex"}, foreground_hwnd=12)
        card = record_crew_window(self.root, foreground=True, os_=fake)
        self.assertTrue(card["ok"], card)
        self.assertEqual((card["hwnd"], card["title"]), (12, "codex"))
        rows = _rows(self.root, "crew-window")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hwnd"], 12)
        self.assertEqual(fake.typed, [])
        self.assertEqual(fake.foregrounded, [])

    def test_hwnd_that_is_not_a_wt_window_is_refused(self):
        card = record_crew_window(self.root, hwnd=99, os_=FakeOS({11: "grok"}))
        self.assertFalse(card["ok"])
        self.assertFalse(card["recorded"])
        self.assertEqual(_rows(self.root, "crew-window"), [])

    def test_no_hwnd_and_no_foreground_flag_refuses(self):
        card = record_crew_window(self.root, os_=FakeOS({11: "grok"}))
        self.assertFalse(card["ok"])
        self.assertIn("--hwnd", card["error"])

    def test_no_real_os_outside_windows(self):
        with mock.patch("convoy.wt_walk.os.name", "posix"):
            card = record_crew_window(self.root, hwnd=11)
        self.assertFalse(card["ok"])
        self.assertIn("Windows", card["error"])


class CliWiring(unittest.TestCase):
    def _help(self, *argv):
        src = str(Path(__file__).resolve().parents[2] / "src")
        env = {**os.environ, "PYTHONPATH": src}
        return subprocess.run([sys.executable, "-m", "convoy", *argv, "--help"],
                              capture_output=True, text=True, cwd=src, env=env).stdout

    def test_nudge_has_walk_and_force(self):
        out = self._help("nudge")
        self.assertIn("--walk", out)
        self.assertIn("--force", out)

    def test_crew_window_subcommand_exists(self):
        out = self._help("crew-window")
        self.assertIn("--foreground", out)
        self.assertIn("--hwnd", out)


if __name__ == "__main__":
    unittest.main()
