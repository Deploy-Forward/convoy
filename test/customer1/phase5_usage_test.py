import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.layer import feed_since
from convoy.synapse import native_runner, send_one
from convoy.usage import _parse_claude, normalize_usage_remaining, probe

class Phase5Usage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("b")

    def test_grok_probe_is_null_not_zero(self):
        p = probe("grok")
        self.assertIsNone(p["usage_remaining"])
        self.assertFalse(p["limited"])
        self.assertNotEqual(p["usage_remaining"], 0)

    def test_claude_session_line(self):
        rem, limited = _parse_claude("Current session: 0% used\nCurrent week (all models): 69% used")
        self.assertFalse(limited)
        rem100, lim100 = _parse_claude("Current session: 100% used")
        self.assertTrue(lim100)

    def test_claude_blob_not_usage_remaining(self):
        rem, limited = _parse_claude("Total cost: $0.00\nDuration: 2m\nInput: 0\nOutput: 0")
        self.assertFalse(limited)
        self.assertIsNone(rem)
        self.assertIsNone(normalize_usage_remaining("Total cost: $0.00"))

    def test_claude_100_refuses_without_spawn(self):
        def stub(_to):
            return {"usage_remaining": {"session_pct": 100}, "limited": True, "raw": "session 100%"}

        spawned = {"n": 0}

        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "to": "claude", "session_id": "should-not", "model": None, "usage_remaining": None, "body": "nope"}

        card = send_one(self.root, "claude", "hi", runner=runner, probe_fn=stub)
        self.assertFalse(card["ok"])
        self.assertTrue(card.get("refused"))
        self.assertIsNone(card["session_id"])
        self.assertEqual(spawned["n"], 0)
        rows = feed_since(self.root, "1970-01-01T00:00:00.000000Z")
        self.assertEqual(rows[-1]["kind"], "refuse")

    def test_codex_out_of_credits_refuses(self):
        def stub(_to):
            return {"usage_remaining": None, "limited": True, "raw": "Your workspace is out of credits."}

        spawned = {"n": 0}

        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "session_id": "nope", "to": "codex", "model": None, "usage_remaining": None, "body": "nope"}

        card = send_one(self.root, "codex", "hi", runner=runner, probe_fn=stub)
        self.assertFalse(card["ok"])
        self.assertTrue(card.get("refused"))
        self.assertEqual(spawned["n"], 0)

    def test_codex_probe_timeout_refuses(self):
        def stub(_to):
            return {"usage_remaining": None, "limited": True, "raw": "probe timeout", "exit_code": 124}

        spawned = {"n": 0}

        def runner(*a, **k):
            spawned["n"] += 1
            return {"ok": True, "session_id": "nope", "to": "codex", "model": None, "usage_remaining": None, "body": "nope"}

        card = send_one(self.root, "codex", "hi", runner=runner, probe_fn=stub)
        self.assertTrue(card.get("refused"))
        self.assertEqual(spawned["n"], 0)

    def test_invented_zero_is_not_remaining(self):
        p = probe("agy")
        self.assertIsNone(p["usage_remaining"])
        self.assertNotEqual(p["usage_remaining"], 0)

    def test_normalize_usage_remaining_blob_to_null(self):
        self.assertIsNone(normalize_usage_remaining(None))
        self.assertEqual(normalize_usage_remaining(7), 7)
        self.assertEqual(normalize_usage_remaining({"session_pct": 12}), {"session_pct": 12})
        self.assertIsNone(normalize_usage_remaining("Current session: 7% used"))
        self.assertIsNone(normalize_usage_remaining(["not-allowed"]))
        self.assertIsNone(normalize_usage_remaining(False))

    def test_native_runner_argv_uses_vendor_bins_no_ola_wrap(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

            class R:
                returncode = 0
                stdout = '{"session_id":"sess-native"}'
                stderr = ""

            return R()

        with mock.patch("convoy.synapse.shutil.which", side_effect=lambda name: "/usr/bin/" + str(name).replace(".exe", "")):
            with mock.patch("convoy.synapse.subprocess.run", side_effect=fake_run):
                for to in ("grok", "claude", "codex"):
                    card = native_runner(to, "hello", instance_id="sess-" + to, cwd=str(self.root))
                    self.assertTrue(card["ok"])
                    argv = card["argv"]
                    self.assertEqual(argv[1:], ["--resume", "sess-" + to])
                    joined = " ".join(argv).lower()
                    self.assertIn(to, Path(argv[0]).name.lower())
                    self.assertNotIn("ola-brain", joined)
                    self.assertNotIn("ola_brain", joined)
                    self.assertNotIn("side-chat", joined)
        self.assertEqual(len(calls), 3)

    def test_send_refuses_ola_brain_before_overlap_checks(self):
        spawned = {"n": 0}

        def runner(*_a, **_k):
            spawned["n"] += 1
            return {"ok": True, "to": "ola-brain", "session_id": "bad", "model": None, "usage_remaining": None, "body": "bad"}

        packed = {
            "thread": None,
            "role": None,
            "brief": None,
            "handoff": None,
            "instance_id": None,
            "worktree": None,
            "branch": "main",
            "pr": None,
            "git_sha": None,
        }
        with mock.patch("convoy.synapse.pack", return_value=packed):
            with mock.patch("convoy.synapse.live_on_branch", return_value=[{"session_id": "sess-other"}]):
                card = send_one(self.root, "ola-brain", "ping", runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("refuse wrapper target", card["error"])
        self.assertNotIn("two agents on one branch", card["error"])
        self.assertEqual(spawned["n"], 0)


if __name__ == "__main__":
    unittest.main()
