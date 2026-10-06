"""The AGENTS.md block is a one-paragraph pointer, and Convoy replaces only its own.

The block between the identity markers points at the plugins and at convoy-dictionary. An
existing block is replaced only when its text is one an earlier Convoy wrote (its sha256 is in
identity.KNOWN_AGENTS_BLOCKS; fixtures/agents_blocks.json holds every such text). A block anyone
edited is left exactly as it is, with a warning naming the file. Every byte outside the markers is
kept, line endings included.
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import identity
from convoy.cli import main
from convoy.identity import SKILL_BEGIN, SKILL_END, install_neuron_identity

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "agents_blocks.json"
OLD_BLOCKS = json.loads(FIXTURE.read_text(encoding="utf-8"))["blocks"]


def _core(text: str) -> str:
    start = text.index(SKILL_BEGIN)
    end = text.index(SKILL_END) + len(SKILL_END)
    return text[start:end]


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


class ThePointer(unittest.TestCase):
    def test_it_is_one_paragraph_naming_the_plugins_and_the_dictionary(self):
        core = _core(identity._AGENTS_BLOCK)
        lines = core.split("\n")
        self.assertEqual(len(lines), 3, core)
        body = lines[1]
        for phrase in ("`convoy --root <root> whoami`", "convoy-operate", "convoy-dictionary",
                       "Deploy-Forward/plugins"):
            self.assertIn(phrase, body)
        for stale in ("install.mjs", "python -m convoy", "neuron-identity", "neuron-receive", "inbox --wait",
                      "convoy hook note"):
            self.assertNotIn(stale, body)

    def test_every_old_block_is_known_and_the_fixture_is_whole(self):
        for b in OLD_BLOCKS:
            self.assertEqual(_sha(b["text"]), b["sha256"])
            self.assertIn(b["sha256"], identity.KNOWN_AGENTS_BLOCKS)
        self.assertEqual(set(identity.KNOWN_AGENTS_BLOCKS), {b["sha256"] for b in OLD_BLOCKS},
                         "every known hash has its text in the fixture")
        self.assertNotIn(_sha(_core(identity._AGENTS_BLOCK)), identity.KNOWN_AGENTS_BLOCKS)


class Replacement(unittest.TestCase):
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        self.agents = self.wt / "AGENTS.md"

    def test_every_old_block_is_replaced_and_the_rest_is_byte_identical(self):
        for nl in ("\n", "\r\n"):
            for b in OLD_BLOCKS:
                with self.subTest(block=b["sha256"][:12], newline=repr(nl)):
                    head = ("# Project rules" + nl + nl + "keep me  " + nl + nl).encode("utf-8")
                    tail = (nl + nl + "## After" + nl + "tail text, no final newline").encode("utf-8")
                    old = b["text"].replace("\n", nl).encode("utf-8")
                    self.agents.write_bytes(head + old + tail)
                    card = install_neuron_identity(self.wt)
                    self.assertTrue(card["ok"], card)
                    self.assertTrue(card["written"])
                    self.assertFalse(card.get("warnings"), card)
                    new = _core(identity._AGENTS_BLOCK).replace("\n", nl).encode("utf-8")
                    self.assertEqual(self.agents.read_bytes(), head + new + tail)

    def test_a_block_only_file_becomes_the_pointer(self):
        self.agents.write_text(OLD_BLOCKS[-1]["text"] + "\n", encoding="utf-8", newline="")
        install_neuron_identity(self.wt)
        self.assertEqual(self.agents.read_bytes(), identity._AGENTS_BLOCK.encode("utf-8"))

    def test_the_current_pointer_is_left_alone(self):
        install_neuron_identity(self.wt)
        before = self.agents.read_bytes()
        again = install_neuron_identity(self.wt)
        self.assertFalse(again["written"])
        self.assertEqual(self.agents.read_bytes(), before)

    def test_an_edited_block_is_left_exactly_as_it_is_with_a_warning(self):
        edited = OLD_BLOCKS[-1]["text"].replace("Run `convoy", "Our team rule: run `convoy")
        data = ("# mine\r\n\r\n" + edited.replace("\n", "\r\n") + "\r\n").encode("utf-8")
        self.agents.write_bytes(data)
        card = install_neuron_identity(self.wt)
        self.assertTrue(card["ok"], card)
        self.assertFalse(card["written"])
        self.assertEqual(self.agents.read_bytes(), data)
        self.assertTrue(card.get("warnings"))
        self.assertIn(str(self.agents), card["warnings"][0])

    def test_a_lone_marker_is_left_alone_with_a_warning(self):
        data = ("# mine\n" + SKILL_BEGIN + "\nhalf a block\n").encode("utf-8")
        self.agents.write_bytes(data)
        card = install_neuron_identity(self.wt)
        self.assertEqual(self.agents.read_bytes(), data)
        self.assertTrue(card.get("warnings"))

    def test_a_file_without_a_block_keeps_its_bytes_and_gains_the_pointer(self):
        data = "# keep me\r\n\r\nuser rules stay\r\n".encode("utf-8")
        self.agents.write_bytes(data)
        card = install_neuron_identity(self.wt)
        self.assertTrue(card["written"])
        out = self.agents.read_bytes()
        self.assertTrue(out.startswith(b"# keep me\r\n\r\nuser rules stay"))
        self.assertEqual(out.count(SKILL_BEGIN.encode()), 1)

    def test_convoy_skills_prints_the_warning_naming_the_file(self):
        edited = OLD_BLOCKS[-1]["text"].replace("first.", "first, always.")
        self.agents.write_text(edited + "\n", encoding="utf-8", newline="")
        before = self.agents.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            main(["--root", str(self.wt), "skills", "--worktree", str(self.wt), "--write-repo-files"])
        card = json.loads(out.getvalue())
        self.assertEqual(self.agents.read_bytes(), before)
        self.assertIn(str(self.agents), err.getvalue())
        self.assertTrue(any(str(self.agents) in w for w in card.get("warnings") or []), card)


if __name__ == "__main__":
    unittest.main()
