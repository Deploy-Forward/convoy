---
name: convoy
description: "/convoy orchestrates Convoy using live tools/list, never a frozen catalog."
---

# Convoy

Use this skill when the user asks for `/convoy` behavior, tool discovery, or
thread orchestration through Convoy MCP + CLI.

## Core contract (PR23 lock)

1. Always fetch the live MCP `tools/list` before presenting capabilities.
2. Never hardcode tool counts, stale tool names, or a frozen catalog.
3. If a tool is not returned by live `tools/list`, mark it unavailable instead
   of guessing.

## Execution rules

- Public MCP endpoint is `https://convoy.bot/mcp`.
- Public MCP is bound to one root thread; for other roots, run CLI with the
  target `--root`.
- Reuse only documented Convoy verbs and cards. Do not wrap vendor CLIs.
- Keep unknown values as `null`; do not invent session IDs, tokens, or usage.

## Preferred operator flow

1. Discover live harness/worktree state with `choices`.
2. Ensure harness registration with `onboard`.
3. Create/register seats with `join --launch` (single targeted launch) or
   `seat` (explicit chair registration).
4. Use `bring_up` (or `open`) to surface active panes for multiple seats.
5. Use `graph` for thread/neuron grounding, then `send`/`inbox` for delivery.

## Picker rows

When presenting selectable runtime options, format rows as:

- `where`
- `harness`
- `model`
- `effort`

Do not present third-party SaaS provider rows (for example Exa/Apollo style
cards) as Convoy plugin choices.
