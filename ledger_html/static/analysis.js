"use strict";
// The Analysis tab: what each scheduled bill really cost each pay period, how it is trending, and which ones moved.
// Top: the biggest movers (a diverging bar per bill). Below: pick a bill (or all of them) and read its trend in one large chart.
const AN = {A: null, sel: "__all", loaded: false, from: "", to: "", q: "", sort: "name", show: "all", view: "pp"};
const anPct = p => p == null ? "—" : (p > 0 ? "+" : "") + (Math.abs(p) >= 100 ? Math.round(p) : p.toFixed(1)) + "%";
const anShort = l => String(l).replace(/,\s*\d{4}$/, "").replace(/\s*[–—-].*$/, "");  // "Nov 06 – Nov 19, 2026" -> "Nov 06"

async function loadAnalysis(keepFocus) {
  if (!AN.loaded) $("an").innerHTML = `<div class="card"><p class="hint" role="status">Loading analysis…</p></div>`;
  try {
    const qs = new URLSearchParams(); if (AN.from) qs.set("from", AN.from); if (AN.to) qs.set("to", AN.to);
    AN.A = await api("/api/analysis" + (qs.toString() ? "?" + qs : "")); AN.loaded = true; renderAnalysis();
  } catch (e) { fail(e); if (!AN.loaded) $("an").innerHTML = `<div class="card"><p class="hint" role="alert">The analysis didn't load: ${esc(e.message || e)}</p></div>`; }
}

// a bill's series as {label, paid, planned, missed, ...}; "All bills" adds up what was paid across every bill
function anSeries(key) {
  const A = AN.A;
  if (key === "__all") {
    const rows = AN.shown || A.bills, byP = Object.fromEntries(A.periods.map(p => [p.period, {paid: 0, planned: 0, any: false}]));
    rows.forEach(b => b.series.forEach(x => { const t = byP[x.period]; if (!t) return; t.planned += x.planned || 0; if (x.paid != null) { t.paid += x.paid; t.any = true; } }));
    return {name: groupName(), group: rows, series: A.periods.map(p => ({label: p.label, period: p.period, paid: byP[p.period].any ? byP[p.period].paid : null, planned: byP[p.period].planned || null, missed: false}))};
  }
  const b = A.bills.find(x => x.name === key) || A.bills[0];
  return b ? {name: b.name, series: b.series, bill: b} : {name: "", series: []};
}

// what the "All bills" chart is adding up: the bills the list is showing, named after the filter
function groupName() {
  const n = (AN.shown || AN.A.bills).length, q = AN.q.trim();
  const base = {all: "All scheduled bills", reg: "Regular bills", card: "Cards & loans", more: "Bills costing more", less: "Bills costing less", same: "Bills with no change"}[AN.show];
  return `${base}${q ? ` matching “${q}”` : ""}${AN.show === "all" && !q ? "" : ` (${n})`}`;
}

function sparkSvg(vals, color) {
  const v = vals.filter(x => x != null);
  if (v.length < 2) return `<svg class="spk" viewBox="0 0 60 22"></svg>`;
  const lo = Math.min(...v), hi = Math.max(...v), rg = hi - lo || 1;
  const pts = vals.map((x, i) => x == null ? null : [2 + i * 56 / (vals.length - 1), 20 - (x - lo) / rg * 17]).filter(Boolean);
  return `<svg class="spk" viewBox="0 0 60 22"><polyline points="${pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ")}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2.4" fill="${color}"/></svg>`;
}
const anColor = d => d === "up" ? "var(--red)" : d === "down" ? "var(--green)" : "var(--ac)";  // a bill costing more is the bad direction

