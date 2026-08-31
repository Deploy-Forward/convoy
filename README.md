# Convoy

Grok Bot is the conductor (this chat). Convoy is the source of truth that any hop can rehydrate from.
Public MCP endpoint: **https://convoy.bot/mcp**

## Quick start (stranger-friendly)

1. Attach MCP: `https://convoy.bot/mcp`
2. Run onboard and name harnesses you already have:
   - MCP tool: `onboard`
   - CLI: `python -m convoy onboard --to grok --to claude`
   - Chat aliases: `/onboard` and `/onboard -convoy` (same intent; they map to MCP `onboard` only when live MCP lists that tool)
3. Use the core tools:
   - `roster` = machine/PATH truth
   - `send` = headless synapse (pointers in, compact card out)
   - `feed` = layer events since `ts`
   - `context` = packed pointers only
   - `bring_up` / `open` = visible resume; `hide` is the counterpart in this tree

## How it works

### Roles

- **Grok Bot** is the conductor.
- **Convoy** is the system of record for thread state, seats, and layer stamps.
- A **hop** is a BYO harness CLI (`grok`, `claude`, `codex`, `cursor-agent`, `agy`), not a new Grok Bot.

### Objects

- **Thread**: one Convoy thread per Grok Bot conductor. Visible. Hops on that thread share it.
- **`convoy_id` (`cvy_...`)**: durable id for that thread.
- **Tied checkout**: `worktree` / `branch` / `pr` fields are stamped on cards; same-branch overlap without a worktree is refused.
- **Layer**: `.convoy/feed.jsonl` with stamps (who hopped, when, pointers). Not vendor transcripts.
- **Synapse**: one hop, one harness CLI, one `session_id`, one meter, compact card back.
- **Hop talk**: `send` + `feed` on one `convoy_id`. Not Herdr PTY paste. Not a CNVS canvas.

### Flow a stranger actually runs

1. Attach `https://convoy.bot/mcp`.
2. Run onboard. The human names harnesses they already have.
   - Convoy reports PATH truth (`present`, `wired`, `path`).
   - Convoy does not invent a roster.
   - Missing named harnesses point to `install` (opt-in, vendor hosts only).
   - Vendor login is still a human once-gate.
3. Use `roster` for machine/PATH truth after onboarding.
4. Use `send` for headless synapses (default does not pop a TUI).
5. Use `feed` for layer history since `ts`.
6. Use `context` for pointer packs only.
7. Use `bring_up` / `open` for visible sessions (`--resume` in isolated n-pane layout); use `hide` to minimize/hide those windows.

## Product contract

- **BYO harness, no wraps.**
- Convoy refuses wrapper names/paths such as `ola-brain`, `side-chat`, `UltraCode-Shim`, `gemini-cli`, and community `grok-cli`.
- Convoy does not log users in to vendor CLIs.
- `install` is opt-in and vendor-host-only.

## Truth / proof status

### Proven on 2026-08-30 (Grok Bot Linux box, this branch)

- `PYTHONPATH=src python3 test/run.py` passed: **117 tests green**.
- CLI emulator run (`python -m convoy onboard --to grok --to claude --to codex`) on temporary roots:
  - named-only output (no unnamed harnesses silently added),
  - stripped PATH produced all three missing plus install hints,
  - PATH with `~/.local/bin` and `~/.grok/bin` produced `present:true` for all three named harnesses,
  - grok `usage_remaining` was JSON `null`,
  - codex surfaced `limited:true` in the emulator status probe path.

### Not proven (do not claim GREEN)

- Live `https://convoy.bot/mcp` tool listing with `onboard` enabled in the deployed process. The known live snapshot may still be the 7-tool core (`roster`, `send`, `feed`, `context`, `bring_up`, `open`, `terminals`) without `onboard` / `install` / `hide`.
- `/onboard` in a connected Grok Bot chat until the live MCP process actually serves `onboard`.
- Native live send replacement (still routed by `ola_runner`, so native send remains **RED**).
- Hop-to-hop talk proven on a stranger-attachable live thread.

## Linux test harness (no vendor login)

From repo root:

```bash
PYTHONPATH=src python3 test/run.py
```

Equivalent:

```bash
PYTHONPATH=src python3 -m unittest discover -s test/customer1 -p '*_test.py' -v
```

`test/fakes/` contains executable fake binaries used by tests. No vendor login required.

## Windows Terminal isolated bring-up (ops notes)

Visible bring-up opens one isolated WT window per named thread, then splits panes:

```text
wt --window new
nt --title T0 -d DIR0 EXE0
; split-pane -V --title T1 -d DIR1 EXE1
; split-pane -H --title T2 -d DIR2 EXE2
```

Never `wt -w 0` (injects into the focused session). Never `--` before the harness exe (pops WT Help). Grok Bot is not a window.

Claude first-run skip is `skipDangerousModePermissionPrompt` in `~/.claude/settings.json`. Project `.claude/settings.json` is ignored by Anthropic for that dialog.

## Install

```
pip install -e .
PYTHONPATH=src python -m unittest discover -s test/customer1 -p '*_test.py' -v
```

unittest's default pattern `test*.py` misses `phase7_*_test.py` (and the rest of `*_test.py`). Equivalent helpers from repo root: `PYTHONPATH=src python -m test` or `PYTHONPATH=src python test/run.py`.

```
python -m convoy --root . bring-up --dry-run
```

Live TUI spawn is Windows Terminal (Windows-only). Dry-run ungates first-run and does not Popen `wt`. Unit tests use fake absolute binaries under `test/fakes/`; Convoy never logs into a vendor on CI/Linux.

## Glance (OSS data contract)

`glance` is a read-only view over Convoy SoT (`.convoy` seats + feed) and live harness probes.
It does **not** invent meters, dollars, reset dates, or split shared account quotas.

CLI:

```bash
python -m convoy glance --json
python -m convoy glance --thread convoy --json
python -m convoy glance --convoy-id cvy_... --json
python -m convoy glance --tray
```

- **Overall**: keyed by harness (`grok`, `claude`, `codex`, `cursor-agent`, `agy`) with `present`, `badge` (`Live`/`missing`/`limited`), and `usage_remaining` (`number|object|null` only).
- **By thread**: one `convoy_id` / thread card with seats (`to`, optional `model`, `session_id`, `worktree`, `branch`, `pr`) plus `last_synapse` when present.
- Missing model is omitted (never `"unknown"`).
- Tray/indicator is optional; headless tests validate JSON contract only.

Scope lock:

- **Public repo (`deploy-forward/convoy`)**: glance JSON contract (CLI + MCP `glance`) and small optional tray renderer.
- **Closed platform (`Deploy-Forward/platform`)**: polished native product, vendor billing scrapers, and any leftover-$ UX.
