"""g2 grep-gate: argv, hook commands, public cards, and SoT writers.

No `ola`, UltraCode-Shim, or interpreter path in product argv or the
canonical hook command. Public cards carry no token, no invented usage
(null), no frozen tool menu. Writers stay inside docs/CONVOY_SOT.md —
one .convoy JSON architecture, no parallel store.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import isolated_wt_argv, resume_argv
from convoy.cmd import command_bakes_interpreter, inbox_hook_command
from convoy.convoy import bind, ensure_id, seat
from convoy.mcp_http import TOOLS, _WRITE_TOOLS, _listed_tools
from convoy.synapse import native_runner, send_one

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "convoy"
SOT = ROOT / "docs" / "CONVOY_SOT.md"
FORBIDDEN_ARGV = re.compile(r"ola-brain|ola_runner|ultracode-shim|UltraCode-Shim", re.I)
INTERPRETER_NAME = re.compile(r"^(python(\d+(\.\d+)?)?|py)(\.exe)?$", re.I)
OLA_PATH = re.compile(r"\.ola[/\\]")


def _which(name):
    n = str(name).removesuffix(".exe")
    return "C:\\Tools\\" + n + ".exe"


class ArgvAndHookGate(unittest.TestCase):
    def test_canonical_hook_command_is_console_script_not_interpreter(self):
        cmd = inbox_hook_command()
        self.assertEqual(cmd, "convoy inbox --hook-pretooluse")
        self.assertFalse(command_bakes_interpreter(cmd), cmd)
        self.assertIsNone(FORBIDDEN_ARGV.search(cmd), cmd)

    def test_resume_argv_has_no_ola_shim_or_interpreter(self):
        with mock.patch("convoy.bringup.shutil.which", side_effect=_which):
            argv = resume_argv({
                "to": "grok", "worktree": "C:\\w\\g", "session_id": "g-1",
                "resume": "vendor-1", "model": None, "effort": "high",
            })
        self.assertTrue(argv, argv)
        blob = " ".join(str(a) for a in argv)
        self.assertIsNone(FORBIDDEN_ARGV.search(blob), blob)
        self.assertFalse(INTERPRETER_NAME.match(os.path.basename(str(argv[0]))), argv)
        self.assertNotIn("-m convoy", blob)
        self.assertNotIn("ola-brain", blob.lower())

    def test_isolated_wt_argv_has_no_ola_shim_or_interpreter(self):
        with mock.patch("convoy.bringup.shutil.which", side_effect=_which):
            argv = isolated_wt_argv("demo", [{
                "to": "grok", "worktree": "C:\\w\\g", "session_id": "g-1",
                "resume": "vendor-1", "title": "g",
            }])
        blob = " ".join(str(a) for a in argv)
        self.assertIsNone(FORBIDDEN_ARGV.search(blob), blob)
        self.assertNotIn("python", os.path.basename(str(argv[0])).lower(), argv)
        for a in argv:
            if str(a).lower().endswith((".exe",)) or "/" in str(a) or "\\" in str(a):
                base = os.path.basename(str(a)).lower()
                self.assertNotIn("python", base, a)
                self.assertNotIn("ola-brain", base, a)
                self.assertNotIn("ultracode", base, a)

    def test_native_runner_argv_has_no_ola_shim_or_interpreter(self):
        ran = {}

        def fake_run(cmd, **_k):
            ran["cmd"] = list(cmd)
            class R:
                returncode = 0
                stdout = '{"session_id": null}'
                stderr = ""
            return R()

        with mock.patch("convoy.synapse.shutil.which", side_effect=_which), \
             mock.patch("convoy.synapse.subprocess.run", side_effect=fake_run):
            card = native_runner("grok", "hi", instance_id="g-1")
        argv = ran.get("cmd") or card.get("argv") or []
        self.assertTrue(argv, card)
        blob = " ".join(str(a) for a in argv)
        self.assertIsNone(FORBIDDEN_ARGV.search(blob), blob)
        self.assertFalse(INTERPRETER_NAME.match(os.path.basename(str(argv[0]))), argv)

    def test_send_one_does_not_dispatch_ola_runner(self):
        text = (SRC / "synapse.py").read_text(encoding="utf-8")
        # Gate 0: ola_runner is still reachable in-process. The brief: delete
        # it, or hard-refuse with refused:true. Dispatching on identity is RED.
        send_src = text.split("def _send_one(", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("ola_runner", send_src, "_send_one still dispatches on ola_runner")

    def test_src_argv_literals_do_not_name_wrappers(self):
        """String literals that become argv must not be ola-brain / shim.
        Refuse-lists naming them are allowed; constructing them as FileName is not."""
        hits = []
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.List):
                    continue
                vals = []
                for elt in node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        vals.append(elt.value)
                blob = " ".join(vals).lower()
                if not vals:
                    continue
                if vals[0].lower().replace(".exe", "") in ("ola-brain", "ultracode-shim", "side-chat"):
                    # a refuse-list frozenset is a Set, not a List of argv
                    hits.append(f"{path.name}:{node.lineno}:{vals[:3]}")
                if "-m" in vals and "convoy" in vals and "ola-brain" in blob:
                    hits.append(f"{path.name}:{node.lineno}:interpreter+ola")
        self.assertEqual(hits, [], hits)


class PublicCardGate(unittest.TestCase):
    def test_public_tools_list_is_derived_not_a_frozen_tuple(self):
        self.assertIsInstance(_WRITE_TOOLS, frozenset)
        self.assertGreater(len(_WRITE_TOOLS), 3)
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": ""}):
            names = {t["name"] for t in _listed_tools()}
        expected = {t["name"] for t in TOOLS if t["name"] not in _WRITE_TOOLS}
        self.assertEqual(names, expected)
        # the old leak was a frozen ("seat","join","launch") menu
        self.assertNotEqual(names, {"seat", "join", "launch"})

    def test_public_rail_usage_is_null_never_zero_and_carries_no_token(self):
        from convoy.layer import conductor_stamp
        from convoy.lifecycle import join, seated_ack
        from convoy.rail import build_rail

        root = Path(tempfile.mkdtemp())
        ensure_id(root)
        bind(root, "gate")
        joined = join(root, "grok", session_id="g-gate", title="g")
        seated_ack(root, "g-gate", token=joined["token"])
        conductor_stamp(root, "tests drafted")
        with mock.patch("convoy.rail.probe", return_value={"usage_remaining": None, "limited": False, "raw": None}):
            rail = build_rail(root)
        blob = json.dumps(rail)
        self.assertNotIn(joined["token"], blob)
        self.assertNotIn("token", blob)
        for h, u in (rail.get("usage") or {}).items():
            self.assertIsNone(u.get("usage_remaining"), h)
            self.assertNotEqual(u.get("usage_remaining"), 0, h)


class SoTWriterGate(unittest.TestCase):
    def test_sot_page_names_the_one_architecture(self):
        text = SOT.read_text(encoding="utf-8")
        for needle in (
            ".convoy/feed.jsonl", ".convoy/seats.jsonl", ".convoy/inbox/",
            ".convoy/handoff/", "threads.json", "never commit live",
        ):
            self.assertIn(needle, text, needle)

    def test_src_has_no_parallel_store(self):
        hits = []
        for path in SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "sqlite3" in text or "pickle.dump" in text or "shelve.open" in text:
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [], hits)

    def test_handoff_pointers_are_under_convoy_not_ola(self):
        hits = []
        for path in SRC.rglob("*.py"):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if OLA_PATH.search(line):
                    hits.append(f"{path.name}:{i}:{stripped}")
        self.assertEqual(hits, [], "handoff belongs under .convoy/handoff/: " + " | ".join(hits[:12]))

    def test_machine_index_is_finder_fields_only(self):
        from convoy.index import FIELDS
        self.assertEqual(FIELDS, ("convoy_id", "thread", "root", "updated_at"))
        src = (SRC / "index.py").read_text(encoding="utf-8")
        self.assertNotIn("token", src.split("def record", 1)[-1].split("def ", 1)[0])


class LimitedAskHandoffPath(unittest.TestCase):
    def test_limited_refuse_points_at_convoy_handoff(self):
        root = Path(tempfile.mkdtemp())
        card = send_one(
            root, "claude", "hi",
            runner=lambda *a, **k: {"ok": True, "to": "claude", "session_id": None, "model": None, "usage_remaining": None, "body": "x"},
            probe_fn=lambda _t: {"usage_remaining": {"session_pct": 100}, "limited": True, "raw": "100%"},
        )
        self.assertFalse(card.get("ok"), card)
        ask = card.get("ask") or {}
        self.assertTrue(str(ask.get("handoff") or "").replace("\\", "/").startswith(".convoy/handoff"), ask)


if __name__ == "__main__":
    unittest.main()
