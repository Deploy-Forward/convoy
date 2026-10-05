"""A widget launch records the thread's lead as the launcher.

The widget is a person's local UI: there is no agent session to prove. So a widget start with
seats records `launched_by` = the thread's held lead chair (a plain chair string, so its neurons
report to the lead), and the launch card says `launcher.source: "widget-lead"`. With no held
lead (none or dangling) the widget refuses before writing a chair, naming the fix: attach an
agent session so it can lead. It never guesses a launcher and never records null.

Every id is synthetic; roots and the Convoy home are temporary; no harness or terminal runs.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_id  # noqa: E402
from convoy.convoy import bind, ensure_id, list_seats, read_id, seat  # noqa: E402
from convoy.lifecycle import lead_state, take_lead  # noqa: E402

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}
NO_LEAD = "this thread has no lead: attach an agent session (convoy attach <thread>) so it can lead, then start again"


def _repo() -> Path:
    d = Path(tempfile.mkdtemp())
    for argv in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", *argv], cwd=str(d), check=True, capture_output=True, text=True, timeout=30)
    return d


class WidgetLaunches(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-widget-lead-home-")
        self.addCleanup(home.cleanup)
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        p.start()
        self.addCleanup(p.stop)
        self.root = _repo()
        ensure_id(self.root)
        bind(self.root, "w")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.onboard.probe", {"return_value": dict(NULL_PROBE)})):
            q = mock.patch(target, **kw)
            q.start()
            self.addCleanup(q.stop)
        # The widget never resolves a launcher from its own process.
        q = mock.patch("convoy.launcher.resolve_launcher", side_effect=AssertionError("the widget guessed a launcher"))
        q.start()
        self.addCleanup(q.stop)

    def start(self):
        from convoy.widget_web import WidgetApi
        api = WidgetApi([self.root], probe_fn=lambda h: dict(NULL_PROBE), refresh_s=60)
        return api.start(None, ["codex"], "w", False, [{"harness": "codex", "title": "a"}], False)

    def test_a_held_lead_is_recorded_and_named_in_the_prompt(self):
        seat(self.root, "claude", "lead-chair", worktree=tempfile.mkdtemp(), resume="lead-native")
        take_lead(self.root, "lead-chair", lead_state(self.root))
        out = self.start()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["crew"]["launcher"]["source"], "widget-lead")
        new = next(s for s in list_seats(self.root) if s["session_id"] != "lead-chair")
        self.assertEqual(new["launched_by"], "lead-chair", "a plain chair string")
        self.assertIn(neuron_id(read_id(self.root), "lead-chair"), new["boot_prompt"])

    def test_no_held_lead_refuses_with_nothing_written(self):
        out = self.start()
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"], NO_LEAD)
        self.assertEqual(list_seats(self.root), [])
        self.assertEqual([p for p in self.root.parent.iterdir() if p.name.startswith(self.root.name + "-wt-")], [])

    def test_a_dangling_lead_refuses_too(self):
        from convoy.convoy import set_lead
        set_lead(self.root, "codex")   # a lead file naming a harness no chair holds
        self.assertEqual(lead_state(self.root)["status"], "dangling")
        out = self.start()
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["error"], NO_LEAD)
        self.assertEqual(list_seats(self.root), [])


class TheCliLaunchIsUnchanged(unittest.TestCase):
    def test_a_cli_seated_launcher_still_records_itself_with_no_widget_source(self):
        from convoy.launcher import seat_launcher
        root = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"CONVOY_HOME": tempfile.mkdtemp()}):
            bind(root, "cli")
            seat(root, "claude", "x-chair", resume="x-native")   # a chair launcher is a seated chair
            info = seat_launcher(root, {"kind": "seated", "chair": "x-chair", "via": "environment", "why": None})
        self.assertEqual(info["launched_by"], "x-chair")
        self.assertIsNone(info.get("source"))


if __name__ == "__main__":
    unittest.main()
