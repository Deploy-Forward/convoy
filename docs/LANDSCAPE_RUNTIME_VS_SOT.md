# Landscape: runtime vs SoT (Herdr comparison)

**Repo:** `Deploy-Forward/convoy`  
**Status:** positioning / honesty lock — **2026-09-04**; implementation map + pseudo-code — **2026-09-05**  
**Authority:** this file is authoritative for **where Convoy sits in the agent-terminal landscape**. It does **not** override product locks in `SPEC.md` / `CANON.md`. If this file and `SPEC.md` disagree on verbs, seats, or feed contract, **`SPEC.md` wins**.  
**Audience:** engineers deciding whether Convoy is a Herdr-class runtime, a mux, a manager app, or something else.

---

## 1. Sorting row

The field is sorted by one question:

> **What happens to the work when the thing you are looking at goes away?**

Everything else (polish, worktrees, dashboards, SSH) is secondary. Categories are not enemies: a SoT can pair with a worktree manager; a runtime can run inside a fancy terminal. The sorting row still decides which product you actually bought.

---

## 2. Short placement

**Convoy is not Herdr.**

Convoy is a **shared agent source of truth (SoT) + MCP orchestration layer**. It sits:

- **beside** terminal multiplexers (tmux, Windows Terminal, zellij) — it does not replace their PTY ownership;
- **under** manager apps (worktree / diff / review windows) — it can pair with that flow;
- **above** BYO harness CLIs (claude / codex / grok / cursor-agent / agy) — those sessions are the **neurons**.

Convoy is **not** a first-party PTY-owning agent runtime. It does **not** currently sell “N agents · 0 clients attached · still working” as a server that owns the terminals.

---

## 3. Taxonomy

| Kind of thing | Herdr | tmux / zellij | cmux / Warp | solo | conductor / emdash / superset | **Convoy** |
|---|---|---|---|---|---|---|
| What it is | runtime + clients | terminal multiplexer | terminal app | process dashboard | manager app | **thread SoT + MCP + BYO harness neurons** |
| Work survives UI close | yes — server owns PTYs | yes — detach | while the app is open | while the app is open | while the app is open | **SoT yes (`.convoy/`); panes only if the host mux / harness keeps them** |
| Runs inside your existing terminal | yes | yes | replaces it | no (desktop) | no (desktop) | **yes — WT / tmux / cloud panes; Grok Bot is conductor chat, not the PTY host** |
| Semantic agent state | blocked · working · done · idle | — | attention cues | process up / down | workspace status | **partial: seats + feed + glance; not a full blocked / wait FSM** |
| Detach, reattach, SSH in | yes, any tty | yes | partial | — | remote projects | **resume via vendor UUID + `bring_up` / seats; not universal attach-any-tty** |
| Direct attach to one agent | yes | — | — | — | — | **fire / send into a named seat; not Herdr-style “attach this PTY”** |
| API agents drive themselves | read · send · wait · split · attach | terminal scripting | app APIs | MCP for processes | workflow APIs | **MCP orchestration (`roster` / `feed` / `context` / `send` / …; `card` when Gate 0 GREEN) — not PTY control** |
| Worktree and diff review | pairs with it | — | partial | — | their core | **pairs with it (GitHub gate, worktrees per chair); not the product** |
| Clients on the same runtime | TUI · CLI · plain SSH, more coming | its own client | the app only | the app only | the app only | **Grok Bot + CLI + MCP clients; harness TUIs are the neurons** |

---

## 4. Persistence model (Convoy)

Split these or you will overclaim.

### 4.1 SoT that survives (Convoy owns)

Under a bound thread root (named thread = `--root` binding, not a second MCP URL):

| Artifact | Role |
|---|---|
| `.convoy/id` | one-line `convoy_id` |
| `.convoy/thread` | one-line thread key |
| `.convoy/feed.jsonl` | bus: conductor stamps, synapses, notes, refuse cards |
| `.convoy/seats.jsonl` | chairs / occupants (tokens never leave seats on the public wire) |
| lead / github / related files | as documented in `SPEC.md` |

Any client that can speak MCP or CLI can tap this SoT. Closing Grok Bot does **not** delete the SoT.

### 4.2 Panes / PTYs (host mux + vendor harness own)

- **Windows Terminal / tmux / cloud panes** own the interactive surfaces.
- **Vendor session IDs** (resume UUIDs) live in seat metadata; `bring_up` reopens those sessions when the host can.
- Kill the pane host or the vendor process → that **neuron** is gone.
- Convoy still has **pointers** (seats, feed). Pointers are not a live PTY.

