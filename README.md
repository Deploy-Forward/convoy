# Convoy

Convoy: local-first multi-agent orchestration. Run Claude Code, Codex, Cursor, Grok and agy side by side on your machine, on one durable thread.

Convoy's MCP runs on your machine at `http://127.0.0.1:8788/mcp` (`convoy mcp`). There is no hosted Convoy endpoint. One local server serves every thread on the machine; each call names its thread, and `--root` pins one.

Remote access to your loopback MCP is not a Convoy feature; if you build it, put it behind your own access control.

## Install

Python >= 3.11, standard library only (no runtime dependencies).

```bash
git clone https://github.com/Deploy-Forward/convoy.git
cd convoy
python -m pip install .
convoy --help
```

Alternative: `pipx install .` (not verified on Windows in this pass).

The `convoy` console script and `python -m convoy` both work only after
install. To run from a checkout without installing, put `src` on the path:
`PYTHONPATH=src python test/run.py` on bash, or
`$env:PYTHONPATH='src'; python test/run.py` in PowerShell.

### Skills and plugins

Skills ship from Deploy-Forward/plugins
([github.com/Deploy-Forward/plugins](https://github.com/Deploy-Forward/plugins)):
the convoy and worklanes plugins carry the Convoy skills and the MCP connection
to your own Convoy (`http://127.0.0.1:8788/mcp`). The `convoy-wizard` skill is
not in the plugins repository; `convoy preflight` still checks the verbs a guided
setup needs, from the list in `src/convoy/wizard_preflight.py`. This repository is the CLI and
the MCP server. It ships no skill text and no plugin pack, so there is one source
for the skills a neuron reads. Claude Code installs with
`claude plugin install convoy@deploy-forward`; the plugins repository's README
has the install for every other harness.

A launch writes one Convoy file a neuron reads, the `AGENTS.md` pointer (see
below): one paragraph naming the convoy plugin's `convoy-operate` skill and
`convoy-dictionary`. Convoy replaces that block only when it is a block an
earlier Convoy wrote; a block you edited is left as it is and the card names the
file. Convoy deletes nothing in a worktree: skill copies, agent files or prompts
an earlier version wrote stay where they are, and removing them is your call.

`convoy --version` prints the version, the executable that ran, the package
source it imported and whether that source is an editable install. Run it first
when a skill and the CLI seem to disagree.

### Host rendering

Host rendering: unverified. Whether Grok Bot surfaces Convoy as
`@convoy` or `/convoy`, and whether it renders the `card` tool's
`structuredContent` as one card with a drill-down or only shows the text copy,
is a fact about the host that nothing in this repository observes. The server
declares `card` with an MCP `outputSchema` and answers through
`structuredContent` so a host that renders cards can; the claim that it does
stays unverified until a maintainer records a live run in
`test/demo/fixtures/host_rendering.json` (date + verbatim evidence), which flips
`host_rendering_contract_test` from skipped to asserting.

The canonical local and plugin sequence is documented in
[`docs/convoy-happy-path.md`](docs/convoy-happy-path.md), including the exact
chair-addressed `send` path and the tenant-isolation requirement any future
hosted product would have to meet before the word "cloud" applies.

### Receiving messages needs a command that resolves

Neurons receive through a harness hook, and a hook runs in its own shell that
inherits nothing from yours. A hook file only ever carries the bare
`convoy inbox --hook-pretooluse` or `convoy end --hook`, never an interpreter
path, and Convoy **probes** that command before writing any hook file. Check
what it found:

```bash
convoy --root <thread-root> skills --worktree <worktree>
```

In a worktree Convoy did not mint, `skills` refreshes only the Convoy-named
files; add `--write-repo-files` for `AGENTS.md`. Convoy writes no
`.codex/hooks.json`: Codex runs Convoy's hooks from the convoy plugin, once the
person trusts them with `/hooks` in Codex.

The card's `hooks.resolved_via` is `console-script` when the installed
`convoy` answers in the hook shell. When it does not (it is not on PATH, or an
unrelated `convoy` shim shadows it), the card names the PATH problem with an
install hint, **no hook file is written or removed**, and a launch refuses
rather than start a pane that cannot receive. Put the console script first on
PATH (`convoy --version` names the one that runs) and re-run. The same command
is the repair when a hook goes stale: it replaces Convoy's own older entries,
an interpreter-pinned one included, with the bare command and leaves your own
hooks untouched.

## CLI reference

One line per verb; flags shown are the ones you will reach for (see
`convoy <verb> --help` for the full set). Every verb accepts a global
`--root <thread-root>` before the verb name.

Read (no writes to thread state):

- `list [--json] [--all] [--since <window>]` — deterministic numbered thread blocks and full neuron rows. Default: present threads updated/active within 14 days. Temp and absent roots are always named as skipped, never removed. `--all` includes hidden/older usable roots with reasons. Unknown fields stay unknown; detached is not dead. The read-only MCP `list` exposes the same card to authenticated callers, not the anonymous product edge.
- `threads [--prune]` — every Convoy thread this machine knows. `--prune` drops rows whose root is under the OS temp dir or is absent and reports every dropped row (never silent).
- `panes` — every body of every neuron on this thread, from the OS process table; never a token.
- `whoami` — which chair is this process? Walks process ancestry to the harness. On a seated chair it adds `lead` and `launched_by` (`{chair, neuron_id}` or null).
- `report "<text>"` — send your result to the chair that launched you (`launched_by`), else to the lead; refuses with `why` when neither exists. Needs environment, token or pane-host proof of your session.
- A neuron launched over MCP (`crew`, `join`, `launch`, `bring_up`) records the conductor its bearer proves as its launcher (`launched_by: {kind: conductor, name}`); its `convoy report` is a proven note addressed to that conductor, read with the conductor's `replies` cursor. An MCP launch without a bearer identity refuses.
- `adopt --id <neuron id>` (or `--seat <chair>`) — make yourself the launcher of an existing neuron that has none (or whose launcher is gone or detached), then send it its report and reply commands. Needs environment, token or pane-host proof; an unseated caller is attached first. A live recorded launcher is replaced only by the thread's lead.
- `reply <token> "<text>"` — answer one send: a note to its proven sender citing the token, which is the delivery receipt `replies` counts. Refuses an unknown token or a caller that was not the recipient.
- `graph [--neuron <chair>] [--html [--out <file>]]` — read-only ontology of the thread.
- `seats [--convoy-id <id>]` — seat rows.
- `feed --since <10m|2h|1d|45s|ISO>` — events in a window; the card echoes `since_iso`.
- `relaunch [--thread <name>] [--timeout <s>] [--dry-run]` — after the panes died (shutdown): brings every chair up again from `seats.jsonl` in its own worktree, queues each chair an inbox row saying when it left off (`last_seen`, `unread`, the exact `feed --since <ts>` to run), stamps `kind=relaunch`, and proves connected only from seated acks stamped after the relaunch. Dry shows the timeline and spawns nothing.
- `rail [--since <window>] [--probe]` — the strip under the panes: feed events, seats connected | pending | stale (from the seated acks), usage remaining per harness (`null` is unknown, never 0; read by running each harness's CLI only with `--probe`), last stamp, lead. Reads only the thread; from a chair's worktree it finds its thread through the machine index, so every neuron sees one rail.
- `context [--instance-id <chair>]` — pointer pack for a neuron.
- `glance [--thread <name>] [--tray]` — one-screen status.
- `resume --neuron <chair>` — dry: prints native argv + cwd, spawns nothing.
- `choices` — installed harnesses, known worktrees, chairs, terminal adapter; no resume tokens.
- `probe --to <harness>`, `id`, `terminals`.
- `widget [--topmost/--no-topmost] [--refresh 3] [--service]` — always-on-top tkinter strip: one dot per thread from `recent()`, expand chairs, click → `focus`; a stale chair shows a `nudge` button (dry card first, keys typed only on confirm, then the feed is polled 60 s for the chair's own row — that row alone means delivered). `pin` toggles topmost; `x` hides to the tray where `pystray`+`PIL` import, else minimizes. `--service` starts one detached strip per machine behind `$CONVOY_HOME/widget.pid` (`already: true` when the pid is alive and its image is our interpreter; a reused pid respawns). `crew --launch` and `relaunch` start it unless `--no-widget`. A start with seats from the widget records the thread's held lead chair as each neuron's launcher (the card says `launcher.source: "widget-lead"`), so the neurons report to the lead; a thread with no held lead refuses until an agent session attaches (`convoy attach <thread>`). Stdlib only.
- `focus --seat <chair>` — ask the pane host to highlight that chair. `{focused: false, reason}` until a host adapter is evidenced (tmux `select-pane -t` is tested; Windows Terminal `wt focus-pane` is not evidenced).

Write (thread state):

- `init` — create the thread layer at `--root`.
- `bind --thread <name>` — bind this root to a named thread.
- `start [<target>] [--to <harness> ...] [--thread <name>] [--cancel]` — resolve an existing local path without network access; a git URL or `owner/repo` reuses a checkout by normalized remote identity before cloning; a bare name searches indexed/local repos and the authenticated GitHub user's and organizations' repositories. Only exact case-insensitive repository names or folder basenames can resolve automatically; fuzzy suggestions return a numbered picker. Among complete same-remote matches, prefer an indexed thread root (latest indexed update), then a unique main checkout. Otherwise ask, with main checkouts first and linked worktrees collapsed to a count; `--all` expands them. No match asks local folder versus GitHub creation, unless discovery failed (unknown, never absence). Only explicit `--create` creates a private GitHub repo. Missing/logged-out `gh` stays local; an exact local match also works offline without refresh. `--search-root <dir>` repeats and scans one level deep, excluding Convoy state folders except the owned checkout store; `--scan-budget <seconds>` defaults to 5 and includes local candidate dates. Incomplete scans carry warnings and never auto-resolve. Ordinary remotes use config file reads, including shared worktree configs and once-per-resolution global insteadOf rules; conditional includes/overrides fall back to bounded Git reads. GitHub candidate date metadata comes from the single listing's `updatedAt` (marked as that source, not a commit timestamp). Cloud-backed checkouts fetch non-interactively and fast-forward only if clean, behind, and without local commits or ignored/untracked files that would be overwritten; dirty/ahead/diverged/detached work is kept, never stashed, reset, rebased or merged. Fetch and ls-remote alone disable interactive credentials; clone/worktree keep their existing policy. Helper timeouts terminate their process trees without waiting on inherited output pipes. No target returns the existing thread picker. No pane launches. Repo writes stay under `.convoy/` unless `--write-repo-files`; cards include the resolution and `pulled` outcome, with credentials redacted and non-secret Convoy receipt tokens retained.

The ignored-file guard checks incoming paths immediately before fast-forward. An ignored file created concurrently after that check can still be overwritten by Git; this remaining race is not an atomic preservation guarantee. No stash/reset or implicit file deletion is used.

An indexed thread root outranks the main checkout only when its known index update is within 14 days. Older, future or unknown dates do not prove freshness. When only linked worktrees match, the picker shows their actual numbered rows, newest first, rather than an empty collapsed list. Refresh performs one non-interactive fetch followed by local `git merge --ff-only @{upstream}`; it never creates a merge commit or performs a second network round trip through `pull`.
- `attach [<thread>] [--as-harness H]` — link the calling native session to the chosen thread using the same process/native identity proof as `whoami`. `<thread>` is the exact `cvy_` id, a unique prefix of it of at least 8 characters (`cvy_` counts), the exact thread name, or the thread's root path; an ambiguous prefix refuses with `matches N threads: <ids>`. `detach --thread` and `lead --thread` resolve the same way. Pick numbers are display-only: pass the block's `cvy_` id. No choice prints the list and refuses to guess; unavailable/conflicting identity refuses without creating a chair. A native session can sit on several threads at once, one chair on each: the card lists the others in `also_on`, the hooks deliver every thread's inbox (each row labelled with its thread), and a command that needs one thread (`whoami` with no root, `detach` without `--thread`) refuses with the list. Repeating returns `already: true` and per-chair catch-up; a bare local self-join reuses the chair. Explicit names, titles, other worktrees and `join --launch` still provision a new neuron. An unavailable non-temp indexed root is reported in `ownership_skipped` and never refuses the attach; temp roots remain in the index but are excluded from attachment, with reasons in `ownership_skipped`. No pane or vendor usage probe is launched by attach. `--as-harness` asserts, never overrides, the proven harness. Legacy catch-up-only callers use `attach [<cvy_id>] --read-only` (still records an attach event, but never seats the caller).
- `detach [--thread <thread>]` — prove the calling chair, write its rolling handoff and append detached state. No history deletion, pane close or session kill. Pending rows remain on disk but cannot wake the detached chair; sends refuse `detached; attach again`. Attach reactivates the same proven chair.
- `onboard --to <harness> [--to ...] [--thread <name>] [--checkout-root <path|git-url>] [--github yes|no]` — name installed harnesses and bind; a URL is cloned once under `$CONVOY_HOME/checkouts/<owner>/<repo>` (`.convoy/` and `thread.md` go into that clone's `.git/info/exclude`). Onboard names no lead: a new thread's `lead` is unset until a session attaches (it takes the lead) or a seated chair passes it; a later onboard reports a standing lead and never changes it.
- `seat --to <harness> --session-id <chair> [--worktree <path>] [--model M] [--resume <vendor-id>] [--title T] [--effort E]` — register a seated neuron.
- `join --to <harness> [--worktree <path>] [--title T] [--as <chair>] [--launch] [--consent <id>]` — register one fresh chair.
- `crew --seat <harness>[,model=M][,effort=E][,where=local|cloud][,title=T] [--seat ...] [--checkout <path>] [--launch]` — N neurons at once: validates every seat first, mints one worktree per local seat, joins every chair with a boot prompt, and (with `--launch`) brings them up in ONE window. Launched is not connected: the card's `seated` snapshot says `pending`.
- `add <harness> [<model>|auto] [--effort E] [--title T] [--checkout <path>] [--dry-run]` — one neuron: mints its worktree, joins its chair, and launches it inside tmux as a split of your exact pane; on Windows into the thread's own Windows Terminal window (`wt -w convoy-<8 hex>`: the first neuron opens it, later ones split inside it, never your working window); on POSIX outside tmux into the thread's one detached tmux session. It refuses before any write when there is no terminal to use, and when it cannot prove who is launching (run it from an agent session such as Claude Code or Codex, or `convoy attach <thread>` first): every neuron records its launcher. Model and effort are auto unless given: no flag, the harness picks. The card's `placement` is `split`, `thread-window`, `detached`, `here` or `none`; a failed launch leaves the chair joined with a `recovery` verb that works on that path. `--here` is the opt-in to split the window you are working in (Windows: `wt -w 0 split-pane`; inside tmux: a split of your pane); outside both it refuses and names `thread-window`/`detached`. It is never the default.
- `await-seated --seat <chair> [--seat ...] [--timeout <s>]` — observe the acks: per chair `connected` (its own `seated` row cites the minted token) | `pending` | `stale`, with the seconds waited.
- `swap --seat <chair> --to <harness> --handoff <.convoy/handoff/<chair>-<ts>.md> --as <chair>` — replace the occupant, keep the chair.
- `seated --seat <chair> --token <token>` — proof-of-life echo from the new occupant.
- `lead [--thread <thread>] [--to <chair> [--as <you>]]` — read the lead (`lead`, `lead_chair`, `dangling`, `reachable_id`), or pass it to a seated chair. The author is the proven calling chair (environment or token proof); `--as` asserts it and refuses when it disagrees. Only the current lead passes it; `--to <harness>` passes to that harness's one seated chair under the same rule; while the lead is unset or dangling (it names a harness with no seated chair), any seated chair may take it. `convoy attach` takes an unset or dangling lead for the attaching chair. On the lead and attach cards, `conductor` is the lead chair or null; the hosted `grok-bot` is named only where that hosted conductor is meant.
- `hook note "<text>" [--as-me] --to <chair>` — leave a note for a chair (or `grok-bot`). A receipt that cites a send token (`re token <t>` or `token=<t>`) sent to you, with no `--to`, goes to that send's proven sender (a third party citing it stays unaddressed); one addressed to its own author refuses (`a receipt goes to the sender: --to <chair>`).
- `stamp "<summary>" [--agent A] [--model M] [--effort E] [--transcript <pointer>]` — conductor stamp.
- `send --to <chair|harness> "<body>" [--live] [--dry-run] [--instance-id <chair>]` — synapse. `--to <chair>` (a session_id, e.g. `codex-1-demo`) queues into that chair's inbox in its own worktree (`delivery: queued`, `delivered: false`); `--to <harness>` with a chair already on that harness refuses (naming a vendor is not naming a neuron); default runner records a feed row (`delivery: recorded`); `--live` runs a fresh headless vendor session (`executed`).
- `inbox [--seat <chair>] [--drain | --hook-pretooluse]` — list or drain the live-seat inbox. The hook command is always `convoy inbox --hook-pretooluse` (never a baked interpreter path).
- `end [--summary <text>] [--push | --hook]` — explicit task completion, or the Codex/Claude Stop heartbeat. `--push` authorizes exactly one plain `git push` and refuses dirty, detached, or no-upstream state; `--hook` never pushes.
- `install --to <harness> --opt-in [--live]` — cataloged installer; dry-run by default.

Launch / panes:

- `choices` — see above; run it first.
- `launch --seat <chair> [--dry-run] [--consent <id>]` — split one already-joined fresh chair into the active pane host.
- `consent --grant <request-id>` — grant a prior consent request after the user explicitly approves it.
- `close --seat <chair> [--consent <id>]` — request closure of one Convoy-managed pane.
- `nudge --seat <chair> [--keys <exact>] [--target <tmux-pane>] [--dry-run] [--consent <id>]` — wake an idle chair on this machine. Identifies the pane first (live body from `panes` plus a unique WT title or tmux target). Live send needs a consent card that names that pane and the exact keys. `delivery: nudged`, never `delivered`. Refuses when the pane cannot be proven. Write-gated on MCP.
- `bring-up` / `open [--thread <name>] [--dry-run]` — bulk show of seated neurons in the thread's own terminal window (`wt -w convoy-<8 hex>`).
- `hide` / `minimize` / `background [--dry-run]` — bulk hide.
- `resume --neuron <chair> --go` — spawn once in the chair's worktree; refuses when a live body holds the chair.

MCP:

- `mcp [--root <thread-root>] [--host 127.0.0.1] [--port 8788]` — serve the loopback MCP endpoint for every thread in the machine index; `--root` pins one.

### Run your own MCP

```bash
convoy mcp --port 8788
```

Then attach `http://127.0.0.1:8788/mcp` in your MCP client. The server binds only a
loopback address (`--host` accepts `127.0.0.1`, `localhost` or `::1` and refuses
anything else) and answers loopback requests only: the connecting peer must be
this machine's loopback, the `Host` must be `127.0.0.1`, `localhost` or `[::1]`
on its port, and an `Origin`, when a browser sends one, must be an `http://`
loopback origin on that same port. Anything else is a 403, which keeps a web
page (or a DNS-rebinding name) from driving your MCP. No response carries CORS
headers. The desktop widget's own local server applies the same checks.

Writes need a conductor bearer: run `convoy conductor mint` on this machine and
send it as `Authorization: Bearer <bearer>` on every request. The bearer opens
the write gate for `send`, `stamp`, `note`, `join`, `seat`, `launch`,
`crew`, `seated`, `consent`, `await_seated`, `focus`, `nudge`, `onboard`, `clone`, `mint`,
`repos`, `resume` with `go=true`, and `inbox` with `drain=true`. There is no
process-wide switch: `CONVOY_MCP_WRITE_TOOLS` was removed in 1.3.2. A
`tools/list` on a machine with no bearer minted hides the write tools. Once a
bearer exists they are listed for every caller and refused at `tools/call`
without it, so a listed verb is a promise only to the caller holding the
bearer. Reads (`choices`,
`neurons`, `inbox` pending, `graph`) need no bearer, and an inbox read
without one never echoes the row token. `repos` wraps `gh repo list` on the MCP
process PATH (name, url, private, updated_at; gh absent is an install hint);
it lists the gh login on the MCP host, the conductor's account, which is why
it sits behind the gate rather than handing that inventory to strangers.
`clone` puts a URL under `$CONVOY_HOME/checkouts/<owner>/<repo>`; `mint`
derives one worktree per seat from that checkout as `<checkout>-wt-<name>`
on branch `convoy/<name>`, so nobody hand-makes worktrees for N neurons. `crew`
does the whole walk for N seats (validate, mint, join each with a boot prompt,
one window) and `await_seated` reads the acks back, so "they all connected" is
observed, never assumed. `convoy preflight` tells you which of the wizard's
verbs a live `tools/list` is missing and why.
One local server serves every thread on the machine; each call names its
thread. A server started with `--root` is pinned to that thread, and a call
that names another thread still wins.

## Wake service

Wake dispatch is off for a root until `convoy --root <root> wake enable`.
Read `convoy --root <root> wake status` for enabled state, routes, faults and
held alerts; `convoy --root <root> wake disable` opts that root out without
restarting the origin. The supervised MCP origin runs one dispatcher per enabled
root under an OS lock.

The waiter route is dispatcher-managed. A session starts its own background
waiter using the command printed by its Stop hook; it receives a token pointer,
drains only its proven inbox, answers with a token-citing receipt and re-arms.
A detached waiter started by a hook is not a session wake. Do not run legacy
inbox polling alongside the enabled waiter protocol or infer delivery from a
queued/fired card.

A detached chair retains history, handoff and pending rows but cannot drain,
pulse or wake; new sends refuse until the same proven session attaches again.
Detach does not close its pane or terminate its harness.

## Names you will see

- **Grok Bot** — the xAI desktop conductor chat that attaches the MCP; not a neuron.
- **ola-brain** — a private predecessor wrapper; refused by `install`, not needed.
- **platform** — a closed sibling repo; not needed to run this repo.

## Terms

- **Grok Bot**: the conductor in this chat; not a neuron and not a window.
- **neuron**: one BYO harness session (`grok`, `claude`, `codex`, `cursor-agent`, `agy`/antigravity, `hermes`, or `pi`) on a thread.
- **synapse**: a native Convoy `send` into one neuron; one harness, one meter, compact card back.
- **Convoy**: source of truth (`feed`, seats, `convoy_id`).
- **thread**: durable circuit keyed by `convoy_id`.
- **named thread**: a `--root` binding (not a second MCP URL).
- **grok-bot-local vs grok-bot-cloud**: neuron host (user machine vs cloud agent), not a second source of truth.

Product wording retires **hop** in favor of **neuron/synapse/thread**.

## The problem

Single-harness chat is weak project memory: context windows bloat, meter state drifts, and another agent cannot safely rehydrate shared state without copy/paste loss.

Wrapper stacks (one vendor CLI inside another) add indirection and contention instead of shared truth.

## The solution

Convoy keeps a slim pointer/stamp layer while Grok Bot remains conductor. Synapses run on native vendor CLIs, return compact cards, and keep session ownership separated.

Contract: `feed` + seats + `convoy_id`. Unknown values stay JSON `null`; no invented usage/session numbers.

Machine-readable contract: `src/convoy/harness_effort.json` (loaded by MCP-facing code).

### Keyed effort language (locked)

Effort keys are harness-scoped and must not be merged. The locked key space
lives in **CANON.md** ("Effort keys are harness-scoped") and the
machine-readable source of truth is `src/convoy/harness_effort.json` — this
README deliberately does not restate the table, so there is exactly one place
for it to drift from the code: none.

### Supported neurons (code-true contract)

`grok`, `claude`, `codex`, `cursor-agent`, and `agy` have a cataloged installer
(`convoy install --to`); `hermes` and `pi` are BYO-only (`install` refuses them)
and their direct-id resume is unverified.

Where a first run writes: in a worktree Convoy minted (`.convoy/minted.json`,
written by `crew` / `mint` when they create it, naming that worktree and its
checkout) every file in the table goes in. Anywhere else, often your own repo, a
launch and `skills` write only the Convoy-named files git excludes
(`.claude/settings.local.json`, the `convoy-root` pointers,
`.grok/hooks/convoy-inbox.json`). `AGENTS.md` is written there
only after an opt-in: `--write-repo-files` on the CLI, `write_repo_files: true`
on MCP `bring_up` / `open` / `launch` / `crew` behind the write gate (never on a
dry run: a dry `bring-up` / `open` / `relaunch` on the CLI, or a dry MCP
`bring_up` / `open`, refuses it and writes nothing). The opt-in is kept, bound to that folder and kept out
of git, in `.convoy/repo-files.json`, so later launches there refresh them.
Withdraw it with `convoy --root <root> skills --worktree <worktree>
--no-write-repo-files`; the files already written stay, and are yours to keep or
delete. Until
then the card lists what is missing on disk as `would_write`, and a Codex seat
without Convoy's hook cannot receive; the note names the route that works where
it is read. A `.claude/settings.local.json` that git tracks is never written.
The card names each home trust store a launch wrote (`trust_stores_written`).
`start` and `onboard` write nothing outside `.convoy/` without the flag;
`terminals` writes nothing.

| Harness | `onboard` / `roster` id | `resume_argv` shape | `ensure_first_run` behavior | `send --live` behavior |
| --- | --- | --- | --- | --- |
| `grok` | `grok` | `grok -m <model?> --agent <path?> --resume <vendor-id?>` | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); passes `--agent` only for an agent file the seat names; writes project PreToolUse hook (`convoy inbox --hook-pretooluse`). | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `claude` | `claude` | `claude --resume <vendor-id?>` | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); writes `.claude/settings.local.json` (inbox hooks + Stop heartbeat + auto-compact; no permission keys), merges user `~/.claude/settings.json` skip key, and writes `~/.claude.json` trust project keys. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `codex` | `codex` | `codex resume <vendor-id?>` (**not** `--resume`) | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`). No `.codex/hooks.json`: the convoy plugin's `codex-hooks.json` (in Deploy-Forward/plugins, named by the manifest's `hooks` field) carries the Stop heartbeat and PostToolUse inbox hook, keyed `convoy@<marketplace>:codex-hooks.json:<event>:0:0`; `add` / `crew` cards warn until the person trusts them with `/hooks`. No Claude permission-ungate writes. | Native CLI on PATH. A send `codex queue`s (`delivery: native-queued`, `wake: "codex-queue-accepted"`: accepted, not a turn started) once the plugin's Stop hook has recorded the session id; before that it is `queued`, `wake: "inbox-only"`, with `why`. |
| `cursor-agent` | `cursor-agent` | `cursor-agent --resume <vendor-id?>` | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); writes Grok/Claude inbox hook files (swap-safe). Drain via `convoy inbox --drain` (no vendor hook proven). | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `agy` | `agy` | `agy --conversation <vendor-id?>` (live `--help` 2026-09-01: no `--resume`) | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `hermes` | `hermes` | `hermes --resume <vendor-id?>` (live `--help` 2026-09-01) | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |
| `pi` | `pi` | `pi --resume <vendor-id?>` (flag verified live; `--resume` opens a session picker — direct-id resume unverified) | Writes PATH ungate block; writes the `AGENTS.md` plugin-skills pointer (minted worktree, or `--write-repo-files`); inbox hook files as above. | Native CLI on PATH. Named live seats queue (`delivery: queued`); never steals `--resume`. |

Notes tied to code/tests:

- `seat.session_id` and `seat.resume` are distinct: session key vs vendor resume token.
- First-run seats can omit vendor resume; then no resume token is passed.
- Live `send` is headless and never steals an active interactive neuron; refusal cards ask users to `bring_up` / open a pane or write `.convoy/handoff/<chair>-<ts>.md`.
- `context.pack` overlays home-layer `convoy_id` + `thread_key` onto seat-worktree pointers when present.
- `bring_up` / `open` are the bulk show commands; targeted `join --launch` is
  the explicit one-chair exception described below.

### Bring-up and pane invariants

- Every WT launch on a thread targets the thread's own window, `-w convoy-<8 hex of
  sha256(convoy_id)>`: `new-tab` for the first neuron, `split-pane -V` inside it after
  that, panes in one spawn joined with literal `";"` argv elements. Never `-w 0`, never
  the caller's window, never `--` before the harness exe; never per-seat
  `CREATE_NEW_CONSOLE`; never close on fail with `WM_CLOSE`.
- Two same-harness seats on different worktrees are two panes; duplicates collapse by worktree/resume/session key.
- `Ctrl+Shift+W` should only drop one split pane at a time (or no-op when there is no split pane left).
- Codex TUI conflict: while a Codex pane is focused, `Shift+Up` / `Shift+Down` can change reasoning level and fight pane navigation. Do not use those shortcuts for pane selection in that focus state.

### Targeted one-chair launch

Full contract and DoD: [`docs/targeted-launch.md`](docs/targeted-launch.md).

`convoy choices` lists installed harnesses, known Git/registered worktrees,
existing chair identifiers, and the detected terminal adapter. It deliberately
omits every vendor resume token. A model or user can then invoke:

```bash
convoy join --to <harness> --worktree <path> --launch
```

This registers and launches exactly one fresh chair. Harness argv construction
is independent of terminal placement, so all harnesses use the same terminal
adapter contract. A persistent atomic launch claim refuses duplicate launchers;
existing/resumable chairs are not eligible and a failed terminal spawn leaves
the fresh chair pending for an explicit retry.

Supported active-pane adapters:

| Host | Detection | Targeting |
| --- | --- | --- |
| Windows Terminal | Windows and `wt` on PATH | `wt -w convoy-<8 hex> new-tab \| split-pane -V`; the thread's own window (WT_SESSION decides nothing) |
| tmux on macOS/Linux | `TMUX`, `TMUX_PANE`, and `tmux` on PATH | `tmux split-window -t <caller-pane>`; exact caller pane |
| Windows Terminal, `--here` | Windows, `wt` on PATH, and the person's explicit `--here` (MCP `here: true`) | `wt -w 0 split-pane -V`; the window the person is working in, never the default |

On macOS or Linux outside tmux, with tmux installed, `launch` and `join --launch`
join the thread's one detached tmux session (`convoy-<8 hex>`; the first neuron
creates it with `new-session -d`, later ones `split-window -t =<name>:`) instead of
refusing. The card says `placement: detached` and gives `attach`
(`tmux attach -t =<session>`). The session is created synchronously, so a
refused `new-session` is reported as not launched. The MCP `launch` tool, behind
the write gate, does the same.

Other terminal hosts fail closed with a manual-pane instruction. Convoy never
injects keystrokes or guesses an iTerm, Terminal.app, WezTerm, kitty, or shell
API. Source installs currently require Python 3.11+; the project exposes a
cross-platform `convoy` console entry point, but a machine without Python still
needs a packaged executable/runtime before a skill can invoke it.

Creation and closure are separate capabilities. The Windows Terminal CLI can
create a split but does not expose its `closePane` action. A killed TUI may leave
an exited pane visible under graceful `closeOnExit`, so absent process IDs are
not pane-close proof. New targeted launches therefore use a Convoy lifecycle
host: after a separate, scoped `close-chair` consent it terminates only its owned
child tree and exits zero. Legacy panes still require `Ctrl+D` or the configured
`closePane` binding. First-run harness trust prompts are also user decisions;
Convoy returns an `awaiting-user-consent` card and never auto-accepts them.

## Resume: what works today, and what is being improved

**Resume is an area to improve.** Convoy only resumes a neuron's conversation when it knows the
harness's own id for it, and today it learns that id for two harnesses only. For the others, the id
is recorded only if someone writes it on the neuron's row. So a relaunch may start a fresh
conversation instead of continuing the old one.

**Before you promise a person that a neuron will resume**, read the dry plan:
`convoy --root <root> resume --neuron <id>` (without `--go` it launches nothing). If the argv carries
the harness's resume form with an id, it will resume. If it carries a declare flag (`--session-id`,
`-s`) or no id at all, it will start a new conversation. Say so.

| Harness | Resume command | Where the id comes from, and when | Evidence |
| --- | --- | --- | --- |
| `claude` | `claude --resume <id>` | Convoy mints the id before the first launch and declares it with `--session-id <id>`. Every later launch resumes it once the conversation's file exists at `~/.claude/projects/<worktree slug>/<id>.jsonl`. | ran: a session declared with `--session-id`, then relaunched with the argv Convoy builds, answered from the same conversation |
| `grok` | `grok --resume <id>` | The same minting: declared with `-s <id>` on the first launch, and resumed once `~/.grok/sessions/<URL-encoded worktree>/<id>/` exists. | help: `-s, --session-id` is for a new conversation only; the resume path is covered by tests, not yet by a live run |
| `codex` | `codex resume <id>` | Not captured. No launch flag sets the id; record it with `convoy seat --resume <id>`. | help |
| `cursor-agent` | `cursor-agent --resume <id>` | Not captured. No launch flag sets the id; record it with `convoy seat --resume <id>`. | help |
| `agy` | `agy --conversation <id>` | Not captured. No launch flag sets the id; record it with `convoy seat --resume <id>`. | help |
| `hermes` | `hermes --resume <id>` | Not captured; record it by hand as above. | help |
| `pi` | `pi --resume` | Not captured. `--resume` opens a session picker; resuming a given id directly is unverified. | help |

What is being improved:
- capturing the harness's own id automatically for every harness, not only the two that let Convoy
  choose it at launch;
- recording each harness's resume command, and the evidence for it, in the harness contract.

## How it works

1. Start Convoy on your machine (`convoy mcp`) and attach `http://127.0.0.1:8788/mcp`.
2. Run `onboard` with harnesses you already installed.
3. Bind one thread at `--root`; Convoy writes/reads one durable `convoy_id`.
4. Use `send` for synapses. A send that names a live seat **queues** the body
   (`delivery: queued`, `delivered: false`); it does not type into the TUI and
   does not spawn a second `--resume`. Codex may use `codex queue`. Drain with
   `convoy inbox --drain` or the project hook `convoy inbox --hook-pretooluse`
   (Grok PreToolUse, Claude PreToolUse + UserPromptSubmit). Hook files never
   bake an absolute interpreter path.
5. Use `bring_up` / `open` only when you want visible interactive TUIs for seated neurons.

## End-to-end example

```bash
# (after `python -m pip install .`, see Install)
# 1) Name installed harnesses and bind this root to one thread
convoy onboard --to grok --to claude --to codex --thread demo

# 2) Register seated neurons (session key + optional vendor resume token)
convoy seat --to grok --session-id seat-grok --worktree ../wt-grok --model gpt-5.6-sol --resume vendor-grok-uuid
convoy seat --to codex --session-id seat-codex --worktree ../wt-codex --resume vendor-codex-uuid

# 3) Dry-run bring-up shows native argv (Codex uses "resume" subcommand)
convoy bring-up --dry-run

# 4) Headless synapse (safe default)
convoy send --to claude "Summarize open payment retry bugs and propose a fix plan."

# 5) Optional live headless run in a fresh native session (no resume token)
convoy send --to codex --live "Draft unit tests for the retry planner."
```

Development: the supported source-checkout test entrypoints are
`PYTHONPATH=src python test/run.py` (PowerShell: `$env:PYTHONPATH='src'; python test/run.py`)
and `python -m unittest` from the checkout (for example,
`python -m unittest discover -s test/demo -p '*_test.py'`). Both discover
`test/demo/*_test.py` and isolate `CONVOY_HOME` under
the OS temporary directory, even if it was set to a non-temporary path.
Other test adapters, including direct top-level discovery by IDEs or pytest,
must be given their own throwaway `CONVOY_HOME`; their startup shapes are not
covered by this guard.
License: MIT.
