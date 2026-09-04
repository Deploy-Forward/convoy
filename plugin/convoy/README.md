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
frozen catalog. Public MCP `tools/list` may lag `main` until the deployed
server is redeployed, and some wizard verbs (`choices`, `inbox`, `join`,
`launch`, `seat`) have no MCP tool on `main` at all: they run through the
CLI. `python -m convoy preflight` prints the fail-closed card that says
which is which.
