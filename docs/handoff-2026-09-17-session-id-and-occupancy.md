# Handoff: the session id, relaunch occupancy, and what actually needs resolving (2026-09-17)

Adversarial review of one claim from the platform-side session, folded into a fix plan. The claim: "Convoy's relaunch never resumes because the seat never carries a vendor session id, and capturing it from the harness's own session log (newest rollout whose `session_meta.cwd` equals the seat worktree) is sufficient." Six attack points were prescribed; the evidence for each is in section 5. Sections 1 to 4 are the handoff: where each bug is, why it is there, how to correct it, and in what order.

No code has been written for this fix yet. There is nothing to review but the plan.

Sources: Convoy main `06bfd60` (paths under `src/convoy/`), the platform checkout `deploy-forward-canonical` and its `.convoy/` record for thread `cvy_AH96kNbcs0yrgCWJkrs5FQ`, the vendors' own session stores on this machine, and the live process table read at about 2026-09-17T11:00Z. Vendor session ids and inbox tokens are truncated to eight characters on purpose; they must not ride a public document.

## 1. Verdict in six lines

- The diagnosis is right in substance: no seat row carries a vendor session id, every relaunch booted a first run with the boot prompt, and relaunch never touches the previous body.
- It names a field that does not exist. The seat's vendor id field is `resume` (bound to a harness by `resume_for`). `vendor_session_id` is a legacy alias that is only read, and only written as `None` on a harness swap.
- It undercounts the write paths (three, not one), but all three take a caller-supplied value. Nothing observes an id. "Never captured" holds.
- The proposed capture is the wrong mechanism. Convoy already receives the id on every Stop hook for Claude and Codex and discards it by design; Grok carries it in every hook payload and in `GROK_SESSION_ID`; Claude and Grok accept a Convoy-minted id at launch. Reading the log by cwd and recency is the one racy method, and on this run it would have picked a Convoy usage-probe stub 38 times out of 42 for the Claude chair.
- The cost claim is inverted. A boot costs about 26k input tokens, one percent of a life. The millions are per-call context replay, 93 to 96 percent cached, and a resume replays more of it, not less. The id buys continuity and, for Codex, the native `codex queue` wake; it does not buy tokens.
- The finding the brief did not ask for: four bodies of the Claude chair are alive right now, one per launch, about 970 MB together. Relaunch without kill is not a policy gap on paper; it is the memory pressure that killed the waiters.

## 2. The bugs, exactly

Each row: what was observed, where it is in the code, why it is there, and the correction. B1 to B3 are the ones that matter; the rest ride with them.

### B1. The seat never learns its vendor session id

- Observed: 32 seat rows, 11 for `review-thread`; `resume` and `resume_for` null on all 32. Relaunch argv therefore never carried `resume`, `--resume` or `--conversation` (`bringup.py:342-350`), and every relaunched pane booted fresh.
- Where: `convoy.seat()` writes `resume` from its argument (`convoy.py:156-183`); `update_seat` nulls it on a harness change (`convoy.py:321-324`); `lookup_resume` and `resume_target` read it (`convoy.py:376-398`, `bringup.py:286-302`). Callers that set it: CLI `seat --resume` (`cli.py:146`, `:520`), the MCP `seat` tool (`mcp_http.py:865-877`), the widget re-passing a row's own value (`widget_web.py:224`). `relaunch()` changes only `boot_prompt` (`relaunch.py:100-105`).
- Why: the one place that holds the id, the Stop hook payload, hashes it into a dedupe key and drops it on purpose (`end.py:35-61`; docstring `end.py:8-11`: "Vendor session ids ... are never written to the Convoy feed"). That rule was written for the feed and is right for the feed. Nobody then wrote the seat-side counterpart, so the id is in Convoy's hands at every turn end and stored nowhere.
- Correction: stamp `resume` and `resume_for` on the seat row from a deterministic source, never from timing (sources per harness in section 3). Null until observed. The feed rule stays; the seat row is where `graph.py:16` already says tokens live.

### B2. Relaunch neither checks nor terminates the previous body

