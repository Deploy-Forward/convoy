"""`convoy end --push --all` from the lead: every live chair ends and pushes its own
lane through end_task (same refusals), one handoff .md + .json lands, one feed row.
A named --seat ends one lane. Marco 2026-09-09."""
import json, subprocess, tempfile, unittest
from pathlib import Path

from convoy.convoy import bind, ensure_id, seat, update_seat
from convoy.end_all import end_all, render_handoff
from test.demo.end_heartbeat_test import FakeGit


class RoutingGit:
    """FakeGit per worktree: lane A clean, lane B dirty."""
    def __init__(self, by_wt):
        self.by_wt = by_wt
        self.calls = []
    def __call__(self, args, cwd):
        self.calls.append((tuple(args), Path(cwd)))
        return self.by_wt[Path(cwd).resolve()](args, cwd)


class EndOrchestra(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-endall-root-"))
        ensure_id(self.root); bind(self.root, "orchestra")
        self.wa = Path(tempfile.mkdtemp(prefix="wt-a-")); self.wb = Path(tempfile.mkdtemp(prefix="wt-b-")); self.wc = Path(tempfile.mkdtemp(prefix="wt-c-"))
        seat(self.root, "codex", "a-orchestra", worktree=str(self.wa))
        seat(self.root, "claude", "b-orchestra", worktree=str(self.wb))
        seat(self.root, "grok", "c-orchestra", worktree=str(self.wc))
        update_seat(self.root, "c-orchestra", archived=True)
        self.git = RoutingGit({self.wa.resolve(): FakeGit(), self.wb.resolve(): FakeGit(dirty=True), self.wc.resolve(): FakeGit()})

    def _feed(self):
        return [json.loads(l) for l in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_orchestra_ends_every_live_lane_and_pushes_only_the_clean_ones(self):
        card = end_all(self.root, push=True, git_runner=self.git, now="2026-09-09T01:02:03.000000Z")
        self.assertEqual(card["mode"], "orchestra")
        self.assertEqual([l["seat"] for l in card["lanes"]], ["a-orchestra", "b-orchestra"], "archived chair skipped")
        self.assertEqual(card["pushed"], ["a-orchestra"]); self.assertEqual(card["refused"], ["b-orchestra"])
        self.assertFalse(card["ok"], "one refused lane makes the orchestra not-ok, honestly")
        a = card["lanes"][0]; self.assertEqual((a["branch"], a["git_sha"], a["push_status"]), ("topic", "abc123", "pushed"))
        b = card["lanes"][1]; self.assertEqual(b["push_status"], "refused"); self.assertIn("uncommitted", b["error"])
        pushes = [c for c in self.git.calls if c[0] == ("push",)]
        self.assertEqual([p[1] for p in pushes], [self.wa], "exactly one plain push, on the clean lane only")
        md, js = Path(card["handoff_md"]), Path(card["handoff_json"])
        self.assertTrue(md.is_file() and js.is_file())
        self.assertIn("| a-orchestra | codex |", md.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(js.read_text(encoding="utf-8"))["pushed"], ["a-orchestra"])
        kinds = [r["kind"] for r in self._feed()]
        self.assertEqual(kinds.count("heartbeat"), 2, "one task-end row per lane, authored by the lane")
        self.assertEqual(kinds.count("end-all"), 1)
        by_author = {r.get("from") for r in self._feed() if r["kind"] == "heartbeat"}
        self.assertEqual(by_author, {"a-orchestra", "b-orchestra"})

    def test_named_seat_ends_one_lane(self):
        card = end_all(self.root, seat="a-orchestra", push=True, git_runner=self.git, write_files=False)
        self.assertTrue(card["ok"]); self.assertEqual(card["mode"], "seat"); self.assertEqual(card["pushed"], ["a-orchestra"])
        self.assertIsNone(card["handoff_md"])
        self.assertFalse(end_all(self.root, seat="nobody", git_runner=self.git)["ok"])

    def test_no_push_is_a_record_only_orchestra(self):
        card = end_all(self.root, push=False, git_runner=self.git, write_files=False)
        self.assertTrue(card["ok"]); self.assertEqual(card["pushed"], [])
        self.assertEqual([c for c in self.git.calls if c[0] == ("push",)], [])
        self.assertIn("not requested", render_handoff(card))
