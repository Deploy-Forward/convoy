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
