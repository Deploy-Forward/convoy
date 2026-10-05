"""convoy CLI. Phase 1: context + send with pointers. Parallel send is Phase 6. Phase 7: convoy_id attach + bring-up + hide."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .bringup import TRACKED_SETTINGS_NOTE, _convoy_named, dry_opt_in_refusal, bring_up, hide_windows, live_applier, live_runner, repo_files_for, terminals
from .consent import grant_consent
from .install import install as install_harness
from .onboard import onboard as run_onboard
from .start import start as run_start
from .context import pack
from .convoy import attach, bind, ensure_id, list_seats, read_id, seat, CONDUCTOR
from .crew import add as add_neuron, await_seated, crew
from .glance import build_glance, run_tray
from .graph import build_graph, neighborhood
from .graph_html import render_html, resume_neuron
from .identity import (CLAUDE_SETTINGS_RELATIVE, CODEX_HOOKS_MIGRATION_NOTE, ensure_inbox_hooks, install_neuron_identity,
                       person_files_missing, stale_codex_hooks)
from .index import find_root, index_path, list_threads, prune_threads, routable_threads
from .activity import neuron_activity
from .panes import bodies, enumerate_processes, identify
from .provenance import build_provenance, rebase_check, record_commit
from .layer import SCHEMA_VERSION, STAMPED_KINDS, conductor_stamp, feed_since, hook, parse_since
from .rail import build_rail, root_for
from .relaunch import relaunch
from .repo import (REPO_FILES_RECORD, exclude_paths, is_minted_worktree, is_tracked, record_repo_files_opt_in,
                   repo_files_opted_in, withdraw_repo_files_opt_in)
from .lifecycle import join, lead_state, lead_to_harness, pass_lead, seated_ack, swap
from .focus import focus_seat
from .widget import run_widget
from .widget_service import auto_widget_service, convoy_home, ensure_widget_service
from .nudge import nudge_seat
from .wt_walk import record_crew_window
from .pane_host import close_managed_pane
from .synapse import fake_runner, native_runner, send_many, send_one
from .targeted_launch import active_pane_runner, launch_choices, launch_seat
from .launcher import resolve_launcher
from .usage import probe

_SEAT_KEYS = ("model", "effort", "where", "title")
_WRITE_REPO_FILES_HELP = ("also write the repo files a person could own (AGENTS.md) "
                          "outside a worktree Convoy minted")


def _opt_in(args: argparse.Namespace) -> bool | None:
    """--write-repo-files is the person's opt-in; without it a worktree's marker decides."""
    return True if getattr(args, "write_repo_files", False) else None


def _seat_spec(text: str) -> dict:
    """`grok,model=grok-4,effort=high` -> {harness, model, effort}. The first
    token is the harness; the rest are key=value from _SEAT_KEYS."""
    parts = [p.strip() for p in str(text or "").split(",")]
    spec = {"harness": parts[0]}
    for kv in parts[1:]:
        key, sep, val = kv.partition("=")
        if not sep or key not in _SEAT_KEYS:
            raise ValueError("crew --seat takes <harness>[,model=M][,effort=E][,where=W][,title=T]; got " + repr(kv))
        spec[key] = val
    return spec


# The sender probe sits on a send's path: one attempt at the process table, this many seconds.
SENDER_PROBE_TIMEOUT_S = 5


def _proven_sender(root: Path, dry_run: bool, *, explicit_root: bool = False) -> dict[str, Any] | None:
    """The chair whoami proves for this body, as the sender of a send; None when
    nothing proves one. A dry run records no send, and a probe that fails or runs
    out of time never stops a send: the sender is then unknown."""
    if dry_run:
        return None
    try:
        procs = enumerate_processes(attempts=1, timeout=SENDER_PROBE_TIMEOUT_S)
        me = identify(root, procs=procs, env=os.environ, explicit_root=explicit_root)
    except Exception:
        return None
    if not isinstance(me, dict) or not me.get("chair"):
        return None
    return {"chair": me["chair"], "verified_by": me.get("via")}


def _codex_worktree(root: Path, worktree: str | Path) -> bool:
    """A worktree a codex chair on this thread sits in: the one rule for the .codex/hooks.json
    migration note, as on a first run."""
    from .bringup import _harness_bin
    from .inbox import seats_for_worktree
    return any(_harness_bin(str(s.get("to") or "")) == "codex" for s in seats_for_worktree(root, worktree))


def _record_launcher(root: Path, session_ids: list[str] | None,
                     resolved: dict[str, Any] | None = None, *,
                     explicit_root: bool = False) -> dict[str, Any] | None:
    """join --launch / launch / bring-up: resolve the launching session once, act on it
    (attach an unseated one), and record launched_by on each chair this verb may spawn:
    a pending boot prompt and no live pane host (a chair another launch already spawned is
    never touched). The prompt must carry the launcher before the spawn, so the record is
    written first and _settle_launcher undoes it on every chair the verb did not spawn.
    None when no chair is pending."""
    from .launcher import public_block, seat_launcher
    from .lifecycle import record_launcher
    from .targeted_launch import hosted_live, take_launch_claim
    wanted = set(session_ids) if session_ids else None
    fresh = [s for s in list_seats(root)
             if (wanted is None or s.get("session_id") in wanted)
             and str(s.get("boot_prompt") or "").strip() and not hosted_live(root, s["session_id"])]
    if not fresh:
        return None
    from .launcher import refusal
    resolved = resolved if resolved is not None else resolve_launcher(root, explicit_root=explicit_root)
    refused = refusal(resolved)
    if refused:
        return {"refuse": refused}   # before any write: no claim, no attach, no record
    # The launch claim first: only the invocation holding a chair's reservation records
    # and settles it. A chair another launch holds is left alone and not spawned here.
    claims: dict[str, Any] = {}
    refused: dict[str, str] = {}
    for s in fresh:
        try:
            claims[s["session_id"]] = take_launch_claim(root, s["session_id"])
        except (OSError, ValueError) as exc:
            refused[s["session_id"]] = "another launch holds this chair's claim: " + str(exc)
    fresh = [s for s in fresh if s["session_id"] in claims]
    if not fresh:
        return {"recorded_on": [], "claim_refused": refused, "_previous": {}, "_claims": {}}
    try:
        info = seat_launcher(root, resolved)
    except ValueError as exc:
        for path in claims.values():
            path.unlink(missing_ok=True)
        from .launcher import UNPROVEN_NEXT
        return {"refuse": {"ok": False, "error": str(exc), "next": UNPROVEN_NEXT}}
    except BaseException:
        for path in claims.values():
            path.unlink(missing_ok=True)
        raise
    previous = {s["session_id"]: ("launched_by" in s, s.get("launched_by"), s.get("launched_by_why")) for s in fresh}
    for sid in previous:
        record_launcher(root, sid, info.get("launched_by"), info.get("launched_by_why"))
    return {**public_block(info), "recorded_on": list(previous), "warning": info.get("warning"),
            "claim_refused": refused, "_previous": previous, "_claims": claims}


def _settle_launcher(root: Path, recorded: dict[str, Any] | None, spawned: list[str]) -> None:
    """Keep launched_by only on the chairs this verb spawned; put back what was there on
    every other chair (a refused or skipped launch records nothing)."""
    if not recorded:
        return
    from .lifecycle import record_launcher
    # A reservation this invocation took and did not spawn on is released; a spawned
    # chair's pane host adopts it.
    for sid, path in (recorded.pop("_claims", None) or {}).items():
        if sid not in spawned:
            path.unlink(missing_ok=True)
    previous = recorded.pop("_previous", {})
    for sid, (had, by, why) in previous.items():
        if sid in spawned:
            continue
        restored_why = (why if had else "no launch has spawned this chair yet") if by is None else None
        record_launcher(root, sid, by, restored_why)
    recorded["recorded_on"] = [sid for sid in previous if sid in spawned]


def _spawn_settled(root: Path, recorded: dict[str, Any] | None, spawn, spawned_of) -> dict[str, Any]:
    """Run the spawn, then settle launched_by whatever happens: an exception (a wt failure,
    a Ctrl-C) settles with nothing spawned and propagates."""
    spawned: list[str] = []
    try:
        card = spawn()
        spawned = list(spawned_of(card))
        return card
    finally:
        _settle_launcher(root, recorded, spawned)


def _claimed_launch(root: Path, sid: str, recorded: dict[str, Any] | None, launch, *, dry: bool = False) -> dict[str, Any]:
    """One chair's launch under the claim _record_launcher took. Another launch holding the
    claim refuses without launching; holding it, the launch uses it (claimed=True)."""
    refused = ((recorded or {}).get("claim_refused") or {}).get(sid)
    if refused:
        return {"ok": False, "session_id": sid, "error": "refuse duplicate launch: chair already claimed (" + refused + ")"}
    holds = sid in ((recorded or {}).get("_claims") or {})
    return _spawn_settled(root, recorded, lambda: launch(holds),
                          lambda c: [sid] if c.get("ok") and not dry else [])


def _would_refuse(root: Path, session_ids: list[str] | None, card: dict[str, Any], *,
                  explicit_root: bool = False) -> None:
    """A dry run of a launch says what the live one would do with an unproven launcher."""
    from .launcher import refusal
    wanted = set(session_ids) if session_ids else None
    if not any((wanted is None or s.get("session_id") in wanted) and str(s.get("boot_prompt") or "").strip()
               for s in list_seats(root)):
        return
    refused = refusal(resolve_launcher(root, explicit_root=explicit_root))
    if refused and isinstance(card, dict):
        card.update(would_refuse=refused["error"], why=refused["why"], next=refused["next"])


def _with_launcher(card: dict[str, Any], recorded: dict[str, Any] | None) -> None:
    if not recorded or not isinstance(card, dict):
        return
    warning = recorded.pop("warning", None)
    card["launcher"] = {k: v for k, v in recorded.items() if not str(k).startswith("_")}
    if warning:
        card["warnings"] = list(card.get("warnings") or []) + [warning]


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="convoy")
    p.add_argument("--root", default=".", help="layer root")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hook")
    h.add_argument("kind")
    h.add_argument("summary")
    h.add_argument("--instance-id")
    h.add_argument("--to", help="addressee: a seat instance_id or grok-bot")
    h.add_argument("--as-me", action="store_true", help="author = the chair whoami detects for this body; refuses when no chair on this thread matches")

    sub.add_parser("whoami", help="which chair is this body? walks your own process ancestry to the harness and matches it to a chair (token, then cwd); null with an ask when none")

    f = sub.add_parser("feed")
    f.add_argument("--since", required=True, help="10m | 2h | 1d | 45s, or an ISO UTC timestamp")

    rlx = sub.add_parser("relaunch", help="after the panes died: bring every chair up again from seats.jsonl in its worktree, queue each a 'you left off at <ts>' inbox row, and prove connected only from acks stamped after the relaunch")
    rlx.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for this launch")
    rlx.add_argument("--thread", help="must match the bound thread")
    rlx.add_argument("--timeout", type=float, default=0.0, help="seconds to wait for fresh seated acks; 0 is one snapshot")
    rlx.add_argument("--dry-run", action="store_true", help="show the windows and the per-chair timeline; spawn and write nothing")
    rlx.add_argument("--seat", action="append", help="relaunch only this chair (repeat); default every chair. Use it when some panes are still alive")
    rlx.add_argument("--take-over", action="store_true", help="evict a chair whose body of the current incarnation is still alive: writes kind=evicted, asks the pane host to close THAT life, and launches only once it is recorded as exited. Without it a live body refuses the relaunch")
    rlx.add_argument("--no-widget", action="store_true", help="do not start the widget service after bring-up")
    rlx.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    rl = sub.add_parser("rail", help="the strip under the panes: feed events since, seats connected, usage per harness (null is unknown, never 0), last stamp; reads only the thread, so any neuron sees the same rail")
    rl.add_argument("--since", default="10m", help="feed window (default 10m)")

    cm = sub.add_parser("committed", help="append one kind=commit provenance row for a Git revision")
    author = cm.add_mutually_exclusive_group(required=True)
    author.add_argument("--as-me", action="store_true", help="author = the chair whoami detects for this body")
    author.add_argument("--as", dest="author", help="authoring chair session_id")
    cm.add_argument("--rev", default="HEAD", help="commit-ish to record (default HEAD)")
    cm.add_argument("--worktree", help="Git worktree to inspect (default cwd)")

    pv = sub.add_parser("provenance", help="read per-chair commit provenance from seats plus feed rows")
    pv.add_argument("--since", help="optional feed window: 10m | 2h | 1d | 45s, or an ISO UTC timestamp")

    rb = sub.add_parser("rebase", help="inspect rebase overlap without changing Git state")
    rb.add_argument("--check", action="store_true", help="required read-only mode")
    rb.add_argument("--base", help="base branch or commit (default feat/happy-path-proof)")
    rb.add_argument("--worktree", help="Git worktree to inspect (default cwd)")

    st = sub.add_parser("stamp")
    st.add_argument("summary")
    st.add_argument("--agent")
    st.add_argument("--model")
    st.add_argument("--effort")
    st.add_argument("--instance-id")
    st.add_argument("--transcript", help="pointer to the conductor transcript, never its bytes")

    c = sub.add_parser("context")
    c.add_argument("--instance-id")

    rp = sub.add_parser("report", help="send your result to the chair that launched you, else to the lead; refuses with why when neither exists (routing is code, not a prompt)")
    rp.add_argument("body")
    ry = sub.add_parser("reply", help="answer one send by its token: a note to that send's sender citing the token, which is its delivery receipt")
    ry.add_argument("token")
    ry.add_argument("body")

    adp = sub.add_parser("adopt", help="make yourself the launcher of an existing neuron with none (or a gone one), then send it its report/reply commands; a live launcher is replaced only by the lead")
    adp_who = adp.add_mutually_exclusive_group(required=True)
    adp_who.add_argument("--id", dest="neuron_id", help="the neuron's short id (n + 6 hex)")
    adp_who.add_argument("--seat", help="the neuron's chair session_id on --root")

    s = sub.add_parser("send")
    s.add_argument("--to", action="append", help="harness of the target chair (repeat for many); or use --id")
    s.add_argument("--id", dest="neuron_id", help="short neuron id from `convoy neurons --all` (n + 6 hex); resolves the thread root, harness and chair itself, so --root and --to are not needed")
    s.add_argument("body")
    s.add_argument("--live", action="store_true")
    s.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for a headless --live launch")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--label")
    s.add_argument("--instance-id")
    s.add_argument("--worktree", action="append")

    ib = sub.add_parser("inbox", help="queue/drain live-seat messages without stealing a TUI")
    ib.add_argument("--seat")
    ib.add_argument("--drain", action="store_true")
    ib.add_argument("--hook-pretooluse", action="store_true", help="Grok/Claude hook JSON on stdout (reads hook_event_name from stdin; on Stop, blocks the stop with the waiting rows as the reason)")
    ib.add_argument("--wait", action="store_true", help="block until a row is pending or --timeout. --wait is for Claude and Grok background tasks: run it as a BACKGROUND command at the end of your turn so the arriving row wakes you. Codex is woken through its native queue: drain at turn start and never run --wait in the foreground")
    ib.add_argument("--timeout", type=float, default=3600.0, help="seconds for --wait (default 3600)")

    en = sub.add_parser("end", help="record task completion; --hook is the Codex/Claude turn-end heartbeat")
    mode = en.add_mutually_exclusive_group()
    mode.add_argument("--push", action="store_true", help="explicitly authorize one plain git push; refuses dirty/detached/no-upstream state")
    mode.add_argument("--hook", action="store_true", help="read a Stop-hook JSON payload from stdin; heartbeat only, never pushes")
    en.add_argument("--summary", help="one-line task-end summary (automatic hooks use a fixed heartbeat summary)")
    en.add_argument("--seat", default=None, help="lead: end (and --push) ONE named chair's lane from its worktree")
    en.add_argument("--all", action="store_true", help="lead: orchestra; every live chair ends (and --push) its own lane, one handoff .md + .json under .convoy/handoff/")
    en.add_argument("--include-archived", action="store_true", help="with --all: archived chairs too")

    prb = sub.add_parser("probe")
    prb.add_argument("--to", required=True)

    sub.add_parser("init")
    sub.add_parser("id")

    se = sub.add_parser("seat")
    se.add_argument("--to", required=True)
    se.add_argument("--session-id", required=True)
    se.add_argument("--worktree")
    se.add_argument("--model")
    se.add_argument("--resume", help="vendor session_id for --resume; default session_id")
    se.add_argument("--title", help="optional pane title to restore on bring-up")
    se.add_argument("--agent", help="optional agent file path used for native resume")
    se.add_argument("--effort", help="declared effort for this seat, validated against the harness's own keys (convoy choices shows them); applied to argv only where harness_effort.json evidences a flag")
    se.add_argument("--where", choices=["local", "cloud"], help="local (default) or cloud; cloud is refused unless convoy choices offers it for the harness, and takes no --worktree")

    jn = sub.add_parser("join")
    jn.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for --launch")
    jn.add_argument("--to", required=True, help="harness for the new chair")
    jn.add_argument("--session-id")
    jn.add_argument("--worktree")
    jn.add_argument("--model")
    jn.add_argument("--title")
    jn.add_argument("--effort")
    jn.add_argument("--where", choices=["local", "cloud"], help="local (default) or cloud; cloud is refused unless convoy choices offers it for the harness")
    jn.add_argument("--as", dest="author", help="authoring seat (neuron-authored)")
    jn.add_argument("--launch", action="store_true", help="launch exactly one fresh chair: inside tmux a split of your pane; on Windows the thread's own Windows Terminal window (wt -w convoy-<8 hex>: the first neuron opens it, later ones split inside it); on POSIX outside tmux with tmux installed, the thread's detached tmux session")
    jn.add_argument("--consent", help="one-time scoped consent returned by `convoy consent --grant`")
    jn.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    cw = sub.add_parser("crew", help="N neurons at once: mint one worktree per seat, join every chair with a boot prompt, bring them up in ONE window")
    cw.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for --launch")
    cw.add_argument("--seat", action="append", required=True, metavar="SPEC",
                    help="one per neuron: <harness>[,model=M][,effort=E][,where=local|cloud][,title=T]")
    cw.add_argument("--checkout", help="git checkout to mint worktrees from (default: the root)")
    cw.add_argument("--thread", help="must match the bound thread")
    cw.add_argument("--launch", action="store_true", help="spawn the window once; default writes chairs and shows the argv")
    cw.add_argument("--no-widget", action="store_true", help="do not start the widget service after --launch")
    cw.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    ad = sub.add_parser("add", help="one neuron: mint its worktree, join its chair, and launch it: inside tmux a split of your pane; on Windows the thread's own Windows Terminal window (wt -w convoy-<8 hex>: the first neuron opens it, later ones split inside it); elsewhere the thread's detached tmux session")
    ad.add_argument("harness", help="harness id (convoy choices lists them)")
    ad.add_argument("model", nargs="?", help="model id, or auto (the default): no model flag, the harness picks")
    ad.add_argument("--effort", help="effort, or auto (the default): no effort flag; validated against the harness's own keys")
    ad.add_argument("--title", help="chair name (default <harness>-<n>)")
    ad.add_argument("--checkout", help="git checkout to mint the worktree from (default: the root)")
    ad.add_argument("--thread", help="must match the bound thread")
    ad.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for this launch")
    ad.add_argument("--dry-run", action="store_true", help="write nothing; report where the neuron would go")
    ad.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    aw = sub.add_parser("await-seated", help="observe the chairs' seated acks (connected | pending | stale) with the seconds waited")
    aw.add_argument("--seat", action="append", required=True, help="chair session_id (repeat)")
    aw.add_argument("--timeout", type=float, default=120.0, help="seconds; 0 is one snapshot")

    ch = sub.add_parser("choices", help="list installed harnesses, known worktrees, seats, and active-pane support")

    ln = sub.add_parser("launch", description="Launch one already-joined fresh chair. The card's placement says where: split (inside tmux, a split of your pane), thread-window (Windows: the thread's own Windows Terminal window (wt -w convoy-<8 hex>: the first neuron opens it, later ones split inside it); the card names the window), or detached (on POSIX outside tmux with tmux installed, the thread's detached tmux session; the card's attach command opens it).",
                        help="launch one already-joined fresh chair: a split of your tmux pane, the thread's own Windows Terminal window, or the thread's detached tmux session")
    ln.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for this launch")
    ln.add_argument("--seat", required=True, help="fresh join/swap chair session_id")
    ln.add_argument("--dry-run", action="store_true")
    ln.add_argument("--consent", help="one-time scoped consent returned by `convoy consent --grant`")
    ln.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    cs = sub.add_parser("consent", help="grant a prior consent request after the user explicitly approves it")
    cs.add_argument("--grant", required=True, metavar="REQUEST_ID")

    cl = sub.add_parser("close", help="request closure of one exact Convoy-managed pane")
    cl.add_argument("--seat", required=True)
    cl.add_argument("--consent", help="one-time close-chair consent")

    ng = sub.add_parser("nudge", help="wake an idle chair on this machine: proven pane + consent + exact keys; delivery=nudged never delivered")
    ng.add_argument("--seat", required=True)
    ng.add_argument("--keys", help="exact keystroke the consent card names")
    ng.add_argument("--target", help="tmux pane id for send-keys -t")
    ng.add_argument("--dry-run", action="store_true", help="identify only; never send, never consume consent")
    ng.add_argument("--consent", help="one-time nudge-pane consent returned by `convoy consent --grant`")
    ng.add_argument("--walk", action="store_true", help="opt-in: when the WT title is not unique, Alt+Arrow-walk the recorded crew window, re-reading the title; type only into a pane a rule proves is this chair")
    ng.add_argument("--force", action="store_true", help="repeat a nudge whose last nudge_id has no ack from the chair yet (refused otherwise)")

    cwr = sub.add_parser("crew-window", help="record THE Windows Terminal window of this crew as a kind=crew-window feed row (hwnd); the only writer nudge --walk reads")
    cwr.add_argument("--hwnd", type=int, help="window handle of a visible Windows Terminal window")
    cwr.add_argument("--foreground", action="store_true", help="record the window that has the foreground now (run it from inside the crew window)")

    sw = sub.add_parser("swap")
    sw.add_argument("--seat", required=True, help="chair session_id (identity survives the swap)")
    sw.add_argument("--to", required=True, help="replacement harness")
    sw.add_argument("--model")
    sw.add_argument("--effort", help="declared effort for the incoming harness; unset, the old one survives only if that harness takes it")
    sw.add_argument("--handoff", required=True, help="fresh .convoy/handoff/<chair>-<ts>.md file written by the outgoing neuron")
    sw.add_argument("--as", dest="author", required=True, help="outgoing neuron's session_id (neuron-authored; conductor asks via stamp)")

    fo = sub.add_parser("focus", help="ask the pane host to highlight one chair; focused:false with reason until a host adapter is evidenced")
    fo.add_argument("--seat", required=True, help="chair session_id")
    fo.add_argument("--target", help="host pane id (tmux select-pane -t); omitted -> focused:false")

    wg = sub.add_parser("widget", help="always-on-top tkinter strip: one dot per thread from recent(), expand chairs, click -> focus")
    wg.add_argument("--topmost", dest="topmost", action="store_true", default=True)
    wg.add_argument("--no-topmost", dest="topmost", action="store_false")
    wg.add_argument("--refresh", type=float, default=3.0, help="seconds between model rebuilds (default 3)")
    wg.add_argument("--service", action="store_true", help="start one detached widget per machine (pidfile $CONVOY_HOME/widget.pid); alive -> already:true, no second window")
    wg.add_argument("--engine", default="auto", choices=["auto", "webview", "edge", "browser", "tk"], help="auto: pywebview (WebView2 + acrylic) if importable, else Edge --app, else the browser; tk is the legacy strip")
    wg.add_argument("--width", type=int, default=560)
    wg.add_argument("--height", type=int, default=760)
    wg.add_argument("--no-glass", dest="glass", action="store_false", default=True, help="opaque window instead of the translucent acrylic shell")

    sd = sub.add_parser("seated")
    sd.add_argument("--seat", required=True)
    sd.add_argument("--token", required=True, help="token from the join/swap row (proof-of-life echo)")
    sd.add_argument("--incarnation", type=int, default=None,
                    help="the life your boot prompt named; an ack from an older life is not this body's proof")

    gr = sub.add_parser("graph", help="read-only ontology of the thread: chairs, occupants, talk, resume availability (never tokens)")
    gr.add_argument("--neuron", help="one chair's neighborhood: its connected parties + the thread pointer to resume from")
    gr.add_argument("--html", action="store_true", help="render the graph as a self-contained local page (thread side panel + per-chair resume command; no tokens)")
    gr.add_argument("--out", help="file to write with --html (default .convoy/graph.html under the root)")
    gr.add_argument("--also-root", action="append", default=[], help="another root whose thread the page should also show")

    sk = sub.add_parser("skills", help="(re)install the Convoy-owned AGENTS.md pointer and convoy-end copies into a worktree; refreshes stale copies after an upgrade")
    sk.add_argument("--worktree", required=True)
    sk_opt = sk.add_mutually_exclusive_group()
    sk_opt.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)
    sk_opt.add_argument("--no-write-repo-files", action="store_true",
                        help="withdraw an earlier --write-repo-files for this worktree; files already written stay")

    sc = sub.add_parser("start-card", help="read-only: the start card for this thread (where, who, commitments, board, next); one line per item")
    sc.add_argument("--json", action="store_true", help="print the whole card as JSON")
    sc.add_argument("--all", action="store_true", help="lift the 60-line budget")
    nr = sub.add_parser("neurons", help="who is active on this thread and the command that messages each: bus recency first, process evidence second, never a token")
    nr.add_argument("--since", help="ISO UTC lower bound for active (default: last 90 minutes)")
    nr.add_argument("--all", action="store_true", help="every thread the machine index knows, one flat table: harness | model | neuron | thread")

    sub.add_parser("panes", help="every body of every neuron on this thread from the OS process table: pid, via token|cwd, duplicates, unassigned harness processes; never a token")

    th = sub.add_parser("threads", help="every Convoy thread this machine knows (the global index; present=false when a root is gone)")
    th.add_argument("--prune", action="store_true",
                    help="drop rows whose root is under the OS temp dir or is absent; reports every dropped row")

    rs = sub.add_parser("resume", help="resume one neuron at its most recent place: native argv + cwd (dry) or --go to spawn once")
    rs.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for --go")
    rs.add_argument("--neuron", required=True, help="chair session_id")
    rs.add_argument("--go", action="store_true", help="spawn in the chair's worktree, inheriting this terminal; refuses when a live body holds the chair")

    sl = sub.add_parser("seats")
    sl.add_argument("--convoy-id")

    at = sub.add_parser("attach")
    at.add_argument("thread", nargs="?", help="the thread: its cvy_ id, a unique prefix of it of at least 8 characters, its name, or its root path (--read-only takes the exact cvy_ id)")
    at.add_argument("--read-only", action="store_true", help="legacy catch-up only; does not seat this session")
    at.add_argument("--as-harness", help="assert the calling harness; never substitutes for native proof")
    ls = sub.add_parser("list", help="deterministic machine-wide thread picker")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--all", action="store_true")
    ls.add_argument("--since")
    dt = sub.add_parser("detach", help="detach this session without closing it")
    dt.add_argument("--thread")

    bn = sub.add_parser("bind")
    bn.add_argument("--thread", required=True)

    ld = sub.add_parser("lead")
    ld.add_argument("--to", help="a chair session_id (identified neuron; needs --as) or, legacy, a harness name with a seated chair")
    ld.add_argument("--as", dest="author", help="the seated chair passing lead: the current lead, or any seated chair while the lead is unset or dangling")
    ld.add_argument("--thread", help="the thread to act on, as attach takes it (cvy_ id or a prefix of 8+ characters, thread name, or root path); same as --root <that root>")

    for name in ("bring-up", "open"):
        bu = sub.add_parser(name)
        bu.add_argument("--allow-unverified-launch", action="store_true", help="explicitly accept unverified harness launch eligibility for this launch")
        bu.add_argument("convoy_id", nargs="?")
        bu.add_argument("--thread")
        bu.add_argument("--seat", action="append", help="bring up only this chair (repeat); default every chair")
        bu.add_argument("--dry-run", action="store_true")
        bu.add_argument("--write-repo-files", action="store_true", help=_WRITE_REPO_FILES_HELP)

    tm = sub.add_parser("terminals")
    tm.add_argument("convoy_id", nargs="?")
    tm.add_argument("--thread")

    for name in ("hide", "minimize", "background"):
        hd = sub.add_parser(name)
        hd.add_argument("convoy_id", nargs="?")
        hd.add_argument("--thread")
        hd.add_argument("--dry-run", action="store_true")
        if name == "hide":
            hd.add_argument("--mode", default="minimize", choices=["minimize", "hide"])

    ins = sub.add_parser("install")
    ins.add_argument("--to", default=None, help="a vendor harness to install (grok, claude, codex, cursor-agent, agy)")
    ins.add_argument("--opt-in", action="store_true")
    ins.add_argument("--dry-run", action="store_true", default=True)
    ins.add_argument("--live", action="store_true", help="run installer; still requires --opt-in")
    ins.add_argument("--local", action="store_true", help="this machine's Convoy supervisors: origin task, tunnel task, console script; dry by default, --live --opt-in registers, --verify reads back")
    ins.add_argument("--verify", action="store_true", help="with --local: read back the supervisors and the console script, register nothing")
    ins.add_argument("--token-file", default=None, help="with --local: the cloudflared tunnel token FILE the wrapper reads at run time (default CONVOY_HOME/tunnel/run.token)")
    ins.add_argument("--port", type=int, default=8788, help="with --local: the origin's loopback port")

    ins.add_argument("--bound", action="store_true", help="with --local: pin the origin to --root (must be a bound thread); default serves every thread and each call names its thread")
    ins.add_argument("--migrate-token", action="store_true", help="with --local: copy the token FILE named by --token-file into CONVOY_HOME/tunnel/run.token (bytes only, never printed) so the plan and the live task share one home")
    ins.add_argument("--pair", action="store_true", help="with --local: pair this machine to a Worklanes org; writes CONVOY_HOME/origin.json (a pointer to the credential FILE, never its bytes) and proves it with one beat")
    ins.add_argument("--unpair", action="store_true", help="with --local: delete CONVOY_HOME/origin.json; the credential file is left alone")
    ins.add_argument("--org", default=None, help="with --pair: the Worklanes org id")
    ins.add_argument("--user", default=None, help="with --pair: your platform user id")
    ins.add_argument("--credential-file", default=None, help="with --pair: the FILE holding the origin credential; read at call time, never copied, never printed")
    ins.add_argument("--api-base", default=None, help="with --pair: the platform origin, e.g. https://deployforward.dev")
    ins.add_argument("--machine-id", default=None, help="with --pair: override the derived machine key (hostname+home, hashed)")

    cd = sub.add_parser("conductor", help="the conductor's identity on the wire: mint a bearer (shown once, only its hash kept), list, revoke")
    cd.add_argument("action", choices=["mint", "list", "revoke"])
    cd.add_argument("id", nargs="?", help="with revoke: the bearer id from `conductor list`")
    cd.add_argument("--label", default=None, help="with mint: what holds this bearer (a connector name); never the bearer itself")
    cd.add_argument("--conductor", default=None, help="with mint: the conductor id this bearer speaks as (default grok-bot)")

    wk = sub.add_parser("wake", help="wakes on this root: enable (a person opts in), disable, status (read-only)")
    wk.add_argument("action", choices=["enable", "disable", "status"])
    wk.add_argument("--by", default="person", help="with enable: who turns wakes on; recorded as a claim")

    gl = sub.add_parser("glance")
    gl.add_argument("--thread")
    gl.add_argument("--convoy-id")
    gl.add_argument("--json", action="store_true", default=True)
    gl.add_argument("--tray", action="store_true", help="render glance in tray/app-indicator")
    gl.add_argument("--refresh-seconds", type=int, default=60)

    go = sub.add_parser("start", help="resolve a path, URL, owner/repo or project name; safely refresh and onboard; never launch")
    go.add_argument("repo", nargs="?", help="local path, git URL, owner/repo or semantic project name; omitted: thread picker")
    go.add_argument("--to", action="append", help="harness you already have (repeat); default: those on PATH")
    go.add_argument("--thread")
    go.add_argument("--cancel", action="store_true", help="do not bind; leave unbound")
    go.add_argument("--write-repo-files", action="store_true",
                    help="also write the hooks, AGENTS.md pointer and skill copies listed as would_write into the repo")
    go.add_argument("--search-root", action="append", help="project search directory, one level deep (repeat)")
    go.add_argument("--scan-budget", type=float, default=5.0, help="local discovery time budget in seconds")
    go.add_argument("--create", action="store_true", help="explicitly create an unmatched bare-name private GitHub repo")
    go.add_argument("--all", action="store_true", help="expand linked worktrees in an ambiguous checkout picker")

    ob = sub.add_parser("onboard")
    ob.add_argument("--to", action="append", required=True, help="named harness id(s) you already have")
    ob.add_argument("--thread")
    ob.add_argument("--checkout-root", help="existing path, or a git URL cloned under $CONVOY_HOME/checkouts/<owner>/<repo>")
    ob.add_argument("--github", choices=("yes", "no"), default=None, help="record the wizard's GitHub? answer on the bind")
    ob.add_argument("--write-repo-files", action="store_true",
                    help="also write the hooks, AGENTS.md pointer and skill copies listed as would_write into the repo")

    pf = sub.add_parser("preflight", help="fail-closed wizard preflight: live MCP tools/list vs the verbs the @convoy wizard needs")
    pf.add_argument("--url", default=None, help="MCP endpoint (default: your own Convoy, http://127.0.0.1:8788/mcp)")
    pf.add_argument("--tools", default=None, help="comma-separated tool names to score offline instead of fetching")

    mcp = sub.add_parser("mcp")
    mcp.add_argument("--root", default=argparse.SUPPRESS, help="layer root (also accepted after subcommand)")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8788)

    args = p.parse_args(raw_argv)
    root_explicit = any(arg == "--root" or arg.startswith("--root=") for arg in raw_argv)
    root = Path(args.root).resolve()
    # Chats launch from project subfolders: for read verbs, walk up to the
    # nearest .convoy/id when the given root has none (never for writes).
    if args.cmd in ("graph", "threads", "panes", "resume", "seats", "feed", "context", "glance", "inbox", "provenance", "rebase", "focus") and not (root / ".convoy" / "id").is_file():
        found = find_root(root)
        if found is not None:
            root = found

    if args.cmd == "end":
        from .end import end_task

        if (args.seat or args.all) and not args.hook:
            from .end_all import end_all
            card = end_all(root, seat=args.seat, push=bool(args.push), summary=args.summary,
                           include_archived=bool(args.include_archived))
            print(json.dumps(card, ensure_ascii=False))
            return 0 if card.get("ok") else 1
        payload = None
        if args.hook:
            try:
                raw = sys.stdin.read()
                parsed = json.loads(raw) if raw.strip() else None
                payload = parsed if isinstance(parsed, dict) else {"hook_event_name": "invalid"}
            except (OSError, json.JSONDecodeError):
                payload = {"hook_event_name": "invalid"}
        card = end_task(
            root=root if root_explicit else None,
            cwd=Path.cwd(),
            summary=None if args.hook else args.summary,
            push=bool(args.push),
            hook_payload=payload,
        )
        if args.hook:
            # Both Codex and Claude Stop hooks expect hook protocol JSON, not
            # Convoy's result card. Heartbeat failures are advisory and must
            # never trap the agent in a Stop loop.
            if not card.get("ok") and card.get("error"):
                print("convoy end heartbeat: " + str(card["error"]), file=sys.stderr)
            # end_task decides the hook protocol answer - {} for a clean
            # stop, or decision=block with the rows to work or the quota
            # ceiling to hand off at. Printing a hardcoded {} here is why
            # Claude and Codex ended their turn beside a full inbox while only
            # Grok kept working.
            out = card.get("hook")
            print(json.dumps(out if isinstance(out, dict) else {}))
            return 0
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "whoami":
        if not root_explicit and not read_id(root):
            # No thread here: the session itself says which thread it sits on. On several
            # it refuses with the list; whoami answers for one thread.
            from .sessions import proven_session_chairs, several_threads_error
            try:
                hits = proven_session_chairs(Path.cwd())
            except ValueError:
                hits = []
            if len(hits) > 1:
                print(json.dumps({"ok": False, "chair": None, "error": several_threads_error(hits),
                                  "threads": [{"convoy_id": read_id(r), "root": str(r), "chair": s.get("session_id")}
                                              for r, s in hits]}))
                return 1
            if hits:
                root = Path(hits[0][0])
        me = identify(root, explicit_root=root_explicit)
        if me.get("chair"):
            from .launcher import whoami_fields
            me.update(whoami_fields(root, me["chair"]))
        print(json.dumps(me))
        return 0 if me.get("ok") else 1
    if args.cmd == "hook":
        instance_id = args.instance_id
        verified_by = None
        # Explicit authorship is legacy-compatible when no body can be
        # identified, but it cannot override a different proved chair.
        me = identify(root, explicit_root=root_explicit) if (args.as_me or instance_id) else None
        if instance_id and me and me.get("chair") and instance_id != me["chair"]:
            print(json.dumps({"ok": False, "error": "refuse hook: explicit author disagrees with this body's verified chair", "whoami": me}))
            return 1
        if getattr(args, "as_me", False):
            if not me or not me.get("chair"):
                print(json.dumps({"ok": False, "error": "refuse --as-me: no chair on this thread matches this body", "whoami": me}))
                return 1
            instance_id = me["chair"]
        if args.kind in STAMPED_KINDS and me and me.get("chair") == instance_id:
            verified_by = me.get("via")
        try:
            to = args.to
            if args.kind == "note":
                from .wake_dispatch import receipt_address
                to = receipt_address(root, args.summary, instance_id, to)
            row = hook(root, args.kind, args.summary, instance_id=instance_id,
                       to=to, verified_by=verified_by)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(row))
        return 0
    if args.cmd == "feed":
        try:
            since_iso = parse_since(args.since)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        rows = feed_since(root, since_iso)
        print(json.dumps({"schema_version": SCHEMA_VERSION, "since": args.since, "since_iso": since_iso, "events": rows}))
        return 0
    if args.cmd == "relaunch":
        if args.dry_run and args.write_repo_files:
            print(json.dumps({"ok": False, "dry_run": True, "chairs": [], "error": dry_opt_in_refusal(args.cmd, cli=True)}))
            return 1
        card = relaunch(root, thread=args.thread, runner=None if args.dry_run else live_runner, timeout=args.timeout, seats=args.seat, take_over=args.take_over, allow_unverified_launch=args.allow_unverified_launch,
                       write_repo_files=_opt_in(args))
        if card.get("ok") and not args.dry_run:
            card["widget_service"] = auto_widget_service(disabled=bool(args.no_widget))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "rail":
        if not (root / ".convoy" / "id").is_file():
            # A neuron runs this from its worktree: the pointer bring-up wrote
            # there, or the thread index seating this worktree, names the
            # thread root, so the rail it reads is the lead's rail.
            root = root_for(root) or root
        try:
            card = build_rail(root, since=args.since)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "committed":
        chair = args.author
        if args.as_me:
            me = identify(root, explicit_root=root_explicit)
            chair = me.get("chair")
            if not chair:
                print(json.dumps({"ok": False, "error": "refuse committed --as-me: no chair on this thread matches this body", "whoami": me}))
                return 1
        try:
            card = record_commit(root, str(chair or ""), rev=args.rev, worktree=args.worktree)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0
    if args.cmd == "provenance":
        try:
            card = build_provenance(root, since=args.since)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0
    if args.cmd == "rebase":
        if not args.check:
            print(json.dumps({"ok": False, "error": "this verb only reports; run git rebase yourself"}))
            return 1
        card = rebase_check(args.worktree or Path.cwd(), base=args.base or "feat/happy-path-proof", root=root)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "stamp":
        try:
            row = conductor_stamp(
                root,
                args.summary,
                agent=args.agent,
                model=args.model,
                effort=args.effort,
                instance_id=args.instance_id,
                transcript=args.transcript,
            )
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(row))
        return 0
    if args.cmd == "context":
        print(json.dumps(pack(root, instance_id=args.instance_id)))
        return 0
    if args.cmd == "inbox":
        from .inbox import drain, hook_pretooluse, pending, seat_for_worktree, seats_for_worktree
        if args.hook_pretooluse:
            print(json.dumps(hook_pretooluse()))
            return 0
        sid = str(args.seat or "").strip()
        if not sid:
            matches = seats_for_worktree(root, Path.cwd())
            if len(matches) > 1:
                chairs = [str(r.get("session_id") or "") for r in matches]
                print(json.dumps({
                    "ok": False,
                    "error": "inbox refuse: cwd matches more than one chair; pass --seat",
                    "chairs": chairs,
                }))
                return 1
            row = matches[0] if matches else None
            sid = str((row or {}).get("session_id") or "").strip()
        if not sid:
            print(json.dumps({"ok": False, "error": "inbox requires --seat"}))
            return 1
        if getattr(args, "wait", False):
            from .inbox import wait_for_pending
            card = wait_for_pending(root, sid, timeout=args.timeout)
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if args.drain:
            taken = drain(root, sid)
            print(json.dumps({"ok": True, "session_id": sid, "drained": taken, "n": len(taken)}))
            return 0
        waiting = pending(root, sid)
        print(json.dumps({"ok": True, "session_id": sid, "pending": waiting, "n": len(waiting)}))
        return 0
    if args.cmd == "probe":
        print(json.dumps(probe(args.to)))
        return 0
    if args.cmd == "init":
        cid = ensure_id(root)
        print(json.dumps({"ok": True, "convoy_id": cid}))
        return 0
    if args.cmd == "id":
        print(json.dumps({"convoy_id": read_id(root)}))
        return 0
    if args.cmd == "seat":
        row = seat(
            root,
            args.to,
            args.session_id,
            worktree=args.worktree,
            model=args.model,
            resume=args.resume,
            title=args.title,
            agent=args.agent,
            effort=args.effort,
            where=args.where,
        )
        print(json.dumps(row))
        return 0
    if args.cmd in ("join", "swap", "seated"):
        try:
            if args.cmd == "join":
                resolved = None
                if args.launch:
                    # Who is launching, before any write: an unproven launcher refuses here.
                    from .launcher import refusal
                    resolved = resolve_launcher(root, explicit_root=root_explicit)
                    refused = refusal(resolved)
                    if refused:
                        print(json.dumps(refused))
                        return 1
                card = join(root, args.to, session_id=args.session_id, worktree=args.worktree,
                            model=args.model, title=args.title, effort=args.effort, author=args.author,
                            where=args.where, calling_session=not args.launch)
                recorded = None
                if args.launch and not card.get("already"):
                    # Only after the join succeeded: a refused join attaches nobody.
                    recorded = _record_launcher(root, [card["seat"]["session_id"]], resolved=resolved,
                                                    explicit_root=root_explicit)
                    if recorded and recorded.get("refuse"):
                        print(json.dumps({**card, **recorded["refuse"]}))
                        return 1
                if args.launch and not card.get("already"):
                    sid = card["seat"]["session_id"]
                    launched = _claimed_launch(root, sid, recorded, lambda claimed: launch_seat(
                        root,
                        sid,
                        runner=active_pane_runner,
                        consent=args.consent,
                        allow_unverified_launch=args.allow_unverified_launch,
                        write_repo_files=_opt_in(args),
                        claimed=claimed,
                    ))
                    card["launch"] = launched
                    _with_launcher(card, recorded)
                    card["seat"] = next(s for s in list_seats(root) if s.get("session_id") == sid)
                    card["ok"] = bool(card.get("ok")) and bool(launched.get("ok"))
                    if launched.get("ok"):
                        card["next"] = "seated"
                    elif launched.get("state") == "awaiting-user-consent":
                        card["next"] = "consent"
                    else:
                        card["next"] = "launch"
            elif args.cmd == "swap":
                card = swap(root, args.seat, to=args.to, handoff=args.handoff,
                            author=args.author, model=args.model, effort=args.effort)
            else:
                me = identify(root, explicit_root=root_explicit)
                if me.get("chair") and me["chair"] != args.seat:
                    raise ValueError("refuse seated: this body proves another chair")
                card = seated_ack(root, args.seat, token=args.token,
                                  incarnation=getattr(args, "incarnation", None),
                                  verified_by=me.get("via") if me.get("chair") == args.seat else None)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "focus":
        card = focus_seat(root, args.seat, target=getattr(args, "target", None))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "widget":
        if args.service:
            card = ensure_widget_service(convoy_home())
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if args.engine != "tk":
            from .widget_web import run_web_widget
            card = run_web_widget(engine=args.engine, topmost=bool(args.topmost), refresh=float(args.refresh or 3.0),
                                  width=int(args.width), height=int(args.height), glass=bool(args.glass))
        else:
            card = run_widget(topmost=bool(args.topmost), refresh=float(args.refresh or 3.0))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "crew":
        try:
            seats = [_seat_spec(s) for s in args.seat]
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        card = crew(root, seats, thread=args.thread, checkout=args.checkout,
                    runner=live_runner if args.launch else None, allow_unverified_launch=args.allow_unverified_launch,
                    write_repo_files=_opt_in(args),
                    launcher=resolve_launcher(root, explicit_root=root_explicit))
        if card.get("ok") and args.launch:
            card["widget_service"] = auto_widget_service(disabled=bool(args.no_widget))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "add":
        if args.dry_run and args.write_repo_files:
            print(json.dumps({"ok": False, "dry_run": True, "error": dry_opt_in_refusal(args.cmd, cli=True)}))
            return 1
        card = add_neuron(root, args.harness, args.model, effort=args.effort, title=args.title, thread=args.thread,
                          checkout=args.checkout, runner=None if args.dry_run else active_pane_runner,
                          window_runner=None if args.dry_run else live_runner,
                          allow_unverified_launch=args.allow_unverified_launch, write_repo_files=_opt_in(args),
                          launcher=resolve_launcher(root, explicit_root=root_explicit))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "await-seated":
        try:
            card = await_seated(root, args.seat, timeout=args.timeout)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "choices":
        card = launch_choices(root)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "launch":
        recorded = None if args.dry_run else _record_launcher(root, [args.seat], explicit_root=root_explicit)
        if recorded and recorded.get("refuse"):
            print(json.dumps({"session_id": args.seat, **recorded["refuse"]}))
            return 1
        card = _claimed_launch(root, args.seat, recorded, lambda claimed: launch_seat(
            root,
            args.seat,
            runner=None if args.dry_run else active_pane_runner,
            consent=args.consent,
            allow_unverified_launch=args.allow_unverified_launch,
            write_repo_files=_opt_in(args),
            claimed=claimed,
        ), dry=bool(args.dry_run))
        _with_launcher(card, recorded)
        if args.dry_run:
            _would_refuse(root, [args.seat], card, explicit_root=root_explicit)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "consent":
        try:
            card = grant_consent(root, args.grant)
        except ValueError as e:
            card = {"ok": False, "error": str(e)}
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "close":
        card = close_managed_pane(root, args.seat, consent=args.consent)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "nudge":
        card = nudge_seat(
            root,
            args.seat,
            consent=args.consent,
            keys=args.keys,
            dry_run=args.dry_run,
            target=args.target,
            walk=bool(getattr(args, "walk", False)),
            force=bool(getattr(args, "force", False)),
        )
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "crew-window":
        card = record_crew_window(root, hwnd=args.hwnd, foreground=bool(args.foreground))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "seats":
        print(json.dumps(list_seats(root, convoy_id=args.convoy_id)))
        return 0
    if args.cmd == "graph":
        if args.html:
            known = [Path(r["root"]) for r in routable_threads()]
            # the given root counts only when it actually carries a thread (never invent)
            roots = ([root] if read_id(root) else []) + [Path(r) for r in args.also_root]
            roots += [k for k in known if k.resolve() not in {r.resolve() for r in roots}]
            threads = [{"root": str(r), "graph": build_graph(r)} for r in roots]
            out = Path(args.out) if args.out else (root / ".convoy" / "graph.html")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_html(threads), encoding="utf-8")
            skipped = [{"root": r.get("root"), "reason": r["skip_reason"]}
                       for r in list_threads() if r.get("skip_reason") in {"temp", "root gone"}]
            print(json.dumps({"ok": True, "path": str(out), "threads": len(threads), "skipped": skipped}))
            return 0
        try:
            card = neighborhood(root, args.neuron) if args.neuron else build_graph(root)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0
    if args.cmd == "threads":
        if getattr(args, "prune", False):
            card = prune_threads()
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        print(json.dumps({"ok": True, "index": str(index_path()), "threads": list_threads()}))
        return 0
    if args.cmd == "panes":
        print(json.dumps(bodies(root)))
        return 0
    if args.cmd == "start-card":
        from .start_card import LINE_BUDGET, build_start_card
        card = build_start_card(root, budget=None if args.all else LINE_BUDGET)
        print(json.dumps(card) if args.json else "\n".join(card["lines"]))
        return 0
    if args.cmd == "neurons":
        if getattr(args, "all", False):
            from .activity import neurons_everywhere
            print(json.dumps(neurons_everywhere(since=args.since)))
            return 0
        print(json.dumps(neuron_activity(root, since=args.since)))
        return 0
    if args.cmd == "skills":
        # Refresh BOTH halves of a neuron's install: the skill text and the
        # inbox hooks (probed command + root pointer). A long-lived pane that
        # got only the text stayed deaf (audit 2026-09-03).
        # The same rule as a launch: every file in a worktree Convoy minted or one the person opted
        # into before, else only the Convoy-named ones (kept out of git) until --write-repo-files.
        withdrawn = withdraw_repo_files_opt_in(args.worktree) if args.no_write_repo_files else None
        if args.write_repo_files:
            record_repo_files_opt_in(args.worktree)
        person = repo_files_opted_in(args.worktree) or is_minted_worktree(args.worktree)
        local = CLAUDE_SETTINGS_RELATIVE.as_posix()
        skip = {local} if is_tracked(args.worktree, local) else set()
        skills = install_neuron_identity(args.worktree, person_files=person)
        hooks = ensure_inbox_hooks(args.worktree, root=root if read_id(root) else None, skip=skip)
        missing = [] if person else person_files_missing(args.worktree)
        card = {**skills, "skills_ok": bool(skills.get("ok")), "hooks": hooks,
                "would_write": sorted(set(missing) | (skip & {local})),
                "notes": ([TRACKED_SETTINGS_NOTE] if local in skip else []) + (
                    [CODEX_HOOKS_MIGRATION_NOTE] if _codex_worktree(root, args.worktree)
                    and stale_codex_hooks(args.worktree) else []),
                **({"withdrawn": withdrawn} if withdrawn is not None else {}),
                "ok": bool(skills.get("ok")) and bool(hooks.get("ok"))}
        try:
            record = ["/" + REPO_FILES_RECORD.as_posix()] if args.write_repo_files else []
            card["excluded"] = exclude_paths(args.worktree, ["/" + f for f in repo_files_for(None)
                                                             if _convoy_named(f) and f not in skip] + record)
        except OSError as e:
            card["exclude_error"] = type(e).__name__ + ": " + str(e)
        print(json.dumps(card))
        return 0 if card["ok"] else 1
    if args.cmd == "resume":
        try:
            card = resume_neuron(root, args.neuron, go=args.go, allow_unverified_launch=args.allow_unverified_launch)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "attach":
        from .sessions import attach_session
        from .thread_list import format_list
        card = attach(root, convoy_id=args.thread) if args.read_only else attach_session(args.thread, as_harness=args.as_harness)
        if "list" in card:
            print(format_list(card["list"]))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "list":
        from .thread_list import thread_list, format_list
        try:
            card = thread_list(all_threads=args.all, since=args.since)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1
        print(json.dumps(card) if args.json else format_list(card))
        return 0
    if args.cmd == "detach":
        from .sessions import detach_session
        from .inbox import resolve_root
        card = detach_session(root=root if root_explicit else (resolve_root(Path.cwd()) or root), thread=args.thread)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "lead":
        if args.thread:
            from .sessions import resolve_thread
            try:
                root = resolve_thread(args.thread)
            except (OSError, ValueError) as e:
                print(json.dumps({"ok": False, "error": str(e)}))
                return 1
        if args.to:
            try:
                # A lead change is authored by the proven calling chair (environment or token
                # proof; a cwd match is not enough). --as asserts it and never overrides it.
                me = identify(root, explicit_root=root_explicit)
                proven = me.get("chair") if me.get("ok") and me.get("via") in ("environment", "token") else None
                if not proven:
                    raise ValueError("refuse lead change: cannot prove the calling chair (environment or token"
                                     " proof); a cwd match is not enough")
                if args.author and args.author != proven:
                    raise ValueError("refuse lead change: --as " + args.author + " disagrees with this body's"
                                     " proven chair " + proven)
                is_chair = any(s.get("session_id") == args.to for s in list_seats(root))
                if is_chair:
                    print(json.dumps(pass_lead(root, args.to, author=proven)))
                else:
                    print(json.dumps(lead_to_harness(root, args.to, author=proven)))
                return 0
            except ValueError as e:
                print(json.dumps({"ok": False, "error": str(e)}))
                return 1
        from .activity import neuron_id
        state = lead_state(root)
        cid = read_id(root)
        print(json.dumps({"conductor": state["chair"], "lead": state["lead"], "lead_chair": state["chair"],
                          "dangling": state["status"] == "dangling",
                          "reachable_id": neuron_id(cid, state["chair"]), "convoy_id": cid}))
        return 0
    if args.cmd == "bind":
        try:
            print(json.dumps(bind(root, args.thread)))
            return 0
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
    if args.cmd in ("bring-up", "open"):
        if args.dry_run and args.write_repo_files:
            print(json.dumps({"ok": False, "dry_run": True, "windows": [], "error": dry_opt_in_refusal(args.cmd, cli=True)}))
            return 1
        runner = None if args.dry_run else live_runner
        recorded = None if args.dry_run else _record_launcher(root, args.seat, explicit_root=root_explicit)
        if recorded and recorded.get("refuse"):
            print(json.dumps({"windows": [], **recorded["refuse"]}))
            return 1
        card = _spawn_settled(root, recorded, lambda: bring_up(
            root, convoy_id=args.convoy_id, thread=args.thread, runner=runner, session_ids=args.seat,
            allow_unverified_launch=args.allow_unverified_launch, write_repo_files=_opt_in(args),
            exclude=(recorded or {}).get("claim_refused") or None),
            lambda c: [str(w.get("session_id")) for w in c.get("windows") or []
                       if isinstance(w, dict) and w.get("ok") and w.get("session_id")])
        _with_launcher(card, recorded)
        if args.dry_run:
            _would_refuse(root, args.seat, card, explicit_root=root_explicit)
        print(json.dumps(card))
        if args.dry_run:
            existing = {s.get("session_id") for s in list_seats(root, convoy_id=card.get("convoy_id"))}
            minted = [w.get("session_id") for w in (card.get("windows") or []) if w.get("session_id") and w.get("session_id") not in existing]
            if minted:
                print("error: dry-run minted a session_id", file=sys.stderr)
                return 2
        return 0 if card.get("ok") else 1
    if args.cmd == "terminals":
        card = terminals(root, convoy_id=args.convoy_id, thread=args.thread)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd in ("hide", "minimize", "background"):
        mode = "minimize"
        if args.cmd == "hide":
            mode = getattr(args, "mode", None) or "minimize"
        applier = None if args.dry_run else live_applier
        card = hide_windows(root, convoy_id=args.convoy_id, thread=args.thread, mode=mode, applier=applier)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "conductor":
        from . import bearer
        if args.action == "mint":
            # The card is the one and only place the bearer appears. The operator runs this
            # in their own terminal and hands it to the connector; it is never on the
            # record, in a log, or in a transcript by Convoy's doing.
            card = bearer.mint(conductor=args.conductor or CONDUCTOR, label=args.label)
        elif args.action == "revoke":
            card = bearer.revoke(args.id or "") if args.id else {"ok": False, "error": "revoke needs the bearer id (see `convoy conductor list`)"}
        else:
            card = {"ok": True, "path": str(bearer.conductors_path()), "conductors": bearer.list_conductors()}
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "wake":
        from .wake_local import disable, enable
        from .wake_service import wake_status
        if not (root / ".convoy" / "id").is_file():
            card = {"ok": False, "error": "not a Convoy thread root: " + str(root)}
        elif args.action == "enable":
            try:
                enable(root, by=args.by)
                card = wake_status(root)
            except ValueError as e:
                card = {"ok": False, "error": str(e)}
        elif args.action == "disable":
            was = disable(root)
            card = {**wake_status(root), "was_enabled": was}
        else:
            card = wake_status(root)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "install":
        if getattr(args, "local", False) and getattr(args, "unpair", False):
            from .local_install import unpair
            card = unpair()
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if getattr(args, "local", False) and getattr(args, "pair", False):
            from .local_install import pair
            missing = [n for n, v in (("--org", args.org), ("--user", args.user),
                                      ("--credential-file", args.credential_file),
                                      ("--api-base", args.api_base)) if not v]
            if missing:
                print(json.dumps({"ok": False, "error": "pair needs " + ", ".join(missing)}))
                return 1
            card = pair(org_id=args.org, user_id=args.user,
                        credential_file=args.credential_file, api_base=args.api_base,
                        machine_id=getattr(args, "machine_id", None))
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if getattr(args, "local", False):
            from .local_install import install_local
            card = install_local(root, token_file=args.token_file, port=int(args.port), live=bool(args.live),
                                 opt_in=bool(args.opt_in), verify_only=bool(args.verify),
                                 migrate_token=bool(getattr(args, "migrate_token", False)), bound=bool(getattr(args, "bound", False)))
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if not args.to:
            print(json.dumps({"ok": False, "error": "install needs --to <harness> or --local"}))
            return 1
        dry = True
        if getattr(args, "live", False):
            dry = False
        card = install_harness(args.to, dry_run=dry, opt_in=bool(args.opt_in))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "glance":
        if args.tray:
            card = run_tray(
                root,
                thread=getattr(args, "thread", None),
                convoy_id=getattr(args, "convoy_id", None),
                refresh_seconds=max(0, int(getattr(args, "refresh_seconds", 60))),
            )
            if args.json:
                print(json.dumps(card))
            return 0 if card.get("ok") else 1
        card = build_glance(root, thread=getattr(args, "thread", None), convoy_id=getattr(args, "convoy_id", None))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1

    if args.cmd == "start":
        card = run_start(
            root,
            args.repo,
            harnesses=args.to,
            thread=args.thread,
            cancel=bool(args.cancel),
            write_repo_files=bool(args.write_repo_files),
            search_roots=args.search_root,
            scan_budget=args.scan_budget,
            create=args.create,
            all_worktrees=args.all,
        )
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "onboard":
        card = run_onboard(root, args.to, thread=args.thread, checkout_root=args.checkout_root,
                           github=None if args.github is None else args.github == "yes",
                           write_repo_files=bool(args.write_repo_files))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "preflight":
        from .wizard_preflight import PUBLIC_MCP_URL, run_preflight
        tools = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools is not None else None
        card = run_preflight(args.url or PUBLIC_MCP_URL, tools=tools)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "mcp":
        from .mcp_http import serve
        # No explicit --root: the origin serves every thread the machine index
        # knows and each call names its thread (move 3). --root pins it.
        return serve(root if root_explicit else None, host=args.host, port=args.port)
    if args.cmd == "adopt":
        from .adopt import adopt
        from .conductor import RECEIPT_PROOF
        sid = args.seat
        if args.neuron_id:
            from .activity import resolve_neuron_id
            hit = resolve_neuron_id(args.neuron_id)
            if not hit.get("ok"):
                print(json.dumps(hit))
                return 1
            root, sid = Path(hit["root"]), hit["session_id"]
        # A root found from a neuron id is inferred, whatever --root said.
        explicit = root_explicit and not args.neuron_id
        me = identify(root, explicit_root=explicit)
        # A proven caller whose own chair here is detached is re-attached through the launcher
        # path (attach_proven, with its lead rules), so it is resolved like an unseated one.
        own = next((s for s in list_seats(root) if s.get("session_id") == me.get("chair")), {})
        proven = (me.get("ok") and me.get("chair") and me.get("via") in RECEIPT_PROOF
                  and not own.get("detached"))
        card = adopt(root, sid, me=me, launcher=None if proven else resolve_launcher(root, explicit_root=explicit))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd in ("report", "reply"):
        from .route import reply, report
        me = identify(root, explicit_root=root_explicit)
        card = (report(root, args.body, me=me) if args.cmd == "report"
                else reply(root, args.token, args.body, me=me))
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "send":
        runner = native_runner if args.live else fake_runner
        allow_interactive_resume = not bool(args.live)
        wts = args.worktree
        if getattr(args, "neuron_id", None):
            from .activity import resolve_neuron_id
            hit = resolve_neuron_id(args.neuron_id)
            if not hit.get("ok"):
                print(json.dumps(hit))
                return 1
            card = send_one(Path(hit["root"]), hit["to"], args.body, instance_id=hit["session_id"], label=args.label,
                            runner=runner, dry_run=args.dry_run, allow_interactive_resume=allow_interactive_resume,
                            allow_unverified_launch=args.allow_unverified_launch,
                            sender=_proven_sender(Path(hit["root"]), args.dry_run))
            card["id"] = hit["id"]
            card["thread"] = hit["thread"]
            card["root"] = hit["root"]
            print(json.dumps(card))
            return 0 if card.get("ok") else 1
        if not args.to:
            print(json.dumps({"ok": False, "error": "send needs --to <harness> or --id <neuron id>"}))
            return 2
        if wts and len(wts) != len(args.to):
            print("need one --worktree per --to", file=sys.stderr)
            return 2
        if len(args.to) == 1:
            wt = wts[0] if wts else None
            card = send_one(
                root,
                args.to[0],
                args.body,
                instance_id=args.instance_id,
                label=args.label,
                runner=runner,
                dry_run=args.dry_run,
                worktree=wt,
                allow_interactive_resume=allow_interactive_resume,
                allow_unverified_launch=args.allow_unverified_launch,
                sender=_proven_sender(root, args.dry_run, explicit_root=root_explicit),
            )
            print(json.dumps(card))
            if args.dry_run and card.get("session_id"):
                print("error: dry-run minted a session_id", file=sys.stderr)
                return 2
            return 0 if card.get("ok") else 1
        cards = send_many(
            root,
            args.to,
            args.body,
            runner=runner,
            worktrees=wts,
            label=args.label,
            dry_run=args.dry_run,
            allow_interactive_resume=allow_interactive_resume,
            allow_unverified_launch=args.allow_unverified_launch,
            sender=_proven_sender(root, args.dry_run, explicit_root=root_explicit),
        )
        print(json.dumps(cards))
        if args.dry_run and any(c.get("session_id") for c in cards):
            print("error: dry-run minted a session_id", file=sys.stderr)
            return 2
        ids = [c.get("session_id") for c in cards]
        if not all(c.get("ok") for c in cards):
            return 1
        if args.live and len(set(i for i in ids if i)) < 2:
            print("error: parallel send merged session ids", file=sys.stderr)
            return 2
        return 0
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
