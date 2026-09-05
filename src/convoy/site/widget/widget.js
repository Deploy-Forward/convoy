// convoy widget: renders /api/model, refreshes without flicker, POSTs actions.
// Everything shown comes from the model; nothing is invented for looks.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { model: null, selected: 1, usage: "session", pinned: true, pending: null };
  const chev = '<svg viewBox="0 0 10 10"><path d="M1.5 3.5 5 7l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function nz(v, dash) { return v == null || v === "" ? (dash || "unknown") : v; }

  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    return r.json();
  }

  function thread() {
    const m = state.model; if (!m || !m.threads || !m.threads.length) return null;
    return m.threads.find((t) => t.n === state.selected) || m.threads[0];
  }

  function renderDots() {
    const m = state.model; const box = $("dots"); if (!m) return;
    const html = (m.threads || []).map((t) => {
      const cls = ["dot", t.n === state.selected ? "on" : "", t.stale_ring ? "stale" : ""].join(" ");
      return `<span class="${cls}" data-n="${t.n}" title="${esc(t.thread || "")} · ${esc(t.convoy_id || "")}"><i></i>${t.n}</span>`;
    }).join("");
    if (box.innerHTML !== html) box.innerHTML = html;
  }

  function usageRows(t) {
    const u = t.usage || {};
    return Object.keys(u).map((h) => {
      const row = u[h] || {};
      const pct = state.usage === "session" ? row.bar_session : row.bar_week;
      const probing = row.probing === true;
      const known = typeof pct === "number";
      const cls = probing ? "probing" : (known ? "" : "unknown");
      const label = probing ? "probing…" : (known ? pct + "%" : "unknown");
      return `<div class="usage-row"><span>${esc(h)}</span><div class="bar ${cls}"><i style="width:${known ? pct : 0}%"></i></div><span class="pct ${known ? "" : "unknown"}">${label}</span></div>`;
    }).join("") || `<div class="foot">no harness attached</div>`;
  }

  function chairRow(c) {
    const cls = ["row", c.lead ? "lead" : "", c.session_id === state.selectedSeat ? "sel" : ""].join(" ");
    const model = c.model ? `<span class="dd">${esc(c.model)}${chev}</span>` : (c.models ? `<span class="dd">${esc(c.models[0] || "")}${chev}</span>` : `<span class="dd na">model${chev}</span>`);
    const effort = c.effort ? `<span class="dd">${esc(c.effort)}${chev}</span>` : (c.effort_keys && c.effort_keys.length ? `<span class="dd na">effort${chev}</span>` : `<span class="dd na">n/a</span>`);
    const chip = c.chip || (c.body === false ? "gone" : "unknown");
    const nudge = c.nudge_available ? `<span class="nudge" data-nudge="${esc(c.session_id)}">NUDGE</span>` : "";
    const wait = c.waiting ? ` · ${c.waiting}w` : "";
    return `<tr class="${cls}" data-seat="${esc(c.session_id)}" title="${esc(c.worktree || "")}${c.branch ? " · " + esc(c.branch) : ""}">
      <td class="seat">${esc(c.lead ? "lead" : c.seat_label || c.session_id)}</td>
      <td>${esc(c.harness || "")}</td>
      <td>${model}</td>
      <td>${effort}</td>
      <td class="chipcell"><span class="st ${esc(chip)}"><i></i>${esc(chip)}${wait}</span> ${nudge}</td>
    </tr>`;
  }

  function render() {
    const m = state.model; const main = $("main");
    if (!m || !m.ok) { main.innerHTML = `<div class="empty">${esc((m && m.error) || "no model")}</div>`; return; }
    if (m.loading) { return; }
    renderDots();
    const t = thread();
    if (!t) { main.innerHTML = `<div class="empty">no thread on this machine yet · press + to start one</div>`; return; }
    const repo = t.repo || {};
    const connected = repo.connected === true;
    const html = `
    <section class="card repo">
      <div class="eyebrow"><span>Repo</span><span class="chip ${connected ? "ok" : "local"}">${connected ? "connected" : "local"}</span></div>
      ${connected && repo.url ? `<div class="url">${esc(repo.url)}</div>` : `<div class="url" style="color:var(--ink-2)">no remote recorded</div>`}
      <div class="eyebrow" style="margin-top:12px"><span>Local storage · thread</span></div>
      <div class="path">${esc(nz(repo.local_storage, ""))}</div>
      <div class="meta">${esc(nz(repo.index_path, ""))}</div>
      <div class="meta">convoy_id <b>${esc(nz(t.convoy_id))}</b> · bound to thread <b>${esc(nz(t.thread))}</b>${t.lead ? ` · lead <b>${esc(t.lead)}</b>` : ""}</div>
    </section>
    <section class="card">
      <div class="eyebrow"><span>Usage remaining</span><span class="seg nodrag"><span class="${state.usage === "session" ? "on" : ""}" data-usage="session">session</span><span class="${state.usage === "week" ? "on" : ""}" data-usage="week">week</span></span></div>
      ${usageRows(t)}
      ${Object.values(t.usage || {}).map((u) => u.footnote).filter(Boolean).slice(0, 1).map((f) => `<div class="foot">${esc(f)}</div>`).join("")}
    </section>
    <section class="card">
      <div class="eyebrow"><span>Harnesses · neurons in thread</span><span class="right">${t.seated_n || 0} seated · ${(t.seats && t.seats.stale) || 0} stale</span></div>
      <table><colgroup><col style="width:33%"><col style="width:11%"><col style="width:19%"><col style="width:13%"><col style="width:24%"></colgroup>
      <thead><tr><th>seat</th><th>harness</th><th>model</th><th>effort</th><th>chip</th></tr></thead>
      <tbody>${(t.chairs || []).map(chairRow).join("")}</tbody></table>
      ${m.footer ? `<div class="foot">${esc(m.footer)}</div>` : ""}
    </section>`;
    if (main.innerHTML !== html) main.innerHTML = html;
    const ls = t.last_stamp || m.last_stamp; if (!state.selectedSeat) $("status").textContent = ls && ls.summary ? "last stamp · " + ls.summary : "";
    $("clock").textContent = (m.now || "").slice(11, 19) + "Z";
    $("pin").classList.toggle("on", state.pinned);
  }

  async function refresh() {
    try { state.model = await api("/api/model"); } catch (e) { state.model = { ok: false, error: "widget server unreachable" }; }
    render();
  }

  document.addEventListener("click", async (e) => {
    const dot = e.target.closest(".dot"); if (dot) { state.selected = +dot.dataset.n; render(); return; }
    const seg = e.target.closest("[data-usage]"); if (seg) { state.usage = seg.dataset.usage; render(); return; }
    const nd = e.target.closest("[data-nudge]"); if (nd) { e.stopPropagation(); await nudgeDry(nd.dataset.nudge); return; }
    const row = e.target.closest("tr.row"); if (row) {
      state.selectedSeat = state.selectedSeat === row.dataset.seat ? null : row.dataset.seat; render();
      if (!state.selectedSeat) { $("status").textContent = ""; return; }
      const t = thread(); const r = await api("/api/focus", { root: t.root, seat: row.dataset.seat });
      $("status").textContent = r.focused ? "focused pane of " + row.dataset.seat : (row.dataset.seat + " selected · pane focus: " + (r.reason || r.error || "not available on this host"));
      return; }
    if (e.target.closest("#pin")) { state.pinned = !state.pinned; const r = await api("/api/pin", { on: state.pinned }); state.pinned = !!r.on; render(); return; }
    if (e.target.closest("#plus")) { await openStart(); return; }
    if (e.target.id === "start-cancel") { $("start").classList.remove("show"); return; }
    if (e.target.id === "start-go") { await submitStart(); return; }
    const pick = e.target.closest("[data-pick]"); if (pick) { $("s-repo").value = pick.dataset.pick; return; }
    if (e.target.id === "s-add") { addSeatRow(); return; }
    const rm = e.target.closest("[data-rm]"); if (rm) { rm.closest(".seat-row").remove(); return; }
    if (e.target.closest("#tag")) { e.preventDefault(); await api("/api/open", { url: "https://convoy.bot" }); return; }
  });

  async function nudgeDry(seat) {
    const t = thread(); const r = await api("/api/nudge", { root: t.root, seat, dry_run: true });
    state.pending = { seat, root: t.root };
    const c = $("confirm");
    c.innerHTML = `<div>nudge <b>${esc(seat)}</b> · ${esc(r.ok ? (r.adapter || r.transport || "") : (r.error || "refused"))}</div><div class="cmd">${esc(r.text || r.error || JSON.stringify(r))}</div><div class="btns"><span id="nudge-cancel">cancel</span>${r.ok ? '<span class="go" id="nudge-go">type it</span>' : ""}</div>`;
    c.classList.add("show");
  }
  document.addEventListener("click", async (e) => {
    if (e.target.id === "nudge-cancel") { $("confirm").classList.remove("show"); state.pending = null; }
    if (e.target.id === "nudge-go" && state.pending) {
      const r = await api("/api/nudge", { ...state.pending, dry_run: false });
      $("confirm").innerHTML = `<div>${esc(r.delivery || r.error || "")}${r.nudge_id ? " · " + esc(r.nudge_id) : ""} · delivered only when ${esc(state.pending.seat)} writes its own row</div><div class="btns"><span id="nudge-cancel">close</span></div>`;
    }
  });

  // ---- the "+" flow: GitHub? -> repo -> harnesses -> N seats -> launch (original spec)
  let cardCache = null;
  async function openStart() {
    const box = $("start"); box.classList.add("show");
    box.innerHTML = `<div class="eyebrow"><span>New thread</span><span class="right">reading the card…</span></div>`;
    cardCache = await api("/api/card", {});
    const rows = (cardCache.rows || []);
    const recent = (cardCache.recent || []);
    const installed = rows.filter((r) => r.installed);
    const harnessOpts = rows.map((r) => `<label class="hx ${r.installed ? "" : "off"}" title="${esc(r.install && r.install.page ? r.install.page : "")}"><input type="checkbox" value="${esc(r.harness)}" ${r.installed ? "" : "disabled"}> ${esc(r.harness)} <small>${r.installed ? (r.where || []).join("/") : "not installed"}</small></label>`).join("");
    box.innerHTML = `
      <div class="eyebrow"><span>New thread</span><span class="right">${installed.length} harness${installed.length === 1 ? "" : "es"} installed</span></div>
      <div class="frow"><span class="lbl">GitHub?</span><span class="seg" id="s-gh"><span class="on" data-gh="yes">yes</span><span data-gh="no">no</span></span></div>
      <div class="frow"><span class="lbl">repo</span><input id="s-repo" class="in" placeholder="https://github.com/owner/repo.git or a local path"></div>
      ${recent.length ? `<div class="frow"><span class="lbl">recent</span><div class="picks">${recent.map((r) => `<span class="pick" data-pick="${esc(r.root)}" title="${esc(r.root)}">${esc(r.thread || r.convoy_id || r.root)}</span>`).join("")}</div></div>` : ""}
      <div class="frow"><span class="lbl">thread</span><input id="s-thread" class="in" placeholder="thread key (e.g. demo)"></div>
      <div class="frow"><span class="lbl">harnesses</span><div class="hxs">${harnessOpts || "<small>none installed on this host</small>"}</div></div>
      <div class="frow"><span class="lbl">neurons</span><div id="s-seats" class="seats"></div></div>
      <div class="frow"><span class="lbl"></span><span class="pick" id="s-add">+ seat</span></div>
      <div class="btns"><span id="start-cancel">cancel</span><span class="go" id="start-go">launch</span></div>
      <div class="foot" id="s-out"></div>`;
    addSeatRow();
  }
  function seatRowHtml() {
    const rows = (cardCache && cardCache.rows) || [];
    const opts = rows.filter((x) => x.installed).map((x) => `<option value="${esc(x.harness)}">${esc(x.harness)}</option>`).join("");
    return `<div class="seat-row"><select class="in sel-h">${opts}</select><input class="in sel-m" placeholder="model"><select class="in sel-e"><option value="">effort</option></select><select class="in sel-w"><option value="local">local</option></select><span class="pick" data-rm="1">×</span></div>`;
  }
  function addSeatRow() {
    const box = $("s-seats"); const div = document.createElement("div"); div.innerHTML = seatRowHtml(); const row = div.firstElementChild; box.appendChild(row);
    const sync = () => {
      const h = row.querySelector(".sel-h").value; const r = ((cardCache && cardCache.rows) || []).find((x) => x.harness === h) || {};
      const e = row.querySelector(".sel-e"); const keys = (r.effort && r.effort.keys) || [];
      e.innerHTML = `<option value="">effort</option>` + keys.map((k) => `<option>${esc(k)}</option>`).join(""); e.disabled = !keys.length;
      const w = row.querySelector(".sel-w"); const where = r.where || ["local"]; w.innerHTML = where.map((x) => `<option>${esc(x)}</option>`).join("");
      const m = row.querySelector(".sel-m"); m.placeholder = r.models && r.models.length ? "model: " + r.models.join(", ") : "model (free field: no catalog)";
    };
    row.querySelector(".sel-h").addEventListener("change", sync); sync();
  }
  document.addEventListener("click", (e) => { const g = e.target.closest("[data-gh]"); if (g) { g.parentElement.querySelectorAll("span").forEach((x) => x.classList.remove("on")); g.classList.add("on"); } });
  async function submitStart() {
    const gh = $("s-gh").querySelector(".on").dataset.gh === "yes";
    const seats = [...document.querySelectorAll("#s-seats .seat-row")].map((r) => ({ harness: r.querySelector(".sel-h").value, model: r.querySelector(".sel-m").value || null, effort: r.querySelector(".sel-e").value || null, where: r.querySelector(".sel-w").value || "local" }));
    const harnesses = [...document.querySelectorAll(".hxs input:checked")].map((i) => i.value);
    const body = { repo: $("s-repo").value || null, thread: $("s-thread").value || null, github: gh, harnesses: harnesses.length ? harnesses : [...new Set(seats.map((s) => s.harness))], seats, launch: true };
    $("s-out").textContent = "onboarding…";
    const r = await api("/api/start", body);
    if (!r.ok) { const ob = r.onboard || {}; $("s-out").textContent = (r.crew && r.crew.error) || ob.error || (ob.ask && ob.ask.text) || JSON.stringify(r).slice(0, 300); return; }
    const cw = r.crew || {}; $("s-out").textContent = `bound ${r.onboard.thread} · ${cw.seats ? cw.seats.length + " chair(s) joined" : "no seats"} · ${cw.launched ? "window up; chairs pending until they ack" : "not launched"}`;
    setTimeout(refresh, 800);
  }

  refresh();
  setInterval(refresh, Number(document.body.dataset.refresh || 3000));
})();
