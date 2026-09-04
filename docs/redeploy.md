# Redeploy runbook: `https://convoy.bot/mcp`

Operator steps only. This file does **not** record a live origin restart.
A 2026-09-04 probe from a Linux cloud agent is at the bottom; treat that
block as a dated snapshot, not a frozen tool menu.

## What is actually in front of `/mcp`

Three layers. Only the Python origin's `tools/list` is the catalog.

```text
client
  -> https://convoy.bot/mcp
  -> Cloudflare Worker `convoy-bot`  (route: convoy.bot/*)
  -> Cloudflare Tunnel `convoy-bot`  (id dc70d65f-b7a8-45d6-9eb9-5c676e8c894c)
  -> Windows origin 38.66.81.135 cloudflared 2026.8.2 (windows_amd64)
  -> http://127.0.0.1:8788   (Python `convoy mcp`)
```

### Tree vs live (do not confuse them)

| Surface | What the tree says | What was live 2026-09-04 |
|---|---|---|
| `wrangler.jsonc` `vars.MCP_ORIGIN` | placeholder `https://mcp-origin.example` | **not** what the Worker serves |
| Worker binding `MCP_ORIGIN` | (set at deploy) | plain_text `https://convoy.bot` |
| Deployed Worker script | repo `workers-site.mjs` proxies to `env.MCP_ORIGIN` | stub: `/mcp` is `return fetch(request)` (pass-through to the zone origin / tunnel). **It does not read `MCP_ORIGIN`.** |
| Python origin | `convoy mcp --port 8788` | tunnel ingress `http://127.0.0.1:8788` on that Windows host |
| Worker secrets | none required for MCP | `GET .../secrets` was `[]` |

So: **checking out this branch and `wrangler deploy` is not how you pick up new tools**, and deploying the placeholder `MCP_ORIGIN` over production would be wrong. New verbs appear when the **Windows Python process** on `127.0.0.1:8788` is restarted on this tip, with the write gate left **closed** for public.

README/`SECURITY_GATES.md` remain the product contract: public process hides `_WRITE_TOOLS`; gated/loopback sets `CONVOY_MCP_WRITE_TOOLS=1`.

## Derived catalogs (this tip — do not freeze)

From `src/convoy/mcp_http.py` (`TOOLS` / `_WRITE_TOOLS`), printed by
`PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --catalog`:

- **Public** (gate closed): **20** read tools. Writes hidden, not listed-and-refusing.
- **Gated** (`CONVOY_MCP_WRITE_TOOLS=1`): **33** tools (20 reads + 13 writes).
- **Gate 0 GREEN**: the 11 verbs in `wizard_preflight.REQUIRED_WIZARD_VERBS` are all listed. That is independent of the total. A remembered “25” is not the contract on this tip.

Public Gate 0 stays **RED by design** (write-gated wizard verbs `repos`, `clone`, `onboard`, `crew`, `consent`, `await_seated` stay hidden). That is success for `https://convoy.bot/mcp`.

## Public origin restart (writes hidden)

Do this **on the Windows origin that already runs cloudflared**, not on a Linux cloud agent (no `wt`, no SSH to that box from here).

1. On `38.66.81.135` (the tunnel connector host), open a shell that can see the Convoy checkout used by the listening `8788` process.
2. `git fetch origin` and check out the merge tip you intend to serve (`main` after merge, or `feat/convoy-wizard-vision` to stage this PR).
3. Install that checkout: `python -m pip install .` (or the same interpreter the current `8788` process already uses).
4. **Do not** set `CONVOY_MCP_WRITE_TOOLS` on this public process. Unset it:
   `Remove-Item Env:CONVOY_MCP_WRITE_TOOLS -ErrorAction SilentlyContinue`
5. Restart **only** the Python origin, same port the tunnel already points at:
   `convoy mcp --root <the-bound-public-thread-root> --host 127.0.0.1 --port 8788`
6. Leave cloudflared running. Do not `wrangler deploy` from the tree placeholder.

### Public verify (GREEN / RED)

```bash
PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --url https://convoy.bot/mcp --expect public
```