### 4.3 Conductor vs runtime

| Quit this | What continues |
|---|---|
| Grok Bot (conductor chat) | Local neurons **may** continue if WT/tmux panes and vendor sessions still exist; SoT remains |
| Every Herdr client | Agents keep going (Herdr server owns PTYs) |
| Manager app window | Herd often stops with the app |
| Convoy public MCP process | Wire verbs go dark; disk SoT on each root remains; local CLI on `--root` still works |

**Honesty bar:** Convoy must not market Herdr’s “0 clients attached · still working” unless a shipped PTY runtime (or an explicit mux contract) makes that falsifiable.

---

## 5. Vs Herdr (the comparison that matters)

**Herdr’s claim:** a server owns the terminals; every UI is a client. The TUI can detach or crash without the agents noticing.

**Convoy’s claim:** one durable thread (`feed` / `seats` / `convoy_id`); BYO CLIs are the neurons; MCP is how anything taps the SoT.

| | Herdr | Convoy (today) |
|---|---|---|
| Owns PTYs | yes | **no** (mux / vendor do) |
| Owns thread memory | optional / adjacent | **yes — core product** |
| Agent state machine | blocked · working · done · idle | **partial (glance / seats / feed)** |
| Wait API | first-class | **not Herdr-class wait; send / feed / inbox patterns** |
| Clients | TUI · CLI · SSH · … | Grok Bot · `python -m convoy` · MCP clients |

Herdr and Convoy can **pair**: Herdr (or tmux) as the PTY runtime; Convoy as the SoT + MCP bus. They are not substitutes.

---

## 6. Vs multiplexers (tmux / zellij / Windows Terminal)

Multiplexers gave humans persistence: real PTYs, detach, SSH.

Convoy **keeps that inheritance** when the operator’s host provides it. What Convoy adds — and multiplexers never had as product — is:

- which pane/chair is which **harness** (seats);
- a **feed** bus between conductor and neurons;
- **MCP verbs** for roster, context, send, card, glance (live `tools/list`, fail-closed).

Convoy does **not** replace “I own the PTY.” On Windows, **Windows Terminal** remains the mux for isolated thread windows (`--window new`, split panes). Convoy drives bring-up and seat identity on top.

---

## 7. Vs terminal apps (cmux / Warp)

Those products **are** the terminal: their window, their renderer, their supported machines.

Convoy changes nothing about which terminal you chose. It runs **inside** WT/tmux/cloud (or attaches MCP to a conductor that orchestrates those panes). Skills call MCP; they do not invent tools.

---

## 8. Vs manager apps (conductor / emdash / superset)

Manager apps put worktrees, diffs, and review queues in a window. Useful. Convoy **pairs** with that flow (GitHub gate, one chair per worktree, PR-oriented ops).

A window that **manages** agents is not where agents **live**: quit the app and the herd often goes with it.

Convoy is happier as **the layer under that kind of window**: SoT + synapses. Today’s public pitch remains:

> **Grok Bot conductor + BYO harnesses + one MCP root** — not “we are the PTY runtime.”

---

## 9. Vs dashboards (solo)

Solo supervises a dev stack: health, restarts, logs — **process** status.

Convoy’s job is different: **interactive harness sessions** + **thread memory**, with honesty locks:

- unknown usage stays JSON `null` (never invent `0`);
- marketplace / wizard **must** fail closed on live `tools/list` / `card` (Gate 0); public wire may still be RED until origin matches main;
- public write tools gated (`CONVOY_MCP_WRITE_TOOLS`).

---

## 10. Public product pitch (today)

Locked **shape** (see also `SPEC.md`, `plugin/convoy/`). Live wire status is separate — see Acceptance bar below.

