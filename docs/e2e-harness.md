# E2E DoD harness outline (host + wire)

Definition of done for “plugin fully built” as a **scored walk**, not a
Windows Terminal demo. This Linux cloud agent does **not** run `wt` /
`bring_up dry_run=false`. Pane spawn is evidenced on the conductor’s
Windows origin, or as JSON on a gated loopback.

Packaged wizard skill (`plugin/convoy/skills/convoy-wizard/SKILL.md`) drives
`card` + `crew`. This harness still scores the operator path you asked for
(`choices` → N seats → `bring_up`) **and** the wizard equivalent. A step
that only exists as prose is RED.

Existing wire proof (CI, no WT): `test/demo/wizard_e2e_gated_test.py`.
Fill `test/demo/fixtures/e2e_harness.json` from the template when a human
host run is recorded; until then host rendering stays unverified.

## Evidence rules

Every step is **GREEN** or **RED**. Observed values only. `null` stays
`null`. Do not freeze `tools/list`. Do not claim connected from `launched`.

## Steps

### 0. Local plugin symlink

```bash
ln -s /path/to/convoy/plugin/convoy ~/.cursor/plugins/local/convoy
```

(Windows: `New-Item -ItemType SymbolicLink` to the same pack path.)

Reload the window. Customize must show **Convoy**.

| GREEN | RED |
|---|---|
| `~/.cursor/plugins/local/convoy/plugin.json` exists; Customize lists skills `convoy` + `convoy-wizard`; MCP server `convoy` attached from `mcp.json` (`https://convoy.bot/mcp` or a chosen loopback) | folder missing; marketplace install of the same `name` shadows local; MCP URL is neither the configured plugin URL nor the intended loopback |

### 1. `@convoy` Gate 0

Call live `tools/list` on the attached endpoint. Score with
`wizard_preflight` / `card.preflight` / `scripts/mcp_redeploy_verify.py`.

| | GREEN | RED |
|---|---|---|
| Public `https://convoy.bot/mcp` | 20 packaged **reads**, writes hidden, Gate 0 **RED** with `write-gated` for `repos`/`clone`/`onboard`/`crew`/`consent`/`await_seated`; reads that were missing on the 13-tool lag (`card`, `neurons`, `graph`, `inbox`, `choices`, …) now listed | still 13 tools; a write listed; a packaged read still `redeploy` |
| Gated loopback | Gate 0 **GREEN**, all 11 required verbs listed | any required verb missing |

Stop on RED. Do not ask `GitHub?`.

### 2. GitHub? yes

Ask. Record `yes` through `onboard(..., github=yes)` on a **gated**
endpoint (public `onboard` is hidden).

| GREEN | RED |
|---|---|
| `repos` returns the MCP host’s `gh` list (or honest `ok:false` + stderr / install hint, never a remembered list); after bind, `card.summary.github == "yes"` | `repos` listed on public; guessed repo list; a refused onboard wrote `.convoy/github` onto another thread |

### 3. `choices` (discovery surface)

Public read. Wizard uses `card` for the same facts; score **both** if the
host rendered `@convoy`.

| GREEN | RED |
|---|---|
| `choices.ok`; `harnesses[]` carry `where` / `models` / `effort`; no vendor resume id; no inbox token | tool missing (public lag); a resume id or token on the card |

### 4. N seats, C8 (one chair / worktree)

On gated: `crew` once for N **or** N `join`s each with its own minted
worktree. C8: a second chair on a held local worktree is refused, naming
both chairs. Cloud chairs have `worktree` null (C8 is local).

| GREEN | RED |
|---|---|
| N local chairs → N distinct sibling worktrees `<checkout>-wt-<name>`; each join/crew row has a boot prompt; C8 refusal leaves seats/feed untouched | two local chairs one worktree; `seat` used for chairs 2..N (no boot prompt); claimed launch after a refused crew |

### 5. One `cvy_*`

| GREEN | RED |
|---|---|
| one `convoy_id` `cvy_*` for the whole run; `neurons` + `graph` agree on chair count and that id | onboard bound a different root than the MCP process (stranded thread); multiple ids |

### 6. `bring_up` (no `wt` on this agent)

Public: `dry_run` default true. `dry_run=false` must refuse on an ungated
process **before** a runner. Gated: one window argv for the crew (or
`crew launch=true`, which already called bring-up once). `launched` is
not `connected` — `await_seated` observes acks.

| GREEN | RED |
|---|---|
| dry card has one `--window new` + N-1 splits, each `-d` a minted worktree; public `dry_run=false` → `ok:false`, runner never called; `await_seated` `connected` only on matching seated tokens | this (or any) agent ran `wt.exe`; public spawn; per-chair `bring_up`; `connected` inferred from `launched` |

## Wizard equivalent (packaged skill)

Gate 0 → `card` once → GitHub? → `repos` / path → `onboard` → N from
`card.rows` → `crew` once (`launch: true`) → `consent` if asked →
`await_seated` → `neurons` / `graph` → `send`. Do not call `join` /
`launch` / `seat` / `bring_up` per chair after `crew`.

## What this agent already proved vs not

| Proof | Status |
|---|---|
| Packaged catalogs 20 public / 33 gated / Gate 0 11 verbs | `scripts/mcp_redeploy_verify.py --catalog` |
| Loopback public + gated JSON-RPC on this checkout | `--loopback` (no WT) |
| CI vision walk | `test/demo/wizard_e2e_gated_test.py` |
| Live `https://convoy.bot/mcp` | **13 tools** (lag). Origin not restarted. See `docs/redeploy.md` |
| Host Customize / `@convoy` card chrome | **unverified** until Marco records `test/demo/fixtures/host_rendering.json` |
| Live WT panes | **out of scope** on this Linux agent |
