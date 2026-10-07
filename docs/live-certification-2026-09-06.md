# Live certification — 2026-09-06

> **Superseded 2026-10: convoy.bot/mcp is retired.** Convoy's MCP runs on your machine at `http://127.0.0.1:8788/mcp` (`convoy mcp`); there is no hosted Convoy endpoint and no tunnel. This document is kept as dated history; its references to the hosted endpoint describe the past.

Goal: prove Convoy live. Real neurons, launched by Convoy
into their own worktrees with the seat's declared model and effort, each
receiving its boot prompt, acking with its own join token, completing one
small verifiable task, and replying on the thread. grok-bot reads the thread
over the public MCP and confirms the replies. No mocks, no self-supplied
acks.

This document is the lane spec. It is written before the launch and is not
edited to fit the outcome; the outcome is recorded in the evidence section
at the end, with sources.

## Lanes

Thread: `<thread>`, root `<checkout>`. One
`wt.exe` window, one pane per seat, minted from the root checkout as
`<root>-wt-<title>` on branch `convoy/<title>` (`repo.mint_worktrees`).

| title  | harness | model            | effort | where |
|--------|---------|------------------|--------|-------|
| codex-a  | codex   | gpt-5.6-luna     | xhigh  | local |
| codex-b  | codex   | gpt-5.6-luna     | xhigh  | local |
| claude-a | claude  | claude-opus-4-8  | high   | local |
| claude-b | claude  | claude-opus-4-8  | high   | local |

Sources for the names: `gpt-5.6-luna` and `xhigh` are the spec's words;
`claude-opus-4-8` is the id Claude Code writes into its own transcripts
(read from `~/.claude/projects`);
codex takes `xhigh` as its own `model_reasoning_effort` value.

Expected argv per pane, from `bringup.resume_argv` on the merged code:

```text
codex  -m gpt-5.6-luna -c model_reasoning_effort=xhigh "<boot prompt>"
claude --model claude-opus-4-8 --effort high --permission-mode bypassPermissions --allow-dangerously-skip-permissions "<boot prompt>"
```

## The task each seat performs

Delivered two ways: the boot prompt points at `thread.md`, and one inbox row
per seat carries the same text (`convoy send`).

1. Run `convoy --root <root> seated --seat <seat> --token <token>` with the
   token from your own boot prompt. This is the ack; nobody acks for you.
2. Write `docs/cert/<seat>.md` in your worktree containing: your seat id,
   the output of `convoy --root <root> whoami`, the model and effort your
   harness reports for this session (codex: the status line; claude:
   `/status`), and your process id.
3. Commit it on your lane branch with message `cert: <seat>`.
4. Reply on the thread:
   `convoy --root <root> hook note "CERT <seat>: model=<m> effort=<e> pid=<pid>" --as-me --to grok-bot`.
5. Start `convoy --root <root> inbox --wait --seat <seat>` in the background
   and stop.

## Evidence that counts

- **Launch**: the `wt.exe` argv Convoy built (`crew` card, `windows[].argv`)
  and the live process command line of each harness pid read back with
  `Get-CimInstance Win32_Process` after launch. Both must carry the model and
  effort flags above.
- **Receipt**: the boot prompt is visible in that command line.
- **Ack**: a `kind=seated` feed row per seat whose token matches the join
  row's token, written by the pane (`crew.await_seated` reads it; Convoy
  never writes it on the seat's behalf).
- **Task**: a `kind=commit` provenance row per seat on branch
  `convoy/<title>` and the file `docs/cert/<seat>.md` on that branch.
- **Reply**: a `kind=note` row per seat, `from=<seat>`, `to=grok-bot`,
  summary starting `CERT <seat>:`.
- **Read-back**: grok-bot calls the public MCP (`https://convoy.bot/mcp`,
  tool `feed` or `glance`) and its reply quotes the four `CERT` notes. The
  MCP origin must report the merged SHA in `serverInfo.version` and be bound
  to this root, otherwise it is reading a different thread.
- **Usage rows**: at least one `kind=usage` row per seat after its first tool
  call (fresh-install hooks, PostToolUse).

## What this does not prove

Quota-aware automatic delegation (grok-bot's job, not tested here), cloud
seats, and per-account usage attribution beyond "this pane stamped a row".

## Outcome

Launched with `convoy crew --launch`: one wt.exe window, four panes, four
worktrees minted on `convoy/<title>`.

| seat     | live command line (Win32_Process, after launch)                         | seated (own token) | CERT reply                                  | lane commit |
|----------|--------------------------------------------------------------------------|--------------------|---------------------------------------------|-------------|
| codex-a  | codex.exe `-m gpt-5.6-luna -c model_reasoning_effort=xhigh "<boot>"`     | match              | model=gpt-5.6-luna effort=xhigh pid=null    | yes         |
| codex-b  | codex.exe `-m gpt-5.6-luna -c model_reasoning_effort=xhigh "<boot>"`     | match              | model=gpt-5.6-luna effort=xhigh pid=<pid>   | yes         |
| claude-a | claude.exe `--model claude-opus-4-8 --effort high "<boot>"`              | match              | model=claude-opus-4-8 effort=high pid=<pid> | yes         |
| claude-b | claude.exe `--model claude-opus-4-8 --effort high "<boot>"`              | match              | model=claude-opus-4-8 effort=high pid=<pid> | yes         |

"match" means the `kind=seated` row's token equals the `kind=join` row's
token for that seat (read from `.convoy/feed.jsonl`); Convoy wrote none of
the seated rows. codex-b's pane status line read `gpt-5.6-luna xhigh` on a
screenshot. Each seat's `docs/cert/<seat>.md` on its lane
branch reports the same model and effort the argv carried.

Read-back: a Convoy MCP origin on the merged build, bound to this root and
staged on loopback, answered `tools/call feed` with all four `CERT` notes.

**Open, not proven:**

- Public edge: after the origin was cut over to the merged build,
  `https://convoy.bot/mcp` reported that build's version and a `feed` call
  over the edge returned all four CERT notes. Grok Bot confirmed the
  catalog (21 tools on the thread). No grok-bot-authored row is on the feed: the
  public edge lists 21 read tools and hides `note`/`stamp` by design
  (`_WRITE_TOOLS`), so grok-bot cannot stamp a read-back over the public MCP
  unless write tools are enabled on the origin. That is a security decision,
  not a bug, and it is open.
- `kind=commit` provenance rows did not land for the four lane commits; the
  commits exist on the branches, the feed does not carry them.
- Usage rows: both claude seats stamped `kind=usage` on PostToolUse (fresh
  install). Neither codex seat stamped one although
  `.codex/hooks.json` in its worktree carries PostToolUse; whether codex
  reads a project-local hooks.json is unverified.
- codex-a reported `pid=null` (it could not map its own process); claude-b
  put its join token into its CERT note text.
