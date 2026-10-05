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

- The MCP endpoint is your own Convoy on loopback, `http://127.0.0.1:8788/mcp` (start it with `convoy mcp`).
- Your Convoy MCP is bound to one root thread. A marketplace install cannot switch
  roots via CLI; attach an endpoint whose `--root` is the thread you want.
- Reuse only documented Convoy verbs and cards. Do not wrap vendor CLIs.
- Keep unknown values as `null`; do not invent session IDs, tokens, or usage.
- Model/effort per harness comes from live `card` (`rows[].models`,
  `rows[].effort`); `choices` is a lower-level read of the same catalogs.
  A `null` catalog is a free field.

## `/convoy --start` (CLI, not MCP)

CLI resolution accepts a path, URL, owner/repo or name, reusing a matching checkout before cloning. `convoy start` with no target returns a picker; never auto-pick newest. Use `--search-root`, `--all` and `--create` only for their documented discovery/creation modes. Clean behind-only refresh is one fetch plus a local fast-forward-only merge; inspect `pulled`. Offline/incomplete discovery remains unknown. Read the returned start card's pointers. Start opens no pane and does not seat this session.

## Delivery and home writes

Use `send`, never a plain addressed `hook note`, to queue work to a neuron. Cards report `recorded`, `queued`, `native-queued`, `executed`, `refused` or `error`; none is proof of delivery. Only the target's proven token-citing receipt counts. Answer with `convoy reply <token> "..."` (the receipt: it counts and clears your pending row; it needs environment, token or pane-host proof) and report with `convoy report "..."`.

First run can prepare the thread index, `~/.bashrc`, `~/.claude/settings.json`, `~/.claude.json` and the Codex prompt at `~/.codex/prompts/convoy.md` (or `CODEX_HOME/prompts/convoy.md`). A live launch can also prepare harness-specific hook trust stores named by its card. Dry-run refuses the repo-file opt-in but is not universally read-only.

## List, attach and detach

Run `convoy list` and show its output verbatim, including skipped roots and unknown values. Default lists usable recent threads; `--all` includes hidden/older usable threads. Never delete skipped roots automatically.

For the person's chosen block, run `convoy attach <cvy_id|exact thread name>`. Map display pick numbers to the block's exact `cvy_` id; never pass a number. Attach proves this running native session, launches nothing, refuses unavailable/conflicting identity and reuses its chair on repeat. A session can sit on several threads (one chair each); the card lists the others in `also_on`. Legacy pointer-only catch-up uses `attach --read-only`.

Run `convoy detach [--thread <cvy_id|name>]` to detach the proven calling session. Its rolling handoff, chair, history and pending rows remain. It closes no pane and kills no session. Detached chairs cannot drain/pulse or wake; sends refuse until attach reactivates them.

## Wake service

Wake dispatch is off on a root until `convoy --root <root> wake enable`. Inspect it with `wake status` and opt out with `wake disable`. The supervised MCP origin runs the dispatcher for enabled roots. Its waiter route is dispatcher-managed: the session arms its own background waiter using the command the Stop hook prints, drains its own inbox on wake, acts, writes a proven token-citing receipt and re-arms before stopping. A hook-owned detached waiter cannot wake the session. Unknown routes, faults and held alerts are not delivery proof.

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
