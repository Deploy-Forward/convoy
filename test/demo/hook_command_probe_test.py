"""The inbox hook command must RESOLVE where the hook runs (audit 2026-09-03).

Every hook Convoy wrote since PR 40 was `convoy inbox --hook-pretooluse`, a
bare name. On the audited machine that name is shadowed by an unrelated
`convoy.cmd` shim (exits 0, knows no `inbox`), and Git Bash cannot see .cmd
shims at all (exit 127). Only grok-lead ever received, because its hook file
carried an absolute interpreter path. Hook files are gitignored per-worktree
state: they never travel, so an absolute path is not a portability bug.

Rule: probe the candidate (`<cmd> inbox --help` must exit 0 and print the
Python usage). Prefer the bare console script when it passes; else this
interpreter's resolved `-m convoy`; record `resolved_via` on the card; fail
closed with the install hint when neither passes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cmd
from convoy.identity import ensure_claude_inbox_hook, ensure_grok_inbox_hook


def _probe(ok_for):
    def probe(command):
        return command in ok_for
    return probe


class HookCommandResolution(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None

    def test_bare_console_script_wins_when_it_probes_ok(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({"convoy inbox --hook-pretooluse"})):
            r = cmd.resolve_inbox_hook_command()
        self.assertEqual(r["command"], "convoy inbox --hook-pretooluse")
        self.assertEqual(r["resolved_via"], "console-script")

    def test_falls_back_to_this_interpreter_when_bare_name_is_shadowed(self):
        py = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({py})):
            r = cmd.resolve_inbox_hook_command()
        self.assertEqual(r["command"], py)
        self.assertEqual(r["resolved_via"], "interpreter")

    def test_checkout_only_machine_gets_a_source_carrying_command(self):
        """Live 2026-09-03: `python -m convoy` fails without PYTHONPATH when the
        package is not installed; the third candidate carries the source dir."""
        def probe(command):
            return "sys.path.insert" in command
        with mock.patch.object(cmd, "_probe_inbox_command", probe):
            r = cmd.resolve_inbox_hook_command()
        self.assertEqual(r["resolved_via"], "interpreter+src")
        self.assertIn(cmd._source_dir().replace("\\", "\\\\"), r["command"].replace("\\\\", "\\\\"))
        self.assertTrue(r["command"].endswith("inbox --hook-pretooluse"))

    def test_fails_closed_when_nothing_resolves(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(set())):
            r = cmd.resolve_inbox_hook_command()
        self.assertIsNone(r["command"])
        self.assertIsNone(r["resolved_via"])
        self.assertIn("pipx", r["error"])

    def test_live_probe_rejects_a_shim_that_does_not_know_inbox(self):
        # the real probe on this machine: bare `convoy` may be an unrelated shim
        bare = cmd._probe_inbox_command("convoy inbox --hook-pretooluse")
        self.assertIsInstance(bare, bool)
        live = cmd.resolve_inbox_hook_command()
        self.assertIsNotNone(live["command"], "some candidate must resolve on the machine running the suite")
        self.assertIn(live["resolved_via"], ("console-script", "interpreter", "interpreter+src"))


class HookWritersUseResolvedCommand(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None
        self.wt = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".convoy").mkdir()
        (self.root / ".convoy" / "id").write_text("cvy_test\n", encoding="utf-8")

    def test_grok_and_claude_hooks_carry_the_resolved_command_and_say_how(self):
        py = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({py})):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
            c = ensure_claude_inbox_hook(self.wt, root=self.root)
        self.assertTrue(g["ok"] and c["ok"])
        self.assertEqual(g["resolved_via"], "interpreter")
        doc = json.loads((self.wt / ".grok" / "hooks" / "convoy-inbox.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"], py)
        settings = json.loads((self.wt / ".claude" / "settings.json").read_text(encoding="utf-8"))
        cmds = json.dumps(settings["hooks"])
        self.assertIn(py.replace("\\", "\\\\"), cmds)
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertEqual((self.wt / ".grok" / "convoy-root").read_text(encoding="utf-8").strip(), str(self.root.resolve()))

    def test_writers_fail_closed_when_nothing_resolves(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(set())):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
        self.assertFalse(g["ok"])
        self.assertIn("pipx", g["error"])
        self.assertFalse((self.wt / ".grok" / "hooks" / "convoy-inbox.json").exists())

    def test_a_working_prior_hook_is_kept_not_overwritten(self):
        """grok-lead's baked hook is the only one that ever delivered; a later
        ensure_first_run must not replace a command that still probes ok."""
        prior = '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "C:/venv/python.exe -m convoy inbox --hook-pretooluse", "timeout": 8}]}]}}\n'
        dest = self.wt / ".grok" / "hooks" / "convoy-inbox.json"
        dest.parent.mkdir(parents=True)
        dest.write_text(prior, encoding="utf-8")
        ok = {"C:/venv/python.exe -m convoy inbox --hook-pretooluse", "convoy inbox --hook-pretooluse"}
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(ok)):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
        self.assertTrue(g["ok"])
        self.assertFalse(g["written"])
        self.assertEqual(g["kept_existing"], "C:/venv/python.exe -m convoy inbox --hook-pretooluse")
        self.assertEqual(dest.read_text(encoding="utf-8"), prior)


if __name__ == "__main__":
    unittest.main()
