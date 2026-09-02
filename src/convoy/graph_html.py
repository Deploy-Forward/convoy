"""graph --html and resume --neuron (Marco 2026-09-02).

The graph as a visual, rendered by the LOCAL convoy session: a side panel of
threads, the chair graph for the selected thread, and per chair the exact
Convoy command that resumes that neuron at its most recent place. The page is
self-contained (no external loads) and carries no vendor token — the token is
resolved on the machine at run time by `resume --neuron`, never printed into
a page.

`resume --neuron S` is the pipe-able verb a neuron (or a human) runs to bring
another neuron back: native argv from `bringup.resume_argv`, cwd = the chair's
worktree, plus the chair's place card. `--go` spawns it once, inheriting the
terminal, and refuses when Convoy can see a live body for that chair
(duplicate-body guard, minimal form) or when the seat holds no token minted
for its current harness (then `launch --seat` is the path).
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from .bringup import resume_argv, resume_target, terminals
from .convoy import list_seats
from .graph import build_graph, neighborhood


def _chair_live(root: Path, session_id: str) -> bool:
    try:
        card = terminals(Path(root))
    except Exception:  # liveness probe is best-effort; never blocks a dry read
        return False
    for val in card.values():
        if isinstance(val, list):
            for w in val:
                if isinstance(w, dict) and w.get("session_id") == session_id and w.get("live"):
                    return True
    return False


def resume_neuron(
    root: Path,
    session_id: str,
    go: bool = False,
    spawn: Callable[[list[str], str], int] | None = None,
    liveness: Callable[[Path, str], bool] | None = None,
) -> dict[str, Any]:
    root = Path(root)
    sid = str(session_id or "").strip()
    seat = next((s for s in list_seats(root) if s.get("session_id") == sid), None)
    if seat is None:
        raise ValueError("unknown neuron: " + sid)
    n = neighborhood(root, sid)
    cwd = str(seat.get("worktree") or root)
    if not resume_target(seat):
        return {
            "ok": False, "neuron": sid, "spawned": False,
            "error": "no vendor token minted for this chair's current harness",
            "ask": "python -m convoy --root " + str(root) + " launch --seat " + sid,
            "place": n["place"], "thread": n["thread"],
        }
    argv = resume_argv(seat)
    card: dict[str, Any] = {
        "ok": True, "neuron": sid, "argv": argv, "cwd": cwd, "spawned": False,
        "current": n["chair"]["current"], "place": n["place"], "thread": n["thread"],
    }
    if not go:
        return card
    alive = (liveness or _chair_live)(root, sid)
    if alive:
        card.update({"ok": False, "error": "refuse: a live body already holds chair " + sid + " (no-steal)"})
        return card
    runner = spawn or (lambda a, c: subprocess.Popen(a, cwd=c).pid)
    card["pid"] = runner(argv, cwd)
    card["spawned"] = True
    return card


def render_html(threads: list[dict[str, Any]]) -> str:
    """threads: [{root, graph}] — the local session renders what it can see.
    The per-chair resume command is computed HERE (Python), so the page shows
    exactly what the CLI would run, and it is a Convoy verb, never vendor argv
    with a token."""
    out: list[dict[str, Any]] = []
    for t in threads:
        root = str(t["root"])
        qroot = '"' + root.replace('"', '\\"') + '"' if any(c in root for c in ' "') else root
        g = json.loads(json.dumps(t["graph"]))
        for n in g.get("nodes", []):
            if n.get("kind") == "chair":
                n["resume_command"] = "python -m convoy --root " + qroot + " resume --neuron " + n["session_id"] + " --go"
        out.append({"root": root, "graph": g})
    payload = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE.replace("__DATA__", payload).replace("__COUNT__", str(len(threads)))


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convoy graph</title>
<style>
:root{color-scheme:light dark;--bg:#F7F8F6;--panel:#FFFFFF;--ink:#1B2422;--muted:#5F6B67;--rule:#D8DED9;--accent:#0B6E7A;--soft:#E3F1F2;--mono:"JetBrains Mono","Cascadia Code",Consolas,ui-monospace,monospace;--sans:"Work Sans","Segoe UI",system-ui,sans-serif}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0F1514;--panel:#161D1C;--ink:#E4EBE8;--muted:#98A5A0;--rule:#26302D;--accent:#5AC8D3;--soft:#12302F}}
:root[data-theme=dark]{--bg:#0F1514;--panel:#161D1C;--ink:#E4EBE8;--muted:#98A5A0;--rule:#26302D;--accent:#5AC8D3;--soft:#12302F}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
.app{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:100vh}
@media(max-width:820px){.app{grid-template-columns:minmax(0,1fr)}}
aside{border-right:1px solid var(--rule);padding:18px 16px;background:var(--panel)}
aside h1{font-size:1rem;margin:0 0 4px}aside .sub{font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-bottom:14px}
.thread{display:block;width:100%;text-align:left;border:1px solid var(--rule);border-radius:4px;background:transparent;color:var(--ink);padding:10px;margin-bottom:8px;cursor:pointer;font:inherit}
.thread[aria-pressed=true]{border-color:var(--accent);background:var(--soft)}
.thread b{display:block}.thread span{font-family:var(--mono);font-size:.68rem;color:var(--muted);display:block;overflow-wrap:anywhere}
main{padding:22px 26px;max-width:1100px}
h2{margin:0 0 2px;font-size:1.3rem}.id{font-family:var(--mono);font-size:.72rem;color:var(--muted);margin-bottom:16px}
svg{width:100%;height:auto;background:var(--panel);border:1px solid var(--rule);border-radius:4px}
.n text{font-family:var(--mono);font-size:11px;fill:var(--ink)}.n .k{fill:var(--muted);font-size:9px}
.e{stroke:var(--muted);stroke-opacity:.45;stroke-width:1}.e.lead{stroke:var(--accent);stroke-width:2;stroke-opacity:1}.e.seats{stroke-opacity:.18}
circle.chair{fill:var(--soft);stroke:var(--accent)}circle.thread{fill:var(--accent)}circle.conductor{fill:var(--panel);stroke:var(--muted);stroke-dasharray:3 2}
table{border-collapse:collapse;width:100%;margin-top:18px;font-size:.9rem}th{text-align:left;font-family:var(--mono);font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:0 10px 6px 0;border-bottom:1px solid var(--rule)}
td{padding:8px 10px 8px 0;border-bottom:1px solid var(--rule);vertical-align:top}td.m{font-family:var(--mono);font-size:.76rem}
code{font-family:var(--mono);font-size:.76rem;background:var(--soft);padding:2px 6px;border-radius:3px;overflow-wrap:anywhere}
.tag{font-family:var(--mono);font-size:.64rem;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.foot{margin-top:18px;color:var(--muted);font-size:.82rem;max-width:70ch}
</style></head><body>
<div class="app">
<aside><h1>Convoy threads</h1><div class="sub">__COUNT__ visible to this session -rendered locally</div><div id="threads"></div></aside>
<main><h2 id="title"></h2><div class="id" id="cid"></div><div id="svg"></div><div id="chairs"></div>
<p class="foot">The command resumes that neuron at its most recent place: Convoy resolves the vendor token on this machine at run time, so no token is in this page. It refuses when a live body already holds the chair, or when the chair has no token for its current harness (then <code>launch --seat</code>).</p></main>
</div>
<script>
(function(){
var DATA=__DATA__;var sel=0;
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function renderList(){var box=document.getElementById("threads");box.innerHTML="";DATA.forEach(function(t,i){var g=t.graph;var chairs=g.nodes.filter(function(n){return n.kind==="chair"});var b=document.createElement("button");b.className="thread";b.setAttribute("aria-pressed",String(i===sel));b.innerHTML="<b>"+esc(g.thread||"(unbound)")+"</b><span>"+esc(g.convoy_id||"no cvy id")+"</span><span>"+chairs.length+" chair"+(chairs.length===1?"":"s")+" -"+esc(t.root)+"</span>";b.onclick=function(){sel=i;render();};box.appendChild(b);});}
function renderGraph(t){var g=t.graph;var nodes=g.nodes.filter(function(n){return n.kind==="thread"||n.kind==="chair"||n.kind==="conductor"});var W=900,H=520,cx=W/2,cy=H/2,R=Math.min(W,H)/2-70;var pos={};var ring=nodes.filter(function(n){return n.kind!=="thread"});ring.forEach(function(n,i){var a=-Math.PI/2+i*2*Math.PI/Math.max(ring.length,1);pos[n.id]=[cx+R*Math.cos(a),cy+R*Math.sin(a)];});nodes.forEach(function(n){if(n.kind==="thread")pos[n.id]=[cx,cy];});
var s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="thread graph">';g.edges.forEach(function(e){if(!pos[e.from]||!pos[e.to])return;var a=pos[e.from],b=pos[e.to];s+='<line class="e '+esc(e.kind)+'" x1="'+a[0]+'" y1="'+a[1]+'" x2="'+b[0]+'" y2="'+b[1]+'"/>';});
nodes.forEach(function(n){var p=pos[n.id];var r=n.kind==="thread"?14:n.kind==="chair"?18:12;var lab=n.kind==="chair"?n.session_id:(n.kind==="thread"?(g.thread||"thread"):"grok-bot");var sub=n.kind==="chair"?((n.current.harness||"")+(n.current.model?" -"+n.current.model:"")+(n.lead?" -lead":"")):(n.kind==="thread"?(g.convoy_id||""):"conductor");s+='<g class="n"><circle class="'+n.kind+'" cx="'+p[0]+'" cy="'+p[1]+'" r="'+r+'"/><text x="'+p[0]+'" y="'+(p[1]+r+14)+'" text-anchor="middle">'+esc(lab)+'</text><text class="k" x="'+p[0]+'" y="'+(p[1]+r+26)+'" text-anchor="middle">'+esc(sub)+'</text></g>';});
s+='</svg>';document.getElementById("svg").innerHTML=s;}
function renderChairs(t){var g=t.graph;var chairs=g.nodes.filter(function(n){return n.kind==="chair"});var h='<table><thead><tr><th>chair</th><th>occupant</th><th>lineage</th><th>resume</th><th>command</th></tr></thead><tbody>';chairs.forEach(function(n){var last=n.lineage.length?n.lineage[n.lineage.length-1]:null;var lin=last?(last.kind+" "+(last.state||"")+" "+(last.ts||"").slice(0,19)+"Z"):"genesis";var res=n.resume.available?("available for "+n.resume["for"]):"none (launch --seat)";var cmd=n.resume_command||"";h+='<tr><td class="m">'+esc(n.session_id)+(n.lead?' <span class="tag">lead</span>':"")+'</td><td>'+esc(n.current.harness||"")+(n.current.model?"<br><span class=m>"+esc(n.current.model)+"</span>":"")+'</td><td class="m">'+esc(lin)+'</td><td class="m">'+esc(res)+'</td><td><code>'+esc(cmd)+'</code></td></tr>';});h+='</tbody></table>';document.getElementById("chairs").innerHTML=h;}
function render(){renderList();var t=DATA[sel];if(!t){document.getElementById("title").textContent="No threads visible";return;}document.getElementById("title").textContent=t.graph.thread||"(unbound thread)";document.getElementById("cid").textContent=(t.graph.convoy_id||"")+"  - "+t.root;renderGraph(t);renderChairs(t);}
render();
})();
</script></body></html>
"""
