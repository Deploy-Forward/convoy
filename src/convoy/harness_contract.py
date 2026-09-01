"""Load and query the stable harness/effort JSON contract."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONTRACT_PATH = Path(__file__).with_name("harness_effort.json")


def _normalize(name: Any) -> str:
    return str(name or "").strip().lower().replace("_", "-")


@lru_cache(maxsize=1)
def load_harness_contract() -> dict[str, Any]:
    data = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("harness contract must be a JSON object")
    harnesses = data.get("harnesses")
    if not isinstance(harnesses, list):
        raise ValueError("harnesses must be a list")
    return data


def contract_path() -> str:
    return str(_CONTRACT_PATH)


def harness_entries(*, mcp_supported_only: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_harness_contract().get("harnesses") or []:
        if not isinstance(row, dict):
            continue
        hid = _normalize(row.get("id"))
        if not hid:
            continue
        if mcp_supported_only and not bool(row.get("mcp_supported")):
            continue
        item = dict(row)
        item["id"] = hid
        rows.append(item)
    return rows


def canonical_harness_id(name: Any) -> str:
    key = _normalize(name)
    if not key:
        return ""
    for row in harness_entries():
        if key == row["id"]:
            return row["id"]
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            norm_aliases = {_normalize(a) for a in aliases}
            if key in norm_aliases:
                return row["id"]
    return key


def harness_exec(harness_id: str) -> str:
    wanted = canonical_harness_id(harness_id)
    for row in harness_entries():
        if row["id"] != wanted:
            continue
        exe = _normalize(row.get("exec"))
        return exe or wanted
    return wanted


def usage_probe_key(harness_id: str) -> str:
    wanted = canonical_harness_id(harness_id)
    for row in harness_entries():
        if row["id"] != wanted:
            continue
        probe = _normalize(row.get("usage_probe"))
        return probe or wanted
    return wanted


def usage_remaining_null_until_live_probe(harness_id: str) -> bool:
    wanted = canonical_harness_id(harness_id)
    for row in harness_entries():
        if row["id"] == wanted:
            return bool(row.get("usage_remaining_null_until_live_probe"))
    return False
