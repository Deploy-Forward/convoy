# Convoy MCP security gates

This document records the security findings raised on draft PR #50 and the gate
contract implemented to fail closed for any caller without a bearer.

## Findings fixed

1. **Ungated spawn path via `launch`**
   - Before 1.3.2, on a process with the old write flag unset, `launch` accepted
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

`_WRITE_TOOLS = {"send", "stamp", "note", "seat", "join", "launch", "onboard", "clone", "mint", "repos", "crew", "seated", "consent", "await_seated", "focus", "nudge"}`

- No bearer minted on this machine (gate closed): these verbs are hidden from
  `tools/list`.
- Once any bearer is minted on this machine: these verbs are listed for every
  caller, with or without a bearer. Only a request carrying a checked conductor
  bearer (`convoy conductor mint`, sent as `Authorization: Bearer`) can call
  them; any other caller is refused at `tools/call`. The process-wide
  `CONVOY_MCP_WRITE_TOOLS` switch was removed in 1.3.2; nothing else opens
  the gate.
- `onboard`, `clone`, `mint` joined 2026-09-04 (repository step): onboard
  binds the thread (writes `.convoy/`) and, given a URL, spawns `git clone`;
  clone and mint spawn git outright. Before this, onboard was listed and
  mutating for a caller without a bearer.
- `repos` joined the same day after review: `gh repo list` runs as whoever is
  logged in on the MCP host, so an anonymous `repos` could only disclose the
  operator's inventory (private names included) and spend their API quota.
  It reads, but what it reads is the conductor's.
- `crew`, `seated`, `consent`, `await_seated` joined 2026-09-04: crew
  mints worktrees, joins N chairs and with `launch=true` spawns the window;
  seated stamps a chair's proof of life; consent mints a one-time grant.
  await_seated only reads, but it holds the request thread up to its timeout
  (capped at 600 s), which a caller without a bearer must not be offered.

### Anonymous list behavior (truthful Gate 0 signal)

- The write verbs (`seat`, `join`, `launch`, `onboard`, `clone`, `mint`,
  `repos`, `crew`, `seated`, `consent`, `await_seated`, `focus`, `nudge`, and
  the rest of `_WRITE_TOOLS`) are hidden from `tools/list` only while no bearer is minted on this machine.
  That is the state a fresh install is in, and there Gate 0 truthfully reads
  RED. Once a bearer exists they are listed for every caller and refused at `tools/call` without the bearer, so a listed write verb is a promise only
  to the caller holding the bearer.
- `tools/list` for a caller without a bearer **must keep** read-only verbs listed (including `inbox`
  read mode), so the wire truthfully reflects what is usable without
  mutation. `repos` lists names and URLs from `gh repo list`; a missing gh is
  an install hint, never a remembered list.

### Handler-level refusal behavior

When the write gate is closed:

- `seat` / `join` refuse before any mutation.
- `launch` refuses before spawn and returns `spawned: false`.
- `focus` refuses before any pane-host action (`focused: false`).
- `clone` / `mint` refuse before git runs (`cloned: false`, `worktrees: []`).
- `repos` refuses before gh runs (`repos: null`, `count: null`, never `[]`/`0`).
- `clone` refuses a URL starting with `-` and passes `--` before the URL, so
  `--upload-pack=...` can never reach git as an option.
- `inbox` with `drain=true` refuses before drain.
- `threads` with `prune=true` refuses before rewriting the machine index (`dropped: []`, counts JSON null). Dry `threads` list stays open to a caller without a bearer.
- `crew` refuses before validation, mint or join (`seats: []`, `launched: false`);
  `seated` refuses before stamping; `consent` before granting; `await_seated`
  before reading (`chairs: []`); `nudge` refuses before SendInput/send-keys/queue
  (`delivery: null`, `delivered: false`).
- Refusal text names `convoy conductor mint` and does not claim action.

### Loopback only (1.3.2)

- The HTTP server binds only a loopback address: `convoy mcp --host` accepts
  `127.0.0.1`, `localhost` or `::1` and refuses anything else, such as
  `0.0.0.0`.
- It serves a request only when the connecting peer is this machine's
  loopback, its `Host` is `127.0.0.1`, `localhost` or `[::1]` on the port it
  listens on, and any `Origin` is an `http://` loopback origin on that same
  port. A non-loopback peer is a 403 on every method, whatever `Host` it sends,
  so a forged loopback `Host` from another machine opens nothing. Anything else
  is a 403 before the bearer is checked or the body is parsed. This is the
  DNS-rebinding defense the MCP Streamable HTTP transport requires.
- The desktop widget's local server applies the same peer, `Host` and `Origin`
  checks on every GET and POST, and binds loopback only.
- No response carries CORS headers. Every response from the servers' request
  handlers carries `X-Content-Type-Options: nosniff` (a malformed request the
  standard library rejects before any handler runs gets its bare 400 or 431).
- A method with no handler (PUT, DELETE, PATCH, ...) goes through the same
  gate: a 403 off loopback, a 405 on it, never a 501 before the gate.
- On Windows both servers bind with `SO_EXCLUSIVEADDRUSE`, so no other local
  process can bind the same port and take its connections.
- A GET through a proxy header is a 404.
- Convoy ships no tunnel and no hosted endpoint. Remote access to your loopback
  MCP is not a Convoy feature; if you build it, put it behind your own access
  control.

### Inbox safety contract

- `inbox` requires `seat` and never guesses from cwd.
- `inbox` read mode needs no bearer, but pending rows redact `token`.
- `inbox` drain mode is gated (`drain=true` requires write gate).

### No tokens on the wire

- `seat` schema does not accept a caller-supplied `resume`.
- Read paths do not expose inbox tokens: `feed` rows without a bearer drop the `token` key
  (join / swap / seated), the same as the anonymous `inbox` read.
- Without a bearer, `glance` seats and `terminals` / `bring_up` / `open` / `hide` windows carry
  `resume` as `{available, for}`, never the vendor id; `bring_up` / `open` windows and
  the `resume` dry read carry `argv` in the same shape (the id and the boot-prompt
  token ride in it). Behind the gate the cards are whole (`mcp_http._redact_public`).
- `await_seated` compares each `seated` row's token to the join/swap mint on disk
  and answers `connected | pending | stale`; the card never carries a token. The
  gated `seated` card answers with the row's timestamp, not the token it echoed.
- Tokens remain local to chair state/disk and trusted local flows.

