"""Read verbs write no home file and start no harness binary unless --probe is passed.

`start`, `onboard` and `glance` describe a machine; they used to change it. Onboarding a
root ran the full first-run preparation, which wrote the person's machine-wide Claude
settings, and every present harness was probed for usage by running its CLI
(`claude -p /usage`, `codex exec /status`). Glance probed every harness the same way. Now
the first run is reported as a plan (would_write_home), usage stays null (unknown, not
zero) and `probed` is false, until the caller passes --probe (probe=True).

A dry send and the start card leave the thread root as they found it too: no inbox
directory is created on read, and no contract copy is written by a dry send.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.glance import build_glance
from convoy.onboard import onboard
from convoy.start_card import build_start_card

READING = {"usage_remaining": 40, "limited": False, "raw": "40% left"}


def _snapshot(base: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for dirpath, dirs, names in os.walk(base):
        for name in dirs:
            files[str(Path(dirpath) / name) + "/"] = b"dir"
        for name in names:
            p = Path(dirpath) / name
            try:
                files[str(p)] = p.read_bytes()
            except OSError:
                files[str(p)] = b"<unreadable>"
    return files


def _cli(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(list(argv))
    return rc, json.loads(buf.getvalue())


class ReadVerbsArePure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        ensure_id(self.root)
        bind(self.root, "read-pure")
        self.home = Path(tempfile.mkdtemp())
        self.probe = mock.Mock(return_value=dict(READING))
        present = lambda name, *a, **k: "C:/Tools/" + str(name) + ".exe"  # noqa: E731
        for p in (mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}),
                  mock.patch("pathlib.Path.home", return_value=self.home),
                  mock.patch("convoy.onboard._which", side_effect=present),
                  mock.patch("convoy.glance.shutil.which", side_effect=present),
                  mock.patch("convoy.onboard.probe", self.probe),
                  mock.patch("convoy.glance.probe", self.probe),
                  mock.patch("convoy.rail.probe", self.probe),
                  mock.patch("convoy.usage.probe", self.probe)):
            p.start()
            self.addCleanup(p.stop)

    def test_onboard_writes_no_home_file(self):
        before = _snapshot(self.home)
        card = onboard(self.root, ["claude"], checkout_root=str(self.root))
        self.assertTrue(card["ok"], card)
        self.assertEqual(_snapshot(self.home), before, card)
        first_run = card["harnesses"][0]["first_run"]
        self.assertFalse(first_run["home_written"])
        self.assertIn(str(self.home / ".claude" / "settings.json"), first_run["would_write_home"])

    def test_onboard_probes_no_harness_without_probe(self):
        card = onboard(self.root, ["claude", "codex"], checkout_root=str(self.root))
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.probe.call_count, 0)
        for h in card["harnesses"]:
            self.assertTrue(h["present"])
            self.assertFalse(h["probed"])
            self.assertIsNone(h["usage_remaining"])

    def test_onboard_probe_opt_in_reads_usage(self):
        card = onboard(self.root, ["claude"], checkout_root=str(self.root), probe=True)
        self.assertEqual(self.probe.call_count, 1)
        self.assertTrue(card["harnesses"][0]["probed"])
        self.assertEqual(card["harnesses"][0]["usage_remaining"], 40)

    def test_cli_start_writes_no_home_file_and_probes_nothing(self):
        before = _snapshot(self.home)
        rc, card = _cli("--root", str(self.root), "start", str(self.root), "--to", "claude", "--to", "codex")
        self.assertEqual(_snapshot(self.home), before, card)
        self.assertEqual(self.probe.call_count, 0, card)

    def test_cli_glance_probes_nothing_without_probe(self):
        rc, card = _cli("--root", str(self.root), "glance")
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.probe.call_count, 0, card)
        self.assertFalse(card["probed"])
        for row in card["overall"].values():
            self.assertIsNone(row["usage_remaining"])

    def test_cli_glance_probe_flag_reads_usage(self):
        rc, card = _cli("--root", str(self.root), "glance", "--probe")
        self.assertEqual(rc, 0, card)
        self.assertGreater(self.probe.call_count, 0)
        self.assertTrue(card["probed"])

    def test_glance_library_default_probes_nothing(self):
        card = build_glance(self.root)
        self.assertEqual(self.probe.call_count, 0, card)
        self.assertFalse(card["probed"])

    def test_cli_rail_probes_nothing_without_probe(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        seat(self.root, "codex", "chair2", worktree=str(Path(tempfile.mkdtemp())))
        rc, card = _cli("--root", str(self.root), "rail")
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.probe.call_count, 0, card)
        self.assertFalse(card["probed"])
        self.assertEqual(sorted(card["usage"]), ["claude", "codex"])
        for row in card["usage"].values():
            self.assertIsNone(row["usage_remaining"])

    def test_cli_rail_probe_flag_reads_usage(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        rc, card = _cli("--root", str(self.root), "rail", "--probe")
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.probe.call_count, 1)
        self.assertTrue(card["probed"])
        self.assertEqual(card["usage"]["claude"]["usage_remaining"], 40)

    def test_rail_library_default_probes_nothing(self):
        from convoy.rail import build_rail
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        card = build_rail(self.root)
        self.assertEqual(self.probe.call_count, 0, card)
        self.assertFalse(card["probed"])

    def test_start_card_creates_no_inbox_dir(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        inbox = self.root / ".convoy" / "inbox"
        self.assertFalse(inbox.exists())
        build_start_card(self.root)
        self.assertFalse(inbox.exists())

    def test_dry_send_writes_no_contract_copy(self):
        seat(self.root, "claude", "chair", worktree=str(Path(tempfile.mkdtemp())))
        before = _snapshot(self.root / ".convoy")
        _cli("--root", str(self.root), "send", "--to", "claude", "hello", "--dry-run")
        self.assertEqual(sorted(set(_snapshot(self.root / ".convoy")) - set(before)), [])


if __name__ == "__main__":
    unittest.main()
