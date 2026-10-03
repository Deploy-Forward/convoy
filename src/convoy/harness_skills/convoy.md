---
description: Run a Convoy command against the current thread and report its JSON card
argument_hint: <convoy arguments>
---

Run the Convoy CLI from the current repository using the raw arguments below.
Prefer `convoy` when it is on PATH; otherwise use `python -m convoy`.

Raw slash-command arguments:
`$ARGUMENTS`

Preserve the arguments exactly. Use the current checkout/thread root unless the
arguments explicitly provide `--root`. Return the command's JSON card. Do not
invent convoy IDs, seat IDs, session IDs, usage, or delivery acknowledgements.

`start` accepts a path, URL, owner/repo or name and reuses an existing matching
checkout before cloning. Show `list` output verbatim; map a person's displayed
pick to its exact cvy_ id for `attach <cvy_id|exact thread name>`. Attach links
this proven native session without launching; detach preserves its handoff,
chair and pending rows, stops wakes and closes no pane.

Use `send`, not a plain addressed `hook note`, to reach a neuron. Delivery values
include recorded, queued, native-queued, executed, refused and error; only the
target's own proven token-citing receipt establishes delivery.

Wake dispatch is off until `wake enable` on a root; inspect `wake status` and
opt out with `wake disable`. Enabled waiter routes are dispatcher-managed and
require a session-owned background waiter, not a hook-owned detached waiter.

First run can write the thread index, ~/.bashrc, ~/.claude/settings.json,
~/.claude.json and the Codex prompt under CODEX_HOME/prompts (default ~/.codex).
Live launches may also prepare the harness-specific hook trust stores named by
their card. Dry-run refuses the repo-file opt-in but is not universally read-only.
