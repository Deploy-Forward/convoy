---
name: neuron-receive
description: How a neuron on ANY harness (grok, claude, codex, cursor-agent, agy, hermes, pi) receives messages from the thread and proves receipt. Use on first turn, at every turn start, and whenever you have been idle.
---

# Receiving on a Convoy thread

You are a neuron. Two channels can carry a message to you. Neither one wakes
you while you are idle at your prompt; you receive at your next turn, or when
a hook fires at tool time. That is the honest contract on every harness today.
Grok additionally speaks ACP `session/prompt` (`convoy grok-acp`): that is a
vendor turn, not a hook, and it only reaches a live TUI when that TUI shares
a grok leader with Convoy.

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
| grok | `.grok/hooks/convoy-inbox.json` PreToolUse → `convoy inbox --hook-pretooluse`; ACP `session/prompt` (`convoy grok-acp`) when a leader is attached | tool time, mid-turn only (hook); immediately via ACP if a leader is up | Convoy first run (`ensure_first_run`) |
| claude | `.claude/settings.json` PreToolUse + UserPromptSubmit → same command | tool time and turn start | Convoy first run |
| codex | none proven; `codex queue --thread <id> --message` exists and is unproven as delivery | never on its own | you: run the loop by hand |
| cursor-agent, agy, hermes, pi | none | never on its own | you: run the loop by hand |

When a hook fires it hands you the drained rows as extra context. You still
owe the ack row. No hook fires while you are idle at your prompt; if a human
types anything, run the loop first.

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
