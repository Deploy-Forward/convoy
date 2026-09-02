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

Effort keys are harness-scoped and must not be merged. The locked key space
lives in **CANON.md** ("Effort keys are harness-scoped") and the
machine-readable source of truth is `src/convoy/harness_effort.json` — this
README deliberately does not restate the table, so there is exactly one place
for it to drift from the code: none.

### Fully supported neurons (code-true contract)

| Harness | `onboard` / `roster` id | `resume_argv` shape | `ensure_first_run` behavior | `send --live` behavior |
| --- | --- | --- | --- | --- |
| `grok` | `grok` | `grok -m <model?> --agent <path?> --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes Convoy-owned `--agent` file and persists it on seat rows. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `claude` | `claude` | `claude --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes project `.claude/settings.json`, merges user `~/.claude/settings.json` skip key, and writes `~/.claude.json` trust project keys. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `codex` | `codex` | `codex resume <vendor-id?>` (**not** `--resume`) | Writes PATH ungate block; installs `neuron-identity`. No Claude settings writes. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `cursor-agent` | `cursor-agent` | `cursor-agent --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `agy` | `agy` | `agy --conversation <vendor-id?>` (live `--help` 2026-09-01: no `--resume`) | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `hermes` | `hermes` | `hermes --resume <vendor-id?>` (live `--help` 2026-09-01) | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |
| `pi` | `pi` | `pi --resume <vendor-id?>` (flag verified live; `--resume` opens a session picker — direct-id resume unverified) | Writes PATH ungate block; installs `neuron-identity`. | Native CLI on PATH. Live send refuses named resume/session tokens (`no-steal`). |

Notes tied to code/tests:

- `seat.session_id` and `seat.resume` are distinct: session key vs vendor resume token.
- First-run seats can omit vendor resume; then no resume token is passed.
- Live `send` is headless and never steals an active interactive neuron; refusal cards ask users to `bring_up` / open a pane or write `.ola/*handoff*`.
- `context.pack` overlays home-layer `convoy_id` + `thread_key` onto seat-worktree pointers when present.
- `bring_up` / `open` are the bulk show commands; targeted `join --launch` is
  the explicit one-chair exception described below.

### Bring-up and pane invariants

- Isolated WT only: one `wt --window new` spawn, one tab, split panes joined with literal `";"` argv elements.
- Bulk bring-up never uses `-w 0` or `-w <thread>`; targeted launch may use
  `-w 0` only after the user explicitly requests `--launch` from an active
  Windows Terminal session. Never `--` before harness exe; never per-seat
  `CREATE_NEW_CONSOLE`; never close on fail with `WM_CLOSE`.
- Two same-harness seats on different worktrees are two panes; duplicates collapse by worktree/resume/session key.
- `Ctrl+Shift+W` should only drop one split pane at a time (or no-op when there is no split pane left).
- Codex TUI conflict: while a Codex pane is focused, `Shift+Up` / `Shift+Down` can change reasoning level and fight pane navigation. Do not use those shortcuts for pane selection in that focus state.

### Targeted one-chair launch

Full contract and DoD: [`docs/targeted-launch.md`](docs/targeted-launch.md).

`convoy choices` lists installed harnesses, known Git/registered worktrees,
existing chair identifiers, and the detected terminal adapter. It deliberately
omits every vendor resume token. A model or user can then invoke:

```bash
convoy join --to <harness> --worktree <path> --launch
```

This registers and launches exactly one fresh chair. Harness argv construction
is independent of terminal placement, so all harnesses use the same terminal
adapter contract. A persistent atomic launch claim refuses duplicate launchers;
existing/resumable chairs are not eligible and a failed terminal spawn leaves
the fresh chair pending for an explicit retry.

Supported active-pane adapters:

| Host | Detection | Targeting |
| --- | --- | --- |
| Windows Terminal | Windows, `WT_SESSION`, and `wt` on PATH | `wt -w 0 split-pane`; targets the most-recent WT window and its active pane |
| tmux on macOS/Linux | `TMUX`, `TMUX_PANE`, and `tmux` on PATH | `tmux split-window -t <caller-pane>`; exact caller pane |

Other terminal hosts fail closed with a manual-pane instruction. Convoy never
injects keystrokes or guesses an iTerm, Terminal.app, WezTerm, kitty, or shell
API. Source installs currently require Python 3.11+; the project exposes a
cross-platform `convoy` console entry point, but a machine without Python still
needs a packaged executable/runtime before a skill can invoke it.

Creation and closure are separate capabilities. The Windows Terminal CLI can
create a split but does not expose its `closePane` action. A killed TUI may leave
an exited pane visible under graceful `closeOnExit`, so absent process IDs are
not pane-close proof. New targeted launches therefore use a Convoy lifecycle
host: after a separate, scoped `close-chair` consent it terminates only its owned
child tree and exits zero. Legacy panes still require `Ctrl+D` or the configured
`closePane` binding. First-run harness trust prompts are also user decisions;
Convoy returns an `awaiting-user-consent` card and never auto-accepts them.

## How it works

1. Attach `https://convoy.bot/mcp`.
2. Run `onboard` with harnesses you already installed.
3. Bind one thread at `--root`; Convoy writes/reads one durable `convoy_id`.
4. Use `send` for headless synapses and `feed` / `context` for pointers.
5. Use `bring_up` / `open` only when you want visible interactive TUIs for seated neurons.

## End-to-end example

```bash
# 1) Name installed harnesses and bind this root to one thread
python -m convoy onboard --to grok --to claude --to codex --thread demo

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

Development: `PYTHONPATH=src python3 test/run.py` (discovers `test/demo/*_test.py`).  
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
