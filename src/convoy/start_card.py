"""The start card: what the other neurons on this thread committed to, so a new session starts synced.

`start` binds, then returns this card; `convoy start-card` and the read-only MCP `start_card` build
the same one. It is pointer-first and size-budgeted: one line per item, with a path, id or token to
read more, and never a file's contents, a message body or a transcript. Every section reports
unknown as unknown (null, or the word unknown in a line), never as zero or no.

  where        repo, branch, ahead/behind its upstream, dirty (Convoy's own record aside),
               thread (id and name), lead
  who          the neurons, from the existing neuron reader: id, harness, model, active, last seen
  commitments  open sends: a send older than the ack time whose receiver neither drained it nor
               cited its token; the latest handoff per neuron (its first line and its path); the
               last three commits per neuron worktree; asks from limited sends, open until the
               named chair writes any later row
  board        whether this machine is paired; card reads are not available in this Convoy
  next         the lead's latest handoff, or "no handoff: read thread.md"
  notes        one line per thing start chose not to do, so nothing changes silently

Past the line budget the card ends with "+N more" and the command that shows everything.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .activity import neuron_activity, neuron_id
from .cmd import quiet_spawn_kwargs
from .convoy import list_seats, read_id, read_lead, read_thread
from .inbox import _consumed_tokens, _load
from .index import home_dir
from .report import read_origin
from .wake_dispatch import T_ACK, cited_tokens, proven_author

LINE_BUDGET = 60
# A send is open once it has gone unread for the shortest wake acknowledgement time.
OPEN_SEND_AFTER_S = min(T_ACK.values())
ASKS_LABEL = "asks (from limited sends)"
NO_HANDOFF = "no handoff: read thread.md"
TRUST_NOTE = "trust: not written; Claude will ask once"
TRACKED_SETTINGS = ".claude/settings.json"
LINE_MAX = 160


def _git(cwd: Path | str, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=10, **quiet_spawn_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        value = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 3600:
        return str(int(seconds // 60)) + "m"
    if seconds < 86400:
        return str(int(seconds // 3600)) + "h"
    return str(int(seconds // 86400)) + "d"


def _one_line(text: Any) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= LINE_MAX else line[:LINE_MAX - 3] + "..."


def _feed(root: Path) -> list[dict[str, Any]]:
    path = root / ".convoy" / "feed.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _same_path(a: str | Path, b: str | Path) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def _head(cwd: Path | str) -> tuple[str | None, str | None]:
    """(branch, detached_at): a branch name, or the short sha a detached HEAD is at."""
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch.strip() if branch else None
    if branch == "HEAD":
        sha = _git(cwd, "rev-parse", "--short", "HEAD")
        return None, sha.strip() if sha else None
    return branch, None


def _lead_status(root: Path) -> str:
    """none | dangling | held, from the same reader `convoy lead` uses."""
    from .lifecycle import lead_state
    return lead_state(root)["status"]


def _where(root: Path) -> dict[str, Any]:
    where: dict[str, Any] = {"repo": str(root), "branch": None, "detached_at": None, "ahead": None, "behind": None,
                             "dirty": None, "thread": {"id": read_id(root), "name": read_thread(root)},
                             "lead": read_lead(root), "lead_status": _lead_status(root)}
    top = _git(root, "rev-parse", "--show-toplevel")
    if top is None or not _same_path(top.strip(), root):
        return where  # not a repo, or a folder inside someone else's: its git state is unknown
    where["branch"], where["detached_at"] = _head(root)
    counts = _git(root, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if counts and len(counts.split()) == 2:
        where["behind"], where["ahead"] = (int(n) for n in counts.split())
    status = _git(root, "--no-optional-locks", "status", "--porcelain", "--untracked-files=all")
    if status is not None:
        own = (".convoy/", "thread.md")  # Convoy's own record is not the person's work
        where["dirty"] = any(not line[3:].strip('"').startswith(own) for line in status.splitlines() if line.strip())
    return where


def _who(root: Path, cid: str | None, neurons_fn: Callable[[Path], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = (neurons_fn(root) or {}).get("neurons") or []
    return [{"id": neuron_id(cid, r.get("session_id")), "session_id": r.get("session_id"), "harness": r.get("harness"),
             "model": r.get("model"), "active": r.get("active"), "last_seen": r.get("last_authored")}
            for r in rows]


def _open_sends(root: Path, feed: list[dict[str, Any]], now: datetime, redact_tokens: bool) -> list[dict[str, Any]]:
    # Only a proven citation closes a send; a claimed one is shown as a claimed answer, as the
    # wake dispatcher treats it.
    proven: set[tuple[str, str]] = set()
    claimed: set[tuple[str, str]] = set()
    for row in feed:
        if row.get("kind") == "note" and isinstance(row.get("from"), str):
            bucket = proven if proven_author(row) == row["from"] else claimed
            for token in cited_tokens(str(row.get("summary") or "")):
                bucket.add((row["from"], token))
    consumed: dict[str, set[str]] = {}
    out = []
    for row in feed:
        token, target = row.get("token"), row.get("instance_id")
        if row.get("kind") != "synapse" or not isinstance(token, str) or not token or not isinstance(target, str):
            continue
        sent = _parse(row.get("ts"))
        age = (now - sent).total_seconds() if sent else None
        if age is not None and age < OPEN_SEND_AFTER_S:
            continue
        if (target, token) in proven:
            continue
        if target not in consumed:
            try:
                consumed[target] = _consumed_tokens(_load(root, target))
            except (OSError, ValueError):
                consumed[target] = set()
        if token in consumed[target]:
            continue
        item = {"from": proven_author(row), "to": target, "age_s": age, "claimed_answer": (target, token) in claimed}
        if not redact_tokens:
            item["token"] = token  # the receiver's proof: only where the reader may hold it
        out.append(item)
    return out


def _handoff_for(root: Path, chair: str) -> dict[str, Any] | None:
    folder = root / ".convoy" / "handoff"
    if not folder.is_dir():
        return None
    found = [p for p in folder.iterdir() if p.is_file() and p.suffix == ".md"
             and (p.name == chair + ".rolling.md" or p.name.startswith(chair + "-"))]
    if not found:
        return None
    newest = max(found, key=lambda p: p.stat().st_mtime)
    line = ""
    try:
        for raw in newest.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if raw.strip():
                line = raw.strip().lstrip("#").strip()
                break
    except OSError:
        line = ""
    return {"chair": chair, "line": _one_line(line) or None,
            "path": newest.relative_to(root).as_posix()}


def _commits(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for seat in seats:
        wt = seat.get("worktree")
        if not wt:
            continue
        if not Path(wt).is_dir():
            out.append({"chair": seat.get("session_id"), "branch": None, "detached_at": None, "worktree": str(wt),
                        "last": None, "missing": True})
            continue
        key = os.path.normcase(str(Path(wt).resolve()))
        if key in seen:
            continue
        seen.add(key)
        branch, detached_at = _head(wt)
        log = _git(wt, "log", "-3", "--format=%h%x09%s")
        last = None
        if log is not None:
            last = [{"sha": sha, "subject": _one_line(subject)}
                    for sha, _, subject in (line.partition("\t") for line in log.splitlines() if line.strip())]
        out.append({"chair": seat.get("session_id"), "branch": branch, "detached_at": detached_at,
                    "worktree": str(wt), "last": last, "missing": False})
    return out


def _asks(feed: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    out = []
    for row in feed:
        ask = row.get("ask")
        chair = row.get("instance_id")
        if row.get("kind") != "refuse" or not isinstance(ask, dict) or not isinstance(chair, str):
            continue
        asked = _parse(row.get("ts"))
        if asked is not None and any(proven_author(r) == chair and (_parse(r.get("ts")) or asked) > asked
                                     for r in feed):
            continue  # the chair, proven, wrote again: it came back
        out.append({"chair": chair, "action": ask.get("action"), "text": _one_line(ask.get("text")) or None,
                    "handoff": ask.get("handoff"), "age_s": (now - asked).total_seconds() if asked else None})
    return out


def _tracked_convoy_hooks(root: Path) -> int:
    """How many Convoy hook commands the tracked .claude/settings.json still carries (0 when it is
    untracked, missing or unreadable). Convoy never edits that file; the card says so instead."""
    from .cmd import END_HOOK_ARGS, INBOX_HOOK_ARGS
    if _git(root, "ls-files", "--error-unmatch", TRACKED_SETTINGS) is None:
        return 0
    try:
        data = json.loads((root / TRACKED_SETTINGS).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return 0
    hooks = data.get("hooks") if isinstance(data, dict) else None
    count = 0
    for groups in (hooks.values() if isinstance(hooks, dict) else []):
        for group in groups if isinstance(groups, list) else []:
            for entry in (group.get("hooks") or []) if isinstance(group, dict) else []:
                command = str(entry.get("command") or "") if isinstance(entry, dict) else ""
                count += INBOX_HOOK_ARGS in command or END_HOOK_ARGS in command
    return count


def _board() -> dict[str, Any]:
    try:
        paired = read_origin(home_dir()) is not None
    except Exception:  # a pairing that cannot be read is not a pairing
        paired = False
    if not paired:
        return {"connected": False, "line": "board not connected"}
    return {"connected": True, "line": "board: paired; card reads not available in this Convoy"}


def _next(root: Path, seats: list[dict[str, Any]], lead: str | None) -> dict[str, Any]:
    chairs = [s.get("session_id") for s in seats if lead and lead in (s.get("session_id"), s.get("to"))]
    found = [h for h in (_handoff_for(root, c) for c in chairs if c) if h]
    if found:
        newest = max(found, key=lambda h: (root / h["path"]).stat().st_mtime)
        return {"chair": newest["chair"], "path": newest["path"], "line": newest["line"]}
    return {"chair": None, "path": None, "line": NO_HANDOFF}


def _where_line(w: dict[str, Any]) -> str:
    """The where line within LINE_MAX: the repo path gives way first, then the thread's name; the
    thread id and the lead are kept."""
    yes = {True: "yes", False: "no", None: "unknown"}
    head = ("detached at " + w["detached_at"]) if w.get("detached_at") else str(w["branch"] or "unknown")
    upstream = ("ahead " + str(w["ahead"]) + ", behind " + str(w["behind"])) if w["ahead"] is not None \
        else "upstream unknown"
    cid = str(w["thread"]["id"] or "unknown")
    status = w.get("lead_status")
    lead = "; lead: " + ("none" if not w["lead"] or status == "none" else
                         "dangling " + str(w["lead"]) if status == "dangling" else str(w["lead"]))
    named = " on " + head + " (" + upstream + "), dirty " + yes[w["dirty"]] + "; thread " \
        + str(w["thread"]["name"] or "unknown") + " (" + cid + ")" + lead
    bare = " on " + head + " (" + upstream + "), dirty " + yes[w["dirty"]] + "; thread " + cid + lead
    line = "where: " + w["repo"] + named
    if len(line) <= LINE_MAX:
        return line
    for rest in (named, bare):
        room = LINE_MAX - len("where: ...") - len(rest)
        if room >= 0:
            return "where: ..." + (w["repo"][-room:] if room else "") + rest
    # Then the branch gives way, so the thread id and the lead are still on the line.
    after = " (" + upstream + "), dirty " + yes[w["dirty"]] + "; thread " + cid + lead
    room = LINE_MAX - len("where: ... on ") - len(after)
    if room > 3 and len(head) > room:
        head = head[:room - 3] + "..."
    return "where: ... on " + head + after


def _render(card: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(line, section) pairs; section names the card list an item line belongs to, so the JSON lists
    can be capped with the lines."""
    lines: list[tuple[str, str | None]] = [(_where_line(card["where"]), None)]
    lines += [(n, None) for n in card["notes"]]
    lines.append(("who: " + str(len(card["who"])) + " neurons", None))
    state = {True: "active", False: "quiet", None: "unknown"}
    for n in card["who"]:
        lines.append(("  " + str(n["id"] or "unknown") + " | " + str(n["harness"] or "unknown") + " | "
                      + str(n["model"] or "unknown") + " | " + state.get(n["active"], "unknown") + " | last seen "
                      + str(n["last_seen"] or "unknown"), "who"))
    c = card["commitments"]
    lines.append(("open sends: " + (str(len(c["open_sends"])) if c["open_sends"] else "none"), None))
    for s in c["open_sends"]:
        lines.append(("  " + str(s.get("token") or "(token withheld)") + " " + str(s["from"] or "unknown") + " -> "
                      + s["to"] + ", " + _age(s["age_s"]) + (", answered (claimed)" if s["claimed_answer"] else ""),
                      "open_sends"))
    lines.append(("handoffs: " + (str(len(c["handoffs"])) if c["handoffs"] else "none"), None))
    for h in c["handoffs"]:
        lines.append(("  " + h["chair"] + ": " + str(h["line"] or "(empty)") + " (" + h["path"] + ")", "handoffs"))
    lines.append(("commits: " + (str(len(c["commits"])) + " worktrees" if c["commits"] else "none"), None))
    for m in c["commits"]:
        if m["missing"]:
            lines.append(("  " + str(m["chair"]) + ": worktree missing (" + m["worktree"] + ")", "commits"))
            continue
        head = ("detached at " + m["detached_at"]) if m["detached_at"] else str(m["branch"] or "unknown")
        last = "unknown" if m["last"] is None else "; ".join(x["sha"] + " " + x["subject"] for x in m["last"]) or "none"
        lines.append(("  " + str(m["chair"]) + " " + head + " @ " + m["worktree"] + ": " + last, "commits"))
    lines.append((ASKS_LABEL + ": " + (str(len(c["asks"])) if c["asks"] else "none"), None))
    for a in c["asks"]:
        lines.append(("  " + a["chair"] + ": " + str(a["action"] or "unknown") + " - " + str(a["text"] or "")
                      + " (" + _age(a["age_s"]) + ")", "asks"))
    lines.append((card["board"]["line"], None))
    nxt = card["next"]
    lines.append(("next: " + (str(nxt["line"] or nxt["path"]) + " (" + nxt["path"] + ")" if nxt["path"]
                              else nxt["line"]), None))
    return [(_one_line(text) if not text.startswith("  ") else "  " + _one_line(text), section)
            for text, section in lines]


