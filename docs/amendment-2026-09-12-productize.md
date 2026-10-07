# Amendment 2026-09-12: productize Convoy

> **Superseded 2026-10: convoy.bot/mcp is retired.** Convoy 1.3.2 removed the hosted endpoint, the tunnel task an install registered, and the `CONVOY_MCP_WRITE_TOOLS` flag with its `legacy-flag` write gate. Convoy's MCP runs on your machine at `http://127.0.0.1:8788/mcp` (`convoy mcp`), answers loopback requests only, and writes need a conductor bearer. This document is kept as dated history; its references to the tunnel, the public origin and the flag describe the past.

An amendment to Convoy's earlier architecture decisions. It amends; it does not
rewrite. Where this file and an earlier decision disagree, the earlier decision's
objects stand and this file records the phase that changes them.

## What the live certification showed

During the live certification four real seats launched with their declared model
and effort, acked with their own tokens, committed on their lanes, and replied on the
thread; the public MCP served the merged build to grok-bot. Everything that broke
during that period broke for one reason: the machine was the product. One user, one
root per origin, one tunnel, supervisors registered by hand, secrets in a hand-made
folder outside Convoy, a stranger named `convoy` on PATH, the launcher's shell leaking into panes.

| layer | today | replicable |
|---|---|---|
| `.convoy/` record and its rules | code, tested, tenant-neutral | yes |
| seat launch: hooks, boot prompt, model and effort on argv | code, tested, Windows only | one OS |
| widget | reads local disk | one machine |
| MCP origin | one process, one root, no auth, global write flag | no |
| tunnel, supervisors, PATH, tokens | registered by hand | until move 1 |
| conductor | contract shipped (PR #95); identity is a string constant | half |

## Two invariants held through every phase

1. Every number is vendor-native and every claim carries its source. Unknown is null,
   never zero. Scale pressure pushes toward derived numbers; the answer is no.
2. The record is one JSONL file per thread until a second writer on a second machine
   exists. A database arrives when two origins must agree, not before.

## The five moves, one PR-sized seam each

1. **Install is a verb.** `convoy install --local` plans and, with `--live --opt-in`,
   registers the origin task and the tunnel task, checks that `convoy` on PATH is
   Convoy, and proves each by reading it back. `--verify` re-reads any time. The tunnel
   wrapper is Convoy's, under `CONVOY_HOME`, and reads the token from a file at run
   time; the token is never in a task, a card, or a log. Windows today; systemd and
   launchd are the named missing adapters. Landed with this amendment.
2. **Identity on the wire.** A conductor bearer minted by `convoy conductor mint` and
   checked at the origin. `from` is set from the bearer and never from an argument.
   The global `CONVOY_MCP_WRITE_TOOLS` flag is retired. Precondition for anyone but the
   machine's owner touching a thread. This is step 3 of the grok-bot rebase. Landed
   2026-09-12: `convoy conductor mint | list | revoke`, `Authorization: Bearer` checked
   on every request (401 when wrong or revoked), `principal: {bearer: id}` on stamps,
   `roster.conductor.write_gate` in `bearer | legacy-flag | closed`. The flag is still
   honored in code for loopback-only deploys and named `legacy-flag` when it is; the
   public origin retires it by unsetting the variable and restarting.
3. **Many roots per origin.** Every call carries a thread id; the origin resolves the
   root from the thread index instead of a startup flag. One process serves every
   thread on the machine. Landed 2026-09-14: every tool schema carries `thread` and
   `convoy_id`; `threads` lists what the origin can serve and which thread, if any, it
   is pinned to; a call without a thread on an unpinned origin is refused with the list;
   a routed card answers with the `thread` and `root` it touched. `install --local`
   registers an unpinned origin by default; `--bound` pins `--root`. Nothing is pointed.
4. **A tenant is a record.** `tenants.jsonl` maps a bearer to the threads it may see and
   write. Two conductors on one machine, or two people, without a shared flag. The
   widget and `roster` read the same record.
5. **The desktop connector is one adapter.** Everything that touches the machine
   already sits behind `bringup`, `panes`, and `pane_env`. Name the interface, add a
   tmux implementation for Linux and macOS, and the origin plus conductor become
   cloud-hostable while launch stays local. This is the destination.

## Realign the conductor by measurement

Grok-bot is the conductor by choice, not by measurement. Step 4 of the rebase, quota policy
as code, is the first conductor decision Convoy can test: a threshold maps to exactly
three verbs, warn on the feed, stop assigning to that harness, relaunch the seat on
another harness. Run it with grok-bot and with a Claude conductor on the same thread for
one week, compare stamps to outcomes, then decide who conducts. The conductor contract
is written for any conductor for this reason.

## Order and ownership

Move 1 first: it is what broke most often. Then the rebase steps 3, 4, 5
(bearer, policy, reachability), then moves 3 through 5. The conductor owns nothing in
this list except reading its contract and calling the policy verb when it lands.
