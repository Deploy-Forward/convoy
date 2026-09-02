import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from convoy.cli import main
from convoy.install import ALLOWED_HOSTS, HARNESSES, install, vendor_card
from convoy.mcp_http import TOOLS, call_tool, handle_rpc

def _run(root, *argv):
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["--root", str(root), *argv])
    raw = buf.getvalue()
    data = json.loads(raw) if raw.strip() else None
    return rc, data


class PhaseInstall(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.fake_home = Path(tempfile.mkdtemp())
        self._home_patcher = mock.patch("convoy.bringup.Path.home", return_value=self.fake_home)
        self._home_patcher.start()
        self.addCleanup(self._home_patcher.stop)

    def test_vendor_catalog_hosts_are_https_and_allowed(self):
        for to, spec in HARNESSES.items():
            self.assertIn(spec["host"], ALLOWED_HOSTS, to)
            parsed = urlparse(spec["posix_url"])
            self.assertEqual(parsed.scheme, "https", to)
            self.assertEqual(parsed.hostname, spec["host"], to)
            card = vendor_card(to, windows=False)
            self.assertTrue(card["ok"], card)
            self.assertEqual(card["host"], spec["host"])
            self.assertEqual(urlparse(card["url"]).hostname, spec["host"])
            self.assertIsNone(card["affiliate"])
            self.assertFalse(card["ran"])

    def test_agy_host(self):
        card = vendor_card("agy", windows=False)
        self.assertTrue(card["ok"])
        self.assertEqual(card["host"], "antigravity.google")
        alias = vendor_card("antigravity", windows=False)
        self.assertTrue(alias["ok"])
        self.assertEqual(alias["to"], "agy")
        self.assertEqual(alias["host"], "antigravity.google")

    def test_refuse_wrapped_and_unknown(self):
        banned = ["gemini" + "-cli", "grok" + "-cli", "ultracode-shim", "ola-brain", "nope"]
        for to in banned:
            card = install(to, dry_run=True)
            self.assertFalse(card["ok"], to)
            self.assertFalse(card["ran"], to)
            self.assertIn("refuse", str(card.get("error") or "").lower(), to)

    def test_dry_run_does_not_call_installer(self):
        def boom(url):
            raise AssertionError("dry_run must not fetch")
        for to in HARNESSES:
            card = install(to, dry_run=True, opt_in=True, installer=boom)
            self.assertTrue(card["ok"], card)
            self.assertTrue(card["dry_run"])
            self.assertFalse(card["ran"])

    def test_live_without_opt_in_does_not_call_installer(self):
        def boom(url):
            raise AssertionError("opt_in required to fetch")
        card = install("grok", dry_run=False, opt_in=False, installer=boom)
        self.assertFalse(card["ok"])
        self.assertEqual(card.get("error"), "opt_in required")
        self.assertFalse(card["ran"])

    def test_live_opt_in_calls_installer_then_path(self):
        seen = []
        def fake(url):
            seen.append(url)
            return {"ok": True, "url": url}
        # posix URL pick + bashrc ungate are os.name-gated; pin that branch on every OS.
        with mock.patch("convoy.install.os.name", "posix"):
            card = install("claude", dry_run=False, opt_in=True, installer=fake)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["ran"])
        self.assertEqual(seen, [HARNESSES["claude"]["posix_url"]])
        bashrc = self.fake_home / ".bashrc"
        self.assertTrue(bashrc.is_file())
        self.assertIn("convoy harness PATH", bashrc.read_text(encoding="utf-8"))
        self.assertTrue(card.get("path", {}).get("path_ok"))

    def test_installer_is_passed_only_catalog_url(self):
        seen = []
        def fake(url):
            seen.append(url)
            parsed = urlparse(url)
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, ALLOWED_HOSTS)
            return {"ok": True, "url": url}
        for to in HARNESSES:
            install(to, dry_run=False, opt_in=True, installer=fake, windows=False)
        hosts = {urlparse(u).hostname for u in seen}
        self.assertEqual(hosts, ALLOWED_HOSTS)

    def test_mcp_install_listed_and_dry_by_default(self):
        names = [t["name"] for t in TOOLS]
        self.assertIn("install", names)
        desc = next(t for t in TOOLS if t["name"] == "install")["description"].lower()
        self.assertIn("opt", desc)
        self.assertIn("vendor", desc)
        listed = handle_rpc(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        listed_names = [t["name"] for t in listed["result"]["tools"]]
        self.assertIn("install", listed_names)
        payload = call_tool(self.root, "install", {"to": "agy"})
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["ran"])
        self.assertEqual(payload["host"], "antigravity.google")

    def test_mcp_install_live_without_opt_in_refuses(self):
        payload = call_tool(self.root, "install", {"to": "grok", "dry_run": False})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("error"), "opt_in required")

    def test_cli_install_dry_default(self):
        rc, d = _run(self.root, "install", "--to", "codex")
        self.assertEqual(rc, 0)
        self.assertTrue(d["ok"])
        self.assertTrue(d["dry_run"])
        self.assertFalse(d["ran"])
        self.assertEqual(d["host"], "chatgpt.com")

    def test_cli_install_refuses_unknown(self):
        rc, d = _run(self.root, "install", "--to", "nope")
        self.assertEqual(rc, 1)
        self.assertFalse(d["ok"])
        self.assertFalse(d["ran"])


if __name__ == "__main__":
    unittest.main()