| | GREEN | RED |
|---|---|---|
| `tools/list` count / names | exactly the 20 packaged **public** names; **no** `_WRITE_TOOLS` | still 13 (lag), or any write verb listed, or a packaged read missing |
| Gate 0 / `convoy preflight` | `status: RED`, missing writes classified `write-gated`, `next: enable-write-tools-on-deploy` | `status: GREEN` (writes leaked) **or** missing **reads** classified `redeploy` (`card`, `neurons`, `graph`, `inbox`, …) |
| `onboard` | **absent** from the public list (it is a write) | listed (pre-PR-52 public catalog listed it) |

Worker redeploy is **not** required for this step unless you are changing `workers-site.mjs` or the tunnel. The live stub already pass-throughs `/mcp` to `127.0.0.1:8788`.

## Gated loopback (Gate 0 GREEN)

A **second** process, bound to loopback, never the public URL:

```bash
# Windows origin or any checkout; NOT convoy.bot
$env:CONVOY_MCP_WRITE_TOOLS = "1"
convoy mcp --root <conductor-thread-root> --host 127.0.0.1 --port 8789
PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --url http://127.0.0.1:8789/mcp --expect gated
```

| | GREEN | RED |
|---|---|---|
| `tools/list` | all 33 packaged names | any packaged name missing |
| Gate 0 | `preflight.status: GREEN`, `missing: []` | any `REQUIRED_WIZARD_VERBS` gap |
| Writes | `crew` / `onboard` / `repos` listed | still hidden |

Do **not** point the `convoy-bot` tunnel or Worker at this gated process.

This checkout can also score loopback without a long-lived server:

```bash
PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --loopback --expect public
PYTHONPATH=src python3 scripts/mcp_redeploy_verify.py --loopback --expect gated
```

## Cloudflare Worker (only if the proxy itself changed)

Authenticated `wrangler` was **not** available on the 2026-09-04 cloud agent
(`npx wrangler whoami` → not authenticated; no `CLOUDFLARE_API_TOKEN` in env).
The Cloudflare API **was** reachable via the account MCP (`worker:edit` on
account `727ee90709b7359ffc27413050eace8b`).

If you must ship a new Worker:

1. Confirm the dashboard/API `MCP_ORIGIN` binding. Live value was `https://convoy.bot`. The tree placeholder is `https://mcp-origin.example`.
2. Do **not** deploy `workers-site.mjs` with `MCP_ORIGIN=https://convoy.bot` — that constructs a same-host fetch and loops. The live stub’s `fetch(request)` is pass-through to the tunnel. Keep that pass-through unless the origin URL is a **different** host.
3. `wrangler deploy --keep-vars` so a local placeholder does not clobber the live binding.
4. Route `convoy.bot/*` → `convoy-bot` already exists (`15a5de52dd604e3f90ac0a147f25c867`).

## Exact blocker for a remote origin restart (2026-09-04)

This agent **could** read Worker settings, routes, DNS, and tunnel ingress.
It **could not** restart `127.0.0.1:8788` on the Windows origin.

Missing, named:

- **SSH / WinRM / RDP to `38.66.81.135`**: TCP/22 timed out; no `~/.ssh` keys on the agent; TCP/8788 timed out (localhost-only behind cloudflared); TCP/3389 and TCP/5985 timed out.
- **`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in the process env**, or `wrangler login`: `npx wrangler whoami` → not authenticated. (API via Cloudflare MCP is not wrangler.)
- **Any shell on the `windows_amd64` cloudflared host** that owns pid listening on `127.0.0.1:8788`.

Do not point the production tunnel at an ephemeral cloud-agent VM. That would change `tools/list` until the agent dies, then take `convoy.bot/mcp` down.

## Probe snapshot (not a menu)

UTC 2026-09-04, this agent, `POST https://convoy.bot/mcp` `tools/list`:

- HTTP 200, `serverInfo.name=convoy`, `version=0.1.0`
- **13** tools: `roster`, `glance`, `onboard`, `terminals`, `context`, `send`, `feed`, `bring_up`, `open`, `hide`, `minimize`, `background`, `install`
- Matches `test/demo/plugin_wizard_preflight_test.py` `LIVE_2026_09_04`
- After this docs pack: **same 13** — origin was not restarted

Score that snapshot with `--expect live-lag`. After a real public restart, `--expect public` must go GREEN (20 reads, writes hidden).
