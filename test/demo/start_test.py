"""convoy start: picker / clone+onboard / attach; never auto-pick, never bring_up."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, read_github, read_id, seat
from convoy.start import start


ROOT = Path(__file__).resolve().parents[2]
FAKES = (ROOT / "test" / "fakes").resolve()


def _run_cli(root: Path, *argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


def _live(_root):
    return {"ok": True, "chair": "g1", "on_thread": True, "harness": "grok"}


def _dead(_root):
    return {"ok": False, "chair": None, "on_thread": False}


def _empty_roster(_root):
    return {"ok": True, "chairs": []}


def _live_roster(_root):
    return {"ok": True, "chairs": [{"session_id": "g1", "live": True}]}


class StartAlias(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home), "PATH": str(FAKES)})
        self._env.start()
        self.addCleanup(self._env.stop)
        self._home = mock.patch("convoy.bringup.Path.home", return_value=Path(tempfile.mkdtemp()))
        self._home.start()
        self.addCleanup(self._home.stop)

    def test_no_repo_empty_index_asks_new_thread(self):
        card = start(self.root)
        self.assertFalse(card["ok"])
        self.assertEqual(card["ask"], "new thread")
        self.assertEqual(card["threads"], [])
        self.assertFalse(card["bound"])
        self.assertFalse(card["brought_up"])

    def test_no_repo_many_threads_requires_picker_never_auto_picks(self):
        rows = [
            {"thread": "old", "root": "/a", "updated_at": "2026-09-01T00:00:00Z", "convoy_id": "cvy_old", "present": True},
            {"thread": "new", "root": "/b", "updated_at": "2026-09-05T00:00:00Z", "convoy_id": "cvy_new", "present": True},
        ]
        with mock.patch("convoy.start.recent", return_value=rows):
            card = start(self.root)
        self.assertFalse(card["ok"])
        self.assertEqual(card["ask"], "pick")
        self.assertEqual([t["title"] for t in card["threads"]], ["old", "new"])
        self.assertEqual(card["threads"][0]["root"], "/a")
        self.assertEqual(card["threads"][1]["updated_at"], "2026-09-05T00:00:00Z")
        self.assertIsNone(read_id(self.root))
        self.assertFalse(card["brought_up"])

    def test_cancel_leaves_unbound(self):
        card = start(self.root, str(self.root), harnesses=["grok"], cancel=True)
        self.assertTrue(card["ok"])
        self.assertEqual(card["ask"], "cancelled")
        self.assertFalse(card["bound"])
        self.assertIsNone(read_id(self.root))

    def test_local_path_onboards_github_no(self):
        checkout = Path(tempfile.mkdtemp())
        card = start(self.root, str(checkout), harnesses=["grok"], thread="demo",
                     identify_fn=_dead, bodies_fn=_empty_roster)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["thread"], "demo")
        self.assertEqual(read_github(checkout), "no")
        self.assertFalse(card["brought_up"])

    def test_git_url_clones_once_onboards_github_yes_without_gh(self):
        url = "https://github.com/acme/api.git"
        expected = self.home / "checkouts" / "acme" / "api"

        def runner(argv, cwd=None, **_k):
            dest = Path(argv[-1])
            (dest / ".git" / "info").mkdir(parents=True)
            import subprocess
            return subprocess.CompletedProcess(argv, 0, "", "")

        card = start(self.root, url, harnesses=["grok"], thread="demo",
                     clone_runner=runner, identify_fn=_dead, bodies_fn=_empty_roster)
        self.assertTrue(card["ok"], card)
        self.assertEqual(read_github(expected), "yes")
        self.assertTrue(card.get("repo", {}).get("cloned"))
        self.assertFalse(card["brought_up"])
        self.assertNotIn("gh ", json.dumps(card))

    def test_option_shaped_url_is_refused_not_invented(self):
        card = start(self.root, "--upload-pack=calc x://h/o/r", harnesses=["grok"])
        self.assertFalse(card["ok"])
        self.assertIn("starting with '-'", card["error"])
        self.assertFalse(card.get("bound"))

    def test_already_live_attaches_and_does_not_bring_up(self):
        ensure_id(self.root)
        bind(self.root, "demo")
        seat(self.root, "grok", "g1", worktree=str(self.root))
        import convoy.start as mod
        self.assertFalse(hasattr(mod, "bring_up"))
        card = start(self.root, str(self.root), harnesses=["grok"],
                     identify_fn=_live, bodies_fn=_live_roster)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card.get("attached"))
        self.assertFalse(card["brought_up"])
        self.assertEqual(card["thread"], "demo")
        self.assertIn("seats", card)
        self.assertTrue(card.get("convoy_id"))

    def test_cli_start_no_repo_is_picker_or_new(self):
        rc, card = _run_cli(self.root, "start")
        self.assertEqual(rc, 1)
        self.assertIn(card["ask"], ("pick", "new thread"))
        self.assertFalse(card["brought_up"])


if __name__ == "__main__":
    unittest.main()
