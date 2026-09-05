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
import subprocess
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


class StaleHookEntriesArePruned(unittest.TestCase):
    """Live 2026-09-03: convoy-wt-fable ended up with TWO Convoy PreToolUse
    entries, one dead. The merge only appended, so every earlier command
    Convoy wrote kept running (and failing) on every tool call. Re-running
    `skills` is the resolution path: it prunes Convoy's own stale entries and
    leaves anything the user wrote alone."""

    def setUp(self):
        cmd._RESOLVED = None
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        self.wt = Path(tempfile.mkdtemp())
        (self.wt / ".claude").mkdir()
        mine = {"type": "command", "command": "echo user-hook-keep-me"}
        dead = {"type": "command", "command": "C:/gone/python.exe -m convoy inbox --hook-pretooluse"}
        (self.wt / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {"defaultMode": "bypassPermissions"},
            "hooks": {"PreToolUse": [{"hooks": [dead]}, {"hooks": [mine]}],
                      "UserPromptSubmit": [{"hooks": [dead]}]},
        }, indent=2), encoding="utf-8")

    def test_rerunning_skills_replaces_the_dead_entry_and_keeps_user_hooks(self):
        good = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: c == good):
            rc, card = _run_cli(self.root, "skills", "--worktree", str(self.wt))
        self.assertEqual(rc, 0)
        data = json.loads((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"))
        pre = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn(good, pre)
        self.assertIn("echo user-hook-keep-me", pre)
        self.assertNotIn("C:/gone/python.exe -m convoy inbox --hook-pretooluse", pre)
        self.assertEqual(len([c for c in pre if "inbox --hook-pretooluse" in c]), 1)
        ups = [h["command"] for e in data["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
        self.assertEqual(ups, [good])
        self.assertEqual(data["permissions"]["defaultMode"], "bypassPermissions")

    def test_a_quoted_command_is_not_appended_twice(self):
        """The resolved command contains double quotes; the old duplicate
        check compared against json.dumps(events), where they are escaped, so
        it never matched and every run appended another copy (live: this
        worktree ended up with two identical entries per event)."""
        quoted = cmd._quote(sys.executable) + ' -c "import sys; sys.exit(0)" inbox --hook-pretooluse'
        # Seed it as an existing working hook so the writer keeps it: the point
        # under test is duplication of a command containing double quotes.
        (self.wt / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": quoted}]}],
                      "UserPromptSubmit": [{"hooks": [{"type": "command", "command": quoted}]}]},
        }, indent=2), encoding="utf-8")
        grok_hook = self.wt / ".grok" / "hooks" / "convoy-inbox.json"
        grok_hook.parent.mkdir(parents=True, exist_ok=True)
        grok_hook.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": quoted}]}]},
        }, indent=2), encoding="utf-8")
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: c == quoted):
            _run_cli(self.root, "skills", "--worktree", str(self.wt))
            _run_cli(self.root, "skills", "--worktree", str(self.wt))
            rc, card = _run_cli(self.root, "skills", "--worktree", str(self.wt))
        self.assertEqual(rc, 0)
        data = json.loads((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"))
        for event in ("PreToolUse", "UserPromptSubmit"):
            ours = [h["command"] for e in data["hooks"][event] for h in e["hooks"]
                    if "inbox --hook-pretooluse" in h["command"]]
            self.assertEqual(ours, [quoted], event)

    def test_second_run_is_a_no_op(self):
        good = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: c == good):
            _run_cli(self.root, "skills", "--worktree", str(self.wt))
            before = (self.wt / ".claude" / "settings.json").read_text(encoding="utf-8")
            rc, card = _run_cli(self.root, "skills", "--worktree", str(self.wt))
        self.assertEqual(rc, 0)
        self.assertFalse(card["hooks"]["claude_hook"]["written"])
        self.assertEqual((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"), before)


class CodexQueueStillPendsForTheReceiver(unittest.TestCase):
    """`codex queue` exiting 0 is not a receipt: a queued row was found sitting
    in codex's own sqlite for a dead pane (audit 2026-09-03). Convoy's inbox
    row therefore stays PENDING until the receiver drains it, exactly as for
    every other harness, so the receive loop in neuron-receive/SKILL.md is the
    same on all seven. The row records that a native route was also used."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")

    def test_native_queue_is_recorded_but_the_row_still_awaits_a_drain(self):
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native):
            card = send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(card["delivery"], "native-queued")
        self.assertFalse(card["delivered"])
        waiting = pending(self.root, "c-t1")
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["path"], "codex-queue")
        rows = [json.loads(l) for l in (self.root / ".convoy" / "inbox" / "c-t1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual([r for r in rows if r.get("kind") == "consumed-marker"], [])

    def test_inbox_fallback_pends_the_same_way_when_queue_is_unavailable(self):
        with mock.patch("convoy.synapse.try_codex_queue", return_value=None):
            card = send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(card["delivery"], "queued")
        waiting = pending(self.root, "c-t1")
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["path"], "inbox")


class LimitedIsTheSessionNotAnyHundred(unittest.TestCase):
    """The single line that made the whole receive path unreplicable: a send
    to any seated claude chair refused with "claude limited" on every machine
    with Claude Code installed, because the fallback fired on ANY "100%" in
    the /usage blob and a per-model weekly cap sits right beside a session at
    8%. Proven by an adversarial clean-clone run, 2026-09-03."""

    def test_a_weekly_cap_at_100_does_not_limit_a_fresh_session(self):
        from convoy.usage import _parse_claude
        blob = "\n".join(["Current session: 8%",
                          "Current week (all models): 64%",
                          "Current week (Opus): 100%",
                          "Resets Sep 8, 11:30am (America/New_York)"])
        self.assertFalse(_parse_claude(blob)[1])

    def test_a_spent_session_still_limits(self):
        from convoy.usage import _parse_claude
        self.assertTrue(_parse_claude("Current session: 100%\nCurrent week (all models): 64%")[1])

    def test_unparsed_text_falls_back_to_a_session_line_only(self):
        from convoy.usage import _parse_claude
        self.assertTrue(_parse_claude("usage for session is 100% used")[1])
        self.assertFalse(_parse_claude("weekly cap reached 100% for opus")[1])

    def test_a_live_send_to_a_claude_chair_is_not_refused_by_a_weekly_cap(self):
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t1")
        seat(root, "claude", "a-t1", worktree=str(root), resume="claude-uuid")
        blob = "Current session: 8%\nCurrent week (Opus): 100%"

        def probe(_harness):
            from convoy.usage import _parse_claude
            remaining, limited = _parse_claude(blob)
            return {"usage_remaining": remaining, "limited": limited, "raw": blob}

        card = send_one(root, "claude", "PROOF", runner=fake_runner, instance_id="a-t1",
                        probe_fn=probe, allow_interactive_resume=False)
        self.assertFalse(card.get("refused"), card.get("error"))
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(len(pending(root, "a-t1")), 1)


if __name__ == "__main__":
    unittest.main()


class ATimedOutProbeIsUnknownNotExhausted(unittest.TestCase):
    """Live 2026-09-03, answering Marco's "where is the gap for codex": every
    send to the codex chair was refused with "codex limited" because the codex
    usage probe times out on this machine and usage.py read a TIMEOUT as
    out-of-quota. A probe that measured nothing knows nothing: unknown is
    null. If the vendor really is out of credits it says so, and its own
    refusal is evidence; ours was a guess that made the neuron unreachable."""

    def test_timeout_is_not_limited_and_quota_is_null(self):
        from convoy import usage
        with mock.patch.object(usage, "_run", return_value=(124, "probe timeout")):
            p = usage.probe("codex")
        self.assertFalse(p["limited"])
        self.assertTrue(p["probe_timed_out"])
        self.assertIsNone(p["quota"])
        self.assertIsNone(p["usage_remaining"])

    def test_a_real_out_of_credits_still_limits(self):
        from convoy import usage
        with mock.patch.object(usage, "_run", return_value=(0, "Your workspace is out of credits.")):
            p = usage.probe("codex")
        self.assertTrue(p["limited"])
        self.assertEqual(p["quota"], "exhausted")
        self.assertFalse(p["probe_timed_out"])

    def test_a_send_to_codex_is_not_refused_by_a_timed_out_probe(self):
        from convoy import usage
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t1")
        seat(root, "codex", "c-t1", worktree=str(root), resume="01codex")
        with mock.patch.object(usage, "_run", return_value=(124, "probe timeout")), \
             mock.patch("convoy.synapse.try_codex_queue", return_value=None):
            card = send_one(root, "codex", "REACHABLE", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertFalse(card.get("refused"), card.get("error"))
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(len(pending(root, "c-t1")), 1)


class ProbeKillTimeoutIsStillUnknown(unittest.TestCase):
    """Live 2026-09-05: `convoy rail` crashed. claude -p /usage timed out at
    15s, then taskkill /T of that pid timed out at 5s, and the nested
    TimeoutExpired escaped usage._run. A kill that fails is still a probe
    timeout: 124, never a traceback, never an invented 0."""

    def test_taskkill_timeout_returns_124_not_a_raise(self):
        from convoy import usage

        class FakeP:
            pid = 99080
            returncode = None
            killed = False

            def communicate(self, input="", timeout=None):
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)

            def kill(self):
                self.killed = True

        fake = FakeP()

        def boom_taskkill(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="taskkill", timeout=5)

        with mock.patch.object(usage.os, "name", "nt"), \
             mock.patch.object(usage.subprocess, "Popen", return_value=fake), \
             mock.patch.object(usage.subprocess, "run", side_effect=boom_taskkill):
            code, raw = usage._run(["claude", "-p", "/usage"], timeout=15)
        self.assertEqual(code, 124)
        self.assertEqual(raw, "probe timeout")
        self.assertTrue(fake.killed)

    def test_rail_survives_a_raising_probe(self):
        from convoy.rail import build_rail
        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "t1")
        seat(root, "claude", "c-t1", worktree=str(root))

        def boom(_h):
            raise subprocess.TimeoutExpired(cmd="taskkill", timeout=5)

        card = build_rail(root, probe_fn=boom)
        self.assertTrue(card["ok"], card)
        self.assertIsNone(card["usage"]["claude"]["usage_remaining"])
        self.assertFalse(card["usage"]["claude"]["limited"])
        self.assertNotEqual(card["usage"]["claude"]["usage_remaining"], 0)


class CodexQueueBodyCarriesTheToken(unittest.TestCase):
    """codex 2026-09-03 22:27Z, refusing to certify its own receipt: a `codex
    queue` push arrives as an ordinary user turn, and from inside the pane
    that is indistinguishable from a human typing. It was right. The token now
    rides INSIDE the queued body, so an ack citing it is proof only Convoy
    could have sourced."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")

    def test_the_queued_body_names_the_token_that_lands_in_the_inbox(self):
        seen = {}

        def fake_queue(thread, body):
            seen["thread"] = thread
            seen["body"] = body
            return {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}

        with mock.patch("convoy.synapse.try_codex_queue", side_effect=fake_queue):
            card = send_one(self.root, "codex", "PAYLOAD", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(seen["thread"], "01codex")
        row = pending(self.root, "c-t1")[0]
        self.assertIn("token=" + row["token"], seen["body"])
        self.assertIn("PAYLOAD", seen["body"])
        self.assertIn("not a human typing", seen["body"])
        # the stored row keeps the plain body; the framing is transport-only
        self.assertEqual(row["body"], "PAYLOAD")
