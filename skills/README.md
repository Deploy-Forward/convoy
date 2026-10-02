# Convoy skills

Skills are neuron-side instruction files. Convoy agent guidance lives in the
Convoy plugin (`convoy@deploy-forward`): `convoy-operate` (first turn,
identity via `convoy whoami`, how to work on a thread), `convoy-listen`
(receive: wait, drain the inbox, acknowledge with a note citing the token)
and `convoy-send` (send one neuron a message and prove it arrived). Claude
Code and Codex install the convoy plugin from the deploy-forward marketplace
(Claude Code: `claude plugin install convoy@deploy-forward`). Grok and
Cursor get rendered copies when the person runs the plugin's installer
(`node plugin/install.mjs --apply`). agy, hermes and pi have none yet: run
`convoy --root <root> whoami` and the receive loop in `convoy-listen`. The
older `neuron-identity` and `neuron-receive` skills are retired (2026-09-28).

## How a skill reaches a neuron

At first run (`ensure_first_run`), `identity.install_neuron_identity` writes
an `AGENTS.md` pointer block naming the three plugin skills and removes any
retired `neuron-identity` / `neuron-receive` copy Convoy wrote before. It still
copies `convoy-end` to the places each harness reads:

| Harness | Where it lands | Auto-load verified? |
| --- | --- | --- |
| `claude` | `<worktree>/.claude/skills/convoy-end/SKILL.md` | n/a (native skills dir, not AGENTS.md) |
| `grok` | `<worktree>/.grok/skills/convoy-end/SKILL.md` | n/a (native skills dir, not AGENTS.md) |
| `codex` | `<worktree>/.agents/skills/convoy-end/SKILL.md` | n/a (native skills dir, not AGENTS.md) |
| all | `<worktree>/AGENTS.md` pointer to the plugin skills | `codex`: yes. `cursor-agent`: unverified. `agy`, `hermes`, `pi`: unverified. |

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

- `convoy-nudge/` — lead-side recovery for a deaf pane: detect from the tape, relaunch dead chairs scoped, or wake an idle pane with a title-verified keystroke (`scripts/wt-nudge.ps1`); live-proven 2026-09-05
- `convoy/` — the canonical `/convoy` slash sheet: what each public MCP tool
  does, what is live vs tree-only, and where the CLI is the primary surface.
