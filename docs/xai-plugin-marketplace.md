# xAI plugin-marketplace catalog entry (draft)

Paste into [`xai-org/plugin-marketplace`](https://github.com/xai-org/plugin-marketplace)
`.grok-plugin/marketplace.json` `plugins` array. This file is a **draft** in
Deploy-Forward/convoy. It does **not** mean a PR was opened on xai-org.

Schema and process: that repo’s [README](https://github.com/xai-org/plugin-marketplace/blob/main/README.md)
and [CONTRIBUTING](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
(fetched 2026-09-04). Nested remotes (MongoDB, Railway, Stripe) use
`source.path` the same way.

## Exact catalog object

Remote **url** + **40-char lowercase sha** + **nested path**. `name` is
kebab-case `convoy`. Keywords/domains are brand-scoped (CONTRIBUTING: no
generic `mcp` / `cli` / `api`).

```json
{
  "name": "convoy",
  "description": "Convoy for Grok Bot: attach one MCP endpoint, discover live tools, and run the @convoy wizard (GitHub → N neurons on one thread). Public https://convoy.bot/mcp is read-only; write verbs stay hidden until a gated loopback sets CONVOY_MCP_WRITE_TOOLS=1.",
  "category": "development",
  "source": {
    "source": "url",
    "url": "https://github.com/Deploy-Forward/convoy.git",
    "sha": "d5c711d51827dab214f5372ad5b6124429dee44a",
    "path": "plugin/convoy"
  },
  "homepage": "https://convoy.bot",
  "keywords": ["convoy", "convoy.bot", "grok-bot", "@convoy"],
  "domains": ["convoy.bot"]
}
```

| Field | Value | Why |
|---|---|---|
| `source.source` | `"url"` | Remote third-party (not vendored under `external_plugins/`) |
| `source.url` | `https://github.com/Deploy-Forward/convoy.git` | Official org `Deploy-Forward`, not a personal fork (CONTRIBUTING) |
| `source.sha` | `d5c711d51827dab214f5372ad5b6124429dee44a` | Full pin of the commit that added `plugin/convoy/.grok-plugin/plugin.json`. **Not** `main`, not a tag, not a short SHA. |
| `source.path` | `plugin/convoy` | Pack is nested. Indexer does `plugin_root_for_fetch(dest, "plugin/convoy")`. |

Confirm the pin is still on a public ref after push:

```bash
git ls-remote https://github.com/Deploy-Forward/convoy.git d5c711d51827dab214f5372ad5b6124429dee44a
git cat-file -t d5c711d51827dab214f5372ad5b6124429dee44a   # commit
```

If that commit is only on `cursor/redeploy-e2e-dod-3f0a` until merge, **wait until it is reachable on GitHub** (this branch or `feat/convoy-wizard-vision` / `main`). CI clones by SHA; a missing object fails loudly. A squash-merge **changes** the SHA — bump the pin, do not keep this one.

`git ls-remote … HEAD` is `main` (`05277e5…` as of 2026-09-04) and does **not** yet contain the Grok manifest. Do not pin HEAD until this lands on `main`.

## Why `.grok-plugin/plugin.json` exists

`scripts/plugin_catalog.py` `load_manifest` only reads:

- `.grok-plugin/plugin.json`
- `.claude-plugin/plugin.json`

It does **not** read Agent Plugins `plugin.json` or `.cursor-plugin/plugin.json`.
`scan_mcp_servers` then uses `manifest.mcpServers` or defaults to `.mcp.json`.
Without the Grok wrapper, `skills/` still indexes from disk, but `mcp.json`
would be invisible. The wrapper sets `"mcpServers": "mcp.json"` (same file
Cursor already ships).

Expected `plugin-index.json` fragment after
`python3 scripts/generate-plugin-index.py` (descriptions truncated by the
indexer’s 120-char cleaner):

```json
"convoy": {
  "sha": "d5c711d51827dab214f5372ad5b6124429dee44a",
  "version": "0.1.0",
  "components": {
    "mcpServers": [
      { "name": "convoy", "description": "streamable-http" }
    ],
    "skills": [
      {
        "name": "convoy",
        "description": "/convoy orchestrates Convoy using live tools/list, never a frozen catalog."
      },
      {
        "name": "convoy-wizard",
        "description": "Optional @convoy wizard: fail-closed live-tool preflight, then ONE card (harness -> model -> effort | attach, usage remaining per harness) that drives GitHub gate, repo selection, N neurons, one-window launch and observed connects."
      }
    ]
  }
}
```

## xAI marketplace PR checklist (CONTRIBUTING)

Work happens on a **fork of `xai-org/plugin-marketplace`**, branch from `main`.
This convoy repo cannot open that PR from here (`gh` is read-only; no xai-org
write).

### Submit in 6 steps

1. Fork `xai-org/plugin-marketplace`, branch from `main`.
2. Append the JSON object above to `.grok-plugin/marketplace.json` `plugins` (valid JSON, unique `name`).
3. SHA already pinned (table above). Re-check `git ls-remote` on the **public** convoy SHA.
4. `python3 scripts/generate-plugin-index.py` — never hand-edit `.grok-plugin/plugin-index.json`.
5. `python3 scripts/validate-catalog.py` and `python3 scripts/generate-plugin-index.py --check`.
6. Open the PR, fill the template, wait for CI + code-owner review.

### Requirements checklist

- [ ] One entry in `.grok-plugin/marketplace.json`, valid JSON, kebab-case unique `name` (`convoy` is absent from the 2026-09-04 catalog).
- [ ] Remote `sha` is 40-char lowercase hex; commit public and reachable.
- [ ] `plugin-index.json` regenerated and committed (CI fails if stale).
- [ ] `homepage` + clear `description`; brand-scoped `keywords`/`domains`; `category`.
- [ ] License stated (MIT on `plugin/convoy/.grok-plugin/plugin.json`, repo `LICENSE`).
- [ ] Security expectations read (below).

### Security / PR template answers

- [ ] No `curl | bash`, remote-code download/exec, or `postinstall` RCE. (Python stdlib MCP; plugin is skills + remote HTTP MCP.)
- [ ] No reading/exfiltration of secrets, tokens, `.env`, or env vars.
- [ ] Hooks and MCP scope are least-privilege. **No hooks.** MCP is one streamable-http URL.
- **Network endpoints:** `https://convoy.bot/mcp` (JSON-RPC tools/list and tools/call). Worker + Cloudflare Tunnel in front; see `docs/redeploy.md`.
- **Credentials:** none for the public URL. Write tools require operator env `CONVOY_MCP_WRITE_TOOLS=1` on a **loopback** process, not this plugin.

### What review will check

| Dimension | Convoy answer |
|---|---|
| Source legitimacy | `Deploy-Forward/convoy`, MIT, homepage `https://convoy.bot` |
| Security | remote MCP only; public process hides writes (`SECURITY_GATES.md`) |
| Components | skills `convoy`, `convoy-wizard`; MCP `convoy` streamable-http |
| Duplication | no `convoy` row in catalog as of 2026-09-04 |
| CI | validate-catalog + generate-plugin-index --check |

### Common send-backs to avoid

- Pinning `main` / a tag / a short SHA.
- Pinning a SHA that only exists on a laptop (push this branch first).
- Hand-editing `plugin-index.json`.
- Generic keywords (`mcp`, `cli`, `api`, `deploy`).
- Claiming Gate 0 GREEN against live `https://convoy.bot/mcp` while it still lists **13** tools (`docs/redeploy.md`).

## Cursor vs xAI

Cursor official form: [`docs/marketplace-submit.md`](marketplace-submit.md)
(`cursor.com/marketplace/publish`). Different queue, different manifests
(`.cursor-plugin` vs `.grok-plugin`). Ship both; do not treat one as the other.
