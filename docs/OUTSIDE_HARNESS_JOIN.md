# Joining from outside the harness

A `claude`, `codex` or `grok` session someone opened by hand, in a folder that
is no worktree and holds no chair, can still find a thread and receive work.
Nothing is stolen: no second session, no `--resume`, no keystroke into a pane
it does not own. `test/demo/outside_harness_join_test.py` walks every line
below through `cli.main` and the MCP server against real git repos; the only
injected pieces are the process table, the usage probe and the window spawn.

## The walk

```
convoy whoami                         # ok:false, chair:null, ask: "join (...)"; never an invented chair
convoy threads                        # the machine index: every root, present true|false
convoy start                          # picker from recent(): present, non-temp roots; ok:false, ask:pick
convoy --root <root> attach           # the chosen root; convoy_id + thread on the card
convoy --root <root> join --to codex  # one chair, a boot prompt carrying its token; nothing spawned
```

`whoami` walks your own process ancestry to a harness and matches it to a
chair by token, worktree or cwd. Outside every worktree that match is empty,
so the answer is `chair: null` with an ask. A `--root` that carries no
`.convoy/id` answers the same way. `start` with no repo never picks for you:
temp roots (mkdtemp residue) are excluded from the list, and the card is
`ok:false` until you name a root. `attach` and `join` write to the chosen
root only; the folder you started in stays empty.

Then the lead delegates, and you receive:

```
convoy --root <root> send --to <chair> "draft tests"      # delivery: queued, delivered: false
convoy --root <root> inbox --seat <chair> --drain          # the row, with its token
convoy --root <root> hook note "received token=<t>" --instance-id <chair>
convoy --root <root> seated --seat <chair> --token <join token>
convoy --root <root> await-seated --seat <chair> --timeout 0   # connected
```

`delivered` flips only on a row the target chair authors. `connected` is
the chair's own `seated` row citing the token its `join` minted; before that
ack the chair is `pending`, whatever a terminal shows.

## The MCP variant

A neuron that attaches over the MCP endpoint does the same walk with `join`,
`seated` and `await_seated` as tools, on a gated deploy
(`CONVOY_MCP_WRITE_TOOLS=1`, loopback). A `where=cloud` chair is accepted only
for a harness whose `harness_effort.json` cloud block evidences an
interactive attach (claude today; codex is refused by name). It has no
worktree, and `bring_up` refuses it a pane: the card lists it under `cloud`
with `pane: false` and the reason. It proves connected the same way, by its
own `seated` ack. The public, ungated endpoint answers `join` and `seated`
with the gate named; it writes nothing.

## Landscape

Convoy does not own PTYs. It owns the thread on disk (`.convoy/`), the seat
rows and the feed; a pane is whatever the mux or the harness gives you, and
keeping it alive is their job (tmux, Windows Terminal, the vendor's own
session store). When a pane dies the thread is intact; `relaunch` brings the
chairs back and each one is `pending` again until it acks.
