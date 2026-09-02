# Targeted one-chair launch: live evidence (2026-09-02)

Status: **Codex launch/seated PASS; Windows Terminal close RED**. Grok launch
reached a vendor trust gate and is pending explicit user consent. One-time
seated tokens are intentionally excluded from this document.

## Implementation lineage

- Repository: `Deploy-Forward/convoy`
- Feature worktree: `C:\Users\marco\ola\convoy-wt-targeted-launch`
- Branch: `feat/targeted-neuron-launch`
- Base: `8dd8644eb5fa0ec3b0e2ca0cf410ddc5bcd976f4`
- Thread root: `C:\Users\marco\ola\fable-opus-root`
- Caller chair: `codex-fable-opus`
- Caller worktree: `C:\Users\marco\ola\convoy-wt-fable`
- Caller Codex process: PID `14556`

The feature separates harness argv construction from terminal placement. The
live path used the `windows-terminal` adapter; no shell, keyboard injection,
vendor resume token, or root-wide `bring-up` was used.

## Codex proof

Safe command shape (the CLI minted the chair identity):

```text
python -m convoy --root C:\Users\marco\ola\fable-opus-root join \
  --to codex \
  --worktree C:\Users\marco\ola\convoy-wt-pane-proof \
  --title pane-proof \
  --launch
```

Observed lineage:

| Stage | Evidence |
| --- | --- |
| Separate checkout | Detached worktree `C:\Users\marco\ola\convoy-wt-pane-proof` at `8dd8644` |
| Chair registration | CLI returned `pane-proof-fable-opus` |
| Terminal dispatch | `windows-terminal`, target `most-recent-window`, semantics `mru-window-active-pane`; WT launcher PID `121100` |
| Harness process | New Codex PID `120120`, while caller PID `14556` remained alive |
| Vendor TUI identity | Verified session metadata `01a06401-6d65-72f1-9b1d-55b6548029db`, originator `codex-tui`, source `cli`, cwd exactly the proof worktree |
| Join event | `2026-09-02T21:23:28.869555Z` |
| Independent proof of life | `seated pane-proof-fable-opus` authored by that chair at `2026-09-02T21:24:09.772045Z` |

This proves two concurrent Codex neurons with distinct processes, worktrees,
chair identities, and vendor TUI sessions. The new chair read the shared thread
through an absolute pointer; it did not expect `thread.md` to exist in its own
checkout.

## Safety properties exercised

- `join --launch` selected only the chair returned by that invocation.
- Only fresh join/swap chairs are eligible; any vendor resume token is refused.
- An atomic, persistent launch claim prevents a second launcher from opening a
  duplicate pane for the same chair.
- The existing caller process remained alive.
- `convoy choices` reported terminal capability, installed harnesses, known
  worktrees, and safe seat projections without exposing resume tokens.
- Windows Terminal targeting is honestly recorded as MRU-window active pane,
  not as an exact Windows Terminal window identifier.

## Close lineage: process PASS is not pane PASS

At `2026-09-02T21:27:58.235169Z` the process-level close check passed:

- Re-resolved PID `120120` as `codex.exe`, whose immediate wrapper was
  `node.exe` PID `31832`.
- Stopped only PID `120120`; its wrapper then exited.
- Verified PID `120120` absent, wrapper PID `31832` absent, and caller Codex PID
  `14556` still alive.
- Field-preservingly recorded the verified vendor TUI session id,
  `resume_for=codex`, `launch_state=exited`, and the close timestamp on chair
  `pane-proof-fable-opus`. No vendor id was guessed, and it was not recorded
  until the process was no longer live.

Visual verification then disproved the pane-level conclusion. Windows Terminal
retained the split and displayed the non-zero process exit (`0xffffffff`) with
"Ctrl+D or Enter to restart". With the profile's graceful/automatic close
behavior, killing the child is therefore **not** a successful pane close.

Current result: **RED** until the exited proof pane itself disappears. The user
must press `Ctrl+D` in that exact pane. Windows Terminal's CLI exposes
`split-pane` and focus movement but not the `closePane` action; Convoy must not
inject a keystroke into an ambiguously targeted TUI. Future close DoD must
require visual/pane-topology evidence, not only absent PIDs.

## Cross-harness replication

Grok reached a useful intermediate state:

| Stage | Evidence |
| --- | --- |
| Separate checkout | Detached worktree `C:\Users\marco\ola\convoy-wt-pane-grok-proof` at `8dd8644` |
| Chair registration | `grok-pane-proof-fable-opus` at `2026-09-02T21:28:55.491609Z` |
| Terminal dispatch | Windows Terminal launcher PID `92068`; exactly one new split requested |
| Harness process | `grok.exe` PID `49172`, while caller Codex PID `14556` remained alive |
| Convoy preparation | `.grok/agents/convoy-neuron.md` and `.grok/skills/neuron-identity/SKILL.md` exist in the proof checkout |
| Vendor difference | Grok displayed its own repository trust confirmation before accepting the initial boot prompt; `grok inspect` independently reported `Project trusted: no` |
| Proof of life | Pending: no `seated` event while the trust dialog is open |

This is not a launch failure: terminal placement and native Grok startup both
succeeded. It is a first-run authorization gate that Convoy must surface and
leave to the user; it must not silently accept a security/trust prompt.

## Knowledge added to the product contract

The first live pass exposed two dimensions that unit-only launch tests miss:

1. **Create capability is not close capability.** `choices` now reports
   `can_close_exact=false` and an adapter-specific reason. The DoD must keep
   pane topology separate from process liveness.
2. **Harness start is not neuron readiness.** Codex consumed the positional
   boot prompt immediately; Grok first required project trust. The common state
   machine is `joined -> process-started -> vendor-gate? -> seated`, and only
   `seated` is cross-harness readiness.

For Windows Terminal, the next implementation decision is explicit: either
ship a lifecycle host that owns the child process and exits zero after an exact
close request, or retain manual close. Killing a child and inferring that its
pane vanished is forbidden. tmux can eventually capture the pane id returned
by `split-window -P -F '#{pane_id}'` and use that exact id for close; the current
prototype does not yet capture it and therefore also reports close as false.
