---
name: convoy-wizard
description: "Optional @convoy wizard: GitHub gate, repo selection, harness choices, neurons, model/effort, and one-thread launch."
---

# Convoy Wizard (@convoy)

Use this optional wizard when the user wants guided setup instead of raw
commands.

## Mandatory wizard sequence

1. Ask `GitHub?` as a yes/no decision.
2. If yes, ask for the target repository path or URL to anchor the worktree.
3. Resolve the live tool menu first:
   - call MCP `tools/list` on the active Convoy endpoint
   - render only live-returned tools
   - never freeze a static tool menu or hardcode historical counts
4. Query live choices/roster state before proposing seats:
   - `choices` for harness/worktree/terminal availability
   - `onboard` if selected harnesses are not yet registered
5. Ask for `N` neurons (seat count) and selected harness(es) from live choices.
6. Read `src/convoy/harness_effort.json` to constrain model/effort per harness.
7. Keep one `cvy_*` thread for the run and launch exactly one thread window:
   - launch the first seat with `join --launch`
   - register any additional seats with `seat`
   - use `bring_up` (or `open`) to connect/show remaining seats on the same
     thread
8. Confirm topology with `graph`, then hand off work routing via `send` and
   receiver acks via `inbox`.

## Output format

When showing wizard choices, render each seat option as:

- `where` (local or cloud origin / worktree target)
- `harness`
- `model`
- `effort`

Keep answers grounded in live Convoy state. Do not freeze catalog data or
invent unavailable harness/model/effort combinations.
