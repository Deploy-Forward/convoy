---
name: convoy-nudge
description: Lead-side recovery when a neuron pane goes deaf (rows waiting, no drain, body alive or dead). Detect from the tape, then relaunch dead chairs or nudge an idle pane with a title-verified keystroke. Use whenever `rail`/`inbox` shows rows waiting and no ack for minutes.
---

# Nudging a deaf neuron

A neuron receives at tool time (PreToolUse), at turn end (the Stop gate), and
when a background `inbox --wait` completes. It does NOT receive while it sits
idle at its prompt with no background wait running. That is the only gap left,
and this skill closes it from the lead's side. Everything here was run live on
2026-09-05 (docs/briefs/WIDGET.md, slice 5b evidence) and is replicable.

## 1. Detect from the tape, never by eye

```
convoy --root <root> inbox --seat <chair>          # n = rows waiting
convoy --root <root> feed --since 30m             # last row the chair authored
convoy --root <root> panes                        # is there a live body for it
```

Stale = rows waiting AND no row authored or drained for longer than the chair's
usual cadence (grok/codex ack within ~1 min when awake). Say which it is:
`idle` (body alive, nothing waiting), `stale` (body alive, rows waiting),
`gone` (no body). Stamp the diagnosis on the thread.

## 2. Gone: relaunch, scoped

```
convoy --root <root> relaunch --thread <key> --seat <chair> [--seat ...] --timeout 300
```

Only the dead chairs. `relaunch` re-arms each chair's boot prompt with the
token its join minted, queues a "you left off at <ts>" inbox row, and counts
connected only from acks stamped after the relaunch. If Windows Terminal kept
the dead pane open ("process exited... Ctrl+D"), close that window first: find
its HWND by class `CASCADIA_HOSTING_WINDOW_CLASS` and title, `PostMessage
WM_CLOSE`. Stop only processes you can prove are the chair's (pid by name AND
start time equal to the crew launch), by exact pid, never by name.

## 3. Stale: nudge the pane, title-verified

```
powershell -File scripts\wt-nudge.ps1 -List                              # every WT window: hwnd | title
powershell -File scripts\wt-nudge.ps1 -Root <root> -TitleMatch grok -DryRun
powershell -File scripts\wt-nudge.ps1 -Root <root> -TitleMatch grok
```

The script refuses unless exactly one window matches; takes the foreground
with an Alt tap + AttachThreadInput (a bare SetForegroundWindow is refused by
Windows); moves pane focus with Alt+Arrow and types ONLY into a pane whose
title is the idle title (`grok`), never one reading "Waiting for response..."
or "Running: ...". The window title is the focused pane's title: that is the
verification. Alt+Left from the leftmost pane moves nothing, so try the other
direction and re-check rather than assume. The prompt is the same for every
pane and self-identifies through `whoami`, so order cannot misfire. tmux:
`select-pane -t <pane>` then `send-keys -t <pane> '<prompt>' Enter`.

## 4. Prove it on the feed

Within about a minute: the chair drains (inbox n = 0), posts a note, and for a
relaunch a fresh `seated` row cites its join token. Until that row exists the
chair is `pending`, whatever the pane shows.

## Refuse

Typing into a pane Convoy did not launch or cannot match to a chair; any pane
whose title says it is busy; `-p`, `--resume`, or a second session as a
"wake"; anything on a public MCP. If the harness you run in refuses the
action, narrow it (exact pid, title-verified HWND, one pane) and retry once;
say exactly which call failed if it still does.
