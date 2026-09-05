# Convoy widget: always-on-top strip over the terminal

Chair: g1-happy-path (grok), after its slices 1-6 landed (e933a15). Branch convoy/g1.
Data contract: docs/CONVOY_SOT.md. No store of its own, ever.

## Shape (Marco, 2026-09-05)

One small window, always-on-top by default with a toggle, stdlib tkinter only
(runs on Windows and macOS, zero new dependencies; public-repo rule).

Top strip: one dot per Convoy thread this machine knows, from the machine
index (`index.recent()`, g1 slice 1; never temp roots), newest first:
`·1 ·2 ·3`. Each dot IS its own thread: its own `.convoy/` and identity.
Selecting a dot expands that thread:

```
[repo connected? y/n]
   yes -> repo URL (from the bind: github=yes + clone record / git remote of the root)
          AND local root + thread key
   no  -> local root + thread key only (never a fake owner/repo)
[usage remaining by attached harness, % where the vendor gives one, "unknown" for null, never 0]
[one row per chair: harness | model | effort  (tunable: click -> the exact `seat`/`swap` command, never applied silently)]
[per chair: state chip from the seated acks (connected/pending/stale), live-body dot only when `panes` proves a process, worktree+branch, last feed row + ts, unread inbox]
[last stamp]
```

Clicking a chair row highlights it and calls `focus --seat <chair>`: a new
verb that returns `{focused: false, reason}` until a pane-host adapter is
evidenced. tmux: `select-pane -t` is provable now (test with a fake runner).
Windows Terminal: check `wt focus-pane` on this machine and record the
evidence in harness_effort.json-style notes before claiming it; if it cannot
target a pane, say so on the card.

## Sources (all shipped; extend, do not fork)
`rail` (thread, lead, seats, usage, last_stamp), `panes` (live bodies),
`seats` (chair, harness, model, effort, worktree), `threads`/`recent`
(dots), `feed --since` (last row per chair), `inbox --seat` (unread).
Refresh every 3-5 s on a Tk `after` timer; every read goes through the
existing Python functions, not subprocesses.

## Slices
1. `src/convoy/widget.py`: `build_widget_model(roots) -> dict` pure function
   (no Tk) that folds the sources above into the shape drawn. Tests in
   `test/demo/widget_model_test.py` with a real temp repo, two threads, one
   chair connected, one pending, one with a live-body fake from
   `panes._TEST_PROCS`; usage null renders "unknown"; a thread with
   github=no shows no URL.
2. `focus --seat <chair>` verb + `focus.py`: host detection, tmux adapter
   with an injectable runner (tested), WT: evidence-gated, `focused: false`
   with reason by default. CLI + one MCP read-only-safe shape (focus is a
   host action: gate it behind CONVOY_MCP_WRITE_TOOLS like other spawns).
3. `convoy widget [--topmost/--no-topmost] [--refresh 3]`: the Tk window,
   thin, rendering the model; toggle for always-on-top; row click ->
   `focus`. Tk is optional at import (skip the test where Tk is missing,
   like the tray does).
4. README + docs/HAPPY_PATH.md: one section, no hype.

Commit small; `committed` rows if luna1's provenance verb has landed by then,
else hook notes with sha + files. Rebase onto feat/happy-path-proof and
onto convoy/luna1 for anything under rail.py before pushing.

## Reference design (Marco, 2026-09-05): copy this. `docs/briefs/widget-reference.png`

Header: `convoy.bot` wordmark + `Deploy Forward` link, then the thread dots
`● ·1 ·2 ·3` (filled = selected) and a `+` that starts a new thread
(`convoy start`, g1 slice 3: picker / new-thread ask, never auto-bind).

Section 1 `REPO` with a right-aligned `CONNECTED` chip: the repo URL
(`github.com/deploy-forward/convoy`) only when the bind says github=yes and
a real remote exists; otherwise the chip says `LOCAL` and no URL is shown.
`LOCAL STORAGE · THREAD`: the mock shows `~/.convoy/threads/cvy-8f2a.json`.
That is NOT where the truth lives (docs/CONVOY_SOT.md): render the thread
root's `.convoy/` path (e.g. `C:\Users\marco\ola\convoy-wt-happy\.convoy`)
and, on hover or a second line, the machine index `~/.convoy/threads.json`
that found it. Under it, exactly as drawn: `convoy_id cvy_… · bound to
thread <key>`.

