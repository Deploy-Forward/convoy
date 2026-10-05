"""Prepare a neuron worktree: the AGENTS.md pointer, convoy-end, hooks.

Agent guidance lives in the Convoy plugin (convoy@deploy-forward): the
convoy-operate, convoy-listen and convoy-send skills. AGENTS.md gets a short
pointer block naming them. The retired neuron-identity and neuron-receive
copies Convoy used to write are removed. convoy-end is still copied where
grok, claude and codex load skills; canonical text is skills/convoy-end/,
harness_skills/convoy-end/ is the packaged mirror resolved at runtime.
Never writes ~/.grok or ~/.claude user-global skills. Never ola-brain.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import cmd as _cmd
from .cmd import (
    END_HOOK_ARGS,
    INBOX_HOOK_ARGS,
    end_hook_command,
    inbox_hook_command,
)

SKILL_BEGIN = "# >>> convoy neuron identity >>>"
SKILL_END = "# <<< convoy neuron identity <<<"
# Retired 2026-09-28 in favour of the plugin skills; first run removes the
# copies Convoy wrote here before.
RETIRED_SKILL_NAMES = ("neuron-identity", "neuron-receive")
RETIRED_SKILL_HOMES = (Path(".grok") / "skills", Path(".claude") / "skills")
END_SKILL_NAME = "convoy-end"
END_SKILL_RELATIVE = (
    Path(".grok") / "skills" / END_SKILL_NAME / "SKILL.md",
    Path(".claude") / "skills" / END_SKILL_NAME / "SKILL.md",
    Path(".agents") / "skills" / END_SKILL_NAME / "SKILL.md",
)

GROK_AGENT_NAME = "convoy-neuron"
GROK_AGENT_RELATIVE = Path(".grok") / "agents" / (GROK_AGENT_NAME + ".md")
GROK_INBOX_HOOK_RELATIVE = Path(".grok") / "hooks" / "convoy-inbox.json"
# Convoy's Claude hooks live in the local settings file, which Claude Code keeps out of git.
CLAUDE_SETTINGS_RELATIVE = Path(".claude") / "settings.local.json"
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
  convoy-operate skill from the Convoy plugin (convoy@deploy-forward). Missing
  files mean unknown — JSON null. Never invent a `cvy_` or session id.
- Detect, identify, then send: `convoy panes` shows every body on the
  thread; `convoy whoami` names YOUR chair; message a chair with `convoy send`
  (below); acknowledge a message with `convoy hook note "re token <token>: ..."
  --as-me --to <chair>`, which is the receipt (on a wake-enabled root it wakes
  that token's sender once, so don't also send a second message); read your place
  with `convoy graph --neuron <chair>`. (`convoy` is the console script; after a
  plain `pip install .` without PATH, `python -m convoy` is the same thing.)
- Synapse: `convoy send --to <harness> "..."`, or `convoy send --id <id> "..."` with the short id from `convoy neurons --all`. Do not type into another
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
    "You are a Convoy neuron on this thread. Run `convoy --root <root> whoami` first. "
    "Your guidance is the Convoy plugin's skills (convoy@deploy-forward): "
    "convoy-operate (first turn, identity, how to work on a thread), "
    "convoy-listen (wait, drain your inbox, acknowledge with `convoy reply <token> \"...\"`) and "
    "convoy-send (send one neuron a message and prove it arrived). "
    "Claude Code and Codex install the convoy plugin from the deploy-forward marketplace "
    "(Claude Code: `claude plugin install convoy@deploy-forward`). "
    "Grok and Cursor get rendered copies when the person runs the plugin's installer "
    "(`node plugin/install.mjs --apply`). "
    "agy, hermes and pi have none yet: run `convoy --root <root> whoami` "
    "and the receive loop in convoy-listen. "
    "Listening: --wait is for Claude and Grok background tasks. "
    "Codex is woken through its native queue (the convoy plugin's hooks record its session id): "
    "drain your inbox at turn start, and never run `inbox --wait` in the foreground. "
    "Convoy files: `convoy end --push` names any Convoy-written file in the commits it pushes.\n"
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


def remove_retired_skills(worktree: Path | str) -> list[str]:
    """Delete the retired skill copies Convoy itself wrote; return their paths.

    Only a SKILL.md whose front matter says exactly `name: <that skill>` is
    Convoy's; anything else is left alone. The folder goes only once empty.
    """
    removed: list[str] = []
    for home in RETIRED_SKILL_HOMES:
        for name in RETIRED_SKILL_NAMES:
            dest = Path(worktree) / home / name / "SKILL.md"
            if not dest.is_file():
                continue
            lines = dest.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            front = lines[1:lines.index("---", 1)] if lines[:1] == ["---"] and "---" in lines[1:] else []
            if "name: " + name not in (line.rstrip() for line in front):
                continue
            dest.unlink()
            removed.append(str(dest))
            if not any(dest.parent.iterdir()):
                dest.parent.rmdir()
    return removed


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


# Name kept for callers: it now writes the AGENTS.md pointer (and convoy-end)
# and removes retired skill copies; it no longer installs an identity skill.
def install_neuron_identity(worktree: Path | str, *, person_files: bool = True) -> dict[str, Any]:
    """Write the AGENTS.md pointer and Convoy-owned copies into worktree;
    remove the retired skill copies Convoy wrote before. Idempotent.
    person_files False (the person's repo): only the convoy-end copies; AGENTS.md, the retired
    copies and the end command are left as they are."""
    out: dict[str, Any] = {
        "ok": True,
        "written": False,
        "removed": [],
        "agents": None,
    }
    wt = Path(worktree)
    try:
        out["removed"] = remove_retired_skills(wt) if person_files else []
        if out["removed"]:
            out["written"] = True
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
        out["end_paths"] = end_paths
        if not person_files:
            return out
        agents = wt / "AGENTS.md"
        before = agents.read_text(encoding="utf-8") if agents.is_file() else ""
        merged = _merge_agents_block(before)
        if merged != before:
            agents.write_text(merged, encoding="utf-8")
            out["written"] = True
        out["agents"] = str(agents)
        prompt = install_codex_prompt()
        out["codex_prompt"] = prompt
        if prompt.get("written"):
            out["written"] = True
        if not prompt.get("ok"):
            out["ok"] = False
        # The plugin's convoy-end skill carries the end command. A copy Convoy wrote earlier, still
        # exactly Convoy's text, is removed; one the person changed is theirs and stays.
        claude_command = wt / CLAUDE_END_COMMAND_RELATIVE
        command_text = (Path(__file__).resolve().parent / "harness_skills" / "end.md").read_text(encoding="utf-8")
        if claude_command.is_file() and claude_command.read_text(encoding="utf-8") == command_text:
            claude_command.unlink()
            out["removed"] = list(out.get("removed") or []) + [str(claude_command)]
        return out
    except OSError as e:
        out["ok"] = False
        out["error"] = type(e).__name__ + ": " + str(e)
        return out


def person_files_missing(worktree: Path | str) -> list[str]:
    """The files a person could own that do not yet carry Convoy's part, read from disk:
    AGENTS.md without the pointer block."""
    agents = Path(worktree) / "AGENTS.md"
    try:
        has_block = agents.is_file() and SKILL_BEGIN in agents.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        has_block = False
    return [] if has_block else ["AGENTS.md"]


# Codex runs Convoy's hooks from the convoy plugin (codex-hooks.json), keyed once for every
# project. A project .codex/hooks.json is keyed by its absolute path, so in a fresh worktree it is
# a key nobody trusted and never runs; were it trusted, it would fire beside the plugin's. Convoy
# no longer writes one, and one an older Convoy wrote is the person's to remove.
CODEX_HOOKS_MIGRATION_NOTE = (
    ".codex/hooks.json still carries Convoy hooks an older Convoy wrote; the convoy plugin now runs "
    "them in Codex, so remove Convoy's entries from that file (Convoy leaves it as it is)")


def stale_codex_hooks(worktree: Path | str) -> str | None:
    """The worktree's .codex/hooks.json when it carries a Convoy end or inbox hook, else None."""
    dest = Path(worktree) / CODEX_HOOKS_RELATIVE
    try:
        text = dest.read_text(encoding="utf-8-sig") if dest.is_file() else None
    except OSError:
        return None
    if _existing_hook_commands(text, END_HOOK_ARGS) or _existing_hook_commands(text, INBOX_HOOK_ARGS):
        return str(dest)
    return None


def ensure_grok_agent(worktree: Path | str) -> dict[str, Any]:
    """Write the Convoy-owned grok agent file into worktree. Idempotent.

    Points grok --agent at seat identity (role.md + the plugin's convoy-operate).
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
            "PostToolUse": [entry],   # the pane stamps its own vendor usage (kind=usage) after tool calls
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
            "PostToolUse": [entry],
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
    # PostToolUse: the pane stamps its own vendor usage (kind=usage) after
    # tool calls (inbox.stamp_usage_row). A fresh install without it wrote no
    # usage row at all (an audit found zero kind=usage rows on a live thread).
    for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit"):
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


def _strip_convoy_entries(data: dict[str, Any], marker: str) -> tuple[dict[str, Any], bool]:
    """Remove every Convoy-owned entry (by command marker) from every event
    list, keeping foreign entries. Live 2026-09-09: a private client repo commits a
    .claude/settings.json carrying bare `convoy inbox --hook-pretooluse`; on
    a box where no hook-shell interpreter imports convoy, resolution fails and
    the installer used to return without touching the file, so two
    cursor-agent seats booted with a hook that exits 127 under Git Bash and
    every tool was refused. No hook (cli-drain) beats a dead hook."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data, False
    changed = False
    for event, events in list(hooks.items()):
        if not isinstance(events, list):
            continue
        kept = [e for e in events if not _commands_in(e, marker)]
        if kept != events:
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    data["hooks"] = hooks
    return data, changed


def is_convoy_written(path: str) -> bool:
    """A repo path Convoy writes into a worktree: its hooks, root pointers, local Claude settings and
    convoy-* copies. A push whose commits carry one is warned about."""
    rel = "/" + str(path).replace("\\", "/").lstrip("/")
    name = rel.rsplit("/", 1)[-1]
    return (rel.endswith("/.codex/hooks.json") or rel.endswith("/.claude/settings.local.json")
            or name in ("convoy-root", "convoy-inbox.json", "convoy-neuron.md") or "/convoy-end/" in rel)


def _json_object_or_none(text: str | None) -> dict[str, Any] | None:
    """{} for no file, the object for a JSON object, None for anything else (refuse to write)."""
    if text is None:
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _strip_dead_hook_file(dest: Path, prev_text: str | None, markers: tuple[str, ...]) -> bool:
    """Rewrite dest without Convoy's entries for the given markers. True when written."""
    if prev_text is None or not dest.is_file():
        return False
    try:
        raw = json.loads(prev_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict):
        return False
    data, changed = raw, False
    for m in markers:
        data, c = _strip_convoy_entries(data, m)
        changed = changed or c
    if changed:
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


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
        try:
            if _strip_dead_hook_file(dest, prev_text, (END_HOOK_ARGS, INBOX_HOOK_ARGS)):
                out["removed_dead"] = str(dest)
        except OSError as e:
            out["error"] = str(out["error"]) + "; and could not strip the dead hook: " + str(e)
        return out
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = _json_object_or_none(prev_text)
        if data is None:
            # A file that exists but is not a JSON object is the person's, and is never replaced.
            out.update({"ok": False, "error": "unparseable; left alone: " + str(dest)})
            return out
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


def ensure_claude_end_hook(worktree: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Merge the same heartbeat into Claude's project Stop hooks."""
    return _ensure_end_hook_file(worktree, CLAUDE_SETTINGS_RELATIVE, root)


def _skipped(rel: Path) -> dict[str, Any]:
    return {"ok": True, "written": False, "skipped": rel.as_posix()}


def ensure_end_hooks(worktree: Path | str, root: Path | str | None = None, *, skip: Iterable[str] = ()) -> dict[str, Any]:
    """skip: worktree paths not to write (a file the person could own, or one git tracks).
    Claude's Stop hook only: Codex's comes from the convoy plugin (see stale_codex_hooks)."""
    skip = set(skip)
    claude = (_skipped(CLAUDE_SETTINGS_RELATIVE) if CLAUDE_SETTINGS_RELATIVE.as_posix() in skip
              else ensure_claude_end_hook(worktree, root=root))
    out = {
        "ok": bool(claude.get("ok")),
        "written": bool(claude.get("written")),
        "command": claude.get("command") or end_hook_command(),
        "claude_hook": claude,
    }
    if not claude.get("ok"):
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
        if dest.is_file():
            try:
                dest.unlink()
                out["removed_dead"] = str(dest)
            except OSError as e:
                out["error"] = str(out["error"]) + "; and could not remove the dead hook: " + str(e)
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
    """Merge UserPromptSubmit + PreToolUse into the worktree's .claude/settings.local.json.

    Never writes skipDangerousModePermissionPrompt or permissions: the launch argv
    carries the mode. Refuses a baked interpreter path.
    """
    dest = Path(worktree) / CLAUDE_SETTINGS_RELATIVE
    prev_text = dest.read_text(encoding="utf-8-sig") if dest.is_file() else None
    res = _resolved_or_kept(prev_text)
    command = res["command"]
    out: dict[str, Any] = {"ok": True, "written": False, "hook": None, "command": command,
                           "resolved_via": res["resolved_via"], "kept_existing": res.get("kept_existing")}
    if not command:
        out.update({"ok": False, "error": res["error"]})
        try:
            if _strip_dead_hook_file(dest, prev_text, (INBOX_HOOK_ARGS,)):
                out["removed_dead"] = str(dest)
        except OSError as e:
            out["error"] = str(out["error"]) + "; and could not strip the dead hook: " + str(e)
        return out
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = _json_object_or_none(prev_text)
        if data is None:
            # A file that exists but is not a JSON object is the person's, and is never replaced.
            out.update({"ok": False, "error": "unparseable; left alone: " + str(dest)})
            return out
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
    *,
    skip: Iterable[str] = (),
) -> dict[str, Any]:
    """Swap-safe: write Grok + Claude hook docs for every non-home worktree.
    skip: worktree paths not to write (a tracked .claude/settings.local.json).

    cursor-agent / agy / hermes / pi have no proven vendor hook file — they
    drain via `convoy inbox --drain`. Codex's hooks come from the convoy plugin; a send
    native-queues once its Stop hook has recorded the session id.
    Never invent Terminal.app / iTerm adapters.
    """
    from .inbox import HARNESS_INBOX

    skip = set(skip)
    grok = ensure_grok_inbox_hook(worktree, root=root)
    claude = (_skipped(CLAUDE_SETTINGS_RELATIVE) if CLAUDE_SETTINGS_RELATIVE.as_posix() in skip
              else ensure_claude_inbox_hook(worktree, root=root))
    ending = ensure_end_hooks(worktree, root=root, skip=skip)
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

