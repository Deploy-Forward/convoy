# Worklanes and Convoy: card to neuron, and back

Draft for Marco's ruling, 2026-09-15. Amends nothing yet; once locked it becomes phase
6 of the 2026-09-12 productize amendment and the "Delegation" section of the conductor
contract.

## The boundary, in one table

| owns | Worklanes, on app.deployforward (The Ledger) | Convoy |
|---|---|---|
| the work item | card: lane, links to Projects and Repositories, labels, assignees, activity | nothing; Convoy never stores lane or label state |
| cost | est. spend, tokens, sessions at project, repo and builder grain | vendor-native usage per chair, null when unknown |
| execution | nothing; it asks | neuron lifecycle: thread, seat, lane (worktree and branch), send, record, resume |
| the join key | card id and its repo links | thread key, which for a git-tied thread is `owner/repo` |
| authority on "how to delegate" | reads `/convoy` | this document and the conductor contract |

Two invariants follow. The `.convoy/` record is bus state and never board state: a card
id may appear on Convoy rows as a pointer, and lane changes go through the Ledger API by
whoever conducts, never by Convoy. And Convoy never invents a path: a delegation names a
repository, Convoy resolves the checkout, and the card gets back the thread and lane it
actually used.

## What a delegation is

One call, not a recipe. Today the conductor composes `start`, `join`, `launch` and
`send` by hand, and that is where the invented paths and the wrong roots came from.
Convoy exposes one deep verb:

```
delegate {
  repo:      "Deploy-Forward/convoy"            # required; the card's repo link, canonical owner/repo
  card:      {id, url}                          # required; a pointer, never card state
  harness:   "codex" | "claude" | ...           # required; from the card's harness label or the caller's choice
  model, effort:                                # optional; refused with the harness's own words when it cannot take them
  brief:     "<the ask>"                        # required; becomes .convoy/brief.md for the lane and the body of the send
  reuse:     true                               # default: seat an idle chair of that harness on that thread if one exists
}
```

What it does, in order, each step already a Convoy verb: resolve the thread for `repo`
(start it from the URL when no thread exists on this machine, attach when it does);
seat a chair of that harness on a lane, or reuse an idle one; write the brief; send it
with the card pointer; return the delegation card:

```
{ ok, delegation: <token>, thread, convoy_id, repo, root,
  neuron: {id, session_id, harness, model, effort_applied, lane: {worktree, branch}},
  machine, delivery: "queued", delivered: false, card: {id, url} }
```

`delivered` stays false on the card. It is true only when the chair's own note cites the
delegation token, exactly as for `send`. Gated by the bearer like every write.

## What comes back: status, derived, never declared

`delegation {token}` answers from the record alone, in this order of evidence:

| state | evidence on the record |
|---|---|
| `queued` | the send's inbox row is pending; no ledger row since |
| `received` | the chair's note cites the token |
| `working` | ledger rows from that chair since the send (tool calls, files touched) |
| `progressing` | heartbeat rows with a sha newer than the one at the send; commit rows |
| `stalled` | last ledger row older than the policy window; no heartbeat since |
| `done` | a task-end heartbeat with `push_status`, branch and, when there is one, the PR |
| `refused` | the send was refused; the card names why |

This is the `send_status` verb the conductor contract lists as not built. It depends on
move 1 of the review: git state on every automatic heartbeat, commit rows stamped from
the sha diff, and the per-tool-call ledger. Without those, `working` and `progressing`
cannot be told from silence.

The Ledger side consumes this by polling or by a webhook adapter (`CONVOY_WEBHOOK_URL`,
one POST per state change, same card shape). Pull first; push is an adapter added when a
second consumer exists.

## Progress versus delegate is the caller's decision, with Convoy's signals

Convoy does not read cards. The rule the conductor applies lives in Worklanes:

- Progress only: lane change, comment, reassign, wait on a human. No Convoy call.
- Delegate: lane is To-do or Doing, a repo link is present and canonical, and a
  `needs-agent` or `harness:<id>` label is set. Then `delegate`.

Convoy contributes three signals that make the decision honest: `neurons --all` (who is
already seated on that repo's thread and whether they are live), `rail.usage` (vendor
quota per harness, null when unknown), and the policy verb from step 4 of the rebase,
which `delegate` consults before seating: a harness under its threshold is refused with
the reason, so "launch another neuron" cannot be the answer to "this is burning".

Spend context is the Ledger's. Convoy rows carry the card pointer and the repo, which is
what lets the Ledger attach est. spend to a delegation after the fact.

## Stamps on the card

Every Convoy row that a webhook worker mirrors to card activity carries: `harness`,
`session_id` (the chair), `neuron` (the short id), `thread`, `repo`, `machine`, and
`card`. Organization and user come from the bearer's tenant record (move 4), not from
the row. Today rows carry harness, chair and thread; `repo`, `machine` and `card` are
this spec.

## What Worklanes owes Convoy

