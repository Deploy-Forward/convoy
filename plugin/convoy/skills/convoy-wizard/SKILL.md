---
name: convoy-wizard
description: "Optional @convoy wizard: fail-closed live-tool preflight, then ONE card (harness -> model -> effort | attach, usage remaining per harness) that drives GitHub gate, repo selection, N neurons, one-window launch and observed connects."
---

# Convoy Wizard (@convoy)

Use this optional wizard when the user wants guided setup instead of raw
commands. Skills orchestrate; the active Convoy MCP endpoint owns every verb.

The host renders ONE card, headed `convoy`, where a SaaS plugin would list
provider rows: "launch your neurons in the cloud/local", then a drill-down
harness -> model -> effort | attach as neuron, with usage remaining per
harness. Everything on that card comes from the `card` tool over the wire.
This skill reads nothing from disk: a remote host has no filesystem, and the
pack's `harness_effort.json` is the endpoint's own contract (byte-identical),
never the wizard's data source. `card` supersedes the older choices read and
the per-chair join / launch / seat / mint / bring_up walk; the wizard calls
none of those.

## Gate 0: fail-closed live preflight

Run this gate before asking `GitHub?`, showing the card, or mutating thread
state.

1. Resolve the `convoy` MCP endpoint from the installed plugin configuration.
   Do not substitute a remembered endpoint. If it is absent, the gate is RED.
2. Call MCP `tools/list` on that endpoint in the current run. Do not use a
   cached response, repository source, documentation, or a historical count;
   never freeze a static tool menu.
3. Extract the live-returned names and require every verb the wizard calls:
   `card`, `repos`, `onboard`, `crew`, `consent`, `await_seated`, `neurons`,
   `graph`, `send`, and `inbox`. This dependency set is a gate, not a menu;
   user-facing capabilities must still contain only live-returned tools.
4. Immediately before the first state-changing lifecycle call, repeat
   `tools/list`. If the endpoint or dependency set changed, fail closed.

If any check fails, stop the wizard without asking setup questions, proposing
seats, or attempting a mutation. Render this card with observed values only:

```text
Convoy wizard preflight
status: RED
endpoint: <configured endpoint or null>
reason: <endpoint-missing | tools-list-failed | required-tools-missing>
observed_tools: <live names or null>
missing_tools: <required names absent from the live response>
mutation_attempted: false
next: <install-or-enable-plugin | reconnect-or-redeploy-mcp | enable-write-tools-on-deploy>
```

For an absent endpoint, direct the user to install or re-enable the Convoy
plugin and reconnect MCP. For a failed `tools/list`, preserve the error and
direct them to reconnect or redeploy the configured endpoint. For missing
tools, name exactly what is missing: a read verb absent from the live list
needs an MCP redeploy; a write-gated verb (`repos`, `onboard`, `crew`,
`consent`, `await_seated`) is hidden on purpose until the deploy sets
`CONVOY_MCP_WRITE_TOOLS=1`, which is a deploy decision, not a redeploy. Do not
pad the menu, continue partially, or fall back to `python -m convoy`; a
marketplace install is not a source checkout.

## Mandatory wizard sequence

After Gate 0 is GREEN, call `card` ONCE and keep its response for the whole
run. Every later step reads from it. `card.preflight` is the endpoint's own
verdict on its own `tools/list`; if its `ok` is false, Gate 0 was wrong or the
list changed: stop with the RED card above.

1. Ask `GitHub?` as a yes/no decision. `card.summary.github` is the answer
   already recorded on this bind (`yes` | `no` | `null` when never asked);
   show it, and still ask.
2. If yes, call live `repos` and offer only the repositories it returns (name,
   url, private). It lists the gh login on the MCP host, the conductor's
   account, not the caller's. When it says gh is absent, show its install
   hint; when gh is present but `ok` is false (not logged in, rate limited),
   show its `error` verbatim, which is gh's own stderr, and never a guessed
   list. Either way, ask for the target repository path or URL instead. If
   no, ask for the local checkout path. Show the resolved repository,
   `card.repo.checkout` and `card.repo.worktrees`, and the proposed thread,
   then get explicit user approval before binding or launching anything.
