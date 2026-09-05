"""Widget model: folds rail/panes/seats/recent/feed/inbox. No Tk."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.convoy import bind, ensure_id, set_github
from convoy.lifecycle import join, seated_ack
from convoy.widget import build_widget_model, _usage_display


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo(remote: str | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q")
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git(d, "add", "README.md")
    _git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    if remote:
        _git(d, "remote", "add", "origin", remote)
    return d


NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}


class WidgetModel(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)

        self.t1 = _git_repo()
        ensure_id(self.t1)
        bind(self.t1, "one")
        set_github(self.t1, False)
        j1 = join(self.t1, "grok", session_id="g-one", worktree=str(self.t1), effort="high")
        seated_ack(self.t1, "g-one", j1["token"])

        self.t2 = _git_repo(remote="https://github.com/acme/api.git")
        ensure_id(self.t2)
        bind(self.t2, "two")
        set_github(self.t2, True)
        join(self.t2, "claude", session_id="c-two", worktree=str(self.t2), model="claude-opus-5")

        self.procs = [
            {"pid": 12, "ppid": 1, "cmdline": "grok --resume unused", "cwd": str(self.t1)},
            {"pid": 13, "ppid": 1, "cmdline": "claude --resume unused", "cwd": None},
        ]

    def _model(self, **kw):
        return build_widget_model(
            [self.t1, self.t2],
            probe_fn=lambda _h: dict(NULL_PROBE),
            **kw,
        )

    def test_two_threads_dots_newest_shape(self):
        card = self._model()
        self.assertTrue(card["ok"])
        self.assertEqual([t["dot"] for t in card["threads"]], ["·1", "·2"])
        self.assertEqual([t["thread"] for t in card["threads"]], ["one", "two"])

    def test_github_no_shows_no_url_yes_shows_real_remote(self):
        card = self._model()
        one, two = card["threads"]
        self.assertFalse(one["repo"]["connected"])
        self.assertIsNone(one["repo"]["url"])
        self.assertEqual(one["repo"]["github"], "no")
        self.assertTrue(two["repo"]["connected"])
        self.assertEqual(two["repo"]["url"], "https://github.com/acme/api.git")

    def test_connected_and_pending_states(self):
        card = self._model()
        one, two = card["threads"]
        self.assertEqual(one["chairs"][0]["state"], "connected")
        self.assertEqual(two["chairs"][0]["state"], "pending")
        self.assertIn("seat", one["chairs"][0]["tune"])
        self.assertIn("swap --seat g-one", one["chairs"][0]["tune"]["swap"])
        self.assertIn("focus --seat", one["chairs"][0]["focus"])

    def test_live_body_only_when_panes_proves_a_process(self):
        procs = [{"pid": 99, "ppid": 1, "cmdline": "grok -d " + str(self.t1), "cwd": str(self.t1)}]
        card = self._model(enumerate_fn=lambda: procs)
        self.assertTrue(card["threads"][0]["chairs"][0]["live_body"])
        card2 = self._model(enumerate_fn=lambda: [])
        self.assertFalse(card2["threads"][0]["chairs"][0]["live_body"])

    def test_usage_null_renders_unknown_never_zero(self):
        self.assertEqual(_usage_display({"usage_remaining": None}), "unknown")
        card = self._model()
        for t in card["threads"]:
            for harness, u in t["usage"].items():
                self.assertEqual(u["display"], "unknown", harness)
                self.assertIsNone(u["usage_remaining"])
                self.assertNotEqual(u["display"], "0")
                self.assertNotEqual(u["usage_remaining"], 0)

    def test_tune_is_command_text_not_applied(self):
        seats = (self.t1 / ".convoy" / "seats.jsonl").read_text(encoding="utf-8")
        card = self._model()
        cmd = card["threads"][0]["chairs"][0]["tune"]["seat"]
        self.assertIn("seat --to grok", cmd)
        self.assertEqual((self.t1 / ".convoy" / "seats.jsonl").read_text(encoding="utf-8"), seats)


try:
    import tkinter as _tk  # noqa: F401
    _HAS_TK = True
except Exception:
    _HAS_TK = False


@unittest.skipUnless(_HAS_TK, "tkinter missing")
class WidgetWindow(unittest.TestCase):
    def test_builds_without_mainloop(self):
        from convoy.widget import run_widget
        root = _git_repo()
        ensure_id(root)
        bind(root, "w")
        card = run_widget([root], loop=False, probe_fn=lambda _h: dict(NULL_PROBE))
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["threads"], 1)
        self.assertFalse(card.get("loop", True))


if __name__ == "__main__":
    unittest.main()
