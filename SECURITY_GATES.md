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

`_WRITE_TOOLS = {"stamp", "note", "seat", "join", "launch"}`

- Public process (gate closed): these verbs are hidden from `tools/list`.
- Gated/loopback process (`CONVOY_MCP_WRITE_TOOLS=1`): verbs are listed and
  callable.

### Public list behavior (truthful Gate 0 signal)

- Public `tools/list` **must hide**: `seat`, `join`, `launch`.
- Public `tools/list` **must keep** read-only verbs listed (including `inbox`
  read mode), so the wire truthfully reflects what is usable without mutation.

### Handler-level refusal behavior

When the write gate is closed:

- `seat` / `join` refuse before any mutation.
- `launch` refuses before spawn and returns `spawned: false`.
- `inbox` with `drain=true` refuses before drain.
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
- Tokens remain local to chair state/disk and trusted local flows.