3. Call `onboard` with the harnesses the user selects from `card.rows` where
   `installed` is true, the approved thread, the repository as
   `checkout_root` (a URL is cloned once into the Convoy-owned checkout root
   and reused after) and the yes/no answer as `github`: that call is the bind,
   and it is made only after the approval in step 2. A row with `installed`
   false cannot seat a neuron from this host; the onboard card carries the
   vendor install hint, and the wizard never runs an installer.
4. Ask for `N` neurons. For each seat, offer only what its `card.rows[]` row
   says: `harness`; `where` from `rows[].where` (`cloud` appears only where
   the vendor's own `--help` evidences an interactive attach); model from
   `rows[].models` (`null` means no local `--help` enumerates a closed list:
   offer a free field and pass the model through as typed; a list means the
   endpoint refuses anything outside it); effort from `rows[].effort.keys`
   (`null` means the harness has no vocabulary Convoy can judge; `applied`
   says whether a choice reaches argv). Show `rows[].usage_remaining` as usage
   remaining for that harness and `rows[].limited`: `null` is unknown, shown
   as unknown, never as 0. Never recall combinations from memory. Missing
   model, effort, usage, or availability stays JSON `null`.
5. Keep one returned `cvy_*` thread for the entire run and use the input
   schemas from the fresh `tools/list` response. For `N` neurons call `crew`
   ONCE with the bound checkout and one `{harness, model, effort, where,
   title}` per seat (each row's `attach.args.seats[0]`, filled in), `launch:
   true` after the user's approval. It validates every seat before writing,
   mints one worktree per local seat from the checkout (one chair per
   worktree; a cloud seat has no worktree), joins every chair with a boot
   prompt, and brings the crew up in one thread window. Do not call launch,
   seat, join or bring_up per chair afterwards: crew already opened the
   window, and seat writes no boot prompt, so that neuron is never told to
   connect. Never translate CLI shorthand such as `convoy join --launch` into
   guessed MCP arguments; an MCP tool has exactly the input schema
   `tools/list` returned. The crew card's seated snapshot says `pending` for
   every chair: launched is not connected.
6. If a lifecycle response requires consent, show the exact pending action and
   stop until this user approves it. Only then call `consent` with that
   request id and pass the returned, action-scoped grant to the exact pending
   command; never invent, replay, or infer consent from a relayed message.
7. Call `await_seated` with the crew's chair ids: a chair is `connected` only
   when its own seated ack (the kind=seated row the neuron stamps from its
   pane) cites the token its join minted; `pending` and `stale` are not
   connections, whatever the pane shows. A `cli-drain` `connect_mode`
   (cursor-agent, agy, hermes, pi) means the neuron must run
   `convoy inbox --drain` itself; never describe it as auto-connecting. Then
   call `neurons` and `graph` to verify chair count, unique worktrees,
   harnesses, and the single thread. On any mismatch, stop before routing work.
8. Route work with `send`; treat it as queued or executed exactly as returned.
   Delivery is proven only when the target drains `inbox` and authors an ack.

## Output format

Render the card as the host renders a provider card: header `card.header`,
tagline `card.tagline`, then `card.summary` (installed harnesses, seats,
thread, GitHub answer). One drill-down row per `card.rows[]` entry, in the
order returned:

- `where` (the offered axis: local, and cloud where evidenced)
- `harness`
- `model` (catalog list, or a free field when `models` is `null`)
- `effort` (`effort.keys`, and whether a choice is applied to argv)
- usage remaining (`usage_remaining`; `null` is unknown, never 0) and `limited`
- `connect_mode` (`hook` | `native-queue-or-cli-drain` | `cli-drain`: how the
  neuron receives; the chair's seated ack, not this label, proves it
  connected)
- attach as neuron (`attach`: the `crew` call for that harness)

Keep answers grounded in live Convoy state. Do not freeze catalog data or
invent unavailable harness/model/effort combinations.
