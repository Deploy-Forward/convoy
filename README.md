# convoy

Grok Bot MCP + hop CLI. Public repo: [Deploy-Forward/convoy](https://github.com/Deploy-Forward/convoy).

MCP attach: [https://convoy.bot/mcp](https://convoy.bot/mcp)

This is not native Convoy (`Deploy-Forward/platform`) and not the tracker (`Deploy-Forward/Deploy-Forward`). Bring your own harness. Do not wrap Grok as Claude. ola-brain is not the product.

## Isolated bring-up

One Windows Terminal window per named thread, n split-panes inside it.

```
wt --window new
nt --title T0 -d DIR0 EXE0
; split-pane -V --title T1 -d DIR1 EXE1
; split-pane -H --title T2 -d DIR2 EXE2
```

Never `wt -w 0` (injects into the focused session). Never `--` before the harness exe (pops WT Help). Grok Bot is not a window.

Claude first-run skip is `skipDangerousModePermissionPrompt` in `~/.claude/settings.json`. Project `.claude/settings.json` is ignored by Anthropic for that dialog.

## Install

```
pip install -e .
PYTHONPATH=src python -m unittest discover -s test -v
```

```
python -m convoy --root . bring-up --dry-run
```

Live TUI spawn is Windows Terminal. Dry-run ungates first-run and does not Popen `wt`.
