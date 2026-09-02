# Targeted neuron launch contract

## User surface

```text
convoy choices
convoy join --to <harness> --worktree <path> --launch
convoy launch --seat <fresh-chair> [--dry-run]
```

`choices` is the memory-free discovery surface. It lists safe chair projections,
installed harness executables, registered/Git worktrees, and active terminal
capabilities. It never returns vendor resume tokens.

`join --launch` is explicit authorization to register and split exactly one new
chair. If terminal launch fails, registration remains pending. It never falls
back to root-wide `bring-up`, another terminal window, keyboard injection, or a
resume of an existing vendor session.

## Two independent adapters

Harness selection answers **what runs**. Terminal selection answers **where it
runs**. A terminal adapter receives one native harness argv and must create one
pane only.

| Adapter | Active-context proof | Create | Exact close today |
| --- | --- | --- | --- |
| Windows Terminal | Windows + `WT_SESSION` + `wt` | `wt -w 0 split-pane`; MRU window / active pane | No; WT CLI has no `closePane` command |
| tmux | `TMUX` + `TMUX_PANE` + `tmux` | `split-window -t <caller-pane>` | No; prototype does not yet capture the returned new pane id |
| Other hosts | none | Refuse | Refuse |

macOS and Linux are supported when the caller is inside tmux. Terminal.app,
iTerm2, WezTerm, kitty, and other hosts require explicit future adapters; a
model must not infer or simulate them.

## Chair and readiness state

```text
joined -> launch-claimed -> process-started -> vendor-gate? -> seated
                                      |                         |
                                      +-> launch-failed         +-> exited
```

- A chair is launchable only while it has a one-shot join/swap boot prompt and
  no vendor resume token.
- The launch claim is an atomic `O_EXCL` file. It persists after dispatch, so a
  second caller cannot create a second pane for the same chair. A terminal
  dispatch failure removes the claim for an explicit retry.
- `process-started` is not readiness. Only a token-authenticated `seated` event
  authored by the new chair closes the proof-of-life loop.
- Vendor gates remain vendor-specific. Live evidence showed Codex consuming the
  boot prompt immediately, while Grok required explicit project trust first.
  Convoy must never accept that decision for the user.

## Close is a separate definition of done

Process exit and pane exit are different facts. Windows Terminal may keep a
pane visible after an abnormal child exit and display `Ctrl+D or Enter to
restart`. Therefore:

- absent PIDs are insufficient close evidence;
- a chair can be `process_state=exited` while
  `pane_state=stale-awaiting-user-close`;
- Windows Terminal close remains manual until Convoy has an exact control
  protocol or a lifecycle host that can end the pane command successfully;
- tmux close becomes implementable only after launch captures and stores the
  new pane id (`split-window -P -F '#{pane_id}'`).

## Runtime and distribution

The source package requires Python 3.11+ and now exposes the `convoy` console
entry point through `pyproject.toml`. A skill can invoke the console command
without choosing PowerShell versus Bash, but it cannot assume Python exists.
A stranger-machine release must either verify/install the supported Python
runtime or ship a self-contained executable. “The model figures it out” is not
an installation or portability contract.

## Definition of done

For each supported terminal adapter and at least two different harnesses:

1. `choices` discovers the real harness executable, worktree, and terminal
   capability without exposing resume credentials.
2. One invocation creates one chair, one pane, one native harness process, and
   one distinct worktree; caller PIDs remain alive.
3. Repeating launch for that chair opens zero additional panes.
4. The new chair emits its own `seated` event.
5. Vendor authorization gates are surfaced and never silently bypassed.
6. Close evidence separately proves process exit and pane disappearance.
7. Unit, live-local, and clean stranger-machine evidence are all recorded.

The dated live evidence is in
`docs/audits/TARGETED_LAUNCH_LIVE_2026-09-02.md`.
