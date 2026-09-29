"""A proved CLI body cannot attribute any hook kind to another chair."""
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
from convoy.convoy import bind, seat
from convoy.layer import feed_since


class HookAuthorConflict(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="convoy-hook-author-home-")
        root = tempfile.TemporaryDirectory(prefix="convoy-hook-author-root-")
        self.addCleanup(home.cleanup)
        self.addCleanup(root.cleanup)
        self.env = mock.patch.dict(os.environ, {"CONVOY_HOME": home.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = Path(root.name)
        bind(self.root, "synthetic-hook-thread")
        seat(self.root, "codex", "chair-a", worktree=str(self.root))

    def _cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["--root", str(self.root), "hook", *args])
        return rc, json.loads(out.getvalue())

    def _rows(self):
        return feed_since(self.root, "1970-01-01T00:00:00Z")

    def test_proved_chair_conflict_refuses_every_unstamped_kind_without_write(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        for kind in ("heartbeat", "usage", "ack", "synthetic-custom"):
            with self.subTest(kind=kind), mock.patch("convoy.cli.identify", return_value=proof) as identify:
                rc, card = self._cli(kind, "claimed activity", "--instance-id", "chair-b")
                self.assertNotEqual(rc, 0)
                self.assertFalse(card["ok"])
                self.assertIn("author", card["error"])
                identify.assert_called_once()
                self.assertEqual(self._rows(), [])

    def test_matching_explicit_chair_still_writes_unstamped_row(self):
        proof = {"ok": True, "chair": "chair-a", "via": "environment", "harness": "codex"}
        with mock.patch("convoy.cli.identify", return_value=proof) as identify:
            rc, row = self._cli("heartbeat", "own activity", "--instance-id", "chair-a")
        self.assertEqual(rc, 0)
        identify.assert_called_once()
        self.assertEqual((row["kind"], row["from"]), ("heartbeat", "chair-a"))
        self.assertEqual(len(self._rows()), 1)

    def test_unproved_explicit_chair_remains_a_claim(self):
        with mock.patch("convoy.cli.identify", return_value={"ok": True, "chair": None}) as identify:
            rc, row = self._cli("usage", "unproved", "--instance-id", "chair-a")
        self.assertEqual(rc, 0)
        identify.assert_called_once()
        self.assertEqual(row["from"], "chair-a")


if __name__ == "__main__":
    unittest.main()
