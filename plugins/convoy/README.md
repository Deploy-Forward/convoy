# Convoy for OpenAI plugins

This is the OpenAI plugin package for
[Deploy-Forward/convoy](https://github.com/Deploy-Forward/convoy). It connects
Codex to the public Convoy MCP endpoint and bundles the fail-closed `convoy`
skill.

The command-true product journey and its hosted isolation requirement are in
the repository's
[`docs/convoy-happy-path.md`](https://github.com/Deploy-Forward/convoy/blob/main/docs/convoy-happy-path.md).

## Package contents

- `.codex-plugin/plugin.json` — OpenAI plugin metadata and presentation.
- `.mcp.json` — remote HTTP MCP connection to `https://convoy.bot/mcp`.
- `skills/convoy/SKILL.md` — live-capability orchestration and consent rules.
- `assets/logo.svg` — the canonical Deploy Forward mark.

There is deliberately no `.app.json`: Convoy has not declared a registered
OpenAI connector ID. The remote MCP connection is fully described by
`.mcp.json`.

## Install from this repository

From a checkout of the repository:

```text
codex plugin marketplace add <checkout-root>
codex plugin add convoy@convoy
```

Installing the plugin authorizes the declared MCP connection and its bundled
skill for the active product. It is revocable by disabling or uninstalling the
plugin. It does not bypass Convoy's endpoint write gate or action-scoped
consent, accept vendor trust prompts, steal occupied sessions, or inject
keystrokes.

The manifest advertises `Interactive` and `Read` because its declared public
endpoint is not a general-purpose write connection. Guided crew creation fails
closed when its required lifecycle tools are absent. Operators who intentionally
enable lifecycle writes should run a root-bound Convoy MCP endpoint in a trusted
environment and configure the plugin connection to that endpoint; only that
separate distribution should advertise `Write`.

## Validate

```text
python <plugin-creator>/scripts/validate_plugin.py plugins/convoy
python <skill-creator>/scripts/quick_validate.py plugins/convoy/skills/convoy
python -m unittest test.demo.openai_plugin_pack_test -v
```

Public directory submission is a separate publisher action. Do not add an
`.app.json` until OpenAI issues a real connector ID, and do not publish privacy
or terms URLs until Deploy Forward has approved those policies.
