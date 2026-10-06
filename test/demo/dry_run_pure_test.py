"""A dry run writes nothing: no home file, no trust store, no worktree file, no git exclude.

`relaunch --dry-run` and `bring-up --dry-run` promise to spawn and write nothing. Each one
used to run the full first-run preparation, which wrote the person's machine-wide Claude
trust store and settings, the convoy-end skill copies, the Grok agent file and entries in
.git/info/exclude. A dry run now returns the plan (would_write) and leaves every byte as it
was. A live first run stamps the launch heartbeat for the chair it prepares.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import bring_up, ensure_first_run
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.relaunch import relaunch


def _snapshot(*dirs: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for base in dirs:
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                p = Path(dirpath) / name
                try:
                    files[str(p)] = p.read_bytes()
                except OSError:
                    files[str(p)] = b"<unreadable>"
    return files


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


class DryRunsArePure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        _git_init(self.root)
        ensure_id(self.root)
        bind(self.root, "dry-pure")
        self.home = Path(tempfile.mkdtemp())
        self.wt_claude = Path(tempfile.mkdtemp())
        self.wt_grok = Path(tempfile.mkdtemp())
        _git_init(self.wt_claude)
        _git_init(self.wt_grok)
        seat(self.root, "claude", "chair-claude", worktree=str(self.wt_claude), resume="11111111-1111-1111-1111-111111111111")
        seat(self.root, "grok", "chair-grok", worktree=str(self.wt_grok), resume="chair-grok")
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch("convoy.bringup.Path.home", return_value=self.home),
                  mock.patch("convoy.bringup.shutil.which", side_effect=lambda name, *a, **k: "C:/Tools/" + str(name) + ".exe")):
            p.start()
            self.addCleanup(p.stop)

    def _dirs(self):
        return (self.home, self.wt_claude, self.wt_grok, self.root)

    def test_relaunch_dry_run_writes_nothing(self):
        before = _snapshot(*self._dirs())
        card = relaunch(self.root, runner=None)
        after = _snapshot(*self._dirs())
        self.assertEqual(sorted(set(after) - set(before)), [], card)
        self.assertEqual([k for k in before if after.get(k) != before[k]], [], card)

    def test_bring_up_dry_run_writes_nothing(self):
        before = _snapshot(*self._dirs())
        card = bring_up(self.root)
        after = _snapshot(*self._dirs())
        self.assertEqual(sorted(set(after) - set(before)), [], card)
        self.assertEqual([k for k in before if after.get(k) != before[k]], [], card)
        by = {w["to"]: w for w in card["windows"]}
        self.assertEqual(by["claude"]["first_run"]["trust_stores_written"], [])
        self.assertFalse(by["claude"]["first_run"]["home_written"])

    def test_bring_up_dry_run_reports_what_it_would_write(self):
        card = bring_up(self.root)
        by = {w["to"]: w for w in card["windows"]}
        claude = by["claude"]["first_run"]
        self.assertTrue(claude["dry_run"])
        self.assertIn(".claude/settings.local.json", claude["dry_run_writes"])
        self.assertIn(str(self.home / ".claude.json"), claude["would_write_home"])
        # Convoy writes no grok agent file, live or dry, so a dry run plans none.
        self.assertNotIn(".grok/agents/convoy-neuron.md", by["grok"]["first_run"]["dry_run_writes"])
        self.assertNotIn("agent_path", by["grok"]["first_run"])

    def test_bring_up_dry_run_gives_an_agent_less_grok_seat_no_agent(self):
        card = bring_up(self.root)
        by = {w["to"]: w for w in card["windows"]}
        self.assertNotIn("--agent", by["grok"]["argv"])
        row = [s for s in list_seats(self.root) if s.get("session_id") == "chair-grok"][-1]
        self.assertFalse(row.get("agent"), row)

    def test_live_first_run_stamps_launch_heartbeat(self):
        row = [s for s in list_seats(self.root) if s.get("session_id") == "chair-claude"][-1]
        with mock.patch("convoy.inbox.stamp_usage_row", return_value={"ts": "t"}) as stamp, \
             mock.patch("convoy.bringup.ensure_inbox_hooks", return_value={"ok": True, "written": False}), \
             mock.patch("convoy.bringup.ensure_hook_trust", return_value={"trust": []}):
            card = ensure_first_run(row, root=self.root, live=True)
        self.assertEqual(stamp.call_count, 1, card)
        self.assertEqual(stamp.call_args.args[1], "chair-claude")
        self.assertEqual(card["usage_heartbeat"], "t")

    def test_live_first_run_records_heartbeat_error_on_the_card(self):
        row = [s for s in list_seats(self.root) if s.get("session_id") == "chair-claude"][-1]
        with mock.patch("convoy.inbox.stamp_usage_row", side_effect=OSError("synthetic")), \
             mock.patch("convoy.bringup.ensure_inbox_hooks", return_value={"ok": True, "written": False}), \
             mock.patch("convoy.bringup.ensure_hook_trust", return_value={"trust": []}):
            card = ensure_first_run(row, root=self.root, live=True)
        self.assertIsNone(card["usage_heartbeat"])
        self.assertIn("synthetic", card["usage_heartbeat_error"])

    def test_unexpected_heartbeat_error_never_breaks_the_first_run_card(self):
        row = [s for s in list_seats(self.root) if s.get("session_id") == "chair-claude"][-1]
        with mock.patch("convoy.inbox.stamp_usage_row", side_effect=TypeError("synthetic type")), \
             mock.patch("convoy.bringup.ensure_inbox_hooks", return_value={"ok": True, "written": False}), \
             mock.patch("convoy.bringup.ensure_hook_trust", return_value={"trust": []}):
            card = ensure_first_run(row, root=self.root, live=True)
        self.assertTrue(card["ok"], card)
        self.assertIn("TypeError: synthetic type", card["usage_heartbeat_error"])
        self.assertIn("trust_stores_written", card)


if __name__ == "__main__":
    unittest.main()
