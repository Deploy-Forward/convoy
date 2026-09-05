"""convoy CLI. Phase 1: context + send with pointers. Parallel send is Phase 6. Phase 7: convoy_id attach + bring-up + hide."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bringup import bring_up, hide_windows, live_applier, live_runner, terminals
from .consent import grant_consent
from .install import install as install_harness
from .onboard import onboard as run_onboard
from .start import start as run_start
from .context import pack
from .convoy import attach, bind, ensure_id, list_seats, read_id, read_lead, seat, set_lead, CONDUCTOR
from .crew import await_seated, crew
from .glance import build_glance, run_tray
from .graph import build_graph, neighborhood
from .graph_html import render_html, resume_neuron
from .identity import ensure_inbox_hooks, install_neuron_identity
from .index import find_root, index_path, list_threads, prune_threads
from .activity import neuron_activity
from .panes import bodies, identify
from .provenance import build_provenance, rebase_check, record_commit
from .layer import SCHEMA_VERSION, conductor_stamp, feed_since, hook, parse_since
from .rail import build_rail, root_for
from .relaunch import relaunch
from .lifecycle import join, pass_lead, seated_ack, swap
from .focus import focus_seat
from .widget import run_widget
from .nudge import nudge_seat
from .wt_walk import record_crew_window
from .pane_host import close_managed_pane
from .synapse import fake_runner, native_runner, send_many, send_one
from .targeted_launch import active_pane_runner, launch_choices, launch_seat
from .usage import probe

_SEAT_KEYS = ("model", "effort", "where", "title")


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


def main(argv: list[str] | None = None) -> int:
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
    rlx.add_argument("--thread", help="must match the bound thread")
    rlx.add_argument("--timeout", type=float, default=0.0, help="seconds to wait for fresh seated acks; 0 is one snapshot")
    rlx.add_argument("--dry-run", action="store_true", help="show the windows and the per-chair timeline; spawn and write nothing")
    rlx.add_argument("--seat", action="append", help="relaunch only this chair (repeat); default every chair. Use it when some panes are still alive")

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

    s = sub.add_parser("send")
    s.add_argument("--to", action="append", required=True)
    s.add_argument("body")
    s.add_argument("--live", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--label")
    s.add_argument("--instance-id")
    s.add_argument("--worktree", action="append")

    ib = sub.add_parser("inbox", help="queue/drain live-seat messages without stealing a TUI")
    ib.add_argument("--seat")
    ib.add_argument("--drain", action="store_true")
    ib.add_argument("--hook-pretooluse", action="store_true", help="Grok/Claude hook JSON on stdout (reads hook_event_name from stdin; on Stop, blocks the stop with the waiting rows as the reason)")
    ib.add_argument("--wait", action="store_true", help="block until a row is pending or --timeout; run it as a BACKGROUND command at the end of your turn so the arriving row wakes you (grok background-task completion wakes the agent)")
    ib.add_argument("--timeout", type=float, default=3600.0, help="seconds for --wait (default 3600)")

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
    jn.add_argument("--to", required=True, help="harness for the new chair")
    jn.add_argument("--session-id")
    jn.add_argument("--worktree")
    jn.add_argument("--model")
    jn.add_argument("--title")
    jn.add_argument("--effort")
    jn.add_argument("--where", choices=["local", "cloud"], help="local (default) or cloud; cloud is refused unless convoy choices offers it for the harness")
    jn.add_argument("--as", dest="author", help="authoring seat (neuron-authored)")
    jn.add_argument("--launch", action="store_true", help="split exactly one fresh chair into the active supported pane host")
    jn.add_argument("--consent", help="one-time scoped consent returned by `convoy consent --grant`")

    cw = sub.add_parser("crew", help="N neurons at once: mint one worktree per seat, join every chair with a boot prompt, bring them up in ONE window")
    cw.add_argument("--seat", action="append", required=True, metavar="SPEC",
                    help="one per neuron: <harness>[,model=M][,effort=E][,where=local|cloud][,title=T]")
    cw.add_argument("--checkout", help="git checkout to mint worktrees from (default: the root)")
    cw.add_argument("--thread", help="must match the bound thread")
    cw.add_argument("--launch", action="store_true", help="spawn the window once; default writes chairs and shows the argv")

    aw = sub.add_parser("await-seated", help="observe the chairs' seated acks (connected | pending | stale) with the seconds waited")
    aw.add_argument("--seat", action="append", required=True, help="chair session_id (repeat)")
    aw.add_argument("--timeout", type=float, default=120.0, help="seconds; 0 is one snapshot")

    ch = sub.add_parser("choices", help="list installed harnesses, known worktrees, seats, and active-pane support")

    ln = sub.add_parser("launch", help="split one already-joined fresh chair into the active pane host")
    ln.add_argument("--seat", required=True, help="fresh join/swap chair session_id")
    ln.add_argument("--dry-run", action="store_true")
    ln.add_argument("--consent", help="one-time scoped consent returned by `convoy consent --grant`")

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

    sd = sub.add_parser("seated")
    sd.add_argument("--seat", required=True)
    sd.add_argument("--token", required=True, help="token from the join/swap row (proof-of-life echo)")

    gr = sub.add_parser("graph", help="read-only ontology of the thread: chairs, occupants, talk, resume availability (never tokens)")
    gr.add_argument("--neuron", help="one chair's neighborhood: its connected parties + the thread pointer to resume from")
    gr.add_argument("--html", action="store_true", help="render the graph as a self-contained local page (thread side panel + per-chair resume command; no tokens)")
    gr.add_argument("--out", help="file to write with --html (default .convoy/graph.html under the root)")
    gr.add_argument("--also-root", action="append", default=[], help="another root whose thread the page should also show")

    sk = sub.add_parser("skills", help="(re)install the Convoy-owned identity skill copies into a worktree; refreshes stale copies after an upgrade")
    sk.add_argument("--worktree", required=True)

    nr = sub.add_parser("neurons", help="who is active on this thread and the command that messages each: bus recency first, process evidence second, never a token")
    nr.add_argument("--since", help="ISO UTC lower bound for active (default: last 90 minutes)")

    sub.add_parser("panes", help="every body of every neuron on this thread from the OS process table: pid, via token|cwd, duplicates, unassigned harness processes; never a token")

    th = sub.add_parser("threads", help="every Convoy thread this machine knows (the global index; present=false when a root is gone)")
    th.add_argument("--prune", action="store_true",
                    help="drop rows whose root is under the OS temp dir or is absent; reports every dropped row")

    rs = sub.add_parser("resume", help="resume one neuron at its most recent place: native argv + cwd (dry) or --go to spawn once")
    rs.add_argument("--neuron", required=True, help="chair session_id")
    rs.add_argument("--go", action="store_true", help="spawn in the chair's worktree, inheriting this terminal; refuses when a live body holds the chair")

    sl = sub.add_parser("seats")
    sl.add_argument("--convoy-id")

    at = sub.add_parser("attach")
    at.add_argument("convoy_id", nargs="?")

    bn = sub.add_parser("bind")
    bn.add_argument("--thread", required=True)

    ld = sub.add_parser("lead")
    ld.add_argument("--to", help="a chair session_id (identified neuron; needs --as) or, legacy, a harness name")
    ld.add_argument("--as", dest="author", help="the neuron passing lead (neuron-authored; the conductor asks via stamp)")

    for name in ("bring-up", "open"):
        bu = sub.add_parser(name)
        bu.add_argument("convoy_id", nargs="?")
        bu.add_argument("--thread")
        bu.add_argument("--dry-run", action="store_true")

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
    ins.add_argument("--to", required=True)
    ins.add_argument("--opt-in", action="store_true")
    ins.add_argument("--dry-run", action="store_true", default=True)
    ins.add_argument("--live", action="store_true", help="run installer; still requires --opt-in")

    gl = sub.add_parser("glance")
    gl.add_argument("--thread")
    gl.add_argument("--convoy-id")
    gl.add_argument("--json", action="store_true", default=True)
    gl.add_argument("--tray", action="store_true", help="render glance in tray/app-indicator")
    gl.add_argument("--refresh-seconds", type=int, default=60)

    go = sub.add_parser("start", help="thin alias: git URL -> clone once + onboard --github yes; local path -> onboard --github no; no repo -> picker from recent(); already-live -> attach, never bring_up")
    go.add_argument("repo", nargs="?", help="git URL or local checkout path")
    go.add_argument("--to", action="append", help="harness you already have (repeat); default: those on PATH")
    go.add_argument("--thread")
    go.add_argument("--cancel", action="store_true", help="do not bind; leave unbound")

    ob = sub.add_parser("onboard")
    ob.add_argument("--to", action="append", required=True, help="named harness id(s) you already have")
    ob.add_argument("--thread")
    ob.add_argument("--checkout-root", help="existing path, or a git URL cloned under $CONVOY_HOME/checkouts/<owner>/<repo>")
    ob.add_argument("--github", choices=("yes", "no"), default=None, help="record the wizard's GitHub? answer on the bind")

    pf = sub.add_parser("preflight", help="fail-closed wizard preflight: live MCP tools/list vs the verbs the @convoy wizard needs")
    pf.add_argument("--url", default=None, help="MCP endpoint (default: public https://convoy.bot/mcp)")
    pf.add_argument("--tools", default=None, help="comma-separated tool names to score offline instead of fetching")

    mcp = sub.add_parser("mcp")
    mcp.add_argument("--root", default=argparse.SUPPRESS, help="layer root (also accepted after subcommand)")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8788)

    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    # Chats launch from project subfolders: for read verbs, walk up to the
    # nearest .convoy/id when the given root has none (never for writes).
    if args.cmd in ("graph", "threads", "panes", "resume", "seats", "feed", "context", "glance", "inbox", "provenance", "rebase", "focus") and not (root / ".convoy" / "id").is_file():
        found = find_root(root)
        if found is not None:
            root = found

    if args.cmd == "whoami":
        me = identify(root)
        print(json.dumps(me))
        return 0 if me.get("ok") else 1
    if args.cmd == "hook":
        instance_id = args.instance_id
        if getattr(args, "as_me", False):
            me = identify(root)
            if not me.get("chair"):
                print(json.dumps({"ok": False, "error": "refuse --as-me: no chair on this thread matches this body", "whoami": me}))
                return 1
            instance_id = me["chair"]
        try:
            row = hook(root, args.kind, args.summary, instance_id=instance_id, to=args.to)
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
        card = relaunch(root, thread=args.thread, runner=None if args.dry_run else live_runner, timeout=args.timeout, seats=args.seat)
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
            me = identify(root)
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
                card = join(root, args.to, session_id=args.session_id, worktree=args.worktree,
                            model=args.model, title=args.title, effort=args.effort, author=args.author,
                            where=args.where)
                if args.launch:
                    launched = launch_seat(
                        root,
                        card["seat"]["session_id"],
                        runner=active_pane_runner,
                        consent=args.consent,
                    )
                    card["launch"] = launched
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
                card = seated_ack(root, args.seat, token=args.token)
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
                    runner=live_runner if args.launch else None)
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
        card = launch_seat(
            root,
            args.seat,
            runner=None if args.dry_run else active_pane_runner,
            consent=args.consent,
        )
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
            known = [Path(r["root"]) for r in list_threads() if r["present"]]
            # the given root counts only when it actually carries a thread (never invent)
            roots = ([root] if read_id(root) else []) + [Path(r) for r in args.also_root]
            roots += [k for k in known if k.resolve() not in {r.resolve() for r in roots}]
            threads = [{"root": str(r), "graph": build_graph(r)} for r in roots]
            out = Path(args.out) if args.out else (root / ".convoy" / "graph.html")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_html(threads), encoding="utf-8")
            print(json.dumps({"ok": True, "path": str(out), "threads": len(threads)}))
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
    if args.cmd == "neurons":
        print(json.dumps(neuron_activity(root, since=args.since)))
        return 0
    if args.cmd == "skills":
        # Refresh BOTH halves of a neuron's install: the skill text and the
        # inbox hooks (probed command + root pointer). A long-lived pane that
        # got only the text stayed deaf (audit 2026-09-03).
        skills = install_neuron_identity(args.worktree)
        hooks = ensure_inbox_hooks(args.worktree, root=root if read_id(root) else None)
        card = {**skills, "skills_ok": bool(skills.get("ok")), "hooks": hooks,
                "ok": bool(skills.get("ok")) and bool(hooks.get("ok"))}
        print(json.dumps(card))
        return 0 if card["ok"] else 1
    if args.cmd == "resume":
        try:
            card = resume_neuron(root, args.neuron, go=args.go)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "attach":
        card = attach(root, convoy_id=args.convoy_id)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "lead":
        if args.to:
            try:
                is_chair = any(s.get("session_id") == args.to for s in list_seats(root))
                if is_chair:
                    if not args.author:
                        raise ValueError("refuse lead pass to a chair without --as <author chair>")
                    print(json.dumps(pass_lead(root, args.to, author=args.author)))
                else:
                    print(json.dumps(set_lead(root, args.to)))
                return 0
            except ValueError as e:
                print(json.dumps({"ok": False, "error": str(e)}))
                return 1
        lead_chair = next((n["session_id"] for n in build_graph(root)["nodes"] if n["kind"] == "chair" and n.get("lead")), None)
        print(json.dumps({"conductor": CONDUCTOR, "lead": read_lead(root), "lead_chair": lead_chair, "convoy_id": read_id(root)}))
        return 0
    if args.cmd == "bind":
        try:
            print(json.dumps(bind(root, args.thread)))
            return 0
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
    if args.cmd in ("bring-up", "open"):
        runner = None if args.dry_run else live_runner
        card = bring_up(root, convoy_id=args.convoy_id, thread=args.thread, runner=runner)
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
    if args.cmd == "install":
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
        )
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "onboard":
        card = run_onboard(root, args.to, thread=args.thread, checkout_root=args.checkout_root,
                           github=None if args.github is None else args.github == "yes")
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
        return serve(root, host=args.host, port=args.port)
    if args.cmd == "send":
        runner = native_runner if args.live else fake_runner
        allow_interactive_resume = not bool(args.live)
        wts = args.worktree
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
