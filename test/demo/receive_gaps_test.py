"""Two receive-path gaps from the 2026-09-03 audit.

1. `skills --worktree W` refreshed skill text but never the hooks, so a
   long-lived pane stayed deaf after an upgrade. It now installs the probed
   inbox hooks and the root pointer too when --root names a thread.
2. A codex send that native-queued still left its inbox row pending forever:
   Convoy enqueued a row it never drained. The row is now marked consumed by
   a `codex-queue` drain id at delivery time, so the SoT shows the truth
   (queued natively, pending nowhere) while `delivered` stays false until
   codex's own ack.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cmd
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.inbox import pending
from convoy.synapse import fake_runner, send_one


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class SkillsVerbInstallsHooks(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        self.wt = Path(tempfile.mkdtemp())

    def test_skills_writes_hooks_and_root_pointer(self):
        fake = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: c == fake):
            rc, card = _run_cli(self.root, "skills", "--worktree", str(self.wt))
        self.assertEqual(rc, 0)
        self.assertTrue(card["ok"])
        self.assertTrue(card["hooks"]["ok"])
        self.assertEqual(card["hooks"]["resolved_via"], "interpreter")
        grok = json.loads((self.wt / ".grok" / "hooks" / "convoy-inbox.json").read_text(encoding="utf-8"))
        self.assertEqual(grok["hooks"]["PreToolUse"][0]["hooks"][0]["command"], fake)
        claude = json.loads((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertIn("UserPromptSubmit", claude["hooks"])
        self.assertEqual((self.wt / ".grok" / "convoy-root").read_text(encoding="utf-8").strip(), str(self.root.resolve()))
        self.assertEqual((self.wt / ".claude" / "convoy-root").read_text(encoding="utf-8").strip(), str(self.root.resolve()))

    def test_skills_reports_hook_failure_without_hiding_skill_success(self):
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: False):
            rc, card = _run_cli(self.root, "skills", "--worktree", str(self.wt))
        self.assertEqual(rc, 1)
        self.assertTrue(card["skills_ok"])
        self.assertFalse(card["hooks"]["ok"])
        self.assertIn("pipx", card["hooks"]["error"])


class CodexQueueMarksItsRowConsumed(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")

    def test_native_queue_leaves_no_pending_row_but_is_not_delivered(self):
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native):
            card = send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(card["delivery"], "native-queued")
        self.assertFalse(card["delivered"])
        self.assertEqual(pending(self.root, "c-t1"), [])
        rows = [json.loads(l) for l in (self.root / ".convoy" / "inbox" / "c-t1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        markers = [r for r in rows if r.get("kind") == "consumed-marker"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["drain_id"], "codex-queue")
        self.assertEqual(markers[0]["token"], rows[0]["token"])

    def test_inbox_fallback_still_pends_when_queue_is_unavailable(self):
        with mock.patch("convoy.synapse.try_codex_queue", return_value=None):
            card = send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(len(pending(self.root, "c-t1")), 1)


if __name__ == "__main__":
    unittest.main()
