---
name: convoy
description: Coordinate multiple AI coding harnesses on one Convoy thread using only the configured Convoy MCP server's live capabilities. Use for guided setup, neuron discovery, crew launch, routing, and acknowledgement checks.
metadata:
  installation-consent: Installing this plugin authorizes its declared Convoy MCP connection and use of currently exposed tools for the active conversation. It does not authorize session theft, keystroke injection, vendor trust bypass, or hidden host writes.
  permission-model: Read capabilities may run after installation. Lifecycle writes remain limited by the endpoint's write gate and any exact action consent returned by Convoy.
---

# Convoy

Use the configured `convoy` MCP server to orchestrate a durable thread of AI
coding agents (neurons). The MCP server owns the tool contract; this skill does
not wrap vendor CLIs or infer capabilities from repository files.

## Installation permission boundary

Installing Convoy is the user's grant to connect the MCP server declared by
this plugin and invoke tools that server currently exposes. The user can revoke
that grant by disabling or uninstalling the plugin.

That grant is not permission to steal or resume an occupied TUI, inject
keystrokes, accept a vendor trust prompt, bypass a write gate, or operate on a
different checkout. If Convoy returns an action-scoped consent request, show
the exact action and wait for the user's approval before calling `consent`.

## Live-capability gate

Before presenting capabilities or starting a workflow:

1. Inspect the live tools exposed by the configured `convoy` MCP server.
2. Use only tools present in that response. Never hardcode a tool count or
   recreate a missing tool with shell commands.
3. Preserve unknown state as JSON `null`. Never invent chair, thread, token,
   process, model, effort, usage, or delivery values.
4. Immediately before the first lifecycle write, refresh the live tool list.
   If a required tool disappeared, stop without mutation and name it.

The public endpoint can intentionally hide lifecycle tools. A missing write
tool is unavailable in this connection; do not tell the user that an action
ran, and do not fall back to a local checkout.

## Guided setup

When the user asks to create or expand a Convoy:

1. Require these live tools for the guided flow: `card`, `repos`, `clone`,
   `onboard`, `crew`, `consent`, `await_seated`, `neurons`, `graph`, `send`,
   and `inbox`. If any are absent, stop with a fail-closed preflight card that
   includes the configured endpoint, observed tools, missing tools, and
   `mutation_attempted: false`.
2. Call `card` once. Offer only installed harnesses and the `where`, model,
   effort, availability, and usage values it returns.
3. Ask whether to use GitHub. If yes, offer only repositories returned by
   `repos`; if no, ask for the local checkout. Show the resolved checkout and
   proposed thread, then get approval before binding or launching.
4. Call `onboard` for the approved root and chosen installed harnesses. The MCP
   endpoint is bound to one root; if it refuses another root, tell the user to
   attach an endpoint for that root instead of substituting one.
5. Ask for the number of neurons. Call `crew` once with one seat specification
   per neuron and `launch: true` only after approval. One local chair must have
   one worktree. Do not repeat per-chair launch, join, or pane commands.
6. If a response requires consent, pause at the exact returned action. After
   approval, pass the one-time grant only to that action.
7. Call `await_seated`, then `neurons` and `graph`. A launched pane is not a
   connected neuron until its own seated acknowledgement is observed.
8. Route work with `send`. Treat `queued`, `executed`, `refused`, and
   `delivered` exactly as returned. Delivery is complete only after the target
   neuron drains its inbox and authors an acknowledgement.

## Existing threads

For status and routing on an existing thread, start with `card`, `neurons`, and
`graph`. Use `send` for work and `inbox` for receipt state. Distinguish:

- active, positively matched neuron;
- inactive, when no harness process exists;
- unknown, when harness processes exist but cannot be mapped safely.

Never collapse unknown liveness into inactive or infer ownership from a PID or
shared working directory alone.

## Output

Prefer one compact Convoy card with the thread, root, chairs, harnesses,
worktrees, liveness reason, connection state, usage (including `null`), and the
next exact action. Report a lifecycle action as complete only when the returned
card and the target-authored acknowledgement prove it.
