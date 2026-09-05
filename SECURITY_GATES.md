# Convoy MCP security gates

This document records the security findings raised on draft PR #50 and the gate
contract implemented to fail closed on public MCP deploys.

## Findings fixed

1. **Ungated spawn path via `launch`**
   - On a public process (`CONVOY_MCP_WRITE_TOOLS` unset), `launch` accepted
     `dry_run=false` and could reach `launch_seat` / `active_pane_runner`.
   - Impact: an internet caller could trigger host-side process spawning.

2. **Ungated chair mutation via `seat` / `join`**
   - `seat` and `join` were callable publicly.
   - `seat` accepted caller-supplied `resume`, which allowed planting a vendor
     token on another chair.
   - Impact: strangers could mint/modify chairs and influence resume identity.

3. **`inbox` seat guess + token leak**
   - `inbox` could infer seat from server cwd when `seat` was omitted.
   - Public read returned pending rows including `token`.
   - Impact: callers could misroute reads and forge receiver ACKs.

## Gate contract

### Write-gated verbs

`_WRITE_TOOLS = {"stamp", "note", "seat", "join", "launch", "onboard", "clone", "mint", "repos", "crew", "seated", "consent", "await_seated"}`

- Public process (gate closed): these verbs are hidden from `tools/list`.
- Gated/loopback process (`CONVOY_MCP_WRITE_TOOLS=1`): verbs are listed and
  callable.
- `onboard`, `clone`, `mint` joined 2026-09-04 (repository step): onboard
  binds the thread (writes `.convoy/`) and, given a URL, spawns `git clone`;
  clone and mint spawn git outright. Before this, onboard was listed and
  mutating on the public wire.
- `repos` joined the same day after review: `gh repo list` runs as whoever is
  logged in on the MCP host, so a public `repos` could only disclose the
  operator's inventory (private names included) and spend their API quota.
  It reads, but what it reads is the conductor's.
- `crew`, `seated`, `consent`, `await_seated` joined 2026-09-04 (item E): crew
  mints worktrees, joins N chairs and with `launch=true` spawns the window;
  seated stamps a chair's proof of life; consent mints a one-time grant.
  await_seated only reads, but it holds the request thread up to its timeout
  (capped at 600 s), which a public endpoint must not offer.

### Public list behavior (truthful Gate 0 signal)

- Public `tools/list` **must hide**: `seat`, `join`, `launch`, `onboard`,
  `clone`, `mint`, `repos`, `crew`, `seated`, `consent`, `await_seated`.
- Public `tools/list` **must keep** read-only verbs listed (including `inbox`
  read mode), so the wire truthfully reflects what is usable without
  mutation. `repos` lists names and URLs from `gh repo list`; a missing gh is
  an install hint, never a remembered list.

### Handler-level refusal behavior

When the write gate is closed:

- `seat` / `join` refuse before any mutation.
- `launch` refuses before spawn and returns `spawned: false`.
- `clone` / `mint` refuse before git runs (`cloned: false`, `worktrees: []`).
- `repos` refuses before gh runs (`repos: null`, `count: null`, never `[]`/`0`).
- `clone` refuses a URL starting with `-` and passes `--` before the URL, so
  `--upload-pack=...` can never reach git as an option.
- `inbox` with `drain=true` refuses before drain.
- `threads` with `prune=true` refuses before rewriting the machine index (`dropped: []`, counts JSON null). Dry `threads` list stays public.
- `crew` refuses before validation, mint or join (`seats: []`, `launched: false`);
  `seated` refuses before stamping; `consent` before granting; `await_seated`
  before reading (`chairs: []`).
- Refusal text names `CONVOY_MCP_WRITE_TOOLS` and does not claim action.

### Inbox safety contract

- `inbox` requires `seat` and never guesses from cwd.
- `inbox` read mode is public, but pending rows redact `token`.
- `inbox` drain mode is gated (`drain=true` requires write gate).

### No tokens on the wire

- `seat` schema does not accept public `resume`.
- Read paths do not expose inbox tokens: public `feed` rows drop the `token` key
  (join / swap / seated), the same as the public `inbox` read.
- Public `glance` seats and `terminals` / `bring_up` / `open` / `hide` windows carry
  `resume` as `{available, for}`, never the vendor id; `bring_up` / `open` windows and
  the `resume` dry read carry `argv` in the same shape (the id and the boot-prompt
  token ride in it). Behind the gate the cards are whole (`mcp_http._redact_public`).
- `await_seated` compares each `seated` row's token to the join/swap mint on disk
  and answers `connected | pending | stale`; the card never carries a token. The
  gated `seated` card answers with the row's timestamp, not the token it echoed.
- Tokens remain local to chair state/disk and trusted local flows.

