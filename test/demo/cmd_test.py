"""convoy_command: the one spelling of Convoy's own command line (stranger
finding 2026-09-03: `python -m convoy` hardcoded in boot prompts and asks
fails for pipx/console-script installs and hosts without a `python` alias)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import cmd


class ConvoyCommand(unittest.TestCase):
    def test_console_script_wins_when_on_path(self):
        with mock.patch.object(cmd.shutil, "which", return_value="/usr/bin/convoy"):
            self.assertEqual(cmd.convoy_command(), "convoy")
            self.assertEqual(cmd.convoy_root_command("/r"), "convoy --root /r")

    def test_falls_back_to_this_interpreter(self):
        with mock.patch.object(cmd.shutil, "which", return_value=None), \
             mock.patch.object(cmd.sys, "executable", "C:\\Program Files\\Py\\python.exe"):
            self.assertEqual(cmd.convoy_command(), '"C:\\Program Files\\Py\\python.exe" -m convoy')
            self.assertTrue(cmd.convoy_root_command("C:\\a b").endswith(' --root "C:\\a b"'))

    def test_no_hardcoded_python_m_convoy_in_neuron_facing_strings(self):
        src = Path(__file__).resolve().parents[2] / "src" / "convoy"
        for name in ("lifecycle.py", "graph_html.py", "panes.py", "identity.py"):
            text = (src / name).read_text(encoding="utf-8")
            self.assertNotIn('"python -m convoy --root', text, name)
            self.assertNotIn("`python -m convoy send", text, name)


if __name__ == "__main__":
    unittest.main()
