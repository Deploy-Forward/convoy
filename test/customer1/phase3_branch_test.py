import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.context import pack
from convoy.gitstate import git_state
from convoy.layer import feed_since
from convoy.synapse import send_one

def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return r.stdout.strip()

def _repo(name):
    root = Path(tempfile.mkdtemp()) / name
    root.mkdir()
    env = os.environ.copy()
    _git(root, "init")
    _git(root, "config", "user.email", "p3@test")
    _git(root, "config", "user.name", "p3")
    (root / "README").write_text(name)
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    _git(root, "checkout", "-B", name)
    (root / ".ola").mkdir()
    (root / ".ola" / "brief.md").write_text("b")
    return root

class Phase3Branch(unittest.TestCase):
    def test_not_git_is_null_not_main(self):
        root = Path(tempfile.mkdtemp())
        state = git_state(root)
        self.assertIsNone(state["git_branch"])
        self.assertIsNone(state["git_sha"])
        self.assertIsNone(state["pr_number"])
        packed = pack(root)
        self.assertIsNone(packed["branch"])
        self.assertIsNone(packed["pr"])
        blob = json.dumps(packed)
        self.assertNotIn('"main"', blob)

    def test_two_synapses_two_branches(self):
        a = _repo("feat-a")
        b = _repo("feat-b")
        ca = send_one(a, "grok", "A", label="a")
        cb = send_one(b, "grok", "B", label="b")
        self.assertNotEqual(pack(a)["branch"], pack(b)["branch"])
        self.assertEqual(pack(a)["branch"], "feat-a")
        self.assertEqual(pack(b)["branch"], "feat-b")
        ra = feed_since(a, "1970-01-01T00:00:00.000000Z")[-1]
        rb = feed_since(b, "1970-01-01T00:00:00.000000Z")[-1]
        self.assertEqual(ra["git_branch"], "feat-a")
        self.assertEqual(rb["git_branch"], "feat-b")
        self.assertNotEqual(ra["git_sha"], rb["git_sha"])
        self.assertTrue(ca["session_id"])
        self.assertTrue(cb["session_id"])

if __name__ == "__main__":
    unittest.main()