Section 2 `USAGE REMAINING` with a `SESSION | WEEK` toggle: one bar per
attached harness from `usage.surface` (`session_pct` / `week_pct`). The
mock's numbers are illustrative: claude gives session and week; codex gives
a status line the probe parses or null; grok reports no meter, so its bar is
the grey "unknown" bar with the footnote the mock already has ("grok
reports overall only"): keep the footnote honest to what the probe returned,
never 90% from memory. Null is an empty bar labelled `unknown`, never 0%.

Section 3 `HARNESSES · NEURONS IN THREAD` with `N SEATED` on the right,
counted from the seated acks. Table SEAT | HARNESS | MODEL | EFFORT; the lead
row carries the blue left rule and the label `lead` (from `.convoy/lead`).
MODEL and EFFORT are dropdowns whose options come from the harness contract
(`card.rows[].models` may be null: then a free field; `effort.keys`; codex
effort is declared, not applied, and the cell says so on hover). Choosing a
value shows the exact `seat --effort` / `swap` command and runs it only on
confirm. Footer: "every neuron seated in ·1 — model · effort tunable per
seat".

Type and color as drawn: monospace throughout, blue `#2f4fd8`-ish accent,
green CONNECTED, greys for hairlines; Tk fonts Consolas/Menlo fallback.

## Slice 5 (added 2026-09-05T05:1xZ): stale chip + wake, per harness, evidenced

Stale chip: per chair, from the tape only: `last_authored` (newest feed row
with from/instance_id = chair), `last_drained` (newest consumed marker in
its inbox), `waiting` (undrained rows), `idle_s` (now - max of the two),
`body` (panes proves a live process | null). Chip states: `working`
(authored or drained within N s, default 300), `idle` (body live, nothing
in N s), `stale` (waiting > 0 and idle > N), `gone` (no body). Thresholds
are flags, not constants. Rendered on every chair row and summed on the
thread dot (a red ring when any chair is stale). Live case to reproduce:
g1 2026-09-05 04:56-05:05Z, 3 rows waiting, body alive, hook silent.

Wake (`nudge --seat <chair>`): a wake is a per-harness FACT to be tested,
not assumed. Marco: "we haven't done enough pen-testing to count grok out;
we can send keys directly to a specific pane". So slice 5b is an
experiment matrix, run by g2 on its own grok pane and on a codex pane,
evidence recorded in harness_effort.json style (command, observed, ts):
  - codex: native queue (exists) - confirm it wakes an IDLE pane.
  - grok: (1) keystroke into the pane: focus the exact pane in the host
    (tmux `select-pane -t` + `send-keys`; Windows Terminal: find the pane's
    HWND/window, `focus-pane`/`focus-tab` if addressable, then SendInput of
    Enter or a no-op line) and observe whether the PreToolUse hook drains;
    (2) ACP leader `session/prompt` when `grok leader list` shows one
    (grok-lead's branch origin/feat/grok-acp-session-prompt); (3) anything
    grok --help evidences. Record what woke it and what did not.
  - claude: SessionStart/PreToolUse only, or a keystroke as above.
Rules: nudge runs only on the user's own machine, behind the write gate
and a consent card that names the pane and the exact keys; never on the
public MCP; never a WM_CHAR into a pane Convoy cannot prove is that chair
(panes via token/cwd); a nudge that lands returns `delivery: nudged`,
never `delivered` (the ack proves that). Refuse when the target pane
cannot be identified: a keystroke into the wrong pane is worse than idle.

Evidence 2026-09-05 (Fable, this machine, Windows Terminal): `wt focus-pane --help`
shows `-t, --target INT:NONNEGATIVE REQUIRED  Focus the pane at the given index`,
and `wt --help` lists `-w, --window TEXT` plus `move-focus`, `focus-tab`,
`focus-pane`. So a pane IS addressable: `wt -w <window> focus-pane -t <index>`.
Note: wt shows its help as a GUI dialog, never on stdout; probe it once, by hand.

Evidence 2026-09-05 05:57-06:00Z (Fable, live, Windows Terminal, grok panes):
a keystroke into a specific pane DOES wake an idle grok TUI. Method that
worked: find the WT window by class CASCADIA_HOSTING_WINDOW_CLASS + title;
take the foreground with an Alt tap (keybd_event VK_MENU) + AttachThreadInput
+ SetForegroundWindow (a bare SetForegroundWindow from a background process is
refused); move pane focus with Alt+Arrow (WT default move-focus); VERIFY by
the window title, which is the focused pane's title (a busy grok pane reads
"Waiting for response..." / "Running: <tool>", an idle one reads "grok");
SendKeys the message + Enter. Observed: g1 drained 4 rows within a minute of
the keystroke; the second copy landed in g1 again because Alt+Left did not
move focus from the right-most pane, so the title check is mandatory, not
optional. This is the `nudge --seat` adapter for WT; tmux gets `send-keys -t`.

DOUBLE-FIRE FAILURE, recorded (Marco, 2026-09-05): transport = SendKeys into a
Windows Terminal pane, OUTSIDE Convoy (no inbox row, no token, no consumed
marker). Fires: 05:57:08Z into the focused pane (g1); 05:57:29Z after Alt+Left,
which did not move focus, so g1 again; 05:59:50Z after Alt+Right into g2. g1
then reported at 06:10:33Z a "garbled relaunch prompt arrived in live g1 pane
(pid 59824)": a fourth arrival with no matching send. Token: none (a keystroke
carries none). Dedupe key: none existed. Consequence: the same neuron acted
on the same prompt more than once and re-ran seated. Rule for `nudge --seat`:
every nudge carries a nudge_id (uuid) in the typed text AND as a kind=nudge
feed row {ts, instance_id: chair, nudge_id, transport, pane_title}; the
neuron's ack cites nudge_id; a second nudge to a chair whose last nudge_id has
no ack yet is refused unless --force; the pane-focus step must re-read the
title AFTER the move and refuse when it did not change from the previous pane.
Evidence 2026-09-05 06:03-06:07Z (g2-happy-path, this machine, Windows Terminal):
slice 5b matrix, command / observed / ts (also `src/convoy/nudge.py` WAKE_EVIDENCE):
- `grok --help` 06:03:21Z: no `queue`; has `leader`, `agent` stdio, `--resume`,
  `-p`/`-c` (forbidden as a wake). `grok help queue`: unrecognized subcommand.
