"""Refusal next steps: each one is a command the CLI accepts.

A refusal that tells the reader what to run next names that command through next_step(),
which registers its argv here. test/demo/printed_commands_test.py parses every registered
argv with the CLI's own parser, so a renamed flag or a parameter name (opt_in for --opt-in)
cannot reach a refusal text unnoticed. Placeholders are `<word>` and parse as values.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re

# Every next step a module declared, in import order: the argv after `convoy`.
NEXT_STEPS: list[tuple[str, ...]] = []

_PLACEHOLDER = re.compile(r"^<[^<>]+>$")


def next_step(*argv: str) -> str:
    """Register one next step and return its printed form, `convoy <argv>`."""
    step = tuple(str(a) for a in argv)
    if step not in NEXT_STEPS:
        NEXT_STEPS.append(step)
    return "convoy " + " ".join(step)


def parseable(parser: argparse.ArgumentParser, argv: tuple[str, ...] | list[str]) -> bool:
    """True when the CLI parser accepts argv, with each `<placeholder>` as a value."""
    concrete = ["x" if _PLACEHOLDER.match(a) else a for a in argv]
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            parser.parse_args(concrete)
    except SystemExit:
        return False
    return True
