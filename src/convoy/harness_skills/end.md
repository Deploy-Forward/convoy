---
description: End the current Convoy task; optionally push only when --push is supplied
argument_hint: [--summary "one line"] [--push]
---

Run `convoy end $ARGUMENTS` from the current worktree and return its JSON card.
Preserve the raw arguments. Never add `--push`, commit, stage, set an upstream,
force-push, or choose another remote. A successful heartbeat is not proof of a
push; only report a push when the card says `push_status: pushed`.
