# OPUS-1 adversarial stress: SPEC.md DoD truth vs this tree

**Auditor:** opus-1-fable-opus (neuron on thread `fable-opus`)
**Worktree:** `C:\Users\marco\ola\convoy-wt-opus` · **branch:** `fable-opus-opus` · **HEAD:** `b29c79b`
**Run date:** 2026-09-01 (UTC stamps below are verbatim from artifacts)
**Scope:** CODE + SPEC DoD truth only. MCP live-surface audit is opus-2's scope; conductor/orchestration is Fable's.
**Rule applied:** GREEN only with passing code/tests I ran, or a timestamped artifact I read. Everything else RED or `null`. No fixes, no branches, no SPEC edits were made.

## Verdict (my scope)

**Launch-ready: NO.** 13 RED findings.

The *code* is coherent and the suite is green. The failure is in **SPEC.md as a truth document**: its Phase table and "Honesty bar" section still describe a tree from before `native_runner` (2026-08-30) and the no-steal lock (2026-08-31). Six statements are now flatly false about `b29c79b` — in both directions (stale GREEN *and* stale RED). A spec whose own honesty table is wrong cannot gate a launch.

The **locked native-send / structured-talk DoD block is honest** — it says RED, and RED is what the tree and the artifacts support. That block is not the problem.

## Evidence base