1. Attach `https://convoy.bot/mcp` (one root on the public process; named threads are `--root` bindings).
2. Skills orchestrate (`convoy`, optional `@convoy` wizard). The **intended** host UX is one live MCP card from `tools/list` / `card` — never a frozen tool menu. **Acceptance DoD:** that card path is **RED** until Public Gate 0 is GREEN on a live probe (`docs/e2e-dod.md`; wizard skill Gate 0 in `plugin/convoy/skills/convoy-wizard/SKILL.md`). Host-render of the card on Grok Bot remains **unverified** in `plugin/convoy/README.md`. Soften any landing copy that implies the stranger path is already GREEN.
3. Neurons are BYO harness sessions seated on the thread.
4. Synapses are native send into seats (not transcript merges, not UltraCode-Shim wraps).
5. **Pack ≠ product SoT:** pack = `plugin/convoy/` (skills + MCP manifests + logo). Product SoT = `.convoy/*` on the bound `--root`. Prefer saying **“Exa-style pack layout”** for marketplace pin shape; reserve **SoT** for `.convoy/` / feed / seats / `convoy_id`. Avoid calling the xAI marketplace catalog “SoT” in the same breath as product SoT (`docs/e2e-dod.md` wording collision).

### 10.1 Acceptance bar (2026-09-05)

| Check | Score | Evidence |
|---|---|---|
| Pack shape matches attach → skills → Gate 0 → card | shape OK | `plugin/convoy/.mcp.json`, skills `convoy` / `convoy-wizard` |
| Live Public Gate 0 (`card` + required verbs) | **RED** | `docs/e2e-dod.md`; live `POST https://convoy.bot/mcp` tools/list may 405 / lag origin — **never invent tool counts** |
| Host card rendering on Grok Bot | **null / unverified** | `plugin/convoy/README.md` |
| Marketplace listing | **RED** until xAI merge | pin PR separate from this landscape doc |
| Pack ≠ `.convoy/` SoT | **GREEN** | §10.5 / §12 / README |
| §16 Herdr landing honesty | **GREEN** | panes = mux/harness; no PTY-ownership overclaim |

Domain review: Acceptance Testing agent on PR #59 (2026-09-05) — overall Acceptance **RED** until Gate 0 + host-render clear.

---

## 11. Non-goals (this tree)

- Do not become a BYO-Grok-into-Claude shim (named refuse: UltraCode-Shim).
- Do not wrap vendor CLIs as fake harness identities.
- Do not claim Herdr-class PTY ownership without a shipped runtime or an explicit mux contract with live proof.
- Do not claim `blocked | working | idle` as a complete FSM until implemented and proven.
- Do not invent usage, session ids, or tool counts.

---

## 12. Implementation map (this repository)

Claims in this document must point at code or stay RED. Paths are relative to repo root on `main` / this PR tip.

| Claim | Implementation | Tests / evidence |
|---|---|---|
| SoT under `.convoy/` | `src/convoy/convoy.py` (`read_id` L37, `ensure_id` L44, `seats.jsonl` L22, `seat` L111, `list_seats` L208, `attach` L437); `src/convoy/layer.py` (`FEED_NAME` L17, `hook` L49, `feed_since` L137) | `test/demo/temporal_hooks_test.py`, `phase7_attach_test.py`, `feed_v2_contract_test.py`, `feed_note_provenance_test.py` |
| Bring-up does not own PTYs; WT/tmux does | `src/convoy/bringup.py` module docstring L1; `bring_up` L998 | `test/demo/phase7_bringup_test.py`, `consent_pane_host_test.py`, `panes_test.py` |
| Synapse = native send; no-steal | `src/convoy/synapse.py` (`native_runner` L121, `fake_runner` L75, `allow_interactive_resume` L319) | `test/demo/phase_mcp_http_test.py`, `limited_send_ask_test.py` |
| MCP orchestration, write gate | `src/convoy/mcp_http.py` (`_WRITE_TOOLS` L108 / `CONVOY_MCP_WRITE_TOOLS` (comment ~L90, gate L114), `call_tool` L590, `McpHandler` L1075) | `test/demo/phase_mcp_http_test.py`, `mcp_wizard_verbs_test.py`, `wizard_e2e_gated_test.py` |
| Glance / usage honesty | `src/convoy/glance.py`, `src/convoy/usage.py` (`probe` L151, `surface` L194) | `test/demo/glance_test.py`, `glance_public_redaction_test.py`, `phase5_usage_test.py` |
| Tokens never leave seats on wire | `src/convoy/graph.py` L16; public redaction tests | `test/demo/public_wire_redaction_test.py`, `graph_test.py` |
| Marketplace pack ≠ SoT | `plugin/convoy/` (skills + `.mcp.json`); SoT remains `.convoy/` on `--root` | `plugin/convoy/README.md`; prefer “Exa-style pack layout” over “xAI SoT” in `docs/e2e-dod.md` |

---

## 13. Pseudo-code (build shape)

Marco lock: specs are a **build** — each step has pseudo-code, implementation pointer, and GREEN/RED DoD on live functions. Unknown stays `null`.

