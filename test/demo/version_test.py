"""`convoy --version` says which Convoy runs, and every surface reports the same version.

`convoy --version` prints one JSON object: the version, the executable that ran, the source file
of the package it imported, and whether that package is an editable install. The MCP server's
version comes from the same place, so a release bump is one line in pyproject.toml. The widget's
logo ships inside the package, so an installed Convoy serves it without a checkout.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import convoy
from convoy.cli import main

PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


class VersionFlag(unittest.TestCase):
    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertIn(cm.exception.code, (0, None))
        return json.loads(buf.getvalue())

    def test_it_prints_version_executable_source_and_editable(self):
        card = self._run()
        self.assertEqual(set(card), {"version", "executable", "source", "editable"})
        self.assertEqual(card["version"], PYPROJECT["project"]["version"])
        self.assertEqual(Path(card["source"]).resolve(), Path(convoy.__file__).resolve())
        self.assertIsInstance(card["editable"], bool)
        self.assertTrue(isinstance(card["executable"], str) and card["executable"])

    def test_python_dash_m_convoy_answers_from_any_cwd(self):
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        r = subprocess.run([sys.executable, "-m", "convoy", "--version"], cwd=tempfile.mkdtemp(),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        card = json.loads(r.stdout)
        self.assertEqual(card["version"], PYPROJECT["project"]["version"])
        self.assertEqual(Path(card["source"]).resolve(), (REPO / "src" / "convoy" / "__init__.py").resolve())


class Editable(unittest.TestCase):
    """editable is true only for an editable install of the very source that is running."""

    def _dist(self, payload):
        class Dist:
            def read_text(self, name):
                return json.dumps(payload) if name == "direct_url.json" else None
        return Dist()

    def test_an_editable_install_of_this_source_is_editable(self):
        from convoy import version
        url = REPO.resolve().as_uri()   # pip records the project directory
        with mock.patch.object(version.metadata, "distribution",
                               return_value=self._dist({"dir_info": {"editable": True}, "url": url})):
            self.assertTrue(version._editable())

    def test_an_editable_install_of_another_checkout_is_not(self):
        from convoy import version
        other = Path(tempfile.mkdtemp()).resolve().as_uri()
        with mock.patch.object(version.metadata, "distribution",
                               return_value=self._dist({"dir_info": {"editable": True}, "url": other})):
            self.assertFalse(version._editable())

    def test_a_regular_install_is_not(self):
        from convoy import version
        with mock.patch.object(version.metadata, "distribution",
                               return_value=self._dist({"archive_info": {}, "url": "file:///x.whl"})):
            self.assertFalse(version._editable())


class OneVersion(unittest.TestCase):
    def test_the_release_is_1_3_1(self):
        self.assertEqual(PYPROJECT["project"]["version"], "1.3.1")

    def test_the_spec_and_the_deploy_doc_name_the_package_version(self):
        v = PYPROJECT["project"]["version"]
        spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("(base " + v + ")", spec)
        self.assertIn("| `convoy` " + v + ",", spec)
        deploy = (REPO / "docs" / "deploy-convoy-bot-mcp.md").read_text(encoding="utf-8")
        self.assertIn("serverInfo.version = " + v + "+<merged sha>", deploy)
        self.assertIn("report `" + v + "+<git", deploy)
        self.assertIn("a bare `" + v + "` from an installed package", deploy)

    def test_the_mcp_base_version_is_the_package_version(self):
        from convoy import mcp_http, version
        self.assertEqual(version.package_version(), PYPROJECT["project"]["version"])
        self.assertEqual(mcp_http._BASE_VERSION, version.package_version())

    def test_no_git_suffix_when_the_package_is_not_in_a_checkout(self):
        from convoy import mcp_http, version
        with mock.patch.object(version, "in_checkout", return_value=False), \
             mock.patch.object(mcp_http.subprocess, "run", side_effect=AssertionError("git must not run")):
            self.assertEqual(mcp_http._server_version(), mcp_http._BASE_VERSION)


class PackageData(unittest.TestCase):
    def test_the_logo_ships_in_the_package(self):
        from convoy import widget_web
        logo, ctype = widget_web.ASSETS["/assets/logo.svg"]
        pkg = Path(convoy.__file__).resolve().parent
        self.assertEqual(Path(logo).resolve(), (pkg / "assets" / "logo.svg").resolve())
        self.assertTrue(Path(logo).is_file())
        self.assertIn(b"<svg", Path(logo).read_bytes())
        self.assertEqual(ctype, "image/svg+xml")

    def test_package_data_lists_the_assets_and_no_skill_text(self):
        data = PYPROJECT["tool"]["setuptools"]["package-data"]["convoy"]
        self.assertIn("assets/**", data)
        self.assertIn("conductor.md", data)
        self.assertFalse([d for d in data if "harness_skills" in d], data)


if __name__ == "__main__":
    unittest.main()
