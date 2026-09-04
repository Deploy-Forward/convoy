# Convoy

Convoy is shared project memory for Grok Bot: attach one MCP endpoint, route work to your existing CLIs, and keep every neuron grounded in one durable thread state.

Public MCP remains one root: `https://convoy.bot/mcp`. A named thread is a `--root` binding, not a second MCP URL.

## Install

Python >= 3.11, standard library only (no runtime dependencies).

```bash
git clone https://github.com/Deploy-Forward/convoy.git
cd convoy
python -m pip install .
convoy --help
```

Alternative: `pipx install .` (not verified on Windows in this pass).

The `convoy` console script and `python -m convoy` both work only after
install. To run from a checkout without installing, put `src` on the path:
`PYTHONPATH=src python test/run.py` on bash, or
`$env:PYTHONPATH='src'; python test/run.py` in PowerShell.

### Receiving messages needs a command that resolves

Neurons receive through a harness hook, and a hook runs in its own shell that
inherits nothing from yours. Convoy therefore **probes** its own command line
before writing any hook file, and refuses to write one that would not run.
Check what it picked:

```bash
convoy --root <thread-root> skills --worktree <worktree>
```

The card's `hooks.resolved_via` is one of `console-script` (the installed
`convoy` is on PATH — the best case), `interpreter` (this Python can
`-m convoy`), `interpreter+src` (no install: the command carries the
checkout's `src` with it), or `kept-existing` (a hook already there still
works and was left alone). If nothing resolves, the card carries an install
hint and **no hook file is written**; install the console script and re-run.
The same command is the repair when a hook goes stale: it prunes Convoy's own
dead entries and leaves your own hooks untouched.

## CLI reference

One line per verb; flags shown are the ones you will reach for (see
`convoy <verb> --help` for the full set). Every verb accepts a global
`--root <thread-root>` before the verb name.

Read (no writes to thread state):

- `threads` — every Convoy thread this machine knows.
- `panes` — every body of every neuron on this thread, from the OS process table; never a token.
- `whoami` — which chair is this process? Walks process ancestry to the harness.
- `graph [--neuron <chair>] [--html [--out <file>]]` — read-only ontology of the thread.
- `seats [--convoy-id <id>]` — seat rows.
- `feed --since <ts>` — events since a timestamp.
- `context [--instance-id <chair>]` — pointer pack for a neuron.
- `glance [--thread <name>] [--tray]` — one-screen status.
- `resume --neuron <chair>` — dry: prints native argv + cwd, spawns nothing.
- `choices` — installed harnesses, known worktrees, chairs, terminal adapter; no resume tokens.
- `probe --to <harness>`, `id`, `terminals`.

Write (thread state):

