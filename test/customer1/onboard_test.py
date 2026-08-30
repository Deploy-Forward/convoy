import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, read_id, read_thread
from convoy.mcp_http import TOOLS, call_tool
from convoy.onboard import onboard


ROOT = Path(__file__).resolve().parents[2]
FAKES = (ROOT / "test" / "fakes").resolve()


def _run_cli(root: Path, *argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--root", str(root), *argv])
    return rc, json.loads(buf.getvalue())


class OnboardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.checkout = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home.start()
        self.addCleanup(self._home.stop)

    def test_requires_named_harnesses(self):
        card = onboard(self.root, [])
        self.assertFalse(card["ok"])
        self.assertIn("name at least one harness", card["error"])

    def test_refuses_wrapper_ids(self):
        card = onboard(self.root, ["grok", "gemini-cli"])
        self.assertFalse(card["ok"])
        self.assertIn("gemini-cli", card["refused"])
        self.assertIn("refuse", card["error"])

    def test_named_only_not_silent_plus_missing_install_hint(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            card = onboard(self.root, ["grok", "claude"])
        self.assertTrue(card["ok"])
        self.assertEqual(card["named"], ["grok", "claude"])
        self.assertEqual([h["to"] for h in card["harnesses"]], ["grok", "claude"])
        self.assertEqual(card["missing"], ["grok", "claude"])
        for h in card["harnesses"]:
            self.assertFalse(h["present"])
            self.assertFalse(h["wired"])
            self.assertIsNone(h["usage_remaining"])
            self.assertEqual(h["install"]["tool"], "install")
            self.assertTrue(h["install"]["dry_run_default"])
            self.assertTrue(h["install"]["opt_in_required"])

    def test_checkout_root_bind_and_first_run_card(self):
        with mock.patch.dict(os.environ, {"PATH": str(FAKES)}):
            card = onboard(
                self.root,
                ["grok", "claude"],
                thread="customer1",
                checkout_root=str(self.checkout),
            )
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["root"], str(self.checkout.resolve()))
        self.assertEqual(card["thread"], "customer1")
        self.assertEqual(read_thread(self.checkout), "customer1")
        self.assertEqual(read_id(self.checkout), card["convoy_id"])
        self.assertTrue(card["thread_bind"]["changed"])
        self.assertEqual([h["to"] for h in card["harnesses"]], ["grok", "claude"])
        by = {h["to"]: h for h in card["harnesses"]}
        self.assertTrue(by["grok"]["present"])
        self.assertTrue(by["claude"]["present"])
        self.assertIn("first_run", by["grok"])
        self.assertIn("first_run", by["claude"])
        self.assertIsNone(by["grok"]["usage_remaining"])
        self.assertNotEqual(by["grok"]["usage_remaining"], 0)
        bashrc = self.fake_home / ".bashrc"
        self.assertTrue(bashrc.is_file())
        self.assertIn("convoy harness PATH", bashrc.read_text(encoding="utf-8"))

    def test_refuse_stomp_different_thread(self):
        bind(self.checkout, "existing-thread")
        card = onboard(
            self.root,
            ["grok"],
            thread="other-thread",
            checkout_root=str(self.checkout),
        )
        self.assertFalse(card["ok"])
        self.assertEqual(read_thread(self.checkout), "existing-thread")
        self.assertIn("already bound", card["error"])

    def test_cli_onboard_and_mcp_tool(self):
        with mock.patch.dict(os.environ, {"PATH": str(FAKES)}):
            rc, cli = _run_cli(self.root, "onboard", "--to", "grok", "--to", "claude")
            mcp = call_tool(self.root, "onboard", {"to": ["grok"]})
        self.assertEqual(rc, 0)
        self.assertTrue(cli["ok"])
        self.assertEqual(cli["named"], ["grok", "claude"])
        self.assertTrue(mcp["ok"])
        self.assertEqual([h["to"] for h in mcp["harnesses"]], ["grok"])
        names = [t["name"] for t in TOOLS]
        self.assertIn("onboard", names)


if __name__ == "__main__":
    unittest.main()
