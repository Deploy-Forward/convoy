"""Prepare a neuron worktree: the AGENTS.md pointer and the hooks.

Agent guidance ships from Deploy-Forward/plugins (the convoy plugin's skills).
AGENTS.md gets a short pointer block naming them. Convoy writes no skill text
of its own, and deletes nothing: a file an earlier Convoy wrote into a worktree
stays where it is, whatever its name. Never writes ~/.grok or ~/.claude
user-global skills. Never ola-brain.
"""
from __future__ import annotations

import hashlib
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
GROK_INBOX_HOOK_RELATIVE = Path(".grok") / "hooks" / "convoy-inbox.json"
# Convoy's Claude hooks live in the local settings file, which Claude Code keeps out of git.
CLAUDE_SETTINGS_RELATIVE = Path(".claude") / "settings.local.json"
CODEX_HOOKS_RELATIVE = Path(".codex") / "hooks.json"

_AGENTS_BLOCK = (
    SKILL_BEGIN + "\n"
    "You are a Convoy neuron on this thread. Run `convoy --root <root> whoami` first, then follow "
    "the convoy plugin's convoy-operate skill; convoy-dictionary defines every Convoy word. "
    "Convoy's skills ship only from Deploy-Forward/plugins (https://github.com/Deploy-Forward/plugins), "
    "as the convoy and worklanes plugins.\n"
    + SKILL_END + "\n"
)

# The sha256 of every block an earlier Convoy wrote between the markers (opening marker through
# closing marker, LF line endings). Only a block whose hash is here is replaced; one anybody
# edited is left as it is. test/demo/fixtures/agents_blocks.json holds the text of each.
KNOWN_AGENTS_BLOCKS = frozenset({
    "a238bd74a002b5cbb442ab43aecd7f09df4eb842e548e4e9dd248236bb2954d8",
    "b0fec251139313e6d111a32cfbe0ae923e8c11f78273ae5576193ea216795e5f",
    "ce0c03168669e3e9abbbc62fd969fb085259510ba507919342810245195b77a7",
    "fd8fb84353e2430be87b1dd2643b986016b333b3f447b114a2cd58a7a7b24fc4",
    "2193e92471e5e53da1e0b0d85eff2f65610612659d14f68fe401c44f4093d890",
    "082057ebb029bc8a3e753515c1a2a4e51106877e9d7af00a7f7e6371ba072d2e",
    "b3c884d9ec5a5d507cf47f164cb1c6455bd03d50e27e46bf78b814df5f21b863",
    "fd2f9a4efd38cd992904a750014fc52579f6672456e2932fd51d246b13b8f429",
    "586dc1fb5a8f11a78d8e8fab8083acc086d742d23ddcd1f8d09f4beafc2e19df",
    "228681e0edbdabf38e5b3dcb75e33106f341f41f241e5726046b6b6940e79bde",
    "d755c2d4f4ba0d7b054be56cc00ad84d95fd26629bfba841eb4130dd62eafcd0",
    "b0519c037a4721ab1dd7d422480c97bf1da41473baad7f87eaf29b9e16a1646c",
    "a6a603714df417d43b5cfbe53ad16aa38f3e9aaed7c09e94db468d500ce7fd23",
    "4602d90174743266394888d3ee1cb53a9d3e6fc1424dbfcf4133ff7b8879ce6a",
})


