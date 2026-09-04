#!/usr/bin/env python3
"""Derive MCP tool catalogs from this checkout and optionally probe a live URL.

Counts are never frozen in operator memory: they come from mcp_http.TOOLS and
_WRITE_TOOLS. Public https://convoy.bot/mcp must keep CONVOY_MCP_WRITE_TOOLS
unset (writes hidden). Gate 0 GREEN is a gated/loopback process.

This script does not spawn Windows Terminal, wt.exe, or bring_up live.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from convoy.mcp_http import TOOLS, _WRITE_TOOLS, make_server  # noqa: E402
from convoy.wizard_preflight import REQUIRED_WIZARD_VERBS, fetch_tools_list, preflight  # noqa: E402

PUBLIC_MCP_URL = "https://convoy.bot/mcp"
# Snapshot of the public wire on 2026-09-04 (this agent). Not a menu.
LIVE_LAG_2026_09_04 = (
    "roster", "glance", "onboard", "terminals", "context", "send", "feed",
    "bring_up", "open", "hide", "minimize", "background", "install",
)


def catalog() -> dict:
    names = [str(t["name"]) for t in TOOLS]
    public = [n for n in names if n not in _WRITE_TOOLS]
    write = sorted(_WRITE_TOOLS)
    return {
        "packaged_total": len(names),
        "public_count": len(public),
        "write_count": len(write),
        "public_names": public,
        "write_names": write,
        "all_names": names,
        "gate0_required": list(REQUIRED_WIZARD_VERBS),
        "gate0_count": len(REQUIRED_WIZARD_VERBS),
        "placeholder_mcp_origin_in_tree": "https://mcp-origin.example",
        "public_url": PUBLIC_MCP_URL,
        "note": "A remembered '25' is not a contract. Score Gate 0 from gate0_required; count from these lists.",
    }


def score_listed(listed: list[str], expect: str, url: str | None = None) -> dict:
    cat = catalog()
    live_set = set(listed)
    pub_set = set(cat["public_names"])
    all_set = set(cat["all_names"])
    write_listed = sorted(live_set & set(cat["write_names"]))
    pf = preflight(listed, url=url)
    out = {
        "url": url,
        "expect": expect,
        "listed_count": len(listed),
        "listed": listed,
        "write_tools_listed": write_listed,
        "preflight": pf,
        "catalog": {k: cat[k] for k in ("public_count", "packaged_total", "gate0_count")},
    }
    if expect == "public":
        missing_reads = [n for n in cat["public_names"] if n not in live_set]
        extra = sorted(live_set - pub_set)
        ok = listed == cat["public_names"]
        out["status"] = "GREEN" if ok else "RED"
        out["missing_public_reads"] = missing_reads
        out["unexpected"] = extra
        out["ok"] = ok
        out["gate0_on_public"] = pf["status"]
        if pf["ok"]:
            out["ok"] = False
            out["status"] = "RED"
            out["error"] = "public process must not make Gate 0 GREEN (write tools would be listed)"
    elif expect == "gated":
        missing = [n for n in cat["all_names"] if n not in live_set]
        ok = live_set == all_set and pf["ok"]
        out["status"] = "GREEN" if ok else "RED"
        out["missing_packaged"] = missing
        out["ok"] = ok
    elif expect == "live-lag":
        ok = tuple(listed) == LIVE_LAG_2026_09_04
        out["status"] = "LAG" if ok else "RED"
        out["ok"] = ok
        out["expected_lag"] = list(LIVE_LAG_2026_09_04)
        out["note"] = "public convoy.bot still serving the 13-tool pre-PR-52 catalog"
    else:
        out["status"] = "RED"
        out["ok"] = False
        out["error"] = "unknown expect: " + expect
    return out


def probe(url: str, expect: str) -> dict:
    try:
        listed = fetch_tools_list(url)
    except Exception as exc:
        return {
            "url": url,
            "expect": expect,
            "ok": False,
            "status": "RED",
            "error": type(exc).__name__ + ": " + str(exc)[:400],
            "listed": None,
        }
    return score_listed(listed, expect, url=url)


def loopback(expect: str) -> dict:
    """JSON-RPC against make_server on this checkout. No WT, no public URL."""
    home = Path(tempfile.mkdtemp(prefix="convoy-dod-home-"))
    root = Path(tempfile.mkdtemp(prefix="convoy-dod-root-"))
    (root / ".convoy").mkdir(parents=True, exist_ok=True)
    env = {
        "CONVOY_HOME": str(home),
        "CONVOY_MCP_WRITE_TOOLS": "1" if expect == "gated" else "",
    }
    with _env(env):
        httpd = make_server(root, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%s/mcp" % httpd.server_address[1]
            return probe(url, expect)
        finally:
            httpd.shutdown()
            httpd.server_close()


class _env:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.prev = {}

    def __enter__(self):
        for k, v in self.mapping.items():
            self.prev[k] = os.environ.get(k)
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        return self

    def __exit__(self, *exc):
        for k, old in self.prev.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", action="store_true", help="print derived catalogs and exit")
    p.add_argument("--url", default=None, help="probe this MCP URL (default none)")
    p.add_argument("--expect", choices=("public", "gated", "live-lag"), default="public")
    p.add_argument("--loopback", action="store_true", help="probe make_server on this checkout")
    args = p.parse_args(argv)
    if args.catalog:
        print(json.dumps(catalog(), indent=2))
        return 0
    if args.loopback:
        card = loopback(args.expect)
        print(json.dumps(card, indent=2))
        return 0 if card.get("ok") else 1
    if args.url:
        card = probe(args.url, args.expect)
        print(json.dumps(card, indent=2))
        return 0 if card.get("ok") else 1
    p.error("pass --catalog, --loopback, or --url")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
