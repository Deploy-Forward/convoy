# Canonical names

Grok Bot is the conductor for repository work. Convoy is the singular source of truth any agent can tap (`feed`, seats, `convoy_id`).

| Term | Means | Does not mean |
| --- | --- | --- |
| **Grok Bot** | Conductor. One chat, own memory. Orchestrates neurons. | A neuron. A terminal window. A harness CLI session. |
| **neuron** | One `grok` / `claude` / `codex` / `cursor-agent` / `agy` session on a thread. | A second conductor. |
| **synapse** | Native Convoy `send` into one neuron (not `ola-brain side-chat`). | Ownership of another neuron's session, branch, or window. |
| **thread** | Durable circuit keyed by `convoy_id`; seats on that circuit share state. | One circuit per neuron. |
| **named thread** | A `--root` binding for that convoy circuit. | A second MCP URL. |
| **Convoy** | Source of truth: feed, seats, `convoy_id`, thread pointers. | A harness binary or a model wrapper. |
| **onboard** | First run after MCP attach: user names installed harnesses; Convoy reports PATH truthfully. | Auto-installed wrappers, invented roster entries, or auto-login. |
| **grok-bot-local** | Neuron host: user PC (WT + logged-in CLIs). | A second source of truth. |
| **grok-bot-cloud** | Neuron host: cloud agent machine (git/headless flows). | Nested Grok Bots or cloned TUI sessions. |

Product wording retires **hop** in favor of **neuron/synapse/thread**.

## Keyed contract (stable keys)

These keys are locked for docs and conductor language:

- `neuron.harness`: `grok | claude | codex | cursor-agent | agy`
- `thread.convoy_id`: durable `cvy_*`
- `thread.key`: named thread bound at `--root`
- `seat.session_id`: Convoy seat identifier (registry/seats key)
- `seat.resume`: vendor resume token used for native resume argv
- `seat.resume_key`: deterministic map key `cvr_<16hex>` from `(convoy_id, thread, to, worktree)`
- `synapse.mode`: `headless` (`send`) or `interactive` (`bring_up`/`open`)
- `pane.transport`: one isolated WT argv list (`wt --window new`) where split commands are joined with literal `";"` list elements

### Effort keys are harness-scoped

Do not collapse Codex and Claude into one enum.

| Harness | Convoy effort key space | Documented vendor surface | Convoy status |
| --- | --- | --- | --- |
| `codex` | `low`, `medium`, `high`, `extra-high`, `more-reasoning` | Upstream Codex docs expose `model_reasoning_effort` with `xhigh` and allow `-c/--config` overrides; inspected docs do **not** show a dedicated `codex --effort` flag. | Convoy does not set effort flags. |
| `claude` | `low`, `medium`, `high`, `xhigh`, `max` | Claude CLI docs expose `--effort low|medium|high|xhigh|max` (plus `ultracode`, outside this contract). | Convoy does not set effort flags. |
| `grok` | `high` observed; else `null` | No documented Grok effort CLI was verified in this repo run. | Keep unknown values as `null`. |
| `cursor-agent` | `null` | No effort control is documented in Convoy tree. | Keep `null`. |
| `agy` | `null` | No effort control is documented in Convoy tree. | Keep `null`. |

`extra-high` is the product key for Codex `xhigh`. `more-reasoning` is the TUI-only bucket where operators observed Max/Ultra prompts; no Convoy CLI key is documented for those.

Codex TUI menu text lock (model `gpt-5.6-sol`, "Select Reasoning Level"):

1. `low` — "Fast responses with lighter reasoning"
2. `medium` — "Balances speed and reasoning depth" (default)
3. `high` — "Greater reasoning depth"
4. `extra-high` — menu item "Extra high reasoning depth" (vendor value `xhigh`)
5. `more-reasoning` — menu path where Max/Ultra are exposed and consume limits faster

### Live Codex TUI conflict (documented behavior)

When a Codex neuron pane is focused, `Shift+Up` / `Shift+Down` can cycle reasoning level and conflict with WT pane selection. Convoy operator guidance: do not use those pane shortcuts while focused in Codex; set reasoning through documented config/CLI surfaces instead of hotkeys.

## Operational invariants

Do not spawn extra Grok Bot conductors unless explicitly requested. A new conductor needs a distinct thread key or it stomps the same checkout. Vendor resume ids stay on the host that created them.

`glance` includes a `conductor` card (`to: "grok-bot"`). Unknown values remain JSON `null` until a live probe exists.

`roster.present` is the MCP/agent process PATH. Interactive desktop terminals are a different PATH (bash skips `.profile`). Convoy first-run writes `~/.bashrc` so `claude`/`grok`/`codex` resolve in the next shell. Already-open terminals still need `source ~/.bashrc`.

Harness self-identity: `ensure_first_run` installs `neuron-identity` into the seat worktree (`.grok/skills`, `.claude/skills`, `AGENTS.md` pointer). Launched models read `thread.md` / `.convoy/id` and know they are a neuron on that `cvy_id`, not Grok Bot. `context.pack` includes `convoy_id` and `thread_key` from those one-line files (JSON `null` if missing).
