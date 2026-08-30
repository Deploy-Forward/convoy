# Convoy

Grok Bot is the conductor. Convoy is the source of truth for one thread: `convoy_id`, tied checkout, seats, and feed rows.  
Public MCP endpoint: **https://convoy.bot/mcp**

## Quick start (stranger-friendly)

1. Attach MCP: `https://convoy.bot/mcp`
2. Run **onboard** and name harnesses you already have:
   - MCP tool: `onboard`
   - CLI: `python -m convoy onboard --to grok --to claude`
   - User-facing chat command: `/onboard` or `/onboard -convoy` (same flow; Grok Bot may call MCP `onboard`)
3. Use:
   - `roster` for machine/PATH truth
   - `send` for headless hop cards
   - `feed` for layer events
   - `context` for pointer pack
   - `bring_up` / `open` for visible terminal resume

## Product contract

- **BYO harness, no wraps.** Convoy uses named harness CLIs as-is (`grok`, `claude`, `codex`, `cursor-agent`, `agy`).
- Convoy refuses wrapper paths and names such as `ola-brain`, `side-chat`, `UltraCode-Shim`, `gemini-cli`, and community `grok-cli`.
- Vendor login is human once-gate; Convoy does not log anyone in.
- `install` is opt-in and vendor-host-only.

## Truth in status

- This repo is the HTTP MCP + CLI product (`Deploy-Forward/convoy`), not `Deploy-Forward/platform`.
- Native live `send` is still **RED** while live routing remains `ola_runner`; do not claim native send GREEN yet.
- Deployed MCP snapshots may still expose the 7-tool core (`roster`, `send`, `feed`, `context`, `bring_up`, `open`, `terminals`) even though this tree also contains `install`, `hide`, and `onboard`.

## Linux test harness (no vendor login)

From repo root:

```bash
PYTHONPATH=src python test/run.py
```

or:

```bash
PYTHONPATH=src python -m unittest discover -s test/customer1 -p '*_test.py' -v
```

`test/fakes/` contains executable fake binaries used by tests. No vendor login required.

## Windows Terminal isolated bring-up (kept for ops)

Visible bring-up opens one isolated WT window per named thread, then splits panes:

```text
wt --window new
nt --title T0 -d DIR0 EXE0
; split-pane -V --title T1 -d DIR1 EXE1
; split-pane -H --title T2 -d DIR2 EXE2
```

Never use `wt -w 0`, never place `--` before the harness exe, and never treat Grok Bot as a window.
