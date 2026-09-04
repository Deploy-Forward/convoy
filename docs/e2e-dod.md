# E2E definition of done — plugin-finalize (g2)

Dated snapshot: **2026-09-04T16:09Z**. Neuron: grok-2. Evidence baseline:
`b4b186d925bdb24e414cedd8abfa208d342d98b9`
(`origin/feat/convoy-wizard-vision`, PR
[#52](https://github.com/Deploy-Forward/convoy/pull/52)).

This file is evidence, not a frozen tool menu. Live names below were read from
`https://convoy.bot/mcp` in this run. Do not copy them forward as a catalog.
This document landed later at `7cb25c28761f4bcf59ebf9ac1ba53257c355ca8e`;
neither SHA is the moving PR tip. Record and retest the final reviewed SHA
before pinning or deploying.

## Verdict board

| Gate | Color | Evidence |
|---|---|---|
| Pack files vs xAI SoT (Exa layout) | **GREEN** | `.grok-plugin/plugin.json` + `.mcp.json` (`type: http`, `url: https://convoy.bot/mcp`) at evidence baseline; pack tests pass |
| Wizard + Gate 0 + security on loopback | **GREEN** | `test/run.py` suite at evidence baseline (see Tests) |
| Public `https://convoy.bot/mcp` Gate 0 | **RED** | live `tools/list` returned **13** names; `python -m convoy preflight` exit 1 |
| Python origin redeploy | **RED** | no Windows origin host access or supervisor path (see Blockers) |
| Worker deploy | **NOT RUN** | live route already matches `MCP_ORIGIN=https://convoy.bot`; Worker deploy is conditional on Worker-input changes |
| Public security parity | **RED** | stale live origin still lists `onboard`, which current `_WRITE_TOOLS` must hide publicly |
| xai-org/plugin-marketplace listing | **RED** (PR open, not merged) | [#560](https://github.com/xai-org/plugin-marketplace/pull/560) pins `b4030e4bac62807115fac1d787e33543d7c1218c`; `mergeable_state=blocked` (owners/CI) |

Public Gate 0 stays RED until a *fresh* `tools/list` against
`https://convoy.bot/mcp` lists every required wizard verb. A Worker deploy
cannot make that true. A public Python restart without
`CONVOY_MCP_WRITE_TOOLS=1` still leaves Gate 0 RED by design (write verbs
hidden).

## Live public MCP (this run)

`initialize` HTTP 200, `cf-ray` `a35e3c93bf41ca84-PDX`, 2026-09-04T16:05:36Z:

```json
{"protocolVersion":"2025-03-26","serverInfo":{"name":"convoy","version":"0.1.0"}}
```

`tools/list` HTTP 200, 13 names, in the order returned:

1. `roster`
2. `glance`
3. `onboard`
4. `terminals`
5. `context`
6. `send`
7. `feed`
8. `bring_up`
9. `open`
10. `hide`
11. `minimize`
12. `background`
13. `install`

GET `/mcp` is 405 (`allow: POST, OPTIONS`). Site GET `/` is 200.

`python -m convoy preflight` against that list (exit 1):

```text
status: RED
url: https://convoy.bot/mcp
required: card, repos, clone, onboard, crew, consent, await_seated, neurons, graph, send, inbox
listed: background, bring_up, context, feed, glance, hide, install, minimize, onboard, open, roster, send, terminals
missing: card, repos, clone, crew, consent, await_seated, neurons, graph, inbox
remedy:
  card, neurons, graph, inbox -> redeploy
  repos, clone, crew, consent, await_seated -> write-gated
next: enable-write-tools-on-deploy
mutation_attempted: false
```

`onboard` and `send` are the only required wizard verbs present live.
`onboard` is still listed on the public origin. On this branch it is in
`_WRITE_TOOLS` and a public process **must hide it**. That mismatch is
proof the Python origin has not restarted onto this tip; it is not a
promise that public `onboard` will remain after redeploy.

Do not treat the 13-name list as usage. The wizard must fail closed on it.

## Redeploy blockers (exact)

Attempted in this worktree. None of these were present:

1. **No Cloudflare API token / Wrangler profile.**
   - `env` had no `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
     `WRANGLER_*`, or `MCP_ORIGIN`.
   - `npx wrangler@3 whoami` (Node v20.19.2):
     `You are not authenticated. Please run wrangler login.`
   - `npx wrangler@latest whoami` refused to run: Wrangler 4.129.0 requires
     Node `>=22.0.0`; this VM is `v20.19.2`.
   - `~/.config/.wrangler` has logs + `metrics.json` only; no OAuth config.
2. **`MCP_ORIGIN` is not a credential.** `wrangler.jsonc` sets
   `MCP_ORIGIN=https://convoy.bot` so the Worker Route proxies `/mcp` to the
   same hostname's proxied DNS (Cloudflare Tunnel → `127.0.0.1:8788`).
   Deploying the Worker does not update the Python process.
3. **No path to the Windows origin host.** No SSH config, no RDP, no
   checkout path, no Win32 service name, no supervisor command.
4. **Sandbox `cloudflare.json` is not convoy.bot.**
   `/home/box/sand-data/connector-secrets/.../cloudflare.json` is this VM's
   tunnel connector token (key `token` only). It was not used as a Wrangler
   API token and cannot restart the Python origin.

Operator unblock: supply (a) origin checkout path + supervisor restart on
the Windows connector, and/or (b) `CLOUDFLARE_API_TOKEN` + account for a
Worker-only change. Then follow `docs/deploy-convoy-bot-mcp.md`. Keep
`CONVOY_MCP_WRITE_TOOLS` unset on the internet-facing process.

## Tests (evidence baseline `b4b186d`)

Targeted Gate 0 / pack / security modules, 2026-09-04T16:07Z: **55 tests, OK**.

Full suite on this tip, 2026-09-04T16:10Z:

```text
python3 test/run.py
Ran 528 tests in 45.944s
OK (skipped=1)
```

The skipped test is `host_rendering_contract_test` (no live Grok Bot
`test/demo/fixtures/host_rendering.json`).

Loopback E2E (`wizard_e2e_gated_test`) is GREEN: the wizard walk is proven
over JSON-RPC on a gated local server, and the same walk is refused when
the write gate is closed. That is **not** public Gate 0 GREEN.

`host_rendering_contract_test` remains skipped until
`test/demo/fixtures/host_rendering.json` records a live Grok Bot run.

## Marketplace pin

Official SoT: https://github.com/xai-org/plugin-marketplace

- Catalog lives in `.grok-plugin/marketplace.json` on that repo (not convoy's
  `.cursor-plugin/marketplace.json`).
- Plugin root to pin: `plugin/convoy` at
  `b4030e4bac62807115fac1d787e33543d7c1218c`.
- Pack mirrors Exa: `.grok-plugin/plugin.json`, `.mcp.json` (`type: http`),
  `skills/{convoy,convoy-wizard}/SKILL.md`.
- `gh repo view xai-org/plugin-marketplace` → `viewerPermission: READ`.
  No `convoy` entry in the catalog (21 plugins). PR body:
  `docs/marketplace-pr.md`.

Re-pin after #52 merges onto `main` if that commit is not this SHA.

## Production redeploy DoD (public wizard Gate 0 remains RED)

1. Restart the Python origin on this SHA (or later #52 tip).
2. Confirm loopback `http://127.0.0.1:8788/mcp` `tools/list` matches the
   packaged registry (gated or public shape).
3. Repeat `initialize` + `tools/list` + `python -m convoy preflight` on
   `https://convoy.bot/mcp`.
4. Public expected: write verbs hidden; read verbs from this branch
   (`card`, `neurons`, `graph`, `inbox`, …) present. Preflight stays RED
   on public because `repos`/`clone`/`onboard`/`crew`/`consent`/`await_seated`
   are write-gated.
5. Wizard GREEN only on an authenticated/gated endpoint with
   `CONVOY_MCP_WRITE_TOOLS=1` whose live `tools/list` contains every
   `REQUIRED_WIZARD_VERBS` name.

After step 3, public Gate 0 is still expected RED: the capture proves the
origin update and public security parity, not wizard readiness. Wizard GREEN
requires an authenticated/gated endpoint whose fresh list contains every
`REQUIRED_WIZARD_VERBS` name.
