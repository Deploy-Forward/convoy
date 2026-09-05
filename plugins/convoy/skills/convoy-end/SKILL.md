---
name: convoy-end
description: Record the current Convoy task's final heartbeat and, only when explicitly requested, push the current clean branch to its configured upstream. Use when the user asks to end, close out, or finalize a Convoy task, especially with --push.
metadata:
  installation-consent: Installing enables a reviewed Codex or Claude Stop hook to append a token-free turn heartbeat to the active worktree's Convoy thread. It never authorizes git push.
  permission-model: Only the literal user-invoked --push flag authorizes one plain git push of a clean attached branch to its configured upstream.
---

# End a Convoy task

This skill is an explicit completion action. Never invoke it implicitly when
the user merely says that a substep is done.

Run the portable CLI from the current worktree:

```text
convoy end [--summary "one line"] [--push]
```

- Preserve `--push` only when the user supplied it in this invocation.
- Never add `--push` on the user's behalf and never turn an automatic
  heartbeat into push authorization.
- Do not commit, stage, set an upstream, force-push, or select a different
  remote. `convoy end --push` permits exactly one plain `git push` after the
  command verifies a clean attached branch with an existing upstream.
- Treat `push_status: pushed` as proof of push. A heartbeat row by itself is
  not proof that git changed remotely.
- If identity is ambiguous, the worktree is dirty, HEAD is detached, or no
  upstream exists, report the refusal and leave git unchanged.

Codex's native invocation is `$convoy-end --push`; there is no supported
arbitrary `/end` extension point. Claude receives a project command at
`.claude/commands/end.md`, so `/end
--push` is available there after the command is installed/reloaded.

The Codex and Claude `Stop` hooks use `convoy end --hook`. That automatic path
records a turn-end heartbeat only, emits no transcript or vendor identifiers,
and can never push.
