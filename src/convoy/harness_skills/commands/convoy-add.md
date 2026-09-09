---
description: Add one neuron to the bound Convoy thread and launch its pane. Harness, then model, then effort.
argument-hint: <harness> [model] [effort] [--title T]
---

Translate `$ARGUMENTS` into one crew seat and run it from the thread root:

`{{CONVOY}} crew --seat "<harness>,model=<model>,effort=<effort>,title=<title>" --launch --no-widget`

Omit `model=` or `effort=` when the user gave none. Return the JSON card. The card's `windows[].argv` shows exactly what the pane was launched with; quote it rather than describing it. If the card refuses the model or effort, relay the harness's own words from the error and stop.
