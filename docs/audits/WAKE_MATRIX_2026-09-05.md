# Wake matrix (g2-happy-path, 2026-09-05)

Slice 5b of `docs/briefs/WIDGET.md`. Evidence only. Command / observed / ts
also live in `src/convoy/nudge.py` `WAKE_EVIDENCE`.

| command | ts | observed |
| --- | --- | --- |
| `grok --help` | 2026-09-05T06:03:21Z | no `queue`; `leader`, `agent` (stdio/headless/serve/leader), `--resume`, `-p`/`-c`. `grok help queue` = unrecognized subcommand. |
| `grok leader list` | 2026-09-05T06:03:21Z | "No leader candidates found." `~/.grok/leader.sock` missing. |
| `grok agent --help` | 2026-09-05T06:03:21Z | `--leader` / `--no-leader`. Live TUI `session/prompt` needs a leader; `--no-leader` against a pid-held TUI is a steal. |
| `~/.grok/active_sessions.json` | 2026-09-05T06:03:21Z | g1 `01a07024-1b5f-7350-9727-c11c25faeb70` cwd=wt-g1 pid 59824; g2 `01a07026-97ec-7621-bdd2-f60141e7a84a` cwd=wt-g2 pid 101288. |
| WT `CASCADIA_HOSTING_WINDOW_CLASS` titles | 2026-09-05T06:03:21Z | 3 windows, WT pid 99004. Unique worktree title: `convoy-wt-happy-wt-luna2`. g2 title is the user prompt, not the worktree / seat title. Idle title `grok` is generic. |
| `codex queue --help` | 2026-09-05T06:03:21Z | `--thread <UUID or exact session name> --message <TEXT>`. |
| `codex queue --thread 00000000-0000-0000-0000-000000000000 --message convoy-wake-matrix-probe` | 2026-09-05T06:07:27Z | rc 1; `no rollout found for thread id` (code -32603). Seats have `resume=null`. |
| Fable keystroke (cited) | 2026-09-05T05:57-06:00Z | title-verified SendInput woke idle grok (g1 drained 4 rows). Alt+Arrow without a title re-check hit the wrong pane. |

Live dry-run 2026-09-05T06:17Z: `nudge --seat g2-happy-path --dry-run` first
returned `identified: true` because the WT title contained the tool
description "Dry-run nudge identity for g2". Short seat titles are not
substring identity. After the fix, g1/g2 refuse (prompt title); luna1/luna2
refuse (codex bodies unplaced). That refuse is the product.

Not fired this turn: SendInput into any live pane (this grok was working, not
idle; luna2 is another chair). ACP `session/prompt` (no leader). `codex queue`
at a live session (no vendor id on the seat).

`nudge --seat` from this evidence: write gate + `nudge-pane` consent that names
the pane and the exact keys + proven identity (panes body + unique title or
tmux target). `delivery: nudged`, never `delivered`. No Alt+Arrow.
