# Amendment 2026-10-10: a provision can now launch a chair on an enrolled device

An amendment to the origin loop's delivery rule (SPEC.md "Delivery" in `origin_loop.py`;
the first slice of the enrolled-device work). It amends; it does not
rewrite: delivery to an already-seated chair is unchanged, and this records only what is
new on top of it, in Convoy 1.4.1.

## What a provision does on a device, before and after

Before this amendment, `_act` on a pending link read exactly one of today's chairs: a live
seated chair of the link's harness received the brief, and anything else (none, several,
all detached) refused. Nothing was ever spawned on provision, by design, and the board
read that refusal as `harness_absent`.

After it, `decide(link, seats, origin, terminal)` is a pure function with three outcomes:

- **deliver** — exactly one live seated chair of the link's harness: unchanged.
- **launch** — no chair of that harness exists at all, the device owner's own press
  requested it (`link.requestedBy.id == origin.user_id`, ruling R1 in the design doc,
  checked fail-closed: an empty id on either side is never a match), the harness is
  installed, and a pane host can open a window. The existing `crew.add` mints, joins and
  launches the chair — no new spawn path — then the framed card reaches it through the
  same `send_one` call an already-seated chair receives one from.
- **refuse** — everything else, with one of `harness_not_installed`, `no_terminal`,
  `policy_denied`, or `no_resume_target` (several live chairs, or every chair of that
  harness detached: resuming one needs a take-over `crew.add` does not accept yet, so a
  fresh body beside it is refused rather than guessed).

A link carrying `reuseLinkId` or `takeOver` always refuses `no_resume_target`: `crew.add`
does not accept either today. Honouring them is future work, named here so the gap is
recorded rather than silently worked around.

## Nudges: answered, not yet acted on

`pendingNudges` are now read and answered through a new `ReportClient.answer_nudge`
(`POST /api/org/worklanes/origin/nudges/:nudgeId`), one answer per nudge, skipped (never
answered) when not addressed to this origin — the same rule a pending link follows.

Every nudge answers `unsupported` today. The existing nudge rail (`nudge.py`) wakes a
chair only under a human's one-time consent naming the exact pane and keystroke; the
platform's nudge request carries neither, and an unattended loop minting its own consent
would be exactly the guessed injection that rail exists to prevent. A consent-free wake
path is a design question for a later release, not a code gap in this one.

## The heartbeat now matches what the platform reads

`beat_payload` carried `{originId, asOf, threads: [{convoyId, thread, root, chairs}]}` -
`thread`/`root` were never read by `originBeat` in `worklanesApi.ts`, and `writeGate`,
`paneHost` and `harnesses[]` were never sent. It now sends exactly what that handler reads:
top-level `writeGate` (`bearer | closed`, the two values `mcp_http._write_gate` ever
returns), `paneHost` (`wt | tmux | none`) and
`harnesses` (every harness Convoy knows, with whether its binary is actually on PATH); per
thread `convoyId`, `threadKey`, `repoSlug` (from the root's git remote, lowercased
`owner/repo`) and `present: true`. Chair-level fields were already correct.

## The black pane

`pane_host.run_host` sank every managed child's stderr into a file only the host read,
so the exit row could carry a last-words tail. Grok 1.0.50 draws its TUI on stderr, not
stdout, so that pane stayed black for the length of the session - one live chair's sunk
`.stderr` file held 1.68 MB and 106,121 escape sequences nobody ever saw. stderr is now
inherited from the host's own (the pane's), exactly like stdout and stdin already were.
The cost is the tail: a boot failure's last words are on the pane's own scrollback now,
not in the exit row's `stderr_tail`, which is always `null`. Claude and Codex, which draw
on stdout, were never affected and are unchanged.
