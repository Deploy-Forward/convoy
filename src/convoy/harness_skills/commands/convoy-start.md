---
description: Start or attach a Convoy thread on a repository. A git URL clones once and binds; a local path binds; no argument offers recent repositories. Already-live threads attach, never relaunch.
argument-hint: [<git-url> | <local-path>] [--to <harness>]... [--thread <name>]
---

Run `{{CONVOY}} start $ARGUMENTS` and return its JSON card.

- A git URL clones once under the Convoy home and binds the thread with GitHub recorded as yes.
- A local checkout path binds it with GitHub recorded as no.
- No argument lists recent repositories from the card; ask which one, do not guess. If the name the user gave matches none, show the list and ask "did you mean" with the nearest entries.
- If the thread is already live, `start` attaches and never brings panes up again.

Then, to crew it: `{{CONVOY}} crew --seat "<harness>[,model=M][,effort=E][,title=T]" ... --launch`. Preserve the user's model and effort words; the card refuses what the harness cannot take and names its real keys.
