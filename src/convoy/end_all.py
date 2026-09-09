"""`convoy end --push [<seat>]` from the lead: one seat, or the whole convoy.

Marco 2026-09-09: with a seat name, end and push that neuron's lane. With no
name, run an orchestra: every non-archived seat on the thread ends and pushes
its own lane, each appending to its own record, and the lead writes ONE
structured handoff document plus a JSON index of identifiers.

Each lane goes through `end.end_task` unchanged, so the push authorization
boundary is the same as a seat ending itself: plain `git push` of a clean
branch with an upstream, refused otherwise. The orchestra never force-pushes,
never commits on a seat's behalf, and never touches the seat's pane.

Output is structured (the card) and mirrored to disk:
  .convoy/handoff/<stamp>.md    the human handoff
  .convoy/handoff/<stamp>.json  identifiers: thread, seats, branches, SHAs, push status
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .convoy import list_seats, read_id, read_thread
from .end import end_task
from .layer import hook, utc_now


def _lane(root: Path, seat: dict[str, Any], *, push: bool, summary: str | None, git_runner=None) -> dict[str, Any]:
    sid = str(seat.get("session_id") or "")
    wt = seat.get("worktree")
    out: dict[str, Any] = {"seat": sid, "harness": seat.get("to"), "model": seat.get("model"),
                           "effort": seat.get("effort"), "worktree": wt, "where": seat.get("where")}
    if not wt or not Path(str(wt)).is_dir():
        out.update({"ok": False, "push_status": "refused", "error": "no worktree on disk"})
        return out
    kw = {"git_runner": git_runner} if git_runner is not None else {}
    card = end_task(root=root, cwd=Path(str(wt)), summary=summary or ("end --push orchestra for " + sid),
                    push=push, **kw)
    hb = card.get("heartbeat") or {}   # end_task puts the git snapshot on the feed row, not the card
    out.update({"ok": bool(card.get("ok")), "push_status": card.get("push_status"),
                "branch": hb.get("branch"), "git_sha": hb.get("git_sha"),
                "dirty": hb.get("dirty"), "upstream": hb.get("upstream"),
                "error": card.get("error") or (None if card.get("ok") else card.get("reason"))})
    return out


def end_all(root: Path | str, *, seat: str | None = None, push: bool = False, summary: str | None = None,
            include_archived: bool = False, git_runner=None, now: str | None = None,
            write_files: bool = True) -> dict[str, Any]:
    """One seat when named, else every live chair. Structured card; files on disk."""
    r = Path(root)
    stamp = now or utc_now()
    seats = [s for s in list_seats(r) if s.get("session_id")]
    if seat:
        picked = [s for s in seats if str(s.get("session_id")) == seat]
        if not picked:
            return {"ok": False, "error": "unknown seat: " + seat, "thread": read_thread(r), "lanes": []}
    else:
        picked = [s for s in seats if include_archived or not s.get("archived")]
    lanes = [_lane(r, s, push=push, summary=summary, git_runner=git_runner) for s in picked]
    pushed = [l for l in lanes if l.get("push_status") == "pushed"]
    refused = [l for l in lanes if l.get("push_status") in ("refused", "failed")]
    card: dict[str, Any] = {
        "ok": all(l.get("ok") for l in lanes) if lanes else False,
        "thread": read_thread(r), "convoy_id": read_id(r), "root": str(r), "ended_at": stamp,
        "mode": "seat" if seat else "orchestra", "push": bool(push),
        "lanes": lanes, "pushed": [l["seat"] for l in pushed], "refused": [l["seat"] for l in refused],
        "handoff_md": None, "handoff_json": None,
    }
    if not lanes:
        card["error"] = "no chairs to end"
    if write_files:
        d = r / ".convoy" / "handoff"
        d.mkdir(parents=True, exist_ok=True)
        base = stamp.replace(":", "").replace("-", "")[:15]
        md, js = d / (base + ".md"), d / (base + ".json")
        md.write_text(render_handoff(card), encoding="utf-8")
        js.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        card["handoff_md"], card["handoff_json"] = str(md), str(js)
    hook(r, "end-all", ("end --push " if push else "end ") + (seat or "orchestra") + ": " + str(len(pushed)) + " pushed, " +
         str(len(refused)) + " refused", instance_id=None, author=None,
         extra={"mode": card["mode"], "lanes": [l["seat"] for l in lanes], "pushed": card["pushed"],
                "refused": card["refused"], "handoff_json": card["handoff_json"]})
    return card


def render_handoff(card: dict[str, Any]) -> str:
    lines = ["# Convoy handoff: " + str(card.get("thread") or "thread"), "",
             "Ended " + str(card.get("ended_at")) + " on `" + str(card.get("root")) + "` (" + str(card.get("mode")) + ").",
             "Convoy id `" + str(card.get("convoy_id")) + "`. Push " + ("requested" if card.get("push") else "not requested") + ".", "",
             "| seat | harness | model | effort | branch | sha | push |", "|---|---|---|---|---|---|---|"]
    for l in card.get("lanes") or []:
        lines.append("| " + " | ".join(str(l.get(k) if l.get(k) is not None else "") for k in
                                       ("seat", "harness", "model", "effort", "branch")) +
                     " | " + str(l.get("git_sha") or "")[:7] + " | " + str(l.get("push_status") or "") +
                     ((" (" + str(l["error"]) + ")") if l.get("error") else "") + " |")
    lines += ["", "Each lane's task-end row is on the thread feed under its own seat. "
              "Refused lanes were not pushed: the seat's branch is dirty, detached, or has no upstream, and the fix is the seat's."]
    return "\n".join(lines) + "\n"
