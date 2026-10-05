---
name: convoy
install_binding: temporary
trust_scope: install-worktree-only
vendor_prompt_policy: auto-accept-within-scope
description: Canonical /convoy slash sheet — renders the public Convoy MCP tools 1:1. The MCP tools/list is the source of truth; this skill only renders it.
---

# /convoy — the canonical sheet

Slash maps 1:1 onto the public MCP tools. This sheet is rendered from live tools/list and must never hardcode a frozen catalog.

**The single most important fact:** the public MCP process is bound to
**one root** (one thread). `feed` / `context` over the public URL answer for
that thread only. For every other thread, the CLI on its own `--root` is not a
fallback — it is the primary surface.

## Render rules

1. Call `tools/list` on the live MCP endpoint.
2. Render only what the wire returns now (names + descriptions).
3. If a tool is missing on the wire, mark it absent instead of assuming.
4. For write-gated tools, mention `CONVOY_MCP_WRITE_TOOLS` and recommend
   CLI-on-root when the public MCP is read-only.
5. Never copy/paste historical counts ("13 tools", "14 tools") into this file.

On the wire: call `tools/list`. The packaged registry is
`src/convoy/mcp_http.py` (`TOOLS`). A live public process can lag that
registry (`redeploy`) or hide write tools until `CONVOY_MCP_WRITE_TOOLS=1`
(`write-gated`, including `stamp`, `note`, `seat`, `join`, `launch`,
`onboard`, `clone`, `mint`, `repos`, `crew`, `seated`, `consent`,
`await_seated`, `nudge`). Those registered verbs are served on a gated deploy; they
are not absent from the server. Never registered as MCP tools: `init`,
`id`, `bind`, `attach`, `seats`, `swap`, `lead`, `whoami`, `hook` (incl.
`hook note … --as-me`), `close`, `probe`. Render what `tools/list` returns
now; do not invent a catalog count.

## Detect, identify, then send: `panes` and `whoami`

`panes` lists every body of every neuron on the thread from the OS process
table, not only what Convoy launched: per chair `live`, `bodies` (pid, via
`token`, `worktree`, or `cwd`), `duplicate`, plus `unassigned` harness
processes Convoy cannot place (Windows exposes no cwd; a fresh launch there
is placed only if its command line names the worktree or a token).
`whoami` walks YOUR process ancestry to your harness and names your chair
(token, then worktree, then cwd) or returns null with an ask. Author rows as yourself with
`hook note "<text>" --as-me --to <chair>`; it refuses when no chair on this
thread matches your body. Never type into another pane; never resume a chair
that `panes` shows live.

## What a `send` card means

`delivery` is `recorded` (feed only), `queued` (inbox), `native-queued` (native queue), `executed` (a fresh headless run), `refused` or `error`. `delivered` stays false on the card: only the target's own proven token-citing receipt establishes delivery.

To reach an open neuron, use `convoy send --id <neuron-id> "<text>"` (or MCP `send` with the named chair), then wait for that neuron's receipt. A plain addressed `hook note` queues nothing and does not wake the target. Answer a message with `convoy reply <token> "..."` (a note to the sender citing the token, the receipt that counts and clears your pending row; it needs environment, token or pane-host proof of your session), and report results with `convoy report "..."`; never type into its TUI or resume its live session.

## `/convoy --start [<repo>]` (CLI: `convoy start [<repo>]`)

CLI project resolution, not an MCP tool: `convoy start [<path|URL|owner/repo|name>]`. An existing local path needs no cloud read. For a remote target, reuse a matching checkout before cloning; a reused clean, behind-only checkout can be refreshed by one fetch plus a local fast-forward-only merge. Dirty/diverged/unknown state stays with a reason; inspect `pulled` rather than assuming an update.

No argument returns a picker; never auto-pick newest. `--search-root` bounds discovery, `--all` expands worktree choices, `--create` creates a private GitHub repo for an unmatched name; never pass it unless the person asked for a new GitHub repo. Incomplete/offline discovery is unknown, not proof of absence. Read the returned pointer-only start card first. Start opens no pane and does not seat this session; use attach to link it.

## List, attach and detach

Run `convoy list` and show its output verbatim, including skipped roots and unknown values. Default lists usable recent threads; `--all` includes hidden/older usable threads. Never delete skipped roots automatically.

For the person's chosen block, run `convoy attach <cvy_id|exact thread name>`. Map display pick numbers to the block's exact `cvy_` id; never pass a number. Attach proves this running native session, launches nothing, refuses unavailable/conflicting identity and reuses its chair on repeat. Detach before switching threads. Legacy pointer-only catch-up uses `attach --read-only`.

