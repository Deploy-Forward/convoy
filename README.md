# Convoy

Convoy is the shared project memory for Grok Bot: attach one MCP endpoint, route work to your existing CLIs, and keep every hop grounded in the same thread state.

## Terms

- **Grok Bot**: the conductor in this chat; it orchestrates, is chip-less, and is not a hop or a window.
- **Hop**: a BYO harness CLI session (`grok`, `claude`, `codex`, `cursor-agent`, or `agy`); not a new Grok Bot.
- **Synapse**: the hop that executes the CLI; one harness, one `session_id`, one meter, compact card back.
- **Convoy**: the singular source of truth any agent taps: feed, seats, `convoy_id`.
- **Thread**: one Convoy thread per Grok Bot conductor; hops on a thread share it. Sharing a thread key stomps the same checkout.
- **`convoy_id` (`cvy_...`)**: durable id for that thread.
- **grok-bot-local vs grok-bot-cloud**: where a hop runs (user PC vs Grok Bot computer), not a second source of truth.

## The problem

One harness chat works for one conversation, but it is a weak system of record for a real project. Context windows bloat, meter state jumps around, and a second agent cannot reliably tap the same working state without copy/paste drift.

Teams then try to fix this by wrapping one vendor CLI inside another. That adds indirection instead of shared truth: more ceremony, less portability, and no durable pointer layer that other agents can safely rehydrate from.

There is also a collision problem: when two conductors share one thread key, they are steering the same checkout. Without one source of truth for seats and thread identity, that stomp risk is invisible until it hurts.

## The solution

Convoy keeps a skinny shared log of pointers and seat state, while Grok Bot stays the conductor. Work hops out as a synapse onto a BYO vendor CLI on that CLI's own meter, then returns as a compact card any agent can read.

The contract is simple: feed + seats + `convoy_id`. Any agent can rehydrate from those pointers without transcript scraping or invented usage math.

Convoy is BYO harness and wrapper-free: native vendor CLIs only; wrappers are refused.

`glance` is two layers: overall remaining by harness (live probes only; Grok remaining is JSON `null`, never `0` and never leftover-dollar fiction) and by thread id (which seats sit on that `cvy_...`). The public MCP owns this data contract.

## How it works

Attach `https://convoy.bot/mcp`, run `onboard` to name the harnesses you already have, let Convoy verify PATH truth (and point missing ones at install), check `roster`, then `send` work as a headless synapse (`live=true` uses the native CLI on PATH with vendor `--resume`, not a wrap). Read `feed` or `context` for pointers (not file dumps), and optionally use `bring_up` or `open` for a visible tiled TUI on a named thread; visible bring-up uses an isolated Windows Terminal window and never injects into the focused session. Use `glance` when you want quick meter and thread state.

## End-to-end example

1. Attach MCP endpoint: `https://convoy.bot/mcp`.
2. Onboard existing harnesses: `onboard` with `to=["grok","claude"]` and `thread="payments"`.
3. Send a synapse: `send` with `to="claude"`, `body="Summarize open payment retry bugs and propose a fix plan."`, `live=true`.
4. Example hop card shape: `{"ok":true,"to":"claude","session_id":"sess_claude_9f2b3a","argv":["claude","--resume","sess_claude_9f2b3a"],"pointers":{"worktree":"/workspace/.convoy/wt/payments"},"convoy_id":"cvy_7m4q2p9x"}`.
5. Read updates with `feed` using `since="2026-08-31T00:00:00Z"`.
6. Run `glance` by thread id: `glance convoy_id="cvy_7m4q2p9x"`.

Tiny CLI equivalent:

`python -m convoy onboard --to grok --to claude --thread payments`

`python -m convoy send --to claude --live "Summarize open payment retry bugs and propose a fix plan."`

`python -m convoy feed --since 2026-08-31T00:00:00Z`

`python -m convoy glance --convoy-id cvy_7m4q2p9x --json`

Development: `PYTHONPATH=src python3 test/run.py`  
License: MIT.
