# xai-org/plugin-marketplace PR body (convoy)

Official SoT: https://github.com/xai-org/plugin-marketplace
Pin (PR [#52](https://github.com/Deploy-Forward/convoy/pull/52) tip):
`b4b186d925bdb24e414cedd8abfa208d342d98b9`

Opened: https://github.com/xai-org/plugin-marketplace/pull/560
(`ruffinellimarco:add-convoy-plugin` @ `f3579ac4311c22f9e9439b81e542cd2183556402`,
same pin and 36-line catalog/index diff this neuron generated).
`mergeable_state` was `blocked` at 2026-09-04T16:15Z (owners/CI, not content).
Do not open a second PR. Do not hand-edit `.grok-plugin/plugin-index.json`.

Live `https://convoy.bot/mcp` is still 13 tools / public Gate 0 **RED**. The
listing is the pack + hosted endpoint, not a claim that the public wizard is
GREEN. See `docs/e2e-dod.md`.

## Catalog entry to add

Append to `.grok-plugin/marketplace.json` `plugins` (Exa remote-source shape,
with `path` because the plugin root is not the git root — same as mongodb /
railway / stripe):

```json
{
  "name": "convoy",
  "description": "Orchestrate BYO AI harnesses as neurons on one Convoy thread with a live, fail-closed MCP wizard.",
  "category": "development",
  "source": {
    "source": "url",
    "url": "https://github.com/Deploy-Forward/convoy.git",
    "sha": "b4b186d925bdb24e414cedd8abfa208d342d98b9",
    "path": "plugin/convoy"
  },
  "homepage": "https://convoy.bot",
  "keywords": ["convoy", "convoy wizard", "convoy bot"],
  "domains": ["convoy.bot"]
}
```

Then from the marketplace clone:

```bash
python3 scripts/generate-plugin-index.py
python3 scripts/validate-catalog.py
python3 scripts/generate-plugin-index.py --check
```

The SHA is a public commit on `feat/convoy-wizard-vision` (reachable:
`git fetch https://github.com/Deploy-Forward/convoy.git b4b186d925bdb24e414cedd8abfa208d342d98b9`
succeeded in this run). Re-pin after #52 merges if `main` is a different SHA.

## PR title

```text
Add convoy plugin (remote source, Deploy-Forward/convoy)
```

## PR body (paste into GitHub)

```markdown
<!--
Adding or updating a plugin? Read CONTRIBUTING.md first.
Run these locally before opening the PR — they're exactly what CI checks:
  python3 scripts/generate-plugin-index.py
  python3 scripts/validate-catalog.py
  python3 scripts/generate-plugin-index.py --check
-->

## What this PR does

- Plugin name: convoy
- Type: remote source
- Source URL + pinned SHA (remote): https://github.com/Deploy-Forward/convoy.git @ `b4b186d925bdb24e414cedd8abfa208d342d98b9` path `plugin/convoy`
- Homepage: https://convoy.bot

Adds **convoy** as a third-party remote listing, same shape as Exa
(`.grok-plugin/plugin.json` + `.mcp.json` `type: http` + `skills/`).
The plugin root is a subdirectory, so `source.path` is `plugin/convoy`
(mongodb/railway/stripe pattern).

The hosted MCP URL in `.mcp.json` is `https://convoy.bot/mcp`. The plugin
reads no API key. Public Convoy hides write/lifecycle verbs
(`CONVOY_MCP_WRITE_TOOLS` unset); the wizard fail-closes (Gate 0 RED) until
the user points at a gated/loopback endpoint. That is disclosed in the pack
README and skill, not a silent enable.

## Ownership

- [x] I own this plugin or have the right to distribute it.
- [x] The `source` repo is published under our official org (or I've explained why not below).

Source org: [Deploy-Forward/convoy](https://github.com/Deploy-Forward/convoy)
(MIT). Pack path: `plugin/convoy`. SHA is PR
[#52](https://github.com/Deploy-Forward/convoy/pull/52) tip
`b4b186d925bdb24e414cedd8abfa208d342d98b9`. Re-pin after merge if needed.

## Checklist

- [x] Added/updated exactly one entry in `.grok-plugin/marketplace.json` (valid JSON, kebab-case `name`).
- [x] Remote source pins a full 40-char lowercase commit `sha`, and that commit is public + reachable.
- [x] Regenerated `.grok-plugin/plugin-index.json` (`python3 scripts/generate-plugin-index.py`).
- [x] `python3 scripts/validate-catalog.py` passes locally.
- [x] `python3 scripts/generate-plugin-index.py --check` passes locally.
- [x] `homepage` + clear `description` set; local plugins include `README.md` + `.grok-plugin/plugin.json`.
- [x] License is stated.

## Security

- [x] No `curl | bash`, remote-code download/exec, or `postinstall` RCE.
- [x] No reading/exfiltration of secrets, tokens, `.env`, or env vars.
- [x] Hooks and MCP scope are least-privilege.
- Network endpoints this plugin calls (and why):
  `https://convoy.bot/mcp` only (hosted Convoy MCP). The plugin does not
  call other origins. `repos` on a *gated* MCP host runs `gh repo list` as
  that host's login; the public endpoint must keep `repos` hidden.
- Credentials/permissions it requires (and why):
  none. No API key, OAuth, env var, or GitHub token is read by the plugin
  pack. Completing the wizard needs an authenticated or gated user-controlled
  Convoy endpoint (`CONVOY_MCP_WRITE_TOOLS=1`); the pack does not flip that
  gate.

## Notes for reviewers

- Keywords are brand-scoped (`convoy`, `convoy wizard`, `convoy bot`); no
  generic `mcp`/`cli`/`deploy`.
- `.mcp.json` `type` is `http` (Exa / Grok Build indexer). A compatibility
  `mcp.json` with `streamable-http` remains in the pack for Agent Plugins; the
  xAI indexer reads `.mcp.json` because the grok manifest does not override
  `mcpServers`.
- Expected index components after generate (observed 2026-09-04T16:10Z;
  `validate-catalog.py` and `generate-plugin-index.py --check` both OK):

```json
"convoy": {
  "sha": "b4b186d925bdb24e414cedd8abfa208d342d98b9",
  "version": "0.1.0",
  "components": {
    "mcpServers": [
      { "name": "convoy", "description": "http" }
    ],
    "skills": [
      {
        "name": "convoy",
        "description": "/convoy orchestrates Convoy using live tools/list, never a frozen catalog."
      },
      {
        "name": "convoy-wizard",
        "description": "Optional @convoy wizard: fail-closed live-tool preflight, then ONE card (harness -> model -> effort | attach, usage rem…"
      }
    ]
  }
}
```
```

## Operator commands (fork path)

```bash
gh repo fork xai-org/plugin-marketplace --clone --default-branch-only
cd plugin-marketplace
git checkout -b add-convoy-plugin
# apply catalog entry above, then:
python3 scripts/generate-plugin-index.py
python3 scripts/validate-catalog.py
python3 scripts/generate-plugin-index.py --check
git add .grok-plugin/marketplace.json .grok-plugin/plugin-index.json
git commit -m "Add convoy plugin (Deploy-Forward/convoy @ b4b186d925bdb24e414cedd8abfa208d342d98b9)"
git push -u origin add-convoy-plugin
gh pr create --repo xai-org/plugin-marketplace --title "Add convoy plugin (remote source, Deploy-Forward/convoy)" --body-file - <<'EOF'
# paste PR body
EOF
```
