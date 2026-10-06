"""Hook files carry the bare `convoy` command, never a baked interpreter path.

A hook command is `convoy inbox --hook-pretooluse` or `convoy end --hook`, exactly. The writer
probes that spelling where the hook runs; when the bare name does not answer as a Convoy CLI, the
writer refuses (and so does the launch) with an error naming the PATH problem. It never falls back
to `<python> -m convoy` or a `sys.path.insert` command line, and it removes nothing on the way: a
hook file already on disk is left as it is.
"""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from convoy import cmd
from convoy.bringup import bring_up, ensure_first_run
from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.identity import ensure_claude_inbox_hook, ensure_end_hooks, ensure_grok_inbox_hook, ensure_inbox_hooks
from minted_helper import mark_minted

BARE = re.compile(r"^convoy (inbox --hook-pretooluse|end --hook)$")
HOOK_FILES = (".grok/hooks/convoy-inbox.json", ".claude/settings.local.json")


def _commands(node):
    if isinstance(node, dict):
        found = [node["command"]] if isinstance(node.get("command"), str) else []
        return found + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


class Fresh(unittest.TestCase):
    def setUp(self):
        cmd._RESOLVED = None
        cmd._END_RESOLVED = None
        self.addCleanup(setattr, cmd, "_RESOLVED", None)
        self.addCleanup(setattr, cmd, "_END_RESOLVED", None)
        self.wt = Path(tempfile.mkdtemp())
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        home = tempfile.mkdtemp(prefix="user-home-")   # never the operator's home
        for p in (mock.patch.dict(os.environ, {"USERPROFILE": home, "HOME": home}),
                  mock.patch("convoy.bringup.Path.home", return_value=Path(home))):
            p.start()
            self.addCleanup(p.stop)


class Resolution(Fresh):
    def test_only_the_bare_spelling_is_ever_probed(self):
        probed = []
        def probe(command):
            probed.append(command)
            return False
        with mock.patch.object(cmd, "_probe_inbox_command", probe), \
             mock.patch.object(cmd, "_probe_end_command", probe):
            inbox = cmd.resolve_inbox_hook_command()
            end = cmd.resolve_end_hook_command()
        self.assertEqual(probed, ["convoy inbox --hook-pretooluse", "convoy end --hook"])
        for r in (inbox, end):
            self.assertIsNone(r["command"])
            self.assertIn("PATH", r["error"])
            self.assertIn("convoy --version", r["error"])

    def test_the_bare_spelling_resolves_when_it_answers(self):
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: True), \
             mock.patch.object(cmd, "_probe_end_command", lambda c: True):
            self.assertEqual(cmd.resolve_inbox_hook_command()["command"], "convoy inbox --hook-pretooluse")
            self.assertEqual(cmd.resolve_end_hook_command()["command"], "convoy end --hook")


