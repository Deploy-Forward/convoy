"""ONE card: what a host renders for @convoy in place of Exa/Apollo rows.

Marco's vision (2026-09-04): `@convoy` renders one card headed "convoy", the
way `@treg` renders its provider drill-down, reading "launch your neurons in
the cloud/local" where a SaaS card lists providers. The drill-down is harness
-> model -> effort | attach as neuron, with USAGE REMAINING per harness. The
wizard calls this once and drives repos -> onboard -> crew -> consent ->
await_seated from what came back: a remote host has no filesystem, so every
fact the older prose had it read from disk rides here instead.

Nothing on this card is new truth. Rows are `choices` rows (contract order,
effort/models/where/connect_mode from harness_effort.json) plus the usage
probe glance already runs (number|object|null, never an invented 0), plus a
crew attach template. preflight is wizard_preflight.preflight() scored on the
list the calling server hands in - its OWN tools/list - so the card carries
its own Gate 0 verdict. No seat row is rendered, so no vendor id, inbox token
or boot prompt can ride it.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Any, Callable

from .convoy import CONDUCTOR, list_seats, read_github, read_thread
from .glance import probe_view
from .harness_contract import WHERE
from .targeted_launch import GitWorktrees, launch_choices
from .usage import probe

HEADER = "convoy"
TAGLINE = "launch your neurons in the cloud/local"

_NULLABLE_STR = {"type": ["string", "null"]}
_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["where", "harness", "installed", "usage_remaining", "limited", "models", "effort", "connect_mode", "attach"],
    "properties": {
        "where": {"type": "array", "items": {"type": "string", "enum": list(WHERE)},
                  "description": "where a chair on this harness may sit; cloud only where the vendor --help evidences an interactive attach"},
        "harness": {"type": "string"},
        "name": _NULLABLE_STR,
        "installed": {"type": "boolean", "description": "shutil.which on the MCP host's PATH"},
        "usage_remaining": {"type": ["number", "object", "null"],
                            "description": "USAGE REMAINING from the live vendor probe; null when unknown or the harness has no meter, never 0"},
        "limited": {"type": "boolean"},
        "models": {"type": ["array", "null"], "items": {"type": "string"},
                   "description": "closed catalog or null (no local --help enumerates one: offer a free field)"},
        "models_evidence": _NULLABLE_STR,
        "effort": {"type": "object", "required": ["mode", "keys", "cli_flag", "applied"],
                   "properties": {"mode": _NULLABLE_STR, "keys": {"type": ["array", "null"], "items": {"type": "string"}},
                                  "cli_flag": _NULLABLE_STR, "evidence": _NULLABLE_STR, "applied": {"type": "boolean"}}},
        "connect_mode": {"type": ["string", "null"], "enum": ["hook", "native-queue-or-cli-drain", "cli-drain", None],
                         "description": "how a launched neuron receives; a label, not a connection"},
        "attach": {"type": "object", "required": ["tool", "args"],
                   "properties": {"tool": {"const": "crew"},
                                  "args": {"type": "object", "required": ["seats"],
                                           "properties": {"seats": {"type": "array", "items": {
                                               "type": "object", "required": ["harness", "where", "model", "effort"],
                                               "properties": {"harness": {"type": "string"}, "where": {"type": "string", "enum": list(WHERE)},
                                                              "model": _NULLABLE_STR, "effort": _NULLABLE_STR}}}}}}},
    },
}
CARD_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "header", "tagline", "summary", "preflight", "repo", "rows"],
    "properties": {
        "ok": {"type": "boolean"},
        "header": {"const": HEADER},
        "tagline": {"const": TAGLINE},
        "summary": {"type": "object", "required": ["harnesses_installed", "seats", "thread", "github"],
                    "properties": {"harnesses_installed": {"type": "integer"}, "seats": {"type": "integer"},
                                   "thread": _NULLABLE_STR,
                                   "github": {"type": ["string", "null"], "enum": ["yes", "no", None],
                                              "description": "the wizard's GitHub? answer recorded on this bind; null when never asked"}}},
        "preflight": {"type": "object", "required": ["ok", "status", "listed", "required", "missing", "remedy"],
                      "description": "wizard_preflight.preflight() scored on this server's own tools/list: the card's Gate 0 verdict"},
        "repo": {"type": "object", "required": ["github", "checkout", "worktrees"],
                 "properties": {"github": {"type": ["string", "null"], "enum": ["yes", "no", None]},
                                "checkout": {"type": ["string", "null"],
                                             "description": "the bound root when it is a git checkout (what crew mints from); null otherwise"},
                                "worktrees": {"type": "array", "items": {"type": "string"}}}},
        "rows": {"type": "array", "items": _ROW_SCHEMA, "description": "one per contract harness, contract order"},
    },
}

ProbeFn = Callable[[str], dict[str, Any]]
WhichFn = Callable[[str], str | None]


def _row(h: dict[str, Any], probe_fn: ProbeFn) -> dict[str, Any]:
    hid = str(h["id"])
    usage = probe_view(hid, probe_fn) if h["installed"] else {"limited": False, "usage_remaining": None}
    return {
        "where": [w for w in WHERE if (h["where"].get(w) or {}).get("offered")],
        "harness": hid,
        "name": h.get("name"),
        "installed": bool(h["installed"]),
        "usage_remaining": usage["usage_remaining"],
        "limited": bool(usage["limited"]),
        "models": h["models"],
        "models_evidence": h["models_evidence"],
        "effort": h["effort"],
        "connect_mode": h["connect_mode"],
        # The drill-down's leaf: attach as neuron. A crew call with this one
        # seat, model/effort left for the user to fill from the row above.
        "attach": {"tool": "crew", "args": {"seats": [{"harness": hid, "where": "local", "model": None, "effort": None}]}},
    }


def build_card(
    root: Path,
    *,
    listed: list[str] | None,
    probe_fn: ProbeFn | None = None,
    which_fn: WhichFn | None = None,
    git_worktrees: GitWorktrees | None = None,
) -> dict[str, Any]:
    """`listed` is the calling server's own tools/list (None when it failed),
    so preflight here is the same verdict Gate 0 would reach against it."""
    # wizard_preflight imports mcp_http, which imports this module: bound at
    # call time so neither import runs before the other has finished.
    from .wizard_preflight import preflight

    root = Path(root)
    fn = probe_fn or probe
    extra: dict[str, Any] = {"git_worktrees": git_worktrees} if git_worktrees is not None else {}
    choices = launch_choices(root, cwd=root, which=which_fn or which, **extra)
    rows = [_row(h, fn) for h in choices["harnesses"]]
    seats = [s for s in list_seats(root) if s.get("to") != CONDUCTOR and s.get("session_id") != CONDUCTOR]
    github = read_github(root)
    return {
        "ok": True,
        "header": HEADER,
        "tagline": TAGLINE,
        "summary": {
            "harnesses_installed": sum(1 for r in rows if r["installed"]),
            "seats": len(seats),
            "thread": read_thread(root),
            "github": github,
        },
        "preflight": preflight(listed),
        "repo": {
            "github": github,
            # crew mints from the bound root by default (crew.py); a root
            # without .git has nothing to mint from, and the card says so.
            "checkout": str(root.resolve()) if (root / ".git").exists() else None,
            "worktrees": choices["worktrees"],
        },
        "rows": rows,
    }
