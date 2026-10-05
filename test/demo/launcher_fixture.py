"""A real seated launcher chair for tests that drive launch mechanics.

Every launch records a proven launcher, and a chair launcher must be a seated chair on the
thread (seat_launcher refuses anything else). Tests that are about something other than who
launches use this: a synthetic chair, seated on the root the launch runs on the first time it
is asked for, so a launched_by naming a non-chair would still be caught. The refusals are
covered by launcher_always_test, conductor_launcher_test and widget_launcher_test.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

SYNTHETIC_CHAIR = "synthetic-launcher"
SYNTHETIC_LEAD = "synthetic-lead"


def _seated(root: Any, chair: str) -> None:
    from convoy.convoy import list_seats, seat
    root = Path(root)
    if not any(s.get("session_id") == chair for s in list_seats(root)):
        seat(root, "claude", chair, resume=chair + "-native")


def seated_launcher(root: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """The resolved launcher of a synthetic chair seated on this root."""
    _seated(root, SYNTHETIC_CHAIR)
    return {"kind": "seated", "chair": SYNTHETIC_CHAIR, "via": "environment", "why": None}


def widget_lead(root: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """The widget's launcher: a synthetic lead chair seated on this root."""
    _seated(root, SYNTHETIC_LEAD)
    return {"kind": "seated", "chair": SYNTHETIC_LEAD, "via": "widget-lead", "source": "widget-lead", "why": None}


def with_seated_launcher(fn):
    """add/crew with a seated synthetic launcher on the root they are called with."""
    @functools.wraps(fn)
    def call(root, *args, **kwargs):
        kwargs.setdefault("launcher", seated_launcher(root))
        return fn(root, *args, **kwargs)
    return call


def work_seats(root: Any, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """list_seats without the synthetic launcher chairs: the chairs the test itself made."""
    from convoy.convoy import list_seats
    return [s for s in list_seats(root, *args, **kwargs)
            if s.get("session_id") not in (SYNTHETIC_CHAIR, SYNTHETIC_LEAD)]