### 13.1 Sorting-row evaluator

```text
fn what_survives(ui_closed):
  sot = exists(root / ".convoy" / {"id","feed.jsonl","seats.jsonl"})
  panes_alive = host_mux_still_has_neuron_ptys()   # WT/tmux/Herdr — NOT Convoy
  vendor_alive = seat.resume.available == true      # vendor UUID still resumable
  return {
    sot_survives: sot,                 # Convoy GREEN when disk SoT present
    agents_still_working: panes_alive AND vendor_alive,
    herdr_equivalent: agents_still_working WITH zero_convoy_clients
                       AND convoy_owns_pty == false  # today: always false
  }
```

**DoD today:** `sot_survives` can be GREEN via unit + disk. `herdr_equivalent` is **RED** until §15.

### 13.2 SoT read path (implementation)

```text
fn convoy_context(root):
  # src/convoy/context.py + convoy.py
  return {
    convoy_id: read_id(root),           # convoy.py:37 — null if missing, never invent
    thread_key: read_thread(root),
    seats: list_seats(root),            # convoy.py:208
    feed_window: feed_since(root, ts),  # layer.py:137
  }
```

**DoD:** `test/demo/phase1_threaded_context_test.py` GREEN; missing id ⇒ JSON `null`, not a minted UUID.

### 13.3 Seat + bring_up (mux owns PTY)

```text
fn seat(root, session_id, worktree, ...):
  # convoy.py:111 — C8 lives HERE, not in bring_up
  holder = chair_holding_worktree(root, worktree, except_session=session_id)  # convoy.py:148 / :247
  if holder: refuse("C8: one worktree, one chair")
  append_or_update seats.jsonl

fn bring_up_thread(root, convoy_id, thread):
  # bringup.py:998
  seats = list_seats(root, convoy_id)
  panes = _pane_seats(seats)                    # bringup.py:185 — dedup panes only; not C8
  window = host.open_isolated_window()          # WT `--window new` / mux equivalent
  for seat in panes:
    argv = resume_argv(seat)                    # bringup.py:289 — vendor UUID, never Convoy seat id
    host.split_pane(window, argv)               # PTY owned by host
  return card(panes=..., convoy_id=..., nulls_ok=true)
```

**DoD:** C8 enforced at `seat` / `chair_holding_worktree` (`convoy.py`); `bring_up` only tiles. `phase7_bringup_test.py` unit-GREEN. Live GREEN only on a machine with WT/tmux proof — cloud box without WT ≠ live bring-up GREEN.

### 13.4 Synapse send (orchestration, not attach-PTY)

```text
fn synapse_send(root, to, body, live):
  # synapse.py
  allow_resume = not live                       # no-steal: live refuses interactive --resume steal
  runner = native_runner if live else fake_runner
  card = runner(to=to, body=body, ...)
  append_feed(synapse_row(runner=runner_kind, argv0=..., to=to, ...))
  return card
```

**DoD:** MCP/CLI paths pass `allow_interactive_resume=not live`. Live native send without runner provenance ⇒ not evidence of Herdr-class runtime.

### 13.5 MCP tools/list fail-closed

```text
fn tools_list(process):
  # mcp_http.py
  tools = registered_public_tools()
  if env.CONVOY_MCP_WRITE_TOOLS != "1":
    tools = tools - WRITE_TOOLS                 # hidden, not listed-and-refusing
  return tools

fn wizard_gate0():
  live = mcp.tools_list()                       # this run only — no cache
  if required_verbs missing from live:
    return RED(classify=redeploy|write-gated|not-registered)
  return card_tool()                            # one host card when verb exists; else RED
```

**DoD:** `mcp_wizard_verbs_test.py` / Gate 0 classify on a checkout. Public `https://convoy.bot/mcp` tool count is **live probe only** — never pin a number in this SPEC. Stranger Acceptance stays **RED** while live Gate 0 lacks `card` (or POST fails).

### 13.6 Semantic state (partial today)

```text
fn neuron_state(seat):
  # Today — NOT Herdr FSM
  return {
    harness: seat.to,
    model: seat.model or null,
    effort: seat.effort or null,
    resume_available: seat.resume.available,   # bool only on wire
    usage: usage.surface(harness),             # null if no probe — never invent 0
    # blocked|working|done|idle: ABSENT
  }
```

**DoD:** glance/usage tests GREEN for null honesty. Claiming `blocked|working|idle` without code ⇒ **RED prose**.

