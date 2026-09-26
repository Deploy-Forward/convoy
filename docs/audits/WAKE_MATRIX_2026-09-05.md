# Wake matrix (2026-09-05)

Wake-path evidence for the idle-chair nudge. Evidence only. Command / observed / ts
also live in `src/convoy/nudge.py` `WAKE_EVIDENCE`.

| command | ts | observed |
| --- | --- | --- |
| `grok --help` | 2026-09-05T06:03:21Z | no `queue`; `leader`, `agent` (stdio/headless/serve/leader), `--resume`, `-p`/`-c`. `grok help queue` = unrecognized subcommand. |
| `grok leader list` | 2026-09-05T06:03:21Z | "No leader candidates found." `~/.grok/leader.sock` missing. |
| `grok agent --help` | 2026-09-05T06:03:21Z | `--leader` / `--no-leader`. Live TUI `session/prompt` needs a leader; `--no-leader` against a pid-held TUI is a steal. |
| `~/.grok/active_sessions.json` | 2026-09-05T06:03:21Z | grok-a `<session id>` cwd=<grok-a worktree> pid <pid>; grok-b `<session id>` cwd=<grok-b worktree> pid <pid>. |
| WT `CASCADIA_HOSTING_WINDOW_CLASS` titles | 2026-09-05T06:03:21Z | 3 windows, one WT process. Unique worktree title: `<checkout>-wt-codex-b`. grok-b's title is the user prompt, not the worktree / seat title. Idle title `grok` is generic. |
| `codex queue --help` | 2026-09-05T06:03:21Z | `--thread <UUID or exact session name> --message <TEXT>`. |
| `codex queue --thread 00000000-0000-0000-0000-000000000000 --message convoy-wake-matrix-probe` | 2026-09-05T06:07:27Z | rc 1; `no rollout found for thread id` (code -32603). Seats have `resume=null`. |
| conductor-session keystroke (cited) | 2026-09-05T05:57-06:00Z | title-verified SendInput woke idle grok (grok-a drained its rows). Alt+Arrow without a title re-check hit the wrong pane. |

Live dry-run 2026-09-05T06:17Z: `nudge --seat grok-b --dry-run` first
returned `identified: true` because the WT title contained the tool
description "Dry-run nudge identity for grok-b". Short seat titles are not
substring identity. After the fix, grok-a/grok-b refuse (prompt title);
codex-a/codex-b refuse (codex bodies unplaced). That refuse is the product.

Not fired this turn: SendInput into any live pane (this grok was working, not
idle; codex-b is another chair). ACP `session/prompt` (no leader). `codex queue`
at a live session (no vendor id on the seat).

`nudge --seat` from this evidence: write gate + `nudge-pane` consent that names
the pane and the exact keys + proven identity (panes body + unique title or
tmux target). `delivery: nudged`, never `delivered`. No Alt+Arrow.
