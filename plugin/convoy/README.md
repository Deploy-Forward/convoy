# Convoy Agent Plugin (Marketplace pack)

This folder is the installable Agent Plugin pack for Convoy so plugin search
can find **Convoy** and install both:

- `mcp.json` (public Convoy MCP server)
- `skills/` (`convoy` + `convoy-wizard`)

## Layout

```text
plugin/convoy/
├── plugin.json
├── mcp.json
├── harness_effort.json   (byte-identical copy of src/convoy/harness_effort.json)
├── skills/
│   ├── convoy/SKILL.md
│   └── convoy-wizard/SKILL.md
├── .cursor-plugin/plugin.json
└── .grok-plugin/plugin.json   (xAI indexer: skills + mcp.json)
```

`plugin.json` is Agent Plugins format (`agent-plugins.org` schema). The
`.cursor-plugin/plugin.json` wrapper is included for Cursor marketplace
multi-plugin discovery flows. `.grok-plugin/plugin.json` is what
`xai-org/plugin-marketplace` `extract_plugin` loads (it ignores Agent Plugins
`plugin.json` and Cursor's wrapper); `mcpServers: "mcp.json"` is how the
indexer finds the streamable-http server. Catalog entry:
[`docs/xai-plugin-marketplace.md`](../../docs/xai-plugin-marketplace.md).

## Local IDE test

Symlink this folder (do not copy if you want live edits):

`ln -s /path/to/convoy/plugin/convoy ~/.cursor/plugins/local/convoy`

Then reload Cursor and check Customize for **Convoy**. Installing should
add the Convoy MCP endpoint and both skills. GREEN/RED evidence for the
full walk (Gate 0 → GitHub → choices → N seats / C8 → `cvy_*` → bring_up):
[`docs/e2e-harness.md`](../../docs/e2e-harness.md).

## Publish path

Submit the repository to:

https://cursor.com/marketplace/publish

Operator checklist mapped onto this pack:
[`docs/marketplace-submit.md`](../../docs/marketplace-submit.md).
Public MCP catalog lag and origin restart:
[`docs/redeploy.md`](../../docs/redeploy.md).

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
- **write-gated** - of the verbs the wizard needs, `repos`, `onboard`, `crew`,
  `consent`, and `await_seated` are hidden on an ungated process (onboard
  binds the thread and clones a URL; crew mints worktrees, joins N chairs and
  may spawn the window; `repos` runs `gh repo list` as the MCP host's own
  login, the conductor's account; `consent` mints a one-time grant;
  `await_seated` holds the request thread up to its timeout). The same gate
  covers `seat`, `join`, `launch`, `mint`, `clone`, `seated`, `stamp` and
  `note`, which the wizard no longer calls per chair now that `crew` does that
  work in one call,
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
