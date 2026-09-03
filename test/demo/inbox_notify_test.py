import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import ensure_first_run
from convoy.cli import main
from convoy.cmd import INBOX_HOOK_COMMAND, command_bakes_interpreter, inbox_hook_command
from convoy.convoy import bind, ensure_id, seat
from convoy.identity import (
    claude_inbox_hook_document,
    ensure_claude_inbox_hook,
    ensure_grok_inbox_hook,
    ensure_inbox_hooks,
    grok_inbox_hook_document,
)
from convoy.inbox import (
    HARNESS_INBOX,
    drain,
    enqueue,
    hook_pretooluse,
    inbox_path,
    pending,
    write_root_pointer,
)
from convoy.layer import feed_since
from convoy.synapse import send_one


class LiveSeatInbox(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "inbox-thread")
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt), resume="vendor-grok")

    def test_live_instance_id_queues_and_does_not_spawn(self):
        spawned = {"n": 0}

        def should_not_run(*_a, **_k):
            spawned["n"] += 1
            return {"ok": True, "to": "grok", "session_id": "bad", "model": None, "usage_remaining": None, "body": "bad"}

        card = send_one(
            self.root,
            "grok",
            "design review body",
            instance_id="sess-grok",
            runner=should_not_run,
            allow_interactive_resume=False,
        )
        self.assertTrue(card["ok"])
        self.assertEqual(card["delivery"], "queued")
        self.assertFalse(card["delivered"])
        self.assertFalse(card["resume_stolen"])
        self.assertEqual(card["path"], "inbox")
        self.assertTrue(card.get("token"))
        self.assertEqual(spawned["n"], 0)
        waiting = pending(self.root, "sess-grok")
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["body"], "design review body")
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        syn = [r for r in rows if r.get("kind") == "synapse"]
        self.assertEqual(syn[-1]["runner"], "inbox")
        self.assertEqual(syn[-1]["delivery"], "queued")
        self.assertFalse(syn[-1]["delivered"])

    def test_non_live_instance_id_is_not_a_fake_ack(self):
        card = send_one(self.root, "grok", "hello occupant", instance_id="sess-grok")
        self.assertTrue(card["ok"])
        self.assertEqual(card["delivery"], "queued")
        self.assertFalse(card["delivered"])
        self.assertNotIn("ACK", str(card.get("body") or ""))
        self.assertEqual(pending(self.root, "sess-grok")[0]["body"], "hello occupant")

    def test_consume_is_append_only_marker_per_token(self):
        item = enqueue(self.root, "sess-grok", "KEEP-PENDING-LINE", to="grok")
        dest = inbox_path(self.root, "sess-grok")
        before = dest.read_text(encoding="utf-8")
        taken = drain(self.root, "sess-grok")
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["token"], item["token"])
        after = dest.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before.rstrip("\n")))
        lines = [json.loads(x) for x in after.splitlines() if x.strip()]
        self.assertEqual(lines[0]["status"], "pending")
        self.assertEqual(lines[0]["token"], item["token"])
        self.assertEqual(lines[1]["kind"], "consumed-marker")
        self.assertEqual(lines[1]["status"], "consumed")
        self.assertEqual(lines[1]["token"], item["token"])
        self.assertTrue(lines[1].get("drain_id"))
        self.assertEqual(pending(self.root, "sess-grok"), [])

    def test_old_rewritten_consumed_row_is_not_pending(self):
        dest = inbox_path(self.root, "sess-grok")
        dest.write_text(
            json.dumps({
                "ts": "2026-09-03T00:00:00.000000Z",
                "token": "legacytoken",
                "session_id": "sess-grok",
                "body": "old",
                "status": "consumed",
                "consumed_at": "2026-09-03T00:00:01.000000Z",
            }, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(pending(self.root, "sess-grok"), [])

    def test_concurrent_drain_delivers_once(self):
        enqueue(self.root, "sess-grok", "ONCE-ONLY", to="grok")
        bags: list[list] = []

        def go():
            bags.append(drain(self.root, "sess-grok"))

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        taken = [row for batch in bags for row in batch]
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["body"], "ONCE-ONLY")
        self.assertEqual(pending(self.root, "sess-grok"), [])

    def test_drain_and_pretooluse_hook_injects_body(self):
        write_root_pointer(self.wt, self.root)
        enqueue(self.root, "sess-grok", "TOKEN-BODY-99", to="grok", label="design-review")
        card = hook_pretooluse(self.wt)
        ctx = card["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(card.get("decision"), "allow")
        self.assertIn("TOKEN-BODY-99", ctx)
        self.assertIn("design-review", ctx)
        self.assertIn("token=", ctx)
        self.assertEqual(pending(self.root, "sess-grok"), [])
        empty = hook_pretooluse(self.wt)
        self.assertEqual(empty.get("decision"), "allow")

    def test_cli_live_send_queues(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([
                "--root", str(self.root), "send", "--live", "--to", "grok",
                "--instance-id", "sess-grok", "pane-to-pane",
            ])
        self.assertEqual(rc, 0)
        card = json.loads(buf.getvalue())
        self.assertEqual(card["delivery"], "queued")
        self.assertFalse(card["delivered"])
        self.assertEqual(pending(self.root, "sess-grok")[0]["body"], "pane-to-pane")

    def test_codex_queue_used_when_present(self):
        seat(self.root, "codex", "sess-codex", worktree=str(self.wt), resume="01codex")
        calls = []

        def fake_run(cmd, **_k):
            calls.append(list(cmd))
            class R:
                returncode = 0
                stdout = "queued"
                stderr = ""
            return R()

        with mock.patch("convoy.synapse.shutil.which", return_value="C:\\Tools\\codex.exe"), \
             mock.patch("convoy.synapse.subprocess.run", side_effect=fake_run):
            card = send_one(
                self.root, "codex", "hi codex", instance_id="sess-codex",
                allow_interactive_resume=False,
            )
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(card["path"], "codex-queue")
        self.assertFalse(card["delivered"])
        queued = [c for c in calls if len(c) > 1 and c[1] == "queue"]
        self.assertTrue(queued)
        self.assertEqual(queued[0][1:5], ["queue", "--thread", "01codex", "--message"])

    def test_hook_command_is_probed_where_it_runs(self):
        """Audit 2026-09-03 reversed PR 40's bare-only rule: the bare name was
        shadowed by an unrelated shim on the audited machine and invisible to
        Git Bash, so every hook written was dead. Hook files never travel (they
        are gitignored per-worktree state), so an absolute interpreter path is
        allowed when it is the command that actually resolves. The documents
        take whatever the probe returned."""
        self.assertEqual(inbox_hook_command(), INBOX_HOOK_COMMAND)
        self.assertEqual(INBOX_HOOK_COMMAND, "convoy inbox --hook-pretooluse")
        from convoy import cmd as _cmd
        res = _cmd.resolve_inbox_hook_command()
        self.assertIn(res["resolved_via"], ("console-script", "interpreter", "interpreter+src", None))
        if res["command"]:
            self.assertTrue(res["command"].endswith("inbox --hook-pretooluse"))
            grok_doc = grok_inbox_hook_document(res["command"])
            claude_doc = claude_inbox_hook_document(res["command"])
            self.assertEqual(grok_doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"], res["command"])
            self.assertEqual(claude_doc["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"], res["command"])
        else:
            self.assertIn("pipx", res["error"])

    def test_refuse_writing_a_command_that_does_not_resolve(self):
        from convoy import cmd as _cmd
        _cmd._RESOLVED = None
        with mock.patch.object(_cmd, "_probe_inbox_command", return_value=False):
            # a failed resolution is never cached, so later tests re-probe live
            grok = ensure_grok_inbox_hook(self.wt)
            claude = ensure_claude_inbox_hook(self.wt)
        self.assertFalse(grok["ok"])
        self.assertFalse(claude["ok"])
        self.assertIn("pipx", grok["error"])
        self.assertFalse((self.wt / ".grok" / "hooks" / "convoy-inbox.json").exists())

    def test_grok_and_claude_hook_files_are_project_local(self):
        card = ensure_inbox_hooks(self.wt, root=self.root, harness="claude")
        self.assertTrue(card["ok"])
        grok_path = Path(card["grok_hook"]["hook"])
        claude_path = Path(card["claude_hook"]["hook"])
        self.assertTrue(grok_path.is_file())
        self.assertTrue(claude_path.is_file())
        grok_raw = grok_path.read_text(encoding="utf-8")
        claude_data = json.loads(claude_path.read_text(encoding="utf-8"))
        resolved = card["command"]
        self.assertTrue(resolved.endswith("inbox --hook-pretooluse"))
        self.assertIn(card["resolved_via"], ("console-script", "interpreter", "interpreter+src", "kept-existing"))
        self.assertIn(json.dumps(resolved)[1:-1], grok_raw)
        self.assertEqual(claude_data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], resolved)
        self.assertEqual(claude_data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"], resolved)
        self.assertNotIn("skipDangerousModePermissionPrompt", claude_data)
        self.assertNotIn("permissions", claude_data)
        self.assertTrue((self.wt / ".grok" / "convoy-root").is_file())
        self.assertTrue((self.wt / ".claude" / "convoy-root").is_file())

    def test_all_seven_harnesses_have_an_honest_kind(self):
        seven = ("grok", "claude", "codex", "cursor-agent", "agy", "hermes", "pi")
        self.assertEqual(set(HARNESS_INBOX), set(seven))
        self.assertEqual(HARNESS_INBOX["grok"], "grok-hooks")
        self.assertEqual(HARNESS_INBOX["claude"], "claude-settings")
        self.assertEqual(HARNESS_INBOX["codex"], "native-queue-or-cli-drain")
        for hid in ("cursor-agent", "agy", "hermes", "pi"):
            self.assertEqual(HARNESS_INBOX[hid], "cli-drain")
        fake_home = Path(tempfile.mkdtemp())
        with mock.patch("convoy.bringup.Path.home", return_value=fake_home):
            for hid in seven:
                wt = Path(tempfile.mkdtemp())
                card = ensure_first_run({"to": hid, "worktree": str(wt)}, root=self.root)
                self.assertTrue(card.get("ok"), hid)
                self.assertTrue(card.get("inbox_hook_written"), hid)
                grok_hook = Path(wt) / ".grok" / "hooks" / "convoy-inbox.json"
                claude_settings = Path(wt) / ".claude" / "settings.json"
                self.assertTrue(grok_hook.is_file(), hid)
                self.assertIn("inbox --hook-pretooluse", grok_hook.read_text(encoding="utf-8"))
                data = json.loads(claude_settings.read_text(encoding="utf-8"))
                self.assertTrue(
                    data["hooks"]["PreToolUse"][0]["hooks"][0]["command"].endswith("inbox --hook-pretooluse"),
                    hid,
                )
                if hid != "claude":
                    self.assertNotIn("skipDangerousModePermissionPrompt", data)
                    self.assertFalse(card.get("wrote"))
                    self.assertFalse(card.get("home_written"))

    def test_claude_first_run_merges_hooks_without_dropping_ungate(self):
        fake_home = Path(tempfile.mkdtemp())
        with mock.patch("convoy.bringup.Path.home", return_value=fake_home):
            card = ensure_first_run({"to": "claude", "worktree": str(self.wt)}, root=self.root)
        self.assertTrue(card.get("ok"))
        self.assertTrue(card.get("wrote"))
        data = json.loads((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(data.get("skipDangerousModePermissionPrompt"))
        self.assertEqual(data.get("permissions", {}).get("defaultMode"), "bypassPermissions")
        self.assertTrue(
            data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].endswith("inbox --hook-pretooluse")
        )


if __name__ == "__main__":
    unittest.main()