- `init` — create the thread layer at `--root`.
- `bind --thread <name>` — bind this root to a named thread.
- `onboard --to <harness> [--to ...] [--thread <name>] [--checkout-root <path|git-url>] [--github yes|no]` — name installed harnesses and bind; a URL is cloned once under `$CONVOY_HOME/checkouts/<owner>/<repo>` (`.convoy/` and `thread.md` go into that clone's `.git/info/exclude`).
- `seat --to <harness> --session-id <chair> [--worktree <path>] [--model M] [--resume <vendor-id>] [--title T] [--effort E]` — register a seated neuron.
- `join --to <harness> [--worktree <path>] [--title T] [--as <chair>] [--launch] [--consent <id>]` — register one fresh chair.
- `crew --seat <harness>[,model=M][,effort=E][,where=local|cloud][,title=T] [--seat ...] [--checkout <path>] [--launch]` — N neurons at once: validates every seat first, mints one worktree per local seat, joins every chair with a boot prompt, and (with `--launch`) brings them up in ONE window. Launched is not connected: the card's `seated` snapshot says `pending`.
- `await-seated --seat <chair> [--seat ...] [--timeout <s>]` — observe the acks: per chair `connected` (its own `seated` row cites the minted token) | `pending` | `stale`, with the seconds waited.
- `swap --seat <chair> --to <harness> --handoff <.ola/*handoff*> --as <chair>` — replace the occupant, keep the chair.
- `seated --seat <chair> --token <token>` — proof-of-life echo from the new occupant.
- `lead --to <chair> --as <you>` — pass lead to a chair.
- `hook note "<text>" [--as-me] --to <chair>` — leave a note for a chair (or `grok-bot`).
- `stamp "<summary>" [--agent A] [--model M] [--effort E] [--transcript <pointer>]` — conductor stamp.
- `send --to <harness> "<body>" [--live] [--dry-run] [--instance-id <chair>]` — synapse; default runner records a feed row (`delivery: recorded`); `--live` runs a fresh headless vendor session (`executed`); a named live seat queues (`delivery: queued`, `delivered: false`).
- `inbox [--seat <chair>] [--drain | --hook-pretooluse]` — list or drain the live-seat inbox. The hook command is always `convoy inbox --hook-pretooluse` (never a baked interpreter path).
- `install --to <harness> --opt-in [--live]` — cataloged installer; dry-run by default.

Launch / panes:

- `choices` — see above; run it first.
- `launch --seat <chair> [--dry-run] [--consent <id>]` — split one already-joined fresh chair into the active pane host.
- `consent --grant <request-id>` — grant a prior consent request after the user explicitly approves it.
- `close --seat <chair> [--consent <id>]` — request closure of one Convoy-managed pane.
- `bring-up` / `open [--thread <name>] [--dry-run]` — bulk show of seated neurons in one new terminal window.
- `hide` / `minimize` / `background [--dry-run]` — bulk hide.
- `resume --neuron <chair> --go` — spawn once in the chair's worktree; refuses when a live body holds the chair.

MCP:

- `mcp [--root <thread-root>] [--host 127.0.0.1] [--port 8788]` — serve the MCP endpoint for one root.

### Run your own MCP

```bash
convoy mcp --root <thread-root> --port 8788
```

Then attach `http://127.0.0.1:8788/mcp` in your MCP client. Write tools are
off by default on the RPC layer: set `CONVOY_MCP_WRITE_TOOLS=1` on a
gated/loopback deploy to expose `stamp`, `note`, `join`, `seat`, `launch`,
`crew`, `seated`, `consent`, `await_seated`, `onboard`, `clone`, `mint`,
`repos`, `resume` with `go=true`, and `inbox` with `drain=true`. An ungated
public `tools/list` hides the write tools rather than
listing and refusing them, so a listed verb is a promise. Reads (`choices`,
`neurons`, `inbox` pending, `graph`) stay public, and a public inbox
read never echoes the row token. `repos` wraps `gh repo list` on the MCP
process PATH (name, url, private, updated_at; gh absent is an install hint);
it lists the gh login on the MCP host, the conductor's account, which is why
it sits behind the gate rather than handing that inventory to strangers.
`clone` puts a URL under `$CONVOY_HOME/checkouts/<owner>/<repo>`; `mint`
derives one worktree per seat from that checkout as `<checkout>-wt-<name>`
on branch `convoy/<name>`, so nobody hand-makes worktrees for N neurons. `crew`
does the whole walk for N seats (validate, mint, join each with a boot prompt,
one window) and `await_seated` reads the acks back, so "they all connected" is
observed, never assumed. `convoy preflight` tells you which of the wizard's
verbs a live `tools/list` is missing and why.
The public `https://convoy.bot/mcp` is bound to one root; a different thread
means running your own server with your own `--root`.

## Names you will see

- **Grok Bot** — the xAI desktop conductor chat that attaches the MCP; not a neuron.
- **ola-brain** — a private predecessor wrapper; refused by `install`, not needed.
- **Deploy-Forward/platform** — a closed sibling repo; not needed to run this repo.
- **Aether** — an internal demo host; not needed.

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

### Supported neurons (code-true contract)

`grok`, `claude`, `codex`, `cursor-agent`, and `agy` have a cataloged installer
(`convoy install --to`); `hermes` and `pi` are BYO-only (`install` refuses them)
and their direct-id resume is unverified.

| Harness | `onboard` / `roster` id | `resume_argv` shape | `ensure_first_run` behavior | `send --live` behavior |
| --- | --- | --- | --- | --- |
| `grok` | `grok` | `grok -m <model?> --agent <path?> --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes Convoy-owned `--agent` file; writes project PreToolUse hook (`convoy inbox --hook-pretooluse`). | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `claude` | `claude` | `claude --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes project `.claude/settings.json` (ungate + PreToolUse/UserPromptSubmit inbox hooks), merges user `~/.claude/settings.json` skip key, and writes `~/.claude.json` trust project keys. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `codex` | `codex` | `codex resume <vendor-id?>` (**not** `--resume`) | Writes PATH ungate block; installs `neuron-identity`. No Claude permission-ungate writes. | Native CLI on PATH. Named live seats queue; may `codex queue` (`delivery: native-queued`). |
| `cursor-agent` | `cursor-agent` | `cursor-agent --resume <vendor-id?>` | Writes PATH ungate block; installs `neuron-identity`; writes Grok/Claude inbox hook files (swap-safe). Drain via `convoy inbox --drain` (no vendor hook proven). | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `agy` | `agy` | `agy --conversation <vendor-id?>` (live `--help` 2026-09-01: no `--resume`) | Writes PATH ungate block; installs `neuron-identity`; inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `hermes` | `hermes` | `hermes --resume <vendor-id?>` (live `--help` 2026-09-01) | Writes PATH ungate block; installs `neuron-identity`; inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `pi` | `pi` | `pi --resume <vendor-id?>` (flag verified live; `--resume` opens a session picker — direct-id resume unverified) | Writes PATH ungate block; installs `neuron-identity`; inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |

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
4. Use `send` for synapses. A send that names a live seat **queues** the body
   (`delivery: queued`, `delivered: false`); it does not type into the TUI and
   does not spawn a second `--resume`. Codex may use `codex queue`. Drain with
   `convoy inbox --drain` or the project hook `convoy inbox --hook-pretooluse`
   (Grok PreToolUse, Claude PreToolUse + UserPromptSubmit). Hook files never
   bake an absolute interpreter path.
5. Use `bring_up` / `open` only when you want visible interactive TUIs for seated neurons.

## End-to-end example

```bash
# (after `python -m pip install .`, see Install)
# 1) Name installed harnesses and bind this root to one thread
convoy onboard --to grok --to claude --to codex --thread demo

# 2) Register seated neurons (session key + optional vendor resume token)
convoy seat --to grok --session-id seat-grok --worktree ../wt-grok --model gpt-5.6-sol --resume vendor-grok-uuid
convoy seat --to codex --session-id seat-codex --worktree ../wt-codex --resume vendor-codex-uuid

# 3) Dry-run bring-up shows native argv (Codex uses "resume" subcommand)
convoy bring-up --dry-run

# 4) Headless synapse (safe default)
convoy send --to claude "Summarize open payment retry bugs and propose a fix plan."

# 5) Optional live headless run in a fresh native session (no resume token)
convoy send --to codex --live "Draft unit tests for the retry planner."
```

Development: `PYTHONPATH=src python test/run.py` (discovers `test/demo/*_test.py`).  
License: MIT.

## Cloudflare split hosting (static site + MCP proxy)

This repo includes a Cloudflare Worker config that serves the landing page/static files at the edge while preserving the existing Python MCP transport.

- Config: `wrangler.jsonc`
- Worker entry: `workers-site.mjs`
- Static assets directory: `src/convoy/site`

Routing behavior:

- `/mcp` and `/mcp/*` are proxied byte-for-byte to `MCP_ORIGIN` (the current Python MCP origin).
- all other paths are served from Worker static assets (`env.ASSETS.fetch(request)`).

Exact operator runbook (tree placeholder vs live tunnel origin, public vs
gated `tools/list`, what a remote agent cannot restart): [`docs/redeploy.md`](docs/redeploy.md).

E2E DoD outline (plugin symlink → Gate 0 → GitHub → choices → N seats / C8 →
`cvy_*` → `bring_up`, GREEN/RED, no `wt` on Linux agents): [`docs/e2e-harness.md`](docs/e2e-harness.md).

Marketplace submit checklist for `plugin/convoy` against
https://cursor.com/marketplace/publish: [`docs/marketplace-submit.md`](docs/marketplace-submit.md).

xAI / Grok Build catalog entry (remote url + sha + `plugin/convoy`):
[`docs/xai-plugin-marketplace.md`](docs/xai-plugin-marketplace.md).

Deploy steps (from an authenticated environment):

1. Do **not** treat `wrangler.jsonc`'s `MCP_ORIGIN` (`https://mcp-origin.example`) as live. Confirm the Worker binding and the tunnel ingress (`docs/redeploy.md`).
2. Restart the Python origin on `127.0.0.1:8788` **without** `CONVOY_MCP_WRITE_TOOLS` for public. A Worker deploy is not what picks up new tools.
3. If the Worker proxy itself changed: `wrangler deploy --keep-vars` so a local placeholder cannot clobber the live binding. Route `convoy.bot/*` is already attached.

This repo does not claim a live origin restart happened just because these files exist.