// The three panels above the chart (summary tiles, biggest movers, cards & loans). They follow the bill list's filter:
// only the bills the list is showing count, and the cards panel disappears when the filter leaves no cards in it.
function panelsHtml() {
  const A = AN.A, shownB = AN.shown || A.bills, ok = new Set(shownB.map(b => b.name)), filtered = shownB.length !== A.bills.length;
  const al = A.alerts.filter(a => ok.has(a.name));
  const up = al.filter(a => a.kind === "up" || a.kind === "creep"), down = al.filter(a => a.kind === "down" || a.kind === "slide"), missed = al.filter(a => a.kind === "missed");
  const totalPaid = anSeries("__all").series.reduce((t, p) => t + (p.paid || 0), 0);
  const kpi = (l, v, sub, c) => `<div class="kp"><div class="kpl">${l}</div><div class="kpv"${c ? ` style="color:${c}"` : ""}>${v}</div><div class="kps">${sub}</div></div>`;
  const maxAmt = Math.max(1, ...A.alerts.filter(a => ok.has(a.name)).map(a => Math.abs(a.amt || 0)));
  const moverRow = a => {
    const bad = a.kind === "up" || a.kind === "creep" || a.kind === "missed", col = bad ? "var(--red)" : "var(--green)";
    const sub = a.kind === "missed" ? `Planned ${money(a.baseline)}, no payment found`
      : a.kind === "creep" ? "Creeping up over the period" : a.kind === "slide" ? "Sliding down over the period"
      : `${money(a.latest)} vs ${money(a.baseline)} usual`;
    const w = a.amt == null ? 10 : Math.max(6, Math.abs(a.amt) / maxAmt * 100);
    return `<button class="mv" type="button" data-b="${esc(a.name)}"><span class="mvn">${esc(a.name)}<small>${esc(sub)}</small></span><span class="mvb"><i style="width:${w}%;background:${col}"></i></span><span class="mvp" style="color:${col}">${a.kind === "missed" ? "Missed" : a.amt != null ? (a.amt > 0 ? "+" : "−") + money(Math.abs(a.amt), 0) : anPct(a.pct)}<small>${a.kind === "missed" || a.amt == null ? "" : anPct(a.pct)}</small></span></button>`;
  };
  const col = (title, tone, rows, empty) => `<div class="mcol"><div class="mct" style="color:${tone}">${title} <b>${rows.length}</b></div>${rows.length ? rows.slice(0, 5).map(moverRow).join("") : `<p class="hint">${empty}</p>`}</div>`;
  const cd = (AN.shown || A.bills).filter(b => b.card && b.latest != null);
  const maxOver = Math.max(1, ...cd.map(b => Math.max(b.over_latest || 0, 0)));
  const cardsPanel = `<div class="card"><h2 class="lab">Cards &amp; loans ${hp("These are judged against their minimum payment (the amount planned for them), because what you pay swings with how much extra you put on. The bar is how far over the minimum the latest payment was.")}
      <button type="button" class="b anmark" id="an_mark">Choose cards &amp; loans…</button></h2>
    ${cd.length ? `<div class="cdl">${cd.map(b => `<button class="mv cdr" type="button" data-b="${esc(b.name)}"><span class="mvn">${esc(b.name)}<small>${money(b.latest)} paid · ${money(b.minimum)} minimum</small></span><span class="mvb"><i style="width:${Math.max(b.over_latest > 0.5 ? 6 : 0, Math.max(b.over_latest, 0) / maxOver * 100)}%;background:var(--ac)"></i></span><span class="mvp" style="color:${b.over_latest > 0.5 ? "var(--ac)" : "var(--mu)"}">${b.over_latest > 0.5 ? "+" + money(b.over_latest, 0) : "Minimum"}<small>${b.at_min} of ${b.n_paid} at min</small></span></button>`).join("")}</div>`
      : `<p class="hint">No cards or loans are marked yet. Choose them and they get tracked against their minimum, so paying a little extra doesn't show up as a bill going up or down.</p>`}</div>`;
  const tag = filtered ? ` <span class="ancnt">· ${esc(groupName())}</span>` : "";
  const anyCard = A.bills.some(b => b.card);
  return `<div class="kps4">${kpi("Paid on bills", money(totalPaid, 0), `across ${A.periods.length ? "completed pay periods" : "this range"}`)}${kpi("Costing more", up.length, up.length === 1 ? "bill" : "bills", up.length ? "var(--red)" : "")}${kpi("Costing less", down.length, down.length === 1 ? "bill" : "bills", down.length ? "var(--green)" : "")}${kpi("Missed", missed.length, missed.length === 1 ? "payment" : "payments", missed.length ? "var(--red)" : "")}</div>
    <div class="card"><h2 class="lab">Biggest movers${tag} ${hp("Each scheduled bill's latest payment compared with its usual amount (the middle of the three payments before it). Red means it cost more. Click one to open its chart.")}</h2>
      <div class="mgrid">${col("Costing more", "var(--red)", up.concat(missed), "Nothing is costing more.")}${col("Costing less", "var(--green)", down, "Nothing is costing less.")}</div></div>
    ${cd.length || (!anyCard && (AN.show === "all" || AN.show === "card")) ? cardsPanel.replace("Cards &amp; loans ", `Cards &amp; loans${tag} `) : ""}`;
}

