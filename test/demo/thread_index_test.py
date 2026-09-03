"""Machine-level thread index (Marco 2026-09-02): chats launch from project
folders, so .convoy must be findable globally, like Claude's /resume.
~/.convoy/threads.json holds {convoy_id, thread, root, updated_at} rows and
nothing else; every init/bind/seat upserts its row. Roots that vanished
render present=false, never as a thread."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.index import find_root, index_path, list_threads, record


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class ThreadIndex(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        os.environ["CONVOY_HOME"] = str(self.home)
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        os.environ.pop("CONVOY_HOME", None)

    def test_index_path_honours_convoy_home(self):
        self.assertEqual(index_path(), self.home / "threads.json")

    def test_init_bind_and_seat_upsert_one_row(self):
        cid = ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1", resume="secret")
        rows = list_threads()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["convoy_id"], r["thread"], r["root"]), (cid, "t1", str(self.root)))
        self.assertTrue(r["present"])
        self.assertTrue(r["updated_at"])
        self.assertNotIn("secret", index_path().read_text(encoding="utf-8"))
        self.assertEqual(set(json.loads(index_path().read_text(encoding="utf-8"))[0]), {"convoy_id", "thread", "root", "updated_at"})

    def test_vanished_root_is_present_false_not_dropped(self):
        record(str(self.root / "gone"), "cvy_x", "ghost")
        r = list_threads()[0]
        self.assertFalse(r["present"])
        self.assertEqual(r["thread"], "ghost")

    def test_present_requires_the_same_id_on_disk(self):
        ensure_id(self.root)
        record(str(self.root), "cvy_other", "t1")     # index says one id, disk says another
        rows = {r["convoy_id"]: r for r in list_threads()}
        self.assertFalse(rows["cvy_other"]["present"])

    def test_find_root_walks_up_from_a_project_subfolder(self):
        ensure_id(self.root)
        sub = self.root / "src" / "pkg"
        sub.mkdir(parents=True)
        self.assertEqual(find_root(sub), self.root)
        self.assertIsNone(find_root(Path(tempfile.mkdtemp())))

    def test_cli_threads_lists_index_and_graph_html_uses_it(self):
        ensure_id(self.root)
        bind(self.root, "t1")
        other = Path(tempfile.mkdtemp())
        ensure_id(other)
        bind(other, "t2")
        rc, card = _run_cli(self.root, "threads")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(r["thread"] for r in card["threads"]), ["t1", "t2"])
        out = self.root / "g.html"
        rc, card = _run_cli(self.root, "graph", "--html", "--out", str(out))
        self.assertEqual(card["threads"], 2)
        self.assertIn("t2", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
