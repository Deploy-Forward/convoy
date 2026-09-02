---
name: convoy
description: Canonical /convoy slash sheet — renders the public Convoy MCP tools 1:1. The MCP tools/list is the source of truth; this skill only renders it.
---

# /convoy — the canonical sheet

Slash maps 1:1 onto the public MCP tools. This sheet was
rendered from live tools/list at **2026-09-02T16:06:52Z**
(deployed serverInfo version `0.1.0`,
which predates the tree's build-stamped versions — treat deployed-vs-tree
drift as expected until the next redeploy). It is a snapshot the moment that
date is old: re-probe `tools/list` before trusting it.

**The single most important fact:** the public MCP process is bound to
**one root** (one thread). `feed` / `context` over the public URL answer for
that thread only. For every other thread, the CLI on its own `--root` is not a
fallback — it is the primary surface.

## Live tools (13, probed 2026-09-02)

| /convoy … | Tool | What it does |
| --- | --- | --- |
| `roster` | `roster` | BYO harness roster: present/wired from the MCP process PATH; usage null when unknown |
| `glance` | `glance` | Read-only usage card: conductor id, overall per-harness meters, by-thread seat chips |
| `onboard` | `onboard` | First run: name the harnesses you already have; truthful PATH checks, wrappers refused |
| `terminals` | `terminals` | Window metadata for the bound thread; pointers only, no PTY dump |
| `context` | `context` | Packed pointers (thread.md, role.md, brief, handoff, worktree, branch, pr) — never file contents |
| `send` | `send` | Headless synapse to a harness; compact card back; refuses limited without waiting |
| `feed` | `feed` | Layer events since ts (default last 24h) — conclusions, not transcripts |
| `bring-up` / `open` | `bring_up`, `open` | Resume seated neurons visibly; dry_run defaults true on the public URL |
| `hide` / `minimize` / `background` | `hide`, aliases | Minimize neuron windows; sessions keep running; never kills |
| `install` | `install` | Opt-in vendor download from allowed hosts only; dry_run defaults true |

## Tree-only (not deployed as of the probe date)

| Verb | Status |
| --- | --- |
| `stamp` | In the tree, absent from the live server. Conductor-only line onto the feed. Per the N-5 write gate it is CLI-on-root regardless of deployment. |
| `note` | Same: tree-only, neuron-side write, CLI-on-root under the gate. |
| `join` / `swap` / `seated` | Seat lifecycle verbs — CLI only by design this increment. |
| `/convoy threads` | Does not exist until multi-thread MCP lands. Anything claiming it is lying. |

## Honesty rules the sheet inherits

Unknown is JSON `null`, never invented. Limited refuses. Dry-run is not live.
The feed records conclusions; reasoning lives in vendor sessions Convoy may
point at and never mirrors.
