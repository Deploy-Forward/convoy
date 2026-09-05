# Ultracode brief: Happy Path + `/convoy --start` (no ola)

Lead: Fable (claude, chair-less conductor on thread `happy-path`, root
`C:\Users\marco\ola\convoy-wt-happy`, branch `feat/happy-path-proof`, PR #61).
Implement: `g1-happy-path` (grok). Verify: `g2-happy-path` (grok).
Fable classifies and monitors (feed / rail / stamp); neurons write the diffs.

Read first: `docs/HAPPY_PATH.md`, `test/demo/happy_path_test.py`, PR #61.
Work in YOUR worktree (`convoy-wt-happy-wt-g1` / `-g2`), on your branch
(`convoy/g1`, `convoy/g2`). Commit small. Never squash. When a slice is
done: `convoy --root <root> hook note "<what, evidence>" --as-me --to grok-bot`
and push your branch. Unknown stays JSON null. Never invent usage, ids,
tool counts.

## Gate 0 (Fable, stamped 2026-09-05T02:05Z)
| check | result |
|---|---|
| PR #61 mergeable, happy_path_test | GREEN (535 passed, 1 skipped) |
| `ola_runner` reachable in-process | RED: `synapse.py` defines it (~87) and `_send_one` still dispatches on it (~204, ~392) |
| public `tools/list` | null: not probed (standing order: stay local unless asked) |
| pane host / grok CLI on this machine | WT present, grok present; crew --launch opened one window |
| machine thread index `~/.convoy/threads.json` | RED: 4,619 rows, ~all test residue under `%TEMP%` (`demo` x1008, `t1` x900, thread=null x660). A picker and `rail`'s index scan are unusable until hygiene lands |

## g1 slices (implement, in this order)
1. **Index hygiene.** (a) Every test path that mints a root must write to a
   throwaway `CONVOY_HOME` (test/run.py does; bare `python -m unittest` does
   not: fix at the test-package level, e.g. `test/demo/__init__.py` or a
   conftest-equivalent, so no invocation can touch the real home). (b)
   `threads` gains `--prune`/a `prune` verb: drop rows whose root is under the
   OS temp dir or is absent; report what was dropped; never silent. (c)
   `list_threads()` stays honest (present=false kept) but a `recent(limit)`
   helper returns the newest N present rows excluding temp roots, for the
   picker. Tests for all three.
2. **ola purge.** No user-facing `ola` / `ola-brain` / `.ola/` in
   `src/convoy`, `plugin/`, `skills/`, README, SPEC prose that describes the
   product. Handoff pointers move to `.convoy/handoff/<chair>-<ts>.md`;
   `swap --handoff` accepts the new path (keep reading an old `.ola/*handoff*`
   only as a labelled legacy fallback, or drop it if no test needs it). Delete
   `ola_runner` from `synapse.py`, or make `_send_one` hard-refuse it with a
   card (`refused: true`, reason). Refusal of `ola-brain` as a harness stays.
3. **`/convoy --start [<repo>]`.** Thin CLI alias `convoy start [<repo>]`
   composing existing verbs, plus the skill text: git URL -> `clone` once ->
   `onboard --github yes`; local path -> `onboard --github no`; no repo ->
   picker from `recent()` (title + root + last activity), NEVER auto-pick
   newest, empty -> "new thread" ask, cancel -> unbound. Already-live harness
   on the root (whoami/roster) -> attach, never a duplicate `bring_up`.
4. **crew transactional.** `crew.py` mints/joins before `bring_up`; a failed
   window today leaves orphan chairs. Either roll back chairs written in this
   call, or return `partial: true` with the exact recovery verb per chair.
   Test the Popen/OSError path.
5. **whoami honest on an empty process table.** `panes.py` `_safe_enumerate`
   swallows OSError and reads as "no chair". Surface `error` on the card.
6. YELLOW: detect a missing `wt`/pane host BEFORE mint/join (bringup
   `_resolve_wt_bin`), so a dry-only machine never mints for a window it
   cannot open.

## g2 slices (verify, adversarial)
- Keep `happy_path_test.py` GREEN on every g1 push; add failure-path tests:
  no repo + empty index; no repo + many threads (picker required); git URL
  without gh auth (no fake owner/repo, soft continue-local); already-live
  harness (no duplicate bring_up); crew window failure (no orphan chairs or
  `partial: true`); whoami with enumerate error; `--since` garbage.
- Grep-gate: no `ola`, `UltraCode-Shim`, or interpreter path in any argv or
  hook command; public cards carry no token, no invented usage (null), no
  frozen tool menu.
- Review g1's branch against this brief; post findings as hook notes `--to
  g1-happy-path`; refuse to certify anything you did not run.

## Refuse
UltraCode-Shim, ola-brain wraps, inventing usage/ids, frozen tool menus,
auto-binding newest thread, bring_up on an already-wired live seat, claiming
public wizard GREEN while Gate 0 is RED, claiming Herdr-style PTY ownership.

## SoT contract (added 2026-09-05T02:1xZ, Marco)
The brief above is an orchestration brief. The DATA contract every slice must
respect is `docs/CONVOY_SOT.md`: one `.convoy/` JSON architecture (feed row
fields, stamp shape real-or-null, synapse provenance, seat row, handoff under
`.convoy/handoff/`, machine index is a finder not a store, GitHub never holds
the live tape). Do not invent a parallel store or a second envelope. g2:
grep-gate any new writer against that page.
