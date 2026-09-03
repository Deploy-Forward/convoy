"""Install harness self-identity skills into a neuron worktree.

Canonical text lives at skills/neuron-identity/SKILL.md (repo top level);
convoy/harness_skills/neuron-identity/SKILL.md is the packaged mirror this
module resolves at runtime — a byte-equality test keeps the two identical.
Copies land where grok and claude actually load skills. AGENTS.md gets a
short pointer block so Codex (and grok project rules) see the same contract.
Never writes ~/.grok or ~/.claude user-global skills. Never ola-brain.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import cmd as _cmd
from .cmd import (
    INBOX_HOOK_ARGS,
    inbox_hook_command,
)

SKILL_NAME = "neuron-identity"
SKILL_BEGIN = "# >>> convoy neuron identity >>>"
SKILL_END = "# <<< convoy neuron identity <<<"
SKILL_RELATIVE = (
    Path(".grok") / "skills" / SKILL_NAME / "SKILL.md",
    Path(".claude") / "skills" / SKILL_NAME / "SKILL.md",
)
# Second harness-agnostic skill: how ANY neuron receives and proves receipt
# (Marco 2026-09-03). Same install path as identity; AGENTS.md names it too.
RECEIVE_SKILL_NAME = "neuron-receive"
RECEIVE_SKILL_RELATIVE = (
    Path(".grok") / "skills" / RECEIVE_SKILL_NAME / "SKILL.md",
    Path(".claude") / "skills" / RECEIVE_SKILL_NAME / "SKILL.md",
)

GROK_AGENT_NAME = "convoy-neuron"
GROK_AGENT_RELATIVE = Path(".grok") / "agents" / (GROK_AGENT_NAME + ".md")
GROK_INBOX_HOOK_RELATIVE = Path(".grok") / "hooks" / "convoy-inbox.json"
CLAUDE_SETTINGS_RELATIVE = Path(".claude") / "settings.json"
CODEX_PROMPT_NAME = "convoy.md"

_GROK_AGENT_TEXT = """\
---
name: convoy-neuron
description: Convoy neuron seat identity for grok --agent. Not Grok Bot.
---

You are a Convoy neuron: one grok session on a Convoy thread, not Grok Bot.

- Persona: read `role.md` in this worktree.
- Identity: read `thread.md`, `.convoy/id`, `.convoy/thread`, and the
  neuron-identity skill (`.grok/skills/neuron-identity/SKILL.md`). Missing
  files mean unknown — JSON null. Never invent a `cvy_` or session id.
- Detect, identify, then send: `convoy panes` shows every body on the
  thread; `convoy whoami` names YOUR chair; write as yourself with
  `convoy hook note "..." --as-me --to <chair>` and read your place with
  `convoy graph --neuron <chair>`. (`convoy` is the console script; after a
  plain `pip install .` without PATH, `python -m convoy` is the same thing.)
- Synapse: `convoy send --to <harness> "..."`. Do not type into another
  neuron's TUI. Do not steal a live `--resume`.
- Inbox: a send into this live seat is queued under the thread root
  (`.convoy/inbox/<session_id>.jsonl`). Drain with `convoy inbox --drain`
  or the PreToolUse hook (`convoy inbox --hook-pretooluse`). Inbox is
  deferred delivery, not a wake. The vendor session-message API is ACP
  `session/prompt` (`convoy grok-acp`); it reaches a live TUI only when
  that TUI shares a grok leader. Fake send ACKs are not delivery. Never
  grok `-p` / `-c` a live seat.
- Usage dying: ASK the user to bring_up / open a pane, or write a
  `.ola/*handoff*` file. Never guess remaining quota.
