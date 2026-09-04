# Deploying the convoy.bot MCP origin

`convoy.bot` has two independently deployed layers. Updating the Cloudflare
Worker does **not** update the Python MCP server.

## Observed production topology

Read from Cloudflare on 2026-09-04:

```text
convoy.bot/* Worker Route
  -> Worker convoy-bot
  -> MCP_ORIGIN=https://convoy.bot
  -> proxied convoy.bot DNS record
  -> Cloudflare Tunnel convoy-bot
  -> two windows_amd64 connectors
  -> http://127.0.0.1:8788
  -> Python convoy MCP process
```

The same hostname is intentional. For a Worker **Route** in front of an
application server, `fetch()` continues to the application origin configured
by proxied DNS. Do not convert this to a Worker Custom Domain: the Worker is a
proxy, not the MCP origin.

The repository records the production variable and route in `wrangler.jsonc`.
The tunnel UUID, connector credentials, origin checkout path, thread root and
service-manager configuration do not belong in Git.

## Current restart blocker

At the time this runbook was written, the tunnel was healthy and its connectors
were serving `127.0.0.1:8788`, but this repository and the Cursor Linux cloud VM
had none of the following:

- credentials or an SSH/RDP/management path to either Windows connector;
- the Python origin's checkout path and bound thread root;
- a Windows service, scheduled-task or other supervisor definition for the
  MCP process;
- an authenticated Wrangler profile or Cloudflare token in the shell.

Cloudflare can identify the connector and ingress, but it cannot update files
or restart the Python process on that Windows host. Do not deploy the Worker as
a substitute. The origin owner must supply the host access and supervisor name,
then follow the steps below.

## Python origin restart

First capture the public response so the before/after evidence is comparable:

```bash
curl -fsS https://convoy.bot/mcp \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

On the Windows connector host, identify the listener without opening a desktop
pane:

```powershell
$Listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8788 -State Listen |
  Select-Object -First 1
$Process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Listener.OwningProcess)"
$Service = Get-CimInstance Win32_Service |
  Where-Object ProcessId -eq $Listener.OwningProcess
$Process | Select-Object ProcessId, ExecutablePath, CommandLine
$Service | Select-Object Name, State, StartName, PathName
```

Stop if these commands do not reveal the checkout/root and a repeatable
supervisor. Record these operator values from the real process; do not guess
them:

```powershell
$Checkout = '<origin checkout from the running command/service>'
$ServiceName = '<Win32_Service.Name>'
$Python = '<exact python.exe imported by the running service; do not use the py launcher>'
$Expected = '<reviewed PR #52 commit SHA>'
$Previous = git -C $Checkout rev-parse HEAD
if (git -C $Checkout status --porcelain) { throw 'origin checkout is dirty; stop and resolve it first' }
```

Install exactly the reviewed commit with the same interpreter and deployment
mode the service actually uses. Do not assume `py -3` is the service's
interpreter, and do not call a checkout an installed distribution without
checking `PathName`/`CommandLine` above:

```powershell
git -C $Checkout fetch origin feat/convoy-wizard-vision
$Fetched = git -C $Checkout rev-parse FETCH_HEAD
if ($Fetched -ne $Expected) { throw "fetched SHA mismatch: $Fetched" }
git -C $Checkout switch --detach $Expected
if ((git -C $Checkout rev-parse HEAD) -ne $Expected) { throw 'origin SHA mismatch' }
# Only for a service proven above to import an installed distribution:
& $Python -m pip install --force-reinstall --no-deps $Checkout
# For checkout/editable/PYTHONPATH mode, keep that exact mode instead of pip installing.
Restart-Service -Name $ServiceName
```

After restart, re-query the listener and process. Confirm the PID, executable,
command line, service `State`, `StartName`, and `PathName` are the expected
ones; a changed account or interpreter is a stop condition, not evidence of a
successful redeploy.

If `$Service` is empty, do not kill the listener until the owner supplies the
actual scheduled-task/supervisor restart command. A manual foreground process
is not a durable production redeploy path.

Keep `CONVOY_MCP_WRITE_TOOLS` unset on this internet-facing process. Setting it
to `1` would expose thread mutation, repository inventory and process spawning
to public callers. The complete wizard is GREEN only on an authenticated or
gated loopback deployment.

Prove the origin directly on that host before touching the Worker:

```powershell
$Body = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
$Origin = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8788/mcp `
  -ContentType application/json -Body $Body
$Origin.result.tools.name
```

