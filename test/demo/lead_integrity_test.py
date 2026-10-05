"""Lead integrity: a thread's lead is a chair someone can reach, or it is none.

- start/onboard never names a lead: a new thread has no lead, and the start
  card's where line says `lead: none`.
- `convoy attach` (the proven-identity seat) takes a lead that is unset, or
  that names a harness with no seated chair (dangling). It keeps a real lead.
- `lead --to <chair> --as <author>` needs the author to be a seated chair and
  the current lead, unless the lead is unset or dangling.
- `lead --to <harness>` (legacy) needs a seated chair of that harness.
- bare `lead` reports `dangling` and `reachable_id` (the id `convoy list` shows).

Synthetic evidence only: no harness launches, no real home, no real index.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_id
from convoy.cli import main
from convoy.convoy import bind, read_id, read_lead, seat, set_lead
from convoy.layer import feed_since
from convoy.panes import identify

NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}
NO_FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None,
                "home_written": False, "settings_home": None}
FAKES = Path(__file__).resolve().parents[1] / "fakes"


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.addCleanup(self.owner.cleanup)
        base = Path(self.owner.name)
        self.root = base / "project"
        self.root.mkdir()
        home = base / "home"
        home.mkdir()
        env = patch.dict(os.environ, {"CONVOY_HOME": str(base / "convoy-home"), "HOME": str(home),
                                      "USERPROFILE": str(home)})
        env.start()
        self.addCleanup(env.stop)

    def cli(self, *args, proven=None):
        """One CLI call. The calling body is proven as `proven`, else as its own --as (an honest
        caller); proven=False, or neither, proves no chair."""
        if proven is None and "--as" in args:
            proven = args[args.index("--as") + 1]
        me = ({"ok": True, "chair": proven, "via": "environment"} if proven
              else {"ok": True, "chair": None, "via": None})
        out = io.StringIO()
        with redirect_stdout(out), patch("convoy.cli.identify", return_value=me):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])

    def lead_rows(self):
        return [r for r in feed_since(self.root, "1970-01-01T00:00:00Z") if r.get("kind") == "lead"]


class NewThreadHasNoLead(Sandbox):
    def setUp(self):
        super().setUp()
        path = str(FAKES) + os.pathsep + os.environ.get("PATH", "")
        for target, kw in (("convoy.onboard.probe", {"return_value": NULL_PROBE}),
                           ("convoy.onboard.ensure_first_run", {"return_value": NO_FIRST_RUN}),
                           ("convoy.bringup.ensure_first_run", {"return_value": NO_FIRST_RUN})):
            p = patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {"PATH": path})
        p.start()
        self.addCleanup(p.stop)

    def test_onboard_names_no_lead_and_the_where_line_says_none(self):
        from convoy.start_card import build_start_card
        rc, ob = self.cli("onboard", "--to", "grok", "--to", "claude", "--thread", "synthetic-thread",
                          "--checkout-root", str(self.root), "--github", "no")
        self.assertEqual(rc, 0, ob)
        self.assertTrue(ob["ok"], ob)
        self.assertEqual(ob["lead"], {"harness": None, "set": False})
        self.assertIsNone(read_lead(self.root))
        self.assertFalse((self.root / ".convoy" / "lead").exists())
        rc, card = self.cli("lead")
        self.assertIsNone(card["lead"])
        self.assertIsNone(card["lead_chair"])
        where = build_start_card(self.root, neurons_fn=lambda r: {"neurons": []})["lines"][0]
        self.assertIn("lead: none", where)


class AttachTakesAnUnreachableLead(Sandbox):
    def setUp(self):
        super().setUp()
        bind(self.root, "synthetic-project")
        self.procs = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                      {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]

    def attach(self):
        from convoy.sessions import attach_session
        me = lambda root, **kw: identify(root, pid=21, procs=self.procs, cwd=str(self.root),
                                         env={"CLAUDE_CODE_SESSION_ID": "synthetic-native-id"},
                                         allow_unseated=True)
        with patch("convoy.sessions.identify", side_effect=me), \
             patch("convoy.sessions.is_temp_root", return_value=False):
            card = attach_session(read_id(self.root), cwd=self.root)
        self.assertTrue(card["ok"], card)
        return card

    def test_attach_takes_an_unset_lead(self):
        card = self.attach()
        sid = card["chair"]
        self.assertEqual(read_lead(self.root), "claude")
        rows = self.lead_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["from"], rows[0]["to"]), (sid, sid))
        self.assertEqual(card["lead_taken"]["line"], "lead: taken (was none)")
        rc, out = self.cli("lead")
        self.assertEqual(out["lead_chair"], sid)
        self.assertFalse(out["dangling"])
        self.assertEqual(out["reachable_id"], neuron_id(read_id(self.root), sid))

    def test_attach_takes_a_dangling_lead(self):
        (self.root / ".convoy" / "lead").write_text("grok\n", encoding="utf-8")
        rc, before = self.cli("lead")
        self.assertTrue(before["dangling"])
        self.assertIsNone(before["reachable_id"])
        card = self.attach()
        sid = card["chair"]
        self.assertEqual(read_lead(self.root), "claude")
        rows = self.lead_rows()
        self.assertEqual((rows[-1]["from"], rows[-1]["to"]), (sid, sid))
        self.assertEqual(card["lead_taken"]["line"], "lead: taken (was dangling grok)")

    def test_attach_keeps_a_real_lead(self):
        seat(self.root, "codex", "synthetic-lead")
        set_lead(self.root, "codex")
        card = self.attach()
        self.assertEqual(read_lead(self.root), "codex")
        self.assertEqual(self.lead_rows(), [])
        self.assertIsNone(card["lead_taken"])
        rc, out = self.cli("lead")
        self.assertEqual(out["lead_chair"], "synthetic-lead")
        self.assertFalse(out["dangling"])
        self.assertEqual(out["reachable_id"], neuron_id(read_id(self.root), "synthetic-lead"))


class PassLeadNeedsTheLead(Sandbox):
    def setUp(self):
        super().setUp()
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "chair-a", resume="native-chair-a")
        seat(self.root, "codex", "chair-b", resume="native-chair-b")
        seat(self.root, "grok", "chair-c", resume="native-chair-c")

    def test_a_non_chair_cannot_take_an_unset_lead(self):
        rc, out = self.cli("lead", "--to", "chair-b", "--as", "somebody")
        self.assertEqual(rc, 1, out)
        self.assertIn("not a seated chair", out["error"])
        self.assertIsNone(read_lead(self.root))
        self.assertEqual(self.lead_rows(), [])

    def test_a_seated_chair_may_take_an_unset_lead(self):
        rc, out = self.cli("lead", "--to", "chair-a", "--as", "chair-a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["lead_chair"], "chair-a")

    def test_a_non_lead_chair_cannot_pass_a_held_lead(self):
        self.assertEqual(self.cli("lead", "--to", "chair-a", "--as", "chair-a")[0], 0)
        rc, out = self.cli("lead", "--to", "chair-c", "--as", "chair-b")
        self.assertEqual(rc, 1, out)
        self.assertIn("not the current lead", out["error"])
        self.assertEqual(self.cli("lead")[1]["lead_chair"], "chair-a")

    def test_the_current_lead_passes_it(self):
        self.assertEqual(self.cli("lead", "--to", "chair-a", "--as", "chair-a")[0], 0)
        rc, out = self.cli("lead", "--to", "chair-b", "--as", "chair-a")
        self.assertEqual(rc, 0, out)
        rc, read = self.cli("lead")
        self.assertEqual((read["lead"], read["lead_chair"]), ("codex", "chair-b"))
        self.assertEqual(read["reachable_id"], neuron_id(read_id(self.root), "chair-b"))
        self.assertEqual((self.lead_rows()[-1]["from"], self.lead_rows()[-1]["to"]), ("chair-a", "chair-b"))

    def test_any_seated_chair_may_take_a_dangling_lead(self):
        (self.root / ".convoy" / "lead").write_text("cursor\n", encoding="utf-8")
        rc, out = self.cli("lead", "--to", "chair-c", "--as", "chair-b")
        self.assertEqual(rc, 0, out)
        self.assertEqual(read_lead(self.root), "grok")

    def test_legacy_harness_lead_needs_a_chair_of_that_harness(self):
        rc, out = self.cli("lead", "--to", "cursor", proven="chair-a")
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["error"], "no chair of cursor on this thread")
        self.assertIsNone(read_lead(self.root))
        rc, out = self.cli("lead", "--to", "codex", proven="chair-a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(read_lead(self.root), "codex")
        # the harness names one chair, so the pass is stamped to that chair
        self.assertEqual((self.lead_rows()[-1]["from"], self.lead_rows()[-1]["to"]), ("chair-a", "chair-b"))

    def test_legacy_harness_lead_cannot_bypass_a_held_lead(self):
        self.assertEqual(self.cli("lead", "--to", "chair-a", "--as", "chair-a")[0], 0)
        rc, out = self.cli("lead", "--to", "codex", proven="chair-b")
        self.assertEqual(rc, 1, out)
        self.assertIn("not the current lead", out["error"])
        self.assertEqual(self.cli("lead")[1]["lead_chair"], "chair-a")

    def test_legacy_harness_lead_with_two_chairs_of_it_refuses(self):
        seat(self.root, "codex", "chair-b2", resume="native-chair-b2")
        rc, out = self.cli("lead", "--to", "codex", proven="chair-a")
        self.assertEqual(rc, 1, out)
        self.assertIn("2 chairs of codex", out["error"])
        self.assertIsNone(read_lead(self.root))


class LeadChangesNeedAProvenAuthor(Sandbox):
    def setUp(self):
        super().setUp()
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "chair-a", resume="native-chair-a")
        seat(self.root, "codex", "chair-b", resume="native-chair-b")

    def test_an_unproven_caller_cannot_take_an_unset_lead(self):
        rc, out = self.cli("lead", "--to", "chair-a", "--as", "chair-a", proven=False)
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot prove the calling chair", out["error"])
        self.assertIsNone(read_lead(self.root))

    def test_as_cannot_disagree_with_the_proven_chair(self):
        self.assertEqual(self.cli("lead", "--to", "chair-a", "--as", "chair-a")[0], 0)
        rc, out = self.cli("lead", "--to", "chair-b", "--as", "chair-a", proven="chair-b")
        self.assertEqual(rc, 1, out)
        self.assertIn("disagrees", out["error"])
        self.assertEqual(self.cli("lead")[1]["lead_chair"], "chair-a")

    def test_the_proven_chair_is_the_author_without_as(self):
        rc, out = self.cli("lead", "--to", "chair-a", proven="chair-a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.lead_rows()[-1]["from"], "chair-a")


class TheRealIdentifyProvesTheAuthor(Sandbox):
    """`lead --to` through the real panes.identify: an injected process table and env, no
    fixed identify answer."""

    def setUp(self):
        super().setUp()
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "chair-a", resume="synthetic-native-a")
        seat(self.root, "codex", "chair-b", resume="synthetic-native-b")
        self.procs = [{"pid": 20, "ppid": 1, "cmdline": "claude", "cwd": None},
                      {"pid": 21, "ppid": 20, "cmdline": "python -m convoy", "cwd": None}]

    def real(self, env, *args):
        real = lambda root, **kw: identify(root, pid=21, procs=self.procs, cwd=str(self.root), env=env)
        out = io.StringIO()
        with redirect_stdout(out), patch("convoy.cli.identify", side_effect=real):
            rc = main(["--root", str(self.root), *args])
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_the_seats_native_id_proves_the_author_and_the_pass_lands(self):
        rc, out = self.real({"CLAUDE_CODE_SESSION_ID": "synthetic-native-a"}, "lead", "--to", "chair-b")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.lead_rows()[-1]["from"], self.lead_rows()[-1]["to"]), ("chair-a", "chair-b"))

    def test_without_the_native_id_the_pass_refuses(self):
        rc, out = self.real({}, "lead", "--to", "chair-b")
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot prove the calling chair", out["error"])
        self.assertEqual(self.lead_rows(), [])


class NoPassToAChairThatCouldNeverPassItOn(Sandbox):
    def test_a_chair_with_no_recorded_session_id_cannot_be_passed_the_lead(self):
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "chair-a", resume="native-chair-a")
        seat(self.root, "grok", "chair-fresh")
        rc, out = self.cli("lead", "--to", "chair-fresh", "--as", "chair-a")
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["error"], "refuse lead pass: chair-fresh has no recorded session id, so it could "
                                       "never pass the lead on; let it take a turn first")
        self.assertEqual(self.lead_rows(), [])


class ADetachedLeadIsDangling(Sandbox):
    def test_a_detached_lead_chair_is_not_inherited_by_its_harness(self):
        from convoy.convoy import update_seat
        from convoy.start_card import build_start_card
        bind(self.root, "synthetic-project")
        seat(self.root, "claude", "claude-1", resume="native-claude-1")
        seat(self.root, "claude", "claude-2", resume="native-claude-2")
        self.assertEqual(self.cli("lead", "--to", "claude-1", "--as", "claude-1")[0], 0)
        update_seat(self.root, "claude-1", detached=True)
        rc, out = self.cli("lead")
        self.assertTrue(out["dangling"], out)
        self.assertIsNone(out["lead_chair"])
        self.assertIsNone(out["reachable_id"])
        where = build_start_card(self.root, neurons_fn=lambda r: {"neurons": []})["lines"][0]
        self.assertIn("lead: dangling claude", where)


if __name__ == "__main__":
    unittest.main()
