# Convoy

**Repo:** `https://github.com/Deploy-Forward/convoy` (local-first multi-agent orchestration CLI and loopback MCP)
**Plugins:** `https://github.com/Deploy-Forward/plugins` (the convoy and worklanes plugins for each harness)
**Sibling:** `https://github.com/Deploy-Forward/deploy-forward` (`npx deploy-forward`, tracker, board)
**Audience:** engineers who can read a CLI, a JSON card, and a git checkout.
**MCP:** runs on your machine at `http://127.0.0.1:8788/mcp` (`convoy mcp`). There is no hosted Convoy endpoint. Names: see `CANON.md`.

This file is the source of truth for **this repo only**. Sibling products keep their own specs.

Convoy lets you stay in one thread and send work to other harnesses (Grok, Claude, Codex, cursor-agent, agy) without merging their native sessions. The other harness works on its own meter. You get a compact result back. Main context stays skinny.

That sentence is the product. Everything below is how it is actually true, or honestly not true yet.

Landscape / Herdr comparison (positioning only; does not override locks below): [docs/LANDSCAPE_RUNTIME_VS_SOT.md](docs/LANDSCAPE_RUNTIME_VS_SOT.md).

Bring your own harness. Do not bring your own API key into Claude Code. Named refuse: UltraCode-Shim (OnlyTerp). We do not wrap Grok as `claude-grok-4-6`. We do not proxy `cli-chat-proxy.grok.com`.

---

## Canonical lock (2026-08-30)

This block is authoritative for the conductor's MCP layering and native-send DoD. If older notes below disagree, this block wins until they are rewritten.

### Terminology lock (2026-09-01)

- Grok Bot = conductor.
- neuron = one grok/claude/codex/cursor-agent session on a thread.
- synapse = native `send` into that neuron (not `ola-brain side-chat`).
- thread = durable circuit (`convoy_id`).
- named thread = `--root` binding, not a second MCP URL.
- Product wording retires "hop" in current product sentences; historical logs below may still quote it.
- Harness self-identity: first-run writes an `AGENTS.md` pointer (in a minted worktree, or with `--write-repo-files`), one paragraph naming the convoy plugin's `convoy-operate` skill and `convoy-dictionary`, so a launched model knows it is a neuron on a `cvy_id`. Skills ship from Deploy-Forward/plugins; Convoy writes no skill text and deletes nothing in a worktree.

### Feed contract v2 (2026-09-01)

One MCP endpoint. What is versioned is the feed contract, not the URL — a named thread stays a `--root` / `cvy_id` binding.

- `schema_version: 2` rides feed envelopes (MCP `feed`, CLI `feed --since`, the `attach` card). Not a second feed format: `.convoy/feed.jsonl` stays the single `layer.py`-written file, v1 rows keep flowing, and readers skip kinds they do not know.
- Kinds are additive. v2 defines:
  - `conductor` — ONE compact line stamped by the conductor (MCP tool `stamp`, CLI `python -m convoy stamp`). Front-matter shape: `agent` / `model` / `effort` real-or-null, optional `instance_id` (the conductor agent id) and `transcript` (a pointer to where the bubble lives, never its bytes). Summary clamps to one line of ≤ 500 chars; a clamp marks `truncated: true`. The Grok Bot bubble history is not a Convoy object; neurons never receive it.
  - `synapse` — unchanged.
  - `refuse` — the feed row now carries the full `ask` card (`action: bring_up`, `handoff: .convoy/handoff/<chair>-<ts>.md`, text), so a sibling pulling `feed --since` sees the remedy without having been the caller.
  - `heartbeat` — an attributed neuron lifecycle row. Automatic Codex/Claude `Stop` hooks record `event: turn-end`, never git mutation. Explicit `convoy end` records `event: task-end`; only its literal `--push` flag authorizes one plain `git push` after clean/attached/upstream checks. Vendor session/turn ids and assistant messages are never stored; duplicate Stop invocations carry only an opaque derived key.
- Pack stays pointers. Unknown stays JSON `null`. Neurons pull the thread (`feed --since`); nothing in v2 mints a sibling session or steals a TUI.

### Feed contract v2.1 (2026-09-01, additive — stress-test increment)

Locked from the stress findings (audit trail: docs/audits/; further artifacts live in the session worktrees that produced them). Additive only; v1/v2 rows keep flowing.

