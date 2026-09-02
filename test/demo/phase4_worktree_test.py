import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.context import pack
from convoy.synapse import send_one

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)

def _repo(parent, name, branch):
    root = Path(parent) / name
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "p4@test")
    _git(root, "config", "user.name", "p4")
    (root / "README").write_text(name)
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    _git(root, "checkout", "-B", branch)
    (root / ".ola").mkdir()
    (root / ".ola" / "brief.md").write_text("b")
    return root

class Phase4Worktree(unittest.TestCase):
    def test_pack_worktree_null_if_not_git(self):
        root = Path(tempfile.mkdtemp())
        p = pack(root)
        self.assertIsNone(p["worktree"])
        self.assertIsNone(p["branch"])

    def test_same_branch_without_worktree_refuses_second(self):
        parent = Path(tempfile.mkdtemp())
        repo = _repo(parent, "one", "feat-shared")
        t1 = send_one(repo, "grok", "T1", label="one")
        self.assertTrue(t1["ok"])
        self.assertEqual(t1["pointers"]["worktree"], str(repo.resolve()))
        t2 = send_one(repo, "grok", "T2", label="two")
        self.assertFalse(t2["ok"])
        self.assertIsNone(t2["session_id"])
        self.assertIn("worktree", t2["error"])

    def test_two_worktrees_do_not_share_cwd(self):
        parent = Path(tempfile.mkdtemp())
        layer = _repo(parent, "layer", "feat-shared")
        wt_a = _repo(parent, "wt-a", "feat-shared")
        wt_b = _repo(parent, "wt-b", "feat-shared")
        a = send_one(layer, "grok", "A", label="a", worktree=str(wt_a))
        b = send_one(layer, "grok", "B", label="b", worktree=str(wt_b))
        self.assertTrue(a["ok"])
        self.assertTrue(b["ok"])
        self.assertNotEqual(a["pointers"]["worktree"], b["pointers"]["worktree"])
        self.assertEqual(a["pointers"]["worktree"], str(wt_a.resolve()))
        self.assertEqual(b["pointers"]["worktree"], str(wt_b.resolve()))
        resume = send_one(layer, "grok", "T2", instance_id=a["session_id"])
        self.assertTrue(resume["ok"])

if __name__ == "__main__":
    unittest.main()