Run `convoy detach [--thread <cvy_id|name>]` to detach the proven calling session. Its rolling handoff, chair, history and pending rows remain. It closes no pane and kills no session. Detached chairs cannot drain/pulse or wake; sends refuse until attach reactivates them.

## Wake service

Wake dispatch is off on a root until `convoy --root <root> wake enable`. Inspect it with `wake status` and opt out with `wake disable`. The supervised MCP origin runs the dispatcher for enabled roots. Its waiter route is dispatcher-managed: the session arms its own background waiter using the command the Stop hook prints, drains its own inbox on wake, acts, writes a proven token-citing receipt and re-arms before stopping. A hook-owned detached waiter cannot wake the session. Unknown routes, faults and held alerts are not delivery proof.

## Finding threads from anywhere: `threads`

Chats launch from project folders. `convoy threads` reads the machine index
(`$CONVOY_HOME/threads.json`, default `~/.convoy/threads.json`): one row per
thread — `convoy_id`, `thread`, `root`, `updated_at` — upserted by every
`init`, `bind`, and `seat`. `present=false` means the root is gone or its id
changed; never treat that row as a thread. Read verbs (`graph`, `threads`,
`resume`, `seats`, `feed`, `context`, `glance`) walk up from a subfolder to
the nearest `.convoy/id`. `graph --html` shows every present thread in its
side panel. The index carries no tokens, but it is not Convoy's only home write.
First run can also prepare `~/.bashrc`, `~/.claude/settings.json`, `~/.claude.json`
and the Codex prompt `~/.codex/prompts/convoy.md` (or `CODEX_HOME/prompts/convoy.md`).
Live hook trust preparation can also write the harness-specific home trust stores,
as named by the first-run card. Do not describe these operations as read-only.

## Rejoining the fray: `graph --neuron <chair>`

Read-only. Returns the chair's current harness/model, its lineage (join /
swap / seated, `pending` until acked), the parties it has talked with, and the
thread pointer (`convoy_id`, `thread`, `path`, `last_row_ts`) to resume from.
Never a token: `resume.available` is a boolean. Every edge is `attested`
(claimed on the bus), never authenticated.

The card also carries `place`: your last contribution, your temporal rank
among the chairs (1 = most recent author), your degree, and who holds lead.
Run it as your post-hook after you write to the bus. To pass lead to an
identified neuron: `lead --to <chair> --as <your chair>` (neuron-authored;
the conductor asks via `stamp`).

## Two-turn consent rail

### Install-time disclosure

Installing this skill creates a temporary, revocable binding for the selected
Convoy worktree. Within that scope, vendor trust prompts (`y/n`, `--trust`, or
the harness equivalent) are auto-accepted by the launch adapter so the user
does not have to shepherd a first-run TUI. The binding is limited to the exact
worktree, can be modified or revoked by the user, and disappears when the
skill is uninstalled. It never grants trust to another folder or unrelated
commands.

Before installation, disclose the exact worktree and that this binding allows
repo-local configuration, hooks, MCP servers, and LSP code to run with the
user's privileges. Never inject keystrokes into a TUI: use a non-interactive
vendor flag when supported (for example Grok `--trust`); if a harness has no
such flag, report `awaiting-user-consent` and require the user to decide.

`join --launch`, `close --seat`, and `nudge --seat` may return
`state=awaiting-user-consent` with a scoped `consent_request`. When that occurs:

1. If the install binding is active and the harness supports a non-interactive
   trust flag, pass it only for the bound worktree.
2. Otherwise show the returned `prompt` verbatim, including the exact chair
   and worktree, and stop for the user's decision.
3. Any explicit one-time close consent still requires a separate scoped receipt;
   pass it only to the pending command's `--consent` option.

`trust-worktree` permits repo-local configuration, hooks, MCP, and LSP code to
run with the user's privileges. `close-chair` terminates that exact managed
harness child and asks its pane host to exit; unsaved TUI input may be lost.
`nudge-pane` SendInput/send-keys/queues into one proven pane; the prompt names
the HWND/title (or tmux target) and the exact keys. Never grant it for a pane
you cannot see. A nudge that lands is `delivery: nudged`, never `delivered`.

Never type `y`, `n`, `Ctrl+D`, or another key into a harness TUI. An unmanaged
legacy pane returns `manual-close-required`; ask the user to close it. A vendor
gate is `awaiting-user-consent`, not `seated`, and must remain visible until the
user decides.

## Honesty rules the sheet inherits

Unknown is JSON `null`, never invented. Limited refuses. Dry-run is not live.
The feed records conclusions; reasoning lives in vendor sessions Convoy may
point at and never mirrors.
