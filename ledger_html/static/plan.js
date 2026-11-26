"use strict";
// The Plan tab: income, recurring bills, extras, rules, budgets, rename. Loaded after app.js.
const PLAN = {data: null, loaded: false};

// an editable table: inputs in every cell, "+ Add a row", delete buttons, and a Save that turns solid when something changed
function grid(host, cfg) {
  const orig = JSON.stringify(cfg.rows); let rows = cfg.rows.map(r => ({...r}));
  host.innerHTML = `${cfg.noAdd ? "" : `<div class="edbar" style="margin:0 0 8px"><button class="b" data-add>+ Add a row</button></div>`}<div class="scroll"><table class="ed"></table></div><div class="edbar"><button class="b" data-save>${cfg.saveLabel}</button><span class="dirty hide">Unsaved changes</span></div>`;
  const tbl = host.querySelector("table"), save = host.querySelector("[data-save]"), dirty = host.querySelector(".dirty");
  const upd = () => { const d = JSON.stringify(rows) !== orig; save.classList.toggle("pri", d); dirty.classList.toggle("hide", !d); };
  const draw = () => {
    tbl.innerHTML = `<tr>${cfg.cols.map(c => `<th class="${c.type === "text" || c.ro ? "l" : ""}">${c.label}</th>`).join("")}${cfg.reorder ? `<th class="x">Order</th>` : ""}${cfg.noDelete ? "" : `<th class="x">Remove</th>`}</tr>`
      + rows.map((r, i) => `<tr class="${r._rm ? "rm" : ""}">${cfg.cols.map(c => {
        const v = r[c.k]; if (c.ro) return `<td class="ro ${c.type === "number" ? "" : "l"}">${c.fmt ? c.fmt(v, r) : esc(v ?? "")}</td>`;
        if (c.type === "select") return `<td><select data-i="${i}" data-k="${c.k}"${c.on && !c.on(r) ? " disabled" : ""}>${c.opts.map(o => `<option value="${esc(o[0])}"${String(o[0]) === String(v) ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select></td>`;
        if (c.type === "check") return `<td style="text-align:center"><input type="checkbox" data-i="${i}" data-k="${c.k}" ${v ? "checked" : ""}></td>`;
        return `<td><input type="${c.type}" ${c.type === "number" ? `step="${c.step || "0.01"}" ${c.min != null ? `min="${c.min}"` : ""} ${c.max != null ? `max="${c.max}"` : ""}` : ""} data-i="${i}" data-k="${c.k}" value="${esc(v ?? "")}" ${c.ph ? `placeholder="${c.ph}"` : ""} ${c.list ? `list="${c.list}"` : ""}></td>`; }).join("")}`
        + (cfg.reorder ? `<td class="x"><button class="b ic" data-up="${i}" title="Move up">↑</button><button class="b ic" data-dn="${i}" title="Move down">↓</button></td>` : "")
        + (cfg.noDelete ? "" : `<td class="x"><input type="checkbox" data-rm="${i}" ${r._rm ? "checked" : ""} title="Tick to remove this row when you save"></td>`) + `</tr>`).join("");
    tbl.querySelectorAll("[data-k]").forEach(el => el.oninput = el.onchange = () => {
      const c = cfg.cols.find(x => x.k === el.dataset.k), i = +el.dataset.i;
      rows[i][c.k] = c.type === "check" ? el.checked : c.type === "number" ? (el.value === "" ? null : +el.value) : c.type === "select" && c.num ? +el.value : el.value;
      // a column with `on` is only editable while its row says so (Month: only for Quarterly and Yearly); when it switches off it clears
      cfg.cols.filter(x => x.on).forEach(x => { const sel = el.closest("tr").querySelector(`[data-k="${x.k}"]`), allowed = x.on(rows[i]);
        if (sel) { sel.disabled = !allowed; if (!allowed && rows[i][x.k]) { rows[i][x.k] = 0; sel.value = "0"; } } });
      upd(); cfg.onEdit && cfg.onEdit(rows); });
    tbl.querySelectorAll("[data-rm]").forEach(c => c.onchange = () => { const i = +c.dataset.rm; if (c.checked) rows[i]._rm = true; else delete rows[i]._rm; c.closest("tr").classList.toggle("rm", c.checked); upd(); });  // ticked rows go when you save
    tbl.querySelectorAll("[data-up]").forEach(b => b.onclick = () => { const i = +b.dataset.up; if (i > 0) { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; draw(); upd(); } });
    tbl.querySelectorAll("[data-dn]").forEach(b => b.onclick = () => { const i = +b.dataset.dn; if (i < rows.length - 1) { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; draw(); upd(); } });
  };
  draw(); upd();
  const add = host.querySelector("[data-add]"); if (add) add.onclick = () => { rows.push({...cfg.blank}); draw(); upd(); const last = tbl.querySelector("tr:last-child input,tr:last-child select"); last && last.focus(); };
  save.onclick = () => cfg.onSave(rows.filter(r => !r._rm).map(r => { const {_rm, ...rest} = r; return rest; }));
  return {rows: () => rows};
}

// a small dialog that asks for a date per name; resolves {name: iso} groups, or null if cancelled
function askDates(title, groups) {
  return new Promise(res => {
    const f = $("dform"), today = PLAN.data.today;
    f.innerHTML = `<h3>${title}</h3>` + groups.map((g, gi) => `<p><b>${g.label}</b></p>` + g.names.map((n, ni) => `<div class="dl"><span>${esc(n)}</span><input type="date" value="${today}" data-g="${gi}" data-n="${esc(n)}"></div>`).join("") + `<p>${g.note}</p>`).join("")
      + `<div class="dbtn"><button class="b" value="cancel" formnovalidate>Cancel</button><button class="b pri" value="ok">Confirm</button></div>`;
    const d = $("dlg2"); d.onclose = () => { if (d.returnValue !== "ok") return res(null);
      const out = groups.map(() => ({})); f.querySelectorAll("input[type=date]").forEach(i => { out[+i.dataset.g][i.dataset.n] = i.value; }); res(out); };
    d.returnValue = ""; d.showModal();
  });
}
const planAct = (url, body) => api(url, body).then(r => { toast(r.message); return refreshAll().then(loadPlan); }).catch(fail);

async function loadPlan() {
  try { const y = window.scrollY; PLAN.data = await api("/api/plan?period=" + $("period").value); PLAN.loaded = true; renderPlan(); window.scrollTo(0, y); } catch (e) { fail(e); }  // keep your place after a save
}

function renderPlan() {
  const P = PLAN.data, host = $("pl");
  const sec = (id, name, tip) => `<h3 class="sec" id="${id}">${name} <u class="hp" title="${tip}">ⓘ</u></h3>`;
  host.innerHTML = `<div class="plgrid"><nav class="jump" aria-label="Plan sections"><a data-j="p_inc" tabindex="0" role="link">Income</a><a data-j="p_bills" tabindex="0" role="link">Bills &amp; budgets</a><a data-j="p_extras" tabindex="0" role="link">Extras</a><a data-j="p_rules" tabindex="0" role="link">Rules</a></nav><div class="stack">
    <div class="card${S.meta && S.meta.hide_budget_mode ? " hide" : ""}" id="pm_card"><h2 class="lab">How you budget</h2>
      <div class="ctrl"><div class="seg" id="pm_mode"><button type="button" data-m="biweekly">Every two weeks</button><button type="button" data-m="monthly">Monthly</button></div>
        <label class="fl hide" id="pm_dw" style="margin:0">Month starts on day <select id="pm_day"><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option><option value="6">6</option><option value="7">7</option><option value="8">8</option><option value="9">9</option><option value="10">10</option><option value="11">11</option><option value="12">12</option><option value="13">13</option><option value="14">14</option><option value="15">15</option><option value="16">16</option><option value="17">17</option><option value="18">18</option><option value="19">19</option><option value="20">20</option><option value="21">21</option><option value="22">22</option><option value="23">23</option><option value="24">24</option><option value="25">25</option><option value="26">26</option><option value="27">27</option><option value="28">28</option></select></label>
        <button class="b" id="pm_go" disabled>Switch starting next period</button></div>
      <p class="hint" id="pm_hint" style="margin-top:8px"></p></div>
    ${sec("p_inc", "Income", "Your regular paychecks, and any extra money that came in.")}
    <div class="card"><h2 class="lab">Planned income (every paycheck)</h2><div id="nudges"></div><p class="hint">Your regular paychecks. Changes apply from the current pay period on; once a real deposit lands, the actual amount counts instead. Names must match the categories your rules give those deposits.</p><div id="g_inc"></div></div>
    <div class="card"><h2 class="lab">Extra income</h2><div id="x_inc"></div></div>
    ${sec("p_bills", "Bills &amp; budgets", "Everything planned: bills land in the paycheck their due day falls in; budgets count in every paycheck.")}
    <p class="hint"><b>Held back from your totals.</b> What you list here is taken out of Safe to spend before you spend it: a bill in the paycheck its due day falls in, and a budget in every paycheck, until the money is actually spent. Spending limits (further down) are different: they hold nothing back.</p>
    <div class="card"><h2 class="lab">Recurring expenses</h2><p class="hint">Each bill lands in the pay period its due day falls in. Changes apply to bills due from today on. Leave the due day blank for every-paycheck items; for a bill that isn't monthly, pick Yearly (or Quarterly) and the Month it's due in. Month stays locked while Frequency is Monthly.</p><div id="g_rec"></div><div id="rec_warn"></div>
      <div class="edbar"><span>Plan runs through <b>${esc(P.runs_through)}</b></span><input type="number" id="more_n" min="1" max="26" value="6" style="width:80px"><button class="b" id="more_go">Add pay periods</button></div></div>
    <div class="card"><h2 class="lab">Budget limits</h2><p class="hint">Budgets count in every pay period at their full limit until that paycheck ends (or what you spent, if more). Names must match your rule categories.</p><div id="g_bud"></div></div>
    <div class="card"><h2 class="lab">Spending limits</h2><p class="hint">A limit is a yardstick, not a budget: it sets no money aside, so nothing is held back from Safe to spend. The Overview just shows whether you're under or over it this paycheck (like Gas). The spending itself still counts as an Extra as it happens. Names must match your categories.</p><div id="g_lim"></div></div>
    ${sec("p_extras", "Extras", "Unplanned spending. Manage the extra categories here; this paycheck's extras are on the Overview.")}
    <div class="card"><h2 class="lab">One time future expense</h2><p class="hint">Something you know you will pay once, like a tattoo or a trip deposit. It counts as an extra in the pay period its date falls in (and in the Cash Forecast) until the real charge lands. When an imported charge looks like it, the Transactions tab offers to file it under this name and removes the entry here. Filing a charge under the same name does the same thing.</p><div id="g_ot"></div></div>
    <div class="card"><h2 class="lab">Extra categories</h2><p class="hint">Every extra category you use. Name pieces of a trip like "UK Trip - Dining Out" to group them. Tick One-off for curveballs: they still count in totals but not in "typical extras". Click a category name to rename it everywhere. To merge two, rename one to the other's exact name.</p><div id="g_xc"></div></div>
    <div class="card"><h2 class="lab">Extras by pay period (paycheck start date)</h2><div id="x_chart"></div></div>
    ${sec("p_rules", "Rules", "How bank descriptions get their categories automatically, and a tool to rename or merge a category everywhere.")}
    <div class="card"><h2 class="lab">Auto-categorize rules</h2><p class="hint">If a bank description contains the keyword, it gets the category. First match wins, so keep specific rules above general ones. Categories with "income" in the name count as income.</p><div id="g_rules"></div></div>
    <div class="card"><h2 class="lab">Rename or merge a category</h2><p class="hint">For two names that mean the same thing. Updates rules, transactions, plans and budgets at once.</p>
      <div class="rn"><label>Rename this<select id="rn_old"><option value=""></option>${P.names.map(n => `<option>${esc(n)}</option>`).join("")}</select></label>
      <label>Merge into an existing category<select id="rn_into"><option value=""></option>${P.names.map(n => `<option>${esc(n)}</option>`).join("")}</select></label>
      <label>Or rename to a new name<input type="text" id="rn_new" placeholder="e.g. Onpoint"></label><button class="b pri" id="rn_go" disabled>Rename everywhere</button></div></div>
    ${P.can_undo_rec ? `<div><button class="b" id="rec_undo">Undo last save</button></div>` : ""}</div></div>`;
  host.querySelectorAll("[data-j]").forEach(a => a.onclick = () => $(a.dataset.j).scrollIntoView({behavior: "smooth", block: "start"}));
  host.querySelectorAll("[data-j]").forEach(a => a.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); a.click(); } });
  // the side list shows which section you're reading
  { const links = [...host.querySelectorAll("[data-j]")], ids = links.map(a => a.dataset.j), mark = id => links.forEach(a => a.classList.toggle("on", a.dataset.j === id));
    mark(ids[0]);
    if (window.IntersectionObserver) { if (PLAN.io) PLAN.io.disconnect(); PLAN.io = new IntersectionObserver(es => { const v = es.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]; if (v) mark(v.target.id); }, {rootMargin: "-140px 0px -65% 0px"}); ids.forEach(id => PLAN.io.observe($(id))); } }

  // a nudge: the last two real deposits both differ from the plan, which usually means a raise or a deduction change
  $("nudges").innerHTML = P.nudges.map((n, i) => `<div class="idea"><b>${esc(n.source)}</b> has come in at <b>${money(n.actual)}</b> the last 2 paychecks (planned ${money(n.planned)}).<div class="acts"><button class="b pri" data-na="${i}">Update plan going forward</button><button class="lnk" data-nd="${i}">Not a change</button></div></div>`).join("");
  $("nudges").querySelectorAll("[data-na]").forEach(b => b.onclick = () => planAct("/api/nudge/accept", P.nudges[+b.dataset.na]));
  $("nudges").querySelectorAll("[data-nd]").forEach(b => b.onclick = () => planAct("/api/nudge/dismiss", P.nudges[+b.dataset.nd]));

  // income
  grid($("g_inc"), {saveLabel: "Save income", rows: P.income, blank: {source: "", amount: 0},
    cols: [{k: "source", label: "Income", type: "text"}, {k: "amount", label: "Per paycheck", type: "number", min: 0}],
    onSave: async rows => { const pv = await api("/api/plan/income/preview", {rows}); let cancels = {};
      if (pv.removed.length) { const a = await askDates("Effective date of cancellation", [{label: "You removed:", names: pv.removed, note: "Paychecks on or after this date are removed. Earlier ones stay."}]); if (!a) return; cancels = a[0]; }
      planAct("/api/plan/income", {rows, cancels}); }});
  $("x_inc").innerHTML = P.xincome.length ? `<table><tr><th>Source</th><th>Amount</th></tr>${P.xincome.map(x => `<tr><td>${esc(x.source)}</td><td>${money(x.amount)}</td></tr>`).join("")}</table>` : `<span class="mu">No extra income in this pay period.</span>`;

  // recurring expenses
  const monthOpts = [[0, "—"], ...P.months.map((m, i) => [i + 1, m])];
  grid($("g_rec"), {saveLabel: "Save expenses", rows: P.master.map(m => ({...m, month: m.month || 0, due_day: m.due_day == null ? null : Math.round(m.due_day)})), blank: {item: "", due_day: null, amount: 0, freq: "Monthly", month: 0},
    cols: [{k: "item", label: "Expense name", type: "text"}, {k: "due_day", label: "Due day", type: "number", min: 1, max: 31, step: 1}, {k: "amount", label: "Amount", type: "number", min: 0},
           {k: "freq", label: "Frequency", type: "select", opts: P.freqs.map(f => [f, f])}, {k: "month", label: "Month", type: "select", opts: monthOpts, num: true, on: r => r.freq === "Quarterly" || r.freq === "Yearly"}],
    onSave: async rows => { rows = rows.map(r => ({...r, month: r.month || null}));
      const pv = await api("/api/plan/expenses/preview", {rows});
      $("rec_warn").innerHTML = (pv.no_month.length ? `<div class="warn">${esc(pv.no_month.join(", "))}: pick a Month or the expense stays monthly.</div>` : "") + (pv.clash.length ? `<div class="warn">${esc(pv.clash.join(", "))} is a budget, so it's managed under Budget limits and left out of this list.</div>` : "");
      let starts_on = {}, cancels = {};
      if (pv.changed.length || pv.removed.length) {
        const groups = []; if (pv.changed.length) groups.push({label: "New or changed:", names: pv.changed, note: "Bills due on or after this date follow the new amount and due day. Earlier ones stay, unless you pick a past date, which also updates this pay period's rollover."});
        if (pv.removed.length) groups.push({label: "You removed:", names: pv.removed, note: "Bills due on or after this date are removed. Earlier ones stay, so your rollover doesn't change."});
        const a = await askDates("Effective date", groups); if (!a) return; let gi = 0; if (pv.changed.length) starts_on = a[gi++]; if (pv.removed.length) cancels = a[gi];
      }
      planAct("/api/plan/expenses", {rows, starts_on, cancels}); }});
  $("more_go").onclick = () => planAct("/api/plan/periods", {n: +$("more_n").value || 1});
  // how you budget: every two weeks or monthly. A switch takes effect with the next period; history stays as it is.
  const tgt = P.pending ? {mode: P.pending.mode, day: P.pending.day} : {mode: P.mode, day: P.period_day || 1};  // where you're heading: a switch may already be scheduled
  const nextDay = Math.min(+P.next_start.slice(8), 28), pm = {...tgt};  // switching mid-cycle: offer the day the next period starts on
  const pmDraw = () => {
    [...$("pm_mode").children].forEach(b => b.classList.toggle("on", b.dataset.m === pm.mode)); $("pm_dw").classList.toggle("hide", pm.mode !== "monthly"); $("pm_day").value = pm.day;
    const changed = pm.mode !== tgt.mode || (pm.mode === "monthly" && pm.day !== tgt.day); $("pm_go").disabled = !changed;
    const dl = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-US", {month: "short", day: "numeric"});
    $("pm_hint").textContent = (P.mode === "monthly" ? `You budget monthly: each month runs from day ${P.period_day || 1} to the day before the next one.` : "You budget every two weeks: each paycheck is its own period.")
      + (P.pending ? ` A switch to ${P.pending.mode === "monthly" ? `monthly (from day ${P.pending.day})` : "every two weeks"} is set for ${dl(P.pending.from)}.` : "")
      + " Switching takes effect with your next period. The current one and your history stay as they are, and Undo puts it back."
      + (pm.mode === "monthly" && changed && pm.day !== nextDay ? ` Your next period starts on day ${nextDay}, so the first month will be a short one that ends before day ${pm.day}.` : "");
  };
  $("pm_mode").onclick = e => { const b = e.target.closest("button[data-m]"); if (b) { pm.mode = b.dataset.m; if (pm.mode === "monthly" && P.mode !== "monthly") pm.day = nextDay; pmDraw(); } };
  $("pm_day").onchange = e => { pm.day = +e.target.value; pmDraw(); };
  $("pm_go").onclick = () => { if (confirm(`Switch to ${pm.mode === "monthly" ? "monthly budgeting" : "budgeting every two weeks"} starting with your next period? The periods after the current one are rebuilt from your recurring bills and planned income.`))
    api("/api/period/switch", {mode: pm.mode, day: pm.day}).then(r => { toast(r.message); setTimeout(() => location.reload(), 700); }).catch(fail); };
  pmDraw();
  if ($("rec_undo")) $("rec_undo").onclick = () => planAct("/api/plan/undo_rec", {});

  // budgets, chart
  grid($("g_bud"), {saveLabel: "Save budgets", rows: P.budgets, blank: {category: "", limit: 0},
    cols: [{k: "category", label: "Category", type: "text"}, {k: "limit", label: "Limit", type: "number", min: 0}], onSave: rows => planAct("/api/plan/budgets", {rows})});
  grid($("g_lim"), {saveLabel: "Save limits", rows: P.limits, blank: {category: "", limit: 0},
    cols: [{k: "category", label: "Category", type: "text", ph: "pick or type", list: "limlist"}, {k: "limit", label: "Limit per paycheck", type: "number", min: 0}], onSave: rows => planAct("/api/plan/limits", {rows})});
  $("g_lim").insertAdjacentHTML("afterbegin", `<datalist id="limlist">${P.names.map(n => `<option>${esc(n)}</option>`).join("")}</datalist>`);
  const exs = P.extras_by_period, mx0 = Math.max(...exs.map(e => e.amount), 1), st = niceStep(mx0 * 1.2), mx = Math.ceil(mx0 / st) * st;
  const W = Math.max($("x_chart").clientWidth || 900, 420), H = 260, L = 52, B = 26, T = 22, bw = (W - L - 10) / exs.length, py = v => T + (mx - v) / mx * (H - T - B);
  let gl = ""; for (let v = 0; v <= mx + 1e-6; v += st) gl += `<line x1="${L}" x2="${W - 10}" y1="${py(v)}" y2="${py(v)}" stroke="var(--line)" opacity=".7"/><text x="${L - 8}" y="${py(v) + 4}" fill="var(--mu)" font-size="10.5" text-anchor="end">${v.toLocaleString()}</text>`;
  $("x_chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;display:block">${gl}${exs.map((e, i) => { const x = L + i * bw, h = (H - B) - py(e.amount);
    return `<rect x="${x + 6}" y="${py(e.amount)}" width="${bw - 12}" height="${Math.max(h, 0)}" fill="${e.current ? "var(--ac)" : "var(--pri)"}"><title>${fmtD(e.start)}: ${money(e.amount)}</title></rect><text x="${x + bw / 2}" y="${py(e.amount) - 5}" fill="var(--tx)" font-size="10.5" text-anchor="middle">${e.amount ? "$" + Math.round(e.amount).toLocaleString() : "$0"}</text><text x="${x + bw / 2}" y="${H - 8}" fill="var(--mu)" font-size="10.5" text-anchor="middle">${fmtD(e.start)}</text>`; }).join("")}</svg>`;

  // extra categories, rules
  grid($("g_ot"), {saveLabel: "Save one time future expense", rows: P.onetime, blank: {name: "", date: P.today, amount: 0},
    cols: [{k: "name", label: "What", type: "text", ph: "e.g. Tattoo", list: "catlist"}, {k: "date", label: "Date", type: "date"}, {k: "amount", label: "Amount", type: "number", min: 0},
           {k: "open", label: "Status", ro: true, fmt: (v, r) => v === false ? "Done" : r.check ? "Check Transactions" : "Waiting"}],
    onSave: rows => planAct("/api/forecast/onetime", {rows})});
  grid($("g_xc"), {saveLabel: "Save extra categories", rows: P.xcats.map(x => ({...x, orig: x.name})), noAdd: true, noDelete: true,
    cols: [{k: "name", label: "Category (click to rename)", type: "text", list: "catlist"}, {k: "one_off", label: "One-off", type: "check"},
           {k: "n", label: "Used", ro: true, type: "number"}, {k: "last90", label: "Last 90 days", ro: true, type: "number", fmt: v => money(v)}, {k: "last", label: "Last used", ro: true}],
    onSave: rows => {
      const out = rows.map(r => { const nn = String(r.name || "").trim(); return {name: r.orig, one_off: r.one_off, rename_to: nn && nn !== r.orig ? nn : ""}; }),
        ren = out.filter(r => r.rename_to);
      if (ren.length && !confirm(`Rename ${ren.length} categor${ren.length > 1 ? "ies" : "y"} everywhere (transactions, rules, plan, budgets)?\n\n` + ren.map(r => `${r.name}  →  ${r.rename_to}`).join("\n") + "\n\nIf a new name already exists, they merge into it.")) return;
      planAct("/api/plan/xcats", {rows: out}); }});
  grid($("g_rules"), {saveLabel: "Save rules", rows: P.rules, blank: {keyword: "", category: ""}, reorder: true,
    cols: [{k: "keyword", label: "Keyword", type: "text"}, {k: "category", label: "Category", type: "text", ph: "pick or type", list: "catlist"}], onSave: rows => planAct("/api/plan/rules", {rows})});
  $("g_rules").insertAdjacentHTML("afterbegin", `<datalist id="catlist">${P.names.map(n => `<option>${esc(n)}</option>`).join("")}</datalist>`);

  // rename / merge
  const rnNew = () => $("rn_new").value.trim() || $("rn_into").value, rnCheck = () => { const o = $("rn_old").value, n = rnNew(); $("rn_go").disabled = !(o && n && o.toLowerCase() !== n.toLowerCase());
    $("rn_go").textContent = P.names.some(x => x.toLowerCase() === n.toLowerCase()) ? "Merge everywhere" : "Rename everywhere"; };
  ["rn_old", "rn_into", "rn_new"].forEach(id => $(id).oninput = $(id).onchange = rnCheck);
  $("rn_go").onclick = () => { if (confirm(`Change '${$("rn_old").value}' to '${rnNew()}' everywhere?`)) planAct("/api/plan/rename", {old: $("rn_old").value, new: rnNew()}); };
}
