# Harness support matrix

Release-source assessment, 2026-10-02. Coverage is independent by capability.
A successful launch or queue wake does not verify limit detection, body
attribution, transcript completeness, or resume correctness.

Model and effort flags are contract facts backed by dated vendor-help evidence
in [harness_effort.json](../src/convoy/harness_effort.json), with assembly tests
in [harness_contract_test.py](../test/demo/harness_contract_test.py). They are
not new vendor executions on this assessment date. Resume shapes below
describe [resume_argv](../src/convoy/bringup.py), not live resume certification.

| Harness | Launch eligibility | Model argv | Effort argv | Limit signal | Body match | Transcript path/timing | Native resume |
|---|---|---|---|---|---|---|---|
| cursor-agent | verified: [L3](#launch-evidence), 2026-09-08 | `--model`; evidence 2026-09-08 | model-driven, no dedicated flag; evidence 2026-09-08 | unverified | unverified | unverified | unverified; builder emits `--resume <id>` |
| codex | verified: [L2](#launch-evidence), 2026-09-07 | `-m`; evidence 2026-09-06 | `-c model_reasoning_effort=<value>`; evidence 2026-09-06 | unverified | unverified | unverified | unverified live; builder emits `resume <id>` |
| claude | verified: [L1](#launch-evidence), 2026-10-02 | `--model`; evidence 2026-09-04 | `--effort`; evidence 2026-09-01 | unverified | unverified | unverified | unverified live; builder emits `--resume <id>` |
| grok | unverified | `-m`; evidence 2026-09-04 | `--reasoning-effort`; evidence 2026-09-01 | unverified | unverified | unverified | unverified live; builder emits `--resume <id>` |
| agy | unverified | `--model`; evidence 2026-09-04 | `--effort`; evidence 2026-09-01 | unverified | unverified | unverified | unverified live; builder emits `--conversation <id>` |
| hermes | unverified | `-m`; evidence 2026-09-04 | unverified; no evidenced effort flag | unverified | unverified | unverified | unverified; builder emits `--resume <id>` |
| pi | unverified | `--model`; evidence 2026-09-04 | `--thinking`; evidence 2026-09-01 | unverified | unverified | unverified | unverified; builder emits `--resume <id>`; direct-session form needs reconciliation |

## Launch evidence

These sanitized historical observations were checked on 2026-10-02 against
Convoy lifecycle records: a join identifies the harness, and the same chair's
later seated acknowledgement echoes that join's token. No native session
identifiers, local paths or token values are published.

- L1: Claude chair joined 2026-10-02T03:12:43Z and reached token-matched seated
  at 2026-10-02T03:13:23Z.
- L2: Codex chair joined 2026-09-07T00:00:15Z and reached token-matched seated
  at 2026-09-07T00:01:38Z.
- L3: Cursor chair joined 2026-09-08T21:39:17Z and reached token-matched seated
  at 2026-09-08T21:40:32Z.

These establish accepted launch eligibility, not a guarantee for every account,
vendor build or future launch. Grok, agy,
Hermes and Pi eligibility remains unverified in this release assessment;
historical rows alone are not automatically promoted without review.

## Launch enforcement

Canonical `launch_eligibility` cells live in `harness_effort.json`, separately
from `limit` cells. Claude, Codex and Cursor pass the default eligibility gate.
The other four require the person's explicit per-call override.

Live targeted launch, bulk bring-up, crew launch, relaunch and `resume --go`
refuse unverified launch eligibility by harness name before preparation.
Crew refuses before minting worktrees; relaunch refuses before eviction;
widget relaunch refuses before unarchiving. Read-only plans remain available.

`send --live` and authenticated MCP `send` with `live: true` also enforce
eligibility before invoking a new headless vendor process, including native
resume invocations. Queuing a message to an existing chair is not a launch
and does not require a launch override.
For a new headless send, including an unregistered resume token, eligibility
is checked before usage probing. MCP
send rejects non-boolean overrides even when the message would only queue.
Eligibility refusal precedes branch-sibling refusal; accepting the override can expose a later branch refusal.

Use `--allow-unverified-launch` on the launching CLI command, or boolean
`allow_unverified_launch: true` on its authenticated MCP or local widget API
call, only when the person accepts that eligibility gap. The default is false.
The override is never stored on a seat and does not bypass authorization,
occupancy, trust or consent checks. Widget controls supply no implicit override.
Missing or malformed eligibility, evidence or verification date fails closed.

To promote eligibility, review dated, sanitized evidence of a Convoy launch
reaching seated, then update its canonical state, evidence and verification
date. Tests use synthetic identities and mock runners; they do not supply
live evidence or turn a capability green.

## Informational coverage

All seven limit cells remain `unverified`. The phrases in
[limit_signals_test.py](../test/demo/limit_signals_test.py) are explicitly
synthetic, not captured vendor output. Limit coverage informs; it does not
gate launch. A usage percentage, seated acknowledgement, successful resume
or queue wake does not verify a limit signal.

Body matching is implemented in [panes.py](../src/convoy/panes.py), and native
store presence checks in [session_store_has](../src/convoy/bringup.py).
Format fixtures do not prove live completeness, retention or freshness.
Verify each capability independently; keep unknowns null and never publish
credentials, native session identifiers, absolute local paths or transcript
bytes.

[harness_matrix_test.py](../test/demo/harness_matrix_test.py) covers default
launch eligibility, independent unverified limits, explicit overrides and
refusal before side effects.
