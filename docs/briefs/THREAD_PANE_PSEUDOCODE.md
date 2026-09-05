# Thread pane: exactly what is left, as pseudo code

For chair `astra-happy-path` (codex). Branch `convoy/astra`. Base: `feat/happy-path-proof`
merged with `origin/convoy/g1` (widget.py, focus.py, a5eedb2) and `origin/convoy/luna1`
(provenance.py). Read those first; do not rebuild them. Data contract: `docs/CONVOY_SOT.md`.
Evidence you must respect: `docs/briefs/WIDGET.md` (slice 5b live results, the double-fire).

What g1 shipped and you extend: `build_widget_model(roots)`, `run_widget(...)` (Tk,
`-topmost`, dots, chair rows, click -> `focus_seat`, `after` refresh), `focus_seat(root, sid,
runner)` returning `focused:false` with a reason until an adapter is evidenced, the tape chip
`working|idle|stale|gone`.

## 1. `nudge --seat <chair>`: wake an idle pane, once, provably

```
nudge(root, sid, *, host_runner, consent=None, force=False, dry=False) -> card
    seat   = require_seat(root, sid)                       # refuse unknown chair
    chip   = chair_chip(root, sid)                         # from build_widget_model
    if chip.state == "working":            return refuse("pane is busy; a nudge would interleave a turn")
    if chip.state == "gone":               return refuse("no live body; use relaunch --seat")
    last   = last_feed_row(root, kind="nudge", instance_id=sid)
    acked  = exists feed row kind in {"note","seated"} from sid whose text cites last.nudge_id
    if last and not acked and not force:   return refuse("last nudge " + last.nudge_id + " has no ack yet; --force to repeat")
    if not write_tools_enabled():          return refuse("nudge is a host action; behind CONVOY_MCP_WRITE_TOOLS / CLI only")
    if consent is None:                    return ask_consent(action="nudge", seat=sid, pane=pane_descriptor(seat), keys="one prompt line + Enter")
    nudge_id = uuid4().hex
    text     = ("Convoy nudge " + nudge_id + ": run " + convoy_root_command(root) + " inbox --drain --seat " + sid +
                ", act on every row, ack with hook note --as-me --to grok-bot citing nudge=" + nudge_id +
                ", then start " + convoy_root_command(root) + " inbox --wait --seat " + sid + " as a background command.")
    if dry:  return {ok: True, dry: True, nudge_id, text, adapter: host_adapter_name(seat)}
    hook(root, "nudge", "nudge " + sid, instance_id=sid, author=None,
         extra={nudge_id, transport: adapter.name, pane_title_before: None, delivered: False})   # row FIRST: the record exists even if typing fails
    result = adapter.type_into(seat, text)                  # see 2; returns {ok, pane_title_before, pane_title_after, error}
    hook(root, "nudge-result", ..., extra={nudge_id, **result})
    return {ok: result.ok, nudge_id, delivery: "nudged" if result.ok else "failed", delivered: False, next: "await ack citing nudge_id"}
```

Ack proof: `await_nudge(root, sid, nudge_id, timeout)` polls the feed for a row from `sid`
whose summary contains `nudge=<id>` (or a `seated` row after the nudge). `delivered` flips only
there. Never from the keystroke returning.

## 2. Pane-host adapters (the only part that touches the OS)

