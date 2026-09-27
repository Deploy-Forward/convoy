"""Resume or declare: the harness's own session store decides.

Convoy mints a session id before the first launch and declares it with the
harness's `--session-id` flag. What marked a later launch as "resume, do not
declare again" was the row's `incarnations`, written by the pane host. No row
has any, so every relaunch of a claude or grok neuron built `--session-id
<id>` for a conversation that already exists: claude and grok both refuse to
declare an id twice, so the relaunch failed or started over.

The conversation's own file is the fact to read, not a row field:

  claude  ~/.claude/projects/<worktree, every non-alphanumeric as ->/<id>.jsonl
  grok    ~/.grok/sessions/<worktree, URL-encoded>/<id>/

File present: `--resume <id>`. File absent: `--session-id <id>` (the first
launch). The tests point the home folder at a temporary one, so nothing here
reads or writes a real harness store.
"""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import resume_argv

WORKTREE = "C:\\w\\resume.fix_1"


def _minted(to, sid):
    return {"to": to, "session_id": "t-" + to, "worktree": WORKTREE, "resume": sid, "resume_for": to, "resume_minted": True}


def _flag_and_id(argv):
    for flag in ("--resume", "--session-id", "-s"):
        if flag in argv:
            return flag, argv[argv.index(flag) + 1]
    return None, None


class TheSessionStoreDecides(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sid = str(uuid.uuid4())

    def _claude_file(self):
        slug = "".join(c if c.isalnum() else "-" for c in WORKTREE)
        d = self.home / ".claude" / "projects" / slug
        d.mkdir(parents=True)
        (d / (self.sid + ".jsonl")).write_text("{}\n", encoding="utf-8")

    def _grok_dir(self):
        (self.home / ".grok" / "sessions" / quote(WORKTREE, safe="") / self.sid).mkdir(parents=True)

    def test_claude_with_its_session_file_resumes_the_minted_id(self):
        self._claude_file()
        self.assertEqual(_flag_and_id(resume_argv(_minted("claude", self.sid))), ("--resume", self.sid))

    def test_claude_without_its_session_file_declares_the_minted_id(self):
        argv = resume_argv(_minted("claude", self.sid))
        self.assertEqual(_flag_and_id(argv), ("--session-id", self.sid))
        self.assertNotIn("--resume", argv)

    def test_grok_with_its_session_folder_resumes_the_minted_id(self):
        self._grok_dir()
        argv = resume_argv(_minted("grok", self.sid))
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], self.sid)
        self.assertNotIn("-s", argv)
        self.assertNotIn("--session-id", argv)

    def test_grok_without_its_session_folder_declares_the_minted_id(self):
        argv = resume_argv(_minted("grok", self.sid))
        flag, value = _flag_and_id(argv)
        self.assertIn(flag, ("-s", "--session-id"))
        self.assertEqual(value, self.sid)
        self.assertNotIn("--resume", argv)

    def test_another_worktrees_file_is_not_this_neurons_conversation(self):
        # claude --resume looks in the project folder of the cwd it starts in, so a file under
        # another worktree's folder cannot be resumed from this one: declare.
        other = self.home / ".claude" / "projects" / "C--w-elsewhere"
        other.mkdir(parents=True)
        (other / (self.sid + ".jsonl")).write_text("{}\n", encoding="utf-8")
        self.assertEqual(_flag_and_id(resume_argv(_minted("claude", self.sid)))[0], "--session-id")


if __name__ == "__main__":
    unittest.main()
