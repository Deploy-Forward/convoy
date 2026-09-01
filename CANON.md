# Canonical names

Grok Bot is the conductor for repository work. Convoy is the singular source of truth any agent can tap (`feed`, seats, `convoy_id`).

| Term | Means | Does not mean |
| --- | --- | --- |
| **Grok Bot** | Conductor. One chat, own memory. Orchestrates neurons. | A neuron. A terminal window. A harness CLI session. |
| **neuron** | One `grok` / `claude` / `codex` / `cursor-agent` session on a thread. | A second conductor. |
| **synapse** | Native Convoy `send` into one neuron (not `ola-brain side-chat`). | Ownership of another neuron's session, branch, or window. |
| **thread** | Durable circuit keyed by `convoy_id`; seats on that circuit share state. | One circuit per neuron. |
| **named thread** | A `--root` binding for that convoy circuit. | A second MCP URL. |
| **Convoy** | Source of truth: feed, seats, `convoy_id`, thread pointers. | A harness binary or a model wrapper. |
| **onboard** | First run after MCP attach: user names installed harnesses; Convoy reports PATH truthfully. | Auto-installed wrappers, invented roster entries, or auto-login. |
| **grok-bot-local** | Neuron host: user PC (WT + logged-in CLIs). | A second source of truth. |
| **grok-bot-cloud** | Neuron host: cloud agent machine (git/headless flows). | Nested Grok Bots or cloned TUI sessions. |

Product wording retires **hop** in favor of **neuron/synapse/thread**.

Do not spawn extra Grok Bot conductors unless explicitly requested. A new conductor needs a distinct thread key or it stomps the same checkout. Vendor resume ids stay on the host that created them.

`glance` includes a `conductor` card (`to: "grok-bot"`). Unknown values remain JSON `null` until a live probe exists.

`roster.present` is the MCP/agent process PATH. Interactive desktop terminals are a different PATH (bash skips `.profile`). Convoy first-run writes `~/.bashrc` so `claude`/`grok`/`codex` resolve in the next shell. Already-open terminals still need `source ~/.bashrc`.

Harness self-identity: `ensure_first_run` installs `neuron-identity` into the seat worktree (`.grok/skills`, `.claude/skills`, `AGENTS.md` pointer). Launched models read `thread.md` / `.convoy/id` and know they are a neuron on that `cvy_id`, not Grok Bot. `context.pack` includes `convoy_id` and `thread_key` from those one-line files (JSON `null` if missing).