"""

_AGENTS_BLOCK = (
    SKILL_BEGIN + "\n"
    "You are a Convoy neuron on this thread, not Grok Bot. Read thread.md and "
    "the neuron-identity skill (.grok/skills/neuron-identity/SKILL.md or "
    ".claude/skills/neuron-identity/SKILL.md). Detect, identify, then send: "
    "`convoy panes`, `convoy whoami`, `convoy hook note \"...\" --as-me --to <chair>`, "
    "`convoy graph --neuron <chair>`. Synapse via `convoy send` (or `python -m convoy`). "
    "RECEIVE (every turn start, any harness; see .grok/skills/neuron-receive/SKILL.md or "
    ".claude/skills/neuron-receive/SKILL.md): `convoy --root <root> whoami`, "
    "`feed --since <last ack>`, `inbox --drain --seat <you>`, then ack with "
    "`hook note ... --as-me --to <sender>`; a message is delivered only when YOU write that row. "
    "If usage is dying, ask the user to bring_up a "
    "pane; do not steal a TUI. Never invent cvy_ or session ids. Never ola-brain.\n"
    + SKILL_END + "\n"
)


_CODEX_PROMPT_TEXT = """---
description: Run a Convoy command against the current thread and report its JSON card
argument_hint: <convoy arguments>
---

Run the Convoy CLI from the current repository using the raw arguments below.
Prefer `convoy` when it is on PATH; otherwise use `python -m convoy`.

Raw slash-command arguments:
`$ARGUMENTS`

Preserve the arguments exactly. Use the current checkout/thread root unless the
arguments explicitly provide `--root`. Return the command's JSON card. Do not
invent convoy IDs, seat IDs, session IDs, usage, or delivery acknowledgements.
"""


def codex_prompt_source_path() -> Path:
    return Path(__file__).resolve().parent / "harness_skills" / CODEX_PROMPT_NAME


def install_codex_prompt() -> dict[str, Any]:
    """Install Codex's native custom prompt in CODEX_HOME/prompts."""
    import os
    out: dict[str, Any] = {"ok": True, "written": False, "path": None}
    try:
        src = codex_prompt_source_path().read_text(encoding="utf-8")
        codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        dest = codex_home / "prompts" / CODEX_PROMPT_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
        if prev != src:
            dest.write_text(src, encoding="utf-8")
            out["written"] = True
        out["path"] = str(dest)
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def skill_source_path() -> Path:
    return Path(__file__).resolve().parent / "harness_skills" / SKILL_NAME / "SKILL.md"


def skill_text() -> str:
    path = skill_source_path()
    return path.read_text(encoding="utf-8")


def receive_skill_source_path() -> Path:
    return Path(__file__).resolve().parent / "harness_skills" / RECEIVE_SKILL_NAME / "SKILL.md"


def receive_skill_text() -> str:
    return receive_skill_source_path().read_text(encoding="utf-8")


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
        recv = receive_skill_text()
        for rels, text in ((SKILL_RELATIVE, src), (RECEIVE_SKILL_RELATIVE, recv)):
            for rel in rels:
                dest = wt / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
                if prev != text:
                    dest.write_text(text, encoding="utf-8")
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
        prompt = install_codex_prompt()
        out["codex_prompt"] = prompt
        if prompt.get("written"):
            out["written"] = True
        if not prompt.get("ok"):
            out["ok"] = False
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def ensure_grok_agent(worktree: Path | str) -> dict[str, Any]:
    """Write the Convoy-owned grok agent file into worktree. Idempotent.

    Points grok --agent at seat identity (role.md + neuron-identity skill).
    Never overwrites a user agent elsewhere; owns only GROK_AGENT_RELATIVE.
    """
    out: dict[str, Any] = {"ok": True, "written": False, "agent": None}
    dest = Path(worktree) / GROK_AGENT_RELATIVE
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
        if prev != _GROK_AGENT_TEXT:
            dest.write_text(_GROK_AGENT_TEXT, encoding="utf-8")
            out["written"] = True
        out["agent"] = str(dest)
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def _command_hook_entry(command: str) -> dict[str, Any]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 8,
            }
        ]
    }


def grok_inbox_hook_document(command: str | None = None) -> dict[str, Any]:
    command = command or inbox_hook_command()
    return {
        "hooks": {
            "PreToolUse": [_command_hook_entry(command)],
        }
    }


