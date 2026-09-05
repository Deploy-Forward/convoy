# Landscape: runtime vs SoT (Herdr comparison)

**Repo:** `Deploy-Forward/convoy`  
**Status:** positioning / honesty lock — **2026-09-04**  
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
| API agents drive themselves | read · send · wait · split · attach | terminal scripting | app APIs | MCP for processes | workflow APIs | **MCP orchestration (`roster` / `feed` / `context` / `send` / `card` / …) — not PTY control** |
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
- marketplace / wizard fail closed on live `tools/list` / `card`;
- public write tools gated (`CONVOY_MCP_WRITE_TOOLS`).

---

## 10. Public product pitch (today)

Locked shape (see also `SPEC.md`, `plugin/convoy/`):

1. Attach `https://convoy.bot/mcp` (one root on the public process; named threads are `--root` bindings).
2. Skills orchestrate (`convoy`, optional `@convoy` wizard); host renders live MCP cards — not a frozen tool menu.
3. Neurons are BYO harness sessions seated on the thread.
4. Synapses are native send into seats (not transcript merges, not UltraCode-Shim wraps).
5. Pack = skills + MCP manifests (+ logo); SoT = `.convoy/*` on the bound root.

---

## 11. Non-goals (this tree)

- Do not become a BYO-Grok-into-Claude shim (named refuse: UltraCode-Shim).
- Do not wrap vendor CLIs as fake harness identities.
- Do not claim Herdr-class PTY ownership without a shipped runtime or an explicit mux contract with live proof.
- Do not claim `blocked | working | idle` as a complete FSM until implemented and proven.
- Do not invent usage, session ids, or tool counts.

---

## 12. Gap / optional DoD — competing on Herdr’s sorting row

If Convoy chooses to compete on **row 2** (work survives every client going away **as live agents**, not only as pointers), the gap is explicit:

| Requirement | Definition of done (falsifiable) |
|---|---|
| Detachable PTY runtime **or** hard mux contract | Documented owner of neuron PTYs (Convoy server **or** tmux/WT with a tested detach path). Live demo: N neurons keep accepting work with **zero** Convoy UI clients attached. |
| Semantic waits | First-class `blocked \| working \| idle` (or equivalent) with a wait API that does not require pane OCR or invented status. |
| Direct attach | Attach a tty client to one seat without stealing an interactive resume against SPEC no-steal locks. |
| Honesty | Feed/seats gain runner provenance sufficient to prove native vs fake (see feed v2.1) — already partially landed; extend for runtime ownership claims. |

Until that DoD is GREEN on a live proof, landing and sales copy stay on the **SoT + MCP** claim.

---

## 13. Landing one-liners

- **Herdr:** runtime for agent terminals.
- **Convoy:** source of truth and MCP for BYO agent harnesses on one thread — persistence of panes is still the mux / harness’s job.

---

## 14. Glossary cross-ref

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

## 15. Related artifacts

- `SPEC.md` — product / feed / seat / MCP locks  
- `CANON.md` — names  
- `plugin/convoy/` — marketplace pack (skills + MCP), not the SoT  
- `docs/deploy-convoy-bot-mcp.md` — public MCP origin topology  

