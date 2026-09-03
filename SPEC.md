# Convoy

**Repo:** `deploy-forward/convoy` (Grok Bot HTTP MCP + neuron CLI)
**Sibling:** `deploy-forward/deploy-forward` (`npx deploy-forward`, tracker, board)
**Native platform:** `Deploy-Forward/platform` (NOT this MCP)
**Sites:** https://convoy.bot (Grok Bot MCP + frontmatter, tweet this) · https://convoy.deployforward.dev (launch product, not live yet, not the tweet)
**Audience:** engineers who can read a CLI, a JSON card, and a git checkout.
**Status of this tree:** work lives at `/workspace/convoy` on the Grok Bot box. Public repo: `https://github.com/Deploy-Forward/convoy`. Names: see `CANON.md`.

This file is the source of truth for **this repo only**. Native platform Convoy and the public capture layer are sibling products. Do not put this MCP in `Deploy-Forward/platform`.

Convoy lets you stay in one thread and send work to other harnesses (Grok, Claude, Codex, cursor-agent, agy) without merging their native sessions. The other harness works on its own meter. You get a compact result back. Main context stays skinny.

That sentence is the product. Everything below is how it is actually true, or honestly not true yet.

Bring your own harness. Do not bring your own API key into Claude Code. Named refuse: UltraCode-Shim (OnlyTerp). We do not wrap Grok as `claude-grok-4-6`. We do not proxy `cli-chat-proxy.grok.com`.

---

## Canonical lock (2026-08-30)

This block is authoritative for Grok Bot MCP layering and native-send DoD. If older notes below disagree, this block wins until they are rewritten.

### Terminology lock (2026-09-01)

- Grok Bot = conductor.
- neuron = one grok/claude/codex/cursor-agent session on a thread.
- synapse = native `send` into that neuron (not `ola-brain side-chat`).
- thread = durable circuit (`convoy_id`).
- named thread = `--root` binding, not a second MCP URL.
- Product wording retires "hop" in current product sentences; historical logs below may still quote it.
- Harness self-identity: first-run installs `neuron-identity` skills into the seat worktree so a launched model knows it is a neuron on a `cvy_id`.

### Feed contract v2 (2026-09-01)

One MCP endpoint. What is versioned is the feed contract, not the URL — a named thread stays a `--root` / `cvy_id` binding.

- `schema_version: 2` rides feed envelopes (MCP `feed`, CLI `feed --since`, the `attach` card). Not a second feed format: `.convoy/feed.jsonl` stays the single `layer.py`-written file, v1 rows keep flowing, and readers skip kinds they do not know.
- Kinds are additive. v2 defines:
  - `conductor` — ONE compact line stamped by the conductor (MCP tool `stamp`, CLI `python -m convoy stamp`). Front-matter shape: `agent` / `model` / `effort` real-or-null, optional `instance_id` (the conductor agent id) and `transcript` (a pointer to where the bubble lives, never its bytes). Summary clamps to one line of ≤ 500 chars; a clamp marks `truncated: true`. The Grok Bot bubble history is not a Convoy object; neurons never receive it.
  - `synapse` — unchanged.
  - `refuse` — the feed row now carries the full `ask` card (`action: bring_up`, `handoff: .ola/*handoff*`, text), so a sibling pulling `feed --since` sees the remedy without having been the caller.
- Pack stays pointers. Unknown stays JSON `null`. Neurons pull the thread (`feed --since`); nothing in v2 mints a sibling session or steals a TUI.

### Feed contract v2.1 (2026-09-01, additive — stress-test increment)

Locked from the fable-opus stress findings (audit trail: docs/audits/; further artifacts live in the session worktrees that produced them). Additive only; v1/v2 rows keep flowing.

- **Attributed author `from` + addressee `to` on rows (corrected 2026-09-02, OPUS-2 verified defect).** `from` is AUTHORSHIP and appears ONLY where an author is actually claimed: note-family rows (`hook`/`neuron_note`, default `author` = `instance_id`) and conductor rows (`stamp`, `from: "grok-bot"`). On `synapse`/`refuse` rows `instance_id` is the row's SUBJECT — the target/spawned session — so `from` is **absent** there (`author=None` at the call sites): sender-unknown recorded as absence, never as a confidently-wrong name. (The original v2.1 wording let `hook` promote any `instance_id` to `from`, which put the RECIPIENT in `from` on every synapse row — live defect row `2026-09-02T03:11:06Z`.) `send` has no caller identity yet; giving it one (`from` = caller) is a future increment that must land before any @-addressing surface reads these keys. `from` remains claimed-not-authenticated. `grok-bot` stays refused as author under normalized aliasing (both `instance_id` and `author`); conductor identity is `stamp`-only. CLI: `hook ... --to X`.
- **`to` disambiguation (pre-existing key, two meanings).** On `note`/`conductor` rows `to` is the addressee. On `synapse`/`refuse` rows `to` remains what it always was: the send-target harness name. Readers filtering "rows addressed to me" must filter on kind `note`/`conductor` first; a bare `row["to"]=="claude"` filter also matches every send to the claude harness.
- **`note` — the neuron-side write, symmetric to `stamp`.** `layer.neuron_note` / MCP tool `note` (args `summary`, `instance_id` required, `to` optional): kind `note`, same one-line ≤500 clamp as stamp (`truncated: true` on clamp), refuses anonymous or conductor-alias authors. This is the hosted-neuron write path; local neurons may keep using CLI `hook note`.
- **Runner provenance on synapse rows.** Every synapse row stamps `runner` (`"native"`/`"fake"`/`"ola"` by function identity via `synapse.runner_kind`, else the runner's name) and `argv0` (from the card's argv, JSON `null` when absent) — so the SoT can distinguish a native vendor send from a fake ACK. Rows without these fields predate v2.1 and are not evidence of a native send.
- **Build id on the wire.** `initialize` `serverInfo.version` is `0.1.0+<git describe --always --dirty>` when the package sits in a git checkout (`-dirty` marks a patched-in-place deploy), bare `0.1.0` when unknown (never an invented sha). A hung/missing git degrades to the bare version — it must never stop the server (`OSError` and `SubprocessError` both caught). Scope honesty: one-call drift detection holds only for git-checkout deploys; the bare-`0.1.0` fallback is indistinguishable from a pre-v2.1 deploy.
- **One process ↔ one bound root (R-05 resolution, option B).** The public MCP stays bound to exactly one root (demo: <demo-root>). Other threads are CLI/file on their own `--root`; an empty MCP `feed` for an unbound thread is the contract working, not a product fail. No root selector on the public URL (arbitrary-path read hole). Rebinding demo to flip a test GREEN is refused.
- **Public write-tool gate (N-5).** The RPC layer never exposes SoT write tools (`stamp`, `note`) on an ungated process: they are absent from `tools/list` and refused on `tools/call` unless `CONVOY_MCP_WRITE_TOOLS=1` is set (a gated/loopback deploy opts in). CLI and in-process `call_tool` are not gated. The public convoy.bot process stays read-only for the bus until a real writer gate (shared-secret/OAuth) exists; N-5 stays RED on the wire until then.
- **Chip front matter (conductor render contract).** The chip a neuron message surfaces with (`harness / model / effort / session% / week% / convoy_id / vendor session id / worktree / summary`) renders from two existing reads, no jsonl archaeology: the `note` row carries `summary`/`from`/`to`; the glance by-thread seat card carries `to` (harness), `model`, `effort`, `resume` (vendor id), `worktree`, `session_pct` (from the headless `claude -p /usage` probe via `usage.surface`); `week%` comes from glance **Overall** (locked: never duplicated per-thread). `effort` is a declared seat field (`seat --effort`, real-or-null) — Convoy stores it and never sets vendor effort flags; unknown `effort`/`resume`/`model` are omitted from the card, never "unknown". No probe ⇒ usage stays null.
- **`notify` stays JSON `null` per harness** until a documented injection point is proven live. Not a tool, not a promise.

