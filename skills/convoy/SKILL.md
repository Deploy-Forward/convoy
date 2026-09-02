---
name: convoy
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
`close` / `consent`) are absent from the public MCP until deployed. Render them
as absent on the wire; do not invent a catalog count.

## Two-turn consent rail

### Install-time disclosure

Installing this skill does **not** grant a harness trust, `-y` approval, or
permission to execute repo-local code. Before any install or launch flow that
offers folder trust, disclose the exact worktree and that approval may allow
repo-local configuration, hooks, MCP servers, and LSP code to run with the
user's privileges. Treat an explicit opt-in to that exact folder as a separate
consent action; never infer it from skill installation, convoy membership, or a
previous approval for another folder.

`join --launch` and `close --seat` may return
`state=awaiting-user-consent` with a scoped `consent_request`. When that occurs:

1. Show the returned `prompt` to the user verbatim, including the exact chair
   and worktree.
2. Stop. Never run `consent --grant` in the same turn that created the request.
3. Only after the user's next message explicitly approves that exact action,
   run `convoy consent --grant <request_id>`.
4. Pass the returned one-time value only to the pending command's `--consent`
   option. Never reuse it or apply it to another chair/worktree/action.

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
