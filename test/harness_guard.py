"""No test may start the operator's real harness CLIs.

A real `claude -p /usage` or `codex exec /status` runs on the operator's own
account and leaves a session behind, and the real codex also trusts the folder
it ran in, in ~/.codex/config.toml. Tests use the fakes in test/fakes instead.

install() adds an audit hook that stops every spawn of a harness binary (or of
its .exe, .cmd, .bat or .ps1 shim) that is found outside test/fakes. The spawn
fails the way a binary that cannot start fails (PermissionError), and the test
that was running fails at cleanup, naming the binary. test/__init__.py,
test/demo/__init__.py and test/run.py call install(), so `python test/run.py`
and `python -m unittest test.demo.<module>` both carry it. It guards this
process only, not the Python children a test starts. harness_guard_test.py
pins it.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
import unittest

HARNESSES = frozenset({"claude", "codex", "grok", "cursor-agent", "agy", "hermes", "pi"})
_SHIMS = frozenset({".exe", ".cmd", ".bat", ".ps1"})
_SHELLS = frozenset({"cmd", "sh", "bash", "powershell", "pwsh"})
_SHELL_FLAGS = frozenset({"/c", "/k", "-c", "-command", "-file"})
_FAKES = os.path.normcase(os.path.realpath(os.path.join(os.path.dirname(__file__), "fakes"))) + os.sep

# The running test's id, and every spawn the hook stopped, as (test id, binary).
_state: dict = {"test": None, "blocked": []}


def _name(program: str) -> str:
    """`claude` for claude, claude.exe, claude.cmd or a path to claude.ps1."""
    base = os.path.basename(program).lower()
    stem, ext = os.path.splitext(base)
    return stem if ext in _SHIMS else base


def _first_word(line: str) -> tuple[str, str]:
    """A Windows command line's first word, and the rest. A quoted word may hold spaces."""
    line = line.lstrip()
    if line.startswith('"'):
        word, _, rest = line[1:].partition('"')
    else:
        word, _, rest = line.partition(" ")
    return word, rest


def _programs(command) -> list[str]:
    """What a command starts: its program and, for a shell, the program the shell is told to run.

    Windows hands a process one command line; POSIX hands it an argv list, and a shell one line.
    """
    if isinstance(command, str) and os.name == "nt":
        word, rest = _first_word(command)
        if _name(word) in _SHELLS:
            while rest.strip():
                flag, rest = _first_word(rest)
                if flag.lower() in _SHELL_FLAGS:
                    rest = rest.strip()
                    if len(rest) > 1 and rest[0] == rest[-1] == '"':
                        # cmd /c "..." drops one pair of outer quotes; list2cmdline wrote inner ones as \"
                        rest = rest[1:-1].replace('\\"', '"')
                    return [word] + _programs(rest)
        return [word]
    if isinstance(command, str):
        try:
            command = shlex.split(command)
        except ValueError:  # an unbalanced quote
            command = command.split()
    words = [os.fsdecode(w) for w in command]
    if words and _name(words[0]) in _SHELLS:
        for i, word in enumerate(words[1:-1], 1):
            if word.lower() in _SHELL_FLAGS:
                return words[:1] + _programs(words[i + 1])
    return words[:1]


def _real_harness(program: str, env) -> str | None:
    """The real harness binary a spawn would start; None for anything else, a fake, or a name not on PATH."""
    if _name(program) not in HARNESSES:
        return None
    if not os.path.dirname(program):
        # A bare name. Windows looks it up on this process's PATH; POSIX on the child's.
        search = None if env is None or os.name == "nt" else os.pathsep.join(os.get_exec_path(env))
        program = shutil.which(program, path=search)
        if not program:
            return None  # nothing to start; the spawn fails by itself
    return None if os.path.normcase(os.path.realpath(program)).startswith(_FAKES) else program


def _hook(event: str, args: tuple) -> None:
    if event == "subprocess.Popen":  # (executable, args, cwd, env); on Windows args is one line
        exe, command, env = args[0], args[1], args[3]
        if exe and isinstance(command, str):  # the executable is what starts, not the first word
            command = '"%s" %s' % (os.fsdecode(exe), _first_word(command)[1])
        elif exe:
            command = [os.fsdecode(exe)] + list(command)[1:]
    elif event == "os.system":  # (command,)
        command, env = os.fsdecode(args[0]), None
    elif event in ("os.exec", "os.posix_spawn", "os.startfile"):  # (path, ...)
        command, env = [os.fsdecode(args[0])], None
    elif event == "os.spawn":  # (mode, path, args, env)
        command, env = [os.fsdecode(args[1])], None
    else:
        return
    for program in _programs(command):
        binary = _real_harness(program, env)
        if binary:
            _state["blocked"].append((_state["test"], binary))
            raise PermissionError("the test suite never starts a real harness CLI: " + binary)


def _fail_if_blocked(test: unittest.TestCase, since: int) -> None:
    """A cleanup that runs last: fail the test if it tried to start a real harness."""
    started = [binary for who, binary in _state["blocked"][since:] if who == test.id()]
    if started:
        raise test.failureException(
            "tried to start the operator's real harness CLI (blocked): " + ", ".join(started)
            + ". Use test/fakes, or mock the call.")


def install() -> None:
    """Add the hook and the per-test check, once per process.

    This module can load under two names (harness_guard from test/run.py,
    test.harness_guard from the package), so the mark sits on TestCase.run.
    """
    if getattr(unittest.TestCase.run, "_no_real_harness", False):
        return
    run_one = unittest.TestCase.run

    def run(self, result=None):
        outer, _state["test"] = _state["test"], self.id()  # a test run inside a test is its own
        self.addCleanup(_fail_if_blocked, self, len(_state["blocked"]))  # added first, so it runs last
        try:
            return run_one(self, result)
        finally:
            _state["test"] = outer

    run._no_real_harness = True
    unittest.TestCase.run = run
    sys.addaudithook(_hook)


def blocked_outside_tests() -> list[str]:
    """Spawns stopped while no test ran: an import, a setUpClass, a thread that outlived its test."""
    return [binary for test, binary in _state["blocked"] if test is None]