Unit: `test/demo/feed_note_provenance_test.py` (15 tests, GREEN 2026-09-01, suite 199).

### Seat lifecycle: join / swap / seated (ratified by Marco 2026-09-02)

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
  EVERY swap — Marco's ordering lock (close only after proof of life) + the
  no-steal lock forbid two live processes on one vendor session, so **no
  swap ever carries a vendor transcript; swap memory is Convoy state,
  always** → `bring_up` with a one-shot `boot_prompt` delivered as an
  initial POSITIONAL prompt (blessed exception; not `-p` — the session stays
  interactive): read thread.md + handoff, echo the token.
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

Unit: `test/demo/seat_lifecycle_test.py` (15 tests, GREEN 2026-09-02,
suite 232).

### Bodies: panes + whoami (Marco 2026-09-03, "detect → identify → send")

The registry knows only what Convoy launched. Live failure 2026-09-03
~04:44Z: codex-fable-opus was running in an unmanaged pane, registry
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

Unit: `test/demo/panes_test.py`. Live 2026-09-03: `panes` on fable-opus
showed the lead chair with two bodies by token (duplicate=true) and 12
unassigned harness processes on Windows.

### Delivery ladder: recorded → executed → delivered (codex/grok finding 2026-09-02)

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

Why the codex→grok relay showed nothing in the pane: an open TUI has no
message transport in Convoy. The pane host owns lifecycle only; `send --live`
refuses to resume an active session (no-steal); `send` without `--live`
records. The legal path to an open neuron is an ADDRESSED ROW (`hook note "…" --to
<chair>`) plus that neuron's own listener at its next turn boundary (claude:
bus listener; grok: PreToolUse `additionalContext`, tool-time only). That is
"queued", and it becomes "delivered" when the target acks. Idle-wake stays
unproven on every harness (D4 red).

Unit: `test/demo/tools_delivery_test.py`. Also landed: `graph`, `threads`,
`resume` (dry; `go` behind the write gate) as MCP tools, so neurons attached
over MCP can summon them.

### Graph: the ontology of attributions over a thread (Marco 2026-09-02, read side landed)

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
  (codex 2026-09-02: unacked pending is a first-class state).
- **Attestation** is `attested` on every bus-derived edge (claimed, not
  authenticated). `observed` is reserved for a vendor-record reader that does
  not exist yet; the field exists so the upgrade is additive.
- **Resume is a boolean, never a token:** `resume.available` is true only when
  the seat holds a token minted for its current harness (`resume_for`
  match); a swap nulls it by contract.
- **`graph --neuron S`** is the rejoin card: the chair, the parties it has
  talked with, and `{convoy_id, thread, path, last_row_ts}` to resume from.
  Unknown neuron refuses.
- **`place` (the post-hook, Marco 2026-09-02):** every neighborhood card
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
  (`lead: true`, a `lead` edge). `lead --to <harness>` without a chair match
  stays the legacy harness write. Bare `lead` reports both `lead` (harness)
  and `lead_chair`.
- **Not in this increment:** resume-by-neuron launch (`resume --neuron`),
  cross-thread edges (`fork` / `parent_convoy_id`), `observed` attestation.
  Graph is read-only by construction.

Unit: `test/demo/graph_test.py` (14 tests, GREEN 2026-09-02, suite 270).
Live: `graph --neuron codex-fable-opus` on the fable-opus root, same day.

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
- MCP tool: `glance` with optional `thread` / `convoy_id` arguments, read-only and safe for public URL use.

OSS/public vs closed/platform lock:

- **PUBLIC (`deploy-forward/convoy`)**: glance JSON data contract (CLI + MCP), honesty rules, optional lightweight tray JSON renderer.
- **CLOSED (`Deploy-Forward/platform`)**: polished native tray/notch app, leftover-$ billing scrapers, vendor settings scraping, and platform UI.

### Neighbors (canonical contrast)

- **Herdr (`herdr.dev`)** owns PTYs on a background server and agents type into sibling TUIs. Convoy does not use PTY paste as the hop bus and does not rebuild Herdr inside this MCP.
- **CNVS (`cnvs.dev`, Max Blade, closed-source macOS Swift ADE)** is voice + infinite canvas with in-app army controls. Convoy is one visible thread + one `cvy_id` + tied checkout contract, not a canvas product.
- **Buzz** is Slack-shaped agent chat. Out of scope except one contrast: their missing terminal view is why `bring_up` exists.

### Current code honesty (tree-verified)