- `grok leader list` 06:03:21Z: "No leader candidates found." `leader.sock` missing.
  ACP `session/prompt` not attempted: a second `--no-leader` agent against a
  pid-held TUI is a steal (`~/.grok/active_sessions.json` has g1 pid 59824 and
  g2 pid 101288, cwd-matched).
- WT titles 06:03:21Z: 3 `CASCADIA_HOSTING_WINDOW_CLASS` windows, all WT pid
  99004. Unique worktree title: `convoy-wt-happy-wt-luna2`. g1/g2 titles are
  the user prompt, not the worktree, not seat title `g2`; idle title `grok` is
  generic and never unique with two grok chairs. Adapter never Alt+Arrows
  (Fable's mis-delivery).
- `codex queue --help` 06:03:21Z: `--thread <UUID or exact session name>
  --message`. Fake UUID 06:07:27Z: rc 1, "no rollout found for thread id".
  All four seats have `resume=null`, so live queue cannot be aimed.
- This grok pane was working, not idle; no SendInput was fired. Occupant-side
  wake remains `inbox --wait` (ead0b58). `nudge --seat` is the host-side verb:
  write-gated, consent names pane+keys, `delivery: nudged` never `delivered`.
- Live dry-run 06:17Z: `nudge --seat g2-happy-path --dry-run` first claimed
  `identified: true` because the WT title contained the tool description
  "Dry-run nudge identity for g2". Short seat titles are not substring
  identity; only the worktree folder name or an exact/prefix pane title
  counts. After the fix, g1/g2 refuse (prompt title); luna1/luna2 refuse
  (codex bodies unplaced, liveness unknown). That refuse is the product.
