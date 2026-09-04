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
└── .cursor-plugin/plugin.json
```

`plugin.json` is Agent Plugins format (`agent-plugins.org` schema). The
`.cursor-plugin/plugin.json` wrapper is included for Cursor marketplace
multi-plugin discovery flows.

## Local IDE test

Clone/copy this folder to:

`~/.cursor/plugins/local/convoy`

Then reload Cursor and check Plugins search for **Convoy**. Installing should
add the Convoy MCP endpoint and both skills.

## Publish path

Submit the repository to:

https://cursor.com/marketplace/publish

## Notes on live MCP catalog

The plugin skills always require live `tools/list` and must never hardcode a
frozen catalog. Every verb the wizard calls is registered on `main`
(`src/convoy/mcp_http.py`), but a live `tools/list` can still lack some of
them for two different reasons, and the wizard's Gate 0 tells them apart:

- **redeploy** - the public deploy lags `main`, so a registered verb is not
  served yet. A redeploy fixes it.
- **write-gated** - `seat`, `join`, and `launch` mutate the thread or spawn a
  process, so an ungated public process hides them from `tools/list` on
  purpose and Gate 0 is RED there by design. They appear only on a deploy
  with `CONVOY_MCP_WRITE_TOOLS=1` (a gated loopback process). A redeploy alone
  does not change this; the gate does.

The wizard fails closed on either gap; it never falls back to the CLI, because
a marketplace install is not a source checkout. Operators with a checkout can
run `python -m convoy preflight` for the card that names which gap is which.
