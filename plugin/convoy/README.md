# Convoy plugin (Grok Build marketplace pack)

This folder is the installable Convoy plugin root. The official xAI Grok
Marketplace can clone this repository at a pinned commit with
`path: "plugin/convoy"` and discover:

- `.mcp.json` (the Convoy hosted MCP endpoint)
- `skills/` (`convoy` + `convoy-wizard`)
- `.grok-plugin/plugin.json` (display metadata)

## Layout

```text
plugin/convoy/
├── .grok-plugin/plugin.json
├── .mcp.json
├── harness_effort.json   (byte-identical copy of src/convoy/harness_effort.json)
├── skills/
│   ├── convoy/SKILL.md
│   └── convoy-wizard/SKILL.md
├── plugin.json            (Agent Plugins compatibility)
├── mcp.json               (Agent Plugins compatibility)
└── .cursor-plugin/plugin.json
```

The unprefixed manifests and `.cursor-plugin` wrapper remain compatibility
surfaces; the xAI catalog and Grok Build discover `.mcp.json`,
`.grok-plugin/plugin.json`, and `skills/`.

## Install from Grok Marketplace

The official catalog is
[`xai-org/plugin-marketplace`](https://github.com/xai-org/plugin-marketplace).
Until a catalog PR merges, this pack is not listed there. After it is, Grok
Build install matches Exa:

1. In Grok Bot, open **Settings → Plugins** and select **Marketplace**.
2. Find **convoy** and install it; installed plugins are visible under **Yours**.
3. The MCP view should show the `convoy` server (`type: http`,
   `https://convoy.bot/mcp`). There is no OAuth/sign-in step; this plugin
   reads no API key.

Grok Build's `/marketplace` command is also supported: find **convoy** and
press `i`.

The catalog entry is a third-party remote source, same shape as Exa's
(`name` kebab-case, `source.source=url`, full 40-char `sha`, optional
`path` because the plugin root is not the git root):

```json
{
  "name": "convoy",
  "description": "Orchestrate BYO AI harnesses as neurons on one Convoy thread with a live, fail-closed MCP wizard.",
  "category": "development",
  "source": {
    "source": "url",
    "url": "https://github.com/Deploy-Forward/convoy.git",
    "sha": "<full reviewed 40-character commit>",
    "path": "plugin/convoy"
  },
  "homepage": "https://convoy.bot",
  "keywords": ["convoy", "convoy wizard", "convoy bot"],
  "domains": ["convoy.bot"]
}
```

The SHA must be the commit containing this pack. After adding or updating the
entry, regenerate `.grok-plugin/plugin-index.json` with the official
marketplace's `python3 scripts/generate-plugin-index.py`; never hand-edit the
generated index.

## Network and permission disclosure

- The installed MCP config connects only to `https://convoy.bot/mcp`.
- The plugin reads no API key, environment variable, SSH key, or GitHub token.
- `repos` runs `gh repo list` as the account logged in on the **MCP host**.
  A per-user/local endpoint therefore sees that user's login; the shared public
  endpoint must keep `repos` hidden.
- Repository choices, thread identifiers, and routed task text are sent to the
  configured MCP endpoint when the user invokes those tools.
- Public Convoy is read-only for lifecycle operations. Completing the wizard
  requires an authenticated or gated user-controlled endpoint; the plugin does
  not silently enable its write gate or install vendor harnesses.

## Cursor compatibility test

Clone/copy this folder to `~/.cursor/plugins/local/convoy`, reload Cursor, and
check Plugins search for **Convoy**. Installing should add the same endpoint
and both skills. Cursor's marketplace wrapper is compatibility metadata, not
the Grok Marketplace source of truth.

## Host rendering

Host rendering: unverified. Whether Grok Bot surfaces the wizard skill as
`@convoy` or `/convoy`, and whether it renders the `card` tool's
`structuredContent` as one card with a drill-down (the way `@treg` renders its
providers) or only shows the text copy, is a fact about the host that nothing
in this repository observes. The server declares `card` with an MCP
`outputSchema` and answers through `structuredContent` so a host that renders
cards can; the claim that it does stays unverified until Marco records a live
run in `test/demo/fixtures/host_rendering.json` (date + verbatim evidence),
which flips `host_rendering_contract_test` from skipped to asserting.

## Notes on live MCP catalog

The plugin skills always require live `tools/list` and must never hardcode a
frozen catalog. Every verb the wizard calls is registered on `main`
(`src/convoy/mcp_http.py`), but a live `tools/list` can still lack some of
them for two different reasons, and the wizard's Gate 0 tells them apart:

- **redeploy** - the public deploy lags `main`, so a registered verb is not
  served yet. A redeploy fixes it.
- **write-gated** - of the verbs the wizard needs, `repos`, `clone`, `onboard`,
  `crew`, `consent`, `await_seated`, and `send` are hidden on an ungated process
  (onboard binds the thread and clones a URL; `clone` is the explicit git
  clone the sequence may call; crew mints worktrees, joins N chairs and may
  spawn the window; `repos` runs `gh repo list` as the MCP host's own login,
  the conductor's account; `consent` mints a one-time grant; `await_seated`
  holds the request thread up to its timeout). The same gate covers `seat`,
  `join`, `launch`, `mint`, `seated`, `stamp` and `note`, which the wizard no
  longer calls per chair now that `crew` does that work in one call,
  so an ungated public process hides them from `tools/list` on purpose and
  Gate 0 is RED there by design. They appear only on a deploy
  with `CONVOY_MCP_WRITE_TOOLS=1` (a gated loopback process). A redeploy alone
  does not change this; the gate does.

The read-only `card` tool carries the same verdict as `card.preflight`, scored
on the serving process's own `tools/list`, so a host sees RED or GREEN on the
card itself before the wizard asks anything.

The wizard fails closed on either gap; it never falls back to the CLI, because
a marketplace install is not a source checkout. Operators with a checkout can
run `python -m convoy preflight` for the card that names which gap is which.