def _block_sha(core: str) -> str:
    return hashlib.sha256(core.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _merge_agents_block(existing: str, path: Path | str = "AGENTS.md") -> tuple[str, str | None]:
    """(text to write, warning). The text is existing, unchanged byte for byte, unless Convoy owns
    the change: a file with no block gains the pointer, and a block an earlier Convoy wrote (its
    hash is in KNOWN_AGENTS_BLOCKS) is replaced by the pointer. Everything outside the markers is
    kept as it is, line endings included. A block somebody edited, or an incomplete pair of
    markers, is left alone and the warning names the file."""
    current = _AGENTS_BLOCK[:-1]   # opening marker through closing marker
    nl = "\r\n" if "\r\n" in existing else "\n"
    begins, ends = existing.count(SKILL_BEGIN), existing.count(SKILL_END)
    if begins == 0 and ends == 0:
        block = current.replace("\n", nl) + nl
        prefix = existing.rstrip("\r\n")
        return (prefix + nl + nl + block if prefix.strip() else block), None
    start, stop = existing.find(SKILL_BEGIN), existing.find(SKILL_END)
    if begins == 1 and ends == 1 and start < stop:
        stop += len(SKILL_END)
        core = existing[start:stop]
        sha = _block_sha(core)
        if sha == _block_sha(current):
            return existing, None
        if sha in KNOWN_AGENTS_BLOCKS:
            block_nl = "\r\n" if "\r\n" in core else "\n"
            return existing[:start] + current.replace("\n", block_nl) + existing[stop:], None
    return existing, (str(path) + ": the Convoy block in this file is not one Convoy wrote (edited, or "
                      "its markers are incomplete); left as it is")


# Name kept for callers: it writes the AGENTS.md pointer, nothing else.
def install_neuron_identity(worktree: Path | str, *, person_files: bool = True) -> dict[str, Any]:
    """Write the AGENTS.md pointer into worktree. Idempotent. Writes no skill text and removes
    nothing. person_files False (the person's repo): AGENTS.md is left as it is."""
    out: dict[str, Any] = {
        "ok": True,
        "written": False,
        "removed": [],
        "agents": None,
    }
    if not person_files:
        return out
    wt = Path(worktree)
    try:
        agents = wt / "AGENTS.md"
        # newline="": read and write the characters as they are, so CRLF stays CRLF.
        before = ""
        if agents.is_file():
            with agents.open(encoding="utf-8", newline="") as f:
                before = f.read()
        merged, warning = _merge_agents_block(before, agents)
        if warning:
            out["warnings"] = [warning]
        elif merged != before:
            agents.write_text(merged, encoding="utf-8", newline="")
            out["written"] = True
        out["agents"] = str(agents)
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


def _existing_hook_commands(text: str | None, marker: str = INBOX_HOOK_ARGS) -> list[str]:
    """Every matching command inside an existing hook document, or []."""
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _commands_in(data, marker)


def _unresolved(out: dict[str, Any], error: Any) -> dict[str, Any]:
    """A failed probe: nothing written, nothing removed. `unresolved` tells the launch to refuse."""
    out.update({"ok": False, "error": error, "unresolved": True})
    return out


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
    resolved = _cmd.resolve_end_hook_command()
    out: dict[str, Any] = {
        "ok": True, "written": False, "hook": None,
        "command": resolved.get("command"), "resolved_via": resolved.get("resolved_via"),
    }
    command = resolved.get("command")
    if not command:
        return _unresolved(out, resolved.get("error"))
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
    The bare command is PROBED where it runs; when it resolves to a shim or to
    nothing, no file is written or removed (fail closed with the PATH error)."""
    dest = Path(worktree) / GROK_INBOX_HOOK_RELATIVE
    prev = dest.read_text(encoding="utf-8") if dest.is_file() else None
    res = _cmd.resolve_inbox_hook_command()
    out: dict[str, Any] = {"ok": True, "written": False, "hook": None, "command": res["command"],
                           "resolved_via": res["resolved_via"]}
    if not res["command"]:
        return _unresolved(out, res["error"])
    doc = grok_inbox_hook_document(res["command"])
    payload = json.dumps(doc, indent=2) + "\n"
    # A kept command still needs the CURRENT event set: a file written before
    # the Stop gate existed carries only PreToolUse and leaves the pane deaf
    # at turn end. Upgrade events, keep cmd.
    stale_events = False
    if prev is not None:
        try:
            have = set((json.loads(prev).get("hooks") or {}).keys())
            stale_events = have != set(doc["hooks"].keys())
        except (json.JSONDecodeError, AttributeError):
            stale_events = True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if prev != payload:
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
    carries the mode. Writes only the bare command; a failed probe leaves the file as it is.
    """
    dest = Path(worktree) / CLAUDE_SETTINGS_RELATIVE
    prev_text = dest.read_text(encoding="utf-8-sig") if dest.is_file() else None
    res = _cmd.resolve_inbox_hook_command()
    command = res["command"]
    out: dict[str, Any] = {"ok": True, "written": False, "hook": None, "command": command,
                           "resolved_via": res["resolved_via"]}
    if not command:
        return _unresolved(out, res["error"])
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

    Convoy writes no hook file for cursor-agent, agy, hermes or pi; they drain via
    `convoy inbox --drain`. cursor-agent does run project hooks (a Convoy command in a project's
    .claude/settings.json runs there too), but no Convoy cursor hook file is proven to deliver.
    Codex's hooks come from the convoy plugin; a send native-queues once its Stop hook has
    recorded the session id.
    Never invent Terminal.app / iTerm adapters.
    """
    from .inbox import HARNESS_INBOX

    skip = set(skip)
    # Resolve every command before writing any file, so one failed probe leaves the worktree as it was.
    probes = [_cmd.resolve_inbox_hook_command()]
    if CLAUDE_SETTINGS_RELATIVE.as_posix() not in skip:
        probes.append(_cmd.resolve_end_hook_command())
    failed = next((p for p in probes if not p.get("command")), None)
    if failed is not None:
        return _unresolved({"written": False, "command": None, "resolved_via": None,
                            "harness": str(harness or "").strip().lower() or None}, failed.get("error"))
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
    if any(card.get("unresolved") for card in (grok, claude, ending.get("claude_hook") or {})):
        out["unresolved"] = True
    if not grok.get("ok"):
        out["error"] = grok.get("error")
    elif not claude.get("ok"):
        out["error"] = claude.get("error")
    elif not ending.get("ok"):
        out["error"] = ending.get("error") or "end-hook installation failed"
    return out

