---
description: End a Convoy task. Bare form ends this pane's lane; --seat <chair> ends one neuron's lane; --all runs the orchestra with a handoff .md and .json. Push only when --push is supplied.
argument-hint: [--push] [--seat <chair> | --all] [--summary "one line"]
---

Run `{{CONVOY}} end $ARGUMENTS` from the current worktree and return its JSON card.

Forms, all from the lead or a seat:
- `{{CONVOY}} end [--summary "..."] [--push]` this pane's own lane.
- `{{CONVOY}} end --push --seat <chair>` one neuron's lane, from its worktree.
- `{{CONVOY}} end --push --all` every live chair ends and pushes its own lane; the card names `handoff_md` and `handoff_json` under `.convoy/handoff/`.

Preserve the raw arguments. Never add `--push`, commit, stage, set an upstream, force-push, or choose another remote. A task-end row is not proof of a push; report a push only where the card says `push_status: pushed`, per lane. A refused lane names its reason (dirty, detached, no upstream); the fix is that seat's, not yours.
