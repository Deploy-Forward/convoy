# Marketplace submit checklist — `plugin/convoy`

Submit against https://cursor.com/marketplace/publish (official Cursor
Marketplace, manual review). Community listing is https://cursor.directory
and is a **different** queue; do not treat directory publish as this form.

This file does **not** record that a submission was sent.

Official bullets (Cursor Plugins reference, 2026-09-04) mapped onto **this
repo**. GREEN = true in tree. RED = missing. UNVERIFIED = host/reviewer fact.

## Pack roots

| Path | Role |
|---|---|
| `plugin/convoy/` | Agent Plugin pack (`plugin.json` + `mcp.json` + `skills/`) |
| `plugin/convoy/.cursor-plugin/plugin.json` | Cursor discovery wrapper (`skills`, `mcpServers`) |
| `.cursor-plugin/marketplace.json` | repo-root multi-plugin manifest, `pluginRoot: "plugin"`, entry `convoy` / source `convoy` |

Local test (required before submit):

```bash
ln -s "$(pwd)/plugin/convoy" ~/.cursor/plugins/local/convoy
```

Then Developer: Reload Window → Customize → Convoy. Details: `docs/e2e-harness.md` step 0.

## Checklist

| # | Cursor requirement | This pack | Verdict |
|---|---|---|---|
| 1 | Valid root `plugin.json` **or** `.cursor-plugin/plugin.json` | Both: `plugin/convoy/plugin.json` (`$schema` agent-plugins.org 1.0.0) and `plugin/convoy/.cursor-plugin/plugin.json` | GREEN |
| 2 | `name` unique, lowercase, kebab-case | `"convoy"` | GREEN in tree; uniqueness vs the live Marketplace is **UNVERIFIED** until review |
| 3 | `description` explains purpose | plugin.json + wrapper + marketplace entry | GREEN |
| 4 | Components valid + frontmatter | `skills/convoy/SKILL.md`, `skills/convoy-wizard/SKILL.md` have YAML frontmatter (`name`, `description`) | GREEN (sequence tests pin the wizard) |
| 5 | Logo committed, relative path if provided | **no** `logo` field, no pack image | RED if you want a store tile; optional per Cursor docs |
| 6 | `README.md` documents usage / config | `plugin/convoy/README.md` + repo `README.md` | GREEN |
| 7 | Agent Plugins conform to schemas | `$schema` on `plugin.json` and `mcp.json`; tests in `test/demo/plugin_marketplace_pack_test.py` | GREEN vs schemas-in-tree; live schema fetch **UNVERIFIED** here |
| 8 | Cursor variables: every `${VAR}` in `mcp.json` declared | `mcp.json` has **no** `${VAR}` (fixed `https://convoy.bot/mcp`) | GREEN (n/a) |
| 9 | Manifest paths relative, no `..`, no absolute | `skills`, `mcp.json` | GREEN |
| 10 | Tested locally | documented; this cloud agent is not a Cursor desktop | UNVERIFIED until Marco’s symlink reload |
| 11 | Multi-plugin repo has `.cursor-plugin/marketplace.json` at **repo** root, unique names | present; one plugin `convoy` | GREEN |
| 12 | Public Git repo | `https://github.com/Deploy-Forward/convoy` | GREEN |
| 13 | Open source (Marketplace security FAQ) | `LICENSE` MIT, 2026 Deploy Forward | GREEN |

## Form fields to paste

- **Repository:** `https://github.com/Deploy-Forward/convoy`
- **Plugin directory / pack:** `plugin/convoy` (marketplace `pluginRoot` is `plugin`, source `convoy`)
- **MCP:** streamable-http `https://convoy.bot/mcp` (`plugin/convoy/mcp.json`)
- **Skills:** `convoy`, `convoy-wizard` (`@convoy`)
- **Public MCP honesty:** Gate 0 is RED on the public URL until write tools are opted in on a **gated loopback**, and until the Python origin on the tunnel is restarted on this tip (`docs/redeploy.md`). Do not tell reviewers the wizard is GREEN against today’s 13-tool public list.

## Do not submit until

1. Public origin restart scored GREEN for `--expect public` (20 reads, writes hidden) **or** the listing text explicitly says the public URL is read-only / Gate 0 RED.
2. Local symlink test (step 0) is GREEN on a Cursor desktop.
3. Optional logo, if you want a Marketplace tile.

## Out of scope for this pack

- `cursor.directory` self-serve listing (separate system).
- Team marketplace import (Dashboard → Plugins) — uses the same `marketplace.json` but is not `/marketplace/publish`.
