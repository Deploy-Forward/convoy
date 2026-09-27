"""No module in src/convoy may define the same top-level name twice.

A merge once left three functions defined twice, and the LATE copy silently
won, so the reviewed code was not the running code. Python does not warn - the second `def` just
rebinds the name. A reader diffing the file sees both and cannot tell which
one runs. Nothing else in the suite catches it, and a merge can reintroduce
it at any time, so it belongs in a test rather than in a review habit.

Scope is the direct children of the module body only. A name bound twice
inside `if TYPE_CHECKING:` / `try: ... except ImportError:` is a deliberate
fallback, not a merge artefact, and those live inside an If or a Try node.
`@overload` stubs are excluded for the same reason.
"""
import ast
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

PACKAGE = SRC / "convoy"


DEFINITION = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _is_overload(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        name = decorator.attr if isinstance(decorator, ast.Attribute) else getattr(decorator, "id", None)
        if name == "overload":
            return True
    return False


def duplicate_top_level_definitions(source: str) -> list[tuple[str, list[int]]]:
    """Names bound more than once by a def/class at the module's top level,
    each with every line that binds it, in first-seen order."""
    lines_by_name: dict[str, list[int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, DEFINITION) and not _is_overload(node):
            lines_by_name.setdefault(node.name, []).append(node.lineno)
    return [(name, lines) for name, lines in lines_by_name.items() if len(lines) > 1]


class DuplicateDefinitionScanner(unittest.TestCase):
    """The scanner itself, pinned against fixtures before it is trusted on
    the tree: a scanner that finds nothing is indistinguishable from a clean
    tree unless you have watched it find something."""

    def test_a_function_defined_twice_is_reported_with_both_line_numbers(self):
        source = "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef a():\n    return 3\n"
        self.assertEqual(duplicate_top_level_definitions(source), [("a", [1, 9])])

    def test_a_class_defined_twice_is_reported(self):
        source = "class C:\n    pass\n\n\nclass C:\n    pass\n"
        self.assertEqual(duplicate_top_level_definitions(source), [("C", [1, 5])])

    def test_a_clean_module_reports_nothing(self):
        source = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
        self.assertEqual(duplicate_top_level_definitions(source), [])

    def test_a_conditional_fallback_is_not_a_duplicate(self):
        source = ("try:\n    from x import a\nexcept ImportError:\n    def a():\n        return None\n\n\n"
                  "def a():\n    return 1\n")
        self.assertEqual(duplicate_top_level_definitions(source), [])

    def test_overload_stubs_are_not_duplicates(self):
        source = ("from typing import overload\n\n\n@overload\ndef a(x: int) -> int: ...\n\n\n"
                  "def a(x):\n    return x\n")
        self.assertEqual(duplicate_top_level_definitions(source), [])


class PackageHasNoDuplicateDefinitions(unittest.TestCase):
    def test_every_module_in_src_convoy_defines_each_top_level_name_once(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name, lines in duplicate_top_level_definitions(source):
                offenders.append(path.relative_to(SRC).as_posix() + ": " + name + " at lines " +
                                 ", ".join(str(n) for n in lines))
        self.assertEqual(offenders, [], "a later def silently rebinds the earlier one:\n" + "\n".join(offenders))

    def test_the_scan_actually_read_the_package(self):
        # A rglob that matched nothing would make the guard above vacuous.
        self.assertGreater(len(list(PACKAGE.rglob("*.py"))), 20)


if __name__ == "__main__":
    unittest.main()
