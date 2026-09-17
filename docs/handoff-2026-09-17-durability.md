# Handoff to Fable, Convoy side, 2026-09-17: durability

Read this before any Convoy work. It rebases the plan on the first real multi-chair run
under load, conducted from the platform-side Fable session on 2026-09-16/17.

## What the live run proved

- The platform thread: one `start`, one `crew`
  that minted five worktrees on their own branches and opened five panes in one window.
  About twenty sends, zero lost, every one acked by a note citing the token. Chairs
  coordinated peer to peer on the feed without the lead (Lane C found Lane B's validator
  bug; B fixed it in 37 minutes). A Codex chair, Astra, delivered three reproduced defect
  lists and was escalated by Marco, through a send, to merge and deploy production.
- Six relaunches: the Fable chair three times, Astra three times, the Grok chairs never.
  Causes were concrete: one bad model id, the Claude chair's background `inbox --wait`
  killed twice under memory pressure, the Codex chair's native-queue drain never firing.
  `relaunch` itself worked every time in under a minute.
- The delegation contract held. The operational layer, liveness, layout and validation, is
  where Convoy fails, and it fails silently.

## The eight defects observed, plus one environmental

1. `start` does not accept `owner/repo` (spec W1).
2. The boot prompt points at `thread.md`, which a fresh `bind` never writes.
3. No model-id validation at seat or launch; a pane that dies at boot leaves no row.
4. `await_seated` on MCP versus `await-seated` on the CLI.
5. Thread resolution from cwd: `--root` is required from any other directory.
6. `relaunch` loses the 2x2 tile layout.
7. Stale Grok usage rows.
8. A chair's reachability depends on `inbox --wait` surviving in its pane.
9. Memory pressure from stray harness processes: Codex leaks one copy of every MCP server
   per session (twelve copies each observed on 2026-09-14). One config edit, Marco's call.

## Why chats go stale, precisely

A seat hears a send only through a wake path inside its own harness. For Claude that is a
background `convoy inbox --wait` (two-second poll, default timeout one hour) spawned by the
chair's own turn, whose completion wakes the session. For Codex it is the native queue plus
a PostToolUse hook that is unverified live. For Grok it is the Stop hook refusing to stop
while rows are pending. When the waiter dies, the seat is deaf, nothing on the feed says so,
`neurons` fades it to quiet only after ninety minutes, and recovery is a human noticing and
running `relaunch`. Death is invisible, relaunch is manual, and the record cannot tell idle
from dead.

## Durability design, in build order

- **D1. Liveness is recorded, never inferred.** `inbox --wait` writes
  `.convoy/wait/<chair>.json` with pid, started, expires and incarnation on start and
  removes it on exit. `neurons`, `rail` and `roster` report `reachable` as one of
  `waiter-alive | waiter-dead | no-waiter | unknown` from that file plus pid liveness.
  Red test: kill the waiter, `neurons` says dead within one poll.
- **D2. Short waits, re-armed at every turn end.** Default timeout ten minutes, not one
  hour. The Stop hook for every harness, through the hooks module, re-arms the wait when
  rows are pending or no waiter is alive. Claude's Stop hook prints `{}` today; it must
  return the same block-with-reason Grok's does when rows are pending. A dead waiter is
  then noticed within one window instead of an hour.
- **D3. Death is a row.** `kind=unreachable {chair, since, evidence}` when rows are pending
  and no waiter is alive past the window; `kind=boot-failed {chair, argv, exit, stderr
  tail}` when a launched pane exits before its seated ack. `delegation` status can then say
  `stalled` with a cause and the board's `workState` is honest.
- **D4. Supervised relaunch as policy.** On a gated deploy, `unreachable` past a threshold
  triggers `relaunch --seat S` by the origin, a spawn on the machine, never over the public
  MCP, with the relaunch row citing the `unreachable` row it answers. Layout survives
  (defect 6) because `crew` records the window and tile plan in `.convoy/layout.json` and
  `relaunch` reads it.
- **D5. Incarnation.** Every launch or relaunch increments `incarnation` on the seat row.
  The boot token carries it, hooks stamp it on every row the chair writes, the delegation
  card and every report carry it. Any row then says which life of the chair wrote it.
- **D6. Vendor session continuity.** Seat rows carry the harness session id (W0).
  `relaunch` records `resumed: true|false` and the new id, so the Ledger join either
  survives a relaunch or knows it broke.

## How we know a thread relaunched, accurately

Today: a `kind=relaunch` row naming the chairs and the time, followed per chair by a
`seated` row citing the boot token the relaunch queued; connected is counted only from
acks after the relaunch timestamp. That is accurate for "it came back". It cannot say why
there is no death row, whether the vendor session continued, or which rows belong to
which life. D3, D5 and D6 close those three. The Ledger sees a relaunch as a report on the
same delegation carrying a higher incarnation.

## Order, merged with the existing map

Move 1, the record, stays first: D3, D5 and D6 are rows on it. Then the hooks module,
move 2, carrying D1 and D2. Then D4 with the policy verb, step 4 of the rebase. Defects 1
through 5 are small and ride W1, the roots module and the verb registry; 6 rides D4; 7
rides the usage cluster; 8 is D1 through D4. The platform-side session has a Plan agent
drafting `docs/convoy-fix-plan-2026-09-17.md` in the platform repo with the same inputs.
Read it before building. If its order conflicts, adopt it and say why on the feed.

## The fold question, flagged once

Marco has said twice that Convoy should fold into "our repository", by user, traceable to
board actions. Two readings: move Convoy's code into the private platform, which reverses
the open/closed ruling and the boundary tests, or fold the fixes plus pairing and the
tenant record into the public Convoy, with platform's origin registry as the tracing spine.
The tracing he wants is the same under both: org, user, origin, thread, chair, incarnation,
delegation token, on every row and every board action. My recommendation stays the second.
The ruling is his, and it is decision A in the platform-side plan.

## Still open on Marco

The three restore lines for the edge (issue #107). The ruling on PR #106, which the
platform lanes have partly implemented ahead of it. The Codex MCP scoping edit. Decision A.
