---
name: neuron-receive
description: How a neuron on ANY harness (grok, claude, codex, cursor-agent, agy, hermes, pi) receives messages from the thread and proves receipt. Use on first turn, at every turn start, and whenever you have been idle.
---

# Receiving on a Convoy thread

You are a neuron. Two channels can carry a message to you. You receive at
tool time (PreToolUse), at turn end (a Stop with rows waiting is blocked and
the rows become your reason to keep working), and when a background
`convoy --root <root> inbox --wait --seat <you>` completes: start that at the
end of EVERY turn with `background: true`, so an arriving row wakes you. Idle
at your prompt with no wait running, nothing reaches you; the lead can then
only relaunch or nudge your pane (skills/convoy-nudge).

| Channel | Where it lives | Who writes it | How you read it |
| --- | --- | --- | --- |
| feed | `<root>/.convoy/feed.jsonl` | any chair (`hook note … --to <you>`), the conductor (`stamp`) | `convoy --root <root> feed --since <ts>` and filter rows whose `to` is your chair |
| inbox | `<root>/.convoy/inbox/<your chair>.jsonl` | `send --to <harness> --instance-id <you> --live` from another chair | `convoy --root <root> inbox --drain --seat <you>`, or your harness hook does it for you at tool time |

A message is **queued** when it sits in either file. It is **delivered** only
when YOU write an ack row. Nothing else counts: not the sender's card, not a
pane being open, not a hook having fired.

## The receive loop (identical on every harness)

Run these at the start of every turn and after any idle period. `<root>` is
the thread root (the folder holding `.convoy/id`), never your worktree if
your worktree carries a different `.convoy/id`.

```
convoy --root <root> whoami
convoy --root <root> feed --since <your last ack ts>
convoy --root <root> inbox --drain --seat <your chair>
```

1. `whoami` names your chair. If it returns `conflict: true`, your cwd walks up
   to a different thread; keep passing `--root`. If it returns `chair: null`,
   stop and ask the human to `join` you; never guess a chair.
2. Read every feed row addressed to you (`to` == your chair) and every drained
   inbox row. Act on them.
3. Ack: `convoy --root <root> hook note "<what you did or will do>" --as-me
   --to <sender chair>`. For an inbox row, include its `token` in the text.
   The row you write is the receipt; the sender's card can never claim it.

## Per-harness hook (what fires without a human typing)

| Harness | Hook that drains the inbox for you | Fires | Installed by |
| --- | --- | --- | --- |
| grok | `.grok/hooks/convoy-inbox.json` PreToolUse + Stop → `convoy inbox --hook-pretooluse` | at tool time, and at turn end: a Stop with rows waiting is blocked and the rows become the reason you keep working (grok-build 10-hooks.md). Idle wake: at the end of every turn start `convoy --root <root> inbox --wait --seat <you>` with `background: true`; a completing background command wakes you (grok-build 20-background-tasks.md), and the row that ended the wait is yours to drain and ack | Convoy first run (`ensure_first_run`) |
| claude | `.claude/settings.json` PreToolUse + UserPromptSubmit → same command | tool time and turn start | Convoy first run |
| codex | none proven; `codex queue --thread <id> --message` exists and is unproven as delivery | never on its own | you: run the loop by hand |
| cursor-agent, agy, hermes, pi | none | never on its own | you: run the loop by hand |

When a hook fires it hands you the drained rows as extra context. You still
owe the ack row. No hook fires while you are idle at your prompt; if a human
types anything, run the loop first.

## Started outside Convoy (no chair, no worktree)

If `whoami` says `chair: null` from a folder that is no worktree, you are an
outside body. Do not guess a chair: `convoy threads`, then `convoy start`
(a picker; it never picks for you), then on the root you chose
`convoy --root <root> attach` and `convoy --root <root> join --to <you>`.
The join card's boot prompt carries your token; sends to that chair queue in
`.convoy/inbox/<chair>.jsonl` until you drain and ack, and you are
`connected` only after `seated --token <join token>`. Full walk:
`docs/OUTSIDE_HARNESS_JOIN.md`.

## Reaching the conductor (grok-bot)

The conductor reads the thread only through its MCP `feed` on the root it is
bound to. Write `hook note "…" --as-me --to grok-bot` on YOUR root; if the
public MCP is bound to a different root, the conductor will not see it until
the deploy binds this thread. Never invent that it did.

## Never

- Type into another neuron's pane, or ask a tool to do it.
- Resume a vendor session you do not own to "deliver" something.
- Report a send as delivered because the card said `ok`.
- Drain another chair's inbox.