- A canonical repo link on every delegable card: `owner/repo` or the https URL that
  resolves to it. A card with a project but no repo cannot be delegated and the refusal
  says so.
- The label vocabulary as `delegate` arguments: `needs-agent`, `harness:<id>`,
  `model:<id>`, `effort:<key>`. Convoy validates them against the harness contract and
  refuses with the harness's own words.
- A bearer for whatever calls `delegate`. Grok Bot uses its conductor bearer; a Worklanes
  webhook worker mints its own, and the tenant record maps it to the repos it may touch.
- A consumer of `delegation` status that moves the lane. Convoy never moves a lane.

## PR map, after move 1

| PR | what | test that goes red first |
|---|---|---|
| W1 | thread key for a git-tied thread is `owner/repo`; `threads` reports `repo`; `start <url>` excludes `.convoy/` from the clone's git | `start` on a URL yields thread `owner/repo` and a clone whose `git status` never shows the record |
| W2 | `delegate` verb, CLI and MCP, gated; card pointer and repo on the send, the brief, the seat | one call on a fresh machine index ends with a seated chair, a pending inbox row citing the card, and a delegation card naming the real worktree |
| W3 | `delegation {token}` status, derived from ledger, heartbeat, commit and note rows | a fixture record for each state answers that state and no other |
| W4 | `delegate` consults the policy verb; a Worklanes bearer with a tenant record scoped to repos | a harness under threshold is refused with the reason; a bearer outside its repos is refused by name |
| W5 | webhook adapter: one POST per state change, off by default | a fake receiver sees the same card the pull returns |
| W6 | contract and CONVOY_SOT gain the Delegation section; the `/convoy` reading list in Worklanes points at them | the contract test pins the section |

Order of everything: move 1 of the review (the record), then W1 and W2, then W3, then
the policy verb and W4 together, then W5 and W6. Moves 2 through 6 of the review
interleave where they unblock a W step; the verb registry lands before W2 if it is ready,
so `delegate` is declared once.

## Not in this spec

Card state in Convoy. Lane moves by Convoy. Spend computed by Convoy. A second database.
Any of these arrives only when two consumers need it and the record cannot answer.

## Reconciliation with the Ledger-side map, 2026-09-15

A second map was written from the Ledger side (deploy-forward-canonical, main) the same
day. The two agree on the boundary, on five-valued delivery, on the record never being
copied, on relational shape over a Firestore store behind one seam, and on card text
being data. What follows is only where they differ or where one saw what the other did
not.

**The Ledger map read a checkout 320 commits behind platform origin/main.** It did not
see `packages/convoy-mcp`, `remote-contracts`, `remote-orchestration`,
`services/session-relay`, `apps/desktop-agent`, or `functions/src/remoteCommandPlane.ts`:
a second, platform-native Convoy with `thread_` ids, owned by an account, addressed to
Grok Bot over stdio, none of it deployed and no lane past review. Both maps' plans put
the board and its API in the Ledger and delegation in Convoy, which is only consistent
if that platform lane is retired or re-pointed at `convoy.bot`. That is the one ruling
that remains, and both maps already assume its answer.

**CardThreadLink needs the machine.** The Ledger map keys the link `cardId + uid` and
carries `convoyId`, `sendToken`, `delivered`. A user with two machines has two threads
for one card; the link must carry the origin that can answer for the thread, because
the cloud names a thread it can never read and someone must resolve it. Identity tuple,
as both maps ask for on paper before any schema: `(org, user, machine, thread, chair)`.
Convoy today has only `(thread, chair)`; `machine` arrives with the delegation card,
`user` and `org` come from the tenant record (move 4), never from a row.

**Per-user conductor means per-user origin.** One Grok Bot per user, each with its own
bearer, each reaching that user's machine. Today there is one origin at `convoy.bot`
on one machine. Addressing N origins is a known unknown on the Convoy side: a hostname
per user, or a relay the Ledger fronts. Nothing in this spec depends on the answer
except the `machine` field on the link.

**Two words, two fields.** `delivered` is Convoy's five-valued truth about the send.
`delegation {token}` in this spec answers a different question, the state of the work:
queued, received, working, progressing, stalled, done, refused. Both ride the report;
neither replaces the other. And "card" is a result envelope in Convoy
(`CARD_OUTPUT_SCHEMA`) and a work item in Worklanes: Convoy docs say "result card",
Worklanes docs say "work card", and CANON names the collision.

**Card text into a neuron is untrusted.** `delegate` writes the brief into the lane's
`.convoy/brief.md` and the send body. The boot prompt and the contract frame it as
content to act on, never as instructions that override the seat's rules, the same
boundary the feed already enforces on notes.

**What this changes in the PR map.** W0 is new: seat rows carry the harness session id,
so the Ledger join on `(tool, toolSessionId)` exists. W1 adds the `.git/info/exclude`
write on `bind` and `onboard`, not only on `clone`. W2's delegation card carries
`machine`. W4's tenant record carries `user` and `org` for the stamps.
