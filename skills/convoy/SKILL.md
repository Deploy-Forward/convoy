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
4. For write tools (`stamp`, `note`), mention the gate behavior and recommend
   CLI-on-root when the public MCP is read-only.
5. Never copy/paste historical counts ("13 tools", "14 tools") into this file.

Tree-only CLI verbs (`join` / `swap` / `seated`, plus `choices` / `launch` /
`close` / `consent`, plus `graph [--neuron S]`) are absent from the public MCP
until deployed. Render them as absent on the wire; do not invent a catalog
count.

## What a `send` card means

`delivery` on the card is `recorded` (feed row only, nothing reached a
neuron), `executed` (a fresh headless session ran it, not the open pane), or
`refused`. `delivered` is always false on a card: only an ack row authored by
the target proves delivery. To reach an OPEN neuron, write an addressed row
(`note --to <chair>`) and wait for its ack; never type into its TUI, never
resume its session.

## Finding threads from anywhere: `threads`

Chats launch from project folders. `convoy threads` reads the machine index
(`$CONVOY_HOME/threads.json`, default `~/.convoy/threads.json`): one row per
thread — `convoy_id`, `thread`, `root`, `updated_at` — upserted by every
`init`, `bind`, and `seat`. `present=false` means the root is gone or its id
changed; never treat that row as a thread. Read verbs (`graph`, `threads`,
`resume`, `seats`, `feed`, `context`, `glance`) walk up from a subfolder to
the nearest `.convoy/id`. `graph --html` shows every present thread in its
side panel. The index is the one user-global file Convoy writes; it carries
no tokens.

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

`join --launch` and `close --seat` may return
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

Never type `y`, `n`, `Ctrl+D`, or another key into a harness TUI. An unmanaged
legacy pane returns `manual-close-required`; ask the user to close it. A vendor
gate is `awaiting-user-consent`, not `seated`, and must remain visible until the
user decides.

## Honesty rules the sheet inherits

Unknown is JSON `null`, never invented. Limited refuses. Dry-run is not live.
The feed records conclusions; reasoning lives in vendor sessions Convoy may
point at and never mirrors.
