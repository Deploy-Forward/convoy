"""Convoy graph: the read-only projection over seats + feed (Marco, 2026-09-02).

A thread is a context; the graph is the ontology of attributions over it:
which chairs exist, who occupies each (harness + model, attested from the
bus), which chair talked to which, and where a resume can legally start.
Read side only: it never mints, never launches, never carries a token.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat, update_seat
from convoy.graph import build_graph, neighborhood
from convoy.layer import feed_since, hook
from convoy.lifecycle import join, seated_ack, swap


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


def _ids(items, kind):
    return sorted(n["id"] for n in items if n["kind"] == kind)


class EmptyRoot(unittest.TestCase):
    def test_unbound_root_is_an_honest_empty_graph(self):
        root = Path(tempfile.mkdtemp())
        g = build_graph(root)
        self.assertEqual(g["graph_version"], 1)
        self.assertIsNone(g["convoy_id"])
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])


class ChairsAndTalk(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1", model="claude-opus-5", worktree="wa")
        seat(self.root, "codex", "b-t1", worktree="wb")

    def test_thread_seats_chairs_and_chairs_run_on_harness_and_model(self):
        g = build_graph(self.root)
        cid = g["convoy_id"]
        self.assertEqual(_ids(g["nodes"], "thread"), ["thread:" + cid])
        self.assertEqual(_ids(g["nodes"], "chair"), ["chair:a-t1", "chair:b-t1"])
        self.assertIn("harness:claude", _ids(g["nodes"], "harness"))
        self.assertIn("model:claude-opus-5", _ids(g["nodes"], "model"))
        kinds = {(e["kind"], e["from"], e["to"]) for e in g["edges"]}
        self.assertIn(("seats", "thread:" + cid, "chair:a-t1"), kinds)
        self.assertIn(("runs_on", "chair:a-t1", "harness:claude"), kinds)
        self.assertIn(("runs", "chair:a-t1", "model:claude-opus-5"), kinds)
        # model unknown => no runs edge, never a placeholder node
        self.assertNotIn(("runs", "chair:b-t1", "model:None"), kinds)
        self.assertNotIn("model:None", _ids(g["nodes"], "model"))

    def test_note_rows_become_attributed_talk_edges(self):
        hook(self.root, "note", "hi b", instance_id="a-t1", to="b-t1")
        hook(self.root, "note", "hi conductor", instance_id="b-t1", to="grok-bot")
        g = build_graph(self.root)
        talk = [(e["from"], e["to"]) for e in g["edges"] if e["kind"] == "note"]
        self.assertIn(("chair:a-t1", "chair:b-t1"), talk)
        self.assertIn(("chair:b-t1", "conductor:grok-bot"), talk)
        self.assertIn("conductor:grok-bot", _ids(g["nodes"], "conductor"))
        for e in g["edges"]:
            if e["kind"] == "note":
                self.assertEqual(e["attestation"], "attested")
                self.assertTrue(e["ts"])

    def test_synapse_rows_have_no_caller_and_say_so(self):
        hook(self.root, "synapse", "send", instance_id="b-t1", author=None, extra={"to": "codex"})
        g = build_graph(self.root)
        syn = [e for e in g["edges"] if e["kind"] == "synapse"]
        self.assertEqual(len(syn), 1)
        self.assertIsNone(syn[0]["from"])
        self.assertEqual(syn[0]["to"], "chair:b-t1")


class Lineage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")

    def test_join_swap_seated_project_into_chair_lineage(self):
        j = join(self.root, "claude", session_id="x-t1", model="claude-opus-5")
        seated_ack(self.root, "x-t1", j["token"])
        hp = self.root / ".ola" / "handoff-x.md"
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text("handoff", encoding="utf-8")
        swap(self.root, "x-t1", "codex", str(hp), author="x-t1", model="gpt-5.6")
        g = build_graph(self.root)
        chair = next(n for n in g["nodes"] if n["id"] == "chair:x-t1")
        self.assertEqual(chair["current"]["harness"], "codex")
        self.assertEqual(chair["current"]["model"], "gpt-5.6")
        kinds = [e["kind"] for e in chair["lineage"]]
        self.assertEqual(kinds, ["join", "seated", "swap"])
        self.assertEqual(chair["lineage"][-1]["state"], "pending")   # no seated after the swap
        self.assertEqual(chair["lineage"][1]["state"], "acked")
        self.assertTrue(all(e["attestation"] == "attested" for e in chair["lineage"]))
        # runs_on edges carry history: claude then codex
        harness_edges = [(e["to"], e.get("current")) for e in g["edges"] if e["kind"] == "runs_on" and e["from"] == "chair:x-t1"]
        self.assertIn(("harness:claude", False), harness_edges)
        self.assertIn(("harness:codex", True), harness_edges)

    def test_graph_never_carries_tokens(self):
        j = join(self.root, "claude", session_id="x-t1")
        seated_ack(self.root, "x-t1", j["token"])
        update_seat(self.root, "x-t1", resume="vendor-uuid-secret", resume_for="claude")
        blob = json.dumps(build_graph(self.root))
        self.assertNotIn(j["token"], blob)
        self.assertNotIn("vendor-uuid-secret", blob)
        chair = next(n for n in build_graph(self.root)["nodes"] if n["id"] == "chair:x-t1")
        self.assertTrue(chair["resume"]["available"])
        self.assertEqual(chair["resume"]["for"], "claude")

    def test_resume_unavailable_after_swap_and_when_harness_mismatches(self):
        j = join(self.root, "claude", session_id="x-t1")
        seated_ack(self.root, "x-t1", j["token"])
        update_seat(self.root, "x-t1", resume="uuid", resume_for="claude")
        hp = self.root / "h.md"
        hp.write_text("h", encoding="utf-8")
        swap(self.root, "x-t1", "codex", str(hp), author="x-t1")
        chair = next(n for n in build_graph(self.root)["nodes"] if n["id"] == "chair:x-t1")
        self.assertFalse(chair["resume"]["available"])
        self.assertIsNone(chair["resume"]["for"])


class Neighborhood(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1")
        seat(self.root, "codex", "b-t1")
        seat(self.root, "grok", "c-t1")
        hook(self.root, "note", "a->b", instance_id="a-t1", to="b-t1")
        hook(self.root, "note", "c->grok", instance_id="c-t1", to="grok-bot")

    def test_neighborhood_lists_connected_chairs_and_thread_pointer(self):
        n = neighborhood(self.root, "a-t1")
        self.assertEqual(n["chair"]["id"], "chair:a-t1")
        self.assertEqual(sorted(x["id"] for x in n["neighbors"]), ["chair:b-t1"])
        self.assertTrue(n["thread"]["path"].endswith("thread.md"))
        self.assertEqual(n["thread"]["convoy_id"], n["convoy_id"])
        self.assertTrue(n["thread"]["last_row_ts"])

    def test_unknown_neuron_refuses(self):
        with self.assertRaises(ValueError):
            neighborhood(self.root, "nobody")

    def test_cli_graph_and_neuron(self):
        rc, g = _run_cli(self.root, "graph")
        self.assertEqual(rc, 0)
        self.assertEqual(g["graph_version"], 1)
        self.assertEqual(len(_ids(g["nodes"], "chair")), 3)
        rc, n = _run_cli(self.root, "graph", "--neuron", "c-t1")
        self.assertEqual(rc, 0)
        self.assertEqual(n["chair"]["id"], "chair:c-t1")
        self.assertEqual([x["id"] for x in n["neighbors"]], ["conductor:grok-bot"])


class PlaceAndLead(unittest.TestCase):
    """Marco 2026-09-02: each neuron gets a post-hook to understand its place —
    temporal (rank by latest contribution), latest contribution, position
    (degree) — so lead status can be passed to an identified neuron."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1")
        seat(self.root, "codex", "b-t1")
        seat(self.root, "grok", "c-t1")
        hook(self.root, "note", "a->b", instance_id="a-t1", to="b-t1")
        hook(self.root, "note", "b->a", instance_id="b-t1", to="a-t1")

    def test_place_reports_last_contribution_rank_and_degree(self):
        a = neighborhood(self.root, "a-t1")["place"]
        self.assertEqual(a["last_contribution"]["kind"], "note")
        self.assertEqual(a["last_contribution"]["summary"], "a->b")
        self.assertEqual(a["contributions"], 1)
        self.assertEqual(a["degree"], 1)
        self.assertEqual(a["rank"], 2)          # b contributed later
        self.assertEqual(neighborhood(self.root, "b-t1")["place"]["rank"], 1)
        c = neighborhood(self.root, "c-t1")["place"]
        self.assertIsNone(c["last_contribution"])
        self.assertIsNone(c["rank"])
        self.assertFalse(a["lead"])
        self.assertIsNone(a["lead_chair"])

    def test_pass_lead_to_identified_neuron(self):
        from convoy.convoy import read_lead
        from convoy.lifecycle import pass_lead
        out = pass_lead(self.root, "b-t1", author="a-t1")
        self.assertEqual(out["lead_chair"], "b-t1")
        self.assertEqual(out["lead"], "codex")
        self.assertEqual(read_lead(self.root), "codex")
        rows = [r for r in feed_since(self.root, "1970-01-01T00:00:00Z") if r["kind"] == "lead"]
        self.assertEqual((rows[-1]["from"], rows[-1]["to"]), ("a-t1", "b-t1"))
        self.assertTrue(neighborhood(self.root, "b-t1")["place"]["lead"])
        self.assertEqual(neighborhood(self.root, "a-t1")["place"]["lead_chair"], "b-t1")
        g = build_graph(self.root)
        leads = {n["id"]: n["lead"] for n in g["nodes"] if n["kind"] == "chair"}
        self.assertEqual(leads, {"chair:a-t1": False, "chair:b-t1": True, "chair:c-t1": False})
        self.assertIn(("lead", "chair:a-t1", "chair:b-t1"), {(e["kind"], e["from"], e["to"]) for e in g["edges"]})

    def test_pass_lead_refuses_unknown_chair_and_conductor_author(self):
        from convoy.lifecycle import pass_lead
        with self.assertRaises(ValueError):
            pass_lead(self.root, "nobody", author="a-t1")
        with self.assertRaises(ValueError):
            pass_lead(self.root, "b-t1", author="grok-bot")
        with self.assertRaises(ValueError):
            pass_lead(self.root, "b-t1", author="")

    def test_cli_lead_to_chair_requires_author_and_stamps(self):
        rc, out = _run_cli(self.root, "lead", "--to", "b-t1")
        self.assertEqual(rc, 1)
        rc, out = _run_cli(self.root, "lead", "--to", "b-t1", "--as", "a-t1")
        self.assertEqual(rc, 0)
        self.assertEqual(out["lead_chair"], "b-t1")
        rc, out = _run_cli(self.root, "lead")
        self.assertEqual(out["lead"], "codex")
        self.assertEqual(out["lead_chair"], "b-t1")


if __name__ == "__main__":
    unittest.main()