Derive the expected public set from the reviewed checkout and compare sets,
not remembered counts. Run this in the same shell only as a probe; preserve
the service's actual environment and deployment mode:

```powershell
$OldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $Checkout 'src'
$ExpectedPublic = @(& $Python -c 'import json; from convoy.mcp_http import TOOLS, _WRITE_TOOLS; print(json.dumps([t["name"] for t in TOOLS if t["name"] not in _WRITE_TOOLS]))' | ConvertFrom-Json)
$env:PYTHONPATH = $OldPythonPath
$Delta = @(Compare-Object -ReferenceObject $ExpectedPublic -DifferenceObject @($Origin.result.tools.name))
if ($Delta.Count) { $Delta | Format-Table | Out-String | Write-Error; throw 'public/loopback tool-set mismatch' }
```

Also call `initialize`. A checkout deployment should report `0.1.0+<git
description>`; a bare `0.1.0` from an installed package is not SHA evidence.
If loopback proof fails, roll back to `$Previous` with the same interpreter and
deployment mode, restart the named supervisor, and repeat the proof before
touching the Worker.

## Worker deploy

The Worker only needs redeployment when `workers-site.mjs`,
`wrangler.jsonc`, or static assets changed. It is not required for a Python-only
origin restart.

From an authenticated shell at the repository root:

```bash
npx wrangler@latest whoami
npx wrangler@latest deploy --dry-run
npx wrangler@latest deploy
npx wrangler@latest deployments status
```

Before approving the deploy, confirm its configuration says:

```text
MCP_ORIGIN=https://convoy.bot
route=convoy.bot/*
route kind=Worker Route (not Custom Domain)
```

If the Worker deploy fails or the edge no longer reaches MCP, run
`npx wrangler@latest rollback` and leave the already-verified Python origin
running.

## Edge proof and verdict

Repeat both `initialize` and `tools/list` against
`https://convoy.bot/mcp`. Save the exact returned names and version with the
deployment evidence.

The expected security verdict is:

- public endpoint: Gate 0 **RED** because every `_WRITE_TOOLS` verb is hidden;
- authenticated/gated loopback endpoint with `CONVOY_MCP_WRITE_TOOLS=1`:
  Gate 0 **GREEN** only if the fresh `tools/list` contains every required
  wizard verb.

After a public restart, expect exact parity with the derived public set:
`card`, `neurons`, `graph`, and `inbox` should appear; stale public `onboard`
must disappear; the public preflight remains RED with only write-gated
missing verbs and no `redeploy` remedies. This is origin-freshness/security
parity, not public wizard readiness.

An updated version or a newly visible read tool proves that the Python restart
landed. It does not authorize calling the public wizard GREEN.

## Attempt 2026-09-04T16:05Z (g2) — still blocked

Worktree `neurons/g2` on `b4b186d925bdb24e414cedd8abfa208d342d98b9`. Public
Gate 0 remains **RED**. Exact blockers this shell had:

| Probe | Result |
|---|---|
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` / `WRANGLER_*` in env | absent |
| `npx wrangler@3 whoami` (Node v20.19.2) | `You are not authenticated. Please run wrangler login.` |
| `npx wrangler@latest whoami` | Wrangler 4.129.0 requires Node `>=22`; VM is v20.19.2 |
| `~/.config/.wrangler` | logs + `metrics.json` only; no login |
| SSH / Windows origin checkout / Win32 service name | absent |
| Live `POST https://convoy.bot/mcp` `initialize` | HTTP 200, `serverInfo.version=0.1.0` |
| Live `tools/list` | **13** names: `roster`, `glance`, `onboard`, `terminals`, `context`, `send`, `feed`, `bring_up`, `open`, `hide`, `minimize`, `background`, `install` |
| `python -m convoy preflight` | RED, exit 1; missing `card, repos, clone, crew, consent, await_seated, neurons, graph, inbox` |

Do not deploy the Worker as a substitute. Do not set
`CONVOY_MCP_WRITE_TOOLS=1` on the internet-facing origin. Full E2E board:
`docs/e2e-dod.md`. Marketplace pin/PR body: `docs/marketplace-pr.md`.