def _scrub(value: Any, tokens: set[str]) -> Any:
    """Replace every send token inside the card's text, in place: a handoff or an ask may quote one."""
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = _scrub(item, tokens)
        return value
    if isinstance(value, list):
        return [_scrub(item, tokens) for item in value]
    if isinstance(value, str) and tokens:
        for token in tokens:
            if token in value:
                value = value.replace(token, "(token withheld)")
    return value


def build_start_card(root: Path | str, *, notes: list[str] | None = None, budget: int | None = LINE_BUDGET,
                     neurons_fn: Callable[[Path], dict[str, Any]] | None = None,
                     now: datetime | None = None, redact_tokens: bool = False) -> dict[str, Any]:
    """The start card for a bound root. Read-only: it writes nothing anywhere. redact_tokens drops
    every send token, the receiver's proof, for a reader that may not hold it (the ungated wire)."""
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    cid = read_id(root)
    seats = list_seats(root, convoy_id=cid) if cid else []
    feed = _feed(root)
    where = _where(root)
    card: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "where": where,
        "who": _who(root, cid, neurons_fn or neuron_activity),
        "commitments": {
            "open_sends": _open_sends(root, feed, now, redact_tokens),
            "handoffs": [h for h in (_handoff_for(root, s["session_id"]) for s in seats if s.get("session_id")) if h],
            "commits": _commits(seats),
            "asks": _asks(feed, now),
        },
        "board": _board(),
        "next": _next(root, seats, where["lead"]),
        "notes": list(notes or []),
    }
    from .index import index_error, index_path
    card["index_error"] = index_error()
    if card["index_error"]:
        card["notes"].append("thread index " + str(index_path()) + " is " + card["index_error"]
                             + "; it is not rewritten; fix or remove it to list this thread")
    if redact_tokens:
        _scrub(card, {r["token"] for r in feed if r.get("kind") == "synapse" and isinstance(r.get("token"), str)
                      and r["token"]})
    stale = _tracked_convoy_hooks(root)
    if stale:
        card["notes"].append("tracked " + TRACKED_SETTINGS + " has " + str(stale) + " Convoy hooks; they now live in "
                             "settings.local.json; remove them from the tracked file")
    tagged = _render(card)
    more_command = "convoy --root " + str(root) + " start-card --all"
    more = 0
    if budget is not None and len(tagged) > budget:
        more = len(tagged) - budget
        tagged = tagged[:budget]
        # The JSON lists carry what the lines carry, so a capped card is capped everywhere.
        kept: dict[str, int] = {}
        for _, section in tagged:
            if section:
                kept[section] = kept.get(section, 0) + 1
        card["who"] = card["who"][:kept.get("who", 0)]
        for section in ("open_sends", "handoffs", "commits", "asks"):
            card["commitments"][section] = card["commitments"][section][:kept.get(section, 0)]
    lines = [text for text, _ in tagged] + (["+" + str(more) + " more: " + more_command] if more else [])
    card.update({"lines": lines, "more": more, "more_command": more_command})
    return card
