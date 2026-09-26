---
name: convoy
description: "/convoy orchestrates Convoy using live tools/list, never a frozen catalog."
---

# Convoy

Use this skill when the user asks for `/convoy` behavior, tool discovery, or
thread orchestration through Convoy MCP.

## Core contract (PR23 lock)

1. Always fetch the live MCP `tools/list` before presenting capabilities.
2. Never hardcode tool counts, stale tool names, or a frozen catalog.
3. If a tool is not returned by live `tools/list`, mark it unavailable instead
   of guessing. Operators with a source checkout can run
   `python -m convoy preflight` to score the live list against the wizard's
   required verbs. Each missing verb is one of: `redeploy` (registered on
   main, the live deploy lags), `write-gated` (registered, hidden until
   `CONVOY_MCP_WRITE_TOOLS=1` on that deploy), or `not-registered` (no MCP
   tool on main; needs a server commit). A marketplace install has no CLI
   and simply stays RED.

## Execution rules

- Public MCP endpoint is `https://convoy.bot/mcp`.
- Public MCP is bound to one root thread. A marketplace install cannot switch
  roots via CLI; attach an endpoint whose `--root` is the thread you want.
- Reuse only documented Convoy verbs and cards. Do not wrap vendor CLIs.
- Keep unknown values as `null`; do not invent session IDs, tokens, or usage.
- Model/effort per harness comes from live `card` (`rows[].models`,
  `rows[].effort`); `choices` is a lower-level read of the same catalogs.
  A `null` catalog is a free field.

## `/convoy --start` (CLI, not MCP)

`convoy start [<repo>]` is a thin CLI alias: git URL → clone once + onboard
`--github yes`; local path → onboard `--github no`; no repo → picker from
`recent()` (never auto-pick newest); empty → new-thread ask; cancel → unbound.
Already-live harness on the root → `attach`, never a duplicate `bring_up`.
It is not an MCP tool; a marketplace install uses the wizard sequence above.

## Preferred operator flow

1. Discover live harness/worktree state with `card` (one card, all rows).
   `choices` is the older read of the same catalogs.
2. Ensure harness registration with `onboard` (write-gated).
3. For N neurons use `crew` once (validates every seat, mints one worktree
   each, joins every chair with a boot prompt, one window). For one chair,
   `join` with `launch: true` is the MCP path; `seat` registers a chair
   without a boot prompt, so it never tells a neuron to connect. Never
   translate CLI shorthand such as `join --launch` into guessed MCP
   arguments.
4. Call `await_seated` to observe which chairs actually acked (`connected` |
   `pending` | `stale`); launched is not connected. `bring_up` / `open` only
   surface panes; they do not connect neurons.
5. Use `graph` for thread/neuron grounding, then `send`/`inbox` for delivery.

## Picker rows

When presenting selectable runtime options, format rows as:

- `where`
- `harness`
- `model`
- `effort`

Do not present third-party SaaS provider rows (for example Exa/Apollo style
cards) as Convoy plugin choices.
