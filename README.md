# Convoy

Convoy is shared project memory for Grok Bot: attach one MCP endpoint, route work to your existing CLIs, and keep every neuron grounded in one durable thread state.

Public MCP remains one root: `https://convoy.bot/mcp`. A named thread is a `--root` binding, not a second MCP URL.

## Terms

- **Grok Bot**: the conductor in this chat; not a neuron and not a window.
- **neuron**: one BYO harness session (`grok`, `claude`, `codex`, `cursor-agent`, `agy`/antigravity, `hermes`, or `pi`) on a thread.
- **synapse**: a native Convoy `send` into one neuron; one harness, one meter, compact card back.
- **Convoy**: source of truth (`feed`, seats, `convoy_id`).
- **thread**: durable circuit keyed by `convoy_id`.
- **named thread**: a `--root` binding (not a second MCP URL).
- **grok-bot-local vs grok-bot-cloud**: neuron host (user machine vs cloud agent), not a second source of truth.

Product wording retires **hop** in favor of **neuron/synapse/thread**.

## The problem

Single-harness chat is weak project memory: context windows bloat, meter state drifts, and another agent cannot safely rehydrate shared state without copy/paste loss.

Wrapper stacks (one vendor CLI inside another) add indirection and contention instead of shared truth.

## The solution

Convoy keeps a slim pointer/stamp layer while Grok Bot remains conductor. Synapses run on native vendor CLIs, return compact cards, and keep session ownership separated.

Contract: `feed` + seats + `convoy_id`. Unknown values stay JSON `null`; no invented usage/session numbers.

Machine-readable contract: `src/convoy/harness_effort.json` (loaded by MCP-facing code).

### Keyed effort language (locked)

Effort keys are harness-scoped and must not be merged:

- **Codex**: `low`, `medium`, `high`, `extra-high`, `more-reasoning`  
  - Product key `extra-high` maps to vendor `xhigh`.  
  - TUI lock (gpt-5.6-sol): `low` (fast/lighter), `medium` (default balance), `high` (deeper), `extra-high` (xhigh), `more-reasoning` (Max/Ultra path).  
  - Inspected upstream Codex docs expose `model_reasoning_effort` and `-c/--config`; this repo run could not execute `codex --help` (binary not present).  
  - Max/Ultra are treated as `more-reasoning` (TUI path), with no Convoy-specific CLI key documented here.
- **Claude**: `low`, `medium`, `high`, `xhigh`, `max` (`--effort` per Claude CLI docs).
- **Grok / cursor-agent / agy**: no verified effort CLI in this repo run; keep unknown as `null`.
- **Hermes / Pi**: harnesses are model-agnostic; effort belongs to the model they drive, so harness-level effort stays `null`.

### Fully supported neurons (code-true contract)

| Harness | `onboard` / `roster` id | `resume_argv` shape | `ensure_first_run` behavior | `send --live` behavior |
| --- | --- | --- | --- | --- |
| `grok` | `grok` | `grok -m <model?> --agent <path?> --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes Convoy-owned `--agent` file and persists it on seat rows. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `claude` | `claude` | `claude --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes project `.claude/settings.json`, merges user `~/.claude/settings.json` skip key, and writes `~/.claude.json` trust project keys. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `codex` | `codex` | `codex resume <vendor-id?>` (**not** `--resume`) | Writes PATH ungate block; installs `neuron-identity`. No Claude settings writes. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `cursor-agent` | `cursor-agent` | `cursor-agent --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `agy` | `agy` | `agy --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `hermes` | `hermes` | `hermes --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `pi` | `pi` | `pi --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |

Notes tied to code/tests:

- `seat.session_id` and `seat.resume` are distinct: session key vs vendor resume token.
- First-run seats can omit vendor resume; then no resume token is passed.
- Live `send` is headless and never steals an active interactive neuron; refusal cards ask users to `bring_up` / open a pane or write `.ola/*handoff*`.
- `context.pack` overlays home-layer `convoy_id` + `thread_key` onto seat-worktree pointers when present.
- `bring_up` / `open` are the only show commands.

### Bring-up and pane invariants

- Isolated WT only: one `wt --window new` spawn, one tab, split panes joined with literal `";"` argv elements.
- Never `-w 0`; never `-w <thread>`; never `--` before harness exe; never per-seat `CREATE_NEW_CONSOLE`; never close on fail with `WM_CLOSE`.
- Two same-harness seats on different worktrees are two panes; duplicates collapse by worktree/resume/session key.
- `Ctrl+Shift+W` should only drop one split pane at a time (or no-op when there is no split pane left).
- Codex TUI conflict: while a Codex pane is focused, `Shift+Up` / `Shift+Down` can change reasoning level and fight pane navigation. Do not use those shortcuts for pane selection in that focus state.

## How it works

1. Attach `https://convoy.bot/mcp`.
2. Run `onboard` with harnesses you already installed.
3. Bind one thread at `--root`; Convoy writes/reads one durable `convoy_id`.
4. Use `send` for headless synapses and `feed` / `context` for pointers.
5. Use `bring_up` / `open` only when you want visible interactive TUIs for seated neurons.

## End-to-end example

```bash
# 1) Name installed harnesses and bind this root to one thread
python -m convoy onboard --to grok --to claude --to codex --thread customer1

# 2) Register seated neurons (session key + optional vendor resume token)
python -m convoy seat --to grok --session-id seat-grok --worktree ../wt-grok --model gpt-5.6-sol --resume vendor-grok-uuid
python -m convoy seat --to codex --session-id seat-codex --worktree ../wt-codex --resume vendor-codex-uuid

# 3) Dry-run bring-up shows native argv (Codex uses "resume" subcommand)
python -m convoy bring-up --dry-run

# 4) Headless synapse (safe default)
python -m convoy send --to claude "Summarize open payment retry bugs and propose a fix plan."

# 5) Optional live headless run in a fresh native session (no resume token)
python -m convoy send --to codex --live "Draft unit tests for the retry planner."
```

Development: `PYTHONPATH=src python3 test/run.py` (discovers `test/customer1/*_test.py`).  
License: MIT.

## Cloudflare split hosting (static site + MCP proxy)

This repo includes a Cloudflare Worker config that serves the landing page/static files at the edge while preserving the existing Python MCP transport.

- Config: `wrangler.jsonc`
- Worker entry: `workers-site.mjs`
- Static assets directory: `src/convoy/site`

Routing behavior:

- `/mcp` and `/mcp/*` are proxied byte-for-byte to `MCP_ORIGIN` (the current Python MCP origin).
- all other paths are served from Worker static assets (`env.ASSETS.fetch(request)`).

Deploy steps (from an authenticated environment):

1. Set `MCP_ORIGIN` in `wrangler.jsonc` (or with environment-specific vars) to the current Python MCP origin URL.
2. Run `wrangler deploy`.
3. Attach the `convoy.bot/*` route to this Worker in Cloudflare.

This repo does not assume that Cloudflare Worker routing is live until those steps are completed.
