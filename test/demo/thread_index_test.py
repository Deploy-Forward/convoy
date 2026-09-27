"""Machine-level thread index: chats launch from project
folders, so .convoy must be findable globally, like Claude's /resume.
~/.convoy/threads.json holds {convoy_id, thread, root, updated_at} rows and
nothing else; every init/bind/seat upserts its row. Roots that vanished
render present=false, never as a thread. prune drops temp/absent rows and
reports them; recent() is the picker (present, not temp)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.activity import neuron_id, neurons_everywhere, resolve_neuron_id
from convoy.index import find_root, index_path, is_temp_root, list_threads, prune_threads, recent, record, set_hidden
from convoy.mcp_http import _known_threads, _resolve_root
from convoy.origin_loop import _roots_from_index
from convoy.local_install import _known_roots
from convoy.rail import root_for


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class ThreadIndex(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self._prev_home = os.environ.get("CONVOY_HOME")   # restore, never pop: the runner's guard must survive
        os.environ["CONVOY_HOME"] = str(self.home)
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("CONVOY_HOME", None)
        else:
            os.environ["CONVOY_HOME"] = self._prev_home

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

    def test_temp_thread_is_retained_but_not_routable_or_listed_as_neurons(self):
        cid = ensure_id(self.root)
        bind(self.root, "synthetic-temp-thread")
        seat(self.root, "claude", "synthetic-temp-neuron")
        worktree = Path(tempfile.mkdtemp())
        seat(self.root, "codex", "synthetic-temp-worker", worktree=str(worktree))
        before = index_path().read_bytes()
        self.assertTrue(list_threads()[0]["present"])
        self.assertTrue(is_temp_root(self.root))

        with self.subTest("MCP resolver"):
            self.assertFalse(
                any(row["convoy_id"] == cid for row in _known_threads()),
                "MCP thread resolution must not route through a test-temp root",
            )
        activity = neurons_everywhere()
        with self.subTest("all-neurons view"):
            self.assertFalse(
                any(row["thread"] == "synthetic-temp-thread" for row in activity["rows"]),
                "neurons --all must not present test-temp neurons as live user neurons",
            )
        with self.subTest("neuron-id routing"):
            resolved = resolve_neuron_id(neuron_id(cid, "synthetic-temp-neuron"))
            self.assertFalse(resolved["ok"], "a test-temp neuron must not be a routable send target")
        with self.subTest("board origin root resolution"):
            self.assertNotIn(self.root, _roots_from_index(),
                             "the existing board origin loop must not select a test-temp root")
        with self.subTest("local install choices"):
            self.assertFalse(any(row["root"] == str(self.root) for row in _known_roots()))
        with self.subTest("rail fallback"):
            self.assertIsNone(root_for(worktree), "implicit worktree routing must not select a test-temp root")
        with self.subTest("explicit root remains usable"):
            self.assertEqual(_resolve_root(self.root, {}), self.root)
            self.assertEqual(root_for(self.root), self.root)
        self.assertEqual(index_path().read_bytes(), before, "filtering must not prune existing rows")
        self.assertTrue(list_threads()[0]["present"], "historical temp rows stay in the index")

    def test_durable_thread_stays_discoverable(self):
        keep = self._durable_root()
        cid = ensure_id(keep)
        bind(keep, "synthetic-durable-thread")
        worktree = Path(tempfile.mkdtemp())
        seat(keep, "codex", "synthetic-durable-neuron", worktree=str(worktree))
        self.assertIn(cid, {row["convoy_id"] for row in _known_threads()})
        self.assertIn(keep, _roots_from_index())
        self.assertTrue(any(row["root"] == str(keep) for row in _known_roots()))
        self.assertEqual(root_for(worktree), keep)
        self.assertTrue(resolve_neuron_id(neuron_id(cid, "synthetic-durable-neuron"))["ok"])
        self.assertTrue(any(row["thread"] == "synthetic-durable-thread"
                            for row in neurons_everywhere()["rows"]))

    def test_hidden_durable_thread_is_routable_but_absent_from_views(self):
        keep = self._durable_root()
        cid = ensure_id(keep)
        bind(keep, "synthetic-hidden-thread")
        worktree = Path(tempfile.mkdtemp())
        seat(keep, "codex", "synthetic-hidden-neuron", worktree=str(worktree))
        self.assertTrue(set_hidden(cid, True)["ok"])

        self.assertNotIn(cid, {row["convoy_id"] for row in _known_threads()})
        self.assertNotIn(cid, {row["convoy_id"] for row in recent(20)})
        self.assertFalse(any(row["thread"] == "synthetic-hidden-thread"
                             for row in neurons_everywhere()["rows"]))
        self.assertFalse(any(row["root"] == str(keep) for row in _known_roots()))

        self.assertIn(keep, _roots_from_index(), "hidden must not disable board delivery")
        self.assertEqual(root_for(worktree), keep)
        self.assertEqual(_resolve_root(None, {"convoy_id": cid}), keep.resolve())
        self.assertTrue(resolve_neuron_id(neuron_id(cid, "synthetic-hidden-neuron"))["ok"])

        out = self.root / "hidden-graph.html"
        rc, card = _run_cli(self.root, "graph", "--html", "--out", str(out))
        self.assertEqual(rc, 0)
        self.assertEqual(card["threads"], 1)
        self.assertIn("synthetic-hidden-thread", out.read_text(encoding="utf-8"))

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

    def test_cli_threads_keeps_temp_history_but_graph_needs_an_explicit_temp_root(self):
        ensure_id(self.root)
        bind(self.root, "t1")
        other = Path(tempfile.mkdtemp())
        ensure_id(other)
        bind(other, "t2")
        rc, card = _run_cli(self.root, "threads")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(r["thread"] for r in card["threads"]), ["t1", "t2"])
        self.assertEqual({r["thread"]: r.get("skip_reason") for r in card["threads"]},
                         {"t1": "temp", "t2": "temp"})
        out = self.root / "g.html"
        rc, card = _run_cli(self.root, "graph", "--html", "--out", str(out))
        self.assertEqual(rc, 0)
        self.assertEqual(card["threads"], 1)
        self.assertTrue(any(r["root"] == str(other) and r["reason"] == "temp"
                            for r in card["skipped"]))
        self.assertNotIn("t2", out.read_text(encoding="utf-8"))
        rc, card = _run_cli(self.root, "graph", "--html", "--also-root", str(other), "--out", str(out))
        self.assertEqual(rc, 0)
        self.assertEqual(card["threads"], 2, "explicit --also-root must keep working under Temp")
        self.assertIn("t2", out.read_text(encoding="utf-8"))

    def _durable_root(self):
        """A present root that is NOT under the OS temp dir, so prune keeps it."""
        base = Path(__file__).resolve().parent / "_keep_roots"
        base.mkdir(exist_ok=True)
        p = Path(tempfile.mkdtemp(prefix="keep-", dir=str(base)))
        self.addCleanup(shutil.rmtree, p, True)
        return p

    def test_list_threads_keeps_present_false_prune_is_what_drops(self):
        gone = Path(tempfile.mkdtemp())
        record(str(gone), "cvy_ghost", "ghost")
        shutil.rmtree(gone)
        listed = list_threads()
        self.assertTrue(any(r["convoy_id"] == "cvy_ghost" and r["present"] is False for r in listed))
        card = prune_threads()
        self.assertTrue(card["ok"])
        self.assertGreaterEqual(card["n_dropped"], 1)
        self.assertTrue(any(d["convoy_id"] == "cvy_ghost" and d["reason"] == "absent" for d in card["dropped"]))
        self.assertFalse(any(r["convoy_id"] == "cvy_ghost" for r in list_threads()))

    def test_prune_drops_temp_roots_keeps_durable_present_and_is_never_silent(self):
        temp_root = Path(tempfile.mkdtemp())
        ensure_id(temp_root)
        bind(temp_root, "demo")
        keep = self._durable_root()
        cid = ensure_id(keep)
        bind(keep, "keep-me")
        first = prune_threads()
        self.assertIn("dropped", first)
        self.assertIsInstance(first["dropped"], list)
        self.assertTrue(any(d["root"] == str(temp_root) and d["reason"] == "temp" for d in first["dropped"]))
        remaining = {r["convoy_id"]: r for r in list_threads()}
        self.assertIn(cid, remaining)
        self.assertTrue(remaining[cid]["present"])
        self.assertFalse(is_temp_root(keep))
        # second prune drops nothing: still reports the empty list
        again = prune_threads()
        self.assertTrue(again["ok"])
        self.assertEqual(again["dropped"], [])
        self.assertEqual(again["n_dropped"], 0)
        self.assertTrue(any(r["convoy_id"] == cid for r in again["threads"]))

    def test_cli_threads_prune_reports_dropped(self):
        gone = Path(tempfile.mkdtemp())
        record(str(gone), "cvy_cli_gone", "ghost")
        shutil.rmtree(gone)
        rc, card = _run_cli(self.root, "threads", "--prune")
        self.assertEqual(rc, 0)
        self.assertTrue(any(d["convoy_id"] == "cvy_cli_gone" and d["reason"] == "absent" for d in card["dropped"]))
        self.assertIn("n_dropped", card)

    def test_recent_is_newest_present_excluding_temp_and_absent(self):
        keep_old = self._durable_root()
        ensure_id(keep_old)
        bind(keep_old, "old")
        keep_new = self._durable_root()
        cid_new = ensure_id(keep_new)
        bind(keep_new, "new")
        temp_root = Path(tempfile.mkdtemp())
        ensure_id(temp_root)
        bind(temp_root, "temp-demo")
        gone = Path(tempfile.mkdtemp())
        record(str(gone), "cvy_recent_gone", "ghost")
        shutil.rmtree(gone)
        got = recent(1)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["convoy_id"], cid_new)
        self.assertEqual(got[0]["thread"], "new")
        self.assertTrue(got[0]["present"])
        self.assertFalse(is_temp_root(got[0]["root"]))
        self.assertEqual(recent(0), [])
        many = recent(50)
        ids = [r["convoy_id"] for r in many]
        self.assertIn(cid_new, ids)
        self.assertNotIn("cvy_recent_gone", ids)
        self.assertTrue(all(not is_temp_root(r["root"]) for r in many))
        self.assertTrue(all(r["present"] for r in many))


class PackageHomeGuard(unittest.TestCase):
    def test_demo_package_points_convoy_home_at_a_throwaway(self):
        home = os.environ.get("CONVOY_HOME")
        self.assertTrue(home)
        self.assertTrue(is_temp_root(home))
        self.assertNotEqual(Path(home).resolve(), (Path.home() / ".convoy").resolve())
        self.assertNotEqual(index_path(), Path.home() / ".convoy" / "threads.json")


if __name__ == "__main__":
    unittest.main()
