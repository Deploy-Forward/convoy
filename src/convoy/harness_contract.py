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


def _effort_block(harness_id: str) -> dict[str, Any]:
    wanted = canonical_harness_id(harness_id)
    for row in harness_entries():
        if row["id"] == wanted:
            eff = row.get("effort")
            return eff if isinstance(eff, dict) else {}
    return {}


def _accepted_efforts(eff: dict[str, Any]) -> list[str] | None:
    """What seat/join accept as `effort` for this harness: the harness-scoped
    keys, else the flag's own values when the harness only exposes a flag
    (pi --thinking, live 2026-09-01). None when the contract has no vocabulary
    (cursor-agent unknown, hermes model-driven) — Convoy cannot judge those."""
    keys = eff.get("keys")
    if isinstance(keys, list) and keys:
        return [str(k) for k in keys]
    values = eff.get("cli_values")
    if eff.get("cli_flag") and isinstance(values, list) and values:
        return [str(v) for v in values]
    return None


def _applied_flag(eff: dict[str, Any]) -> str | None:
    """The flag Convoy puts on argv, or None. A flag is applied only when the
    contract carries it WITH an evidence string quoting a live --help; codex
    has a config key and no evidence, so it is recorded, not applied."""
    flag = eff.get("cli_flag")
    if isinstance(flag, str) and flag.strip() and isinstance(eff.get("evidence"), str) and eff["evidence"].strip():
        return flag.strip()
    return None


def effort_contract(harness_id: str) -> dict[str, Any]:
    """Per-harness effort view for the wire, straight from the contract.
    Unknown stays null — the contract's own "unknown" mode token included,
    since the wire never says "unknown"; `applied` says whether a chosen
    effort reaches argv."""
    eff = _effort_block(harness_id)
    mode = eff.get("mode")
    return {
        "mode": None if mode == "unknown" else mode,
        "keys": _accepted_efforts(eff),
        "cli_flag": eff.get("cli_flag"),
        "evidence": eff.get("evidence"),
        "applied": _applied_flag(eff) is not None,
    }


def validate_effort(harness_id: str, effort: Any) -> str | None:
    """Normalize a declared effort for ONE harness. Blank is None. A value the
    harness does not take is refused naming its real keys (grok xhigh vs codex
    extra-high vs pi --thinking) — never a global enum. A harness without a
    vocabulary records the declaration as given."""
    text = str(effort).strip().lower() if isinstance(effort, str) else ""
    if not text:
        return None
    accepted = _accepted_efforts(_effort_block(harness_id))
    if accepted is not None and text not in accepted:
        hid = canonical_harness_id(harness_id)
        raise ValueError("refuse effort " + repr(text) + " for " + hid + ": " + hid + " takes " + ", ".join(accepted))
    return text


def effort_argv(harness_id: str, effort: Any) -> list[str]:
    """[flag, effort] when the harness has an evidenced flag and the value is
    one it takes; [] otherwise. Re-checks the value so a row written before
    validation existed never hands a vendor a word its --help does not list."""
    eff = _effort_block(harness_id)
    flag = _applied_flag(eff)
    text = str(effort).strip().lower() if isinstance(effort, str) else ""
    accepted = _accepted_efforts(eff)
    if flag and text and accepted is not None and text in accepted:
        return [flag, text]
    return []


def effort_applied(harness_id: str, effort: Any) -> bool | None:
    """Seat-row fact: None when no effort is declared, else whether argv carries it."""
    if not (isinstance(effort, str) and effort.strip()):
        return None
    return bool(effort_argv(harness_id, effort))


def model_catalog(harness_id: str) -> dict[str, Any]:
    """Per-harness model catalog for the wire: {models, evidence}. models is
    the contract's list or None; None means no local --help enumerates a
    closed list (live 2026-09-04: none does — every CLI present on this box
    takes a free-form --model; cursor-agent was not on PATH, so nothing was
    observed for it), so the card offers a field, not a menu. Never a
    remembered name."""
    wanted = canonical_harness_id(harness_id)
    for row in harness_entries():
        if row["id"] == wanted:
            models = row.get("models")
            return {
                "models": [str(m) for m in models] if isinstance(models, list) and models else None,
                "evidence": row.get("models_evidence"),
            }
    return {"models": None, "evidence": None}


def validate_model(harness_id: str, model: Any) -> str | None:
    """Blank is None. A model outside a NON-null catalog is refused naming the
    list; a null catalog accepts anything as declared — unknown is not a
    refusal, and Convoy never invents the list it would check against."""
    if not (isinstance(model, str) and model.strip()):
        return None
    models = model_catalog(harness_id)["models"]
    if models is not None and model not in models:
        hid = canonical_harness_id(harness_id)
        raise ValueError("refuse model " + repr(model) + " for " + hid + ": " + hid + " lists " + ", ".join(models))
    return model
