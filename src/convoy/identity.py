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
    END_HOOK_ARGS,
    INBOX_HOOK_ARGS,
    end_hook_command,
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
END_SKILL_NAME = "convoy-end"
END_SKILL_RELATIVE = (
    Path(".grok") / "skills" / END_SKILL_NAME / "SKILL.md",
    Path(".claude") / "skills" / END_SKILL_NAME / "SKILL.md",
    Path(".agents") / "skills" / END_SKILL_NAME / "SKILL.md",
)

GROK_AGENT_NAME = "convoy-neuron"
GROK_AGENT_RELATIVE = Path(".grok") / "agents" / (GROK_AGENT_NAME + ".md")
GROK_INBOX_HOOK_RELATIVE = Path(".grok") / "hooks" / "convoy-inbox.json"
CLAUDE_SETTINGS_RELATIVE = Path(".claude") / "settings.json"
CLAUDE_END_COMMAND_RELATIVE = Path(".claude") / "commands" / "end.md"
CODEX_HOOKS_RELATIVE = Path(".codex") / "hooks.json"
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
  or the PreToolUse hook (`convoy inbox --hook-pretooluse`). Fake send
  ACKs are not delivery.
- Usage dying: ASK the user to bring_up / open a pane, or write a
  `.convoy/handoff/<chair>-<ts>.md` file. Never guess remaining quota.
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
    "END: Codex/Claude Stop hooks run `convoy end --hook` as a heartbeat; this never pushes. "
    "Only explicit Codex `$convoy-end --push` or Claude `/end --push` grants one plain git push. "
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


def end_skill_source_path() -> Path:
    return Path(__file__).resolve().parent / "harness_skills" / END_SKILL_NAME / "SKILL.md"


def end_skill_text() -> str:
    return end_skill_source_path().read_text(encoding="utf-8")


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
        end_text = end_skill_text()
        end_paths: list[str] = []
        for rel in END_SKILL_RELATIVE:
            dest = wt / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
            if prev != end_text:
                dest.write_text(end_text, encoding="utf-8")
                out["written"] = True
            end_paths.append(str(dest))
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
        claude_command = wt / CLAUDE_END_COMMAND_RELATIVE
        claude_command.parent.mkdir(parents=True, exist_ok=True)
        before_command = claude_command.read_text(encoding="utf-8") if claude_command.is_file() else None
        command_text = (Path(__file__).resolve().parent / "harness_skills" / "end.md").read_text(encoding="utf-8")
        if before_command != command_text:
            claude_command.write_text(command_text, encoding="utf-8")
            out["written"] = True
        out["end_paths"] = end_paths
        out["claude_end_command"] = str(claude_command)
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


def _end_hook_entry(command: str) -> dict[str, Any]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 5,
                "statusMessage": "Recording Convoy heartbeat",
            }
        ]
    }


