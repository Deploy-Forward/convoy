# Convoy skills

Skills are neuron-side instruction files. Convoy installs them into each seat
worktree at first run (`ensure_first_run`), so a freshly launched model knows
what it is and how to behave on the thread — before its first turn.

## How a skill reaches a neuron

Per harness, `identity.install_neuron_identity` writes the same text to the
places each harness reads:

| Harness | Where it lands | Auto-load verified? |
| --- | --- | --- |
| `claude` | `<worktree>/.claude/skills/<name>/SKILL.md` | n/a (native skills dir, not AGENTS.md) |
| `grok` | `<worktree>/.grok/skills/<name>/SKILL.md` | n/a (native skills dir, not AGENTS.md) |
| all | `<worktree>/AGENTS.md` pointer naming both paths | `codex`: yes. `cursor-agent`: unverified. `agy`, `hermes`, `pi`: unverified. |

Whether or not a harness auto-loads `AGENTS.md`, the boot prompt Convoy
passes at launch names the `SKILL.md` path directly, so a neuron reads it
regardless.

## Canonical vs packaged copies

This folder is the **canonical public home**. The installed Python package
ships its own copy under `src/convoy/harness_skills/` — that copy is what
`identity.py` resolves at runtime (a top-level folder cannot be an importable
package resource without claiming the generic `skills` namespace, which a
public package must not do). A test (`test/demo/skills_folder_test.py`)
asserts the two copies are byte-identical: edit one without the other and the
suite goes red.

## Codex native slash prompt

Codex's native composer does not turn a repository `skills/` folder into a bare
slash command. The installer also writes `$CODEX_HOME/prompts/convoy.md`;
invoke it as `/prompts:convoy` after starting a new Codex session. This is the
Codex custom-prompt namespace, not a second Convoy identity skill.

## Skills

- `neuron-receive/` — how a neuron on ANY harness receives from the thread
  (feed rows addressed to it, its inbox file), which hook drains for it at
  tool time (grok, claude) and which harnesses must run the loop by hand
  (codex, cursor-agent, agy, hermes, pi), and the one rule that makes a
  message delivered: the receiver's own ack row. Installed beside
  `neuron-identity`; named in `AGENTS.md`.

- `neuron-identity/` — who a neuron is: one BYO harness session on a
  `cvy_` thread, not the conductor. Installed into every seat worktree.
- `convoy/` — the canonical `/convoy` slash sheet: what each public MCP tool
  does, what is live vs tree-only, and where the CLI is the primary surface.
