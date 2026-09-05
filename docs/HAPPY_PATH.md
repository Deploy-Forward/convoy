# Convoy happy path

Establish a `.convoy` thread and prove it useful against a repository. Six
frames, each a shipped command; `test/demo/happy_path_test.py` walks all six
against a real git repo and is the proof. Agent-agnostic: any harness you are
already logged into can lead; neurons spend their own meters and tap one
shared thread.

## 1 · Launch

Open a terminal with any harness: `claude`, `grok`, `codex`. The harness that
onboards first conducts: its name lands in `.convoy/lead` and on the onboard
card as `lead: {harness, set: true}`. A later onboard reports the standing
lead (`set: false`) and never steals it; lead passes are neuron-authored
(`lead --to <chair> --as <you>`).

## 2 · Connect

```
convoy onboard --to claude --to codex --to grok --thread demo
```

One durable thread: `convoy_id` (`cvy_…`), `thread`, `root` on the card.
`.convoy/` holds the feed, the seats and the stamps. That directory IS the
shared memory; there is no second store.

## 3 · Point at work

```
convoy onboard ... --checkout-root <git-url>            # GitHub: cloned once under $CONVOY_HOME/checkouts/<owner>/<repo>
convoy onboard ... --checkout-root <path> --github no   # local folder, same memory
```

## 4 · Summon neurons

```
convoy crew --seat codex --seat grok,effort=high --thread demo --launch
```

Every seat is validated first; one worktree is minted per local seat
(`<checkout>-wt-<name>`); every chair is joined with a boot prompt carrying
the token its join minted; ONE window comes up. The card's `seated` snapshot
says `pending` for every chair: launched is not connected.

## 5 · Prove they are seated

```
convoy await-seated --seat codex-1-demo --seat grok-2-demo
```

`connected` only when the chair's own `seated` row cites the token its join
minted (the neuron runs `convoy seated --seat <me> --token <t>` from its
pane). `pending` and `stale` are not connections, whatever the pane shows.

## 6 · Delegate, then read the shared memory

```
convoy send --to codex-1-demo "draft tests for retry planner"   # delivery: queued, delivered: false
convoy send --to grok-2-demo  "audit retry paths"
convoy stamp "tests drafted"
convoy feed --since 10m                                          # join, seated, synapse, conductor rows
```

`--to` names a CHAIR (its session_id). Naming a harness that already has a
chair refuses: naming a vendor is not naming a neuron. Delivery is proven only
when the target drains its inbox and authors an ack citing the token.

## The rail

```
convoy rail [--since 10m]
```

The strip under the panes: `feed.events`, `seats {total, connected, pending,
stale}` from the seated acks, `usage` per harness (`null` is unknown, never
0), `last_stamp`, `lead`. It reads only the thread. Run from a chair's
worktree it finds its thread through the machine index, so the neuron, the
lead and a chat over MCP (`rail` is a public read verb) see one rail. That
is the definition of done: any neuron rehydrates from the thread alone.

## What "cloud" means here

The thread is a directory under the bound root. A cloud thread is that same
directory on the host that serves the Convoy MCP endpoint, with neurons
attaching over MCP instead of by pane. No cloud launcher exists yet
(`where=cloud` writes a chair and refuses a pane); a cloud neuron proves it
is connected the same way, by its own seated ack.
