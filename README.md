# Convoy

Convoy is shared project memory for Grok Bot: attach one MCP endpoint, route work to your existing CLIs, and keep every neuron grounded in one durable thread state.

## Terms

- **Grok Bot**: the conductor in this chat; not a neuron and not a window.
- **Neuron**: one BYO harness session (`grok`, `claude`, `codex`, `cursor-agent`, or `agy`) on a thread.
- **Synapse**: a native Convoy `send` into one neuron; one harness, one meter, compact card back.
- **Convoy**: source of truth (`feed`, seats, `convoy_id`).
- **Thread**: durable circuit keyed by `convoy_id`.
- **Named thread**: a `--root` binding (not a second MCP URL).
- **grok-bot-local vs grok-bot-cloud**: where a neuron runs (user PC vs cloud agent), not a second source of truth.

Product wording retires **hop** in favor of **neuron/synapse/thread**.

## The problem

Single-harness chat is weak project memory: context windows bloat, meter state drifts, and another agent cannot safely rehydrate shared state without copy/paste loss.

Wrapper stacks (one vendor CLI inside another) add indirection and contention instead of shared truth.

## The solution

Convoy keeps a slim pointer/stamp layer while Grok Bot remains conductor. Synapses run on native vendor CLIs, return compact cards, and keep session ownership separated.

Contract: feed + seats + `convoy_id`. Unknown values stay JSON `null`; no invented usage/session numbers.

## Current lock notes

- Windows bring-up uses isolated WT only: `wt --window new`, one tab, split panes (`; split-pane -V/-H`), argv-list tokenization, no `-w 0`, no `--` before harness exe.
- First-run Claude trust is explicit: project settings + home `~/.claude/settings.json` skip key + `~/.claude.json` `projects[worktree].hasTrustDialogAccepted=true` (both slash spellings).
- `convoy send --live` is headless and **does not steal/resume** an active interactive neuron. If a live seat already exists, resumed live send is refused (RED) rather than spawning a second interactive `--resume` process.
- First-run installs a `neuron-identity` harness skill into the seat worktree so the launched model knows it is a neuron on that `cvy_id`, not Grok Bot.

## How it works

1. Attach `https://convoy.bot/mcp`.
2. Run `onboard` with named harnesses.
3. Use `send` for a synapse and `feed`/`context` for pointers.
4. Use `bring_up` / `open` only when you want visible TUIs for seated neurons.
5. Use `glance` for quick overall + by-thread state.

Tiny CLI:

`python -m convoy onboard --to grok --to claude --thread payments`

`python -m convoy send --to claude --live "Summarize open payment retry bugs and propose a fix plan."`

`python -m convoy feed --since 2026-08-31T00:00:00Z`

`python -m convoy glance --convoy-id cvy_example --json`

Development: `PYTHONPATH=src python3 test/run.py`  
License: MIT.
