# Canonical names

Grok Bot is a project manager for repositories (and thus projects). Convoy is the singular source of truth any agent can tap. Grok Bot orchestrates.

| Term | Means | Does not mean |
| --- | --- | --- |
| **Grok Bot** | Conductor. One chat, own memory. Chip-less. Orchestrates hops. | A hop. A window. A grok CLI session. |
| **hop** | BYO harness session: `grok`, `claude`, or `codex` CLI. | A new Grok Bot. |
| **Convoy** | Source of truth: feed, seats, `convoy_id`. Any agent rehydrates from it. | A harness. A conductor. |
| **synapse** | One hop: Convoy executes one BYO harness CLI on one instance/meter and gets a compact card back. | Ownership of another synapse's session, branch, or the Grok Bot main window. |
| **hop talk** | Cross-harness talk goes through Convoy `send` + `feed` on one `convoy_id`. | Herdr PTY paste bus. CNVS canvas chat flow. |
| **onboard** | First run after MCP attach: the human names harnesses they already have, and Convoy reports PATH truthfully. | Convoy inventing a roster, auto-installing wrappers, or auto-login. |
| **thread** | One Convoy thread per Grok Bot conductor. Hops on that thread share it. | One thread per hop. |
| **grok-bot-local** | Hop host: the user's PC (Windows Terminal, their logged-in CLIs). | A second source of truth. |
| **grok-bot-cloud** | Hop host: Grok Bot's computer (git, headless hops, no WT). | Nested Grok Bots. A cloned TUI `--resume`. |

Do not spawn extra Grok Bot agents unless the user explicitly asks. A new conductor needs its own Convoy thread key or it stomps the same checkout. Vendor `--resume` stays on the host that created it. Git history is what travels.

`glance` includes a `conductor` card (`to: "grok-bot"`) as the Grok Bot weekly usage identifier; OSS leaves unknown values as JSON `null` until a live probe exists.

`roster.present` is the MCP/agent process PATH. Interactive desktop terminals are a different PATH (bash skips `.profile`). Convoy first-run writes `~/.bashrc` so `claude`/`grok`/`codex` resolve in the next shell. Already-open terminals still need `source ~/.bashrc`.