| Evidence | What I did | Result |
|---|---|---|
| Test suite | `PYTHONPATH=src python test/run.py` | **184 tests, OK**, 54.07s, 0 failures (2026-09-01) |
| Tree inventory | `ls src/convoy`, `find . -name "*.ps1"` | 17 modules + `harness_skills`; **zero `.ps1` files** |
| Runner wiring | `cli.py:249`, `mcp_http.py:346`, `synapse.py:119` | live ⇒ `native_runner` on both paths |
| No-steal gate | `cli.py:250`, `mcp_http.py:356`, `synapse.py:283` | `allow_interactive_resume = not live` at both callers |
| Live layer (customer 1) | read-only `C:\Users\marco\ola\da-integration\.convoy\{feed,seats,registry}.jsonl`, `id` | 30 feed rows, 2026-08-28 → 2026-09-01 |
| This thread's layer | `C:\Users\marco\ola\fable-opus-root\.convoy\feed.jsonl` | my own ack row `2026-09-01T16:27:34.919938Z` |
| Code timeline | `git log -S` on `synapse.py` | `native_runner` = `acba4e3` **2026-08-30** (#4); `no-steal-live-resume` = `273a345` **2026-08-31** (#12) |

## RED list

**R1 — SPEC:896 is false.** Honesty-bar table: "native `send` is RED while `live=true` routes to `ola_runner`". `mcp_http.py:346` is `runner = native_runner if live else fake_runner`. Directly contradicts SPEC:87, which is the correct one.

**R2 — SPEC:891 is false.** "`ola_runner` still shells `ola-brain side-chat send` for live mode". Live is `native_runner` on both paths (`cli.py:249`, `mcp_http.py:346`). `ola_runner` survives as dead code, reachable only by an identity comparison at `synapse.py:255`. SPEC:349 carries the same stale premise ("until live vendor PATH execution replaces `ola_runner`" — it already did, `acba4e3`). A refuse-target wrapper left executable in the shipped module is itself a launch smell.

**R3 — SPEC:874 is false.** "**RED** this tree: `layer.py` is feed only; no `context.py`; `ola_runner` regex-guesses `session_id`". `src/convoy/context.py` exists, is imported by `synapse.py` and `mcp_http.py`, and `phase1_threaded_context_test.py` passes.

**R4 — SPEC:875 is false.** "Feature branch understanding: **RED**. Not in `layer.py` events today". `synapse.py:380-384` merges `gitstate.git_state()` into every synapse row. Live proof: feed row `2026-08-31T11:58:40.211558Z` carries `git_branch: integration/convoy-web-poc-20260828`, `git_sha: 76874008…`, `pr_number: 167`.

**R5 — SPEC:876 is false.** "Worktree understanding: **RED** for Convoy. Need to pass through to harness CLI". Worktree is on every row (same evidence as R4) and is passed as `cwd=` into `native_runner` (`synapse.py:162`); `phase4_worktree_test.py` passes.

**R6 — SPEC:181 and the honesty table cite files that are not in this tree.** `ConvoyLayer.ps1` ("the copy in this tree", listed as a path row) and `Invoke-AgentChannel.ps1` (cited as the GREEN source for the roster `usageRemaining` null rule, SPEC:634) — `find . -name "*.ps1"` returns **nothing**. Two GREEN claims rest on files a stranger cloning this repo will not have.

**R7 — Phase 5 table GREEN contradicts its own section.** SPEC:364 says "5 | Usage remaining | GREEN 2026-08-28". SPEC:624 titles the section "**Phase 5 Usage remaining per harness (BLOCKED)**" and lists three REDs (grok has no `/usage`; `cursor-agent` exposes no remaining; `agy` unknown). What is actually proven is narrower: *unknown normalizes to `null`*. That is honesty plumbing, not "usage remaining per harness".

**R8 — Phase 4 table GREEN has no live citation.** SPEC:363 "GREEN 2026-08-28". The Phase 4 section offers only "GREEN unit", plus "MCP still RED" and "Live dual hop is Phase 6. Not started." SPEC:356 states the gate itself: "Unit tests with a fake runner are not enough to unlock the next phase." By the spec's own rule this is unit-GREEN, live-`null`.

**R9 — Phase 3 section is stale in the other direction.** SPEC:524-526 says live probes are "in flight" and "Probes, **when implemented**" — but `gitstate.py` implements all three (`git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number`) and `registry.jsonl` holds a real `pr_number: 167`. Understating is still drift: it makes the document unusable as a status source.

**R10 — every dated live GREEN in the Phase table predates the current contract.** Table rows 1-7 are all stamped `2026-08-28`. `native_runner` landed **2026-08-30** (`acba4e3`), the no-steal lock **2026-08-31** (`273a345`). SPEC:378 and SPEC:709 confirm the 08-28 runs went through `ola-brain side-chat send` — the exact wrapper the canonical lock now names a refuse target. So no GREEN in that table is evidence for DoD item 1 (native BYO send). They are evidence about a code path that has since been forbidden.

**R11 — no artifact anywhere proves a live native vendor send, and the layer cannot tell one from a fake.** `synapse.py:384` stamps `dry_run: False` and records `to/ok/label/worktree/git_*` — but never which runner ran, no argv, no `live` flag. `fake_runner` mints `session_id = "spawned-" + to` (`synapse.py:74`). The three most recent non-dry rows in the customer-1 feed are `spawned-agy` (`2026-08-31T00:32:29Z`), `spawned-cursor-agent` (`2026-08-31T00:32:51Z`) — fake-runner shapes, recorded as `ok: true, dry_run: false`. A reader of the SoT cannot distinguish a real vendor turn from an ACK string. This is the single most launch-relevant finding: the audit trail can be honest-looking and empty.

**R12 — the "Honesty bar / This tree today" table is stale and incomplete.** It opens "This tree today (`/workspace/convoy`, not a landed GitHub checkout)" — it *is* landed (`b29c79b`, merge of PR #24). It lists 8 paths and omits 8 shipped modules (`bringup.py`, `convoy.py`, `gitstate.py`, `glance.py`, `harness_contract.py`, `identity.py`, `install.py`, `registry.py`) plus `harness_skills/`, and names 2 of 22 test modules. (Corrected 2026-09-01: this line first said "24 test files"; the directory holds 22 `*_test.py` modules plus `__init__.py` and `README.md`.) The section whose stated job is "if a function is not in `src/convoy/`, it is not GREEN" does not describe `src/convoy/`.

**R13 — the no-steal lock is a caller-set default, not an invariant (precision RED).** SPEC:89 says "`synapse.py` refuses live resumed send". The refusal at `synapse.py:283` fires only when `allow_interactive_resume=False`, and the parameter **defaults to `True`** (`synapse.py:206`, `:400`). Today both callers pass `not live` correctly and 4 MCP tests cover it — so behavior is right. But the guarantee lives in two call sites, not in the function that spawns the process: `native_runner` will still build `[exe, --resume, <id>]` (`synapse.py:144-152`) if called directly. The claim should read "both send paths refuse", or the default should invert.

## GREEN (verified by me at b29c79b)

- **Suite:** 184 tests pass, 0 failures.
- **All five "Current code honesty" bullets (SPEC:86-91) hold** — `send` live⇒native routing; PATH exec + wrapper refuse in `native_runner`; live-resume refusal (with R13's caveat); `TOOLS` contains `onboard`/`hide`/`install` (14 entries incl. aliases); wrapper-name refusal in `bringup.py` (`:98-117`, `:241`, `:658`) and `install.py` (`:61`, `:101`).
- **Feed contract v2 matches code:** `SCHEMA_VERSION = 2` (`layer.py:23`) on `feed`/CLI/attach envelopes; `conductor_stamp` clamps to one line ≤500 chars and marks `truncated: true` (`layer.py:70-86`); `refuse` rows carry the full `ask` card (`synapse.py:262-271`); `transcript` is a pointer field only.
- **Phase 2 live claim corroborates exactly:** SPEC's c1-locked `2026-08-28T14:42:46.975866Z` is a real row in `da-integration/.convoy/feed.jsonl`.
- **Phase 6 `send-dry` claim corroborates exactly:** `dry-grok-51884583` and `dry-claude-5a173460`, two rows, `14:42:47.669895Z` / `14:42:47.724691Z`.
- **Phase 7 attach claim corroborates:** `.convoy/id` = `cvy_KE0tAyDLOnqEuWxYHjpsbQ`, three `attach` rows (`23:38:35Z`, `23:38:36Z`, `23:44:36Z`), both seats in `seats.jsonl` with distinct `resume_key`s.
- **The locked DoD block's own status is honest:** items 1-3 are RED/PARTIAL and nothing in the tree or artifacts contradicts that.
- **Live CLI works on this thread today:** my ack row `2026-09-01T16:27:34.919938Z` in `fable-opus-root/.convoy/feed.jsonl`.

## NULL (unprovable from my scope — not GREEN, not RED)

- Everything about the deployed `https://convoy.bot/mcp` process: tool count, feed version, whether the no-steal lock is live there. Fable's feed row `2026-09-01T20:10:13.541928Z` reports 13 tools, no `stamp`, v1 feed description — **peer-reported, second-hand, I did not probe it.** It is consistent with my count (14 tools here minus `stamp` = 13), which would mean the deployment predates feed-v2. Assigned to opus-2.
- DoD item 2 (structured talk, two neurons on one `cvy_id` visible to a second client) and item 3 (stranger attach): no artifact, no test. `null`.
- Phase 7 SPEC:764 "RED live (parent): two attach stamps, `feed --since`" — the feed now *has* three attach rows, so this RED may itself be stale, but I cannot tie those rows to a parent-thread bind. `null`.

## What would move my verdict to yes

1. Correct or delete R1-R6, R12 — the six false statements and the stale inventory.
2. Reconcile the Phase table with each section (R7-R9), and re-date rows 1-7 as pre-native-runner (R10).
3. Add a runner discriminator to the synapse feed row — `runner: "native"|"fake"` and argv[0] — so the SoT can prove a live send (R11). Until then "live GREEN" is unfalsifiable by design.

## Fixes executed (2026-09-01, docs only, branch `fable-opus-opus`)

Increment called by Marco via the conductor (GREEN.md), scoped by lead to R1-R10 + R12, with **R13 reclassified: SPEC wording only, the code default is not flipped.** Thirteen replacements in `SPEC.md`, each applied against an exact unique string and asserted. **No `src/` or `test/` edits.** Provenance / `note` / `to` primitives are the lead's to spec-lock — nothing here documents them as existing.

| Finding | What changed in SPEC.md |
|---|---|
| R1 | Honesty-bar MCP row rewritten: live `send` routes to `native_runner`; RED is now stated as "no live vendor execution proven on the public URL", not "routes to `ola_runner`". The matching "We do not" bullet was rewritten the same way. |
| R2 | `synapse.py` inventory row rewritten — `ola_runner` is labelled the **retired** ola-brain path, unreachable from CLI or MCP. SPEC:349's "until live vendor PATH execution replaces `ola_runner`" now says the swap already happened (`acba4e3`, 2026-08-30) and what is missing is live proof. |
| R3 | Customer-1 log bullet: "no `context.py`" replaced with a dated correction — `context.py` ships (`pack` / `stdin_for`), imported by `synapse.py` and `mcp_http.py`; `registry.parse_session_id` has no UUID regex. |
| R4 | "Feature branch understanding: RED" → GREEN code + unit + live artifact (`gitstate.git_state()` merged into every synapse row; `pr_number: 167` on `2026-08-31T11:58:40.211558Z`). |
| R5 | "Worktree understanding: RED" → GREEN code + unit (stamped on every row, passed as `cwd` into the runner); live **native** dual-worktree hop kept explicitly `null`. |
| R6 | SPEC:181 now states `ConvoyLayer.ps1` is **not in this repo** (`find . -name "*.ps1"` returns nothing at `b29c79b`) and exists only on the Aether box. The Phase 6 "copy at `/workspace/convoy/ConvoyLayer.ps1`" parenthetical is gone. The Phase 5 roster-field GREEN no longer rests on `Invoke-AgentChannel.ps1`; it cites `usage.normalize_usage_remaining` + `harness_contract.usage_remaining_null_until_live_probe` with their tests. |
| R7 | Phase table row 5 is now **PARTIAL**, splitting the proven honesty rule (unknown ⇒ `null`) from the BLOCKED part (grok / `cursor-agent` / `agy` expose no remaining), and the Phase 5 section carries a matching scope note. Table and section no longer contradict. |
| R8 | Phase table row 4 states unit-GREEN and live-`null` explicitly, per SPEC's own gate ("unit tests with a fake runner are not enough"). Phase 4 section's "MCP still RED / not started" bullets replaced with what is actually true at `b29c79b`. |
| R9 | Phase 3 section's "in flight" / "Probes, when implemented" replaced with the shipped probes in `gitstate.py` plus the live artifact. |
| R10 | New **Provenance** paragraph under the phase table: every 2026-08-28 live run went through `ola-brain side-chat send`; `native_runner` landed 2026-08-30 (`acba4e3` #4) and the no-steal lock 2026-08-31 (`273a345` #12); those runs are evidence about a retired path, not proof of DoD item 1. Rows 1, 4, 6 are individually marked retired-path evidence; row 7 marks the resume-hop RED as **by design**, not a hang. |
| R12 | "This tree today (`/workspace/convoy`, not a landed GitHub checkout)" → "This tree at `b29c79b` — the landed public checkout of `Deploy-Forward/convoy` (merge of PR #24)", with all 17 `src/convoy/` modules plus `harness_effort.json` and `harness_skills/neuron-identity/`, one line each from the module's own code, and the real test count (22 modules, 184 tests). |
| R13 | Wording only, as directed: SPEC:89 now reads that **both** send entry points (`cli.py`, `mcp_http.py`) pass `allow_interactive_resume=not live`, refusal is enforced at both callers, and 4 tests in `phase_mcp_http_test.py` cover it. The `allow_interactive_resume=True` default in `synapse.py` is untouched. |

**Not changed, and why.** R11 (no runner discriminator on the synapse feed row) is a code change and belongs to the lead's provenance primitives — it is deliberately absent from SPEC so the document does not describe something that does not exist. Historical `ola_runner` references remain in the Phase 1 "target shape" pseudo-code blocks (SPEC ~416-429, ~503, ~610) as design history; they are now covered by the retired-path label but were not individually rewritten (outside the assigned scope). Nothing in `src/` or `test/` was touched, so the 184-test result quoted above still stands as measured at `b29c79b`.