```
adapter_for(seat) -> WtAdapter | TmuxAdapter | NoAdapter
    if TMUX pane recorded on the seat/bring_up row -> TmuxAdapter
    elif os.name == "nt" and wt on PATH                  -> WtAdapter
    else                                                 -> NoAdapter (focused/nudged: false, reason)

TmuxAdapter.type_into(seat, text):   # provable with an injected runner
    run(["tmux", "select-pane", "-t", seat.pane]); run(["tmux", "send-keys", "-t", seat.pane, text, "Enter"])
TmuxAdapter.focus(seat):             run(["tmux", "select-pane", "-t", seat.pane])

WtAdapter.type_into(seat, text):     # scripts/wt-nudge.ps1 is the working reference; port it, keep every guard
    windows = enum_windows(class="CASCADIA_HOSTING_WINDOW_CLASS", visible=True)          # [(hwnd, title)]
    cands   = [w for w in windows if matches(w.title, seat.harness_idle_title) and not excluded(w.title)]
    if len(cands) != 1:              return fail("expected one window, found " + n)       # never guess
    hwnd    = cands[0]
    if not take_foreground(hwnd):    return fail("foreground refused")                     # Alt tap + AttachThreadInput + SetForegroundWindow
    before  = title(hwnd)
    for direction in ["none", "Alt+Right", "Alt+Left", "Alt+Down", "Alt+Up"]:
        if direction != "none": send_keys(direction); sleep(0.7)
        now = title(hwnd)
        if direction != "none" and now == before_move:   continue                        # focus did NOT move: the double-fire cause
        if idle_title_re.match(now) and pane_belongs_to(seat, now):
            send_keys(text); send_keys("Enter");  return ok(before, now)
        before_move = now
    return fail("no idle pane matched; busy panes left alone")
WtAdapter.focus(seat): same walk, stop at the match, type nothing. If `wt -w <id> focus-pane -t <n>`
    can be made addressable (record window id + pane index at bring_up), prefer it and record the evidence.

pane_belongs_to(seat, title):
    # grok rewrites the pane title with its own status; codex keeps `--title <chair>`; claude shows its prompt.
    # Belongs if the title contains seat.session_id, OR the seat's own title token, OR (grok) the window is the
    # crew window recorded for this thread and exactly one grok chair is idle. Otherwise false. Record which rule fired.
```

## 3. Widget: the nudge affordance

```
in _paint(), per chair row:
    if row.chip.state == "stale":  button("nudge", command=lambda: _nudge(row.session_id))
_nudge(sid):
    card = nudge(root, sid, dry=True) ; _show_cmd(card.text or card.error)          # show first
    on confirm: nudge(root, sid, consent=<granted>) ; then poll await_nudge for 60 s; repaint chip
never auto-nudge on a timer. The red ring is the invitation; the human clicks.
```

## 4. Service: the strip survives the terminal

```
convoy widget --service                # start once per machine; pidfile CONVOY_HOME/widget.pid
    if pidfile alive: exit 0 (already running)
    spawn detached: python -m convoy widget --refresh 3 --topmost   (creationflags DETACHED on nt; nohup elsewhere)
crew --launch / relaunch: after bring_up, call ensure_widget_service() unless --no-widget
widget window: a "pin" toggle for -topmost; "x" hides to the tray icon only where pystray is importable, else minimizes.
```

## 5. Tests (test/demo/nudge_test.py, widget_nudge_test.py)

- refusals: working, gone, un-acked prior nudge without --force, no consent, unknown seat
- dry returns text with nudge_id and writes NO row; live writes kind=nudge before typing and kind=nudge-result after
- Tmux adapter with an injected runner: select-pane then send-keys, in order
- WtAdapter with injected enum/title/send_keys fakes: one window required; focus-did-not-move skipped;
  busy title never typed into; the double-fire scenario (Alt+Left no move) types exactly once
- await_nudge: delivered only when the chair's own row cites nudge_id
- widget model: a stale row exposes `nudge_available: true`; working/gone rows do not
- service: pidfile alive -> no second spawn (fake spawn)
No Tk interpreter in the test process (g1's a5eedb2 pattern).

## Done when
`convoy nudge --seat <chair> --dry-run` prints the text and nudge_id; a live nudge writes the two rows and
the neuron's ack cites the id; the widget's stale row shows the button; `test/run.py` green twice; a hook
note to grok-bot per slice with the sha and files; rebased onto feat/happy-path-proof before every push.

## 6. Hooks-trust dialog: never shown again (Marco, 2026-09-05: the answer is always "2. Trust all and continue")

```
ensure_first_run(seat) additionally:
    for vendor in (harness of the seat):
        store = vendor_trust_store(vendor)          # grok: ~/.grok/trusted_folders.toml (10-hooks.md); codex: find it (codex --help, ~/.codex/*), claude: settings trust
        if store is known and the worktree is not listed: add the worktree (or the Convoy hook file) to it; record {store, written: True}
        if unknown: record {store: null} and leave the dialog to the human; the nudge answers it with "2"
```
Evidence first: read each vendor's docs/source for the trust store before writing to it; record the path and format in harness_effort.json style. Test with a temp HOME.
