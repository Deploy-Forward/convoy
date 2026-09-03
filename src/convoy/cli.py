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
from .context import pack
from .convoy import attach, bind, ensure_id, list_seats, read_id, read_lead, seat, set_lead, CONDUCTOR
from .glance import build_glance, run_tray
from .graph import build_graph, neighborhood
from .graph_html import render_html, resume_neuron
from .identity import ensure_inbox_hooks, install_neuron_identity
from .index import find_root, index_path, list_threads
from .panes import bodies, identify
from .layer import SCHEMA_VERSION, conductor_stamp, feed_since, hook
from .lifecycle import join, pass_lead, seated_ack, swap
from .pane_host import close_managed_pane
from .synapse import fake_runner, native_runner, send_many, send_one
from .targeted_launch import active_pane_runner, launch_choices, launch_seat
from .usage import probe

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
    f.add_argument("--since", required=True)

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
    ib.add_argument("--hook-pretooluse", action="store_true", help="Grok/Claude hook JSON on stdout")

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
    se.add_argument("--effort", help="declared effort for this seat (real-or-null; Convoy never sets vendor effort flags)")

    jn = sub.add_parser("join")
    jn.add_argument("--to", required=True, help="harness for the new chair")
    jn.add_argument("--session-id")
    jn.add_argument("--worktree")
    jn.add_argument("--model")
    jn.add_argument("--title")
    jn.add_argument("--effort")
    jn.add_argument("--as", dest="author", help="authoring seat (neuron-authored)")
    jn.add_argument("--launch", action="store_true", help="split exactly one fresh chair into the active supported pane host")
    jn.add_argument("--consent", help="one-time scoped consent returned by `convoy consent --grant`")

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

    sw = sub.add_parser("swap")
    sw.add_argument("--seat", required=True, help="chair session_id (identity survives the swap)")
    sw.add_argument("--to", required=True, help="replacement harness")
    sw.add_argument("--model")
    sw.add_argument("--handoff", required=True, help="fresh .ola/*handoff* file written by the outgoing neuron")
    sw.add_argument("--as", dest="author", required=True, help="outgoing neuron's session_id (neuron-authored; conductor asks via stamp)")

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

    sub.add_parser("panes", help="every body of every neuron on this thread from the OS process table: pid, via token|cwd, duplicates, unassigned harness processes; never a token")

    sub.add_parser("threads", help="every Convoy thread this machine knows (the global index; present=false when a root is gone)")

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

    ob = sub.add_parser("onboard")
    ob.add_argument("--to", action="append", required=True, help="named harness id(s) you already have")
    ob.add_argument("--thread")
    ob.add_argument("--checkout-root")

    mcp = sub.add_parser("mcp")
    mcp.add_argument("--root", default=argparse.SUPPRESS, help="layer root (also accepted after subcommand)")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8788)

    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    # Chats launch from project subfolders: for read verbs, walk up to the
    # nearest .convoy/id when the given root has none (never for writes).
    if args.cmd in ("graph", "threads", "panes", "resume", "seats", "feed", "context", "glance", "inbox") and not (root / ".convoy" / "id").is_file():
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
        rows = feed_since(root, args.since)
        print(json.dumps({"schema_version": SCHEMA_VERSION, "since": args.since, "events": rows}))
        return 0
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
        from .inbox import drain, hook_pretooluse, pending, seat_for_worktree
        if args.hook_pretooluse:
            print(json.dumps(hook_pretooluse()))
            return 0
        sid = str(args.seat or "").strip()
        if not sid:
            row = seat_for_worktree(root, Path.cwd())
            sid = str((row or {}).get("session_id") or "").strip()
        if not sid:
            print(json.dumps({"ok": False, "error": "inbox requires --seat"}))
            return 1
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
        )
        print(json.dumps(row))
        return 0
    if args.cmd in ("join", "swap", "seated"):
        try:
            if args.cmd == "join":
                card = join(root, args.to, session_id=args.session_id, worktree=args.worktree,
                            model=args.model, title=args.title, effort=args.effort, author=args.author)
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
                            author=args.author, model=args.model)
            else:
                card = seated_ack(root, args.seat, token=args.token)
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
        print(json.dumps({"ok": True, "index": str(index_path()), "threads": list_threads()}))
        return 0
    if args.cmd == "panes":
        print(json.dumps(bodies(root)))
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

    if args.cmd == "onboard":
        card = run_onboard(root, args.to, thread=args.thread, checkout_root=args.checkout_root)
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