function wirePanels() {
  document.querySelectorAll("#an_panels [data-b]").forEach(el => el.onclick = () => { AN.sel = el.dataset.b; renderList(); drawBill(); $("an_main").scrollIntoView({block: "nearest", behavior: "smooth"}); });
  if ($("an_mark")) $("an_mark").onclick = markCards;
}

function refreshPanels() { $("an_panels").innerHTML = panelsHtml(); wirePanels(); }


function renderAnalysis() {
  const A = AN.A, all = A.span.all;
  if (!A.span.first) { $("an").innerHTML = `<div class="card"><p class="hint">Import some bank transactions first. The analysis reads what each scheduled bill really cost in each pay period.</p></div>`; return; }
  if (AN.sel !== "__all" && !A.bills.some(b => b.name === AN.sel)) AN.sel = "__all";
  const lo = AN.from || all[0].period, hi = AN.to || A.span.last;
  const chip = (label, n) => `<button type="button" class="chp${!AN.to && (n ? AN.from === all[all.length - n].period : !AN.from) ? " on" : ""}" data-n="${n}">${label}</button>`;
  const shown = A.periods.length;
  $("an").innerHTML = `<div class="stack">
    <div class="anhead"><div><h2 class="anh">Bill trends</h2><div class="ansub">${shown ? `${shown} pay period${shown === 1 ? "" : "s"} · ${esc(anShort(A.periods[0].label))} to ${esc(anShort(A.periods[shown - 1].label))}` : "No pay periods in this range"}</div></div>
      <div class="anctl"><div class="chps" role="group" aria-label="Quick ranges">${chip("All data", 0)}${all.length > 3 ? chip("Last 3", 3) : ""}${all.length > 6 ? chip("Last 6", 6) : ""}</div>
        <label class="fld"><span class="ft">From</span><input type="date" id="an_from" value="${lo}" min="${all[0].period}" max="${hi}"></label>
        <label class="fld"><span class="ft">To</span><input type="date" id="an_to" value="${hi}" min="${lo}" max="${A.span.last}"></label></div></div>
    <div class="anwrap"><div class="card anlist"><h2 class="lab">Scheduled bills <span id="an_cnt" class="ancnt"></span></h2>
        <div class="anfl"><input type="search" id="an_q" placeholder="Filter bills…" aria-label="Filter bills by name" value="${esc(AN.q)}">
          <div class="anfr"><select id="an_show" aria-label="Show">${[["all", "All bills"], ["reg", "Regular bills"], ["card", "Cards & loans"], ["more", "Costing more"], ["less", "Costing less"], ["same", "No change"]].map(([v, l]) => `<option value="${v}"${AN.show === v ? " selected" : ""}>${l}</option>`).join("")}</select>
          <select id="an_sort" aria-label="Sort by">${[["name", "Sort: Name A–Z"], ["latest", "Sort: Latest amount"], ["pct", "Sort: Change %"], ["amt", "Sort: Change $"], ["more", "Sort: Costing more first"]].map(([v, l]) => `<option value="${v}"${AN.sort === v ? " selected" : ""}>${l}</option>`).join("")}</select></div></div>
        <div id="an_list"></div></div>
      <div class="anright">
    <div id="an_panels" class="anpan"></div>
        <div class="card" id="an_main"></div></div></div></div>`;
  renderList();
  refreshPanels();
  document.querySelectorAll("#an .chp").forEach(el => el.onclick = () => { const n = +el.dataset.n; AN.to = ""; AN.from = n && all.length > n ? all[all.length - n].period : ""; loadAnalysis(); });
  const dateChanged = () => { const f = $("an_from").value, t = $("an_to").value; AN.from = f && f > all[0].period ? f : ""; AN.to = t && t < A.span.last ? t : ""; if (f && t && f > t) { toast("The From date has to be before the To date."); return; } loadAnalysis(); };
  $("an_from").onchange = $("an_to").onchange = dateChanged;
  $("an_q").oninput = () => { AN.q = $("an_q").value; AN.sel = "__all"; renderList(); refreshPanels(); drawBill(); };
  $("an_show").onchange = () => { AN.show = $("an_show").value; AN.sel = "__all"; renderList(); refreshPanels(); drawBill(); };
  $("an_sort").onchange = () => { AN.sort = $("an_sort").value; renderList(); };
  if (A.periods.length) drawBill(); else $("an_main").innerHTML = `<p class="hint">No pay periods fall in this date range. Widen it, or choose All data.</p>`;
}


