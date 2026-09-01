"""Install harness self-identity skills into a neuron worktree.

Canonical text lives in convoy/harness_skills/neuron-identity/SKILL.md.
Copies land where grok and claude actually load skills. AGENTS.md gets a
short pointer block so Codex (and grok project rules) see the same contract.
Never writes ~/.grok or ~/.claude user-global skills. Never ola-brain.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SKILL_NAME = "neuron-identity"
SKILL_BEGIN = "# >>> convoy neuron identity >>>"
SKILL_END = "# <<< convoy neuron identity <<<"
SKILL_RELATIVE = (
    Path(".grok") / "skills" / SKILL_NAME / "SKILL.md",
    Path(".claude") / "skills" / SKILL_NAME / "SKILL.md",
)

_AGENTS_BLOCK = (
    SKILL_BEGIN + "\n"
    "You are a Convoy neuron on this thread, not Grok Bot. Read thread.md and "
    "the neuron-identity skill (.grok/skills/neuron-identity/SKILL.md or "
    ".claude/skills/neuron-identity/SKILL.md). Synapse via "
    "`python -m convoy send`. If usage is dying, ask the user to bring_up a "
    "pane; do not steal a TUI. Never invent cvy_ or session ids. Never ola-brain.\n"
    + SKILL_END + "\n"
)


def skill_source_path() -> Path:
    return Path(__file__).resolve().parent / "harness_skills" / SKILL_NAME / "SKILL.md"


def skill_text() -> str:
    path = skill_source_path()
    return path.read_text(encoding="utf-8")


def _merge_agents_block(existing: str) -> str:
    text = existing.replace("\r\n", "\n")
    if SKILL_BEGIN in text and SKILL_END in text:
        before = text.split(SKILL_BEGIN, 1)[0]
        after = text.split(SKILL_END, 1)[1]
        if after.startswith("\n"):
            after = after[1:]
        return before.rstrip("\n") + ("\n\n" if before.strip() else "") + _AGENTS_BLOCK + after
    prefix = text.rstrip()
    if prefix:
        return prefix + "\n\n" + _AGENTS_BLOCK
    return _AGENTS_BLOCK


def install_neuron_identity(worktree: Path | str) -> dict[str, Any]:
    """Write Convoy-owned identity skill copies into worktree. Idempotent."""
    out: dict[str, Any] = {
        "ok": True,
        "written": False,
        "paths": [],
        "agents": None,
    }
    wt = Path(worktree)
    try:
        src = skill_text()
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out
    try:
        paths: list[str] = []
        for rel in SKILL_RELATIVE:
            dest = wt / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
            if prev != src:
                dest.write_text(src, encoding="utf-8")
                out["written"] = True
            paths.append(str(dest))
        agents = wt / "AGENTS.md"
        before = agents.read_text(encoding="utf-8") if agents.is_file() else ""
        merged = _merge_agents_block(before)
        if merged != before:
            agents.write_text(merged, encoding="utf-8")
            out["written"] = True
        out["paths"] = paths
        out["agents"] = str(agents)
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out