- `src/convoy/mcp_http.py` `call_tool("send", ...)` sets `runner = native_runner if live else fake_runner`.
- `src/convoy/synapse.py` `native_runner` executes vendor binaries on PATH; wrapper names are refused.
- Live resumed send is refused at **both** send entry points: `cli.py` and `mcp_http.py` each pass `allow_interactive_resume=not live` into `synapse.send_one`, which refuses any `session_id` / `resume` on a live send rather than spawning a second interactive `--resume` process (documented RED no-steal lock). Refusal is enforced at both callers; 4 tests in `test/demo/phase_mcp_http_test.py` cover it.
- `src/convoy/mcp_http.py` `TOOLS` includes `onboard`, `hide`, and `install` (plus aliases), but a deployed process can still expose the 7-tool snapshot (`roster`, `send`, `feed`, `context`, `bring_up`, `open`, `terminals`).
- `src/convoy/bringup.py` and `src/convoy/install.py` refuse wrapper names (`ola-brain`, `side-chat`, `UltraCode-Shim`) for those tool paths.

### Native-send + structured talk DoD (locked)

#### Definition

Status: **RED** until live functions pass on `https://convoy.bot/mcp` without shell paste.

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
| Native platform | `Deploy-Forward/platform` | Skinny Convoy thread/layer inside Composer. Native `turn.send`. | Not this HTTP MCP. Do not land MCP code there. |

Demo talks to Grok Bot. Grok Bot opens synapses through Convoy. Each synapse lands on a harness the human already signed into. Three products, one thread.

---

## Objects: Thread, Layer, Synapse

| Object | Lives where | Shape | Owns | Does not own |
|---|---|---|---|---|
| **Thread** | The human conversation (this Grok Bot chat, or any customer thread). Front matter is in the chat, never invented. | Message to/From, Thread path, Skill on disk. The conversation is the durable unit. | The human's questions, compact cards coming back, the decision to open a synapse. | Vendor session_ids. Packed stdin. Full transcripts. |
| **Layer** | `.convoy/feed.jsonl` under a checkout root. On Aether demo: `<demo-root>/.convoy/feed.jsonl`. | JSONL of `{ts, kind, instance_id, summary, ...extra}`. Sliding window via `feed_since`. | Event time. Pointers (thread.md, role.md, `.ola/brief.md`, newest handoff, instance_id, worktree, branch, pr). Which neuron was touched, when. | Bytes of a vendor transcript. `hook-context` / `precompact` / `session-end` from ola-brain. Vendor `--resume`. |
| **Synapse** | One native send: Convoy execs one harness CLI, one instance, one meter. Card comes back compact. | `{ok, to, session_id, model, usage_remaining, body, ...}`. Hook row stamped on send/refuse/spawn. | That harness's native session_id. That harness's cwd/worktree. That harness's remaining quota (or JSON `null`). | Another synapse's session. Another synapse's branch. The Grok Bot main context window. |

Rules that follow from the table:

- Two synapses never share a vendor session.
- The layer is pointers and stamps, not packed bytes in stdin.
- Turn 2+ of a neuron resumes **that instance's** vendor session id only.
- Unknown fields are JSON `null`. Never invent `main`, never invent a token count, never invent a session id.

---

## How Grok Bot connects (MCP, historical details)

The canonical lock above is authoritative when this section disagrees.