- Observed: `claude.exe` bodies of `lane-c-store-api-thread` alive at 11:00Z: pid 32272 (first boot, 14:12:24Z, model id `claude-fable-5.1`, never seated), 28136 (14:17:33Z), 50668 (22:43:46Z), 65448 (02:22:14Z); 217, 226, 262, 267 MB. Three relaunches, zero terminations. The Codex chair has one body (the 10:24Z life); its four predecessors are gone with no row saying how or when. The three Grok bodies match `~/.grok/active_sessions.json` pid for pid.
- Where: `relaunch()` re-arms the prompt and calls `bring_up(session_ids=...)` with no occupancy check (`relaunch.py:47-121`). The only claim in the codebase belongs to `launch --seat` (`targeted_launch.py:210-230`, "refuse duplicate launch: chair already claimed"). Crew and relaunch panes put the harness exe straight into the terminal argv (`bringup.py:888`), so no pid is recorded; only the managed host tracks `harness_pid` and `process_state` (`pane_host.py:120-181`).
- Why: commit `ab5006a` (2026-09-03) removed the kill coupling after a stale close request terminated a fresh grok-lead two seconds after start. The coupling was removed; an occupancy rule never replaced it.
- Correction: every launch path records the body (pid, started, incarnation) on the seat, which means crew and relaunch go through the managed host too (the platform plan's D3). `relaunch --seat S` refuses while a body of the current incarnation is alive and no death row exists. `relaunch --take-over` writes `kind=evicted {chair, incarnation, pid, evidence}` and terminates the process tree through the host (never terminal input), then launches incarnation+1. Automatic take-over only from a `kind=unreachable` row (D3 of the durability handoff). A body that is provably gone needs no kill, only its exit row. The case that matters is deaf but alive, and the only signal that justifies eviction is: rows pending, no live waiter, and no hook row from this incarnation for the window (D1 plus D2).

### B3. The Codex chair has no idle wake path, and the fix it needs is the id

- Observed: every life of the Codex chair ended its turns and went deaf. Sends sat 2 h 23 m (22:37Z to 01:00Z) until a human relaunched. In the latest rollout the boot instruction "start `inbox --wait` as a background command" appears nine times, in the prompt, in event text and in tool output; zero of the 30 tool calls executed it. Codex 0.154.0 records no background exec.
- Where: `synapse.py:218-226` calls `codex queue` only when the seat has a resume token; with `resume` null every send fell to the inbox file (`runner: inbox`, `delivery: queued`). Codex 0.154.0 has `codex queue --thread <UUID> --message <TEXT>`.
- Why: the wake for Codex was designed as native queue first, inbox second, and the native path is keyed on the id nobody captured (B1).
- Correction: B1 turns every send to a Codex chair into a native wake of the idle TUI. Plus the platform plan's B1: the Stop hook of every harness blocks with a reason while rows are pending (Grok's already does; Claude's and Codex's print `{}`).

### B4. The Claude waiter dies under memory pressure Convoy helps create

- Observed: the waiter was OOM-killed twice (feed 14:49:04Z). At 11:00Z live waiters exist only for the three Grok chairs (started 10:41Z to 10:47Z, each a powershell, `convoy.exe`, python, python chain of four processes); none for the Claude or Codex chair. Beside them: about 970 MB of Claude zombie bodies from B2, plus the Codex MCP server copies flagged earlier.
- Correction: B2 removes the zombies; the durability handoff's D1 (pulse file, `reachable` reported) and D2 (ten-minute waits re-armed at every Stop) and the platform plan's slim `convoy-wait` make the waiter light and its death visible.

### B5. The proposed capture heuristic is racy on all three harnesses

