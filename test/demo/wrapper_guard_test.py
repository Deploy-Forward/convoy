"""The wrapper guard reads exe positions only.

The guard exists to stop a pane from running a wrapper program instead of the harness. It
used to substring-match every argv word, so a thread whose root path merely contained a
wrapper's name (in the boot prompt, or in the pane host's --root value) was refused, and the
refused launch had already written its launch record. The guard now reads the basename of
each exe position: the harness exe the pane host runs, and the program each pane runs. When
that program is an interpreter or launcher (python, node, uvx), its script or package
argument is read too, since that argument is what the pane actually runs.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.bringup import _WT_VALUE_OPTIONS, _live_argv, isolated_wt_argv
from convoy.convoy import bind, ensure_id, list_seats, seat, update_seat

WT = r"C:\Windows\System32\wt.exe"
EXE = r"C:\Tools\claude.exe" if os.name == "nt" else "/usr/local/bin/claude"


def _wrapper(name):
    return ("C:\\Tools\\" if os.name == "nt" else "/usr/local/bin/") + name


class WrapperGuardReadsExePositions(unittest.TestCase):
    def thread(self, name):
        root = Path(tempfile.mkdtemp()) / name
        root.mkdir()
        ensure_id(root)
        bind(root, "guard")
        return root

    def chair(self, root, exe=EXE):
        wt = root / "wt"
        wt.mkdir(exist_ok=True)
        seat(root, "claude", "chair", worktree=str(wt), resume="11111111-1111-1111-1111-111111111111")
        # A pending boot prompt names the root twice, as a real join's prompt does.
        update_seat(root, "chair", boot_prompt="Run convoy --root " + str(root) + " seated; root " + str(root))
        row = [s for s in list_seats(root) if s.get("session_id") == "chair"][-1]
        return {**row, "exe": exe}

    def launch_records(self, root):
        panes = root / ".convoy" / "panes"
        return sorted(panes.glob("*.launch.json")) if panes.is_dir() else []

    def test_wrapper_guard_allows_ola_brain_in_root_and_prompt(self):
        for name in ("ola-brain-x", "side-chat-x"):
            root = self.thread(name)
            argv = isolated_wt_argv("guard", [self.chair(root)], wt=WT, root=root)
            out = _live_argv(argv)
            self.assertEqual(out[0], WT)
            self.assertEqual(len(self.launch_records(root)), 1)

    def test_wrapper_guard_refuses_wrapper_exe(self):
        for name in ("ola-brain.exe", "side-chat.cmd", "ultracode-shim.exe"):
            root = self.thread("plain-x")
            with self.assertRaises(ValueError, msg=name):
                isolated_wt_argv("guard", [self.chair(root, exe=_wrapper(name))], wt=WT, root=root)

    def test_refused_launch_writes_no_launch_record(self):
        root = self.thread("plain-x")
        with self.assertRaises(ValueError):
            isolated_wt_argv("guard", [self.chair(root, exe=_wrapper("ola-brain.exe"))], wt=WT, root=root)
        self.assertEqual(self.launch_records(root), [])

    def test_live_argv_refuses_wrapper_program_in_a_pane(self):
        argv = [WT, "-w", "convoy-0a1b2c3d", "new-tab", "--title", "t", "-d", r"C:\tmp",
                _wrapper("ola-brain.exe"), "send"]
        with self.assertRaises(ValueError):
            _live_argv(argv)

    def test_live_argv_allows_wrapper_name_in_pane_arguments(self):
        argv = [WT, "-w", "convoy-0a1b2c3d", "new-tab", "--title", "t", "-d", r"C:\tmp",
                EXE, "--root", r"C:\tmp\ola-brain-x", "--seat", "side-chat-x"]
        self.assertEqual(_live_argv(argv)[0], WT)

    def test_live_argv_reads_camel_case_wt_options(self):
        # wt documents its options in camelCase; the value after one is never the program.
        for opt, val in (("--startingDirectory", r"C:\d"), ("--tabColor", "#fff"),
                         ("--colorScheme", "Campbell"), ("--Profile", "Ubuntu")):
            argv = [WT, "-w", "convoy-abcd1234", "new-tab", opt, val, _wrapper("side-chat.cmd")]
            with self.assertRaises(ValueError, msg=opt):
                _live_argv(argv)

    def test_live_argv_reads_the_program_after_a_wt_flag(self):
        # Some wt options are flags with no value; the word after one is the pane's program.
        for flag in ("--suppressApplicationTitle", "--useApplicationTitle", "-V", "-H"):
            argv = [WT, "-w", "convoy-abcdef12", "nt", flag, _wrapper("ola-brain.exe")]
            with self.assertRaises(ValueError, msg=flag):
                _live_argv(argv)

    def test_live_argv_reads_the_program_after_every_value_option(self):
        for opt in sorted(_WT_VALUE_OPTIONS):
            argv = [WT, "-w", "convoy-abcdef12", "nt", opt, "v", _wrapper("ola-brain.exe")]
            with self.assertRaises(ValueError, msg=opt):
                _live_argv(argv)

    def test_live_argv_reads_the_program_a_shell_runs(self):
        for shell, flag in (("cmd", "/c"), ("powershell", "-Command"), ("pwsh", "-c"), ("bash", "-c")):
            argv = [WT, "-w", "convoy-abcd1234", "new-tab", "-d", r"C:\d", shell, flag, "ola-brain", "run"]
            with self.assertRaises(ValueError, msg=shell):
                _live_argv(argv)

    def test_live_argv_allows_a_shell_running_the_harness(self):
        argv = [WT, "-w", "convoy-abcd1234", "new-tab", "-d", r"C:\tmp\ola-brain-x", "cmd", "/c", EXE,
                "--root", r"C:\tmp\plain-x"]
        self.assertEqual(_live_argv(argv)[0], WT)

    def test_live_argv_reads_every_word_a_shell_runs(self):
        # A shell's command line can chain programs, so under a shell every later word is
        # read as a possible program; Convoy's own panes never run through a shell.
        argv = [WT, "-w", "convoy-abcd1234", "new-tab", "cmd", "/c", EXE, "&&", _wrapper("side-chat.cmd")]
        with self.assertRaises(ValueError):
            _live_argv(argv)

    def test_live_argv_reads_the_script_an_interpreter_runs(self):
        # A pane may run a wrapper through an interpreter or launcher: the program is then
        # python, node or uvx, and the wrapper is its script or package argument.
        cases = (
            ["C:/py/python.exe", "C:/tools/ola-brain/main.py"],
            ["C:/py/python3.12.exe", "-u", "C:/tools/ola-brain.py", "send"],
            ["py", "-3.12", "C:/tools/ola-brain/main.py"],
            ["pythonw", "-m", "ola_brain"],
            ["python3", "-X", "utf8", "/opt/side-chat/__main__.py"],
            ["uvx", "ola-brain"],
            ["uvx", "--from", "ola-brain", "ob"],
            ["uv", "run", "--with", "rich", "C:/tools/ola-brain/main.py"],
            ["uv", "tool", "run", "side-chat"],
            ["pipx", "run", "ultracode-shim"],
            ["node", "C:/tools/side-chat/index.js"],
            ["node", "--require", "ts-node/register", "C:/tools/ultracode-shim/cli.ts"],
            ["npx", "-y", "side-chat@latest"],
            ["npx.cmd", "-p", "@acme/ola-brain", "ob"],
            ["deno", "run", "-A", "C:/tools/side-chat.ts"],
            ["bun", "x", "ola-brain"],
            ["ruby", "C:/tools/side-chat/bin/side-chat"],
            ["perl", "-w", "C:/tools/ultracode-shim.pl"],
        )
        for pane in cases:
            argv = [WT, "-w", "convoy-abcd1234", "nt", "-d", r"C:\d", *pane]
            with self.assertRaises(ValueError, msg=" ".join(pane)):
                _live_argv(argv)

    def test_live_argv_reads_the_script_an_interpreter_runs_under_a_shell(self):
        for pane in (["cmd", "/c", "C:/py/python.exe", "C:/tools/ola-brain/main.py"],
                     ["bash", "-c", "uvx ola-brain"],
                     ["powershell", "-File", "C:/tools/run.ps1", "&&", "node", "C:/tools/side-chat/index.js"]):
            argv = [WT, "-w", "convoy-abcd1234", "nt", *pane]
            with self.assertRaises(ValueError, msg=" ".join(pane)):
                _live_argv(argv)

    def test_live_argv_allows_an_interpreter_running_the_harness(self):
        # A root, a boot prompt, a --seat value or a wt profile may carry a wrapper's name;
        # under an interpreter only the script or package argument is read.
        for pane in (
            ["C:/py/python.exe", "C:/tools/harness/main.py", "--root", "C:/tmp/ola-brain-x",
             "--seat", "side-chat-x", "Run convoy --root C:/tmp/ola-brain-x seated"],
            ["uvx", "harness", "--seat", "ola-brain-x"],
            ["node", "C:/tools/harness/index.js", "--root", "C:/tmp/side-chat-x"],
            ["npx", "-y", "harness", "ultracode-shim-x"],
        ):
            argv = [WT, "-w", "convoy-abcd1234", "nt", "-p", "ola-brain-x", "-d", "C:/tmp/ola-brain-x", *pane]
            self.assertEqual(_live_argv(argv)[0], WT, msg=" ".join(pane))

    def test_refused_second_pane_writes_no_launch_record_for_the_first(self):
        root = self.thread("plain-x")
        first = self.chair(root)
        wt2 = root / "wt2"
        wt2.mkdir()
        seat(root, "claude", "chair2", worktree=str(wt2), resume="22222222-2222-2222-2222-222222222222")
        row2 = [s for s in list_seats(root) if s.get("session_id") == "chair2"][-1]
        second = {**row2, "exe": _wrapper("ola-brain.exe")}
        with self.assertRaises(ValueError):
            isolated_wt_argv("guard", [first, second], wt=WT, root=root)
        self.assertEqual(self.launch_records(root), [])


if __name__ == "__main__":
    unittest.main()
