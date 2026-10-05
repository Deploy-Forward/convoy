"""One thread resolver for attach, detach --thread and lead --thread.

It accepts the exact cvy_ id, a unique prefix of it of at least 8 characters
(counting "cvy_"), an exact thread name, or the thread's root path. It refuses
an ambiguous prefix and names the ids, a short prefix, a pure number, and temp
or absent roots. Synthetic evidence only: no harness launches.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, read_id
from convoy.panes import identify

ID_A = "cvy_synthAAAA" + "1" * 15
ID_B = "cvy_synthAAAA" + "2" * 15


def _thread(base: Path, name: str, cid: str | None, thread: str | None) -> Path:
    root = base / name
    (root / ".convoy").mkdir(parents=True)
    if cid:
        (root / ".convoy" / "id").write_text(cid + "\n", encoding="utf-8")
    bind(root, thread or name)
    return root


class ThreadResolve(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        base = Path(self.owner.name)
        home = base / "home"
        home.mkdir()
        env = patch.dict(os.environ, {"CONVOY_HOME": str(base / "convoy-home"), "HOME": str(home),
                                      "USERPROFILE": str(home)})
        env.start()
        self.addCleanup(env.stop)
        self.a = _thread(base, "alpha", ID_A, "synthetic-alpha")
        self.b = _thread(base, "beta", ID_B, "synthetic-beta")
        self.assertEqual((read_id(self.a), read_id(self.b)), (ID_A, ID_B))
        self.procs = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                      {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]
        temp = patch("convoy.sessions.is_temp_root", return_value=False)
        temp.start()
        self.addCleanup(temp.stop)

    def attach(self, choice, cwd):
        from convoy.sessions import attach_session
        me = lambda root, **kw: identify(root, pid=21, procs=self.procs, cwd=str(cwd),
                                         env={"CLAUDE_CODE_SESSION_ID": "synthetic-native-id"},
                                         allow_unseated=True)
        with patch("convoy.sessions.identify", side_effect=me):
            return attach_session(choice, cwd=cwd)

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["--root", str(Path(self.owner.name) / "elsewhere"), *args])
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_a_unique_prefix_resolves(self):
        card = self.attach("cvy_synthAAAA1", self.a)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["convoy_id"], ID_A)

    def test_an_ambiguous_prefix_refuses_and_names_the_ids(self):
        card = self.attach("cvy_synthAAAA", self.a)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], "matches 2 threads: " + ID_A + ", " + ID_B)

    def test_a_prefix_shorter_than_8_refuses(self):
        card = self.attach("cvy_syn", self.a)
        self.assertFalse(card["ok"])
        self.assertIn("at least 8 characters", card["error"])

    def test_a_pure_number_still_refuses(self):
        card = self.attach("12345678", self.a)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], "pass the cvy_ id from convoy list")

    def test_a_root_path_resolves(self):
        card = self.attach(str(self.b), self.b)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["convoy_id"], ID_B)

    def test_a_name_that_is_also_another_threads_prefix_refuses_and_names_both(self):
        named = _thread(Path(self.owner.name), "gamma", "cvy_synthZZZZ" + "3" * 15, "cvy_synthAAAA1")
        card = self.attach("cvy_synthAAAA1", self.a)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], "matches 2 threads: " + ID_A + ", " + read_id(named))

    def test_a_shared_name_refuses_and_names_the_ids(self):
        twin = _thread(Path(self.owner.name), "delta", "cvy_synthDDDD" + "4" * 15, "synthetic-alpha")
        card = self.attach("synthetic-alpha", self.a)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], "matches 2 threads: " + ID_A + ", " + read_id(twin))

    def test_lead_thread_reads_that_root(self):
        rc, out = self.cli("lead", "--thread", "cvy_synthAAAA2")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["convoy_id"], ID_B)
        rc, out = self.cli("lead", "--thread", "synthetic-alpha")
        self.assertEqual(out["convoy_id"], ID_A)

    def test_lead_thread_refuses_an_ambiguous_prefix(self):
        rc, out = self.cli("lead", "--thread", "cvy_synthAAAA")
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["error"], "matches 2 threads: " + ID_A + ", " + ID_B)


if __name__ == "__main__":
    unittest.main()
