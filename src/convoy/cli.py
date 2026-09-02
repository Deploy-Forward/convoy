"""convoy CLI. Phase 1: context + send with pointers. Parallel send is Phase 6. Phase 7: convoy_id attach + bring-up + hide."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bringup import bring_up, hide_windows, live_applier, live_runner, terminals
from .install import install as install_harness
from .onboard import onboard as run_onboard
from .context import pack
from .convoy import attach, bind, ensure_id, list_seats, read_id, read_lead, seat, set_lead, CONDUCTOR
from .glance import build_glance, run_tray
from .layer import SCHEMA_VERSION, conductor_stamp, feed_since, hook
from .lifecycle import join, seated_ack, swap
from .synapse import fake_runner, native_runner, send_many, send_one
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

    sw = sub.add_parser("swap")
    sw.add_argument("--seat", required=True, help="chair session_id (identity survives the swap)")
    sw.add_argument("--to", required=True, help="replacement harness")
    sw.add_argument("--model")
    sw.add_argument("--handoff", required=True, help="fresh .ola/*handoff* file written by the outgoing neuron")
    sw.add_argument("--as", dest="author", required=True, help="outgoing neuron's session_id (neuron-authored; conductor asks via stamp)")

    sd = sub.add_parser("seated")
    sd.add_argument("--seat", required=True)
    sd.add_argument("--token", required=True, help="token from the join/swap row (proof-of-life echo)")

    sl = sub.add_parser("seats")
    sl.add_argument("--convoy-id")

    at = sub.add_parser("attach")
    at.add_argument("convoy_id", nargs="?")

    bn = sub.add_parser("bind")
    bn.add_argument("--thread", required=True)

    ld = sub.add_parser("lead")
    ld.add_argument("--to")

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

    if args.cmd == "hook":
        try:
            row = hook(root, args.kind, args.summary, instance_id=args.instance_id, to=args.to)
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
            elif args.cmd == "swap":
                card = swap(root, args.seat, to=args.to, handoff=args.handoff,
                            author=args.author, model=args.model)
            else:
                card = seated_ack(root, args.seat, token=args.token)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(card))
        return 0
    if args.cmd == "seats":
        print(json.dumps(list_seats(root, convoy_id=args.convoy_id)))
        return 0
    if args.cmd == "attach":
        card = attach(root, convoy_id=args.convoy_id)
        print(json.dumps(card))
        return 0 if card.get("ok") else 1
    if args.cmd == "lead":
        if args.to:
            try:
                print(json.dumps(set_lead(root, args.to)))
                return 0
            except ValueError as e:
                print(json.dumps({"ok": False, "error": str(e)}))
                return 1
        print(json.dumps({"conductor": CONDUCTOR, "lead": read_lead(root), "convoy_id": read_id(root)}))
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
