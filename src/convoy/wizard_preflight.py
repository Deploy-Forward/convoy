"""Fail-closed preflight for the @convoy wizard.

The wizard may only drive verbs the live MCP endpoint actually lists. It never
freezes a menu (PR23) and never assumes a redeploy will fix a gap: a verb the
packaged server does not register either is CLI-only and the card says so.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from .mcp_http import TOOLS as PACKAGED_TOOLS

PUBLIC_MCP_URL = "https://convoy.bot/mcp"

# What the wizard sequence needs (FIRE 2026-09-04). Order is the wizard order.
REQUIRED_WIZARD_VERBS: tuple[str, ...] = ("choices", "graph", "inbox", "join", "launch", "seat")

REMEDY_REDEPLOY = "redeploy"      # packaged server has it; the live deploy lags main
REMEDY_CLI_ONLY = "cli-only"      # no MCP tool exists on main either; use python -m convoy --root <root> <verb>


def packaged_tool_names() -> list[str]:
    return [str(t["name"]) for t in PACKAGED_TOOLS]


def preflight(listed: list[str] | None, *, url: str | None = None, error: str | None = None) -> dict[str, Any]:
    """Score a live tools/list against the wizard's needs.

    listed=None means tools/list itself failed: the card is RED with the
    error verbatim and no tool is assumed present.
    """
    packaged = set(packaged_tool_names())
    live = None if listed is None else sorted({str(n) for n in listed})
    live_set = set(live or [])
    missing = [v for v in REQUIRED_WIZARD_VERBS if v not in live_set]
    remedy = {v: (REMEDY_REDEPLOY if v in packaged else REMEDY_CLI_ONLY) for v in missing}
    ok = listed is not None and not missing
    card: dict[str, Any] = {
        "ok": ok,
        "status": "GREEN" if ok else "RED",
        "url": url,
        "listed": live,
        "required": list(REQUIRED_WIZARD_VERBS),
        "missing": missing,
        "remedy": remedy,
        "frozen_menu": False,
        "error": error,
    }
    if listed is None:
        card["ask"] = "tools/list failed; wizard must not propose seats. Retry, or run the verbs via python -m convoy --root <root>."
    elif missing:
        redeploy = [v for v in missing if remedy[v] == REMEDY_REDEPLOY]
        cli_only = [v for v in missing if remedy[v] == REMEDY_CLI_ONLY]
        parts = []
        if redeploy:
            parts.append("redeploy the public MCP to pick up: " + ", ".join(redeploy))
        if cli_only:
            parts.append("no MCP tool exists on main for: " + ", ".join(cli_only) + "; drive them with python -m convoy --root <root> <verb>")
        card["ask"] = "wizard fail-closed. " + ". ".join(parts) + ". Do not freeze or pad the menu."
    return card


def fetch_tools_list(url: str, *, timeout: float = 20.0, opener: Callable[..., Any] = urllib.request.urlopen) -> list[str]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Mozilla/5.0 (convoy wizard preflight)",
        },
    )
    with opener(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    data = json.loads(raw)
    tools = data.get("result", {}).get("tools")
    if not isinstance(tools, list):
        raise ValueError("tools/list returned no result.tools: " + raw[:200])
    return [str(t.get("name")) for t in tools if isinstance(t, dict) and t.get("name")]


def run_preflight(url: str = PUBLIC_MCP_URL, *, tools: list[str] | None = None, fetch: Callable[[str], list[str]] = fetch_tools_list) -> dict[str, Any]:
    """CLI entry: --tools bypasses the network (offline/black-box tests)."""
    if tools is not None:
        return preflight(tools, url=None)
    try:
        listed = fetch(url)
    except Exception as exc:  # network, JSON, WAF: all RED, all verbatim
        return preflight(None, url=url, error=type(exc).__name__ + ": " + str(exc)[:300])
    return preflight(listed, url=url)