Transport: HTTP MCP at `https://convoy.bot/mcp` (or a user daemon reachable from Grok Bot's computer). **NOT** stdio on the Grok Bot box pointing at Windows `localhost:4717`. That failed.

2026-08-28 wire snapshot (demo): Shell on Aether-Deployed `machineId` `<redacted>` running `C:\.grok\Invoke-AgentChannel.ps1` and `C:\.grok\ConvoyLayer.ps1` wrapping `ola-brain.exe`. MCP catalog had no Convoy plugin at that time. Status then: **RED** for HTTP MCP, **GREEN** for PC CLI hop.

`ConvoyLayer.ps1` is **not in this repo** (`find . -name "*.ps1"` at `b29c79b` returns nothing, audited 2026-09-01). It exists only on the Aether box, where it carried the 2026-08-28 contract: `hook`, `feed-since`, `send-dry`. Do not cite it as in-tree evidence. In this repo, default `python -m convoy send` uses `fake_runner` and `--live` uses `synapse.native_runner` (vendor binary on PATH). Live resumed send is refused at both entry points (RED no-steal lock) to avoid launching a second interactive resume process. HTTP MCP server code is in `src/convoy/mcp_http.py` (`python -m convoy mcp --root ROOT --port 8788`). Do not treat this paragraph as current attach status; use the canonical split above.

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

1. Live `https://convoy.bot/mcp` process serving `onboard` in `tools/list`.
2. Chat aliases `/onboard` and `/onboard -convoy` in connected Grok Bot sessions (only true once live MCP serves the tool).

#### `terminals`

Live windows + instance records for a thread (`thread=` or `convoy_id=`). Optional grep. **No PTY dump.** Pointers and metadata only (`to`, `session_id`, `resume`, `resume_key`, `worktree`, `rect`). Desktop access is this plus `bring_up`, not a second product. Conductor grok-bot is not a window. Historical 2026-08-28 snapshot marked HTTP MCP RED; use canonical lock for current status.

#### `context`

Packed pointers only:

- `thread.md`
- `role.md`
- `.ola/brief.md`
- newest handoff
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

Each window: `to`, `session_id`, `resume` (vendor id passed to `--resume`; never null if ok; never invented), `resume_key` (`cvr_` + sha256(convoy_id + "\0" + thread + "\0" + to + "\0" + worktree).hexdigest()[:16] — **four** fields; hash is the map key, resume is the harness argument; because `to` and `worktree` are hashed, the key CHANGES when a seat's harness or checkout changes, so it is a resume map key and never a stable seat identity — `session_id` is the seat), `worktree`, `rect` `{x,y,w,h}`, plus CLI extras `argv`, `ok`. Lookup by thread+to returns the same resume. No PTY dump. Historical 2026-08-28 snapshot marked HTTP MCP RED; use canonical lock for current status. CLI: `python -m convoy bring-up` / `open` `[convoy_id] [--thread T] [--dry-run]`.

First-run Claude bypass warning is ungated by `bring_up` / `ensure_first_run`. Anthropic ignores `skipDangerousModePermissionPrompt` in project `{worktree}/.claude/settings.json` — that key only works in the **user** file `~/.claude/settings.json`. Merge `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create `~/.claude/` if missing; merge, do not clobber other keys). Do **not** set `permissions.defaultMode` on the user global file (that would make ALL Claude sessions on the machine bypass). Still write the project copy (`skipDangerousModePermissionPrompt: true`, `permissions.defaultMode: bypassPermissions`) as a record. Also merge `~/.claude.json` `projects[worktree].hasTrustDialogAccepted = true` for both slash spellings of the worktree path. Never write `~/.claude` if the worktree **is** the home dir. Grok/codex no-op on Claude settings. Not a user paste. Not a step-by-step TUI guide. User once-gates only: attach `https://convoy.bot/mcp`, and vendor CLI login. `roster.present` is `shutil.which` on the MCP process PATH, not an already-open desktop terminal. Interactive bash skips `.profile`, so `~/.local/bin` (claude, codex) can be installed and still `command not found` while grok (`.bashrc`) works. `roster` and `bring_up` / `ensure_first_run` call `ensure_interactive_path`, which writes an idempotent `# >>> convoy harness PATH >>>` block into `~/.bashrc` (`$HOME/.local/bin` and `$HOME/.grok/bin`). No-op on Windows (WT inherits user PATH). Does not source a foreign PID; already-open terminals still need `source ~/.bashrc` or a new shell. Roster JSON includes `path` (`path_ok`, `path_written`, `path_bashrc`, `path_host`). Folder trust, Claude Bypass Permissions, `role.md` persona, isolated WT tiling, and agent-driven verify are Convoy's job. Dry-run still calls `ensure_first_run` (cards show `first_run.prepared`, `home_written`, `settings_home`, `trust_written`; `settings` stays the project path) and must not Popen `wt`. Claude live argv keeps `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`. Persona is `role.md` in the worktree, not CLI `--append-system-prompt`.



#### `install`

Opt-in vendor harness download. HTTP `dry_run` defaults true. Live requires `opt_in=true` (and CLI `--live --opt-in`). Does not log the user in. `affiliate` is always JSON null.

Allowed hosts only: `x.ai` (grok), `claude.ai` (claude), `chatgpt.com` (codex), `cursor.com` (cursor-agent), `antigravity.google` (agy). Refuse gemini CLI, community grok CLI, UltraCode-Shim, ola-brain. After a live install, `ensure_interactive_path` runs.

Unit GREEN: `test/demo/phase_install_test.py`.

#### `hide` (aliases `minimize`, `background`)

Default synapse (`send`) is headless: it never pops a TUI and never calls `live_runner` / `CREATE_NEW_CONSOLE`. `bring_up` / `open` is the only show command (HTTP `dry_run` still defaults true so a public URL cannot pop windows; CLI `bring-up` without `--dry-run` uses `live_runner`, which Popen's **one** `wt.exe` whose ArgumentList is `isolated_wt_argv` — FileName is wt, not in the list; `--window new`; first command `nt`; n=2 one `-V`; n=3 `-V` then `-H`; absolute exe positional after `-d DIR`; never `--` before the exe; never `-w 0`; never per-seat `CREATE_NEW_CONSOLE` + `MoveWindow`; never `WM_CLOSE`). Isolated spawn is a new WINDOW not a new PROCESS. Dry-run still calls `ensure_first_run` and must not Popen `wt`. Never ola-brain / side-chat / UltraCode-Shim. `hide` / `minimize` / `background` minimize neuron windows (Win32 `SW_MINIMIZE` = 6; optional `mode=hide` is `SW_HIDE` = 0). Sessions keep running. Not `taskkill`. Never kills `grok.exe` / `claude.exe` / `Grok Bot.exe`. Conductor grok-bot is not a window. `restore` is `bring_up`, not this tool. HTTP MCP attach is still RED.

### Front matter in this chat, never invented

```
Message to/From: {Agent} | {model} | {effort}
Thread: {filepath} | usage remaining {n|unknown}
Skill on disk: <agent-host>/workflows/agent-channel/SKILL.md
```

If a field is unknown, write `unknown` or JSON `null`. Do not fill it from memory.

### Definition of done (legacy attach checklist)

Historical attach checklist only. Current canonical DoD is the native-send + structured-talk block above: attach/roster/feed may be PARTIAL GREEN, while native `send` remains RED until a live vendor PATH execution is proven on `https://convoy.bot/mcp`. The code swap already happened (`native_runner`, `acba4e3`, 2026-08-30); what is missing is live proof, not the implementation.

---


## Phases (hard gate)

Step N is Phase N. Do not start Phase N+1 until Phase N Definition of done is GREEN, proven on demo (this chat / Aether). Unit tests with a fake runner are not enough to unlock the next phase.

| Phase | Name | Status |
|---|---|---|
| 1 | Threaded context | Unit GREEN (`phase1_threaded_context_test.py`). Live 2026-08-28 Aether auto-register `<demo-phase1-session>` is **retired-path evidence** (ola-brain `side-chat send`, pre-`native_runner`). Native path not re-proven live: `null`. |
| 2 | Temporally aware | GREEN. Unit `temporal_hooks_test.py`; live row `2026-08-28T14:42:46.975866Z` re-read in `<demo-root>/.convoy/feed.jsonl` on 2026-09-01. Runner-independent: the stamp path did not change with `native_runner`. |
| 3 | Feature branch | GREEN code + unit: `gitstate.git_state()` runs `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number`; `phase3_branch_test.py`. Live artifact: `git_branch integration/convoy-web-poc-20260828` + `pr_number: 167` on feed rows through `2026-08-31T12:00:12.490736Z`. |
| 4 | Worktree | Unit GREEN (`phase4_worktree_test.py`); worktree is stamped on every synapse row and passed as `cwd` into the runner. Live **native** dual-worktree hop unproven: `null` (the 2026-08-28 dual hop was the retired ola-brain path). |
| 5 | Usage remaining | **PARTIAL.** GREEN: unknown normalizes to JSON `null` — never `0`, never invented dollars (`usage.normalize_usage_remaining`, `harness_contract.usage_remaining_null_until_live_probe`, `phase5_usage_test.py`, `glance_test.py`); `claude -p /usage` and `codex` probes parse (2026-08-28). BLOCKED: grok, `cursor-agent`, `agy` expose no remaining quota at all — see the Phase 5 section. This row is not "usage remaining per harness". |
| 6 | Parallel native send | Unit GREEN (`parallel_agents_test.py`); Aether `send-dry` GREEN (`<dry-grok-session>`, `<dry-claude-session>`, two rows `2026-08-28T14:42:47Z`). Live dual 2026-08-28 11:59 ET (`<demo-grok-session>` + `<demo-claude-session>`) is **retired-path evidence** (ola-brain). Native parallel live: `null`. |
| 7 | Durable convoy_id / attach / bring-up | bind+attach GREEN 2026-08-28 `<demo-convoy-id>` thread `demo` — 3 attach rows and both seats (distinct `resume_key`) re-read 2026-09-01. Live resume hop is RED **by design** since 2026-08-31 (`273a345` no-steal lock), not a hang to fix. Live TUI bring-up RED. Not Phase 8. |

**Provenance of the 2026-08-28 GREENs (audited 2026-09-01 at `b29c79b`).** Every live run dated 2026-08-28 went through `ola-brain side-chat send` (`ola_runner`). `native_runner` — vendor binary on PATH — landed 2026-08-30 (`acba4e3`, PR #4); the no-steal live-resume lock landed 2026-08-31 (`273a345`, PR #12). The canonical lock names `ola-brain` a refuse target, so those runs are evidence about a **retired path**: they are not proof of DoD item 1 (native BYO send). No live native vendor send is recorded on any Convoy layer read on 2026-09-01. Unknown stays `null`.

MCP attach status is split: attach/roster/context/feed can be PARTIAL GREEN while native `send` is still RED. This remains a Phase 7 hole, not a Phase 8 launch.

## Phase 1 Threaded context

### Definition

The human conversation is the thread. The layer is pointers, not pack bytes in stdin. Turn 2+ resumes **this** instance `session_id` only. Two harnesses never share a vendor session. A dry-run that prints an instance id without a registry row is a bug.

### Successful functions

- **GREEN:** ola-brain `side-chat send grok --label synapse-proof` → `<demo-synapse-session>` `SYNAPSE_OK` 34s; turn 2 `SYNAPSE_TURN2` 11s; turn 3 via convoy mention `SYNAPSE_TURN3`; registry `session_id` `<redacted-vendor-session-id>` (2026-08-28 Aether).
- **GREEN:** `Invoke-AgentChannel.ps1 context` (packed pointers).
- **RED:** CLI side-chat `send` skips the IDE hydration pointer (cold message). Codex JSON has no `session_id` so next turn is `resume --last` (hostile).
- **RED:** dry-run printed instance id without `register_agent`.
- **GREEN (this tree):** `context.py` pack/stdin pointers. `ola_runner` passes `--label` before target. `parse_session_id` reads JSON or ola-brain `instance_id: reply` (must contain `-session-`). No UUID regex. Dry-run session_id is JSON null. Live 2026-08-28: pointers in, PHASE1_T1/T2, vendor `<redacted-vendor-session-id>`. CLI auto-register from stdout was the remaining gap.

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
- **GREEN Aether:** convoy hook stamps `{ts,kind,instance_id,summary}` to `<demo-root>/.convoy/feed.jsonl` via `C:\.grok\ConvoyLayer.ps1`. `convoy feed --since` returns that window. Example demo-locked ts `2026-08-28T14:42:46.975866Z`.
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
- **GREEN code (corrected 2026-09-01, `b29c79b`):** `src/convoy/gitstate.py` `git_state()` shells all three probes — `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number -q .number` — and `synapse.send_one` merges the result into every synapse row and registry entry. Never a remembered branch name; non-git is JSON `null`.
- **Live artifact:** `<demo-root>/.convoy/feed.jsonl` rows carry `git_branch: integration/convoy-web-poc-20260828`, `git_sha: 76874008c529cb908aded8de681af52d372cdd80`, `pr_number: 167` (re-read 2026-09-01). The earlier "in flight / when implemented" wording was stale.

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
- **GREEN code (corrected 2026-09-01, `b29c79b`):** CLI `send --worktree <path>`; the worktree is stamped on every synapse row and passed as `cwd` into the runner (`synapse.send_one` -> `native_runner(cwd=...)`). The retired `ola_runner` `--worktree` argv note is history.
- MCP `send` accepts `worktree`; live MCP proof on `https://convoy.bot/mcp` is still `null`.
- Live **native** dual-worktree hop: `null`. The 2026-08-28 dual hop was the retired ola-brain path (Phase 6).

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

- **GREEN probe:** `claude -p /usage` JSON. 5-hour session 100% used, reset 11:30 AM America/New_York 2026-08-28, week 69%, Fable week 70%.
- **GREEN probe:** `codex login status` logged in ChatGPT; `codex doctor` silent on quota; `codex exec /status` stdin closed ⇒ `Your workspace is out of credits.` Hop without probe hung.
- **GREEN roster field:** unknown `usage_remaining` is JSON `null`, never `0`, never invented dollars. In-tree proof: `usage.normalize_usage_remaining`, `harness_contract.usage_remaining_null_until_live_probe`, covered by `phase5_usage_test.py` and `glance_test.py`. (`Invoke-AgentChannel.ps1` was the 2026-08-28 Aether-side source and is **not in this repo** — do not cite it as in-tree evidence.)
- **Scope note (2026-09-01):** what is GREEN here is the honesty rule (unknown stays `null`), not per-harness remaining quota. The phase table row says PARTIAL for that reason.
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
- Never copy a number from memory. Live Claude at 100% is a probe result from 2026-08-28, not a constant in code.
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

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Each synapse on its own meter. Fake runner and Aether `send-dry` prove the plumbing. Live dual is the remaining bar.

### Successful functions

- **GREEN** fake runner: `python -m convoy send --to grok --to claude` (`src/convoy/synapse.py` `fake_runner` + `send_many` via `ThreadPoolExecutor`). Unit: `test/demo/parallel_agents_test.py` (`test_two_synapses_own_session_ids`). Distinct `session_id` values; CLI returns 2 if parallel send merged ids.
- **GREEN** Aether `send-dry`: `<dry-grok-session>` and `<dry-claude-session>`. Two distinct ids, two hook rows. Implemented in `C:\.grok\ConvoyLayer.ps1` `Send-Dry` (Aether-side only; no copy of that script exists in this repo).
- **GREEN** live dual 2026-08-28 11:59 AM ET: `send --live --to grok --to claude --label phase6b` with two worktrees. session_ids `<demo-grok-session>` (<demo-root>, PR 167) and `<demo-claude-session>` (ola-brain `feat/side-chat`). Both bodies PHASE6B. First try failed on grok cp1252 decode + ola-brain `--worktree` argv; UTF-8 replace + cwd-only worktree fixed it. Codex not hopped (probe timeout refuse).

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
- `--live` execs `ola_runner`. Live dual on Aether must pass `--label`, parse JSON `session_id`, stamp two hook rows, return two cards.
- grok argv must not split (the 10:51 ET failure). agy must see the prompt, not print a generic hello.
- Probe first (Step 5): do not start a 120s Claude hop when `/usage` already said 100%.
- MCP `send` with two sequential or parallel calls must produce two cards in this thread, not a Shell paste.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Not dry-run. Not fake runner.

---


## Phase 7 Durable convoy_id / attach

### Definition

A durable `convoy_id` keys harness + model + thread (`session_id`) + worktree to one convoy. The hop chip is a live seat. The convoy is the parent. Home layer is `--root` (demo: `<demo-root>`). Seats MAY point at other worktrees (Phase 6 dual hop: grok on <demo-root>, claude on ola-brain). One convoy, many worktrees.

Knowledge layer = `context.pack` pointers (`thread.md`, `role.md`, brief, handoff, branch, sha, worktree) plus feed. Not packed transcripts. A closed Grok Bot chat can `attach` and resume those seats on the same pointers. Resume uses the registered `session_id`. Do not mint a sibling `grok-session-*` and call it the same seat. Unknown fields are JSON `null`. Model on a seat is stored if provided; do not invent one.

### Successful functions

- **GREEN unit:** `test/demo/phase7_attach_test.py` (14 tests). Prior 8: `init` writes `.convoy/id` (`cvy_` + url-safe random); second `init` same id. `id` before init is JSON `null` and does not create. Two seats (grok + claude) under one `convoy_id`, different worktrees; `seats` returns both; session_ids unchanged. `attach` unknown id → `ok` False, `convoy_id mismatch`, no seats. `attach` after init+seats → `ok` True, same `convoy_id`, both seats, pointers dict with no file contents. Fake-runner send WITH `instance_id` resumes `sess-grok` (not `spawned-grok`). Fake-runner send WITHOUT `instance_id` when a grok seat exists → refuse, do not spawn. Dry-run `session_id` still JSON `null`. Fold-in 6: `bind` writes `.convoy/thread` + short `thread.md` (convoy_id + thread key); pack/attach `pointers.thread` is the path, not file bytes; bind does not mint a second convoy_id; first attach stamps kind `attach` with `since` JSON null and `feed` `[]`; second attach `since` == first `ts`, feed includes the first attach row (`ts >= since`), second `ts` > first; mismatch attach does not append an attach hook; `send_one` card has `convoy_id` from `read_id` after init (null if none).
- **GREEN live attach (2026-08-28 ~4:26 PM ET):** `init` wrote `<demo-convoy-id>` at `<demo-root>/.convoy/id`. Seated `<demo-grok-session>` (`grok-4.6`, <demo-root>) and `<demo-claude-session>` (`claude-fable-5`, ola-brain). `attach` returned both plus pointers (branch `integration/convoy-web-poc-20260828`, PR 167, sha `76874008c529cb908aded8de681af52d372cdd80`). Spawn without `--instance-id` refused `seat exists`. Wrong id refused `convoy_id mismatch`.
- **RED live (parent):** bind this Grok Bot thread, two attach stamps, `feed --since`, resume hop body. Not done on Aether in this fold.
- **RED live resume hop:** `send --live --instance-id <demo-grok-session> PHASE7_ATTACH` kept that session_id (no sibling mint) but `ok` false, TimeoutExpired 120s. ola-brain invoked `grok.EXE -p ... -c` (continue latest in cwd), not a successful turn body. Hostile. Bring-up must not use grok `-p` or `-c`.
- **GREEN unit (this fold, 2026-08-29):** `test/demo/phase7_bringup_test.py`. `resume_argv` is native `[grok, --resume, session_id]` / `[claude, --resume, session_id]`, cwd=worktree. Not ola-brain, not `side-chat`, not grok `-p`/`-c`/`--output-format`. Dry-run `bring-up` / `open` returns two windows, distinct tile rects on 1920x1080, conductor grok-bot is not a window, `resume` equals registered `session_id` (never minted). `resume_key = "cvr_" + sha256(convoy_id + "\0" + thread + "\0" + to + "\0" + worktree).hexdigest()[:16]`; same convoy_id+thread+to+worktree → same key; a different thread, a different harness, or a different worktree each give a different key (`phase7_bringup_test.py` `test_resume_key_same_inputs_same_hash_different_thread_differs` asserts all of them). Lookup by thread+to returns the same resume. Missing session_id refuses that seat. MCP JSON cards exist in CLI (`bring_up` / `terminals`); attach/read can be partial GREEN, native `send` remains RED.
- **GREEN unit (2026-08-29 first-run ungate):** `test/demo/phase7_first_run_test.py`. Anthropic ignores project `skipDangerousModePermissionPrompt`; user-level `~/.claude/settings.json` is required for that one key (do not set user-global `defaultMode`). `ensure_first_run` writes thread `{worktree}/.claude/settings.json` (`skipDangerousModePermissionPrompt` + `permissions.defaultMode: bypassPermissions`), merges `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create dir if missing; merge existing home keys), and persists `~/.claude.json` `projects[worktree].hasTrustDialogAccepted=true` for slash/backslash worktree keys. Refuses if worktree is home. Grok/codex no-op (no home write). Dry-run `bring_up` still calls it (`first_run.prepared`, `home_written`, `settings_home`, `trust_written`) and does not Popen `wt`. Live Claude argv adds `--allow-dangerously-skip-permissions` (no duplicate) plus `--permission-mode bypassPermissions`. `isolated_wt_argv` is a pure argv builder. Live GREEN on WT 1.24.11911.0 (Aether 2026-08-29): `--window new`, first command `nt`, n=3 one `-V` then one `-H`, absolute exe positional after `-d DIR` (never `--` before the exe; that pops GUI Help), never `-w 0`, never `-w <thread-name>` (Help), literal `;`. No live WT spawn in unit tests.
- **GREEN unit (2026-08-29 isolated live_runner wire):** `bring_up` + `live_runner` spawn **one** `wt.exe` per named thread. Argv matches `isolated_wt_argv`. Never per-seat `CREATE_NEW_CONSOLE`, never `MoveWindow`, never `WM_CLOSE` (close-on-fail TDD killed Marco's 7-tab `C:\` session because `--window new` shares one `WindowsTerminal.exe` process). Duplicate-launch guard: do not add the same seat twice (same worktree+to, or same resume_key/session_id). Not one pane per harness name — two grok hops on different worktrees (wt-grok-1 vs wt-grok-2) are two panes (n=3 claude+grok+grok: `--window new`, `nt`, `; split-pane -V`, `; split-pane -H`). Grok Bot conductor is never a window. Titles `{to}-{i}`.
- Unit tests BYO fake abs binaries under `test/fakes/`; never vendor login; live WT is Windows-only.

- **GREEN live isolated n-pane TDD (2026-08-29 ~4:21–4:23 PM ET):** `<demo-root>/.convoy/tdd-panes.jsonl`. One new CASCADIA per combo, splits inherited: n=2 grok+grok, n=2 claude+grok, n=3 claude+grok+grok, n=2 claude+claude. `C:\\` hwnd 67496 untouched. `--version`, `-w <name>`, and `--` before exe popped WT Help 1.24.11911.0 (RED, dialog closed).
- **RED live bring-up:** parent pops visible TUIs only when Marco says bring up a thread. Do not exec live TUIs from unit tests.

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
    # utf-8-sig (BOM happened on Aether). latest row per session_id
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
- `src/convoy/bringup.py`: `resume_argv(seat)` emits native argv (`grok/claude --resume <id>`, `codex resume <id>`, and no resume flag when vendor id is unknown on first-run). `ensure_first_run` writes thread `.claude/settings.json`, merges user-level `skipDangerousModePermissionPrompt` into `~/.claude/settings.json`, and marks `~/.claude.json` trust (`projects[worktree].hasTrustDialogAccepted=true` for both slash spellings). `isolated_wt_argv` builds WT argv (`--window new`, no `--` before exe; Claude live `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`; no spawn). `bring_up` with a runner fires **one** `isolated_wt_argv` via `live_runner` (Popen FileName=wt, ArgumentList=argv[1:]; never per-seat `CREATE_NEW_CONSOLE` / `MoveWindow` / `WM_CLOSE`). Default runner no-op; dry-run still ungates first-run. `tile_rects` still on window cards. `terminals` metadata, no PTY. ola-brain / side-chat / UltraCode-Shim is not in argv and not an MCP tool name.

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

White-glove path: `npx deploy-forward --convoy`, attach HTTP MCP at `https://convoy.bot/mcp`, `roster` says who will actually hop, then `send` fires grok / claude / codex / agy / cursor-agent as themselves.

Keep this section short. Installer code does not live in this tree.

---

## Demo log (2026-08-28)

The demo thread key is `demo`. Tests live in `test/demo/`. These tests must fail until native code passes them. No invented usage. No claiming MCP until HTTP works from this chat.

- Temporal hooks: **GREEN** on Aether. `convoy hook` stamps `{ts,kind,instance_id,summary}` to `.convoy/feed.jsonl`. `convoy feed --since` returns that window. This is not ola-brain `hook-context` / `precompact` / `session-end`. Unit GREEN: `test/demo/temporal_hooks_test.py`. Code GREEN: `src/convoy/layer.py` `hook()`, `feed_since()`. Example demo-locked ts `2026-08-28T14:42:46.975866Z` on `<demo-root>/.convoy/feed.jsonl` via `C:\.grok\ConvoyLayer.ps1`.
- Parallel native chat: **GREEN** on fake runner (`python -m convoy send --to grok --to claude`). **GREEN** on Aether `send-dry` (two distinct `session_id` values, two hook rows: `<dry-grok-session>` and `<dry-claude-session>`). **LIVE dual hop not proven:** Claude 5-hour session was 100% until 11:30 AM ET; Codex was out of credits. Sequential live hops were proven earlier the same day (synapse-proof / SYNAPSE_OK / SYNAPSE_TURN2 / SYNAPSE_TURN3, registry `<redacted-vendor-session-id>`). grok+agy first live attempt 2026-08-28 10:51 ET started together (pids `79160`, `94228`) but grok argv split and agy printed a generic hello (prompt not seen).
- Grok Bot HTTP MCP: still absent from the catalog. This chat is not natively connected yet. Status **RED** for HTTP MCP, **GREEN** for PC CLI hop via Shell on Aether-Deployed `machineId` `<redacted>` running `C:\.grok\Invoke-AgentChannel.ps1` and `C:\.grok\ConvoyLayer.ps1` wrapping `ola-brain.exe`. Stdio MCP to Windows `localhost:4717` from the Grok Bot box **failed**.
- Threaded context: **GREEN** ola-brain `side-chat send grok --label synapse-proof`. **GREEN** `Invoke-AgentChannel.ps1 context` (packed pointers). **RED** CLI side-chat send skips IDE hydration pointer (cold message). **RED** Codex JSON has no `session_id` so next turn is `resume --last` (hostile). **RED** dry-run printed instance id without `register_agent`. **Corrected 2026-09-01 (`b29c79b`):** `src/convoy/context.py` ships (`pack` / `stdin_for`, pointers only) and is imported by `synapse.py` and `mcp_http.py`; `registry.parse_session_id` reads JSON or an ola-brain `instance_id:` reply and has no UUID regex. The `ola_runner` line is history: that path is retired.
- Feature branch understanding: **GREEN code + unit + live artifact (corrected 2026-09-01, `b29c79b`).** `gitstate.git_state()` is merged into every synapse row by `synapse.send_one`; rows carry `git_branch` / `git_sha` / `pr_number` (e.g. `pr_number: 167` on `2026-08-31T11:58:40.211558Z`). Unit: `phase3_branch_test.py`.
- Worktree understanding: **GREEN code + unit (corrected 2026-09-01, `b29c79b`).** The worktree is stamped on every synapse row and passed as `cwd` into the runner. Unit: `phase4_worktree_test.py`. Live **native** dual-worktree hop stays `null`.
- Usage remaining: **GREEN** probes as logged below. **GREEN** roster `usageRemaining` JSON `null` (never guesses). Live Claude 100% and Codex out of credits blocked the dual hop. Grok / cursor-agent / agy / Gemini probes do not expose remaining quota.
- Usage probes (same day): `claude -p /usage` JSON, 5-hour session 100% used, reset 11:30 AM America/New_York, week 69%, Fable week 70%. `codex login status` logged in ChatGPT; `codex doctor` silent on quota; `codex exec /status` stdin closed ⇒ `Your workspace is out of credits.` Hop without probe hung. grok has no `/usage` (models/doctor/login only); probe aborted. `cursor-agent status` logged in `<account redacted>`, no remaining quota in status/about. `agy.exe` present with `-p`, not on ola-brain agents list. Gemini auth unknown.

---

## Honesty bar

Claims in this file must be true of **this tree** or of a named demo run with a timestamp. If a function is not in `src/convoy/`, it is not GREEN for this tree.

This tree at `b29c79b` — the landed public checkout of `Deploy-Forward/convoy` (merge of PR #24), inventory audited 2026-09-01: 17 modules under `src/convoy/`, 22 test modules under `test/demo/`, **184 tests passing** (`PYTHONPATH=src python test/run.py`). No `.ps1` file exists anywhere in the repo.

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
| `src/convoy/identity.py` | Installs the `neuron-identity` skill into a seat worktree so a launched model knows it is a neuron on a `cvy_id`. Never writes user-global `~/.grok` / `~/.claude` skills. |
| `src/convoy/harness_skills/neuron-identity/` | Packaged mirror of the skill text `identity.py` installs; canonical copy is top-level `skills/neuron-identity/` (byte-equality test enforces the pair). |
| `src/convoy/install.py` | Opt-in vendor install. Refuses unknown or wrapped harnesses and non-vendor hosts. Dry by default. |
| `src/convoy/layer.py` | `hook()`, `feed_since()`, `conductor_stamp()`, `utc_now()`, `feed_path()`, `SCHEMA_VERSION = 2`. The module writes the feed; branch / worktree / usage reach a row as `extra` from the caller, not from here. Feed contract v2.1 adds `neuron_note` plus an **attributed** `from` and an addressee `to` — see that section, which is the source of truth for it (attributed, not authenticated: the bus records a claimed `instance_id`). |
| `src/convoy/mcp_http.py` | JSON-RPC POST `/mcp`. Tool availability is always discovered from live `tools/list` at runtime (never copied from docs). Live `send` routes to `native_runner` with `allow_interactive_resume=False`. Attach/read tools may be PARTIAL GREEN when bound; native `send` stays RED until a live vendor execution is proven on the public URL. |
| `src/convoy/onboard.py` | Declared-harness onboarding: refuse wrappers, probe only named harnesses, optional thread bind, install hints, first-run PATH ungate. |
| `src/convoy/registry.py` | Instance registry: `register`, `lookup`, `parse_session_id`, `parse_agents_jsonl`, `live_on_branch`. No printed `session_id` without a row. |
| `src/convoy/synapse.py` | `fake_runner` (default), `native_runner` (`--live`: vendor binary on PATH, wrapper names refused, `cwd=worktree`), `send_one` / `send_many`. `ola_runner` is the **retired** ola-brain path — no longer reachable from the CLI or MCP; live mode is native on both. |
| `src/convoy/usage.py` | `probe()`, `normalize_usage_remaining()`, `surface()`. Unknown remaining is JSON `null`; never invent `0`; grok remaining is always `null`. |
| `test/run.py` + `test/demo/` | 22 test modules, 184 tests, all passing at `b29c79b` (2026-09-01). |
| `pyproject.toml` | `convoy` 0.1.0, packages under `src`, requires-python >= 3.11. |

We do not:

- Wrap Grok as `claude-grok-4-6` (or any Anthropic-shaped alias) behind Claude Code / UltraCode-Shim.
- Proxy `cli-chat-proxy.grok.com` / `api.x.ai` / Codex OAuth / cursor-agent HTTP so another product can wear our meter.
- Merge native sessions. A synapse execs the harness CLI the human already signed into. The other CLI keeps its own `session_id` and its own meter.
- Pretend a LAN stdio MCP to Windows `localhost:4717` is a Grok Bot MCP.
- Invent usage numbers, branch names, session ids, or MCP attach.
- Claim full HTTP MCP GREEN on unit tests alone. Live `send` routes to `native_runner` in code (`acba4e3`); GREEN needs a timestamped live vendor execution on the public URL, not a passing suite.
- Land this MCP in `Deploy-Forward/platform`.

If a PR starts looking like UltraCode-Shim (OnlyTerp, https://github.com/OnlyTerp/UltraCode-Shim — local proxy, Claude Code stays the shell, `/model` ids must start with `claude` or `anthropic`, Grok becomes a backend, `grok_build` hits `cli-chat-proxy.grok.com`), it does not land in `deploy-forward/convoy`.

Bring your own harness. Do not bring your own API key into someone else's harness.

Unknown is `null`. Limited is refuse. Dry-run is not live. Feed is the layer, not vendor `--resume`. The thread stays skinny.

## Phase 6 Parallel native send

Fire more than one synapse at once. Each keeps its own `session_id`. Sequential `@mention` is not this step.

GREEN: `test/demo/parallel_agents_test.py` fake runner. Aether `send-dry` wrote `<dry-grok-session>` and `<dry-claude-session>` plus two hook rows.

RED live: grok+agy 10:51 ET started together (pids 79160, 94228) but grok argv split and agy never saw the ping.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread.

