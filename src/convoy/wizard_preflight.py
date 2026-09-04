"""Fail-closed preflight for the @convoy wizard.

The wizard may only drive verbs the live MCP endpoint actually lists. It never
freezes a menu (PR23) and never assumes a redeploy will fix a gap. Each missing
verb is classified from the packaged server's own registry, so the card says
WHICH gap it is: `redeploy` (registered on main, the live deploy lags),
`write-gated` (registered, but tools/list hides it until
CONVOY_MCP_WRITE_TOOLS=1 on that deploy), or `not-registered` (no MCP tool on
main either; needs a server commit). There is no CLI fallback: a marketplace
install is not a source checkout.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from .mcp_http import _WRITE_TOOLS as WRITE_GATED, TOOLS as PACKAGED_TOOLS

PUBLIC_MCP_URL = "https://convoy.bot/mcp"

# Every verb the wizard skill calls (plugin/convoy/skills/convoy-wizard, Gate 0),
# and only those: plugin_wizard_sequence_test holds Gate 0's list equal to this.
# A dependency set, not a menu: user-facing capabilities stay live-only.
# card superseded choices and the per-chair join/launch/seat/mint/bring_up walk
# (2026-09-04, item F): the wizard reads card once and crew does the rest.
REQUIRED_WIZARD_VERBS: tuple[str, ...] = (
    "card", "repos", "clone", "onboard", "crew", "consent", "await_seated",
    "neurons", "graph", "send", "inbox",
)

REMEDY_REDEPLOY = "redeploy"              # packaged server registers it; the live deploy lags main
REMEDY_NOT_REGISTERED = "not-registered"  # no MCP tool on main either; needs a server commit, not a redeploy
REMEDY_WRITE_GATED = "write-gated"        # packaged, but tools/list hides it until CONVOY_MCP_WRITE_TOOLS=1 on the deploy


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
    def _remedy(v: str) -> str:
        if v not in packaged:
            return REMEDY_NOT_REGISTERED
        return REMEDY_WRITE_GATED if v in WRITE_GATED else REMEDY_REDEPLOY
    remedy = {v: _remedy(v) for v in missing}
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
        "mutation_attempted": False,
        "error": error,
    }
    if listed is None:
        card["reason"] = "tools-list-failed"
        card["next"] = "reconnect-or-redeploy-mcp"
        card["ask"] = "tools/list failed; wizard must not ask setup questions or propose seats. Reconnect or redeploy the configured endpoint, then retry."
    elif missing:
        redeploy = [v for v in missing if remedy[v] == REMEDY_REDEPLOY]
        gated = [v for v in missing if remedy[v] == REMEDY_WRITE_GATED]
        unregistered = [v for v in missing if remedy[v] == REMEDY_NOT_REGISTERED]
        card["reason"] = "required-tools-missing"
        if unregistered:
            card["next"] = "mcp-server-commit"
        elif gated:
            card["next"] = "enable-write-tools-on-deploy"
        else:
            card["next"] = "reconnect-or-redeploy-mcp"
        parts = []
        if redeploy:
            parts.append("redeploy the public MCP to pick up: " + ", ".join(redeploy))
        if gated:
            parts.append("the deploy hides write tools until CONVOY_MCP_WRITE_TOOLS=1: " + ", ".join(gated) +
                         "; that is a deploy decision, not a redeploy")
        if unregistered:
            parts.append("no MCP tool is registered on main for: " + ", ".join(unregistered) + "; a redeploy cannot fix that, the server needs a commit")
        card["ask"] = ("wizard fail-closed. " + ". ".join(parts) +
                       ". Do not freeze or pad the menu, continue partially, or fall back to the CLI: a marketplace install is not a source checkout.")
    else:
        card["reason"] = None
        card["next"] = None
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