// the bill list, narrowed by the filter box and the Show menu, and ordered by the Sort menu ("All bills" always stays on top)
function renderList() {
  const A = AN.A, q = AN.q.trim().toLowerCase();
  let rows = A.bills.filter(b => (!q || b.name.toLowerCase().includes(q)) && (AN.show === "all" || (AN.show === "reg" ? !b.card : AN.show === "card" ? b.card : b.card ? false : AN.show === "more" ? b.dir === "up" : AN.show === "less" ? b.dir === "down" : b.dir === "steady")));
  const num = (v, d) => v == null ? d : v;
  const byMap = {name: (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: "base"}), latest: (a, b) => num(b.latest, -1) - num(a.latest, -1),
    pct: (a, b) => Math.abs(num(b.change_pct, 0)) - Math.abs(num(a.change_pct, 0)), amt: (a, b) => Math.abs(num(b.change_amt, 0)) - Math.abs(num(a.change_amt, 0)),
    more: (a, b) => num(b.change_amt, 0) - num(a.change_amt, 0)}, by = byMap[AN.sort];
  const cardKey = {latest: (a, b) => num(b.latest, -1) - num(a.latest, -1), pct: (a, b) => num(b.over_latest, 0) - num(a.over_latest, 0), amt: (a, b) => num(b.over_latest, 0) - num(a.over_latest, 0), more: (a, b) => num(b.over_latest, 0) - num(a.over_latest, 0), name: byMap.name}[AN.sort];
  AN.shown = rows;
  const regs = rows.filter(b => !b.card).sort(by), cds = rows.filter(b => b.card).sort(cardKey);
  const item = (k, n, b) => {
    const ser = k === "__all" ? anSeries("__all").series.map(x => x.paid) : b.series.map(x => x.paid);
    const d = b ? b.dir : "steady", pct = b ? b.change_pct : null;
    const tail = b && b.card ? (b.over_latest > 0.5 ? `<span class="alp" style="color:var(--ac)">+${money(b.over_latest, 0)} over</span>` : `<span class="alp" style="color:var(--mu)">minimum</span>`)
      : `<span class="alp" style="color:${anColor(d)}">${pct == null ? "" : (pct > 0 ? "▲" : pct < 0 ? "▼" : "") + " " + anPct(pct)}</span>`;
    return `<button type="button" class="ali${k === AN.sel ? " on" : ""}" data-b="${esc(k)}" title="${esc(n)}"><span class="aln">${esc(n)}</span>${sparkSvg(ser, anColor(d))}<span class="alv">${b && b.latest != null ? money(b.latest, 0) : k === "__all" ? (() => { const v = anSeries("__all").series.map(x => x.paid).filter(x => x != null); return v.length ? money(v[v.length - 1], 0) : "—"; })() : "—"}</span>${tail}</button>`;
  };
  const head = t => `<div class="algh">${t}</div>`;
  $("an_list").innerHTML = item("__all", AN.show === "all" && !AN.q.trim() ? "All bills" : "Shown bills", null) + (regs.length && cds.length ? head("Bills") : "") + regs.map(b => item(b.name, b.name, b)).join("")
    + (cds.length ? head("Cards &amp; loans <small>vs minimum</small>") + cds.map(b => item(b.name, b.name, b)).join("") : "") + (rows.length ? "" : `<p class="hint" style="margin:10px 8px">No bills match.</p>`);
  $("an_cnt").textContent = rows.length === A.bills.length ? `${A.bills.length}` : `${rows.length} of ${A.bills.length}`;
  $("an_list").querySelectorAll("[data-b]").forEach(el => el.onclick = () => { AN.sel = el.dataset.b; renderList(); if (A.periods.length) drawBill(); $("an_main").scrollIntoView({block: "nearest", behavior: "smooth"}); });
}