def grok_inbox_hook_document(command: str | None = None) -> dict[str, Any]:
    command = command or inbox_hook_command()
    entry = _command_hook_entry(command)
    # Stop: keep the turn alive while rows wait (grok-build 10-hooks.md, the
    # Stop gate). Same command; the handler reads hook_event_name from stdin.
    return {
        "hooks": {
            "PreToolUse": [entry],
            "Stop": [entry],
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


def _commands_in(node: Any, marker: str = INBOX_HOOK_ARGS) -> list[str]:
    """Every Convoy command containing ``marker`` inside a hook object."""
    found: list[str] = []
    if isinstance(node, dict):
        c = node.get("command")
        if isinstance(c, str) and marker in c:
            found.append(c)
        for v in node.values():
            found.extend(_commands_in(v, marker))
    elif isinstance(node, list):
        for v in node:
            found.extend(_commands_in(v, marker))
    return found


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


def _existing_hook_commands(text: str | None, marker: str = INBOX_HOOK_ARGS) -> list[str]:
    """Every matching command inside an existing hook document, or []."""
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _commands_in(data, marker)


def _resolved_or_kept(prev_text: str | None) -> dict[str, Any]:
    """Keep an existing Convoy hook command that still probes ok (audit
    2026-09-03: the only hook that ever delivered was a baked path a later
    first-run would have overwritten); else resolve fresh."""
    for c in _existing_hook_commands(prev_text):
        if _cmd.probe_existing_hook_command(c):
            return {"command": c, "resolved_via": "kept-existing", "error": None, "kept_existing": c}
    r = _cmd.resolve_inbox_hook_command()
    r["kept_existing"] = None
    return r


def _resolved_end_or_kept(prev_text: str | None) -> dict[str, Any]:
    for command in _existing_hook_commands(prev_text, END_HOOK_ARGS):
        if _cmd.probe_existing_end_hook_command(command):
            return {"command": command, "resolved_via": "kept-existing", "error": None,
                    "kept_existing": command}
    result = _cmd.resolve_end_hook_command()
    result["kept_existing"] = None
    return result


def _merge_end_hook(data: dict[str, Any], command: str) -> tuple[dict[str, Any], bool]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    events = hooks.get("Stop")
    if not isinstance(events, list):
        events = []
    rebuilt = [entry for entry in events if not _commands_in(entry, END_HOOK_ARGS)] + [_end_hook_entry(command)]
    changed = rebuilt != events
    hooks["Stop"] = rebuilt
    data["hooks"] = hooks
    return data, changed


def _ensure_end_hook_file(
    worktree: Path | str,
    relative: Path,
    root: Path | str | None,
) -> dict[str, Any]:
    dest = Path(worktree) / relative
    prev_text = dest.read_text(encoding="utf-8-sig") if dest.is_file() else None
    resolved = _resolved_end_or_kept(prev_text)
    out: dict[str, Any] = {
        "ok": True, "written": False, "hook": None,
        "command": resolved.get("command"), "resolved_via": resolved.get("resolved_via"),
        "kept_existing": resolved.get("kept_existing"),
    }
    command = resolved.get("command")
    if not command:
        out.update({"ok": False, "error": resolved.get("error")})
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
        data, changed = _merge_end_hook(data, command)
        if changed or not dest.is_file():
            dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            out["written"] = True
        out["hook"] = str(dest)
        if root is not None:
            from .inbox import write_root_pointer
            write_root_pointer(Path(worktree), Path(root))
        return out
    except OSError as e:
        out.update({"ok": False, "error": type(e).__name__ + ": " + str(e)})
        return out


def ensure_codex_end_hook(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Merge Convoy's heartbeat into project ``.codex/hooks.json``."""
    return _ensure_end_hook_file(worktree, CODEX_HOOKS_RELATIVE, root)


def ensure_claude_end_hook(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Merge the same heartbeat into Claude's project Stop hooks."""
    return _ensure_end_hook_file(worktree, CLAUDE_SETTINGS_RELATIVE, root)


def ensure_end_hooks(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    codex = ensure_codex_end_hook(worktree, root=root)
    claude = ensure_claude_end_hook(worktree, root=root)
    out = {
        "ok": bool(codex.get("ok") and claude.get("ok")),
        "written": bool(codex.get("written") or claude.get("written")),
        "command": codex.get("command") or claude.get("command") or end_hook_command(),
        "codex_hook": codex,
        "claude_hook": claude,
    }
    if not codex.get("ok"):
        out["error"] = codex.get("error")
    elif not claude.get("ok"):
        out["error"] = claude.get("error")
    return out


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
    doc = grok_inbox_hook_document(res["command"])
    payload = json.dumps(doc, indent=2) + "\n"
    # A kept command still needs the CURRENT event set: a file written before
    # the Stop gate existed carries only PreToolUse and leaves the pane deaf
    # at turn end (live 2026-09-05, four worktrees). Upgrade events, keep cmd.
    stale_events = False
    if prev is not None:
        try:
            have = set((json.loads(prev).get("hooks") or {}).keys())
            stale_events = have != set(doc["hooks"].keys())
        except (json.JSONDecodeError, AttributeError):
            stale_events = True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (res["resolved_via"] != "kept-existing" or stale_events) and prev != payload:
            dest.write_text(payload, encoding="utf-8")
            out["written"] = True
            out["upgraded_events"] = stale_events
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
    ending = ensure_end_hooks(worktree, root=root)
    hid = str(harness or "").strip().lower() or None
    kinds = dict(HARNESS_INBOX)
    out: dict[str, Any] = {
        "ok": bool(grok.get("ok") and claude.get("ok") and ending.get("ok")),
        "written": bool(grok.get("written") or claude.get("written") or ending.get("written")),
        "command": grok.get("command") or claude.get("command"),
        "resolved_via": grok.get("resolved_via") or claude.get("resolved_via"),
        "grok_hook": grok,
        "claude_hook": claude,
        "end_hooks": ending,
        "kinds": kinds,
        "harness": hid,
        "harness_kind": kinds.get(hid) if hid else None,
    }
    if not grok.get("ok"):
        out["error"] = grok.get("error")
    elif not claude.get("ok"):
        out["error"] = claude.get("error")
    elif not ending.get("ok"):
        out["error"] = ending.get("error") or "end-hook installation failed"
    return out