- Codex: the rollout's `session_meta` appears 8.0 to 18.5 s after the `relaunch` row (measured on four relaunches). A reader that runs "after spawn" sees the previous life's rollout as the newest for that cwd during that window. During the run, other Codex sessions ran on the machine (Codex Desktop with cwd `C:\`, twelve `codex exec` sessions with cwd `fable-sol`); the cwd filter held only because nobody opened Codex in the review worktree by hand.
- Claude: 8.3, 9.3 and 81.4 s between the relaunch row and the first log row. Worse, the chair's project directory holds 42 session files of which 4 are chair lives; the other 38 are nine-row stubs whose first user row is `/usage`. They come from Convoy's own probe `claude -p /usage` (`usage.py:206`), run every 300 s (`inbox.py:337`) from the chair's cwd. "Newest file for this cwd" is a probe stub 38 times out of 42.
- Grok: it does write a store, `~/.grok/sessions/<url-encoded cwd>/<id>/` with `chat_history.jsonl` and more, so the brief's doubt is answered; but it also maintains `~/.grok/active_sessions.json` as `{session_id, pid, cwd, opened_at}` and exports `GROK_SESSION_ID` to hooks, so the log is the worst of three sources.
- Token match: the boot token is the same in all five Codex lives (relaunch re-arms "the token ITS join minted", `relaunch.py:88-92`; every `seated` row cites `a9310906...`). It identifies the chair, not the life. The relaunch prompt does carry a unique string, "relaunched at <ts>", so a text match on this launch's exact boot prompt is unique; a token match is not.
- Correction: no timing anywhere. Sources in section 3.

### B6. Convoy's usage probe pollutes the vendors' session stores

- Observed: 38 probe sessions in one chair's Claude project directory in about nine hours of chair life.
- Where: `usage.py:206` runs `claude -p /usage` from the current directory; `stamp_usage_row` re-runs it every 300 s (`inbox.py:337-378`).
- Correction: run the probe with `cwd=CONVOY_HOME` so its stubs land in one neutral directory, and skip the stamp when `as_of` is unchanged (already the platform plan's D7). Platform side to check: whether the tracker uploads these stubs as sessions to the Ledger.

### B7. Zombie bodies write as the chair

- Observed: the four Claude bodies share one seat name; their Stop hooks fire `convoy end --hook` and stamp heartbeats as `lane-c-store-api-thread`. Nothing on the feed says which life wrote a row.
- Correction: D5 of the durability handoff, incarnation on the seat row, in the boot token, on every row the hooks write. After B2 lands, a row from an evicted incarnation is flagged, not merged.

### B8. The record is one `git add -A` from GitHub

- Observed: in the platform checkout `.convoy/` is `??` untracked, not ignored, and `.git/info/exclude` is empty.
- Correction: W1 of PR #106, the exclude line written by `bind`, `onboard` and `crew`. It must land before B1 puts a vendor id on the seat row.

## 3. Where the id comes from, per harness

| Harness | Installed | Mint at launch | Observe at runtime | Never |
|---|---|---|---|---|
| Claude | 2.1.274 | `--session-id <uuid>` (in `--help`) | Stop and PostToolUse payload `session_id`; project log `~/.claude/projects/<cwd with separators as '-'>/<id>.jsonl` | newest file by cwd (B5) |
| Grok | 1.0.34 | `-s, --session-id <uuid>` for a new conversation | every hook payload `sessionId` and `GROK_SESSION_ID` (user guide `10-hooks.md:256`, `:492`); `~/.grok/active_sessions.json` by the pane host's child pid | newest directory by cwd |
| Codex | 0.154.0 | none in `--help` | Stop and PostToolUse payload `session_id` (live proof: all four Codex `heartbeat` rows carry an `event_key`, which `_event_key` returns only when the id is present); fallback: the rollout whose first user message equals this launch's boot prompt | newest rollout by cwd (B5) |

Match the observation to the seat the way `end.py:140-146` already does, by cwd through `seats_for_worktree`. Minting is preferred where it exists because the seat row can carry the id before the pane even opens; observing fills the rest and confirms the mint.

Resume shapes, checked at the installed versions:

- Codex: `codex resume [OPTIONS] [SESSION_ID] [PROMPT]`, `-m, --model` accepted under `resume`; `codex -m gpt-6-astra resume --help` parses. The positional prompt starts a turn, which is what the re-armed boot prompt needs. Help text and parse only; no TUI was spawned.
- Claude: `claude -p --resume <stub id> --model claude-haiku-4-5-20251001 "Reply with exactly the single word ok"` printed `ok`, exit 0, against a throwaway probe stub. Live proof of the shape at 2.1.274.
- Grok: `-r, --resume [<SESSION_ID_OR_TITLE>]` with positional `[PROMPT]`, plus `--fork-session`. Help text only.

## 4. What actually needs to be resolved, in order

Each step is one PR in `Deploy-Forward/convoy`, red test first, gate `python test/run.py` with its own summary line quoted, installed into the production venv, one live read-back. Labels in brackets map to the platform-side `docs/convoy-fix-plan-2026-09-17.md` and to `docs/handoff-2026-09-17-durability.md`.

1. **Exclude the record from git** [W1]. `bind`, `onboard`, `crew` write `.convoy/` to `.git/info/exclude` when absent. Red: a fresh bind on a temp repo leaves `git status --porcelain` empty. Gate for everything below that writes an id.
2. **Every launch is a recorded body** [D3]. Crew and relaunch go through `convoy-pane-host`; the seat row gets `harness_pid`, `launched_at`, `incarnation` (+1 per launch); the host stamps `kind=pane {chair, incarnation, exit, stderr tail}` on exit, so a body that dies at boot finally leaves a row. Red: `test_child_exit_stamps_pane_row_with_returncode_and_stderr_tail`; `test_relaunch_increments_incarnation`.
3. **Occupancy rule on relaunch** [B2 above; D4 of the durability handoff]. Refuse while a body of the current incarnation is alive and no death row exists; `--take-over` evicts with `kind=evicted` through the host; automatic take-over only from `kind=unreachable`. Red: `test_relaunch_refuses_live_body_by_name`; `test_take_over_writes_evicted_then_launches_next_incarnation`. This lands before any resume goes live, otherwise a resume attaches a second body to a session that is still open.
4. **Session id onto the seat** [C0]. Mint for Claude and Grok at launch; `end --hook` and `inbox --hook-pretooluse` stamp `resume`/`resume_for` from the payload when the seat has none, matched by cwd; Grok also via `GROK_SESSION_ID`. Never on the feed; `_redact_public` already shapes `resume` to `{available, for}` on the public wire (`mcp_http.py:1167-1207`, applied at `:759`) and `roster` does not render seat rows. Red: `test_seat_resume_null_until_observed`; `test_stop_hook_stamps_resume_for_matching_seat_only`; `test_minted_session_id_rides_launch_argv`.
5. **Relaunch resumes** [D6]. With `resume` set and the body evicted or gone, `resume_argv` already emits the vendor shape; add `resumed: true|false` and the new id to the `relaunch` row. Red: `test_relaunch_with_resume_emits_vendor_resume_argv`; `test_relaunch_row_records_resumed`.
6. **Codex native wake** [B3 above]. Nothing new to write: with `resume` set, `synapse.py:218-226` calls `codex queue`. Read back live: one send to an idle Codex chair arrives as a user turn citing the token without a relaunch.
7. **Stop blocks on pending rows for every harness** [platform B1]. Red: `test_stop_with_pending_rows_blocks_with_reason`.
8. **Waiter liveness** [D1, D2, platform B2/B3]. Pulse file, ten-minute default, `reachable` on `neurons`, `rail`, `roster`.
9. **Usage probe cwd** [B6 above]. Red: `test_usage_probe_runs_from_convoy_home_not_the_worktree`.

Two rulings for Marco, flagged once:

- **Does the raw vendor id ride the delegation report to the Ledger?** The brief says an id must never leave the machine. The Ledger already keys every session document by it: `functions/src/ingest.ts:296`, `${uid}_${tool}_${toolSessionId}`, uploaded by the tracker from the same machine. Either the report carries it as a local locator, consistent with the tracker (recommended: it resumes nothing without the local log, and the Ledger join is the point of C0), or both sides switch to a keyed hash, which is a platform change.
- **Default on a deaf body: refuse or evict?** Recommended: refuse by default, evict by evidence (step 3). The consent path already exists for close (`pane_host.py:185-244`).

## 5. Evidence per attack point

### Point 1, null real or artifact

Seat schema on the thread (32 rows): `agent, boot_prompt, convoy_id, effort, effort_applied, model, resume, resume_for, resume_key, session_id, title, to, where, worktree`. `session_id` is the chair name; `resume_key` is `cvr_` plus a hash, a map key (`convoy.py:32`). No row has `vendor_session_id`; the alias appears in code only at `bringup.py:298`, `convoy.py:323-324`, `convoy.py:385-397`, `panes.py:232`, `:358`. So the brief's field was a read artifact; the substance (`resume` null on all 32, 11 of them `review-thread`) is real. The id is present in Convoy at every Stop: 13 heartbeat rows (9 Claude, 4 Codex), each with a 64-hex `event_key`, which `_event_key` returns only when `payload["session_id"]` is truthy (`end.py:38-39`).

### Point 2, does resume work

Shapes and live checks are in section 3. Whether a resumed session re-arms the wait: for Claude and Grok the boot prompt's last sentence does it and the record shows Grok obeying it (three live waiters). For Codex it never happened in five lives and cannot with this version; the wake for Codex is the queue (B3).

### Point 3, capture heuristic

Codex lives of `review-thread`, from the five rollouts whose `session_meta.cwd` is the review worktree:

| Life | `relaunched_at` | `session_meta` ts | Gap | Model calls | Input total | Cached | Context at last call |
|---|---|---|---|---|---|---|---|
| 1 | crew, about 14:12:14Z | 14:12:33.35Z | n/a | 8 | 372,733 | 322,432 | 56,985 |
| 2 | 18:50:11.68Z | 18:50:23.63Z | 12.0 s | 27 | 2,932,131 | 2,783,104 | 152,314 |
| 3 | 01:00:29.72Z | 01:00:37.73Z | 8.0 s | 22 | 2,404,200 | 2,248,832 | 158,297 |
| 4 | 09:44:55.12Z | 09:45:13.59Z | 18.5 s | 25 | 2,717,815 | 2,565,120 | 156,408 |
| 5 | 10:23:54.97Z | 10:24:05.50Z | 10.5 s | 32 | 2,736,007 | 2,622,080 | 126,729 |

Claude lives of `lane-c-store-api-thread`:

| Life | `relaunched_at` | First log row | Gap | pid | Alive at 11:00Z |
|---|---|---|---|---|---|
| 1 | crew boot 14:12:24Z | 14:12:28.74Z | n/a | 32272 | yes, 217 MB, never seated |
| 2 | 14:17:29.05Z | 14:17:37.32Z | 8.3 s | 28136 | yes, 226 MB |
| 3 | 22:43:40.44Z | 22:43:49.77Z | 9.3 s | 50668 | yes, 262 MB |
| 4 | 02:20:56.96Z | 02:22:18.34Z | 81.4 s | 65448 | yes, 267 MB |

Plus 38 `/usage` probe stubs in the same directory (B6). Grok: `active_sessions.json` lists exactly the three live grok pids (56044, 23716, 65784) with cwd and `opened_at`.

### Point 4, relaunch without kill

Section 2, B2. The process table is the proof; the history is `ab5006a`.

### Point 5, the cost claim

Boot-turn input per Codex life: 25,971; 26,091; 26,091; 26,094; 26,094 tokens, of which cached 7,936; 7,936; 7,040; 7,936; 12,928. Sum of the four full lives: about 10.8 M input, 10.2 M cached; the four boots about 0.1 M. The millions are the per-call replay of a 127k to 158k context, not the boot prompt. A resume would open with that whole transcript as its first input, 5 to 6 times a fresh boot, and carry it on every later call. Cache state after gaps of 25 minutes to 4 hours is vendor-dependent and was not measured. What a resume saves is the first turns' re-reading (second-call inputs were 31k to 37k, so about 10k of tool output) and, mainly, what the chair knew.

### Point 6, scope

Capture reads vendor files or hook stdin and writes only `.convoy/seats.jsonl`. Three exits from the machine exist today: the public MCP (already shaped by `_redact_public`; `roster` uses seats only to find worktrees, `mcp_http.py:672`), git (B8, open), and the Ledger's own tracker (`ingest.ts:296`, which already ships the raw id). The rule as written in the brief conflicts with the last one; that is the first ruling above.

## What this changes in the platform fix plan

C0's sentence "captured from the vendor's own session file after seated by the pane host" becomes "minted at launch where the harness allows it, otherwise stamped from the harness's own hook payload matched by cwd; never by recency". Its dependency stays D3 (the pane host) and gains the occupancy rule (step 3 above) before D6 resumes anything. Everything else in that plan stands.
