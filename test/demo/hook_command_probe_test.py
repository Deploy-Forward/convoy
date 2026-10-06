"""The inbox hook command must RESOLVE where the hook runs, and it is always bare.

A hook file carries `convoy inbox --hook-pretooluse` (or `convoy end --hook`), the console
script's own name. The writer probes it the way the hook runs it (`<cmd> inbox --help` must exit
0 and print the Python usage): an unrelated `convoy.cmd` shim that exits 0 with its own help
fails, and so does a name Git Bash cannot see (exit 127). When the bare name fails, the writer
fails closed with the install hint and the PATH problem; it never bakes an interpreter path in
its place, because a baked path pins one machine's interpreter into a worktree. `convoy
--version` names the executable that runs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cmd
from convoy.identity import ensure_claude_inbox_hook, ensure_grok_inbox_hook

BARE = "convoy inbox --hook-pretooluse"


def _probe(ok_for):
    def probe(command):
        return command in ok_for
    return probe


class HookCommandResolution(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None
        cmd._END_RESOLVED = None

    def test_bare_console_script_wins_when_it_probes_ok(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({BARE})):
            r = cmd.resolve_inbox_hook_command()
        self.assertEqual(r["command"], BARE)
        self.assertEqual(r["resolved_via"], "console-script")

    def test_a_shadowed_bare_name_fails_closed_instead_of_baking_this_interpreter(self):
        py = cmd._quote(sys.executable) + " -m convoy inbox --hook-pretooluse"
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({py})):
            r = cmd.resolve_inbox_hook_command()
        self.assertIsNone(r["command"])
        self.assertIn("PATH", r["error"])

    def test_fails_closed_when_nothing_resolves(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(set())):
            r = cmd.resolve_inbox_hook_command()
        self.assertIsNone(r["command"])
        self.assertIsNone(r["resolved_via"])
        self.assertIn("pipx", r["error"])

    def test_live_probe_rejects_a_shim_that_does_not_know_inbox(self):
        # the real probe on this machine: bare `convoy` may be an unrelated shim
        bare = cmd._probe_inbox_command(BARE)
        self.assertIsInstance(bare, bool)
        live = cmd.resolve_inbox_hook_command()
        self.assertEqual(live["command"], BARE if bare else None)
        self.assertIn(live["resolved_via"], ("console-script", None))

    @unittest.skipUnless(sys.platform == "win32", "Windows shell selection")
    def test_windows_hook_shell_prefers_git_bash_over_wsl_bash_on_path(self):
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        if not git_bash.is_file():
            self.skipTest("Git Bash is not installed in the standard location")
        with mock.patch.object(cmd.shutil, "which", return_value=r"C:\Windows\System32\bash.exe"):
            shell = cmd.hook_shell()
        self.assertEqual(shell, [str(git_bash), "-c"])

    def test_end_hook_has_the_same_probed_bare_resolution(self):
        with mock.patch.object(cmd, "_probe_end_command", _probe({"convoy end --hook"})):
            result = cmd.resolve_end_hook_command()
        self.assertEqual(result["command"], "convoy end --hook")
        self.assertEqual(result["resolved_via"], "console-script")


class HookWritersUseResolvedCommand(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None
        cmd._END_RESOLVED = None
        self.wt = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".convoy").mkdir()
        (self.root / ".convoy" / "id").write_text("cvy_test\n", encoding="utf-8")

    def test_grok_and_claude_hooks_carry_the_bare_command_and_say_how(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe({BARE})):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
            c = ensure_claude_inbox_hook(self.wt, root=self.root)
        self.assertTrue(g["ok"] and c["ok"])
        self.assertEqual(g["resolved_via"], "console-script")
        doc = json.loads((self.wt / ".grok" / "hooks" / "convoy-inbox.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"], BARE)
        settings = json.loads((self.wt / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertIn("PostToolUse", settings["hooks"], "a fresh claude install stamps usage rows")
        self.assertEqual(settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"], BARE)
        self.assertEqual((self.wt / ".grok" / "convoy-root").read_text(encoding="utf-8").strip(), str(self.root.resolve()))

    def test_writers_fail_closed_when_nothing_resolves(self):
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(set())):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
        self.assertFalse(g["ok"])
        self.assertIn("pipx", g["error"])
        self.assertFalse((self.wt / ".grok" / "hooks" / "convoy-inbox.json").exists())

    def test_claude_stop_hook_carries_end_heartbeat_and_codex_gets_no_project_file(self):
        """Codex's Stop hook is the convoy plugin's (codex-hooks.json), trusted once for every
        project; a project .codex/hooks.json is a new untrusted key in each worktree."""
        from convoy.identity import ensure_end_hooks

        with mock.patch.object(cmd, "_probe_end_command", _probe({"convoy end --hook"})):
            card = ensure_end_hooks(self.wt, root=self.root)
        self.assertTrue(card["ok"], card)
        self.assertFalse((self.wt / ".codex" / "hooks.json").exists())
        claude = json.loads((self.wt / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        self.assertEqual(claude["hooks"]["Stop"][0]["hooks"][0]["command"], "convoy end --hook")
        self.assertEqual(
            (self.wt / ".codex" / "convoy-root").read_text(encoding="utf-8").strip(),
            str(self.root.resolve()),
        )

    def test_a_baked_prior_hook_is_rewritten_bare_with_the_current_events(self):
        """A file an older Convoy wrote with a baked interpreter path, and only PreToolUse, gets
        the bare command and the current event set; a second run rewrites nothing."""
        prior = '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "C:/venv/python.exe -m convoy inbox --hook-pretooluse", "timeout": 8}]}]}}\n'
        dest = self.wt / ".grok" / "hooks" / "convoy-inbox.json"
        dest.parent.mkdir(parents=True)
        dest.write_text(prior, encoding="utf-8")
        ok = {"C:/venv/python.exe -m convoy inbox --hook-pretooluse", BARE}
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(ok)):
            g = ensure_grok_inbox_hook(self.wt, root=self.root)
        self.assertTrue(g["ok"])
        self.assertTrue(g["written"])
        doc = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(set(doc["hooks"]), {"PreToolUse", "PostToolUse", "Stop"})
        for ev in ("PreToolUse", "PostToolUse", "Stop"):
            self.assertEqual(doc["hooks"][ev][0]["hooks"][0]["command"], BARE)
        with mock.patch.object(cmd, "_probe_inbox_command", _probe(ok)):
            again = ensure_grok_inbox_hook(self.wt, root=self.root)
        self.assertFalse(again["written"])


class DeadHooksAreLeftAsTheyAre(unittest.TestCase):
    """A failed resolve writes nothing and removes nothing: the launch refuses instead, so no pane
    starts with a hook that cannot run, and the files on disk stay the person's to change."""

    def setUp(self):
        cmd._RESOLVED = None; cmd._END_RESOLVED = None   # a success is cached per process; these need a fresh failure
        self.addCleanup(setattr, cmd, '_RESOLVED', None); self.addCleanup(setattr, cmd, '_END_RESOLVED', None)
        self.wt = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".convoy").mkdir()
        (self.root / ".convoy" / "id").write_text("cvy_test\n", encoding="utf-8")

    def test_claude_settings_are_left_byte_for_byte(self):
        dest = self.wt / ".claude" / "settings.local.json"; dest.parent.mkdir(parents=True)
        dest.write_text(json.dumps({"hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python -m ola_brain.cli guard"}]},
                           {"hooks": [{"type": "command", "command": "convoy inbox --hook-pretooluse", "timeout": 8}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "convoy inbox --hook-pretooluse"}]}],
        }}), encoding="utf-8")
        before = dest.read_bytes()
        with mock.patch.object(cmd, "_probe_inbox_command", return_value=False):
            r = ensure_claude_inbox_hook(self.wt, root=self.root)
        self.assertFalse(r["ok"])
        self.assertNotIn("removed_dead", r)
        self.assertEqual(dest.read_bytes(), before)

    def test_grok_hook_file_and_codex_file_are_left_alone(self):
        from convoy.identity import ensure_end_hooks
        g = self.wt / ".grok" / "hooks" / "convoy-inbox.json"; g.parent.mkdir(parents=True)
        g.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "convoy inbox --hook-pretooluse"}]}]}}), encoding="utf-8")
        h = self.wt / ".codex" / "hooks.json"; h.parent.mkdir(parents=True)
        h.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "convoy end --hook"}]}],
            "SessionStart": [{"hooks": [{"type": "command", "command": "node vendor.mjs"}]}],
        }}), encoding="utf-8")
        before = {p: p.read_bytes() for p in (g, h)}
        with mock.patch.object(cmd, "_probe_inbox_command", return_value=False), \
             mock.patch.object(cmd, "_probe_end_command", return_value=False):
            rg = ensure_grok_inbox_hook(self.wt, root=self.root)
            ensure_end_hooks(self.wt, root=self.root)
        self.assertFalse(rg["ok"])
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data, p)


if __name__ == "__main__":
    unittest.main()