// a checklist of every scheduled bill: tick the credit cards and loans. Saved to your settings (card_bills).
function markCards() {
  const all = AN.A.all_bills, dlg = document.createElement("dialog");
  dlg.innerHTML = `<h3 style="margin:0 0 6px">Cards &amp; loans</h3><p class="hint" style="margin:0 0 10px">Tick the bills whose payment changes with how much extra you put on them. They are tracked against their minimum, the amount planned for them.</p>
    <div class="anchk">${all.map((b, i) => `<label class="tog"><input type="checkbox" data-n="${esc(b.name)}"${b.card ? " checked" : ""}> ${esc(b.name)}</label>`).join("")}</div>
    <div class="dbtn"><button type="button" class="b" id="mk_x">Cancel</button><button type="button" class="b" id="mk_ok">Save</button></div>`;
  document.body.appendChild(dlg); dlg.showModal();
  dlg.onclose = () => dlg.remove();
  dlg.querySelector("#mk_x").onclick = () => dlg.close();
  dlg.querySelector("#mk_ok").onclick = () => api("/api/settings", {set: {card_bills: [...dlg.querySelectorAll("input:checked")].map(x => x.dataset.n)}})
    .then(() => { dlg.close(); toast("Saved."); return loadAnalysis(); }).catch(fail);
}

// The chart: spending by calendar month (a month only counts toward the stats once the transactions cover all of it).
function anMonthly(key) {
  const A = AN.A, ms = A.months;
  if (key === "__all") {
    const rows = AN.shown || A.bills;
    return {name: groupName(), group: rows, months: ms.map((m, i) => ({...m, paid: rows.reduce((t, b) => t + (b.monthly[i]?.paid || 0), 0), planned: rows.reduce((t, b) => t + (b.monthly[i]?.planned || 0), 0) || null}))};
  }
  const b = A.bills.find(x => x.name === key) || A.bills[0];
  return b ? {name: b.name, bill: b, group: [b], months: ms.map((m, i) => ({...m, paid: b.monthly[i]?.paid || 0, planned: b.monthly[i]?.planned ?? null}))} : {name: "", group: [], months: []};
}

