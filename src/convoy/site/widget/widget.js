// convoy widget: one card, six zones (thread · bound · seats · act · history · usage).
// Everything shown comes from /api/model and /api/feed; nothing is invented for looks.
// Vendor marks: simple-icons (CC0 1.0) for claude, cursor, gemini; @lobehub/icons-static-svg (MIT)
// for OpenAI (codex) and Grok. Marks are the vendors' trademarks, shown to identify the vendor.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { model: null, selected: 1, selectedSeat: null, pinned: true, usageTab: "thread", histTab: "session", feed: [], feedFor: null };
  const chat = { seat: null, reply: "", ok: false, meta: "", draft: "", waiting: null };

  const MARK = {
    claude: '<svg viewBox="0 0 24 24"><path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1214-.5343-.7043.0546-.3522.4797-.3218.6863.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.2549h.3886l.0546-.1579-.1336-.0972-.1032-.0971-2.3496-1.5908-2.5439-1.6817-1.3323-.9714-.7164-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0608.2246.0607.8925.6863 1.9064 1.4754 2.4893 1.8335.3643.3035.1457-.1032.0182-.0729-.1639-.2731-1.3505-2.4407-1.4451-2.4893-.6436-1.0321-.17-.6193c-.0607-.2549-.1032-.4674-.1032-.7286l.7468-1.0139.4128-.1336.9957.1336.4189.3643.6193 1.4147 1.0018 2.2282 1.5543 3.0286.4553.8985.2428.8318.0911.2549h.1579v-.1457l.1275-1.7062.2368-2.0947.2306-2.6956.079-.7589.3764-.9107.7468-.4918.5828.2792.4797.6863-.0668.4432-.2853 1.8517-.5586 2.9012-.3643 1.9429h.2124l.2428-.2428.9835-1.3052 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.7589 1.129-.34 1.1655-1.0625 1.3474-.8804 1.1411-1.2626 1.7-.7893 1.3596.0729.1093.1882-.0182 2.8526-.6071 1.5422-.2793 1.8396-.3156.8318.3886.0911.3946-.3278.8075-1.9672.4857-2.3072.4614-3.4357.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.6211l3.0165.2246.7893.5222.4735.6375-.079.4857-1.2141.6193-1.6393-.3886-3.8244-.9107-1.3112-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5074 2.3314.1275.5768-.3218.4553-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.6208h-.1275v.17l.4432.6496 2.3436 3.5208.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3717-1.9247-1.4147-2.1676-1.1411-1.9428-.1396.0789-.6739 7.2555-.3157.3704-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9247.3157-1.5301.2853-1.9004.17-.6314-.0121-.0425-.1396.0182-1.4329 1.9672-2.1797 2.9451-1.7244 1.8456-.4128.1639-.7164-.3704.0668-.6618.4006-.5889 2.386-3.0347 1.4389-1.8821.929-1.0868-.0061-.1579h-.0546l-6.3383 4.1155-1.129.1457-.4857-.4553.0608-.7468.2306-.2428 1.9064-1.3112-.0061.0061z"/></svg>',
    codex: '<svg viewBox="0 0 24 24" fill-rule="evenodd"><path d="M8.086.457a6.105 6.105 0 013.046-.415c1.333.153 2.521.72 3.564 1.7a.117.117 0 00.107.029c1.408-.346 2.762-.224 4.061.366l.063.03.154.076c1.357.703 2.33 1.77 2.918 3.198.278.679.418 1.388.421 2.126a5.655 5.655 0 01-.18 1.631.167.167 0 00.04.155 5.982 5.982 0 011.578 2.891c.385 1.901-.01 3.615-1.183 5.14l-.182.22a6.063 6.063 0 01-2.934 1.851.162.162 0 00-.108.102c-.255.736-.511 1.364-.987 1.992-1.199 1.582-2.962 2.462-4.948 2.451-1.583-.008-2.986-.587-4.21-1.736a.145.145 0 00-.14-.032c-.518.167-1.04.191-1.604.185a5.924 5.924 0 01-2.595-.622 6.058 6.058 0 01-2.146-1.781c-.203-.269-.404-.522-.551-.821a7.74 7.74 0 01-.495-1.283 6.11 6.11 0 01-.017-3.064.166.166 0 00.008-.074.115.115 0 00-.037-.064 5.958 5.958 0 01-1.38-2.202 5.196 5.196 0 01-.333-1.589 6.915 6.915 0 01.188-2.132c.45-1.484 1.309-2.648 2.577-3.493.282-.188.55-.334.802-.438.286-.12.573-.22.861-.304a.129.129 0 00.087-.087A6.016 6.016 0 015.635 2.31C6.315 1.464 7.132.846 8.086.457zm-.804 7.85a.848.848 0 00-1.473.842l1.694 2.965-1.688 2.848a.849.849 0 001.46.864l1.94-3.272a.849.849 0 00.007-.854l-1.94-3.393zm5.446 6.24a.849.849 0 000 1.695h4.848a.849.849 0 000-1.696h-4.848z"/></svg>',
    grok: '<svg viewBox="0 0 24 24" fill-rule="evenodd"><path d="M9.27 15.29l7.978-5.897c.391-.29.95-.177 1.137.272.98 2.369.542 5.215-1.41 7.169-1.951 1.954-4.667 2.382-7.149 1.406l-2.711 1.257c3.889 2.661 8.611 2.003 11.562-.953 2.341-2.344 3.066-5.539 2.388-8.42l.006.007c-.983-4.232.242-5.924 2.75-9.383.06-.082.12-.164.179-.248l-3.301 3.305v-.01L9.267 15.292M7.623 16.723c-2.792-2.67-2.31-6.801.071-9.184 1.761-1.763 4.647-2.483 7.166-1.425l2.705-1.25a7.808 7.808 0 00-1.829-1A8.975 8.975 0 005.984 5.83c-2.533 2.536-3.33 6.436-1.962 9.764 1.022 2.487-.653 4.246-2.34 6.022-.599.63-1.199 1.259-1.682 1.925l7.62-6.815"/></svg>',
    "cursor-agent": '<svg viewBox="0 0 24 24"><path d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.611-5.55a.84.84 0 0 0 .42-.726V6.404a.84.84 0 0 0-.42-.726L12.497.131a1 1 0 0 0-.994 0zm.493 1.756 8.6 4.966-8.6 4.966-8.6-4.966zm-9.1 6.7 8.6 4.966v9.93l-8.6-4.966zm18.2 0v9.93l-8.6 4.966v-9.93z"/></svg>',
    agy: '<svg viewBox="0 0 24 24"><path d="M11.04 19.32Q12 21.51 12 24q0-2.49.93-4.68.96-2.19 2.58-3.81t3.81-2.55Q21.51 12 24 12q-2.49 0-4.68-.93-2.19-.96-3.81-2.58t-2.55-3.81Q12 2.49 12 0q0 2.49-.96 4.68-.93 2.19-2.55 3.81T4.68 11.07 0 12q2.49 0 4.68.96 2.19.93 3.81 2.55t2.55 3.81z"/></svg>',
    hermes: '<svg viewBox="0 0 24 24"><path d="M3 12c4-8 14-8 18 0-4 8-14 8-18 0zm9-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>',
    pi: '<svg viewBox="0 0 24 24"><path d="M4 6h16v2.4h-2.6V18h-2.4V8.4H9V18H6.6V8.4H4z"/></svg>',
  };
  // Every vendor mark in one flat ink, no chip (Marco 2026-09-08): the glyph identifies the vendor, colour does not.
  const mark = (h) => `<span class="vm" title="${esc(h)}">${MARK[h] || '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="3"/></svg>'}</span>`;

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    return r.json();
  }
  function thread() { const m = state.model; if (!m || !m.threads || !m.threads.length) return null; return m.threads.find((t) => t.n === state.selected) || m.threads[0]; }
  const short = (ts) => ts ? String(ts).slice(11, 19) + "Z" : "";

  $("dots").addEventListener("wheel", (e) => { const b = $("dots"); if (b.scrollWidth > b.clientWidth && e.deltaY) { b.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });

  // ---------- zone 1: thread ----------
  function renderHeader() {
    const m = state.model; const box = $("dots"); if (!m) return;
    // Marco 2026-09-10: the strip clipped past four threads and could not archive one.
    // Now it scrolls (wheel = sideways), every tab has an × that archives the thread off
    // the strip (index flag only; nothing under the root changes), and a trailing chip
    // shows how many are archived and reveals them dimmed; clicking a dimmed one restores it.
    const hidden = m.hidden_threads || [];
    let html = (m.threads || []).map((t) => `<span class="dot ${t.n === state.selected ? "on" : ""} ${t.stale_ring ? "stale" : ""}" data-n="${t.n}" title="${esc(t.thread || "")} · ${esc(t.convoy_id || "")}"><i></i>${esc(t.thread || t.n)}<b class="x" data-hide="${esc(t.convoy_id || "")}" title="archive this thread off the strip (kept on disk)">×</b></span>`).join("");
    if (hidden.length) {
      html += `<span class="dot more ${state.showHiddenThreads ? "on" : ""}" data-toggle-hidden="1" title="archived threads">${state.showHiddenThreads ? "hide" : "+" + hidden.length}</span>`;
      if (state.showHiddenThreads) html += hidden.map((h) => `<span class="dot hid" data-unhide="${esc(h.convoy_id || "")}" title="restore ${esc(h.thread || "")} to the strip"><i></i>${esc(h.thread || h.convoy_id)}</span>`).join("");
    }
    if (box.innerHTML !== html) box.innerHTML = html;
    const t = thread(); $("count").textContent = t ? `${t.seated_n || 0}/${(t.chairs || []).length} seated` : "";
    $("pin").classList.toggle("on", state.pinned);
  }

  // ---------- zone 2: bound ----------
  function zoneBound(t) {
    const repo = t.repo || {}; const connected = repo.connected === true;
    const flags = `--root ${t.root || "."}`;
    return `<section class="z">
      <div class="bound"><span class="what">Bound</span>${connected ? `<span class="chip ok">GitHub</span><span class="repo" title="${esc(repo.url)}">${esc(repo.url)}</span>` : `<span class="chip local">Local · no GitHub</span><span class="repo">${esc(t.thread || "")}</span>`}</div>
      <details class="disc"><summary>${esc((repo.local_storage || "").replace(/^.*[\\\\/](?=[^\\\\/]+[\\\\/]\\.convoy$)/, "…/"))} · ${esc(t.convoy_id || "")} · copy flags</summary>
        <div class="kv"><b>thread</b><span>${esc(t.thread || "")}</span><span></span>
        <b>convoy_id</b><span>${esc(t.convoy_id || "")}</span><span class="copy" data-copy="${esc(t.convoy_id || "")}">copy</span>
        <b>.convoy</b><span>${esc(repo.local_storage || "")}</span><span class="copy" data-copy="${esc(repo.local_storage || "")}">copy</span>
        <b>index</b><span>${esc(repo.index_path || "")}</span><span></span>
        <b>flags</b><span>${esc(flags)}</span><span class="copy" data-copy="${esc(flags)}">copy</span>
        <b>lead</b><span>${esc(t.lead || "unknown")}</span><span></span></div>
      </details></section>`;
  }

  // ---------- zone 3: seats ----------
  function bodyChip(c) {
    const bs = c.body_state || (c.body ? "live" : "no-body");
    if (bs === "live") { const sub = c.chip === "working" ? "working" : c.chip === "stale" ? "stale" : "idle"; const wait = c.waiting ? ` · ${c.waiting}w` : ""; return `<span class="bs live ${sub}" title="process tied to this chair by token or cwd"><i></i>live · ${sub}${wait}</span>`; }
    if (bs === "gone") return `<span class="bs gone" title="the chair's pane was closed with consent"><i></i>gone</span>`;
    return `<span class="bs nobody" title="no process Convoy can tie to this chair by token or cwd; a codex pane on Windows exposes neither, so it may well be alive"><i></i>no body found${c.waiting ? ` · ${c.waiting}w` : ""}</span>`;
  }
  function archivedRow(c) {
    return `<tr class="row archived" data-seat="${esc(c.session_id)}" title="${esc(c.worktree || "")}">
      <td class="seat">${esc(c.seat_label || c.session_id)}</td>
      <td><span class="hn">${mark(c.harness)}${esc(c.harness || "")}</span></td>
      <td colspan="3" style="overflow:visible"><span class="bs gone" style="margin-right:10px"><i></i>archived</span><span class="btn" data-relaunch="${esc(c.session_id)}">relaunch</span> <span class="btn" data-unarchive="${esc(c.session_id)}">unarchive</span></td>
      <td></td></tr>`;
  }
  function chairRow(c) {
    const cls = ["row", c.lead ? "lead" : "", c.session_id === state.selectedSeat ? "sel" : ""].join(" ");
    const model = c.models && c.models.length
      ? `<select class="tune" data-tune="model" data-seat="${esc(c.session_id)}">${(c.model && !c.models.includes(c.model)) ? `<option selected>${esc(c.model)}</option>` : ""}${c.models.map((m) => `<option ${m === c.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>`
      : `<input class="tune" data-tune="model" data-seat="${esc(c.session_id)}" value="${esc(c.model || "")}" placeholder="model" title="no catalog for ${esc(c.harness || "")}: typed through as-is">`;
    const keys = c.effort_keys || [];
    const effort = keys.length ? `<select class="tune" data-tune="effort" data-seat="${esc(c.session_id)}"><option value="" ${c.effort ? "" : "selected"}>effort</option>${keys.map((k) => `<option ${k === c.effort ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>` : `<select class="tune" disabled title="no effort vocabulary for ${esc(c.harness || "")}"><option>n/a</option></select>`;
    const nudge = c.nudge_available ? ` <span class="nudge" data-nudge="${esc(c.session_id)}">NUDGE</span>` : "";
    const wait = chat.waiting && chat.waiting.seat === c.session_id ? ` <span class="waiting"><i></i>waiting on ${esc(c.seat_label || c.session_id)}…</span>` : "";
    return `<tr class="${cls}" data-seat="${esc(c.session_id)}" title="${esc(c.worktree || "")}${c.branch ? " · " + esc(c.branch) : ""}">
      <td class="seat">${esc(c.lead ? "lead" : c.seat_label || c.session_id)}</td>
      <td><span class="hn">${mark(c.harness)}${esc(c.harness || "")}</span></td>
      <td title="${c.own_usage ? esc("this pane's own reading at " + c.own_usage.ts + ": " + (typeof c.own_usage.session_pct === "number" ? (100 - c.own_usage.session_pct) + "% left 5h" : "session unknown") + ", " + (typeof c.own_usage.week_pct === "number" ? (100 - c.own_usage.week_pct) + "% left week" : "week unknown")) : "no usage row from this pane yet (it stamps one after tool calls)"}">${bodyChip(c)}${c.own_usage ? `<span class="own ${c.own_usage.limited ? "limit" : ""}">${typeof c.own_usage.week_pct === "number" ? (100 - c.own_usage.week_pct) + "%w" : ""}${typeof c.own_usage.session_pct === "number" ? " " + (100 - c.own_usage.session_pct) + "%s" : ""}</span>` : ""}${nudge}${wait}</td>
      <td>${model}</td>
      <td>${effort}</td>
      <td class="x" data-archive="${esc(c.session_id)}" title="archive this seat: hidden here, kept on the thread; show archived to relaunch">×</td>
    </tr>`;
  }
  function zoneSeats(t) {
    return `<section class="z">
      <div class="eyebrow"><span>Seats</span><span class="right">${t.seated_n || 0} seated · ${(t.seats && t.seats.stale) || 0} stale</span></div>
      <table><colgroup><col style="width:27%"><col style="width:15%"><col style="width:24%"><col style="width:16%"><col style="width:13%"><col style="width:5%"></colgroup>
      <thead><tr><th>seat</th><th>harness</th><th>body</th><th>model</th><th>effort</th><th></th></tr></thead>
      <tbody>${(t.chairs || []).filter((c) => !c.archived).map(chairRow).join("")}${state.showArchived ? (t.chairs || []).filter((c) => c.archived).map(archivedRow).join("") : ""}</tbody></table>
      <div class="legend"><span class="bs live"><i></i>live</span><span class="bs nobody"><i></i>no body found</span><span class="bs gone"><i></i>gone</span>${(t.chairs || []).some((c) => c.archived) ? `<span class="btn" id="toggle-archived" style="margin-left:auto">${state.showArchived ? "hide" : "show"} ${(t.chairs || []).filter((c) => c.archived).length} archived</span>` : ""}</div>
    </section>`;
  }

  // ---------- zone 4: act ----------
  function zoneAct(t) {
    const chairs = t.chairs || []; const seat = state.selectedSeat || (chairs.length === 1 ? chairs[0].session_id : null);
    if (!seat) return `<section class="z"><div class="eyebrow"><span>Act</span><span class="right">select a seat</span></div><div class="meta">click a seat row: ping asks it to identify itself on the feed; message queues text into its inbox; @g1 @luna1 … fans out</div></section>`;
    if (chat.seat !== seat) { chat.seat = seat; chat.reply = ""; chat.ok = false; chat.meta = ""; }
    const draft = chat.draft || ("@" + seat + " ");
    return `<section class="z">
      <div class="eyebrow"><span>Act</span><span class="right">${esc(seat)}</span></div>
      <div class="act"><span class="btn" id="act-ping">ping</span><input class="in" id="act-msg" value="${esc(draft)}"><span class="btn primary" id="act-send">send</span></div>
      ${chat.reply ? `<div class="reply ${chat.ok ? "ok" : ""}">${esc(chat.reply)}</div>` : ""}${chat.meta ? `<div class="meta">${esc(chat.meta)}</div>` : ""}
    </section>`;
  }

  // ---------- zone 5: history ----------
  function zoneHistory(t) {
    const rows = state.feed || []; const latest = rows[0];
    const line = latest ? `<div class="line"><span class="t">${short(latest.ts)}</span> <b>${esc(latest.who || latest.kind)}</b> ${esc(latest.summary || "")}</div>` : `<div class="line">no rows in this window</div>`;
    const sheet = state.histOpen ? `<div class="sheet">${rows.slice(0, 40).map((r) => `<div class="line"><span class="t">${short(r.ts)}</span> <b>${esc(r.who || r.kind)}</b>${r.to ? " → " + esc(r.to) : ""} ${esc(r.summary || "")}${r.delivery ? " · " + esc(r.delivery) : ""}</div>`).join("") || `<div class="line">nothing</div>`}</div>` : "";
    return `<section class="z hist">
      <div class="eyebrow"><span>History</span><span class="seg nodrag"><span class="${state.histTab === "session" ? "on" : ""}" data-hist="session">session</span><span class="${state.histTab === "week" ? "on" : ""}" data-hist="week">week</span></span></div>
      <div id="hist-toggle" style="cursor:pointer">${line}</div>${sheet}
    </section>`;
  }

  // ---------- zone 6: usage ----------
  function meter(title, remaining, used, resets, extra) {
    const known = typeof remaining === "number";
    const limit = known && remaining <= 0;
    return `<div class="bar ${extra.probing ? "probing" : known ? (limit ? "limit" : "") : "unknown"}"><i style="width:${known ? Math.max(remaining, 2) : 100}%"></i></div>
      <div class="lab">${extra.probing ? "probing…" : known ? `<b>${remaining}% left</b>` : "unknown"} · ${title}${resets ? " · reset " + esc(resets) : ""}${limit ? ' <span class="chip limit">limited</span>' : ""}${extra.stale ? ` <span class="stale">· ${esc(extra.stale)}</span>` : ""}</div>`;
  }
  function vendorRow(name, r, seated) {
    if (!r) return "";
    const stale = r.source && r.as_of ? "as of " + String(r.as_of).slice(0, 16).replace("T", " ") + "Z" + (r.age_s != null ? " (" + (r.age_s >= 3600 ? Math.round(r.age_s / 3600) + " h" : Math.round(r.age_s / 60) + " min") + " old)" : "") : "";
    const noMeter = name === "grok" || (r.reason || "").includes("no meter") || (r.reason || "").includes("only inside its own TUI");
    const body = noMeter && typeof r.bar_session !== "number"
      ? `<div class="nometer">${esc(r.reason || "no meter on disk or CLI")}</div>`
      : `<div class="meter">${meter("session", r.bar_session, r.used_session, r.resets && r.resets.session, { probing: r.probing, stale })}${meter("week", r.bar_week, r.used_week, r.resets && r.resets.week, { probing: r.probing, stale })}</div>`;
    const logins = (r.logins || []).map((o) => `<div class="meter alt"><div class="lab">another ${esc(name)} login${o.resets && o.resets.week ? " (week resets " + esc(o.resets.week) + ")" : ""}: ${typeof o.session_pct === "number" ? (100 - o.session_pct) + "% left · 5h" : ""}${typeof o.week_pct === "number" ? " · " + (100 - o.week_pct) + "% left · week" : ""}${o.limited ? ' <span class="chip limit">limited</span>' : ""} <span class="stale">· ${esc(o.as_of || "")}</span></div></div>`).join("");
    // Marco 2026-09-08: explicit, not "near". The chip carries the smallest remaining share.
    const left = [r.bar_session, r.bar_week].filter((v) => typeof v === "number");
    const low = left.length ? Math.min(...left) : null;
    const chip = r.limited ? ' <span class="chip limit">limited' + (low != null ? " · " + low + "% left" : "") + '</span>'
      : (r.near_limit && low != null ? ' <span class="chip near">' + low + '% left</span>' : "");
    return `<div class="vrow ${seated ? "seated" : ""}">${mark(name)}<span class="name">${esc(name)}${chip}</span><div>${body}${logins}</div></div>`;
  }
  function zoneUsage(t) {
    const u = t.usage || {}; const seated = new Set((t.chairs || []).filter((c) => !c.archived).map((c) => c.harness));
    const rank = (n) => u[n].limited ? -1 : (typeof u[n].bar_session === "number" ? u[n].bar_session : 999);
    const all = Object.keys(u).sort((a, b) => rank(a) - rank(b));
    const mine = all.filter((n) => seated.has(n));
    let body;
    if (state.usageTab === "thread") {
      const withMeter = mine.filter((n) => typeof u[n].bar_session === "number" || u[n].probing);
      body = mine.length ? mine.map((n) => vendorRow(n, u[n], true)).join("") : `<div class="empty">no seated harness on this thread</div>`;
      if (mine.length && !withMeter.length) body += `<div class="empty">No usage for this thread's seats<span class="btn" data-usage-tab="overall">see overall</span></div>`;
    } else {
      body = all.length ? all.map((n) => vendorRow(n, u[n], seated.has(n))).join("") : `<div class="empty">no vendor meter Convoy can read</div>`;
    }
    return `<section class="z">
      <div class="eyebrow"><span>Usage</span><span class="utabs nodrag"><span class="${state.usageTab === "thread" ? "on" : ""}" data-usage-tab="thread">thread</span><span class="${state.usageTab === "overall" ? "on" : ""}" data-usage-tab="overall">overall</span></span></div>
      ${body}
    </section>`;
  }

  // ---------- render ----------
  function render() {
    const m = state.model; const main = $("main");
    if (!m || !m.ok) { main.innerHTML = `<div class="empty">${esc((m && m.error) || "no model")}</div>`; return; }
    if (m.loading) return;
    renderHeader();
    const t = thread();
    if (!t) { main.innerHTML = `<div class="empty">no thread on this machine yet · press + to start one</div>`; return; }
    const html = zoneBound(t) + zoneSeats(t) + zoneAct(t) + zoneHistory(t) + zoneUsage(t);
    if (main.innerHTML !== html) {
      const focused = document.activeElement && document.activeElement.id === "act-msg" ? { pos: document.activeElement.selectionStart } : null;
      main.innerHTML = html;
      if (focused && $("act-msg")) { const el = $("act-msg"); el.focus(); try { el.setSelectionRange(focused.pos, focused.pos); } catch (e) {} }
    }
    $("clock").textContent = short(m.now);
    const ls = t.last_stamp || m.last_stamp; if (!chat.waiting) $("status").textContent = ls && ls.summary ? "stamp · " + ls.summary : "";
  }
  async function refresh(force) {
    try { state.model = await api("/api/model" + (force ? "?force=1" : "")); } catch (e) { state.model = { ok: false, error: "widget server unreachable" }; }
    const t = thread();
    if (t && !(state.model && state.model.loading)) {
      const since = state.histTab === "week" ? "7d" : "6h";
      try { const f = await api("/api/feed", { root: t.root, since, limit: 40 }); state.feed = f.rows || []; } catch (e) { state.feed = []; }
    }
    render();
  }

  // ---------- actions ----------
  let watching = null;
  async function watchReply(seat, since, pingId, started) {
    const t = thread(); if (!t) return;
    const r = await api("/api/replies", { root: t.root, seat, since, ping_id: pingId || null });
    if (r.answered) { const last = r.rows[r.rows.length - 1]; chat.reply = (pingId ? "identified · " : "replied · ") + last.summary; chat.ok = true; chat.meta = "own row at " + last.ts; chat.waiting = null; watching = null; render(); return; }
    const waited = Math.round((Date.now() - started) / 1000);
    chat.meta = (pingId ? "queued; waiting for its own feed row citing " + pingId : "queued; waiting for a reply row") + " · " + waited + " s"; chat.waiting = { seat }; render();
    if (waited < 180) watching = setTimeout(() => watchReply(seat, since, pingId, started), 3000); else { chat.meta += " · no reply in 3 min: idle or no body (nudge or relaunch)"; chat.waiting = null; watching = null; render(); }
  }
  async function act(kind) {
    const t = thread(); if (!t) return;
    const seat = state.selectedSeat || ((t.chairs || []).length === 1 ? t.chairs[0].session_id : null); if (!seat) return;
    const raw = kind === "ping" ? "" : ($("act-msg") ? $("act-msg").value : "");
    const mentions = [...raw.matchAll(/(^|\s)@([\w.-]+)/g)].map((m) => m[2]);
    const chairs = (t.chairs || []).map((c) => c.session_id);
    const targets = kind === "ping" ? [seat] : (mentions.length ? mentions.map((m) => chairs.find((c) => c === m || c.startsWith(m + "-") || c.split("-")[0] === m) || m) : [seat]);
    const text = kind === "ping" ? "ping" : raw.replace(/(^|\s)@[\w.-]+/g, "$1").trim();
    if (kind !== "ping" && !text) { chat.reply = "say something after the @mentions"; chat.ok = false; render(); return; }
    const lines = []; let first = null;
    for (const tgt of targets) {
      const one = await api("/api/send", { root: t.root, seat: tgt, body: text, label: kind === "ping" ? "ping" : "widget" });
      lines.push(tgt + ": " + (one.ok ? (one.delivery || "queued") : "refused · " + (one.error || ""))); if (!first) first = one;
    }
    chat.draft = "@" + seat + " ";
    if (targets.length > 1) { chat.reply = lines.join("\n"); chat.ok = false; chat.meta = "delivered: false for each until that chair's own row"; render(); return; }
    if (!first.ok) { chat.reply = "refused: " + (first.error || ""); chat.ok = false; chat.meta = ""; render(); return; }
    chat.ok = false; chat.reply = (kind === "ping" ? "ping " + first.ping_id : "message") + " " + (first.delivery || "queued") + " · delivered: false until " + targets[0] + " acks";
    chat.waiting = { seat: targets[0] };
    if (watching) clearTimeout(watching);
    render(); watchReply(targets[0], first.ts || new Date().toISOString().replace("Z", "000Z"), first.ping_id || null, Date.now());
  }
  async function nudgeDry(seat) {
    const t = thread(); const r = await api("/api/nudge", { root: t.root, seat, dry_run: true });
    state.pending = { seat, root: t.root };
    const c = $("confirm");
    c.innerHTML = `<div>nudge <b>${esc(seat)}</b> · ${esc(r.ok ? (r.adapter || r.transport || "") : (r.error || "refused"))}</div><div class="cmd">${esc(r.text || r.error || JSON.stringify(r))}</div><div class="btns"><span id="nudge-cancel">cancel</span>${r.ok ? '<span class="go" id="nudge-go">type it</span>' : ""}</div>`;
    c.classList.add("show");
  }

  document.addEventListener("change", async (e) => {
    const el = e.target.closest("[data-tune]"); if (!el) return;
    const t = thread(); const body = { root: t.root, seat: el.dataset.seat }; body[el.dataset.tune] = el.value || null;
    $("status").textContent = "applying " + el.dataset.tune + " for " + el.dataset.seat + "…";
    const r = await api("/api/tune", body);
    $("status").textContent = r.ok ? `${el.dataset.seat}: ${el.dataset.tune} = ${el.value || "unset"} (seat rewritten; a live pane picks it up on its next launch)` : ("refused: " + (r.error || JSON.stringify(r)));
    setTimeout(() => refresh(true), 300);
  });
  document.addEventListener("input", (e) => { if (e.target.id === "act-msg") chat.draft = e.target.value; });
  document.addEventListener("keydown", (e) => { if (e.target.id === "act-msg" && e.key === "Enter") act("send"); });
  document.addEventListener("click", async (e) => {
    if (e.target.id === "act-ping") { await act("ping"); return; }
    if (e.target.id === "act-send") { await act("send"); return; }
    if (e.target.id === "nudge-cancel") { $("confirm").classList.remove("show"); state.pending = null; return; }
    if (e.target.id === "nudge-go" && state.pending) { const r = await api("/api/nudge", { ...state.pending, dry_run: false }); $("confirm").innerHTML = `<div>${esc(r.delivery || r.error || "")}${r.nudge_id ? " · " + esc(r.nudge_id) : ""} · delivered only when ${esc(state.pending.seat)} writes its own row</div><div class="btns"><span id="nudge-cancel">close</span></div>`; return; }
    const cp = e.target.closest("[data-copy]"); if (cp) { try { await navigator.clipboard.writeText(cp.dataset.copy); cp.textContent = "copied"; setTimeout(() => (cp.textContent = "copy"), 1200); } catch (x) { $("status").textContent = "clipboard unavailable"; } return; }
    const ut = e.target.closest("[data-usage-tab]"); if (ut) { state.usageTab = ut.dataset.usageTab; render(); return; }
    const ht = e.target.closest("[data-hist]"); if (ht) { state.histTab = ht.dataset.hist; await refresh(); return; }
    if (e.target.closest("#hist-toggle")) { state.histOpen = !state.histOpen; render(); return; }
    const hx = e.target.closest("[data-hide]"); if (hx) { e.stopPropagation(); const r = await api("/api/thread-hide", { convoy_id: hx.dataset.hide, hidden: true }); $("status").textContent = r.ok ? (r.thread || "thread") + " archived off the strip (kept on disk; open the +N chip to restore)" : "refused: " + (r.error || ""); await refresh(true); return; }
    const uh = e.target.closest("[data-unhide]"); if (uh) { e.stopPropagation(); const r = await api("/api/thread-hide", { convoy_id: uh.dataset.unhide, hidden: false }); $("status").textContent = r.ok ? (r.thread || "thread") + " restored" : "refused: " + (r.error || ""); await refresh(true); return; }
    const th = e.target.closest("[data-toggle-hidden]"); if (th) { state.showHiddenThreads = !state.showHiddenThreads; renderHeader(); return; }
    const dot = e.target.closest(".dot"); if (dot && dot.dataset.n) { state.selected = +dot.dataset.n; state.selectedSeat = null; chat.draft = ""; await refresh(); return; }
    const nd = e.target.closest("[data-nudge]"); if (nd) { e.stopPropagation(); await nudgeDry(nd.dataset.nudge); return; }
    const ax = e.target.closest("[data-archive]"); if (ax) { e.stopPropagation(); const t = thread(); const c = (t.chairs || []).find((x) => x.session_id === ax.dataset.archive); if (c) { c.archived = true; } if (state.selectedSeat === ax.dataset.archive) state.selectedSeat = null; render();
      const r = await api("/api/archive", { root: t.root, seat: ax.dataset.archive, archived: true }); $("status").textContent = r.ok ? ax.dataset.archive + " archived (kept on the thread; show archived to relaunch)" : "refused: " + (r.error || ""); if (!r.ok && c) { c.archived = false; render(); } await refresh(true); return; }
    const ux = e.target.closest("[data-unarchive]"); if (ux) { e.stopPropagation(); const t = thread(); const c = (t.chairs || []).find((x) => x.session_id === ux.dataset.unarchive); if (c) { c.archived = false; render(); }
      const r = await api("/api/archive", { root: t.root, seat: ux.dataset.unarchive, archived: false }); $("status").textContent = r.ok ? ux.dataset.unarchive + " unarchived" : "refused: " + (r.error || ""); await refresh(true); return; }
    const rl = e.target.closest("[data-relaunch]"); if (rl) { e.stopPropagation(); const t = thread(); $("status").textContent = "relaunching " + rl.dataset.relaunch + "…"; const r = await api("/api/relaunch", { root: t.root, seat: rl.dataset.relaunch }); $("status").textContent = r.ok ? rl.dataset.relaunch + (r.launched ? " relaunched: pending until it acks" : " chair written; window did not launch: " + (r.error || "")) : "refused: " + (r.error || ""); await refresh(); return; }
    if (e.target.id === "toggle-archived") { state.showArchived = !state.showArchived; render(); return; }
    if (e.target.closest("details.disc") || e.target.closest(".act") || e.target.closest("select") || e.target.closest("input")) return;
    const row = e.target.closest("tr.row"); if (row) {
      state.selectedSeat = state.selectedSeat === row.dataset.seat ? null : row.dataset.seat; chat.draft = state.selectedSeat ? "@" + state.selectedSeat + " " : ""; render();
      if (!state.selectedSeat) { $("status").textContent = ""; return; }
      const t = thread(); const r = await api("/api/focus", { root: t.root, seat: row.dataset.seat });
      $("status").textContent = r.focused ? "raised the pane of " + row.dataset.seat : (row.dataset.seat + " selected · pane focus: " + (r.reason || (r.identify && r.identify.reason) || "not available on this host"));
      return; }
    if (e.target.closest("#pin")) { state.pinned = !state.pinned; const r = await api("/api/pin", { on: state.pinned }); state.pinned = !!r.on; render(); return; }
    if (e.target.closest("#plus")) { await openStart(); return; }
    if (e.target.id === "start-cancel") { $("start").classList.remove("show"); return; }
    if (e.target.id === "start-go") { await submitStart(); return; }
    const pick = e.target.closest("[data-pick]"); if (pick) { $("s-repo").value = pick.dataset.pick; if (pick.dataset.thread) $("s-thread").value = pick.dataset.thread; return; }
    if (e.target.id === "s-add") { addSeatRow(); return; }
    const rm = e.target.closest("[data-rm]"); if (rm) { rm.closest(".seat-row").remove(); return; }
    const g = e.target.closest("[data-gh]"); if (g) { g.parentElement.querySelectorAll("span").forEach((x) => x.classList.remove("on")); g.classList.add("on"); return; }
    if (e.target.closest("#tag")) { e.preventDefault(); await api("/api/open", { url: "https://convoy.bot" }); return; }
  });

  // ---------- the "+" flow: GitHub? -> repo -> harnesses -> N seats -> launch (original spec) ----------
  let cardCache = null;
  async function openStart() {
    const box = $("start"); box.classList.add("show");
    box.innerHTML = `<div class="eyebrow"><span>New thread</span><span class="right">reading the card…</span></div>`;
    cardCache = await api("/api/card", {});
    const rows = (cardCache.rows || []); const recent = (cardCache.recent || []); const installed = rows.filter((r) => r.installed);
    const harnessOpts = rows.map((r) => `<label class="hx ${r.installed ? "" : "off"}" title="${esc(r.install && r.install.page ? r.install.page : "")}"><input type="checkbox" value="${esc(r.harness)}" ${r.installed ? "" : "disabled"}> ${mark(r.harness)}${esc(r.harness)} <small>${r.installed ? (r.where || []).join("/") : "not installed"}</small></label>`).join("");
    box.innerHTML = `
      <div class="eyebrow"><span>New thread</span><span class="right">${installed.length} harness${installed.length === 1 ? "" : "es"} installed</span></div>
      <div class="frow"><span class="lbl">GitHub?</span><span class="seg" id="s-gh"><span class="on" data-gh="yes">yes</span><span data-gh="no">no</span></span></div>
      <div class="frow"><span class="lbl">repo</span><input id="s-repo" class="in" placeholder="https://github.com/owner/repo.git or a local path"></div>
      ${recent.length ? `<div class="frow"><span class="lbl">recent</span><div class="picks">${recent.map((r) => `<span class="pick" data-pick="${esc(r.root)}" data-thread="${esc(r.thread || "")}" title="${esc(r.root)}">${esc(r.thread || r.convoy_id || r.root)}</span>`).join("")}</div></div>` : ""}
      <div class="frow"><span class="lbl">thread</span><input id="s-thread" class="in" placeholder="thread key (e.g. demo)"></div>
      <div class="frow"><span class="lbl">harnesses</span><div class="hxs">${harnessOpts || "<small>none installed on this host</small>"}</div></div>
      <div class="frow"><span class="lbl">neurons</span><div id="s-seats" class="seats"></div></div>
      <div class="frow"><span class="lbl"></span><span class="pick" id="s-add">+ seat</span></div>
      <div class="btns"><span id="start-cancel">cancel</span><span class="go" id="start-go">launch</span></div>
      <div class="meta" id="s-out"></div>`;
    addSeatRow();
  }
  function seatRowHtml() {
    const rows = (cardCache && cardCache.rows) || [];
    const opts = rows.filter((x) => x.installed).map((x) => `<option value="${esc(x.harness)}">${esc(x.harness)}</option>`).join("");
    return `<div class="seat-row"><select class="in sel-h">${opts}</select><input class="in sel-t" placeholder="title (unique)"><input class="in sel-m" placeholder="model"><select class="in sel-e"><option value="">effort</option></select><select class="in sel-w"><option value="local">local</option></select><span class="pick" data-rm="1">×</span></div>`;
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
    const title = () => { const h = row.querySelector(".sel-h").value; const taken = new Set(((thread() || {}).chairs || []).map((c) => c.seat_label || c.session_id)); let n = 1; while (taken.has(h + "-" + n) || [...document.querySelectorAll("#s-seats .sel-t")].some((i) => i !== row.querySelector(".sel-t") && i.value === h + "-" + n)) n++; row.querySelector(".sel-t").value = h + "-" + n; };
    row.querySelector(".sel-h").addEventListener("change", () => { sync(); title(); }); sync(); title();
  }
  async function submitStart() {
    const gh = $("s-gh").querySelector(".on").dataset.gh === "yes";
    const seats = [...document.querySelectorAll("#s-seats .seat-row")].map((r) => ({ harness: r.querySelector(".sel-h").value, title: r.querySelector(".sel-t").value || null, model: r.querySelector(".sel-m").value || null, effort: r.querySelector(".sel-e").value || null, where: r.querySelector(".sel-w").value || "local" }));
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
