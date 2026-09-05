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
