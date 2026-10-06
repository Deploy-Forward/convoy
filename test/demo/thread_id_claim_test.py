"""One convoy id is one thread at one path, and every root with an id is in the index.

A copied root carried its original's .convoy/id and was accepted as that thread: binding the
copy repointed the original's index row, after which attaching the original failed with
"unknown thread". A root whose id was never indexed (start or init on it) stayed out of the
index, so attach refused it. The id is now claimed: indexed when absent or at the same path,
refused when it is the live thread at another path, with `init --new-id` as the way out.
"""
import io
import json
import shutil
import sys
import tempfile
import uuid
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, read_id
from convoy.index import list_threads
from convoy.onboard import _thread_bind


def _run(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = out.getvalue().strip()
    return rc, (json.loads(raw) if raw else None)


def _rows(cid):
    return [r for r in list_threads() if r.get("convoy_id") == cid]


def _same(a, b):
    return Path(a).resolve() == Path(b).resolve()


class ThreadIdClaim(unittest.TestCase):
    def setUp(self):
        self.original = Path(tempfile.mkdtemp())
        self.cid = ensure_id(self.original)
        bind(self.original, "claimed")
        self.copy = Path(tempfile.mkdtemp()) / "copy"
        shutil.copytree(self.original, self.copy)

    def unindexed(self):
        root = Path(tempfile.mkdtemp())
        (root / ".convoy").mkdir()
        cid = "cvy_unindexed" + uuid.uuid4().hex[:12]   # unique: the test index is shared
        (root / ".convoy" / "id").write_text(cid + "\n", encoding="utf-8")
        self.assertEqual(_rows(cid), [])
        return root, cid

    def test_start_indexes_existing_unindexed_id(self):
        root, cid = self.unindexed()
        _thread_bind(root, None)       # start and onboard on a root that already has an id
        [row] = _rows(cid)
        self.assertTrue(_same(row["root"], root))

    def test_init_indexes_existing_unindexed_id(self):
        root, cid = self.unindexed()
        rc, card = _run(root, "init")
        self.assertEqual(rc, 0, card)
        [row] = _rows(cid)
        self.assertTrue(_same(row["root"], root))

    def test_start_refuses_id_already_indexed_at_other_path(self):
        convoy_id, _bound, status = _thread_bind(self.copy, None)
        self.assertIn("error", status)
        rc, card = _run(self.copy, "init")
        self.assertNotEqual(rc, 0, card)
        self.assertFalse(card["ok"])
        for text in (str(self.original.resolve()), str(self.copy.resolve()), "init --new-id"):
            self.assertIn(text, card["error"])

    def test_bind_on_copy_does_not_repoint_original(self):
        with self.assertRaises(ValueError):
            bind(self.copy, "claimed")
        [row] = _rows(self.cid)
        self.assertTrue(_same(row["root"], self.original))

    def test_init_new_id_gives_the_copy_its_own_id(self):
        rc, card = _run(self.copy, "init", "--new-id")
        self.assertEqual(rc, 0, card)
        self.assertNotEqual(card["convoy_id"], self.cid)
        self.assertEqual(read_id(self.copy), card["convoy_id"])
        self.assertTrue(_same(_rows(self.cid)[0]["root"], self.original))
        self.assertTrue(_same(_rows(card["convoy_id"])[0]["root"], self.copy))

    def test_a_moved_root_keeps_its_id(self):
        shutil.rmtree(self.original)
        self.assertEqual(ensure_id(self.copy), self.cid)
        self.assertTrue(_same(_rows(self.cid)[0]["root"], self.copy))


if __name__ == "__main__":
    unittest.main()
