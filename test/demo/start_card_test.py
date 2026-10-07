"""The start card: a new session starts synced with what the other neurons on this thread committed to.

After `start` binds, it returns a card that is pointer-first and size-budgeted: one line per item,
with a path or id to read more, never file contents. Every section reports unknown as unknown.

  where        repo, branch, ahead/behind its upstream, dirty, thread (id and name), lead
  who          the neurons: id, harness, model, active, last seen
  commitments  open sends (no read and no citation, older than the ack time, token, age, from -> to),
               the latest handoff per neuron (one line and its path), recent commits per neuron
               worktree (branch, last three short shas and subjects)
  next         the single resume pointer: the lead's latest handoff, or "no handoff: read thread.md"
  notes        one line per thing start chose not to do, so nothing changes silently

Past the line budget the card ends with "+N more" and the command that shows everything.

The fixture is a thread root and two neuron worktrees, each a scratch git repository in a temporary
folder, with one open send and one handoff. Ids are synthetic; nothing is launched or probed.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.activity import neuron_activity, neuron_id
from convoy.convoy import bind, ensure_id, seat, set_lead
from convoy.inbox import enqueue
from convoy.start_card import LINE_BUDGET, build_start_card
try:
    from test.demo.write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401
except ModuleNotFoundError:  # discovered as a top-level module
    from write_gate_fixture import open_write_gate, write_gate, write_gate_if  # noqa: F401

NOW = datetime.now(timezone.utc)
CHAIR_A = "chair-a"
CHAIR_B = "chair-b"
OPEN = format(1, "032x")
ANSWERED = format(2, "032x")


def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test",
                           *args], capture_output=True, text=True, check=True).stdout


def repo_with_commits(path, subjects):
    git(path, "init", "-q", "-b", "main")
    for n, subject in enumerate(subjects):
        (Path(path) / ("f" + str(n))).write_text(subject, encoding="utf-8")
        git(path, "add", ".")
        git(path, "commit", "-qm", subject)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convoy-card-root-"))
        remote = Path(tempfile.mkdtemp(prefix="convoy-card-remote-"))
        git(remote, "init", "-q", "--bare", "-b", "main")
        repo_with_commits(self.root, ["root one"])
        git(self.root, "remote", "add", "origin", str(remote))
        git(self.root, "push", "-q", "-u", "origin", "main")
        (self.root / "f9").write_text("ahead", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "root two")
        self.cid = ensure_id(self.root)
        bind(self.root, "synthetic-thread")
        set_lead(self.root, CHAIR_A)
        self.wt_a = Path(tempfile.mkdtemp(prefix="convoy-card-wt-a-"))
        self.wt_b = Path(tempfile.mkdtemp(prefix="convoy-card-wt-b-"))
        repo_with_commits(self.wt_a, ["a one", "a two", "a three", "a four"])
        repo_with_commits(self.wt_b, ["b one"])
        seat(self.root, "claude", CHAIR_A, worktree=str(self.wt_a), model="claude-synthetic")
        seat(self.root, "codex", CHAIR_B, worktree=str(self.wt_b), model="codex-synthetic")
        old = iso(NOW - timedelta(minutes=30))
        for token in (OPEN, ANSWERED):
            enqueue(self.root, CHAIR_B, "PRIVATE-BODY-TEXT", to="codex", token=token)
            self.feed({"ts": old, "kind": "synapse", "instance_id": CHAIR_B, "summary": "send codex", "to": "codex",
                       "token": token, "from": CHAIR_A, "verified_by": "environment"})
        self.feed({"ts": iso(NOW - timedelta(minutes=5)), "kind": "note", "instance_id": CHAIR_B, "from": CHAIR_B,
                   "summary": "re token " + ANSWERED + ": done", "to": CHAIR_A, "verified_by": "environment"})
        handoffs = self.root / ".convoy" / "handoff"
        handoffs.mkdir(parents=True, exist_ok=True)
        (handoffs / (CHAIR_A + ".rolling.md")).write_text("# Rolling handoff\n\nBuilt the parser; next is the CLI.\n"
                                                         "PRIVATE-HANDOFF-DETAIL\n", encoding="utf-8")

    def feed(self, row):
        path = self.root / ".convoy" / "feed.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def card(self, **kwargs):
        return build_start_card(self.root, neurons_fn=lambda r: neuron_activity(r, procs=[]), **kwargs)


class Where(Fixture):
    def test_where_names_the_repo_branch_upstream_dirty_thread_and_lead(self):
        where = self.card()["where"]
        self.assertEqual(Path(where["repo"]).resolve(), self.root.resolve())
        self.assertEqual(where["branch"], "main")
        self.assertEqual((where["ahead"], where["behind"]), (1, 0))
        self.assertFalse(where["dirty"])
        self.assertEqual(where["thread"], {"id": self.cid, "name": "synthetic-thread"})
        self.assertEqual(where["lead"], CHAIR_A)

    def test_a_lead_with_no_seated_chair_reads_dangling(self):
        set_lead(self.root, "cursor")
        self.assertIn("lead: dangling cursor", self.card()["lines"][0])

    def test_a_root_with_no_upstream_reports_unknown_not_zero(self):
        git(self.root, "branch", "--unset-upstream")
        where = self.card()["where"]
        self.assertIsNone(where["ahead"])
        self.assertIsNone(where["behind"])


class Who(Fixture):
    def test_each_neuron_has_its_id_harness_model_active_and_last_seen(self):
        seat(self.root, "grok", "chair-quiet", worktree=None, model="grok-synthetic")
        who = {n["session_id"]: n for n in self.card()["who"]}
        self.assertEqual(set(who), {CHAIR_A, CHAIR_B, "chair-quiet"})
        self.assertEqual(who[CHAIR_B]["id"], neuron_id(self.cid, CHAIR_B))
        self.assertEqual((who[CHAIR_B]["harness"], who[CHAIR_B]["model"]), ("codex", "codex-synthetic"))
        self.assertIn("active", who[CHAIR_B])
        self.assertIsNotNone(who[CHAIR_B]["last_seen"], "chair-b authored a note")
        self.assertIsNotNone(who[CHAIR_A]["last_seen"], "chair-a authored its sends")
        self.assertIsNone(who["chair-quiet"]["last_seen"], "unknown, never invented")


class Commitments(Fixture):
    def test_an_open_send_is_listed_with_its_token_age_and_direction(self):
        sends = self.card()["commitments"]["open_sends"]
        self.assertEqual([s["token"] for s in sends], [OPEN], "the answered send is not open")
        self.assertEqual((sends[0]["from"], sends[0]["to"]), (CHAIR_A, CHAIR_B))
        self.assertGreaterEqual(sends[0]["age_s"], 29 * 60)

    def test_a_drained_send_is_not_open(self):
        from convoy.inbox import drain
        drain(self.root, CHAIR_B)
        self.assertEqual(self.card()["commitments"]["open_sends"], [])

    def test_the_latest_handoff_per_neuron_is_one_line_and_a_path(self):
        [handoff] = self.card()["commitments"]["handoffs"]
        self.assertEqual(handoff["chair"], CHAIR_A)
        self.assertEqual(handoff["line"], "Rolling handoff")
        self.assertTrue(handoff["path"].endswith(CHAIR_A + ".rolling.md"))

    def test_recent_commits_are_the_last_three_per_worktree(self):
        commits = {c["chair"]: c for c in self.card()["commitments"]["commits"]}
        self.assertEqual([c["subject"] for c in commits[CHAIR_A]["last"]], ["a four", "a three", "a two"])
        self.assertEqual(commits[CHAIR_A]["branch"], "main")
        self.assertEqual(Path(commits[CHAIR_A]["worktree"]).resolve(), self.wt_a.resolve())
        self.assertEqual(len(commits[CHAIR_B]["last"]), 1)


class AsksAndBoard(Fixture):
    def refuse(self, chair, minutes_ago):
        self.feed({"ts": iso(NOW - timedelta(minutes=minutes_ago)), "kind": "refuse", "instance_id": chair,
                   "summary": "codex limited", "to": "codex",
                   "ask": {"action": "bring_up", "handoff": ".convoy/handoff/" + chair + "-synthetic.md",
                           "text": "codex is limited; bring up a fresh pane"}})

    def test_an_ask_from_a_limited_send_is_open_until_its_chair_writes_again(self):
        self.refuse(CHAIR_A, 20)
        self.refuse(CHAIR_B, 20)  # chair-b noted 5 minutes ago: it came back
        asks = self.card()["commitments"]["asks"]
        self.assertEqual([a["chair"] for a in asks], [CHAIR_A])
        self.assertEqual(asks[0]["action"], "bring_up")
        self.assertIn("asks (from limited sends)", "\n".join(self.card()["lines"]))

    def test_no_pairing_means_the_board_is_not_connected(self):
        from unittest import mock
        with mock.patch("convoy.start_card.read_origin", return_value=None):
            board = self.card()["board"]
        self.assertEqual(board, {"connected": False, "line": "board not connected"})

    def test_a_paired_machine_says_card_reads_are_not_available(self):
        from unittest import mock
        with mock.patch("convoy.start_card.read_origin", return_value={"machine_id": "machine-0000"}):
            board = self.card()["board"]
        self.assertEqual(board, {"connected": True, "line": "board: paired; card reads not available in this Convoy"})


class TheSurfaces(Fixture):
    def test_mcp_start_card_is_read_only_and_returns_the_same_card(self):
        from convoy.mcp_http import TOOLS, _WRITE_TOOLS, call_tool
        self.assertIn("start_card", {t["name"] for t in TOOLS})
        self.assertNotIn("start_card", _WRITE_TOOLS)
        before = (self.root / ".convoy" / "feed.jsonl").read_bytes()
        card = call_tool(self.root, "start_card", {})
        self.assertTrue(card["ok"], card)
        [send] = card["commitments"]["open_sends"]
        self.assertNotIn("token", send, "a token is the receiver's proof: never on the ungated wire")
        self.assertNotIn(OPEN, json.dumps(card))
        self.assertEqual((send["from"], send["to"]), (CHAIR_A, CHAIR_B))
        self.assertEqual(card["where"]["thread"]["id"], self.cid)
        self.assertEqual((self.root / ".convoy" / "feed.jsonl").read_bytes(), before, "no writes")

    def test_a_token_in_free_text_never_reaches_the_ungated_wire(self):
        from convoy.mcp_http import TOOLS, call_tool
        handoff = self.root / ".convoy" / "handoff" / (CHAIR_A + ".rolling.md")
        handoff.write_text("# waiting on token=" + OPEN + " from chair-b\n", encoding="utf-8")
        card = call_tool(self.root, "start_card", {})
        self.assertNotIn(OPEN, json.dumps(card))
        self.assertIn(OPEN, json.dumps(self.card()), "the CLI card keeps it")
        [tool] = [t for t in TOOLS if t["name"] == "start_card"]
        self.assertIn("withheld", tool["description"])

    def test_mcp_start_card_behind_the_write_gate_keeps_the_token(self):
        import os
        from unittest import mock
        from convoy.mcp_http import call_tool
        with write_gate():
            card = call_tool(self.root, "start_card", {})
        self.assertEqual([s["token"] for s in card["commitments"]["open_sends"]], [OPEN])

    def test_the_cli_prints_the_lines_and_json_on_request(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        with redirect_stdout(io.StringIO()) as out:
            rc = main(["--root", str(self.root), "start-card"])
        self.assertEqual(rc, 0)
        text = out.getvalue().splitlines()
        self.assertTrue(text[0].startswith("where:"), text[:3])
        with redirect_stdout(io.StringIO()) as out:
            rc = main(["--root", str(self.root), "start-card", "--json"])
        card = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual([s["token"] for s in card["commitments"]["open_sends"]], [OPEN])
        self.assertEqual(card["lines"][0], text[0])

    def setUp(self):
        super().setUp()
        self.home = tempfile.mkdtemp(prefix="convoy-card-home-")

    def test_start_returns_the_card_with_the_trust_note(self):
        from unittest import mock
        import convoy.onboard as onboard_module
        from convoy.start import start
        with mock.patch.object(onboard_module, "probe", return_value={}), \
                mock.patch.object(onboard_module, "_which", side_effect=lambda h: "C:/synthetic/" + h), \
                mock.patch.dict("os.environ", {"USERPROFILE": self.home, "HOME": self.home}), \
                mock.patch("convoy.bringup.Path.home", return_value=Path(self.home)):
            card = start(self.root, str(self.root), harnesses=["claude"], identify_fn=lambda r: {},
                         bodies_fn=lambda r: {"chairs": []})
        self.assertTrue(card["ok"], card)
        start_card = card["start_card"]
        self.assertIn("trust: not written; Claude will ask once", start_card["notes"])
        self.assertEqual([s["token"] for s in start_card["commitments"]["open_sends"]], [OPEN])


class TheReviewedRendering(Fixture):
    def test_an_unknown_active_renders_unknown(self):
        rows = {"neurons": [{"session_id": CHAIR_A, "harness": "claude", "model": None, "active": None,
                             "last_authored": None}]}
        card = build_start_card(self.root, neurons_fn=lambda r: rows)
        line = [l for l in card["lines"] if l.startswith("  " + str(card["who"][0]["id"]))][0]
        self.assertIn("| unknown |", line)
        self.assertNotIn("quiet", line)

    def test_the_json_card_is_capped_like_its_lines(self):
        for n in range(LINE_BUDGET):
            seat(self.root, "claude", "chair-extra-" + str(n), worktree=None)
        card = self.card()
        self.assertLess(len(card["who"]), LINE_BUDGET + 2, "the lists are capped too")
        self.assertGreater(card["more"], 0)
        self.assertEqual(len(self.card(budget=None)["who"]), LINE_BUDGET + 2)

    def test_the_where_line_shortens_the_path_and_keeps_the_thread_and_lead(self):
        from unittest import mock
        # 110: the thread id (26 characters) and the lead must fit beside the fixed words.
        with mock.patch("convoy.start_card.LINE_MAX", 110):
            line = self.card()["lines"][0]
        self.assertLessEqual(len(line), 110)
        self.assertTrue(line.startswith("where: ..."), line)
        self.assertIn(self.cid, line)
        self.assertTrue(line.endswith("lead: " + CHAIR_A), line)

    def test_a_long_branch_gives_way_before_the_lead(self):
        from unittest import mock
        git(self.root, "checkout", "-q", "-b", "feature/" + "x" * 120)
        with mock.patch("convoy.start_card.LINE_MAX", 110):
            line = self.card()["lines"][0]
        self.assertLessEqual(len(line), 110)
        self.assertTrue(line.endswith("lead: " + CHAIR_A), line)
        self.assertIn(self.cid, line)

    def test_a_detached_head_says_where_it_is(self):
        sha = git(self.root, "rev-parse", "--short", "HEAD").strip()
        git(self.root, "checkout", "-q", "--detach")
        card = self.card()
        self.assertIsNone(card["where"]["branch"])
        self.assertEqual(card["where"]["detached_at"], sha)
        self.assertIn("detached at " + sha, card["lines"][0])

    def test_a_root_that_is_not_its_own_repo_reports_git_unknown(self):
        nested = self.root / "nested-root"
        nested.mkdir()
        ensure_id(nested)
        bind(nested, "nested-thread")
        where = build_start_card(nested, neurons_fn=lambda r: {"neurons": []})["where"]
        for key in ("branch", "ahead", "behind", "dirty"):
            self.assertIsNone(where[key], key + " is the parent's, not this root's")

    def test_status_takes_no_optional_locks(self):
        from unittest import mock
        import convoy.start_card as sc
        real, seen = sc.subprocess.run, []

        def recording(argv, *a, **k):
            seen.append(list(argv))
            return real(argv, *a, **k)

        with mock.patch.object(sc.subprocess, "run", recording):
            self.card()
        statuses = [argv for argv in seen if "status" in argv]
        self.assertTrue(statuses)
        for argv in statuses:
            self.assertIn("--no-optional-locks", argv)

    def test_a_claimed_citation_does_not_close_a_send_or_an_ask(self):
        self.feed({"ts": iso(NOW - timedelta(minutes=1)), "kind": "note", "instance_id": CHAIR_B, "from": CHAIR_B,
                   "summary": "re token " + OPEN + ": done", "verified_by": None, "author_claimed": True})
        self.feed({"ts": iso(NOW - timedelta(minutes=20)), "kind": "refuse", "instance_id": CHAIR_A, "to": "codex",
                   "summary": "codex limited", "ask": {"action": "bring_up", "text": "bring up a pane"}})
        self.feed({"ts": iso(NOW - timedelta(minutes=1)), "kind": "note", "instance_id": CHAIR_A, "from": CHAIR_A,
                   "summary": "back", "verified_by": None, "author_claimed": True})
        card = self.card()
        [send] = card["commitments"]["open_sends"]
        self.assertEqual(send["token"], OPEN)
        self.assertTrue(send["claimed_answer"])
        self.assertEqual([a["chair"] for a in card["commitments"]["asks"]], [CHAIR_A])

    def test_a_seat_whose_worktree_is_gone_is_listed(self):
        seat(self.root, "claude", "chair-gone", worktree=str(self.root / "no-such-worktree"))
        commits = {c["chair"]: c for c in self.card()["commitments"]["commits"]}
        self.assertTrue(commits["chair-gone"]["missing"])
        self.assertIn("worktree missing", "\n".join(self.card()["lines"]))


class NextAndRender(Fixture):
    def test_next_is_the_leads_latest_handoff(self):
        nxt = self.card()["next"]
        self.assertTrue(nxt["path"].endswith(CHAIR_A + ".rolling.md"))

    def test_with_no_handoff_next_says_read_the_thread(self):
        (self.root / ".convoy" / "handoff" / (CHAIR_A + ".rolling.md")).unlink()
        nxt = self.card()["next"]
        self.assertIsNone(nxt["path"])
        self.assertEqual(nxt["line"], "no handoff: read thread.md")

    def test_the_card_is_pointers_never_contents(self):
        card = self.card(notes=["trust: not written; Claude will ask once"])
        blob = json.dumps(card)
        self.assertNotIn("PRIVATE-BODY-TEXT", blob)
        self.assertNotIn("PRIVATE-HANDOFF-DETAIL", blob)
        self.assertIn("trust: not written; Claude will ask once", card["lines"])
        for line in card["lines"]:
            self.assertNotIn("\n", line)

    def test_past_the_budget_the_card_says_how_many_more_and_how_to_see_them(self):
        for n in range(LINE_BUDGET):
            seat(self.root, "claude", "chair-extra-" + str(n), worktree=None)
        card = self.card()
        self.assertLessEqual(len(card["lines"]), LINE_BUDGET + 1)
        self.assertGreater(card["more"], 0)
        self.assertEqual(card["lines"][-1], "+" + str(card["more"]) + " more: " + card["more_command"])
        self.assertIn("start-card", card["more_command"])
        full = self.card(budget=None)
        self.assertEqual(full["more"], 0)


if __name__ == "__main__":
    unittest.main()
