# The `.convoy` source of truth

One JSON architecture. Do not invent a parallel store. Everything below is
what `src/convoy/layer.py`, `convoy.py` and `lifecycle.py` already write;
this page names it so every agent reads the same thing.

## On disk, under the thread root

| Path | Role |
|---|---|
| `.convoy/id` | one line, `cvy_…` |
| `.convoy/thread` | one line, the thread key |
| `.convoy/lead` | one line, the lead harness (whoever onboarded first; passes are neuron-authored) |
| `.convoy/feed.jsonl` | the timestamped bus, append-only, single writer (`layer.hook`) |
| `.convoy/seats.jsonl` | chairs and occupants |
| `.convoy/inbox/<chair>.jsonl` | queued sends for a live chair, drained by the chair |
| `.convoy/handoff/…` | pass-off files (replaces `.ola/*handoff*`) |
| `~/.convoy/threads.json` | machine INDEX only: `{convoy_id, thread, root, updated_at}`. Not the SoT; it finds the root |

## Feed row (every event)

```json
{"ts":"<ISO-Z>","kind":"<kind>","instance_id":"<subject-or-null>","summary":"<one line, ≤500>","from":"<author?>","to":"<addressee-or-target?>"}
```

- `ts` always; event time, never a vendor resume time.
- `kind` is an open set: `conductor`, `synapse`, `note`, `refuse`, `join`, `swap`, `seated`, `attach`, … Readers skip kinds they do not know.
- `instance_id` is the row's SUBJECT (usually the chair).
- `from` is AUTHORSHIP, present only when claimed (notes, stamps). A synapse whose sender is unknown has no `from`; it is never invented. `grok-bot` authors stamps only, never notes.
- `to` is the addressee on notes and stamps, the target chair on a synapse.
- `schema_version: 2` rides the CLI/MCP envelope (`feed`, `attach`), not the file.

## Conductor stamp (`kind=conductor`)

```json
{"ts":"…","kind":"conductor","from":"grok-bot","summary":"…","agent":null,"model":null,"effort":null,"transcript":null,"usage_remaining":null}
```

Unknown is JSON null. `transcript` is a pointer, never bubble bytes. `truncated: true` marks a clamp.

## Synapse and pass-off

- A synapse row carries provenance: `runner` (`inbox` | `codex-queue` | `native` | `fake` …), `argv0`, `delivery`, `delivered`, `worktree`, git state.
- A live send to a chair is QUEUED (`delivery: queued`, `delivered: false`) until the chair drains its inbox and authors an ack row citing the token.
- Seated proof is the chair's own `seated` row citing the token its `join`/`swap` minted (`await-seated`; launched is not connected).
- A handoff is a file under `.convoy/handoff/…`, pointed at by a `refuse`/`swap` row and the boot prompt, never inlined.

## Seat row (`seats.jsonl`)

Chair identity is `session_id`. Occupant harness is `to`. Plus `worktree`,
`model`, `effort`, `effort_applied`, `where` (`local` | `cloud`), `title`,
`agent`, `resume` / `resume_for` / `resume_key` (vendor resume id, null when
none), `convoy_id`. Tokens never leave `seats.jsonl` on the public wire.

## Where it lives

| Layer | Store | Why |
|---|---|---|
| canonical SoT | `<root>/.convoy/feed.jsonl` + `seats.jsonl` | already the temporal bus; any agent on that root (CLI or MCP) can `feed --since` / `rail` and resume |
| find the root | `~/.convoy/threads.json` | an agent with no cwd runs `convoy threads`, picks a root, reads the feed |
| "cloud" | the same `.convoy/` on the MCP host's disk (one public `--root` today) | neurons attach over MCP; they never get a second store. Multi-tenant roots are future work, never per-thread MCP URLs |
| GitHub | the checkout only (code, optional `thread.md`) | never commit live `feed.jsonl` / `seats.jsonl` (noise, tokens, PII). At most a pointer that cites `convoy_id` + last stamp summary |

## Last note, any agent launches

```text
1) resolve root   -> threads index | --root | MCP bound root
2) last note      -> feed --since …, kind in {note, conductor, refuse}, newest ts
3) pass-off file  -> .convoy/handoff/<id> when the row points there
4) launch         -> resume (seat argv) | crew seat | send into inbox,
                     from seats.jsonl (harness `to`, vendor resume, worktree)
```

Persist on the thread root, discover via the index or MCP, prove via feed
timestamps. GitHub is for the repo, not the live agent tape.