def claude_inbox_hook_document(command: str | None = None) -> dict[str, Any]:
    """Same command as Grok. Claude injects allowing-hook additionalContext
    on UserPromptSubmit and PreToolUse (mid-turn / turn-start, never idle-wake)."""
    command = command or inbox_hook_command()
    entry = _command_hook_entry(command)
    return {
        "hooks": {
            "PreToolUse": [entry],
            "UserPromptSubmit": [entry],
        }
    }


def _commands_in(node: Any) -> list[str]:
    """Every Convoy inbox `command` string inside a hook object."""
    found: list[str] = []
    if isinstance(node, dict):
        c = node.get("command")
        if isinstance(c, str) and INBOX_HOOK_ARGS in c:
            found.append(c)
        for v in node.values():
            found.extend(_commands_in(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_commands_in(v))
    return found


def _hooks_already_have_command(events: Any, command: str) -> bool:
    # Compare extracted strings, never a JSON blob: our command contains
    # double quotes, which json.dumps escapes, so a substring test never
    # matched and every run appended ANOTHER copy (live 2026-09-03: this
    # worktree ended up with two identical entries per event).
    return any(c == command for c in _commands_in(events))


def _is_stale_convoy_entry(entry: Any, command: str) -> bool:
    """A Convoy-owned inbox hook entry that is NOT the command we resolved.

    The merge used to only append, so a hook Convoy wrote earlier and that no
    longer resolves stayed in the file and ran (and failed) on every tool call
    beside the working one (live 2026-09-03: convoy-wt-fable carried a dead
    `-m convoy` entry next to a good one). Only entries carrying our own
    INBOX_HOOK_ARGS are touched; a user's own hooks are never removed."""
    for c in _existing_hook_commands(json.dumps(entry)):
        if c != command:
            return True
    return False


def _merge_claude_inbox_hooks(data: dict[str, Any], command: str) -> tuple[dict[str, Any], bool]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    changed = False
    for event in ("PreToolUse", "UserPromptSubmit"):
        events = hooks.get(event)
        if not isinstance(events, list):
            events = []
        # Rebuild: everything that is not ours, then EXACTLY ONE entry of
        # ours. Filtering-then-appending left duplicates of the same command
        # in place; this cannot.
        others = [e for e in events if not _commands_in(e)]
        rebuilt = others + [_command_hook_entry(command)]
        if rebuilt != events:
            changed = True
        hooks[event] = rebuilt
    data["hooks"] = hooks
    return data, changed


def _existing_hook_commands(text: str | None) -> list[str]:
    """Every `command` string inside an existing hook document, or []."""
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            c = node.get("command")
            if isinstance(c, str) and INBOX_HOOK_ARGS in c:
                found.append(c)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


def _foreign_convoy_worktree(command: str) -> bool:
    """True when the baked interpreter lives in another convoy-wt-* tree.

    Live 2026-09-03: grok-lead kept
    convoy-wt-inbox\\.venv\\Scripts\\python.exe because that interpreter still
    probed ok. A keep of a working command is right when it is THIS install;
    a keep of another worktree's venv is a delivery bug the moment that
    worktree is gc'd or its convoy is stale.
    """
    text = str(command or "").replace("\\", "/").lower()
    here = str(Path(__file__).resolve()).replace("\\", "/").lower()
    key = "convoy-wt-"
    start = 0
    while True:
        i = text.find(key, start)
        if i < 0:
            return False
        j = i
        while j < len(text) and text[j] not in "/":
            j += 1
        name = text[i:j]
        if name and name not in here:
            return True
        start = j


def _resolved_or_kept(prev_text: str | None) -> dict[str, Any]:
    """Keep an existing Convoy hook command that still probes ok (audit
    2026-09-03: the only hook that ever delivered was a baked path a later
    first-run would have overwritten); else resolve fresh.

    Never keep a command whose interpreter is in a *different* convoy-wt-*
    tree than this package (live 2026-09-03: inbox venv shadowed grok-lead).
    """
    for c in _existing_hook_commands(prev_text):
        if _foreign_convoy_worktree(c):
            continue
        if _cmd.probe_existing_hook_command(c):
            return {"command": c, "resolved_via": "kept-existing", "error": None, "kept_existing": c}
    r = _cmd.resolve_inbox_hook_command()
    r["kept_existing"] = None
    return r


def ensure_grok_inbox_hook(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Write the Convoy-owned Grok PreToolUse inbox hook. Project-local only.
    The command is PROBED where it runs; a bare name that resolves to a shim
    or to nothing is never written (fail closed with the install hint)."""
    dest = Path(worktree) / GROK_INBOX_HOOK_RELATIVE
    prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
    res = _resolved_or_kept(prev)
    out: dict[str, Any] = {"ok": True, "written": False, "hook": None, "command": res["command"],
                           "resolved_via": res["resolved_via"], "kept_existing": res.get("kept_existing")}
    if not res["command"]:
        out.update({"ok": False, "error": res["error"]})
        return out
    payload = json.dumps(grok_inbox_hook_document(res["command"]), indent=2) + "\n"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if res["resolved_via"] != "kept-existing" and prev != payload:
            dest.write_text(payload, encoding="utf-8")
            out["written"] = True
        out["hook"] = str(dest)
        if root is not None:
            from .inbox import write_root_pointer
            write_root_pointer(Path(worktree), Path(root))
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def ensure_claude_inbox_hook(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Merge UserPromptSubmit + PreToolUse into project .claude/settings.json.

    Does not write skipDangerousModePermissionPrompt or permissions.defaultMode
    (those stay Claude first-run ungate). Refuses a baked interpreter path.
    """
    dest = Path(worktree) / CLAUDE_SETTINGS_RELATIVE
    prev_text = dest.read_text(encoding="utf-8-sig") if dest.is_file() else None
    res = _resolved_or_kept(prev_text)
    command = res["command"]
    out: dict[str, Any] = {"ok": True, "written": False, "hook": None, "command": command,
                           "resolved_via": res["resolved_via"], "kept_existing": res.get("kept_existing")}
    if not command:
        out.update({"ok": False, "error": res["error"]})
        return out
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if prev_text is not None:
            try:
                raw = json.loads(prev_text)
            except json.JSONDecodeError:
                raw = {}
            data = raw if isinstance(raw, dict) else {}
        else:
            data = {}
        data, changed = _merge_claude_inbox_hooks(data, command)
        if changed or not dest.is_file():
            dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            out["written"] = True
        out["hook"] = str(dest)
        if root is not None:
            from .inbox import write_root_pointer
            write_root_pointer(Path(worktree), Path(root))
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def ensure_inbox_hooks(
    worktree: Path | str,
    root: Path | str | None = None,
    harness: str | None = None,
) -> dict[str, Any]:
    """Swap-safe: write Grok + Claude hook docs for every non-home worktree.

    cursor-agent / agy / hermes / pi have no proven vendor hook file — they
    drain via `convoy inbox --drain`. Codex may native-queue on send.
    Never invent Terminal.app / iTerm adapters.
    """
    from .inbox import HARNESS_INBOX

    grok = ensure_grok_inbox_hook(worktree, root=root)
    claude = ensure_claude_inbox_hook(worktree, root=root)
    hid = str(harness or "").strip().lower() or None
    kinds = dict(HARNESS_INBOX)
    out: dict[str, Any] = {
        "ok": bool(grok.get("ok") and claude.get("ok")),
        "written": bool(grok.get("written") or claude.get("written")),
        "command": grok.get("command") or claude.get("command"),
        "resolved_via": grok.get("resolved_via") or claude.get("resolved_via"),
        "grok_hook": grok,
        "claude_hook": claude,
        "kinds": kinds,
        "harness": hid,
        "harness_kind": kinds.get(hid) if hid else None,
    }
    if not grok.get("ok"):
        out["error"] = grok.get("error")
    elif not claude.get("ok"):
        out["error"] = claude.get("error")
    return out

