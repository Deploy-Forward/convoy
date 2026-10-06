import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class WtNudgeScript(unittest.TestCase):
    """The deaf-pane recovery script carries its own refusals. The convoy-nudge skill that runs it
    ships from Deploy-Forward/plugins."""

    def test_the_script_carries_the_refusals(self):
        script = (REPO / "scripts" / "wt-nudge.ps1").read_text(encoding="utf-8")
        for guard in ("-List", "-DryRun", "IdleTitle", "Waiting for response", "CASCADIA_HOSTING_WINDOW_CLASS", "AttachThreadInput"):
            self.assertIn(guard, script, guard)
        # refuses: busy pane, several windows, no root; never -p / --resume
        self.assertIn("nothing typed", script)
        self.assertIn("-Root <thread root> is required", script)
        for banned in ("--resume", " -p "):
            self.assertNotIn(banned, script.split("# Only on the machine")[1] if "# Only on the machine" in script else script, banned)


if __name__ == "__main__":
    unittest.main()