- **Attributed author `from` + addressee `to` on rows (corrected after a verified defect).** `from` is AUTHORSHIP and appears ONLY where an author is actually claimed: note-family rows (`hook`/`neuron_note`, default `author` = `instance_id`) and conductor rows (`stamp`, `from: "grok-bot"`). On `synapse`/`refuse` rows `instance_id` is the row's SUBJECT — the target/spawned session — so `from` is **absent** there (`author=None` at the call sites): sender-unknown recorded as absence, never as a confidently-wrong name. (The original v2.1 wording let `hook` promote any `instance_id` to `from`, which put the RECIPIENT in `from` on every synapse row — a live defect.) `send` has no caller identity yet; giving it one (`from` = caller) is a future increment that must land before any @-addressing surface reads these keys. `from` remains claimed-not-authenticated. `grok-bot` stays refused as author under normalized aliasing (both `instance_id` and `author`); conductor identity is `stamp`-only. CLI: `hook ... --to X`.
- **`to` disambiguation (pre-existing key, two meanings).** On `note`/`conductor` rows `to` is the addressee. On `synapse`/`refuse` rows `to` remains what it always was: the send-target harness name. Readers filtering "rows addressed to me" must filter on kind `note`/`conductor` first; a bare `row["to"]=="claude"` filter also matches every send to the claude harness.
- **`note` — the neuron-side write, symmetric to `stamp`.** `layer.neuron_note` / MCP tool `note` (args `summary`, `instance_id` required, `to` optional): kind `note`, same one-line ≤500 clamp as stamp (`truncated: true` on clamp), refuses anonymous or conductor-alias authors. This is the neuron-side write path over MCP; local neurons may keep using CLI `hook note`.
- **Runner provenance on synapse rows.** Every synapse row stamps `runner` (`"native"`/`"fake"`/`"ola"` by function identity via `synapse.runner_kind`, else the runner's name) and `argv0` (from the card's argv, JSON `null` when absent) — so the SoT can distinguish a native vendor send from a fake ACK. Rows without these fields predate v2.1 and are not evidence of a native send.
- **Build id on the wire.** `initialize` `serverInfo.version` is `<base>+<git describe --always --dirty>` (base 1.4.1) when the package sits in a git checkout (`-dirty` marks a patched-in-place deploy), the bare base version when unknown (never an invented sha). A hung/missing git degrades to the bare version — it must never stop the server (`OSError` and `SubprocessError` both caught). Scope honesty: one-call drift detection holds only for git-checkout deploys; the bare-version fallback is indistinguishable from a pre-v2.1 deploy.
- **One local server, many threads.** `convoy mcp` serves every thread in the machine index and each call names its thread (`thread` or `convoy_id`); `--root` pins one, and a named thread still wins. A read routes by a thread from the index, never by an arbitrary path (arbitrary-path read hole); only the write-gated `onboard` takes a checkout path. Rebinding a thread to flip a test GREEN is refused.
- **Write-tool gate.** The RPC layer never exposes SoT write tools (`stamp`, `note`) to a caller without identity: with no bearer minted they are absent from `tools/list`, and `tools/call` refuses them unless the request carries a checked conductor bearer (`convoy conductor mint`, sent as `Authorization: Bearer`). There is no process-wide switch; `CONVOY_MCP_WRITE_TOOLS` was removed in 1.3.2. The CLI is not gated.
- **Loopback only (1.3.2).** The MCP HTTP server binds only a loopback address (`--host` other than `127.0.0.1`, `localhost` or `::1` is refused) and serves a request only when the peer is this machine's loopback, its `Host` is `127.0.0.1`, `localhost` or `[::1]` on the port it listens on, and any `Origin` is an `http://` loopback origin on that same port; a non-loopback peer is a 403 on every method whatever `Host` it sends, and anything else is a 403 before identity or body (DNS-rebinding defense, required by the MCP Streamable HTTP transport). No response carries CORS headers. The desktop widget's local server applies the same checks. A GET through a proxy header is a 404; a loopback `GET /` is one line of text naming the version and the thread count; `GET /mcp` is a 405. Remote access to your loopback MCP is not a Convoy feature; if you build it, put it behind your own access control.
- **Chip front matter (conductor render contract).** The chip a neuron message surfaces with (`harness / model / effort / session% / week% / convoy_id / vendor session id / worktree / summary`) renders from two existing reads, no jsonl archaeology: the `note` row carries `summary`/`from`/`to`; the glance by-thread seat card carries `to` (harness), `model`, `effort`, `resume` (vendor id), `worktree`, `session_pct` (from the headless `claude -p /usage` probe via `usage.surface`); `week%` comes from glance **Overall** (locked: never duplicated per-thread). `effort` is a declared seat field (`seat --effort`, real-or-null) — validated per harness against `harness_effort.json` keys (grok `xhigh`, codex `extra-high`, pi `--thinking` levels; a refusal names the harness's real keys). Convoy applies it to argv when, and only when, the contract carries `cli_flag` + an `evidence` string (grok `--reasoning-effort`, claude `--effort`, agy `--effort`, pi `--thinking`); the seat row's `effort_applied` records which (`false` = recorded, not applied: codex, cursor-agent, hermes; `null` = no effort declared). `choices` carries `harnesses[].effort = {mode, keys, cli_flag, evidence, applied}`. Unknown `effort`/`resume`/`model` are omitted from the card, never "unknown". No probe ⇒ usage stays null.
- **`notify` stays JSON `null` per harness** until a documented injection point is proven live. Not a tool, not a promise.

Unit: `test/demo/feed_note_provenance_test.py` (15 tests).

### Seat lifecycle: join / swap / seated

The seat is the chair; the neuron is the occupant. Chair identity is
`session_id`, full stop — `resume_key` hashes `(convoy_id, thread, to,
worktree)` and legitimately changes when the occupant's harness changes: it
is a resume MAP key, never seat identity.

- **`swap --seat S --to H [--model M] --handoff F --as AUTHOR`** replaces the
  occupant, never the chair. NEURON-authored always (the conductor asks via
  `stamp`; `from: grok-bot` has no legal author path on a swap row). Ordered,
  fail-closed: fresh handoff file required → kind `swap` row stamps FIRST
  (`from`=author, `to`=chair, `swap_to`, `token`, `memory: "convoy-state"`)
  → field-preserving `update_seat` (never bare `seat()`: whole-row last-wins
  blanks unpassed fields) with `resume` AND `vendor_session_id` nulled on
  EVERY swap — the ordering lock (close only after proof of life) + the
  no-steal lock forbid two live processes on one vendor session, so **no
  swap ever carries a vendor transcript; swap memory is Convoy state,
  always** → `bring_up` with a one-shot `boot_prompt` delivered as an
  initial POSITIONAL prompt (blessed exception; not `-p` — the session stays
  interactive): read thread.md + handoff (each only when it exists), echo
  the token.
- **`seated --seat S --token T`**: proof-of-life — the replacement echoes the
  token as kind `seated` and the boot prompt clears. The outgoing pane must
  not close before this row exists; then "safe to close" + optional `hide`.
  The outgoing neuron MAY exit itself; **Convoy never closes a window.** The
  latest `seated` row per session_id names the chair's current occupant.
- **`join --to H [...]`**: a new chair — `seat` + boot prompt + kind `join`
  row. Newcomer rehydrates from thread state, never a vendor transcript.
- **Token-to-harness binding:** seat rows carry `resume_for` (minting
  harness, attributed); `resume_target` returns a token only on match, BOTH
  `vendor_session_id` and `resume` guarded — a stale token can never ride
  another harness's argv (cross-harness impossible by construction). Legacy
  rows without `resume_for` are whole-row writes: minted under their own
  `to`. `live_on_branch` dedupes by session_id: one chair is one agent.

Unit: `test/demo/seat_lifecycle_test.py` (15 tests).

### Launch identity: launched_by, attach-on-launch, report / reply

A neuron is either the lead or not, and it knows which; when the lead did not
launch it, it knows which neuron did. Live failure behind this: an unseated
session ran `start` and `add codex` twice; both neurons, asked to report to the
lead, found no lead and no record of who launched them, and their boot prompt
pointed at a `thread.md` that did not exist.

- **Launcher resolution** (`launcher.resolve_launcher`): every path that seats
  and launches a neuron (`add`, `crew`, `join --launch`, `launch`, `bring-up` /
  `open`) resolves the launching session once with `identify` (one attempt at
  the process table, 30 s). Environment or token proof is strong; a cwd or
  worktree path match, a pane-host record alone, a script with no harness and an
  unreadable table are not. Read-only.
- **launched_by** on the new seat row:
  - launcher seated on this thread with strong proof: `launched_by: <its chair>`;
  - launcher NOT seated but its native session id is proven (environment or
    token): it is **attached first**, through the same code as `convoy attach`
    (`sessions.attach_proven`): a new chair holding that native id, a kind
    `seated` row, a kind `attach` row, and it **takes the lead when the lead is
    none or dangling** (the attach rule; a held lead is kept). Then
    `launched_by: <that chair>`. This changes who leads a fresh thread: the
    session that launches the first neuron becomes the lead. The card's
    `launcher` block says `attached: true`, `lead_taken`, `lead_was` and a line;
  - no proof (a cwd or path match only, a script, a conflict, an unreadable
    table): the launch **refuses before any write**: no worktree, no chair, no
    claim, no attach, no lead change, `ok: false`, `error: "cannot prove who is
    launching"`, `next`: run it from an agent session or `convoy attach <thread>`
    first. A dry run reports `would_refuse` with the same reason. No launch
    records `launched_by: null`; legacy rows that carry it are still read.
  A session may hold one chair on each of any number of threads, so a session
  seated on another thread is attached here as above, never refused.
  The launcher is acted on only once the chair exists: `add`, `crew` and
  `join --launch` attach and record after every join succeeded, so a refused
  join or a failed mint attaches nobody and moves no lead (a dry `add` attaches
  nobody and shows `would_attach`). `launch` and `bring-up` act before the spawn
  (accepted: the chair exists and this session is launching it) and record on
  the chairs that invocation spawns: the record is written before the spawn (the
  prompt must carry it) on each chair with a pending boot prompt and no live pane
  host, then put back on every chair the verb did not spawn. A refused launch
  records nothing, and a chair another session already launched (its pane host is
  alive) is skipped by `bring-up` (`skipped[]` on the card; never a second pane;
  the card's `launched[]` names the chairs a pane was spawned for, and when every
  chair named was skipped `ok` stays true with a plain `note`: nothing launched)
  and keeps its `launched_by`; the card's `launcher.recorded_on` names only the
  chairs spawned. The record is written only under the chair's launch claim: the
  CLI takes the O_EXCL reservation first, so of two launches of one chair only
  the claim holder records and settles (the other refuses, or bring-up skips the
  chair with the reason), and the spawn runs inside try/finally, so a spawn that
  raises (a wt failure, a Ctrl-C) settles with nothing spawned and releases the
  reservation. A reservation records the process that took it (`reserver_pid`
  and its start time); a claim whose holder (its host, else its reserver) is dead
  has expired and the next launch adopts it (a reservation, whose launching CLI
  exits right after wt returns, only once it is also older than 30 s, so the
  handoff to the pane host is never taken over; a dead host expires at once; the
  judged bytes are re-read before the unlink and the new claim is O_EXCL, so of
  two adopters exactly one wins), so an invocation that crashed
  between claim and spawn never blocks the chair (a claim naming no holder cannot
  be judged and still refuses). A live pane host is its pid AND its start time (the claim
  records `host_started`: the creation time on Windows, the start tick from
  `/proc` on Linux; macOS gives none, and there the pid alone decides), so a pid
  the OS reused for another process never reads as the host. A chair that joins itself records nothing. An MCP
  launch (`crew`, `join`, `launch`, `bring_up` with `dry_run: false`) records
  the conductor its bearer proves: `launched_by: {"kind": "conductor", "name":
  <conductor>}`, on the chairs it spawns (put back on any it did not); with no
  bearer the write gate refuses it before anything is recorded or spawned, and
  an in-process call with no launcher refuses with "cannot prove who is
  launching". A chair launcher keeps its string shape (`launched_by: <chair>`);
  readers take both (`launcher.launcher_of`: a dict without a kind is a chair).
  `add` and `crew` called with no launcher at all refuse the same way, so no
  caller can launch without naming one. A chair launcher must be a seated chair
  on that thread (`seat_launcher` refuses a name that is not one, or a detached
  chair). An MCP launch checks and records under the chair's launch-claim lock
  and skips a chair whose launch claim a live process holds, so it never
  overwrites a CLI launch in flight. A swap clears the old occupant's launcher:
  the new occupant's prompt says `Launched by: recorded when this chair is
  launched`, and the launch that spawns it records its launcher (the swap CLI
  takes `--as` as an assertion, not a proof, so the swap caller is not
  recorded). `adopt` refuses a chair whose boot prompt is still pending: "this
  chair has not launched yet; its launch will record its launcher". The widget is a person's local UI with
  no agent session to prove: a widget launch (a start with seats) records the
  thread's held lead chair as `launched_by` (the plain chair string, so its
  neurons report to the lead) and the card says `launcher.source:
  "widget-lead"`. With no held lead (none or dangling) it refuses before writing
  a chair: "this thread has no lead: attach an agent session (convoy attach
  <thread>) so it can lead, then start again". It never guesses a launcher and
  never records null.
  The boot prompt then reads `Launched by: conductor <name>`, `whoami` shows
  `launched_by: {kind: conductor, name}`, `convoy report` writes a proven note
  (environment, token or pane-host) from the chair addressed `to=<conductor>`,
  which the conductor's `replies {since}` cursor returns (it filters by
  addressee, not by token), and `adopt` treats a conductor launcher as live
  (only the lead replaces it).
- **Boot prompt** (`lifecycle._boot_prompt`), one line: the seat, `Read` only
  the files that exist (`thread.md`, the handoff; a thread started without a name
  has no `thread.md`, so none is named), the `seated` ack with its token, then
  information only: `Lead: <chair> (neuron <id>, <harness>).`, or `Lead: you`,
  or `Lead: none (<reason>)`. A lead is named only when a kind `lead` row names
  that chair; a chair that merely matches the lead file's harness is never told
  it leads (the reason then says which harness the lead file names); `Launched by: <chair> (neuron <id>).`
  (a legacy row with no launcher reads `Launched by: not recorded; ask the
  person or your conductor to run convoy adopt --id <id>`), or `Lead and
  launcher: ...` named once when
  they are the same chair; and two commands: `Report results with: convoy --root
  <root> report "..."` and `Answer a message with: convoy --root <root> reply
  <token> "..."`. No routing rules in prose: routing is the code below. This
  identity tail is composed again right before a spawn (`launch_seat`,
  `bring_up`, `lifecycle.refresh_identity`), after a swap's seat change, so a
  pending prompt names the lead and launcher as they are at launch. A relaunch
  prompt (`relaunch.relaunch_prompt`) carries the same tail and no wait or wake
  instruction: each harness receives by its own route.
- **`whoami`** on a seated chair adds `lead` and `launched_by`, each
  `{chair, neuron_id}` or null. The existing fields are unchanged.
- **`report "<text>"`** (`route.report`): the caller's chair by `identify`,
  with environment, token or pane-host proof (a cwd or worktree match refuses with why);
  sends to its `launched_by` chair; when that is null, no
  longer a seat, or detached, to the lead. The lead with no live launcher
  refuses; no launcher and no lead refuses; both with `ok: false` and `why`. The
  send is the ordinary send path (fake runner, sender = the proven chair), so
  wake and delivery are those of `send`; the card adds `routed_to`, `route`
  (`launcher` | `lead`) and `route_why` on a fallback.
- **One session, several threads.** A native session may hold one chair on each
  of any number of threads (`sessions.proven_session_chairs` returns every
  active (root, chair) from one process-table read). `attach` and a session
  joining itself never refuse because the session sits elsewhere; the attach card
  lists the others in `also_on`. The hooks that run without a root act on every
  thread the session sits on: the inbox hook drains and delivers each thread's
  inbox, each row labelled with its thread and its reply command, and the Stop
  writes a heartbeat and stamp on each, all from the hook's one read (2 s inbox,
  3 s Stop). A command that needs exactly one thread (`whoami` with no root,
  `detach` without `--thread`, a manual `end`) refuses with the list: pass
  `--root` or `--thread`. `report`, `reply` and `send` take `--root`. Acting on
  thread A with `--root A` from thread B's folder is normal: when the caller is
  proven on A by environment or token, `identify` reports the cwd as
  `cwd_thread_differs: {cwd_thread, root_thread, hint}`, not `conflict`. A real
  disagreement (environment and token naming different chairs, or a path chair
  contradicting an environment chair on that root) still refuses with
  `via: conflict`. `adopt` from a proven caller whose own chair on the thread is
  detached re-attaches it (the attach path, with its lead rules) and proceeds;
  so does a launch: adopt and launch re-attach a caller who detached on purpose.
  The cwd relaxation applies only to an explicit `--root`: an inferred root
  (from the cwd, `CONVOY_ROOT` or a neuron id) keeps `conflict` and its ask. That
  changes only what the identity record reports (`cwd_thread_differs` instead
  of `conflict`), never whether a launch, adopt, send or reply proceeds: with an
  inferred root the cwd chose the thread, so a launch goes there and attaches
  its launcher there. A path proof (a pane-host record, a worktree in the
  argv, the cwd) never identifies a different session than the caller's own
  native id proves: that id recorded as a chair on another thread refuses the
  path's chair with `ok: false`, `via: conflict` and an ask naming both chairs.
  A body with no native id still resolves by path. A
  session on several threads cannot use the native-id plus unique-cwd shortcut,
  so every one of its hooks pays the process read; the Stop budget (3 s read,
  then per thread a git snapshot, handoff and heartbeat) assumes up to about 4
  threads on one session. A PostToolUse runs the vendor usage probe at most once
  per harness and stamps every chair of that harness from that one reading. A
  worktree serves one thread: a chair is never seated in a worktree whose root
  pointer names another thread (the seat refuses with the reason). The lead
  override in `adopt` counts only a lead held before the adopt began, and adopt
  refuses a detached neuron before writing, writes by compare-and-set under the
  chair's launcher lock (the lock every launcher record takes), and puts the
  previous launcher back if its message cannot be sent.
- **`adopt --id <neuron id>` / `--seat <chair>`** (`adopt.adopt`): makes the
  proven caller (environment, token or pane-host; an unseated caller is attached
  first, as a launch does) the launcher of an existing neuron whose
  `launched_by` is missing, null, or names a chair that is gone or detached. A
  live recorded launcher is replaced only by the thread's lead, and the card says
  so. It then sends the neuron one message from the caller: `Your launcher is now
  <chair> (neuron <id>). Report with: convoy --root <root> report "..."; answer
  messages with convoy reply <token>.` The card carries `previous_launched_by`,
  `launched_by` and the send `token`. `report` refusing for want of a launcher
  and a lead names this fix: ask the person or your conductor to run `convoy
  adopt --id <your neuron id>`.
- **`reply <token> "<text>"`** (`route.reply`): the caller's chair by
  environment, token or pane-host proof; finds the send carrying that token; refuses an unknown token and a caller that was not its recipient;
  writes a `note` from the caller's chair, addressed to the send's proven
  sender (through `receipt_address`), with `token=<token>` in the summary: the
  receipt the sender's `replies` counts as delivered. `replies(token=)` counts
  only a note whose author is proven by environment, token or pane-host
  (`conductor.RECEIPT_PROOF`, the one proof set: `convoy reply`/`report` require
  it and `inbox.reply_index` uses it to clear a pending row, so a cleared row and
  a counted receipt never disagree), not claimed: a claimed note, or one placed
  only by a worktree or cwd match, is a row, never a receipt. Both citation
  spellings count everywhere: `token=<t>` and `re token <t>`. A cursor-agent,
  agy, hermes or pi chair under a pane host delivers by pane-host proof. A chair is a body that can run the CLI; an MCP-only
  actor is a conductor, and conductors never author notes (rule 4).
  `conductor.md` (rule 6, the delivered row) says so, and the MCP instructions,
  built from it, cite its sha (taken from the LF text, so a CRLF checkout cites
  the same sha). The MCP `note` tool
  writes claimed notes and its response says so (`receipt: false` and a
  `receipt_note` naming `convoy reply <token>`).
- **Tests never prove a real session.** The shared test guard
  (`test/home_guard.py`) clears `panes.NATIVE_SESSION_ENV` and `CONVOY_ROOT` for
  the run (restored at exit) and sets `launcher.TEST_DEFAULT_PROCS = []`, so a
  launch under test reads no real process table; a test opts in with
  `panes._TEST_PROCS` or `procs=`. It also clears the terminal placement
  variables (`WT_SESSION`, `WT_PROFILE_ID`, `TMUX`, `TMUX_PANE`), and
  `test/harness_guard.py` refuses any real `wt` or `tmux` spawn unless a test
  opts in with `allow_real_terminal()`: an inherited `WT_SESSION` would make a
  test split real panes in the developer's own window. A direct `python test/demo/x_test.py` run
  imports no test package and is not covered.

Unit: `test/demo/launch_identity_test.py`.

### Placement: one terminal window per thread

Windows Terminal's CLI cannot split a specific pane: `wt -w 0 split-pane` splits
whichever pane has focus in the most recently used window, so a neuron landed
wherever the person had last clicked. On Windows every launch on a thread (`add`,
`launch`, `join --launch`, `crew --launch`, `bring-up`, `relaunch`) now targets
the thread's own named window:

- the name is `convoy-` + the first 8 hex of sha256(convoy_id)
  (`targeted_launch.thread_window_name`): deterministic, short, safe, never
  numeric (wt reads a number as a window id), never `0`;
- the first neuron opens it: `wt -w <name> new-tab --title T -d DIR <host argv>`;
  a later one splits inside it: `wt -w <name> split-pane -V ...`. "First" means
  no other chair of the thread has a live pane host (its claim's pid and start
  time match a running process);
- never window `0`, never the caller's window: `WT_SESSION` decides nothing, and
  the wt argv validator refuses any target other than `-w convoy-<8 hex>`;
- the card says `placement: thread-window` and `window: <name>`;
- the window's tab shows the focused pane's `--title`, so every pane title in the
  thread window is `<thread label> - <chair title>`, and so is the tmux session's
  window name (`new-session -n`). The label is the bound thread name, else the
  repo folder name, plus `-<4 hex of the window id>` so it is unique per thread
  (two repos with one folder name never share it); with neither name it is the
  window's 8 hex. ASCII letters, digits and `. _ -`, at most 24 characters (the
  name is trimmed, never the hex), never a `cvy_` id or a path
  (`targeted_launch.thread_label`). The separator is ` - `, ASCII (a middle dot
  was not checked in WT);
- a composed title proves a chair to `nudge` and the wt walk only as that chair's
  OWN exact title (its thread's label plus its own title, `pane_title` on the
  seat row nudge reads). Another thread's label never proves it; a composed title
  never matches through the old `<seat title> - ` prefix rule (so a chair titled
  like a label matches no pane); two matching windows are ambiguous and refused;
- `split-pane` into an existing named window splits that window's focused pane
  (Microsoft's documented behaviour for `-w <name> split-pane`). Inside the
  thread's window that is one of this thread's own neurons, which is fine;
- Live-verified on Windows Terminal 1.24.11911.0: `wt -w convoy-livechk1 new-tab --title first -d <home> <absolute powershell.exe> -NoExit -Command ...`, then `wt -w convoy-livechk1 split-pane -V --title second -d <home> <absolute powershell.exe> ...`. Result: one separate window holding both panes side by side, the working window untouched, no Help dialog.
- still forbidden: `--` before the harness exe (pops GUI Help) and `-w 0`. The
  earlier live note that `-w <thread-name>` popped Help came from a different
  argv shape (the thread's own name as the window, in the old `--window new`
  era), not from `-w convoy-<name> new-tab|split-pane -d DIR <absolute exe>`.

#### Placement `here`: an opt-in split of the person's own window

`add --here`, `launch --here` and the MCP `launch` tool's `here: true` are the
person's explicit opt-in to the one thing the default never does: a split of the
window they are working in. It is never the default.

- Windows: `wt -w 0 split-pane -V --title <label> - <chair> -d <worktree> <host argv>`,
  built by the same pane-command builder the thread window uses
  (`targeted_launch.active_pane_argv`), with `-w 0` allowed only for this placement
  (`-w 0` is the most recently used window, i.e. where the person is, which is
  what `--here` means). Always `split-pane`, never `new-tab`, never `--`. The
  `-w 0` refusals in `isolated_wt_argv`, `_check_thread_window` and
  `active_pane_argv` stay for every other placement;
- inside tmux: the existing `split` of the caller's exact pane;
- POSIX outside tmux (and Windows without `wt`): refused before anything is
  written, naming `thread-window` and `detached` as the alternatives. It never
  falls back to a detached session;
- the card says `placement: here`; no `window`, no `attach`;
- `--dry-run` prints the exact wt argv.

Unit: `test/demo/launch_here_test.py`.

tmux keeps splitting the caller's exact pane when the launch runs inside tmux
(`TMUX_PANE` names it). Outside tmux, with tmux installed, one detached session
per thread mirrors the window: the same `convoy-<8 hex>` name, `new-session -d -s`
for the first neuron and `split-window -t =<name>:` for later ones; the card's
`attach` opens it. Every tmux split (of the caller's pane or of the detached
session) is chained with `; select-layout -t <target> tiled`, so a window of many
neurons stays a grid of usable panes; `new-session` is not.

Unit: `test/demo/thread_window_test.py`, `test/demo/convoy_add_test.py`.

#### crew: N neurons with one task (1.4.0)

`crew --seat SPEC [--seat SPEC ...] [--launch]` mints one worktree per local seat,
joins every chair with a boot prompt and brings them up in the thread's one window
with a single wt argv. Three options build on it:

- `--count N` repeats the one `--seat` SPEC N times. Titles are `<harness>-<i>`, or
  `<title>-<i>` when the SPEC has `title=`. `--count` beside a second `--seat` is a
  usage error, and N is 1..16: above 16 crew refuses before anything is written
  ("crew --count is capped at 16 per call; run crew again on the same thread for
  more"). The MCP `crew` tool takes the same optional integer `count`, through the
  same code (`crew.expand_count`).
- `--brief TEXT|@path` (MCP `brief`): after `--launch`, crew waits for every chair
  to seat (`await_seated`, `--brief-timeout`, default 300 s; MCP `brief_timeout`,
  at most 600) and then sends each seated neuron its copy through the path `convoy
  send` takes (`send_one` to the chair's id: one inbox row and one token per
  neuron, a `synapse` feed row, `delivered: false`). Nothing is typed into a pane.
  Each copy starts with one line: "You are neuron <i> of <N> on thread <thread>
  (crew <first seat id>). Coordinate through Convoy notes; claim your share before
  starting." The card's `briefs` lists per neuron `{neuron_id, session_id,
  worktree, send_token, seated}`. A chair that does not seat in time gets
  `seated: false`, no send and a line in `warnings`, and the card's `ok` is false;
  a crew that did not launch sends no brief. Without `--launch` the card carries
  the planned copies (`briefs[].brief`, `brief_sent: false`) and sends nothing.
- `--here` splits the person's own window (`wt -w 0 split-pane`) and takes at most
  four neurons; for more it refuses before anything is written ("--here takes at
  most 4 neurons; drop --here to open them in the thread's window in tabs").
- Canary first (default on; `--no-canary`, MCP `canary: false`, opts out). Model
  ids pass through unverified, so a `crew --launch` of more than one local neuron
  launches the first seat alone, waits for it to seat (`--canary-timeout`, default
  120 s; the same seated-ack reading as `await_seated`, also stopping at the pane
  host's harness-exit row), and only then launches the rest in one more wt argv
  that continues the layout from pane 2 of tab 1 (the canary is pane 1). A canary
  that does not seat in time, or whose harness exits, stops the rest: their chairs
  stay joined, each marked `launched: false, reason: "canary_failed"` in `seats`
  and `not_launched`, with a `launch --seat` per chair in `recovery`; the canary's
  own error (the exit code and stderr tail, or the await reason) is in `warnings`,
  `canary` holds the verdict, and `ok` is false. A failed canary sends no brief.
  A crew of one has no canary step. A dry pass waits for nobody and names the
  canary in `canary_plan`.

Layout: up to four panes keep the chain above (`new-tab`, then `split-pane -V`,
then `split-pane -H`). More than four tile in tabs of four, each a 2x2 grid, in
the same `-w convoy-<8 hex>` window: pane 1 of a tab is `new-tab` (the launch's
first pane keeps the `first` rule: `split-pane -V` when the window already holds
neurons), pane 2 `split-pane -V`, pane 3 `move-focus left ; split-pane -H`, pane 4
`move-focus right ; split-pane -H`; pane 5 opens the next tab. One `-w` per argv,
literal `;` separators, never `--` before the harness exe. The `move-focus` shape
is live-verified on Windows Terminal 1.24.11911.0 (ten panes: three tabs of 4, 4, 2, each four
equal quadrants). Without `--launch` the card's
`planned_argv` is the wt argv a launch would spawn, built raw (no session minted,
no launch record written), so each pane shows the harness argv where a launch
runs the Convoy pane host that starts it.

Unit: `test/demo/crew_count_brief_test.py`.

### Bodies: panes + whoami (detect → identify → send)

The registry knows only what Convoy launched. In a live failure a codex
chair was running in an unmanaged pane, registry
liveness said false, a second `codex resume <id>` was launched and codex
refused ("already has an active writer"). Liveness therefore comes from the
OS process table too:

- `panes` (CLI + MCP): per chair `live`, `bodies[] {pid, via, exe}`,
  `duplicate` (two bodies on one chair), and `unassigned[]` harness
  processes Convoy cannot place — listed, never hidden. `via` is `token`
  (chair's vendor token in a command line; portable) or `cwd` (process cwd
  == worktree; Linux /proc, macOS lsof; Windows has no stdlib cwd, so that
  rung is null there and fresh Windows launches land in `unassigned`).
  Never prints a token. Enumeration failure ⇒ `source: null`, all not-live.
- `whoami`: walks the CALLER's ancestry (shell → harness) and names its chair
  by token, then by cwd; else null with an `ask` (join / seat this worktree).
  `hook … --as-me` authors as that chair and refuses otherwise: a body may
  send on a thread only after it is detected AND identified on it.
- `resume --neuron … --go` and every launch path consult `panes` before the
  registry; a live body on the chair refuses (no-steal).
- Close is unchanged: managed panes close through the consented pane host;
  an unmanaged body is `manual-close-required`, pid shown.

Unit: `test/demo/panes_test.py`. Live: `panes` on a demo thread
showed the lead chair with two bodies by token (duplicate=true) and several
unassigned harness processes on Windows.

### Delivery ladder: recorded → executed → delivered

A `send` card says what happened to the message, never more:

- `delivery: "recorded"` — a feed row exists; nothing reached a neuron (fake
  runner, dry run). This is what the default `send` has always done; the
  card now says so instead of an ACK body that reads like receipt.
- `delivery: "executed"` — a FRESH headless vendor session ran the body and
  replied. Not the open pane. Not the seated occupant.
- `delivery: "refused"` / `"error"` — nothing happened (no-steal, limited,
  wrapper, unknown instance).
- `delivered` is always `false` on a card. **Only an ack row authored by the
  target** (`seated`, or a `note` from that chair answering the addressed
  row) proves delivery; a card cannot author that. Readers: the receipt is on
  the bus, not in the return value.
- `wake` and `why` (codex chairs only) say what the wake path did, never that
  the neuron woke. `wake: "codex-queue-accepted"`: `codex queue` exited 0 for
  the chair's recorded session id. Accepted is not a turn started (a queued row
  was once found in Codex's own store for a dead pane), and only the neuron's
  own receipt proves delivery. `wake: "inbox-only"`: the row waits in the inbox
  and nothing woke the pane; `why` says whether no Codex session id was
  recorded (the plugin's hooks not trusted or not yet run) or `codex queue` did
  not run or exited non-zero. A dry-run card carries neither field. The id is
  recorded by the plugin's Stop hook, and only when the hook's own process
  ancestry shows a top-level body of the chair's harness (a nested `codex
  exec` stamps nothing; the ancestry is read only when the payload's id differs
  from the recorded one, and after the Stop heartbeat is written). A hook reads
  the process table at most once, in one attempt: the identity check and this
  gate share that read, and a failed read is not retried in the same hook. The
  Stop hook's read is bounded at a fixed 3 s, about 1.5x the slowest real read,
  so the read plus interpreter start plus the git snapshot fit under the
  plugin's 5 s hook timeout (worst case about 3.6 s); the inbox hook's at 2 s; the Stop heartbeat is written by the cwd's one chair even when
  the read fails. Callers outside a hook keep 3 attempts of 150 s. Each refusal is
  remembered per chair and id hash in `.convoy/hook-stamps.json` while the
  seat's recorded id and live pane-host body are unchanged: for good when it
  cannot change, for 10 minutes when it can (a failed read, a refused replace).
  A failed read records its budget and holds only against a hook whose budget
  is no larger: a failed 2 s inbox read never stops the Stop hook's 3 s read,
  and a failed Stop read holds against both. A first id is stamped even while a
  pane host owns a live body for the chair; that refusal is for a replace only.
  The Stop hook and the inbox hook stamp through this one gate. A different id replaces the recorded one only when
  all hold: a top-level codex body, the payload cwd is exactly the chair's
  worktree and no other chair sits there, no pane host owns a live body for the
  chair, and no replace for that chair in the last 10 minutes. A refused flap
  writes one `resume-flap` row ("two codex bodies in one worktree?"). A replace
  writes a `resume-changed` row carrying only hashes of the two ids; the
  incarnation is the pane host's and is never touched.

Current delivery path to an open neuron: `send` queues the inbox row;
`hook note` alone does not reach or wake its target. Use `send --id <neuron-id>`
on the CLI, or the named chair in MCP `send`. Cards can say recorded, queued,
native-queued, executed, refused or error; their delivered field is not proof.
Only a target-authored proven receipt citing the send token establishes delivery.
That receipt is a `hook note ... --as-me --to <sender>`, not a new brief.
A native queue, tool-time hook or enabled dispatcher-managed waiter supplies the
harness-specific wake path; a plain addressed note with no token is not one.

Unit: `test/demo/tools_delivery_test.py`. Also landed: `graph`, `threads`,
`resume` (dry; `go` behind the write gate) as MCP tools, so neurons attached
over MCP can summon them.

### Graph: the ontology of attributions over a thread (read side landed)

A thread is the **context**; the graph is the **ontology of attributions** over
it. Context is model-agnostic within a session (an in-session model switch
keeps the vendor UUID and transcript) and the chair survives the occupant, so
a neuron resuming anywhere needs two things: the thread pointer, and who else
is connected to it. `convoy graph` answers both from `seats.jsonl` +
`feed.jsonl` only — never a vendor transcript, never a token.

- **Nodes:** `thread:<cvy_id>`, `chair:<session_id>` (with `current`
  harness/model/effort, `resume: {available, for}`, `lineage[]`),
  `harness:<id>`, `model:<id>` (only when known — no placeholder node),
  `conductor:grok-bot`, `unknown:<name>` (a bus name that is not a chair).
- **Edges:** `seats` (thread→chair), `runs_on` (chair→harness, `current`
  true/false so history stays visible), `runs` (chair→model), `note` /
  `stamp` (from→to, attributed), `synapse` (`from: null` — send has no caller
  identity, sender-unknown recorded as absence).
- **Lineage** projects `join` / `swap` / `seated` rows per chair; a join or
  swap is `pending` until its `seated` ack, then `acked` with `seated_at`
  (unacked pending is a first-class state).
- **Attestation** is `attested` on every bus-derived edge (claimed, not
  authenticated). `observed` is reserved for a vendor-record reader that does
  not exist yet; the field exists so the upgrade is additive.
- **Resume is a boolean, never a token:** `resume.available` is true only when
  the seat holds a token minted for its current harness (`resume_for`
  match); a swap nulls it by contract.
- **`graph --neuron S`** is the rejoin card: the chair, the parties it has
  talked with, and `{convoy_id, thread, path, last_row_ts}` to resume from.
  Unknown neuron refuses.
- **`place` (the post-hook):** every neighborhood card
  carries the chair's self-knowledge — `last_contribution` (ts/kind/summary
  of the newest row it AUTHORED; synapse rows have no author and never
  count), `contributions`, temporal `rank` (1-based by latest contribution,
  newest first, `null` when it never wrote), `of` (chairs on the thread),
  `degree` (parties it has talked with), `lead`, `lead_chair`. A harness's
  post-tool hook can call `graph --neuron <me>` and know its place.
- **Lead is passed to an identified neuron:** `lead --to <chair> --as
  <author chair>` stamps kind `lead` (`from`=author, `to`=chair; neuron-
  authored, conductor aliases refused) and then writes the legacy
  `.convoy/lead` harness file so bring-up keeps its meaning. The latest
  `lead` row naming an existing chair is the lead; graph marks it
  (`lead: true`, a `lead` edge). `lead --to <harness>` is a pass to that
  harness's one seated chair under the same rules ("no chair of <harness> on
  this thread" when none, and a refusal naming them when several). The
  author of every lead change is the proven calling chair (environment or
  token proof; a cwd match is not enough); `--as` asserts it and refuses when
  it disagrees. A pass to a chair with no recorded session id refuses (it
  could never pass the lead on). Bare `lead` reports `lead` (harness), `lead_chair`,
  `dangling` and `reachable_id`.
- **The lead is reachable or none:** onboard and start never set a lead; a
  new thread's lead is null and the start card's where line says `lead:
  none`. A seated chair is a seat that is not detached. The lead is
  dangling when `.convoy/lead` names a harness with no seated chair, or when
  the chair the latest `lead` row names has detached (another chair of its
  harness does not inherit it); the where line then says `lead: dangling
  <harness>`. Only
  the current lead chair passes the lead; while it is unset or dangling, any
  seated chair may take it. `convoy attach` takes an unset or dangling lead
  for the attaching chair (a kind `lead` row from and to that chair; the
  card's `lead_taken.line` says `lead: taken (was none|dangling <harness>)`)
  and keeps a lead held by a seated chair. `reachable_id` is the lead
  chair's neuron id as `convoy list` shows it, or null. The lead and attach
  cards print `conductor` as the lead chair or null, never the hosted
  constant.
- **A receipt goes to the sender:** a note citing a token sent to its
  author, with no addressee, is addressed to that send's proven sender; a
  third party citing the token stays unaddressed; a note citing a token
  someone else sent to its author, addressed to the author itself, refuses.
- **One thread resolver** (attach, `detach --thread`, `lead --thread`): the
  exact `cvy_` id wins; otherwise a thread name, a root path or a unique
  `cvy_` prefix of at least 8 characters, and any string that could mean two
  threads refuses with `matches N threads: <ids>`.
- **Not in this increment:** resume-by-neuron launch (`resume --neuron`),
  cross-thread edges (`fork` / `parent_convoy_id`), `observed` attestation.
  Graph is read-only by construction.

Unit: `test/demo/graph_test.py` (14 tests).
Live: `graph --neuron <chair>` on a demo root.

### Locked layer statement

> Grok Bot is the opposite layer from Herdr and CNVS. This Grok Bot chat is the conductor. MCP is how the conductor attaches (`roster`, `onboard`, `send`, `feed`, `context`, `bring_up`/`open`, `terminals`; tree also has `install` and `hide`). Convoy is the SoT: one visible thread, one `cvy_id`, one tied repo, seats/neuron sessions that stay isolated. Default `send` is headless on purpose. `bring_up` is the terminal view, isolated n-pane, and only uses vendor resume ids. Same-branch overlap is refused. Pointers in, compact card out.
>
> Bring your own harness. Do not wrap the model. Named refuse: UltraCode-Shim, ola-brain as the product, grok `-p`/`-c`, wrapping Grok as `claude-grok-4-6`.

### Glance contract (Overall vs By thread)

`glance` is a read-only Convoy view, not a second source of truth.

- **Overall usage by harness** (`grok`, `claude`, `codex`, `cursor-agent`, `agy`):
  - `usage_remaining` is only `number | object | null` (from probe + normalize only).
  - Grok remaining is always JSON `null` (never invented `0`, never invented dollars).
  - Missing binary => `present=false`, `usage_remaining=null`, badge `missing`.
  - Badge is `Live`, `missing`, or `limited`.
  - Progress bar fields appear only when a real percent was parsed.
- **By thread** (`--thread` or `--convoy-id`):
  - Seats are listed from Convoy SoT for that convoy only.
  - Seat card includes `to`, optional `model` (omitted when unknown), `session_id`, `worktree`, `branch`, `pr`, and `last_synapse` when present.
  - No thread-level summed token pile.
  - Claude week% belongs on Overall; do not duplicate as a fake thread budget.
  - Shared account meters are never split into invented per-seat remaining values.

CLI + MCP:

- CLI: `python -m convoy glance [--thread T|--convoy-id ID] --json`
- Optional GUI: `python -m convoy glance --tray` (must stay optional/headless-testable).
- MCP tool: `glance` with optional `thread` / `convoy_id` arguments, read-only and safe for a caller without a bearer.

OSS/public vs closed/platform lock:

- **PUBLIC (`deploy-forward/convoy`)**: glance JSON data contract (CLI + MCP), honesty rules, optional lightweight tray JSON renderer.
- **CLOSED (the platform repo)**: polished native tray/notch app, leftover-$ billing scrapers, vendor settings scraping, and platform UI.

### Neighbors (canonical contrast)

- **Herdr (`herdr.dev`)** owns PTYs on a background server and agents type into sibling TUIs. Convoy does not use PTY paste as the hop bus and does not rebuild Herdr inside this MCP.
- **CNVS (`cnvs.dev`, closed-source macOS Swift ADE)** is voice + infinite canvas with in-app army controls. Convoy is one visible thread + one `cvy_id` + tied checkout contract, not a canvas product.
- **Buzz** is Slack-shaped agent chat. Out of scope except one contrast: their missing terminal view is why `bring_up` exists.

### Current code honesty (tree-verified)

- `src/convoy/mcp_http.py` `call_tool("send", ...)` sets `runner = native_runner if live else fake_runner`.
- `src/convoy/synapse.py` `native_runner` executes vendor binaries on PATH; wrapper names are refused.
- Live resumed send is refused at **both** send entry points: `cli.py` and `mcp_http.py` each pass `allow_interactive_resume=not live` into `synapse.send_one`, which refuses any `session_id` / `resume` on a live send rather than spawning a second interactive `--resume` process (documented RED no-steal lock). Refusal is enforced at both callers; 4 tests in `test/demo/phase_mcp_http_test.py` cover it.
- `src/convoy/mcp_http.py` `TOOLS` includes `onboard`, `hide`, and `install` (plus aliases), but a deployed process can still expose the 7-tool snapshot (`roster`, `send`, `feed`, `context`, `bring_up`, `open`, `terminals`).
- `src/convoy/bringup.py` and `src/convoy/install.py` refuse wrapper names (`ola-brain`, `side-chat`, `UltraCode-Shim`) for those tool paths.

### Native-send + structured talk DoD (locked)

#### Definition

Status: **RED** until live functions pass on the loopback MCP (`http://127.0.0.1:8788/mcp`) without shell paste.

#### Successful functions (today)

- **PARTIAL GREEN:** attach/`roster`/`context`/`feed` at MCP layer are attachable.
- **RED (locked):** live resumed `send` is intentionally refused for now; Convoy must not spawn a second interactive `harness --resume <id>` process that contends with an already-live neuron.
- **GREEN (scope guard):** `bring_up` and `install` refusal paths already reject wrapper targets.

Until item (1) exists in code, items (2) and (3) cannot be GREEN. Fake dual-send is not talk. `ola_runner` success on one machine is not stranger-attachable proof.

#### Pseudo-code (target shape, not today-file prescription)

```python
def native_send(to, body, context_pack, worktree=None, model=None):
    exe = resolve_vendor_binary_on_path(to)  # grok/claude/codex/cursor-agent/agy
    refuse_wrappers(exe)  # never ola-brain/side-chat/UltraCode-Shim
    stdin_payload = context_pack_pointers_plus_body(context_pack, body)
    card = run_vendor_cli(exe, stdin=stdin_payload, cwd=worktree, model=model)
    return compact_card_real_or_null(card)
```

Native runner work should follow the same PATH-exec principle already used by `bringup.resume_argv` for TUI resume.

#### Implementation notes

- Keep Convoy as SoT (`feed` + pointers + seats).
- Keep `send` headless by default.
- Keep same-branch overlap refusal.
- Keep `bring_up` as the only show command.
- Do not wrap the model.

#### Definition of done (all required for GREEN)

1. **Native BYO send.** Live `send` executes vendor binary on PATH (`grok`, `claude`, `codex`, `cursor-agent`, `agy`). Never `ola-brain`, never `side-chat`, never UltraCode-Shim, never grok `-p`/`-c`. BYO harness/login. `stdin` is `context.pack` pointers plus body. Compact card fields are real or JSON `null` only: `ok`, `to`, `session_id`, `model`, `usage_remaining`, `body`, `convoy_id`, `worktree`, `branch`, `pr`.
2. **Structured talk (not Herdr PTY paste).** Conductor `send` to grok stamps a synapse row. Conductor `send` to claude on same `cvy_id` includes those pointers. Claude card stamps as a new row. `feed --since` from conductor shows both. Neither hop typed into the other's TUI. Neither merged native sessions. Same-branch overlap still refuses.
3. **Stranger attach.** A second Grok Bot (or fresh bind) attaches same MCP URL and same `convoy_id`; `roster` lists seats; `feed` shows talk; `send` hops without `ola-brain` on PATH. Tied checkout fields remain on every card.

Live checks for GREEN:

- `send` `live=true` `to=grok` with unique body token returns that token and process argv is vendor CLI, not `ola-brain side-chat send`.
- Two sends (two `to`s) produce two `session_id`s and two `kind=synapse` rows visible to a second attached client.
- `install to=ola-brain` and `install to=ultracode-shim` refuse; `bring_up` argv never contains those names.

Phase gate note: this is the remaining MCP-attach/send hole inside Phase 7. Do not start a fake Phase 8 while Phase 7 resume-hop remains RED.

---

## Three products (do not collapse them)

| Product | Repo | What it is | What it is not |
|---|---|---|---|
| Convoy MCP + neuron CLI | `deploy-forward/convoy` | HTTP MCP tools (`roster`, `onboard`, `terminals`, `context`, `send`, `feed`) plus a Python neuron CLI that stamps a layer and fires harness CLIs | Not the native Composer `turn.send`. Not `npx deploy-forward` itself. |
| Installer / tracker / board | `deploy-forward/deploy-forward` | `npx deploy-forward --convoy --tracker --board`. White-glove attach. Tracking and the public board. | Not the MCP process. Board requires tracker. |
| Native platform | the closed platform repo | Skinny Convoy thread/layer inside Composer. Native `turn.send`. | Not this HTTP MCP. Do not land MCP code there. |

Demo talks to Grok Bot. Grok Bot opens synapses through Convoy. Each synapse lands on a harness the human already signed into. Three products, one thread.

---

## Objects: Thread, Layer, Synapse

| Object | Lives where | Shape | Owns | Does not own |
|---|---|---|---|---|
| **Thread** | The human conversation (this Grok Bot chat, or any customer thread). Front matter is in the chat, never invented. | Message to/From, Thread path, Skill on disk. The conversation is the durable unit. | The human's questions, compact cards coming back, the decision to open a synapse. | Vendor session_ids. Packed stdin. Full transcripts. |
| **Layer** | `.convoy/feed.jsonl` under a checkout root. On the demo host: `<demo-root>/.convoy/feed.jsonl`. | JSONL of `{ts, kind, instance_id, summary, ...extra}`. Sliding window via `feed_since`. | Event time. Pointers (thread.md, role.md, `.ola/brief.md`, newest handoff, instance_id, worktree, branch, pr). Which neuron was touched, when. | Bytes of a vendor transcript. `hook-context` / `precompact` / `session-end` from ola-brain. Vendor `--resume`. |
| **Synapse** | One native send: Convoy execs one harness CLI, one instance, one meter. Card comes back compact. | `{ok, to, session_id, model, usage_remaining, body, ...}`. Hook row stamped on send/refuse/spawn. | That harness's native session_id. That harness's cwd/worktree. That harness's remaining quota (or JSON `null`). | Another synapse's session. Another synapse's branch. The Grok Bot main context window. |

Rules that follow from the table:

- Two synapses never share a vendor session.
- The layer is pointers and stamps, not packed bytes in stdin.
- Turn 2+ of a neuron resumes **that instance's** vendor session id only.
- Unknown fields are JSON `null`. Never invent `main`, never invent a token count, never invent a session id.

---

## How Grok Bot connects (MCP, historical details)

The canonical lock above is authoritative when this section disagrees.

Transport: HTTP MCP on the user's own machine at `http://127.0.0.1:8788/mcp`. There is no hosted Convoy endpoint. **NOT** stdio on a remote box pointing at Windows `localhost:4717`. That failed.

An early wire snapshot (demo): a shell on the demo host running two local wrapper scripts, `Invoke-AgentChannel.ps1` and `ConvoyLayer.ps1` (not in this repository), wrapping `ola-brain.exe`. MCP catalog had no Convoy plugin at that time. Status then: **RED** for HTTP MCP, **GREEN** for PC CLI hop.

`ConvoyLayer.ps1` is **not in this repo** (`find . -name "*.ps1"` at `f40b01a` returned nothing). It existed only on the demo host, where it carried the early contract: `hook`, `feed-since`, `send-dry`. Do not cite it as in-tree evidence. In this repo, default `python -m convoy send` uses `fake_runner` and `--live` uses `synapse.native_runner` (vendor binary on PATH). Live resumed send is refused at both entry points (RED no-steal lock) to avoid launching a second interactive resume process. HTTP MCP server code is in `src/convoy/mcp_http.py` (`python -m convoy mcp --root ROOT --port 8788`). Do not treat this paragraph as current attach status; use the canonical split above.

### Required MCP tools and JSON cards

#### `roster`

Returns live agents. Fields, all present, nulls not guesses:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable agent / harness id (`grok`, `claude`, `codex`, `agy`, `cursor-agent`, …) |
| `name` | string | Display name |
| `present` | bool | Binary is on PATH / machine |
| `wired` | bool | Convoy can actually exec it |
| `auth` | string \| null | Login state if the harness exposes it, else null |
| `models` | list \| null | What the harness reports, else null |
| `availability` | string | Probe result: available / limited / unknown. Availability is **not** DF tracking. |
| `usage_remaining` | number \| object \| null | `null` if unknown. Never a remembered number. |
| `tracking` | `off` \| `on` \| `untracked` | DF tracker flag |
| `board` | `off` \| `on` \| `hidden` | DF board flag. Board requires tracker. |
| `thread` | string \| null | Thread path if known |
| `worktree` | string \| null | Checkout path for the live instance |
| `branch` | string \| null | `git rev-parse --abbrev-ref HEAD` or JSON null |
| `pr` | number \| null | `gh pr view` number or JSON null |

#### `onboard`

First run after MCP attach. The human names which harnesses they already have.

- MCP tool: `onboard`
- CLI: `python -m convoy onboard`
- User-facing chat command mapping: `/onboard` and `/onboard -convoy` are the same flow.

Args:

- `to` (required list): one or more harness ids from `grok`, `claude`, `codex`, `cursor-agent`, `agy`
- optional `thread`
- optional `checkout_root`

Refuse list: `gemini-cli`, community `grok-cli`, `UltraCode-Shim`, `ola-brain`.

JSON card shape (per named harness; unnamed are never silently added):

| Field | Type | Meaning |
|---|---|---|
| `to` | string | Named harness id from the allowed set |
| `present` | bool | `shutil.which` / install `_which` found the binary |
| `wired` | bool | Convoy can exec it from PATH right now |
| `path` | string \| null | Resolved executable path if found |
| `availability` | string | `available`, `limited`, or `missing` |
| `usage_remaining` | number \| object \| null | Probe value if the harness exposes one; `null` when unknown or unparseable. Never invented `0`. |
| `limited` | bool | True when probe says limited |
| `install` | object \| null | For missing named harnesses only: hint to use MCP/CLI `install` with opt-in |

Pseudo-code:

```python
def onboard(root, named, thread=None, checkout_root=None):
    ids = normalize(named)  # dedupe, lower
    refuse_if_empty_or_wrapped(ids)
    refuse_if_unknown(ids, allowed={"grok","claude","codex","cursor-agent","agy"})
    target_root = resolve_checkout(root, checkout_root)
    path_card = ensure_interactive_path()  # ~/.bashrc block for next shell PATH
    convoy_id, bound_thread = bind_thread_if_requested_without_stomp(target_root, thread)
    rows = []
    for hid in ids:
        path = which(hid)
        row = {"to": hid, "present": bool(path), "wired": bool(path), "path": path}
        row["usage_remaining"] = probe_usage_or_null(hid, present=bool(path))
        if checkout_root:
            row["first_run"] = ensure_first_run({"to": hid, "worktree": str(target_root)})
        if not path:
            row["install"] = {"tool": "install", "opt_in_required": True}
        rows.append(row)
    return card(convoy_id, bound_thread, target_root, path_card, rows)
```

Implementation:

- `src/convoy/onboard.py` implements normalization/refusal, declared-only probing, optional bind, and install hints.
- `src/convoy/mcp_http.py` exposes MCP tool `onboard`.
- `src/convoy/cli.py` exposes CLI `python -m convoy onboard`.

Definition of done (split status):

GREEN (emulator / tree):

1. Unit tests with fakes simulate PATH and harness probes (`test/demo/onboard_test.py`).
2. `onboard` with named harnesses returns cards only for named `to`, each with truthful `present`/`wired` from PATH.
3. `usage_remaining` is number/object/null only; blob strings clamp to `null`; never invented `0`.
4. Wrapper names are refused.
5. Flow is dry with respect to UI: no window pop / no `wt` spawn.

RED (live deploy until proven):

1. A live loopback MCP process (`convoy mcp`) serving `onboard` in `tools/list`.
2. Chat aliases `/onboard` and `/onboard -convoy` in connected Grok Bot sessions (only true once live MCP serves the tool).

#### `terminals`

Live windows + instance records for a thread (`thread=` or `convoy_id=`). Optional grep. **No PTY dump.** Pointers and metadata only (`to`, `session_id`, `resume`, `resume_key`, `worktree`, `rect`). Desktop access is this plus `bring_up`, not a second product. A listing: it runs no first run and writes no file. Conductor grok-bot is not a window. A historical snapshot marked HTTP MCP RED; use canonical lock for current status.

#### `context`

Packed pointers only:

- `thread.md`
- `role.md`
- `.convoy/brief.md`
- newest handoff (`.convoy/handoff/…`)
- `instance_id`
- `worktree`
- `branch`
- `pr`

Not file contents. Not a vendor transcript. Not stdin bytes.

#### `send`

Args: `to=harness|instance_id`, `body`, optional `model` / `label` / `worktree`. Returns a compact card. Refuses if unavailable (limited quota, missing binary, same-branch pair with no worktree). Does not wait 120s on a known-limited harness. Default synapse is headless: `send` never pops a TUI and never calls `live_runner` / `CREATE_NEW_CONSOLE`. Live resumed send is currently refused (RED no-steal lock) rather than spawning a second interactive `harness --resume`.

#### `feed`

Events since `ts`. Default last window, not unbounded vendor `--resume`. Maps to `feed_since` in `src/convoy/layer.py`.

#### `bring_up` (alias `open`)

Args: `thread=` or `convoy_id=`. Opens every seated neuron for that thread **visible** (`headless=false`) with native harness argv (`grok/claude --resume <vendor-id>`, `codex resume <vendor-id>`). If no vendor id exists yet, first-run omits resume flags. Returns a windows card:

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | False on mismatch or a refused seat |
| `convoy_id` | string \| null | Durable id |
| `thread` | string \| null | Bound thread key |
| `conductor` | string | Always `grok-bot`. Not a window. No harness chip. |
| `lead` | string \| null | Hop lead harness |
| `windows` | list | One card per hop seat. Not grok-bot. |

Each window: `to`, `session_id`, `resume` (vendor id passed to `--resume`; never null if ok; never invented), `resume_key` (`cvr_` + sha256(convoy_id + "\0" + thread + "\0" + to + "\0" + worktree).hexdigest()[:16] — **four** fields; hash is the map key, resume is the harness argument; because `to` and `worktree` are hashed, the key CHANGES when a seat's harness or checkout changes, so it is a resume map key and never a stable seat identity — `session_id` is the seat), `worktree`, `rect` `{x,y,w,h}`, plus CLI extras `argv`, `ok`. Lookup by thread+to returns the same resume. No PTY dump. A historical snapshot marked HTTP MCP RED; use canonical lock for current status. CLI: `python -m convoy bring-up` / `open` `[convoy_id] [--thread T] [--dry-run]`.

First-run Claude bypass warning is ungated by `bring_up` / `ensure_first_run`. Anthropic ignores `skipDangerousModePermissionPrompt` in project `{worktree}/.claude/settings.json` — that key only works in the **user** file `~/.claude/settings.json`. Merge `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create `~/.claude/` if missing; merge, do not clobber other keys). Do **not** set `permissions.defaultMode` on the user global file (that would make ALL Claude sessions on the machine bypass). No settings file Convoy writes in a worktree carries `permissions` or `skipDangerousModePermissionPrompt`: a project `permissions.defaultMode` would apply to every Claude session opened there, and the launch argv already carries the mode. The worktree's `.claude/settings.local.json` (never the tracked `.claude/settings.json`) holds the inbox and Stop hooks and `autoCompactEnabled: true`: a neuron runs unattended and must compact on its own, and project settings take precedence over the user file. The user file gets `skipDangerousModePermissionPrompt` only when the key is missing, and a file that does not parse is left alone and reported. Never write `autoCompactEnabled` to `~/.claude/settings.json`; the person's own sessions keep their choice. Also merge `~/.claude.json` `projects[worktree].hasTrustDialogAccepted = true` for both slash spellings of the worktree path. Never write `~/.claude` if the worktree **is** the home dir. Grok/codex no-op on Claude settings. Not a user paste. Not a step-by-step TUI guide. User once-gates only: attach `http://127.0.0.1:8788/mcp`, and vendor CLI login. `roster.present` is `shutil.which` on the MCP process PATH, not an already-open desktop terminal. Interactive bash skips `.profile`, so `~/.local/bin` (claude, codex) can be installed and still `command not found` while grok (`.bashrc`) works. `roster` and `bring_up` / `ensure_first_run` call `ensure_interactive_path`, which writes an idempotent `# >>> convoy harness PATH >>>` block into `~/.bashrc` (`$HOME/.local/bin` and `$HOME/.grok/bin`). No-op on Windows (WT inherits user PATH). Does not source a foreign PID; already-open terminals still need `source ~/.bashrc` or a new shell. Roster JSON includes `path` (`path_ok`, `path_written`, `path_bashrc`, `path_host`). Folder trust, Claude Bypass Permissions, `role.md` persona, isolated WT tiling, and agent-driven verify are Convoy's job. A dry run writes nothing: `ensure_first_run(live=False)` returns the plan (`first_run.dry_run` true, `prepared` false, `dry_run_writes` for the worktree, `would_write_home` for home files and trust stores; `settings` stays the project path) and must not Popen `wt`. Claude live argv keeps `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`. Persona is `role.md` in the worktree, not CLI `--append-system-prompt`. Repo files: `mint_worktrees` writes `<worktree>/.convoy/minted.json` only when it creates the worktree, and `is_minted_worktree` is true only when that marker names this folder, git resolves the folder's common dir to the recorded one, and the recorded checkout still lists the worktree. A launch (`bring-up`, `open`, `launch`, `join --launch`, `crew`, `relaunch`, the widget relaunch) and `skills` write every repo file there; anywhere else, often the person's own repo, they write only the Convoy-named files git excludes (`.claude/settings.local.json`, the `convoy-root` pointers, `.grok/hooks/convoy-inbox.json`) and list `AGENTS.md` as `would_write`, read from disk. No launch writes `.codex/hooks.json`: Codex keys a project hook by its absolute path, so each worktree's file is a key nobody trusted, while the convoy plugin's `codex-hooks.json` (named by the manifest's `hooks` field, in Deploy-Forward/plugins) is keyed `convoy@<marketplace>:codex-hooks.json:<event>:0:0` (`convoy@deploy-forward` from the published marketplace) and trusted once. A `.codex/hooks.json` carrying Convoy entries an older Convoy wrote is left as it is, with a card note to remove them. `add` and `crew` cards for a codex chair carry a warning while `codex_hooks_trusted` (read-only; `$CODEX_HOME/config.toml` when set) reads the enabled `convoy@*` plugin's keys as untrusted, disabled (`enabled = false`) or unknown (the config does not parse: "codex hook trust unknown: <reason>", never "not trusted"). An opt-in is recorded in `.convoy/repo-files.json`, bound to its folder and git common dir and added to info/exclude, and honoured by later launches until `skills --no-write-repo-files` removes it; a dry `bring-up` / `open` / `relaunch`, CLI (`--dry-run --write-repo-files`) or MCP `bring_up` / `open` (`dry_run: true` with `write_repo_files: true`), refuses the opt-in and writes nothing. A `.claude/settings.local.json` git tracks is never written. The card's `trust_stores_written` names each home trust store a launch wrote. `terminals` is a listing and writes nothing. The read verbs `start`, `onboard`, `glance` and `rail` write no home file and start no harness binary: onboarding reports the first run as a plan (`first_run.would_write_home`) and the live launch performs it (`start --write-repo-files` / `onboard --write-repo-files` performs it at once); every usage field is `null` (unknown, not zero) and `probed` is false until `--probe` (MCP `onboard`: `probe: true`). MCP `glance` and `rail`, and the widget, read through their cached probe. Reading a thread creates no `.convoy/inbox/` directory, and a dry `send` refreshes no `.convoy/conductor.md` copy.



#### `install`

Opt-in vendor harness download. HTTP `dry_run` defaults true. Live requires `opt_in=true` (and CLI `--live --opt-in`). Does not log the user in. `affiliate` is always JSON null.

Allowed hosts only: `x.ai` (grok), `claude.ai` (claude), `chatgpt.com` (codex), `cursor.com` (cursor-agent), `antigravity.google` (agy). Refuse gemini CLI, community grok CLI, UltraCode-Shim, ola-brain. After a live install, `ensure_interactive_path` runs.

Unit GREEN: `test/demo/phase_install_test.py`.

#### `hide` (aliases `minimize`, `background`)

Default synapse (`send`) is headless: it never pops a TUI and never calls `live_runner` / `CREATE_NEW_CONSOLE`. `bring_up` / `open` is the only show command (HTTP `dry_run` still defaults true, and `dry_run` false needs a conductor bearer; CLI `bring-up` without `--dry-run` uses `live_runner`, which Popen's **one** `wt.exe` whose ArgumentList is `isolated_wt_argv` — FileName is wt, not in the list; `-w convoy-<8 hex>` (the thread's own window, see "Placement: one terminal window per thread"); first command `new-tab`, or `split-pane` when the window already holds a live neuron; n=2 one `-V`; n=3 `-V` then `-H`; absolute exe positional after `-d DIR`; never `--` before the exe; never `-w 0`; never per-seat `CREATE_NEW_CONSOLE` + `MoveWindow`; never `WM_CLOSE`). Isolated spawn is a new WINDOW not a new PROCESS. A dry run writes nothing (its `first_run` card is the plan) and must not Popen `wt`. Never ola-brain / side-chat / UltraCode-Shim. `hide` / `minimize` / `background` minimize neuron windows (Win32 `SW_MINIMIZE` = 6; optional `mode=hide` is `SW_HIDE` = 0). Sessions keep running. Not `taskkill`. Never kills `grok.exe` / `claude.exe` / `Grok Bot.exe`. Conductor grok-bot is not a window. `restore` is `bring_up`, not this tool. HTTP MCP attach is still RED.

### Front matter in this chat, never invented

```
Message to/From: {Agent} | {model} | {effort}
Thread: {filepath} | usage remaining {n|unknown}
Skill on disk: <agent-host>/workflows/agent-channel/SKILL.md
```

If a field is unknown, write `unknown` or JSON `null`. Do not fill it from memory.

### Definition of done (legacy attach checklist)

Historical attach checklist only. Current canonical DoD is the native-send + structured-talk block above: attach/roster/feed may be PARTIAL GREEN, while native `send` remains RED until a live vendor PATH execution is proven on the loopback MCP. The code swap already happened (`native_runner`, `75f00c7`); what is missing is live proof, not the implementation.

---


## Phases (hard gate)

Step N is Phase N. Do not start Phase N+1 until Phase N Definition of done is GREEN, proven on the demo (this chat and the demo host). Unit tests with a fake runner are not enough to unlock the next phase.

| Phase | Name | Status |
|---|---|---|
| 1 | Threaded context | Unit GREEN (`phase1_threaded_context_test.py`). An early live auto-register (`<demo-phase1-session>`) is **retired-path evidence** (ola-brain `side-chat send`, pre-`native_runner`). Native path not re-proven live: `null`. |
| 2 | Temporally aware | GREEN. Unit `temporal_hooks_test.py`; a live row re-read in `<demo-root>/.convoy/feed.jsonl`. Runner-independent: the stamp path did not change with `native_runner`. |
| 3 | Feature branch | GREEN code + unit: `gitstate.git_state()` runs `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number`; `phase3_branch_test.py`. Live artifact: real `git_branch` + `pr_number` values on demo feed rows. |
| 4 | Worktree | Unit GREEN (`phase4_worktree_test.py`); worktree is stamped on every synapse row and passed as `cwd` into the runner. Live **native** dual-worktree hop unproven: `null` (the earlier dual hop was the retired ola-brain path). |
| 5 | Usage remaining | **PARTIAL.** GREEN: unknown normalizes to JSON `null` — never `0`, never invented dollars (`usage.normalize_usage_remaining`, `harness_contract.usage_remaining_null_until_live_probe`, `phase5_usage_test.py`, `glance_test.py`); `claude -p /usage` and `codex` probes parse. BLOCKED: grok, `cursor-agent`, `agy` expose no remaining quota at all — see the Phase 5 section. This row is not "usage remaining per harness". |
| 6 | Parallel native send | Unit GREEN (`parallel_agents_test.py`); demo-host `send-dry` GREEN (`<dry-grok-session>`, `<dry-claude-session>`, two rows). An early live dual send (`<demo-grok-session>` + `<demo-claude-session>`) is **retired-path evidence** (ola-brain). Native parallel live: `null`. |
| 7 | Durable convoy_id / attach / bring-up | bind+attach GREEN (`<demo-convoy-id>`, thread `demo`) — 3 attach rows and both seats (distinct `resume_key`) re-read. Live resume hop is RED **by design** (`d6af562`, the no-steal lock), not a hang to fix. Live TUI bring-up RED. Not Phase 8. |

**Provenance of the early live GREENs (audited at `f40b01a`).** Every early live run went through `ola-brain side-chat send` (`ola_runner`). `native_runner` — vendor binary on PATH — landed later (`75f00c7`, PR #4), and so did the no-steal live-resume lock (`d6af562`, PR #12). The canonical lock names `ola-brain` a refuse target, so those runs are evidence about a **retired path**: they are not proof of DoD item 1 (native BYO send). No live native vendor send was recorded on any Convoy layer read in that audit. Unknown stays `null`.

MCP attach status is split: attach/roster/context/feed can be PARTIAL GREEN while native `send` is still RED. This remains a Phase 7 hole, not a Phase 8 launch.

## Phase 1 Threaded context

### Definition

The human conversation is the thread. The layer is pointers, not pack bytes in stdin. Turn 2+ resumes **this** instance `session_id` only. Two harnesses never share a vendor session. A dry-run that prints an instance id without a registry row is a bug.

### Successful functions

- **GREEN:** ola-brain `side-chat send grok --label synapse-proof` → `<demo-synapse-session>` `SYNAPSE_OK`; turn 2 `SYNAPSE_TURN2`; turn 3 via convoy mention `SYNAPSE_TURN3`; registry `session_id` `<redacted-vendor-session-id>` (demo host).
- **GREEN:** the local wrapper's `context` command (packed pointers; the wrapper is not in this repository).
- **RED:** CLI side-chat `send` skips the IDE hydration pointer (cold message). Codex JSON has no `session_id` so next turn is `resume --last` (hostile).
- **RED:** dry-run printed instance id without `register_agent`.
- **GREEN (this tree):** `context.py` pack/stdin pointers. `ola_runner` passes `--label` before target. `parse_session_id` reads JSON or ola-brain `instance_id: reply` (must contain `-session-`). No UUID regex. Dry-run session_id is JSON null. Live: pointers in, PHASE1_T1/T2, vendor `<redacted-vendor-session-id>`. CLI auto-register from stdout was the remaining gap.

### Pseudo-code

```python
def context_pack(root, instance_id=None):
    # pointers only — never file contents, never a vendor transcript
    return {
        "thread": pointer(root / "thread.md"),
        "role": pointer(root / "role.md"),
        "brief": pointer(root / ".ola" / "brief.md"),
        "handoff": newest_handoff(root),
        "instance_id": instance_id,
        "worktree": git_worktree(root),   # JSON null if not a checkout
        "branch": git_branch(root),       # JSON null if not a checkout
        "pr": gh_pr_number(root),         # JSON null if none
    }

def send(to, body, label=None, instance_id=None, worktree=None):
    packed = context_pack(worktree or cwd(), instance_id)
    stdin = "read these paths, then do the body:\n" + json.dumps(packed)
    if instance_id:
        # turn 2+ resumes THIS instance only
        return resume(to, instance_id, stdin, body)
    card = spawn(to, stdin, body, label=label, cwd=worktree)
    session_id = parse_session_id_from_json(card)  # not regex guess, not Codex --last
    register_agent(session_id, to, worktree)
    hook(kind="synapse", instance_id=session_id, summary=f"send {to}")
    return card
```

### Implementation

- Add `src/convoy/context.py` with `pack()` returning only paths and ids.
- `synapse.py` `ola_runner` must pass `--label` and parse the real `session_id` from ola-brain JSON, not a regex guess over mixed stdout/stderr.
- Never Codex `--last`. Codex JSON today has no `session_id`; treating `--last` as "the other agent" is hostile and merges sessions.
- MCP `context` tool maps 1:1 onto `context.pack`. MCP `send` first line of hop stdin says "read those paths".
- Registry row is required before any printed instance id. A test that sees a dry-run id without a registry row fails.

Current `ola_runner` (must change):

```python
cmd = ["ola-brain", "side-chat", "send", to, body]
# missing --label
# session_id = first token that looks like a uuid  ← regex guess, forbidden
```

Target `ola_runner`:

```python
cmd = ["ola-brain", "side-chat", "send", to, body, "--label", label]
payload = json.loads(stdout)
session_id = payload["session_id"]   # KeyError if missing; do not guess
```

### Definition of done

- `context` MCP tool returns only paths/ids.
- First hop stdin says read those paths.
- Turn 2 uses the returned `session_id`.
- Two harnesses never share a vendor session.
- Test fails if dry-run prints an id without a registry row.

---

## Phase 2 Temporally aware

### Definition

Event time is the hook stamp on the layer. Sliding window = grep feed by `ts`. Not vendor `--resume`. Not ola-brain `hook-context` / `precompact` / `session-end`. Asking "what happened in the last 10 minutes" reads the layer, not a vendor transcript.

### Successful functions

- **GREEN unit:** `test/demo/temporal_hooks_test.py` (`hook` + `feed_since`). Asserts `ts`, `kind`, `instance_id`, `summary` and that `feed_since(later["ts"])` returns the new hop.
- **GREEN (demo host):** convoy hook stamps `{ts,kind,instance_id,summary}` to `<demo-root>/.convoy/feed.jsonl` via a local wrapper script (not in this repository). `convoy feed --since` returns that window.
- **GREEN code:** `src/convoy/layer.py` `hook()`, `feed_since()`. CLI: `python -m convoy hook <kind> <summary> [--instance-id]` and `python -m convoy feed --since <ISO>`.
- **RED:** MCP `feed` tool not attached to this chat. ola-brain feed is a different object and hung when probed.

`hook()` today writes:

```python
event = {"ts": utc_now(), "kind": kind, "instance_id": instance_id, "summary": summary}
# extra fields merged if provided
# appended as one JSONL line under root/.convoy/feed.jsonl
```

`feed_since()` today returns every row whose `ts >= since_iso`. Inclusive lower bound. Empty file → `[]`.

### Pseudo-code

```python
def hook(root, kind, summary, instance_id=None, extra=None):
    event = {
        "ts": utc_now(),            # ISO UTC, microseconds, trailing Z
        "kind": kind,               # synapse | refuse | spawn | note | ping | ...
        "instance_id": instance_id,
        "summary": summary,
    }
    if extra:
        event.update(extra)
    append_jsonl(root / ".convoy" / "feed.jsonl", event)
    return event

def feed(root, since, until=None):
    rows = []
    for row in read_jsonl(root / ".convoy" / "feed.jsonl"):
        if row["ts"] < since:
            continue
        if until is not None and row["ts"] > until:
            continue
        rows.append(row)
    return rows
```

Every `send` / `refuse` / `spawn` calls `hook`. MCP `feed` maps to `feed_since`. CLI `/hook` is `python -m convoy hook`.

### Implementation

- Keep `src/convoy/layer.py` as the single writer. Do not invent a second feed format.
- `synapse.send_many` already calls `hook(..., kind="synapse", ...)` after each card. That must stay, and refuse/spawn paths must call `hook` too (they do not yet — refuse path does not exist in this tree).
- MCP `feed` is a thin wrapper: args `since` (required), `until` (optional). Default last window when `since` omitted at the MCP layer, not unbounded.
- A hop without a stamp fails the test. Do not let `ola_runner` return a card that never hit `hook`.
- Do not call ola-brain `hook-context`, `precompact`, or `session-end` and call that the layer.

### Definition of done

- After two hops, `feed --since T0` returns both synapse rows with `ts`.
- A hop without a stamp fails the test.
- Grok Bot can ask "what happened in the last 10 minutes" and get that window from `feed`, not a vendor transcript.
- HTTP MCP `feed --since` works from this chat without Shell paste (still RED today).

---

## Phase 3 Feature branch understanding

### Definition

Each live instance carries `branch` + `pr` on the layer. The thread can say which hop owns which PR. Probes are `git rev-parse --abbrev-ref HEAD` and `gh pr view`, never guessed. JSON `null` if not a git checkout. Never invent `main`.

### Successful functions

- **GREEN unit:** `test/demo/phase3_branch_test.py`. Non-git pack is JSON null, never `"main"`. Two send_one roots (`feat-a`, `feat-b`) stamp two different `git_branch` fields.
- **GREEN code (corrected at `f40b01a`):** `src/convoy/gitstate.py` `git_state()` shells all three probes — `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number -q .number` — and `synapse.send_one` merges the result into every synapse row and registry entry. Never a remembered branch name; non-git is JSON `null`.
- **Live artifact:** `<demo-root>/.convoy/feed.jsonl` rows carry the real `git_branch`, `git_sha` and `pr_number` of the checkout they ran in. The earlier "in flight / when implemented" wording was stale.

### Pseudo-code

```python
def git_state(cwd):
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    sha = run(["git", "rev-parse", "HEAD"], cwd=cwd)
    pr = run(["gh", "pr", "view", "--json", "number", "-q", ".number"], cwd=cwd)
    return {
        "git_branch": branch if branch else None,   # JSON null, never "main"
        "git_sha": sha if sha else None,
        "pr_number": int(pr) if pr else None,
    }

def send(to, body, worktree=None, pr=None):
    state = git_state(worktree or cwd())
    if pr is not None:
        state["pr_number"] = pr
    # refuse silently using another instance's branch
    other = live_instance_on_branch(state["git_branch"], excluding=None)
    if other and other.worktree == (worktree or cwd()):
        raise OverlapError("same branch, same cwd, two agents")
    card = spawn(to, body, cwd=worktree)
    hook(kind="synapse", instance_id=card["session_id"], extra=state)
    return card
```

### Implementation

- Extra fields on `hook` + instance record: `git_branch`, `git_sha`, `pr_number`.
- MCP `roster` / `context` expose `branch`, `pr`.
- `send --pr` optional (CLI + MCP).
- If the cwd is not a git checkout, store JSON `null`. A test that sees the string `"main"` when `rev-parse` failed fails CI.
- Do not copy a branch name from another instance's card.

### Definition of done

- Two synapses on two branches show two different `branch` fields.
- `null` if not a git checkout (never invent a branch name).
- Test asserts JSON `null` not `"main"`.

---

## Phase 4 Worktree understanding

### Definition

A synapse records its worktree / checkout path. Two agents on one branch without a worktree is a bug. Grok and `cursor-agent` already have `--worktree` flags on their CLIs. Convoy must pass those through. Missing worktree on a same-branch pair is an explicit error, not a silent overlap.

### Successful functions

- **GREEN unit:** `test/demo/phase4_worktree_test.py`. Non-git worktree is JSON null. Second send on the same branch without `--worktree` returns explicit error. Two `--worktree` paths do not share cwd.
- **GREEN code (corrected at `f40b01a`):** CLI `send --worktree <path>`; the worktree is stamped on every synapse row and passed as `cwd` into the runner (`synapse.send_one` -> `native_runner(cwd=...)`). The retired `ola_runner` `--worktree` argv note is history.
- MCP `send` accepts `worktree`; live MCP proof on the loopback MCP is still `null`.
- Live **native** dual-worktree hop: `null`. The earlier dual hop was the retired ola-brain path (Phase 6).

### Pseudo-code

```python
def send(to, body, worktree=None):
    if worktree:
        cwd = worktree
    else:
        cwd = os.getcwd()
    siblings = live_instances(branch=git_branch(cwd))
    if siblings and not worktree:
        raise WorktreeRequired(
            "two agents on one branch without a worktree is a bug"
        )
    card = spawn(to, body, cwd=cwd, worktree_flag=worktree)
    hook(kind="synapse", instance_id=card["session_id"], extra={"worktree": cwd})
    return card

def spawn(to, body, cwd, worktree_flag):
    if to in ("grok", "cursor-agent") and worktree_flag:
        argv = [to, "--worktree", worktree_flag, ...]
    else:
        argv = harness_argv(to, body)
    return run(argv, cwd=cwd)
```

### Implementation

- CLI: `send --worktree <path>`.
- `ola_runner` `cwd=worktree` (already in the signature, not wired from CLI).
- `cursor-agent` / `grok` pass their `--worktree` flag.
- MCP `send.worktree`.
- `roster` shows each instance's `worktree`.
- Same-branch pair with missing worktree → explicit error card, not a silent overlap.

### Definition of done

- Two parallel hops with two worktree paths do not share cwd.
- `roster` shows each instance's worktree.
- Missing worktree on a same-branch pair is an explicit error, not a silent overlap.

---

## Phase 5 Usage remaining per harness (BLOCKED)

### Definition

Probe the way the harness actually exposes limits **before** spawn. Unknown is `null`. Limited ⇒ refuse, do not wait 120s. Availability is not DF tracking. Never copy a number from memory. A test that invents `0` tokens fails CI.

### Successful functions

- **GREEN probe:** `claude -p /usage` JSON: the 5-hour session percent, its reset time and the week percents parse.
- **GREEN probe:** `codex login status` reports the login; `codex doctor` is silent on quota; `codex exec /status` with stdin closed prints `Your workspace is out of credits.` when the workspace has none. Hop without probe hung.
- **GREEN roster field:** unknown `usage_remaining` is JSON `null`, never `0`, never invented dollars. In-tree proof: `usage.normalize_usage_remaining`, `harness_contract.usage_remaining_null_until_live_probe`, covered by `phase5_usage_test.py` and `glance_test.py`. (A local wrapper script was the demo host's earlier source and is **not in this repo** — do not cite it as in-tree evidence.)
- **Scope note:** what is GREEN here is the honesty rule (unknown stays `null`), not per-harness remaining quota. The phase table row says PARTIAL for that reason.
- **RED:** grok has no `/usage` subcommand (`models` / `doctor` / `login` only); probe aborted.
- **RED:** `cursor-agent status` logged in `<account redacted>`, no remaining quota in `status` / `about`.
- **RED:** `agy.exe` present with `-p`, not on ola-brain agents list. Gemini auth unknown.

Refuse rules:

- Claude session 100% ⇒ refuse.
- Codex `out of credits` ⇒ refuse.
- Missing probe ⇒ `usage_remaining` null, still may hop unless last probe said limited.

### Pseudo-code

```python
def probe(harness):
    match harness:
        case "claude":
            raw = run(["claude", "-p", "/usage"])
            data = parse_usage_json(raw)
            limited = data.get("session_pct") == 100
            return {"usage_remaining": data, "limited": limited, "raw": raw}
        case "codex":
            raw = run(["codex", "exec", "/status"])  # closed stdin; do not hang
            limited = "out of credits" in raw.lower()
            remaining = None if limited or not raw else raw
            return {"usage_remaining": remaining, "limited": limited, "raw": raw}
        case "grok":
            # no /usage subcommand — models/doctor/login only
            return {"usage_remaining": None, "limited": False, "raw": None}
        case "agy":
            return {"usage_remaining": None, "limited": False, "raw": None}
        case "cursor-agent":
            # status/about have login, no remaining quota
            return {"usage_remaining": None, "limited": False, "raw": None}
        case _:
            return {"usage_remaining": None, "limited": False, "raw": None}

def send(to, body, **kw):
    p = probe(to)
    if p["limited"]:
        hook(kind="refuse", summary=f"{to} limited", extra={"raw": p["raw"]})
        return {"ok": False, "to": to, "refused": True,
                "usage_remaining": p["usage_remaining"],
                "body": p["raw"]}          # no 120s hang
    return spawn(to, body, **kw)
```

### Implementation

- New file: `src/convoy/usage.py` with `probe(harness)`.
- `roster` calls `probe` per present harness.
- `send` calls `probe` before spawn.
- Never copy a number from memory. Live Claude at 100% was a probe result, not a constant in code.
- Timeout on probe must be short. Codex hop without probe hung; that is the bug this step exists to kill.
- A unit test that stubs `0` tokens and expects a hop to succeed (or invents a remaining count) fails CI.

### Definition of done

- Live Claude at 100% returns a refused card with the `/usage` text, no 120s hang.
- Codex out of credits same.
- Grok hop with `usage_remaining` null is allowed and the card says unknown/`null`.
- A test that invents `0` tokens fails CI.

---

## Phase 6 Parallel native send

### Definition

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Each synapse on its own meter. Fake runner and the demo host's `send-dry` prove the plumbing. Live dual is the remaining bar.

### Successful functions

- **GREEN** fake runner: `python -m convoy send --to grok --to claude` (`src/convoy/synapse.py` `fake_runner` + `send_many` via `ThreadPoolExecutor`). Unit: `test/demo/parallel_agents_test.py` (`test_two_synapses_own_session_ids`). Distinct `session_id` values; CLI returns 2 if parallel send merged ids.
- **GREEN** demo-host `send-dry`: `<dry-grok-session>` and `<dry-claude-session>`. Two distinct ids, two hook rows. Implemented in a local wrapper script's `Send-Dry` (demo host only; no copy of that script exists in this repo).
- **GREEN** live dual (the retired ola-brain path): `send --live --to grok --to claude --label phase6b` with two worktrees. session_ids `<demo-grok-session>` (<demo-root>) and `<demo-claude-session>` (a second checkout). Both bodies PHASE6B. First try failed on grok cp1252 decode + ola-brain `--worktree` argv; UTF-8 replace + cwd-only worktree fixed it. Codex not hopped (probe timeout refuse).

### Pseudo-code

```python
def send_many(root, targets, body, runner=None, worktree=None):
    if len(targets) < 1:
        raise ValueError("need at least one --to")
    run = runner or fake_runner
    cards = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = {pool.submit(run, t, body): t for t in targets}
        for fut in as_completed(futs):
            card = fut.result()
            hook(root, kind="synapse",
                 summary=f"send {card.get('to')}",
                 instance_id=card.get("session_id"),
                 extra={"to": card.get("to"), "ok": card.get("ok")})
            cards.append(card)
    cards.sort(key=lambda c: str(c.get("to")))
    ids = [c.get("session_id") for c in cards]
    if len(targets) >= 2 and len(set(ids)) < 2:
        raise MergedSessionError("parallel send merged session ids")
    return cards
```

That shape is already in `src/convoy/synapse.py` / `cli.py`. Live dual needs the runner to be a real harness CLI, `--label` + JSON `session_id` (Step 1), probe-before-spawn (Step 5), and argv that does not split.

### Implementation

- Keep `ThreadPoolExecutor` in `send_many`. Default runner stays fake so unit tests do not exec ola-brain.
- `--live` execs `ola_runner`. Live dual on the demo host must pass `--label`, parse JSON `session_id`, stamp two hook rows, return two cards.
- grok argv must not split (an early live failure). agy must see the prompt, not print a generic hello.
- Probe first (Step 5): do not start a 120s Claude hop when `/usage` already said 100%.
- MCP `send` with two sequential or parallel calls must produce two cards in this thread, not a Shell paste.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Not dry-run. Not fake runner.

---


## Phase 7 Durable convoy_id / attach

### Definition

A durable `convoy_id` keys harness + model + thread (`session_id`) + worktree to one convoy. The hop chip is a live seat. The convoy is the parent. Home layer is `--root` (demo: `<demo-root>`). Seats MAY point at other worktrees (Phase 6 dual hop: grok on <demo-root>, claude on a second checkout). One convoy, many worktrees.

Knowledge layer = `context.pack` pointers (`thread.md`, `role.md`, brief, handoff, branch, sha, worktree) plus feed. Not packed transcripts. A closed Grok Bot chat can `attach` and resume those seats on the same pointers. Resume uses the registered `session_id`. Do not mint a sibling `grok-session-*` and call it the same seat. Unknown fields are JSON `null`. Model on a seat is stored if provided; do not invent one.

### Successful functions

- **GREEN unit:** `test/demo/phase7_attach_test.py` (14 tests). Prior 8: `init` writes `.convoy/id` (`cvy_` + url-safe random); second `init` same id. `id` before init is JSON `null` and does not create. Two seats (grok + claude) under one `convoy_id`, different worktrees; `seats` returns both; session_ids unchanged. `attach` unknown id → `ok` False, `convoy_id mismatch`, no seats. `attach` after init+seats → `ok` True, same `convoy_id`, both seats, pointers dict with no file contents. Fake-runner send WITH `instance_id` resumes `sess-grok` (not `spawned-grok`). Fake-runner send WITHOUT `instance_id` when a grok seat exists → refuse, do not spawn. Dry-run `session_id` still JSON `null`. Fold-in 6: `bind` writes `.convoy/thread` + short `thread.md` (convoy_id + thread key); pack/attach `pointers.thread` is the path, not file bytes; bind does not mint a second convoy_id; first attach stamps kind `attach` with `since` JSON null and `feed` `[]`; second attach `since` == first `ts`, feed includes the first attach row (`ts >= since`), second `ts` > first; mismatch attach does not append an attach hook; `send_one` card has `convoy_id` from `read_id` after init (null if none).
- **GREEN live attach:** `init` wrote `<demo-convoy-id>` at `<demo-root>/.convoy/id`. Seated `<demo-grok-session>` (`grok-4.6`, <demo-root>) and `<demo-claude-session>` (`claude-fable-5`, a second checkout). `attach` returned both plus pointers (the demo checkout's branch, PR number and sha). Spawn without `--instance-id` refused `seat exists`. Wrong id refused `convoy_id mismatch`.
- **RED live (parent):** bind this Grok Bot thread, two attach stamps, `feed --since`, resume hop body. Not done on the demo host yet.
- **RED live resume hop:** `send --live --instance-id <demo-grok-session> PHASE7_ATTACH` kept that session_id (no sibling mint) but `ok` false, TimeoutExpired 120s. ola-brain invoked `grok.EXE -p ... -c` (continue latest in cwd), not a successful turn body. Hostile. Bring-up must not use grok `-p` or `-c`.
- **GREEN unit:** `test/demo/phase7_bringup_test.py`. `resume_argv` is native `[grok, --resume, session_id]` / `[claude, --resume, session_id]`, cwd=worktree. Not ola-brain, not `side-chat`, not grok `-p`/`-c`/`--output-format`. Dry-run `bring-up` / `open` returns two windows, distinct tile rects on 1920x1080, conductor grok-bot is not a window, `resume` equals registered `session_id` (never minted). `resume_key = "cvr_" + sha256(convoy_id + "\0" + thread + "\0" + to + "\0" + worktree).hexdigest()[:16]`; same convoy_id+thread+to+worktree → same key; a different thread, a different harness, or a different worktree each give a different key (`phase7_bringup_test.py` `test_resume_key_same_inputs_same_hash_different_thread_differs` asserts all of them). Lookup by thread+to returns the same resume. Missing session_id refuses that seat. MCP JSON cards exist in CLI (`bring_up` / `terminals`); attach/read can be partial GREEN, native `send` remains RED.
- **GREEN unit (first-run ungate):** `test/demo/phase7_first_run_test.py`. Anthropic ignores project `skipDangerousModePermissionPrompt`; user-level `~/.claude/settings.json` is required for that one key (do not set user-global `defaultMode`). `ensure_first_run` writes thread `{worktree}/.claude/settings.local.json` (inbox and Stop hooks + `autoCompactEnabled: true`, never in the home file; no permission keys in any project file), merges `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create dir if missing; merge existing home keys), and persists `~/.claude.json` `projects[worktree].hasTrustDialogAccepted=true` for slash/backslash worktree keys. Refuses if worktree is home. Home preparation is harness-specific, not a universal no-op. A dry run refuses the `--write-repo-files` / `write_repo_files` opt-in before writing person-ownable repo files. Without that opt-in a dry run still writes nothing anywhere: no `~/.bashrc`, `AGENTS.md` pointer, `.git/info/exclude` entry, `~/.claude/settings.json`, `~/.claude.json` trust or `.claude/settings.local.json`. Dry-run `bring_up` records the plan (`first_run.dry_run`, `dry_run_writes`, `would_write_home`, `settings_home`, `trust_settings_home`) and does not Popen `wt`. A live first run stamps the chair's launch heartbeat (`usage_heartbeat`, or `usage_heartbeat_error`). Live Claude argv adds `--allow-dangerously-skip-permissions` (no duplicate) plus `--permission-mode bypassPermissions`. `isolated_wt_argv` is a pure argv builder. Live GREEN on WT 1.24.11911.0 (demo host), before the one-window-per-thread placement: `--window new`, first command `nt`, n=3 one `-V` then one `-H`, absolute exe positional after `-d DIR` (never `--` before the exe; that pops GUI Help), never `-w 0`, `-w <thread-name>` popped Help, literal `;`. Superseded by "Placement: one terminal window per thread" (`-w convoy-<8 hex>`), live-verified on WT 1.24.11911.0 (named-window new-tab then split-pane -V: one separate window, both panes, no Help); `--` before the exe and `-w 0` stay forbidden. No live WT spawn in unit tests.
- **GREEN unit (isolated live_runner wire):** `bring_up` + `live_runner` spawn **one** `wt.exe` per named thread, into that thread's own window. Argv matches `isolated_wt_argv`. Never per-seat `CREATE_NEW_CONSOLE`, never `MoveWindow`, never `WM_CLOSE` (a close-on-fail test once closed an unrelated terminal session, because `--window new` shares one `WindowsTerminal.exe` process). Duplicate-launch guard: do not add the same seat twice (same worktree+to, or same resume_key/session_id). Not one pane per harness name — two grok hops on different worktrees (wt-grok-1 vs wt-grok-2) are two panes (n=3 claude+grok+grok: `-w convoy-<8 hex>`, `new-tab`, `; split-pane -V`, `; split-pane -H`). Grok Bot conductor is never a window. Titles `{to}-{i}`.
- Unit tests BYO fake abs binaries under `test/fakes/`; never vendor login; live WT is Windows-only.

- **GREEN live isolated n-pane TDD:** `<demo-root>/.convoy/tdd-panes.jsonl`. One new CASCADIA per combo, splits inherited: n=2 grok+grok, n=2 claude+grok, n=3 claude+grok+grok, n=2 claude+claude. An unrelated terminal window was left untouched. `--version`, `-w <name>`, and `--` before exe popped WT Help 1.24.11911.0 (RED, dialog closed).
- **RED live bring-up:** parent pops visible TUIs only when the human says bring up a thread. Do not exec live TUIs from unit tests.

### Pseudo-code

```python
def ensure_id(root):
    path = root / ".convoy" / "id"
    if path.is_file():
        return path.read_text(encoding="utf-8-sig").strip()  # never regenerate
    cid = "cvy_" + urlsafe_random()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cid + "\n", encoding="utf-8")  # one line, no BOM
    return cid

def read_id(root):
    path = root / ".convoy" / "id"
    if not path.is_file():
        return None  # do not create
    return path.read_text(encoding="utf-8-sig").strip() or None

def make_resume_key(convoy_id, thread, to, worktree=None):
    blob = convoy_id + "\0" + thread + "\0" + to + "\0" + (worktree or "")
    return "cvr_" + sha256(blob).hexdigest()[:16]

def seat(root, to, session_id, worktree=None, model=None, resume=None):
    if not session_id:
        raise ValueError("refuse empty session_id")
    cid = ensure_id(root)
    thread = read_thread(root) or ""
    resume_val = resume or session_id  # never invent; default session_id
    row = {"convoy_id": cid, "to": to, "session_id": session_id,
           "worktree": worktree, "model": model,
           "resume": resume_val, "resume_key": make_resume_key(cid, thread, to, worktree)}
    append_jsonl(root / ".convoy" / "seats.jsonl", row)
    register(root, session_id, to, extra={...})
    return row

def list_seats(root, convoy_id=None):
    # utf-8-sig (a BOM happened on the demo host). latest row per session_id
    ...

def attach(root, convoy_id=None):
    disk = read_id(root)
    if convoy_id is not None and convoy_id != disk:
        return {"ok": False, "error": "convoy_id mismatch", "convoy_id": disk, "seats": []}
    if convoy_id is None and disk is None:
        return {"ok": False, "error": "no convoy_id"}
    cid = convoy_id or disk
    return {"ok": True, "convoy_id": cid, "seats": list_seats(root, cid),
            "pointers": pack(root)}  # home layer pointers; do not merge other worktrees

def send_one(root, to, body, instance_id=None, dry_run=False, **kw):
    if dry_run:
        return {"ok": True, "session_id": None, "dry_run": True, ...}
    if instance_id:
        return resume(to, instance_id, body)  # registered session_id only
    cid = read_id(root)
    if cid and any(s.get("to") == to for s in list_seats(root, cid)):
        return {"ok": False, "session_id": None,
                "error": "seat exists; attach and resume session_id"}  # no sibling spawn
    return spawn(to, body)
```

### Implementation

- `src/convoy/convoy.py`: `ensure_id`, `read_id`, `read_thread`, `bind`, `seat`, `list_seats`, `attach`, `make_resume_key`, `lookup_resume`.
- Persist `.convoy/id` and `.convoy/thread` (one line each, utf-8, no BOM) and `.convoy/seats.jsonl` (utf-8 write, utf-8-sig read). `bind` writes short `thread.md` (convoy_id + thread key only).
- `seat` stamps `convoy_id` from `ensure_id` and calls existing `register()` so `lookup` / `--instance-id` resume still works. Optional `resume=` stored on the row (default `session_id`). Always stores `resume_key`.
- CLI: `init`, `id`, `bind --thread KEY`, `seat --to H --session-id S [--worktree P] [--model M] [--resume R]`, `seats [--convoy-id ID]`, `attach [convoy_id]`, `bring-up`/`open` `[convoy_id] [--thread T] [--dry-run]`, `terminals`.
- `send_one` guard: harness name, seat already exists under this convoy, no `instance_id` → refuse spawn. Dry-run still cannot mint a session_id. Cards include `convoy_id` from `read_id(root)` (JSON null if none).
- Successful `attach` calls Phase 2 `hook(kind="attach")` and returns `thread`, `ts`, `since` (prior attach ts or null), `feed` (`feed_since` when since set, else `[]`). Failed attach does not stamp. Pointers = `pack(root)` only.
- `src/convoy/bringup.py`: `resume_argv(seat)` emits native argv (`grok/claude --resume <id>`, `codex resume <id>`, and no resume flag when vendor id is unknown on first-run). `ensure_first_run` writes thread `.claude/settings.local.json` (hooks and `autoCompactEnabled: true`; no permission keys), merges user-level `skipDangerousModePermissionPrompt` into `~/.claude/settings.json`, and marks `~/.claude.json` trust (`projects[worktree].hasTrustDialogAccepted=true` for both slash spellings). `isolated_wt_argv` builds WT argv (`-w convoy-<8 hex>`, no `--` before exe; Claude live `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`; no spawn). `bring_up` with a runner fires **one** `isolated_wt_argv` via `live_runner` (Popen FileName=wt, ArgumentList=argv[1:]; never per-seat `CREATE_NEW_CONSOLE` / `MoveWindow` / `WM_CLOSE`). Default runner no-op; a dry run writes nothing and reports the first-run plan. `tile_rects` still on window cards. `terminals` metadata, no PTY, no first run. ola-brain / side-chat / UltraCode-Shim is not in argv and not an MCP tool name.

### Definition of done

- **unit GREEN:** bind + attach stamp + since (14 tests in `test/demo/phase7_attach_test.py`). Bring-up dry-run unit in `test/demo/phase7_bringup_test.py`. Live still RED for parent (bind this Grok Bot thread, two attach stamps, feed --since, resume hop body, visible bring-up TUIs).
- **live attach GREEN / live bind+two-attach+feed --since+resume hop RED / live bring-up RED:** see Successful functions. Phase 7 is not fully GREEN. Do not start Phase 8.

## Installer (`npx deploy-forward`)

One package, sibling repo `deploy-forward/deploy-forward`. Flags:

| Flag | Meaning |
|---|---|
| `--convoy` | Install / wire Convoy MCP + hop CLI |
| `--tracker` | Install DF tracker |
| `--board` | Install DF board. **Requires tracker.** |
| y / n / i | Interactive per-component (yes / no / install) |
| `--yes` | Confirm the current prompt. **`--yes` is not all-yes.** |

White-glove path: `npx deploy-forward --convoy`, run `convoy mcp` and attach `http://127.0.0.1:8788/mcp`, `roster` says who will actually hop, then `send` fires grok / claude / codex / agy / cursor-agent as themselves.

Keep this section short. Installer code does not live in this tree.

---

## Demo log

The demo thread key is `demo`. Tests live in `test/demo/`. These tests must fail until native code passes them. No invented usage. No claiming MCP until HTTP works from this chat.

- Temporal hooks: **GREEN** on the demo host. `convoy hook` stamps `{ts,kind,instance_id,summary}` to `.convoy/feed.jsonl`. `convoy feed --since` returns that window. This is not ola-brain `hook-context` / `precompact` / `session-end`. Unit GREEN: `test/demo/temporal_hooks_test.py`. Code GREEN: `src/convoy/layer.py` `hook()`, `feed_since()`. The demo rows were written to `<demo-root>/.convoy/feed.jsonl` through a local wrapper script (not in this repository).
- Parallel native chat: **GREEN** on fake runner (`python -m convoy send --to grok --to claude`). **GREEN** on the demo host's `send-dry` (two distinct `session_id` values, two hook rows: `<dry-grok-session>` and `<dry-claude-session>`). **LIVE dual hop not proven:** the Claude session was at its limit and Codex was out of credits. Sequential live hops were proven earlier (synapse-proof / SYNAPSE_OK / SYNAPSE_TURN2 / SYNAPSE_TURN3, registry `<redacted-vendor-session-id>`). The first grok+agy live attempt started both together, but grok argv split and agy printed a generic hello (prompt not seen).
- History (before 1.3.2): Grok Bot HTTP MCP was absent from the catalog; that chat was not natively connected. Status **RED** for HTTP MCP, **GREEN** for PC CLI hop via a shell on the demo host running two local wrapper scripts (not in this repository) around `ola-brain.exe`. Stdio MCP to Windows `localhost:4717` from the Grok Bot box **failed**.
- Threaded context: **GREEN** ola-brain `side-chat send grok --label synapse-proof`. **GREEN** the local wrapper's `context` command (packed pointers). **RED** CLI side-chat send skips IDE hydration pointer (cold message). **RED** Codex JSON has no `session_id` so next turn is `resume --last` (hostile). **RED** dry-run printed instance id without `register_agent`. **Corrected at `f40b01a`:** `src/convoy/context.py` ships (`pack` / `stdin_for`, pointers only) and is imported by `synapse.py` and `mcp_http.py`; `registry.parse_session_id` reads JSON or an ola-brain `instance_id:` reply and has no UUID regex. The `ola_runner` line is history: that path is retired.
- Feature branch understanding: **GREEN code + unit + live artifact (corrected at `f40b01a`).** `gitstate.git_state()` is merged into every synapse row by `synapse.send_one`; rows carry `git_branch` / `git_sha` / `pr_number`. Unit: `phase3_branch_test.py`.
- Worktree understanding: **GREEN code + unit (corrected at `f40b01a`).** The worktree is stamped on every synapse row and passed as `cwd` into the runner. Unit: `phase4_worktree_test.py`. Live **native** dual-worktree hop stays `null`.
- Usage remaining: **GREEN** probes as logged below. **GREEN** roster `usageRemaining` JSON `null` (never guesses). A Claude session at its limit and Codex out of credits blocked the dual hop. Grok / cursor-agent / agy / Gemini probes do not expose remaining quota.
- Usage probes: `claude -p /usage` JSON parses the 5-hour session percent, its reset time and the week percents. `codex login status` reports the login; `codex doctor` is silent on quota; `codex exec /status` with stdin closed prints `Your workspace is out of credits.` when the workspace has none. Hop without probe hung. grok has no `/usage` (models/doctor/login only); probe aborted. `cursor-agent status` reports the login (`<account redacted>`), no remaining quota in status/about. `agy.exe` present with `-p`, not on ola-brain agents list. Gemini auth unknown.

---

## Honesty bar

Claims in this file must be true of **this tree** or of a named demo run with a timestamp. If a function is not in `src/convoy/`, it is not GREEN for this tree.

The rows below describe this tree (`convoy` 1.4.1); the table began as the inventory of `f40b01a` (merge of PR #24) and has grown with the tree, so it carries no module or test count.

| Path | What it actually does |
|---|---|
| `src/convoy/__init__.py` | Package marker. |
| `src/convoy/__main__.py` | `python -m convoy` entry: `raise SystemExit(cli.main())`. |
| `src/convoy/bringup.py` | Phase 7 bring-up: `resume_argv` (native `[exe, --resume, id]`, never ola-brain / side-chat / grok `-p`/`-c`), `isolated_wt_argv`, `tile_rects`, `ensure_first_run`, `live_runner` (one `wt.exe` per named thread), `bring_up`, `terminals`, `hide`. Conductor grok-bot is not a window. |
| `src/convoy/cli.py` | CLI: `context`, `send`, `hook`, `feed`, `stamp`, `glance`, `onboard`, `mcp`, convoy id/attach/seat/bind helpers, bring-up / hide / install paths. Live `send` sets `runner = native_runner` and `allow_interactive_resume = not live`. |
| `src/convoy/context.py` | `pack()` / `stdin_for()`, `newest_handoff()`. Pointers only, never file contents, never a vendor transcript. |
| `src/convoy/convoy.py` | Durable `convoy_id`: `ensure_id`, `read_id`, `bind`, `seat`, `list_seats`, `lookup_resume`, `attach`, `make_resume_key` (`cvr_` + sha256 prefix), lead. |
| `src/convoy/gitstate.py` | `git_state()`: live `git rev-parse` + `gh pr view` probes. Non-git is JSON `null`. Never invents `main`. |
| `src/convoy/glance.py` | `build_overall` / `build_by_thread` / `build_glance` / `discover_threads`, optional `run_tray`. Read-only view, not a second source of truth. |
| `src/convoy/harness_contract.py` | Loads `harness_effort.json`: `canonical_harness_id`, `harness_exec`, `usage_probe_key`, `usage_remaining_null_until_live_probe`. |
| `src/convoy/harness_effort.json` | The harness/effort contract data. |
| `src/convoy/identity.py` | In a minted worktree or with `--write-repo-files`, writes the `AGENTS.md` pointer to the convoy plugin; replaces an existing block only when its sha256 is in `KNOWN_AGENTS_BLOCKS`, else leaves the file and warns. Writes the Grok and Claude hook files with the bare `convoy` command (never `.codex/hooks.json`; the plugin carries Codex's hooks). Writes no skill text, no agent file and no prompt, and deletes nothing. |
| `src/convoy/version.py` | `convoy --version`: version (the checkout's `pyproject.toml` from a source checkout, else the distribution metadata), executable, source, editable. `mcp_http` takes its base version from here. |
| `src/convoy/assets/logo.svg` | The widget's logo, shipped as package data. |
| `src/convoy/install.py` | Opt-in vendor install. Refuses unknown or wrapped harnesses and non-vendor hosts. Dry by default. |
| `src/convoy/layer.py` | `hook()`, `feed_since()`, `conductor_stamp()`, `utc_now()`, `feed_path()`, `SCHEMA_VERSION = 2`. The module writes the feed; branch / worktree / usage reach a row as `extra` from the caller, not from here. Feed contract v2.1 adds `neuron_note` plus an **attributed** `from` and an addressee `to` — see that section, which is the source of truth for it (attributed, not authenticated: the bus records a claimed `instance_id`). |
| `src/convoy/mcp_http.py` | JSON-RPC POST `/mcp`. Tool availability is always discovered from live `tools/list` at runtime (never copied from docs). Live `send` routes to `native_runner` with `allow_interactive_resume=False`. Attach/read tools may be PARTIAL GREEN when bound; native `send` stays RED until a live vendor execution is proven on the loopback MCP. Serves loopback requests only: a foreign `Host` or `Origin` is a 403, and no response carries CORS headers. |
| `src/convoy/onboard.py` | Declared-harness onboarding: refuse wrappers, probe only named harnesses, optional thread bind, install hints, first-run PATH ungate. |
| `src/convoy/registry.py` | Instance registry: `register`, `lookup`, `parse_session_id`, `parse_agents_jsonl`, `live_on_branch`. No printed `session_id` without a row. |
| `src/convoy/synapse.py` | `fake_runner` (default), `native_runner` (`--live`: vendor binary on PATH, wrapper names refused, `cwd=worktree`), `send_one` / `send_many`. Live mode is native on both CLI and MCP. Wrapper names (`ola-brain`, side-chat, UltraCode-Shim) are refused as a harness. |
| `src/convoy/usage.py` | `probe()`, `normalize_usage_remaining()`, `surface()`. Unknown remaining is JSON `null`; never invent `0`; grok remaining is always `null`. |
| `test/run.py` + `test/demo/` | The suite: `python -m unittest test.demo.<module>` runs one module. |
| `pyproject.toml` | `convoy` 1.4.1, packages under `src`, requires-python >= 3.11. |

We do not:

- Wrap Grok as `claude-grok-4-6` (or any Anthropic-shaped alias) behind Claude Code / UltraCode-Shim.
- Proxy `cli-chat-proxy.grok.com` / `api.x.ai` / Codex OAuth / cursor-agent HTTP so another product can wear our meter.
- Merge native sessions. A synapse execs the harness CLI the human already signed into. The other CLI keeps its own `session_id` and its own meter.
- Pretend a LAN stdio MCP to Windows `localhost:4717` is a conductor's MCP.
- Invent usage numbers, branch names, session ids, or MCP attach.
- Claim full HTTP MCP GREEN on unit tests alone. Live `send` routes to `native_runner` in code (`75f00c7`); GREEN needs a timestamped live vendor execution on the loopback MCP, not a passing suite.
- Land this MCP in the closed platform repo.

If a PR starts looking like UltraCode-Shim (OnlyTerp, https://github.com/OnlyTerp/UltraCode-Shim — local proxy, Claude Code stays the shell, `/model` ids must start with `claude` or `anthropic`, Grok becomes a backend, `grok_build` hits `cli-chat-proxy.grok.com`), it does not land in `deploy-forward/convoy`.

Bring your own harness. Do not bring your own API key into someone else's harness.

Unknown is `null`. Limited is refuse. Dry-run is not live. Feed is the layer, not vendor `--resume`. The thread stays skinny.

## Phase 6 Parallel native send

Fire more than one synapse at once. Each keeps its own `session_id`. Sequential `@mention` is not this step.

GREEN: `test/demo/parallel_agents_test.py` fake runner. The demo host's `send-dry` wrote `<dry-grok-session>` and `<dry-claude-session>` plus two hook rows.

RED live: grok+agy started together but grok argv split and agy never saw the ping.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread.
