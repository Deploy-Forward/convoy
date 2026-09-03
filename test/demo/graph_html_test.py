"""graph --html: the local visual of the graph with a thread side panel and,
per chair, the exact Convoy command that resumes that neuron. resume --neuron:
the pipe-able verb behind that command (Marco 2026-09-02)."""
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
from convoy.graph import build_graph
from convoy.graph_html import render_html, resume_neuron
from convoy.layer import hook


def _run_cli(root, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class RenderHtml(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "claude", "a-t1", model="claude-opus-5", worktree="wa", resume="secret-uuid")
        seat(self.root, "codex", "b-t1", worktree="wb")
        hook(self.root, "note", "a->b", instance_id="a-t1", to="b-t1")

    def test_page_lists_threads_chairs_commands_and_no_tokens(self):
        html = render_html([{"root": str(self.root), "graph": build_graph(self.root)}])
        self.assertIn("<title>", html)
        self.assertIn("t1", html)
        self.assertIn("chair:a-t1", html)
        self.assertIn("resume --neuron a-t1", html)
        self.assertIn("claude-opus-5", html)
        self.assertNotIn("secret-uuid", html)
        self.assertNotIn("http://", html)     # self-contained: no external loads
        self.assertNotIn("https://", html)

    def test_cli_graph_html_writes_file(self):
        out = self.root / "graph.html"
        rc, card = _run_cli(self.root, "graph", "--html", "--out", str(out))
        self.assertEqual(rc, 0)
        self.assertTrue(out.is_file())
        # the page also lists every present thread in the machine index
        self.assertGreaterEqual(card["threads"], 1)
        page = out.read_text(encoding="utf-8")
        self.assertIn("chair:a-t1", page)
        self.assertNotIn("secret-uuid", page)


class ResumeNeuron(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "a-t1", worktree=str(self.root), resume="codex-uuid")
        seat(self.root, "claude", "b-t1", worktree=str(self.root))

    def test_dry_returns_native_argv_cwd_and_place(self):
        card = resume_neuron(self.root, "a-t1")
        self.assertEqual(card["argv"][1:], ["resume", "codex-uuid"])
        self.assertEqual(card["cwd"], str(self.root))
        self.assertIn("place", card)
        self.assertFalse(card["spawned"])

    def test_refuses_without_a_token_for_its_harness_and_points_at_launch(self):
        card = resume_neuron(self.root, "b-t1")
        self.assertFalse(card["ok"])
        self.assertIn("launch --seat b-t1", card["ask"])
        update_seat(self.root, "a-t1", to="claude")   # swap nulls the token
        self.assertFalse(resume_neuron(self.root, "a-t1")["ok"])

    def test_go_spawns_once_in_the_worktree_and_refuses_when_live(self):
        calls = []
        # Liveness is explicit: the default probe reads the real machine, and
        # since unknown now reads as live to a guard (no-steal fails safe),
        # any codex/claude process on the host would refuse this spawn.
        card = resume_neuron(self.root, "a-t1", go=True, liveness=lambda root, sid: False,
                             spawn=lambda argv, cwd: calls.append((argv, cwd)) or 4242)
        self.assertTrue(card["spawned"])
        self.assertEqual(card["pid"], 4242)
        self.assertEqual(calls[0][1], str(self.root))
        live = resume_neuron(self.root, "a-t1", go=True, spawn=lambda a, c: 1, liveness=lambda root, sid: True)
        self.assertFalse(live["ok"])
        self.assertIn("live", live["error"])

    def test_unknown_neuron_refuses(self):
        with self.assertRaises(ValueError):
            resume_neuron(self.root, "nobody")

    def test_cli_resume_dry_and_missing_token_exit_codes(self):
        rc, card = _run_cli(self.root, "resume", "--neuron", "a-t1")
        self.assertEqual(rc, 0)
        self.assertEqual(card["argv"][1:], ["resume", "codex-uuid"])
        rc, card = _run_cli(self.root, "resume", "--neuron", "b-t1")
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
