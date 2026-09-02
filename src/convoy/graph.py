"""Convoy graph: read-only projection of one thread's ontology of attributions.

Marco (2026-09-02): a thread is the context; the graph is who sat where, on
what harness and model, who talked to whom, and where a resume can legally
start. Context is model-agnostic within a session and the chair survives the
occupant, so the graph is built from two files only — seats.jsonl (chairs,
current occupant) and feed.jsonl (attributed rows) — and never from a vendor
transcript.

Honesty rules this module inherits:
- Every edge from the bus is `attested` (claimed on the bus, not
  authenticated). Nothing here is `observed` until a vendor-record reader
  exists; the field is present so a later increment can upgrade it.
- Synapse rows carry no caller identity (feed contract v2.1), so their edge
  has `from: null` — sender-unknown recorded as absence.
- Tokens never leave seats.jsonl: a chair reports `resume.available` (bool)
  and `resume.for` (harness), never the token, never the boot prompt.
- Unknown model => no model node, no runs edge. Never a placeholder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .convoy import list_seats, read_id, read_thread
from .layer import _is_conductor_alias, feed_path, feed_since

GRAPH_VERSION = 1
EPOCH = "1970-01-01T00:00:00.000000Z"
LINEAGE_KINDS = ("join", "swap", "seated")


def _chair_id(sid: str) -> str:
    return "chair:" + sid


def _party_id(name: Any, chairs: set[str]) -> str | None:
    """Resolve a bus name to a node id: a chair, the conductor, or None."""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    if _is_conductor_alias(name):
        return "conductor:grok-bot"
    if name in chairs:
        return _chair_id(name)
    return "unknown:" + name


def _lineage(rows: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") not in LINEAGE_KINDS or r.get("instance_id") != sid:
            continue
        entry: dict[str, Any] = {"kind": r["kind"], "ts": r.get("ts"), "attestation": "attested"}
        if r["kind"] == "join":
            entry["to_occupancy"] = {"harness": r.get("harness"), "model": r.get("model")}
            entry["state"] = "pending"
        elif r["kind"] == "swap":
            entry["to_occupancy"] = {"harness": r.get("swap_to"), "model": _model_from_summary(r.get("summary"))}
            entry["memory"] = r.get("memory")
            entry["state"] = "pending"
        else:  # seated: the ack closes the newest pending entry
            entry["state"] = "acked"
            for prev in reversed(out):
                if prev["kind"] in ("join", "swap") and prev["state"] == "pending":
                    prev["state"] = "acked"
                    prev["seated_at"] = r.get("ts")
                    break
        out.append(entry)
    return out


def _lead_chair(rows: list[dict[str, Any]], chairs: set[str]) -> str | None:
    """Latest kind=lead row naming an existing chair wins."""
    lead = None
    for r in rows:
        if r.get("kind") == "lead" and r.get("to") in chairs:
            lead = r["to"]
    return lead


CONTRIBUTION_KINDS = ("note", "join", "swap", "seated", "lead")


def _contributions(rows: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    """Rows this chair AUTHORED (from == sid). Synapse rows have no author and
    never count; a join row authored by nobody does not count either."""
    return [r for r in rows if r.get("kind") in CONTRIBUTION_KINDS and r.get("from") == sid]


def _place(rows: list[dict[str, Any]], chairs: set[str], sid: str, degree: int, lead_chair: str | None) -> dict[str, Any]:
    """Temporal + positional self-knowledge for one chair (Marco 2026-09-02:
    a post-hook so a neuron knows its place and lead can be passed to an
    identified neuron). rank is 1-based by latest contribution, newest first;
    a chair with no authored row has rank null, never 0."""
    mine = _contributions(rows, sid)
    last = mine[-1] if mine else None
    latest: dict[str, str] = {}
    for c in chairs:
        rs = _contributions(rows, c)
        if rs and isinstance(rs[-1].get("ts"), str):
            latest[c] = rs[-1]["ts"]
    order = sorted(latest, key=lambda c: latest[c], reverse=True)
    return {
        "last_contribution": ({"ts": last.get("ts"), "kind": last.get("kind"), "summary": last.get("summary")}
                              if last else None),
        "contributions": len(mine),
        "rank": (order.index(sid) + 1) if sid in order else None,
        "of": len(chairs),
        "degree": degree,
        "lead": sid == lead_chair,
        "lead_chair": lead_chair,
    }


def _model_from_summary(summary: Any) -> str | None:
    # swap rows carry the model only inside "swap S -> H (model)" today; the
    # seat row carries it after update_seat. Read it back, never guess.
    if isinstance(summary, str) and summary.endswith(")") and " (" in summary:
        return summary.rsplit(" (", 1)[1][:-1] or None
    return None


def build_graph(root: Path) -> dict[str, Any]:
    root = Path(root)
    cid = read_id(root)
    thread = read_thread(root)
    seats = list_seats(root, require_session=True)
    rows = feed_since(root, EPOCH) if feed_path(root).exists() else []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if cid is None and not seats and not rows:
        return {"graph_version": GRAPH_VERSION, "convoy_id": None, "thread": thread, "nodes": [], "edges": []}

    node_ids: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        if node["id"] not in node_ids:
            node_ids.add(node["id"])
            nodes.append(node)

    thread_id = "thread:" + (cid or "unbound")
    add_node({"id": thread_id, "kind": "thread", "convoy_id": cid, "thread": thread,
              "path": str(root / "thread.md")})

    chairs = {s["session_id"] for s in seats}
    lead_chair = _lead_chair(rows, chairs)
    for s in seats:
        sid = s["session_id"]
        lineage = _lineage(rows, sid)
        harness = s.get("to")
        model = s.get("model")
        resume_ok = bool(s.get("resume")) and (s.get("resume_for") in (None, harness))
        add_node({
            "id": _chair_id(sid), "kind": "chair", "session_id": sid,
            "title": s.get("title"), "worktree": s.get("worktree"),
            "current": {"harness": harness, "model": model, "effort": s.get("effort")},
            "resume": {"available": resume_ok, "for": s.get("resume_for") if resume_ok else None},
            "lineage": lineage,
            "lead": sid == lead_chair,
        })
        edges.append({"kind": "seats", "from": thread_id, "to": _chair_id(sid)})
        seen_harness: list[str] = []
        for e in lineage:
            occ = e.get("to_occupancy") or {}
            h = occ.get("harness")
            if h and h not in seen_harness:
                seen_harness.append(h)
        if harness and harness not in seen_harness:
            seen_harness.append(harness)
        for h in seen_harness:
            add_node({"id": "harness:" + h, "kind": "harness", "harness": h})
            edges.append({"kind": "runs_on", "from": _chair_id(sid), "to": "harness:" + h,
                          "current": h == harness, "attestation": "attested"})
        if isinstance(model, str) and model.strip():
            add_node({"id": "model:" + model, "kind": "model", "model": model})
            edges.append({"kind": "runs", "from": _chair_id(sid), "to": "model:" + model,
                          "current": True, "attestation": "attested"})

    for r in rows:
        kind = r.get("kind")
        if kind in ("note", "conductor"):
            src = _party_id(r.get("from"), chairs)
            dst = _party_id(r.get("to"), chairs)
            if src is None or dst is None:
                continue
            for pid in (src, dst):
                if pid.startswith("conductor:"):
                    add_node({"id": pid, "kind": "conductor"})
                elif pid.startswith("unknown:"):
                    add_node({"id": pid, "kind": "unknown", "name": pid.split(":", 1)[1]})
            edges.append({"kind": kind if kind == "note" else "stamp", "from": src, "to": dst,
                          "ts": r.get("ts"), "attestation": "attested"})
        elif kind == "lead":
            src = _party_id(r.get("from"), chairs)
            dst = _party_id(r.get("to"), chairs)
            if src is None or dst is None:
                continue
            edges.append({"kind": "lead", "from": src, "to": dst, "ts": r.get("ts"), "attestation": "attested"})
        elif kind == "synapse":
            dst = _party_id(r.get("instance_id"), chairs)
            if dst is None:
                continue
            if dst.startswith("unknown:"):
                add_node({"id": dst, "kind": "unknown", "name": dst.split(":", 1)[1]})
            edges.append({"kind": "synapse", "from": None, "to": dst, "harness": r.get("to"),
                          "ts": r.get("ts"), "runner": r.get("runner"), "attestation": "attested"})

    return {"graph_version": GRAPH_VERSION, "convoy_id": cid, "thread": thread, "nodes": nodes, "edges": edges}


def neighborhood(root: Path, session_id: str) -> dict[str, Any]:
    """What one neuron needs to rejoin the fray: its chair, the chairs and
    parties it has talked with, and the thread pointer to resume from."""
    g = build_graph(Path(root))
    me = _chair_id(str(session_id or "").strip())
    chair = next((n for n in g["nodes"] if n["id"] == me), None)
    if chair is None:
        raise ValueError("unknown neuron: " + str(session_id))
    linked: list[str] = []
    for e in g["edges"]:
        if e["kind"] not in ("note", "stamp", "synapse", "lead"):
            continue
        other = e["to"] if e.get("from") == me else (e.get("from") if e["to"] == me else None)
        if other and other not in linked:
            linked.append(other)
    by_id = {n["id"]: n for n in g["nodes"]}
    last_ts = None
    if feed_path(Path(root)).exists():
        for r in feed_since(Path(root), EPOCH):
            ts = r.get("ts")
            if isinstance(ts, str) and (last_ts is None or ts > last_ts):
                last_ts = ts
    thread_node = next(n for n in g["nodes"] if n["kind"] == "thread")
    rows = feed_since(Path(root), EPOCH) if feed_path(Path(root)).exists() else []
    chairs = {n["session_id"] for n in g["nodes"] if n["kind"] == "chair"}
    lead_chair = next((n["session_id"] for n in g["nodes"] if n["kind"] == "chair" and n.get("lead")), None)
    neighbors = [by_id[i] for i in linked if i in by_id]
    return {
        "graph_version": GRAPH_VERSION,
        "convoy_id": g["convoy_id"],
        "chair": chair,
        "place": _place(rows, chairs, chair["session_id"], len(neighbors), lead_chair),
        "neighbors": neighbors,
        "thread": {"convoy_id": g["convoy_id"], "thread": g["thread"], "path": thread_node["path"],
                   "last_row_ts": last_ts},
    }
