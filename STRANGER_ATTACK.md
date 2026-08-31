# Stranger attach attack (2026-08-31)

Would I tweet `convoy.bot` as a working Grok Bot MCP today?

**No.**

Live process is a 7-tool snapshot bound to one customer thread. README / `main` / SPEC describe a larger catalog and an onboard PATH card that this process does not serve. Python urllib attach without a Chrome UA is Cloudflare 1010. Seated grok/claude cannot `send`. Fake dual-send is not hop talk.

Do not treat this file as a live catalog. The live catalog is the 7 names below.

## 1. Catalog: live vs `TOOLS` vs README — RED

Live `tools/list` (this MCP session **and** a second-client `POST https://convoy.bot/mcp` with Chrome UA, 2026-08-31):

`roster`, `terminals`, `context`, `send`, `feed`, `bring_up`, `open`

That is the 2026-08-30 seven-tool snapshot. Same names, same order, same `send` description: `live=true execs ola_runner`.

`origin/main` (`5d3a74d`, post-#2) `src/convoy/mcp_http.py` `TOOLS`:

`roster`, `onboard`, `terminals`, `context`, `send`, `feed`, `bring_up`, `open`, `hide`, `minimize`, `background`, `install`

No `help` on `main`. No `glance` on `main`. Do not invent them into the live list.

README quick start tells a stranger to run MCP `onboard`, then use `hide` and `install`. Live `tools/call`:

| name | live result |
|---|---|
| `onboard` | `tool not found: onboard` |
| `install` | `tool not found: install` |
| `hide` | `tool not found: hide` |
| `help` | `tool not found: help` |
| `glance` | `tool not found: glance` |

Mismatch is RED for "worthy of sharing". SPEC already admits the deployed process can still be the 7-tool snapshot. README still leads with onboard as step 2.

## 2. One MCP process, one thread — RED

Live bound SoT (from `roster` / `terminals` / `context` / `bring_up`):

- `convoy_id`: `cvy_KE0tAyDLOnqEuWxYHjpsbQ`
- `thread`: `convoy test`
- checkout: `C:\Users\marco\ola\da-integration` (`integration/convoy-web-poc-20260828`, PR 167)
- seats: grok `grok-session-phase6bgrok`, claude `claude-session-phase6bclaude`

CANON / SPEC: one Convoy thread per Grok Bot conductor. A new conductor needs its own thread key or it stomps the same checkout.

Live `terminals` / `bring_up` with `cvy_6ZgRQ7am16POf9kHoJhHBQ`:

```
ok: false
error: convoy_id mismatch
convoy_id: cvy_KE0tAyDLOnqEuWxYHjpsbQ
thread: convoy test
```

A stranger who attaches `https://convoy.bot/mcp` is on customer 1's process. They cannot bind a second conductor id. They read and can stamp that layer.

## 3. Cloudflare 1010 — stranger attach is not "just works" — RED

`POST https://convoy.bot/mcp` `tools/list` from this box, 2026-08-31:

| client | result |
|---|---|
| `python3` `urllib.request` default / `Python-urllib/3.12` UA | HTTP 403, Cloudflare **1010** `browser_signature_banned`, `error_code: 1010`, `cf-ray: a337f0309cad77be` / `a337f030cf5999fe` |
| same urllib + Chrome 128 UA | HTTP 200, 7-tool catalog |
| `curl` with empty UA | HTTP 200, 7-tool catalog |

1010 is a browser-signature ban, not "forgot a header". A stranger writing a Python attach client hits a wall. Grok Bot / Chrome-shaped clients can pass. That is not "attach the URL and it just works".

GET `/` returns `convoy.bot · a grok-bot native mcp`. That line is not a working MCP.

## 4. Onboard / PATH card — specified vs live-proven — RED

Specified (README + `onboard.py` on `main`): user names harnesses; card reports PATH (`present`, `wired`, `path`); missing names point at `install`.

Live-proven:

- `onboard` is not in the live catalog. `tools/call` → `tool not found: onboard`.
- Live `roster` keys: `ok`, `agents`. **No `path`.** Tree `build_roster` would return `path` (`path_ok`, `path_written`, `path_bashrc`, `path_host`). This process does not.
- Live claude `usage_remaining` is a **string blob** (`Current session: 89% used · …`). SPEC / `main` clamp is `number \| object \| null`. Tree `normalize_usage_remaining` would null it. Live does not.
- README "117 tests green" / CLI emulator onboard on a temp root is not a live MCP call. Not GREEN.

No live `onboard`. No live PATH card. Do not mark GREEN.

## 5. Glance PR #3 — not on live MCP — RED

https://github.com/Deploy-Forward/convoy/pull/3

- title: honest glance overall + by-thread
- state: **DRAFT**, **CONFLICTING**
- live `tools/call glance` → `tool not found: glance`

Not shipped. Not cataloged. Ignore it as SoT.

PR #4 (native send + `session_id`/`resume`) is OPEN and not on this live process. Live `send` still has no `instance_id` / `session_id` / `resume` in the schema.

## 6. Hop talk — fake stamps only; grok/claude cannot send — RED

SPEC DoD: two `send`s, two `session_id`s, `feed --since` two `kind=synapse` rows a second client can read. Native vendor CLI. No `ola-brain`. Seated grok/claude participate.

Live `send` schema: `to`, `body`, `model`, `label`, `worktree`, `live`. No `instance_id`. Description still: default fake, `live=true execs ola_runner`.

Live calls this session:

| to | args | result |
|---|---|---|
| grok | body only | `seat exists; attach and resume session_id`, `session_id: null` |
| claude | body only | same refuse |
| grok | extra `instance_id=grok-session-phase6bgrok` via HTTP | same refuse (arg dropped) |
| agy | no worktree | `two agents on one branch without a worktree is a bug` (da-integration) |
| cursor-agent | no worktree | same overlap refuse |
| agy | `worktree=C:\Users\marco\ola\evco-test` | fake `ok`, `session_id=spawned-agy`, body `ACK agy: …` |
| cursor-agent | same worktree | fake `ok`, `session_id=spawned-cursor-agent`, body `ACK cursor-agent: …` |

Second-client `feed` `since=2026-08-31T00:00:00.000000Z` (urllib + Chrome UA, not this session):

```
2026-08-31T00:32:29.396999Z  kind=synapse  to=agy           ok=true  instance_id=spawned-agy
2026-08-31T00:32:51.949578Z  kind=synapse  to=cursor-agent  ok=true  instance_id=spawned-cursor-agent
```

Two fake rows, two minted `spawned-*` ids, readable by a second HTTP client. SPEC: **fake dual-send is not talk.** Prior 2026-08-30 feed already had one fake agy synapse and one failed agy. grok/claude still cannot send.

`ola_runner` was not invoked. Do not wrap it. Do not call that hop talk.

## Verdict

Tweet `convoy.bot` as a working Grok Bot MCP today? **No.**

What is actually live: a Cloudflare-fronted 7-tool HTTP MCP, one process, one `cvy_KE0tAyDLOnqEuWxYHjpsbQ` / `convoy test` / da-integration checkout, fake `send`, seated grok/claude refused, onboard/install/hide/glance absent, Python urllib 1010 without a Chrome signature.

What `main` and README specify is a different catalog and an onboard PATH flow that this process does not run.

Not GREEN. Not tweetable.
