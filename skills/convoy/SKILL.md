---
name: convoy
description: Canonical /convoy slash sheet — renders the public Convoy MCP tools 1:1. The MCP tools/list is the source of truth; this skill only renders it.
---

# /convoy — the canonical sheet

Slash maps 1:1 onto the public MCP tools. This sheet is rendered from live
tools/list and must never hardcode a frozen catalog.

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

## Honesty rules the sheet inherits

Unknown is JSON `null`, never invented. Limited refuses. Dry-run is not live.
The feed records conclusions; reasoning lives in vendor sessions Convoy may
point at and never mirrors.