function drawBill() {
  const {name, months, bill, group} = anMonthly(AN.sel), host = $("an_main");
  const full = months.filter(m => m.full), mean = v => v.reduce((x, y) => x + y, 0) / v.length;
  const isCard = group.length > 0 && group.every(b => b.card), host2 = isCard ? "Minimum" : "Planned";
  const stat = (l, v, sub, c) => `<div class="st"><div class="stl">${l}</div><div class="stv"${c ? ` style="color:${c}"` : ""}>${v}</div>${sub ? `<div class="sts">${sub}</div>` : ""}</div>`;
  const mName = m => m.label.replace(/\s\d{4}$/, "");
  let head = "";
  if (full.length) {
    const last = full[full.length - 1], prev = full[full.length - 2], avg = mean(full.map(m => m.paid));
    head = stat("Latest full month", money(last.paid, 0), esc(last.label)) + stat("Average per month", money(avg, 0), `${full.length} full month${full.length === 1 ? "" : "s"}${group.length > 1 ? ` · ${group.length} bills` : ""}`);
    if (prev) { const d = last.paid - prev.paid, c = isCard ? "var(--ac)" : d > 0 ? "var(--red)" : d < 0 ? "var(--green)" : ""; head += stat("Change vs previous month", `${d > 0 ? "▲ " : d < 0 ? "▼ " : ""}${d >= 0 ? "+" : "−"}${money(Math.abs(d), 0)}`, `${money(prev.paid, 0)} → ${money(last.paid, 0)}${prev.paid ? ` · ${anPct(d / prev.paid * 100)}` : ""}<br>${esc(mName(prev))} to ${esc(mName(last))}`, c); }
    if (full.length >= 2) head += stat("Lowest · Highest month", `${money(Math.min(...full.map(m => m.paid)), 0)} · ${money(Math.max(...full.map(m => m.paid)), 0)}`, "full months only");
    if (isCard && last.planned) head += stat("Minimums", money(last.planned, 0), esc(last.label)) + stat("Over the minimums", last.paid - last.planned > 0.5 ? "+" + money(last.paid - last.planned, 0) : "None", esc(last.label), "var(--ac)");
  } else head = `<p class="hint" style="grid-column:1/-1;margin:0">No full month of data yet, so the averages wait. The bars below still show what was paid so far.</p>`;
  const tog = "";
  host.innerHTML = `<h2 class="lab">${esc(name)} ${hp(`Each bar is a calendar month of what was actually paid. A striped bar is a month the transactions don't cover all of yet, so it is left out of the averages. The dash marks what the plan expected${isCard ? " (for a card or loan, its minimum)" : ""}. A red cross is a month where a payment was expected but none was found.`)}</h2>
    <div class="sts-row">${head}</div><div id="an_chart" class="anchart"></div>
    <div class="anleg"><span><i style="background:var(--ac)"></i>Paid</span><span><i class="hat"></i>Month not complete</span><span><i class="mk"></i>${host2}</span><span><i class="x">✕</i>Missed</span></div>
    <div class="antbl"><table><thead><tr><th>Month</th><th>${host2}</th><th>Paid</th><th>${isCard ? "Over minimum" : "vs plan"}</th></tr></thead><tbody>${months.slice().reverse().map(m => { const d = m.planned != null ? m.paid - m.planned : null; return `<tr><td>${esc(m.label)}${m.full ? "" : ` <span class="mu">· so far</span>`}</td><td>${m.planned != null ? money(m.planned) : "—"}</td><td>${m.paid ? money(m.paid) : m.full && m.planned ? `<b style="color:var(--red)">Missed</b>` : "—"}</td><td>${d == null || !m.paid ? "" : `<span style="color:${isCard ? "var(--ac)" : d > 0.5 ? "var(--red)" : d < -0.5 ? "var(--green)" : "var(--mu)"}">${Math.abs(d) < 0.5 ? "on plan" : (d > 0 ? "+" : "−") + money(Math.abs(d))}</span>`}</td></tr>`; }).join("")}</tbody></table></div>`;
  drawMonths(months, isCard);
}

function drawMonths(months, isCard) {
  const el = $("an_chart"); if (!el) return;
  const n = months.length, W = Math.max(el.clientWidth, 320), H = 320, L = 58, R = 22, T = 26, B = 42;
  const hi = Math.max(1, ...months.map(m => Math.max(m.paid, m.planned || 0))) * 1.14;
  if (!n || !months.some(m => m.paid)) { el.innerHTML = `<p class="hint">No payments found yet.</p>`; return; }
  const slot = (W - L - R) / n, bw = Math.min(slot * 0.62, 120), x = i => L + slot * i + slot / 2, y = v => T + (1 - v / hi) * (H - T - B);
  const nice = (() => { const raw = hi / 4, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; })();
  let g = "";
  for (let v = 0; v <= hi; v += nice) g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1" opacity=".7"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" fill="var(--mu)" font-size="11">${money(v, 0)}</text>`;
  const col = "var(--ac)", yrs = new Set(months.map(m => m.key.slice(0, 4))).size > 1;
  const bars = months.map((m, i) => {
    const h = Math.max(0, y(0) - y(m.paid)), top = y(m.paid);
    const bar = m.paid ? `<rect x="${x(i) - bw / 2}" y="${top}" width="${bw}" height="${h}" rx="5" fill="${m.full ? col : "url(#an_hat)"}" stroke="${col}" stroke-width="${m.full ? 0 : 1.6}" opacity="${m.full ? 0.9 : 1}"/><text x="${x(i)}" y="${top - 8}" text-anchor="middle" fill="var(--tx)" font-size="12.5" font-weight="700">${money(m.paid, 0)}</text>`
      : m.full && m.planned ? `<text x="${x(i)}" y="${y(0) - 8}" text-anchor="middle" fill="var(--red)" font-size="20" font-weight="700">✕</text>` : "";
    const mk = m.planned ? `<line x1="${x(i) - bw / 2 - 8}" x2="${x(i) + bw / 2 + 8}" y1="${y(m.planned)}" y2="${y(m.planned)}" stroke="var(--tx)" stroke-width="2.6" stroke-dasharray="7 4" stroke-linecap="round"/>` : "";
    const lab = `<text x="${x(i)}" y="${H - B + 20}" text-anchor="middle" fill="var(--mu)" font-size="12">${esc(yrs ? m.label : m.label.replace(/\s\d{4}$/, ""))}${m.full ? "" : " (so far)"}</text>`;
    return bar + mk + lab;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Amount paid each calendar month"><defs><pattern id="an_hat" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="color-mix(in srgb,var(--ac) 14%,transparent)"/><rect width="3" height="8" fill="color-mix(in srgb,var(--ac) 55%,transparent)"/></pattern></defs>${g}${bars}<g id="an_hits">${months.map((m, i) => `<rect class="anh" data-i="${i}" x="${L + slot * i}" y="${T}" width="${slot}" height="${H - T - B}" fill="transparent"/>`).join("")}</g></svg><div id="an_tt" class="antt hide"></div>`;
  const tt = $("an_tt");
  el.querySelectorAll(".anh").forEach(r => {
    r.onmousemove = ev => { const m = months[+r.dataset.i], i = +r.dataset.i, d = m.planned != null && m.paid ? m.paid - m.planned : null;
      tt.innerHTML = `<b>${esc(m.label)}${m.full ? "" : " · so far"}</b><br>Paid: ${m.paid ? money(m.paid) : m.full && m.planned ? "<span style='color:var(--red)'>missed</span>" : "—"}${m.planned != null ? `<br>${isCard ? "Minimum" : "Planned"}: ${money(m.planned)}` : ""}${d != null && Math.abs(d) >= 0.5 ? `<br>${d > 0 ? "+" : "−"}${money(Math.abs(d))} ${isCard ? "over minimum" : "vs plan"}` : ""}`;
      tt.classList.remove("hide"); tt.style.left = Math.min(Math.max(x(i) - 83, 4), W - 170) + "px"; tt.style.top = Math.max(y(m.paid) - 96, 0) + "px"; };
    r.onmouseleave = () => tt.classList.add("hide");
  });
}
{ let rt; new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (AN.loaded && !$("an").classList.contains("hide")) drawBill(); }, 120); }).observe(document.body); }
