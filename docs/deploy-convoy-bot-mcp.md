# Deploying the convoy.bot MCP origin

`convoy.bot` has two independently deployed layers. Updating the Cloudflare
Worker does **not** update the Python MCP server.

## Topology

The deployment this repository describes:

```text
convoy.bot/* Worker Route
  -> Worker convoy-bot
  -> MCP_ORIGIN=https://convoy.bot
  -> proxied convoy.bot DNS record
  -> a Cloudflare Tunnel
  -> the tunnel connector on the origin machine
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

## Supervising the origin

Never leave the origin as a foreground Python process: when its parent goes
away nothing owns it and nothing restarts it. `convoy install --local`
registers it as the user-level scheduled task `ConvoyBotMcp` with
restart-on-failure and an at-logon trigger. Prove a replacement on a spare
loopback port before cutover.

Pin the origin to a detached worktree at a merged commit, with its own virtual
environment as the task's interpreter. After cutover, loopback and
`https://convoy.bot/mcp` must agree:

```text
serverInfo.version = 0.1.0+<merged sha>
tools/list = the derived public set (see below)
onboard listed = false
direct onboard call = write tool disabled
GET /mcp = 200 (attach page)
```

Keep the scheduled-task definition and machine-local root outside Git.
For each deploy, stage and smoke-test the new merged SHA on a spare port,
update the task action to that pinned worktree/interpreter, start it, and prove
loopback before proving the edge.

## Who can restart the origin

A restart needs all of the following, and none of them is in this repository:

- a management path to the origin machine;
- the Python origin's checkout path and bound thread root;
- the supervisor definition for the MCP process;
- an authenticated Wrangler profile or Cloudflare token, for Worker changes.

Cloudflare can identify the connector and ingress, but it cannot update files
or restart the Python process on the origin machine. Do not deploy the Worker
as a substitute. The origin owner supplies the host access and supervisor
name, then follows the steps below.

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
$Expected = '<reviewed commit SHA>'
$Previous = git -C $Checkout rev-parse HEAD
if (git -C $Checkout status --porcelain) { throw 'origin checkout is dirty; stop and resolve it first' }
```

Install exactly the reviewed commit with the same interpreter and deployment
mode the service actually uses. Do not assume `py -3` is the service's
interpreter, and do not call a checkout an installed distribution without
checking `PathName`/`CommandLine` above:

```powershell
git -C $Checkout fetch origin <reviewed branch>
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

## Identity on the wire (2026-09-12)

The way a conductor writes over the public edge is a bearer, not the flag:

1. On the origin's machine, in your own terminal (never in a chat or a transcript):
   `convoy conductor mint --label "<connector name>"`. The card shows the bearer
   once. Only its sha256 is kept, in `<CONVOY_HOME>/conductors.jsonl`.
2. Put it on the connector as the header `Authorization: Bearer <bearer>`.
3. The origin checks it on every POST. Wrong or revoked is a 401 before the body
   is parsed. No header is an anonymous read-only caller.
4. `roster.conductor.write_gate` reports `bearer`, `legacy-flag`, or `closed`, and
   `bearers` counts the live ones. A stamp that arrived with a bearer carries
   `principal: {bearer: <id>}`; one that did not carries `principal: null`.
5. `convoy conductor list` and `convoy conductor revoke <id>` manage them.

`tools/list` shows the write tools whenever a live bearer exists, because the
process can accept writes from its holder; each call is still checked.

### Anonymous callers on the public edge

Without this rule, a call through the public URL with no bearer could list
every thread on the machine with its filesystem root, and `card` and `roster`
would carry checkout and worktree paths. So identity is the arbiter on the edge:

- A request is *public* when it carries a proxy header (`Cf-Connecting-Ip`,
  `X-Forwarded-For`, `Forwarded`, `X-Real-Ip`) or comes from a non-loopback
  peer. A loopback caller with no such header is local and unchanged.
- Public and anonymous gets the product surface only: `card`, `choices`,
  `install` (forced dry) and `threads` as a count. Every other tool refuses by
  name and points at `convoy conductor mint`. `tools/list` shows exactly that set.
- Every card an anonymous public caller receives has filesystem paths scrubbed
  to `[redacted]`, and `threads` never enumerates names or ids.
- `CONVOY_MCP_WRITE_TOOLS=1` is a loopback switch. It opens nothing to a public
  anonymous caller, reads or writes. Do not set it on a public edge anyway.
- A bearer holder through the edge sees whole cards, as before.

So the edge proof below differs by identity: anonymous `tools/list` returns the
four product tools; with `Authorization: Bearer` it returns the full set.

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
deployment evidence. An anonymous `tools/list` on the edge is the four
product tools; the derived-set comparison above applies to a call that
carries a bearer (or to loopback), not to an anonymous edge call.

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

## Before you finish

Public Gate 0 stays **RED** on an anonymous edge by design. Wrangler 4.129.0
requires Node 22 or later, and a shell with no `CLOUDFLARE_API_TOKEN` and no
Wrangler login cannot deploy the Worker at all.

Do not deploy the Worker as a substitute. Do not set
`CONVOY_MCP_WRITE_TOOLS=1` on the internet-facing origin. Full E2E board:
`docs/e2e-dod.md`. Marketplace pin/PR body: `docs/marketplace-pr.md`.