class Writers(Fresh):
    def test_every_written_command_is_bare(self):
        with mock.patch.object(cmd, "_probe_inbox_command", lambda c: True), \
             mock.patch.object(cmd, "_probe_end_command", lambda c: True):
            card = ensure_inbox_hooks(self.wt, root=self.root, harness="claude")
        self.assertTrue(card["ok"], card)
        for rel in HOOK_FILES:
            commands = _commands(json.loads((self.wt / rel).read_text(encoding="utf-8")))
            self.assertTrue(commands, rel)
            for c in commands:
                self.assertRegex(c, BARE, rel)

    def test_a_baked_command_already_on_disk_is_rewritten_bare(self):
        baked = "C:/venv/python.exe -m convoy inbox --hook-pretooluse"
        g = self.wt / ".grok" / "hooks" / "convoy-inbox.json"
        g.parent.mkdir(parents=True)
        g.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": baked}]}]}}),
                     encoding="utf-8")
        c = self.wt / ".claude" / "settings.local.json"
        c.parent.mkdir(parents=True)
        c.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "node mine.mjs"}]},
            {"hooks": [{"type": "command", "command": baked}]}]}}), encoding="utf-8")
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: True):
            rg = ensure_grok_inbox_hook(self.wt, root=self.root)
            rc = ensure_claude_inbox_hook(self.wt, root=self.root)
        self.assertTrue(rg["ok"] and rc["ok"], (rg, rc))
        self.assertTrue(all(BARE.match(x) for x in _commands(json.loads(g.read_text(encoding="utf-8")))))
        claude = _commands(json.loads(c.read_text(encoding="utf-8")))
        self.assertIn("node mine.mjs", claude)
        self.assertEqual([x for x in claude if x != "node mine.mjs" and not BARE.match(x)], [])

    def test_a_failed_probe_writes_nothing_and_removes_nothing(self):
        dead = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "convoy inbox --hook-pretooluse"}]}]}}
        g = self.wt / ".grok" / "hooks" / "convoy-inbox.json"
        g.parent.mkdir(parents=True)
        g.write_text(json.dumps(dead), encoding="utf-8")
        c = self.wt / ".claude" / "settings.local.json"
        c.parent.mkdir(parents=True)
        c.write_text(json.dumps({"hooks": {**dead["hooks"], "Stop": [
            {"hooks": [{"type": "command", "command": "convoy end --hook"}]}]}}), encoding="utf-8")
        before = {p: p.read_bytes() for p in (g, c)}
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: False), \
             mock.patch.object(cmd, "_probe_end_command", lambda command: False):
            card = ensure_inbox_hooks(self.wt, root=self.root)
        self.assertFalse(card["ok"])
        self.assertIn("PATH", card["error"])
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data, p)

    def test_a_failed_probe_on_a_fresh_worktree_writes_no_hook_file(self):
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: False), \
             mock.patch.object(cmd, "_probe_end_command", lambda command: False):
            ensure_inbox_hooks(self.wt, root=self.root)
            ensure_end_hooks(self.wt, root=self.root)
        for rel in HOOK_FILES:
            self.assertFalse((self.wt / rel).exists(), rel)


    def test_one_failed_probe_writes_no_hook_file_and_no_pointer(self):
        # Both commands resolve before either file is written: a convoy that answers
        # `inbox --help` but not `end --help` leaves the worktree as it was.
        for inbox_ok, end_ok in ((True, False), (False, True)):
            with self.subTest(inbox=inbox_ok, end=end_ok):
                wt = Path(tempfile.mkdtemp())
                cmd._RESOLVED = None
                cmd._END_RESOLVED = None
                with mock.patch.object(cmd, "_probe_inbox_command", lambda command, ok=inbox_ok: ok),                      mock.patch.object(cmd, "_probe_end_command", lambda command, ok=end_ok: ok):
                    card = ensure_inbox_hooks(wt, root=self.root)
                self.assertFalse(card["ok"])
                self.assertTrue(card.get("unresolved"))
                self.assertIn("PATH", card["error"])
                self.assertEqual(sorted(p.relative_to(wt).as_posix() for p in wt.rglob("*")), [])

class LaunchRefuses(Fresh):
    def test_first_run_refuses_when_bare_convoy_does_not_resolve(self):
        mark_minted(self.wt)
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: False), \
             mock.patch.object(cmd, "_probe_end_command", lambda command: False):
            card = ensure_first_run({"to": "grok", "worktree": str(self.wt)}, root=self.root, live=True)
        self.assertFalse(card["ok"])
        self.assertIn("PATH", card["error"])
        for rel in HOOK_FILES:
            self.assertFalse((self.wt / rel).exists(), rel)

    def test_bring_up_spawns_no_pane_when_bare_convoy_does_not_resolve(self):
        seat(self.root, "grok", "sess-g1", worktree=str(self.wt), resume="vendor-g1")
        spawned = []
        def runner(argv, *a, **k):
            spawned.append(argv)
            return {"ok": True, "pid": 1}
        with mock.patch.object(cmd, "_probe_inbox_command", lambda command: False), \
             mock.patch.object(cmd, "_probe_end_command", lambda command: False):
            d = bring_up(self.root, runner=runner, allow_unverified_launch=True)
        self.assertEqual(spawned, [])
        self.assertFalse(d["ok"], d)
        [win] = d["windows"]
        self.assertFalse(win["ok"])
        self.assertIn("PATH", win["error"])

    def test_convoy_skills_exits_nonzero_and_writes_no_hook_file_without_convoy_on_path(self):
        """The real probe, in the real hook shell, with a PATH that has no `convoy` on it."""
        empty = Path(tempfile.mkdtemp())
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}), redirect_stdout(buf):
            rc = main(["--root", str(self.root), "skills", "--worktree", str(self.wt)])
        card = json.loads(buf.getvalue())
        self.assertNotEqual(rc, 0, card)
        self.assertIn("PATH", card["hooks"]["error"])
        for rel in HOOK_FILES:
            self.assertFalse((self.wt / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