---

## 14. Gap / optional DoD — competing on Herdr’s sorting row

If Convoy chooses to compete on **row 2** (work survives every client going away **as live agents**, not only as pointers), the gap is explicit:

| Requirement | Pseudo-code sketch | Definition of done (falsifiable) |
|---|---|---|
| Detachable PTY runtime **or** hard mux contract | `runtime.own_pty(seat)` **or** `mux.contract.detach(seat)` documented + tested | Live demo: N neurons accept work with **zero** Convoy UI clients; owner of PTY named in SPEC |
| Semantic waits | `wait_until(seat, in={blocked,working,idle})` without pane OCR | First-class state in SoT or runtime API; unit + live proof |
| Direct attach | `attach_tty(seat) -> pty_client` without stealing interactive resume | Compatible with no-steal lock (`allow_interactive_resume`) |
| Honesty | feed rows carry `runner` / `argv0` (feed v2.1) | Reader can distinguish native vs fake ACK |

Until that DoD is GREEN on a live proof, landing and sales copy stay on the **SoT + MCP** claim.

---

## 15. Verification matrix (test domains)

Marco: loop Unit / Integration / Acceptance / System Testing against this SPEC. Each domain signs GREEN/RED/null with evidence paths — never invent.

| Domain | Questions | Primary tree |
|---|---|---|
| **Unit** | Do pseudo-code blocks match functions? Are DoDs falsifiable by `test/demo/*` without network? | `test/demo/*_test.py`, pure `src/convoy/*.py` |
| **Integration** | Do MCP + CLI + seat/feed/bring_up paths compose as claimed? Write gate + no-steal hold across boundaries? | `phase_mcp_http_test.py`, `mcp_wizard_verbs_test.py`, `phase7_*`, `inbox_notify_test.py` |
| **Acceptance** | Does public pitch (§10) match what a stranger gets from attach → skills → live card? Pack ≠ SoT clear? | `plugin/convoy/`, `docs/e2e-dod.md`, `README.md`, Gate 0 |
| **System** | Persistence topology: Worker `/mcp` vs Python origin vs WT/tmux; quit-conductor vs quit-mux behavior | `docs/deploy-convoy-bot-mcp.md`, `workers-site.mjs`, `bringup.py`, live convoy.bot probe |

Reviewers record findings under `docs/audits/` or as PR review comments on the landscape PR — cite file:line.

---

## 16. Landing one-liners

- **Herdr:** runtime for agent terminals.
- **Convoy:** source of truth and MCP for BYO agent harnesses on one thread — persistence of panes is still the mux / harness’s job.

---

## 17. Glossary cross-ref

| Term | Meaning (product) |
|---|---|
| Grok Bot | conductor (chip-less orchestrator chat) |
| neuron | one grok / claude / codex / cursor-agent / agy session on a thread |
| synapse | native send into that neuron |
| thread | durable circuit (`convoy_id`) |
| named thread | `--root` binding — not a second MCP URL |
| SoT | `.convoy/` layer under the bound root |
| seat | chair; neuron is the occupant |

See `CANON.md` and the terminology lock in `SPEC.md`.

---

## 18. Domain review log

| Domain | Agent | Score | Notes |
|---|---|---|---|
| Acceptance | Acceptance Testing (`a5236dab-…`) | **RED** | Softened §10; pack≠SoT GREEN; §16 GREEN; clear = live Gate 0 + host-render |
| Unit | Unit Test | pending | |
| Integration | Integration Test (`62eaa2dc-…`) | **GREEN** (+ citation fix) | C8 at `seat`/`chair_holding_worktree` not `bring_up`; `resume_argv`; `_WRITE_TOOLS` L108 |
| System | System Testing (`f5936e5a-…`) | **GREEN** (SPEC) / live wire **RED** ops | Persistence §4/§6/§14 honest; WT owns PTY; Worker≠origin; POST /mcp 405 this probe — tool count null |

## 19. Related artifacts


- `SPEC.md` — product / feed / seat / MCP locks  
- `CANON.md` — names  
- `plugin/convoy/` — marketplace pack (skills + MCP), not the SoT  
- `docs/deploy-convoy-bot-mcp.md` — public MCP origin topology  
- `src/convoy/{convoy,layer,bringup,synapse,mcp_http,glance,usage,graph}.py` — implementation cited above  
- `test/demo/` — falsifiable unit/integration evidence  

