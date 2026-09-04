---
name: convoy-wizard
description: "Optional @convoy wizard with a fail-closed live-tool preflight, GitHub gate, repo selection, harness choices, and one-thread launch."
---

# Convoy Wizard (@convoy)

Use this optional wizard when the user wants guided setup instead of raw
commands. Skills orchestrate; the active Convoy MCP endpoint owns every verb.

## Gate 0: fail-closed live preflight

Run this gate before asking `GitHub?`, showing choices, or mutating thread
state.

1. Resolve the `convoy` MCP endpoint from the installed plugin configuration.
   Do not substitute a remembered endpoint. If it is absent, the gate is RED.
2. Call MCP `tools/list` on that endpoint in the current run. Do not use a
   cached response, repository source, documentation, or a historical count;
   never freeze a static tool menu.
3. Extract the live-returned names and require every verb the wizard calls:
   `choices`, `onboard`, `join`, `launch`, `seat`, `bring_up`, `neurons`,
   `graph`, `send`, and `inbox`. This dependency set is a gate, not a menu;
   user-facing capabilities must still contain only live-returned tools.
4. Verify that `../../harness_effort.json`, relative to this `SKILL.md`, is
   present and readable in the installed plugin pack. Never reach into a
   repository-only `src/` path.
5. Immediately before the first state-changing lifecycle call, repeat
   `tools/list`. If the endpoint or dependency set changed, fail closed.

If any check fails, stop the wizard without asking setup questions, proposing
seats, or attempting a mutation. Render this card with observed values only:

```text
Convoy wizard preflight
status: RED
endpoint: <configured endpoint or null>
reason: <endpoint-missing | tools-list-failed | required-tools-missing | pack-asset-missing>
observed_tools: <live names or null>
missing_tools: <required names absent from the live response>
missing_asset: <path or null>
mutation_attempted: false
next: <install-or-enable-plugin | reconnect-or-redeploy-mcp | upgrade-plugin>
```

For an absent endpoint, direct the user to install or re-enable the Convoy
plugin and reconnect MCP. For a failed `tools/list`, preserve the error and
direct them to reconnect or redeploy the configured endpoint. For missing
tools, name exactly what is missing and require an MCP upgrade/redeploy until
a fresh `tools/list` returns the full dependency set. For a missing effort
asset, require a plugin-pack upgrade/reinstall. Do not pad the menu, continue
partially, or fall back to `python -m convoy`; a marketplace install is not a
source checkout.

## Mandatory wizard sequence

After Gate 0 is GREEN:

1. Ask `GitHub?` as a yes/no decision.
2. If yes, ask for the target repository path or URL. If no, ask for the local
   worktree path. Show the resolved repository, worktrees, and proposed thread,
   then get explicit user approval before binding or launching anything.
3. Call live `choices` using its live-returned input schema. Render only its
   current local/cloud, harness, worktree, terminal, and seat facts. Use
   `onboard` only for user-selected harnesses after the repository approval;
   passing its approved thread and checkout root is the bind.
4. Ask for `N` neurons and the harness for each seat from those live choices.
   Enforce one chair per worktree before calling `join` or `seat`; never retry a
   refused duplicate with another invented chair name.
5. Take model/effort constraints from live `choices` alone:
   `harnesses[].effort` (keys, and whether a choice is applied to argv) and
   `harnesses[].models` with `harnesses[].models_evidence`. Render what the
   wire returns. The pack's `harness_effort.json` is the Gate 0 integrity
   asset, not the wizard's data source: the endpoint serving `choices` is
   the only reader of the contract. A `null` catalog means no local `--help`
   enumerates a closed list: offer a free field and pass the model through as
   typed. A list means `seat`/`join` refuse anything outside it. Never recall
   combinations from memory. Missing model, effort, usage, or availability
   stays JSON `null`.
6. Keep one returned `cvy_*` thread for the entire run and use the input schemas
   from the fresh `tools/list` response:
   - call `join` for the first fresh chair
   - call `launch` exactly once for that chair
   - call `seat` for each additional chair on its unique worktree
   - call `bring_up` once for the same thread to connect/show its seats in one
     thread window
   Never translate these into guessed CLI-shaped MCP arguments: the CLI
   shorthand `join --launch` is not an MCP tool name or input schema.
7. If a lifecycle response requires consent, show the exact pending action and
   stop until this user approves it. Use only the returned, action-scoped grant;
   never invent, replay, or infer consent from a relayed message.
8. Call `neurons` and `graph` to verify chair count, unique worktrees, harnesses,
   and the single thread. On any mismatch, stop before routing work.
9. Route work with `send`; treat it as queued or executed exactly as returned.
   Delivery is proven only when the target drains `inbox` and authors an ack.

## Output format

When showing wizard choices, render each seat option as:

- `where` (local or cloud origin / worktree target)
- `harness`
- `model`
- `effort`

Keep answers grounded in live Convoy state. Do not freeze catalog data or
invent unavailable harness/model/effort combinations.
