"use strict";
// The Cash Forecast tab: runway chart, savings and debt what-if sliders, the paycheck grid, balances. Loaded after plan.js.
const FC = {apply: null, applyKey: "", F: null, n: 6, amt: 0, mode: "ask", pin: null, sa: 0, sd: 0, saAmt: null, sdAmt: null, det: false, init: false, debt: null, loaded: false};
// the what-if: `sa` and `sd` are two independent sliders, the % of each paycheck's extra put toward savings and toward debt.
// They start at 0 (nothing assigned). Either can instead be a fixed dollar amount per paycheck (`saAmt`/`sdAmt`, null = use the %): typing
// dollars shows the matching %, moving the slider shows the matching dollars, and whichever you touched last is the one that counts.
const addMonths = (d, n) => new Date(d.getFullYear(), d.getMonth() + n, 1);
const monthWhen = m => m == null ? "Never at this pace" : m === 0 ? "Paid off" : addMonths(new Date(), m).toLocaleDateString("en-US", {month: "short", year: "numeric"});
const span = m => m >= 12 && m % 12 ? `${Math.floor(m / 12)} yr ${m % 12} mo` : m >= 12 ? `${Math.floor(m / 12)} yr` : `${m} month${m !== 1 ? "s" : ""}`;
const D = s => new Date(s + "T00:00:00");
const dayLbl = s => D(s).toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});
const sum = (a, f = x => x) => a.reduce((t, x) => t + f(x), 0);
const mon0 = d => money(d, 0);

async function loadForecast() {
  if (!FC.init) $("fc").innerHTML = `<div class="card"><p class="hint" role="status">Loading forecast…</p></div>`;
  try { FC.F = await api("/api/forecast"); FC.loaded = true; if (!FC.init) { initForecast(); } else computeAll(); }
  catch (e) { fail(e); if (!FC.init) { $("fc").innerHTML = `<div class="card"><p class="hint" role="alert">The forecast didn't load: ${esc(e.message || e)}</p><button class="b" type="button" id="f_retry">Try again</button></div>`; $("f_retry").onclick = loadForecast; } }
}

// a help mark: focusable, read aloud, shown on hover (title) and on keyboard focus (data-tip). The text is written once.
const hp = t => { const q = t.replace(/"/g, "&quot;"); return `<span class="hp" tabindex="0" role="note" title="${q}" data-tip="${q}" aria-label="${q}">ⓘ</span>`; };

const pdays = r => Math.round((D(r.end) - D(r.start)) / 864e5) + 1;  // days in a pay period (14 when paid every two weeks)

function initForecast() {
  const F = FC.F; FC.init = true; FC.thr = F.threshold; FC.pin = F.today;
  $("fc").innerHTML = `<div class="stack"><div class="card" id="fc_main"><h2 class="lab">Money runway ${hp("Blue line: each paycheck's own extra (income minus bills, budgets and extras); dots turn red when a paycheck runs short. White line: your rollover, the running total, which shows when money runs out. Solid is what happened, dashed is the projection. The sliders show what putting a share of your extra into savings and toward debt does to your rollover. Nothing here is saved.")}</h2>
    <div class="runctl"><label class="fld"><span class="ft">Show</span><select id="f_n">${[1, 2, 3, 6, 9, 12].map(n => `<option value="${n}"${n === 6 ? " selected" : ""}>${n === 1 ? "Next paycheck" : "Next " + n + " paychecks"}</option>`).join("")}</select></label>
      <label class="fld hide"><span class="ft">One-time payment</span><span class="pfx"><i>$</i><input type="number" id="f_amt" step="50" min="0" value="0"></span></label>
      <div class="seg hide" id="f_mode"><button data-m="ask" class="on">When can I afford it?</button><button data-m="pin">On a date I pick</button></div>
      <label class="fld hide" id="f_dwrap"><span class="ft">On date</span><input type="date" id="f_date" value="${F.today}"></label></div>
    <div class="fcgrid"><div class="fcmain"><div id="f_head"></div>
    <div id="f_msg"></div>
    <div id="f_live" class="sr" role="status" aria-live="polite"></div>
    <div class="fcrow" id="fcrow"><div class="fcl">
      <div class="tabctl"><label class="tog"><input type="checkbox" id="f_det"> Show all the numbers</label></div>
      <div class="scroll"><table id="f_tab" class="grid"></table></div></div></div>
    <p class="hint" id="f_note"></p>
    <details class="more" id="f_dates"><summary>Paycheck dates and 3-paycheck months</summary><div id="f_dates_in"></div></details></div>
    <aside class="whatif" id="f_whatif" aria-label="What-if planner">
      <div class="wi">
        <div class="wtl" role="heading" aria-level="3">What-if planner ${hp("Slide Savings and Debt to see what putting a share of each paycheck's extra there does to your rollover. Nothing here is saved.")}</div>
        <div class="applyto"><span id="ap_lbl">Apply to</span>${hp("Savings and Debt take their share of each ticked paycheck's own extra. Paychecks you leave unticked keep all of theirs. A what-if only.")}<details class="apdd" id="f_apply"><summary id="ap_sum" aria-labelledby="ap_lbl ap_sum">All paychecks</summary><div class="appanel" id="ap_panel"></div></details></div>
        <div class="wi2">
          <div class="wcol"><div class="wctl"><label class="sl"><span class="slh">Savings: share of my extra ${hp("The share of each paycheck's extra (what's left after bills, budgets and extras) you'd move to savings. Or type a dollar amount to move that much from every paycheck: the percentage follows it. A what-if only: nothing here is saved.")}<span class="thrn"><i>$</i><input type="number" id="f_sa_n" min="0" step="10" inputmode="decimal" autocomplete="off" placeholder="0" aria-label="Savings: dollars per paycheck"></span><b id="v_sa">0%</b></span><span class="rng"><input type="range" id="f_sa" min="0" max="100" step="5" value="0" aria-label="Savings: share of my extra" aria-describedby="cap_sa"></span></label><small class="capn" id="cap_sa"></small></div>
            <div class="wib" id="b_sv"><div class="cat" style="color:var(--green-t)">Savings</div><div id="s_sv"></div></div></div>
          <div class="wcol"><div class="wctl"><label class="sl"><span class="slh">Debt: share of my extra ${hp("The share of each paycheck's extra that goes toward debt, on top of your minimums. Or type a dollar amount to pay that much from every paycheck: the percentage follows it. Savings and Debt share the same 100% of your extra, so each slider only goes as far as the other leaves room for. A what-if only.")}<span class="thrn"><i>$</i><input type="number" id="f_sd_n" min="0" step="10" inputmode="decimal" autocomplete="off" placeholder="0" aria-label="Debt: dollars per paycheck"></span><b id="v_sd">0%</b></span><span class="rng"><input type="range" id="f_sd" min="0" max="100" step="5" value="0" aria-label="Debt: share of my extra" aria-describedby="cap_sd"></span></label><small class="capn" id="cap_sd"></small></div>
            <div class="wib" id="b_db"><div class="cat" id="c_db" style="color:var(--k3-t)">Debt</div><div id="s_db"></div></div></div>
        </div>
      </div></aside></div></div>
    <div class="two"><div class="card"><h2 class="lab">One-time expenses</h2><p class="hint">Something you know is coming: a trip, a repair. Each is added to the paycheck its date falls in. Once it shows in your bank import, delete it here so it isn't counted twice.</p><div id="g_ot"></div></div>
    <div class="card"><h2 class="lab">Balances</h2><div class="ctrl"><label class="fl">Saved so far<input type="number" id="b_have" step="100" min="0" value="${F.savings_have}"></label><label class="fl">Savings yield %<input type="number" id="b_apy" step="0.25" min="0" max="20" value="${F.savings_apy}"></label></div>
      <div id="b_unseen"></div><div id="b_moved"></div>
      <h2 class="lab" style="margin-top:14px">Debts</h2><div id="g_debts"></div></div></div></div>`;
  // transfers to savings made at the bank that Saved so far doesn't include yet
  if (F.unseen && F.unseen.n) {
    $("b_unseen").innerHTML = `<div class="ok">${money(F.unseen.amount)} you transferred to savings at the bank (${F.unseen.n} transfer${F.unseen.n !== 1 ? "s" : ""}) isn't in Saved so far yet.
      <div class="ctrl" style="margin:8px 0 0"><button class="b pri" id="u_add">Add it</button><button class="b" id="u_no">Ignore</button></div></div>`;
    const seen = add => api("/api/savings/seen", {add}).then(r => { toast(r.message); return refreshAll().then(() => { FC.init = false; return loadForecast(); }); }).catch(fail);
    $("u_add").onclick = () => seen(true); $("u_no").onclick = () => seen(false);
  }
  // extra income you moved to savings from the Transactions tab, with a way to take it back
  if (F.moved.length) {
    $("b_moved").innerHTML = `<p class="hint">Includes ${money(sum(F.moved, m => m.amount))} moved from extra income (${F.moved.length} deposit${F.moved.length !== 1 ? "s" : ""}).</p>
      <details class="more"><summary>Moved to savings</summary><table style="margin-top:8px"><tr><th class="l"></th><th class="l">Date</th><th class="l">Description</th><th>Amount</th></tr>${F.moved.map(m => `<tr><td class="l"><input type="checkbox" data-bk="${esc(m.id)}"></td><td class="l">${esc(String(m.date).slice(0, 10))}</td><td class="l">${esc(m.description.slice(0, 40))}</td><td>${money(m.amount)}</td></tr>`).join("")}</table>
      <button class="b" id="b_back" style="margin-top:8px" disabled>Take back to spendable</button></details>`;
    const boxes = [...$("b_moved").querySelectorAll("input[data-bk]")];
    boxes.forEach(b => b.onchange = () => { $("b_back").disabled = !boxes.some(x => x.checked); });
    $("b_back").onclick = () => api("/api/savings/back", {ids: boxes.filter(x => x.checked).map(x => x.dataset.bk)}).then(r => { toast(r.message); return refreshAll().then(() => { FC.init = false; return loadForecast(); }); }).catch(fail);
  }
  $("f_apply").addEventListener("focusout", e => { if (e.relatedTarget && !$("f_apply").contains(e.relatedTarget)) $("f_apply").open = false; });  // Tab out of the menu closes it
  $("f_n").onchange = e => { FC.n = +e.target.value; computeAll(); };
  $("f_amt").oninput = e => { FC.amt = Math.max(+e.target.value || 0, 0); computeAll(); };
  $("f_mode").onclick = e => { const b = e.target.closest("button"); if (!b) return; FC.mode = b.dataset.m; [...$("f_mode").children].forEach(x => x.classList.toggle("on", x === b)); $("f_dwrap").classList.toggle("hide", FC.mode !== "pin"); computeAll(); };
  $("f_date").onchange = e => { FC.pin = e.target.value; computeAll(); };
  $("f_det").checked = !!FC.det; $("f_det").onchange = e => { FC.det = e.target.checked; computeAll(); };
  // Savings and Debt share one 100%: each slider can only go as far as the other leaves room for
  $("f_sa").oninput = e => { FC.saAmt = null; FC.sa = Math.min(+e.target.value, FC.sdAmt != null ? 100 : 100 - FC.sd); FC.speak = true; computeAll(); };
  $("f_sd").oninput = e => { FC.sdAmt = null; FC.sd = Math.min(+e.target.value, 100 - FC.sa); FC.speak = true; computeAll(); };
  // a dollar box: that much from every paycheck (never more than one paycheck's income); the % moves to match. Empty goes back to the %.
  const setAmt = (k, v) => { const n = v === "" ? null : Math.min(Math.max(+v || 0, 0), FC.cap > 0 ? FC.cap : Infinity); FC[k + "Amt"] = n; if (n == null) FC[k] = 0; FC.speak = true; computeAll(); };
  $("f_sa_n").oninput = e => setAmt("sa", e.target.value); $("f_sd_n").oninput = e => setAmt("sd", e.target.value);
  const saveBal = () => api("/api/settings", {set: {savings_have: +$("b_have").value || 0, savings_apy: +$("b_apy").value || 0}}).then(() => { FC.F.savings_have = +$("b_have").value || 0; FC.F.savings_apy = +$("b_apy").value || 0; computeAll(); }).catch(fail);
  $("b_have").onchange = $("b_apy").onchange = saveBal;
  const reload = r => { toast(r.message); return refreshAll().then(() => { FC.init = false; return loadForecast(); }); };
  grid($("g_ot"), {saveLabel: "Save one time future expense", rows: F.onetime, blank: {name: "", date: F.today, amount: 0},
    cols: [{k: "name", label: "What", type: "text"}, {k: "date", label: "Date", type: "date"}, {k: "amount", label: "Amount", type: "number", min: 0}],
    onSave: rows => api("/api/forecast/onetime", {rows}).then(reload).catch(fail)});
  grid($("g_debts"), {saveLabel: "Save debts", rows: F.debts, blank: {name: "", current_balance: 0, min_payment: null, apr: null, start_balance: null, in_email: true},
    cols: [{k: "name", label: "Debt", type: "text"}, {k: "current_balance", label: "Current balance", type: "number", min: 0}, {k: "min_payment", label: "Monthly minimum", type: "number", min: 0}, {k: "apr", label: "APR %", type: "number", min: 0, max: 100}],
    onSave: rows => api("/api/forecast/debts", {rows}).then(reload).catch(fail)});
  computeAll();
}

// the "Apply to" menu: tick the paychecks the Savings and Debt sliders act on (or All paychecks)
function drawApply(inV) {
  $("ap_panel").innerHTML = `<label class="apall"><input type="checkbox" id="ap_all"> All paychecks</label>`
    + inV.map(r => `<label><input type="checkbox" data-p="${esc(r.start)}"> ${esc(r.full)}</label>`).join("");
  $("ap_panel").onchange = e => {  // one handler for every box; nothing is rebuilt, so keyboard focus stays on the box you used
    const t = e.target;
    if (t.id === "ap_all") FC.apply = t.checked ? null : [];
    else if (t.dataset.p) { const on = [...$("ap_panel").querySelectorAll("[data-p]")].filter(x => x.checked).map(x => x.dataset.p); FC.apply = on.length === inV.length ? null : on; }
    FC.speak = true; syncApply(inV); computeAll(); };
  syncApply(inV);
}
function syncApply(inV) {
  const all = !FC.apply || FC.apply.length === inV.length, n = FC.apply ? FC.apply.length : inV.length;
  $("ap_sum").textContent = all ? "All paychecks" : n === 0 ? "No paychecks" : n === 1 ? inV.find(r => r.start === FC.apply[0]).full : n + " paychecks";
  const ba = $("ap_all"); ba.checked = all; ba.indeterminate = !all && n > 0;
  $("ap_panel").querySelectorAll("[data-p]").forEach(b => { b.checked = !FC.apply || FC.apply.includes(b.dataset.p); });
}
document.addEventListener("keydown", e => { const d = $("f_apply"); if (e.key === "Escape" && d && d.open) { d.open = false; $("ap_sum").focus(); } });
document.addEventListener("click", e => { const d = $("f_apply"); if (d && d.open && !d.contains(e.target)) d.open = false; });  // click elsewhere closes the menu

// ---------- the numbers ----------
function computeAll() {
  const empty = !FC.F.rows.length || !FC.F.rows.some(r => r.phase !== "past");  // nothing ahead to forecast (a new install, or every paycheck is in the past)
  ["#fc .whatif", "#fcrow", "#f_note", "#f_msg", "#f_dates"].forEach(q => $("fc").querySelector(q)?.classList.toggle("hide", empty));
  if (empty) {
    $("f_head").innerHTML = `<p class="hint" role="status">There are no upcoming paychecks to forecast yet. Add income on the Plan tab, or import your latest transactions.</p>`;
    return;
  }
  // nothing here can go past one paycheck's income: the threshold and the dollar boxes stop at the largest upcoming paycheck
  const cap = Math.max(0, ...FC.F.rows.filter(r => r.phase !== "past").map(r => +r.income || 0)); FC.cap = cap;
  if (cap > 0 && FC.thr > cap) FC.thr = Math.round(cap * 100) / 100;
  const F = FC.F, today = D(F.today), thr = FC.thr, rows = F.rows.map(r => ({...r, s: D(r.start)}));
  const future = rows.filter(r => r.phase === "future");
  let horizon = future.length ? future[Math.min(FC.n, future.length) - 1].s : today;
  const opening = rows[0].available - rows[0].pc_extra;
  const live = rows.filter(r => r.phase !== "past");
  // when could a one-time payment fit: the most each paycheck can take while every later rollover stays above the threshold
  const av = live.map(r => r.available), room = av.map((_, k) => Math.max(Math.min(...av.slice(k)) - thr, 0));
  const fits = live.filter((_, k) => room[k] >= FC.amt - .005);
  let pick = live[0], exp = null, found = null;
  if (FC.amt > 0) {
    if (FC.mode === "ask") { found = fits.length ? new Date(Math.max(fits[0].s, today)) : null; exp = found || D(FC.pin || F.today); pick = fits[0] || live[0]; }
    else { exp = D(FC.pin || F.today); pick = [...live].reverse().find(r => r.s <= exp) || live[0]; }
    if (pick.s > horizon) horizon = pick.s;
  }
  // the scenario: the payment comes out of one paycheck, and the rollover chain is rebuilt
  const scen = rows.map(r => ({...r, spend2: r.spend + (FC.amt > 0 && r.start === pick.start ? FC.amt : 0)}));
  let run = opening; scen.forEach(r => { r.pc2 = r.income - r.spend2; run += r.pc2; r.av2 = run; });
  const inV = scen.filter(r => r.phase !== "past" && r.s <= horizon);
  const pos = inV.map(r => Math.max(r.pc2, 0));
  const apy = F.savings_apy, have = F.savings_have;
  // nothing is assigned until you slide
  // Savings and Debt share one 100% of the extra. The threshold doesn't limit them: it only drives the flags in the table.
  // which paychecks the sliders apply to: all of them, or the ones ticked in the "Apply to" menu
  const keys = inV.map(r => r.start).join();
  if (FC.applyKey !== keys) { FC.applyKey = keys; if (FC.apply) FC.apply = FC.apply.filter(k => inV.some(r => r.start === k)); drawApply(inV); }
  const used = r => !FC.apply || FC.apply.includes(r.start);
  // Savings and Debt: a % of each paycheck's extra, or a fixed dollar amount per paycheck. A dollar amount shows as the % of your average
  // extra it equals; a % shows as the average dollars it comes to. They share one 100% of the extra, and Savings is taken first.
  const usedPos = pos.filter((_, i) => used(inV[i])), avgPos = usedPos.length ? sum(usedPos) / usedPos.length : 0;
  const eqPct = a => avgPos > 0 ? Math.min(Math.round(a / avgPos * 100), 100) : 0, avgOf = pc => Math.round(avgPos * pc) / 100;
  if (FC.saAmt != null) FC.sa = FC.saAmt > 0 ? Math.max(eqPct(FC.saAmt), 1) : 0;
  if (FC.sdAmt != null) FC.sd = FC.sdAmt > 0 ? Math.max(eqPct(FC.sdAmt), 1) : 0;
  if (FC.sdAmt == null && FC.sa + FC.sd > 100) FC.sd = 100 - FC.sa;
  [["sa", "f_sa_n"], ["sd", "f_sd_n"]].forEach(([k, id]) => { const box = $(id), amt = FC[k + "Amt"]; box.max = cap > 0 ? cap : "";
    if (document.activeElement !== box || (cap > 0 && +box.value > cap)) box.value = amt != null ? amt : FC[k] > 0 ? Math.round(avgOf(FC[k])) : ""; });
  $("f_sa").value = FC.sa; $("f_sd").value = FC.sd; $("v_sa").textContent = FC.sa + "%"; $("v_sd").textContent = FC.sd + "%";
  $("f_sa").setAttribute("aria-valuetext", FC.sa + " percent"); $("f_sd").setAttribute("aria-valuetext", FC.sd + " percent");
  ["f_sa", "f_sd"].forEach(id => { const e = $(id); e.style.setProperty("--pf", (e.value - e.min) / ((e.max - e.min) || 1)); });  // where the filled part of each track ends
  const {alloc, dpay, after} = shares(inV, pos, used, FC.sa, FC.sd, FC.saAmt, FC.sdAmt);
  inV.forEach((r, i) => { r.alloc = alloc[i]; r.dpay = dpay[i]; r.after = after[i]; });
  const capTxt = (k, other, label) => { const amt = FC[k + "Amt"], pc = FC[k];
    if (amt != null && amt > 0) { const short = usedPos.filter(p => p < amt - .005).length;
      return `A fixed ${money(amt)} from every paycheck, about ${pc}% of your average extra.` + (short ? ` ${short} paycheck${short !== 1 ? "s have" : " has"} less extra than that and give what they have.` : ""); }
    return (FC[other] && !(k === "sa" && FC.sdAmt != null) ? `Up to ${100 - FC[other]}% (${label} has ${FC[other]}%)` : k === "sa" && FC.sdAmt != null ? "Up to 100% (savings comes first)" : "Up to 100%") + (pc > 0 ? `. About ${money(avgOf(pc), 0)} per paycheck on average.` : ""); };
  $("cap_sa").textContent = capTxt("sa", "sd", "Debt"); $("cap_sd").textContent = capTxt("sd", "sa", "Savings");
  // headline
  const neg = inV.find(r => r.av2 < 0), low = inV.find(r => r.av2 < thr), bottom = inV.reduce((a, b) => b.av2 < a.av2 ? b : a);
  const [state, hit] = neg ? ["bad", neg] : low ? ["warn", low] : ["good", null];
  const head = neg ? `Rollover runs out around ${dayLbl(neg.start)}` : low ? `Rollover dips below ${money(thr)} around ${dayLbl(low.start)}` : `Rollover stays above ${money(thr)} through ${dayLbl(inV[inV.length - 1].start)}`;
  const futPc = inV.filter(r => r.phase === "future").map(r => r.pc2), fm = futPc.length ? sum(futPc) / futPc.length : null;
  const flow = fm == null ? "" : fm >= 0 ? `Each future paycheck adds about ${money(fm)}.` : `Each future paycheck runs about ${money(-fm)} short.`;
  const tone = {bad: "var(--red)", warn: "var(--amber)", good: "var(--green-t)"}[state];
  $("f_head").innerHTML = `${neg ? `<div style="font-size:1.35rem;font-weight:700;color:${tone};margin:6px 0 2px">${esc(head)}</div>` : ""}<div class="mu" style="font-size:.9rem;margin:${neg ? 0 : 8}px 0 8px">${FC.amt > 0 ? `With ${money(FC.amt)} on the ${fmtD(pick.start)} paycheck. ` : ""}Lowest rollover: ${money(bottom.av2)} around ${fmtD(bottom.start)}. ${flow}</div>`;
  // does the payment fit
  let msg = "";
  if (FC.amt > 0) {
    if (FC.mode === "ask") msg = fits.length ? `<div class="ok">Pay ${money(FC.amt)} on <b>${fmtD(found.toISOString().slice(0, 10))}</b> or later, in the ${esc(fits[0].full)} paycheck. Your rollover never drops below ${money(Math.min(...scen.filter(r => r.phase !== "past" && r.s >= fits[0].s).map(r => r.av2)))} after that.</div>`
      : `<div class="warn">${money(FC.amt)} doesn't fit in any paycheck of your forecast while keeping your ${money(thr)} threshold. The most any one can take is ${money(Math.max(...room))}.</div>`;
    else { const k = live.indexOf(pick), m = Math.min(...scen.filter(r => r.phase !== "past" && r.s >= pick.s).map(r => r.av2)) - thr;
      msg = m >= -.005 ? `<div class="ok">Fits. After ${money(FC.amt)} on ${fmtD(exp.toISOString().slice(0, 10))}, your rollover never drops below ${money(m + thr)}, ${money(m)} above your threshold.</div>` : `<div class="warn">Too much for that paycheck: it would take your rollover to ${money(m + thr)}, ${money(-m)} under your threshold. The most that paycheck can take is ${money(room[k])}.</div>`; }
  }
  $("f_msg").innerHTML = msg;
  // the three boxes
  const nV = Math.max(inV.length, 1), totS = sum(alloc), totD = sum(dpay), posTot = sum(pos);
  const endLbl = fmtD(inV[inV.length - 1].start); let bal = have; alloc.forEach((a, i) => { bal = bal * (1 + apy / 100 * pdays(inV[i]) / 365) + a; });
  const stat = (k, v) => `<div class="st2"><span>${k}</span><b>${v}</b></div>`, big = (v, c) => `<div class="bigs" style="color:${c}">${v}</div>`;
  if (FC.sa === 0) $("s_sv").innerHTML = `<div class="bigs idle">$0</div><div class="mu sm">set aside. Slide Savings, or type a dollar amount.</div>`;
  else $("s_sv").innerHTML = big(money(totS), "var(--green-t)") + `<div class="mu sm">over ${inV.length} paychecks</div>` + stat("Balance by " + endLbl, money(bal)) + stat("Per paycheck", money(totS / nV));
  if (FC.sd === 0) $("s_db").innerHTML = `<div class="bigs idle">$0</div><div class="mu sm">extra toward debt. Slide Debt, or type a dollar amount.</div>`;
  else { debtStats(totD, nV, inV, endLbl); }
  table(inV, FC.amt > 0);
}

let debtT; function debtStats(totD, nV, inV, endLbl) {
  const render = d => { FC.debt = d; if (!d.has_debt) { $("s_db").innerHTML = `<div class="bigs" style="color:var(--k3-t)">${money(totD)}</div><div class="mu sm">over ${inV.length} paychecks, on top of minimums</div><div class="mu sm">No debts listed, so there's no payoff date. Add them under Debts below.</div>`; return; }
    const sooner = d.free_base != null && d.free_new != null && d.free_base > d.free_new ? ` (${span(d.free_base - d.free_new)} sooner)` : "";
    $("s_db").innerHTML = `<div class="bigs" style="color:var(--k3-t)">${money(totD)}</div><div class="mu sm">over ${inV.length} paychecks, on top of minimums</div>` + `<div class="st2"><span>Debt-free</span><b>${monthWhen(d.free_new)}${sooner}</b></div><div class="st2"><span>Interest saved</span><b>${d.saved == null ? "-" : money(d.saved)}</b></div>`; };
  if (FC.debt) render(FC.debt);
  clearTimeout(debtT); debtT = setTimeout(() => api(`/api/forecast/debt?extra=${(totD / nV * FC.F.ppm).toFixed(2)}&through=${inV[inV.length - 1].end}`).then(render).catch(fail), 120);
}

// The paycheck table is the forecast, full width: the paycheck, its extra, the rollover and (once a slider is set) what goes to savings and
// debt and what's left of the extra. "Show all the numbers" adds the income, bills, budgets, extras, rollover-in and the savings and debt balances.
function table(inV, hasAmt) {
  const F = FC.F, apy = F.savings_apy, sa = FC.sa > 0, sd = FC.sd > 0, det = !!FC.det, ssa = det && sa, ssd = det && sd; let bal = F.savings_have, cumD = 0;
  const neg = v => v < 0 ? ' class="neg"' : "";
  inV.forEach(r => { bal = bal * (1 + apy / 100 * pdays(r) / 365) + r.alloc; r.sb = bal; cumD += r.dpay; r.cd = cumD; r.rin = r.av2 - r.pc2; });
  const z = v => Math.abs(v) < 0.005 ? 0 : v, ex = r => z(r.pc2 - r.alloc - r.dpay);
  const c = (l, html, cls = "", attrs = "") => `<td data-l="${l}"${cls ? ` class="${cls}"` : ""}${attrs}>${html}</td>`;  // data-l labels the value when a phone shows each paycheck as a card
  const gcell = (l, total, cls) => c(l, money(total), cls, ` data-sort="${total.toFixed(2)}"`);
  const rl = (sa || sd) ? "Rollover after what-if" : "Rollover $";
  const cols = [det && "<th>Income</th>", det && "<th>Bills</th>", det && "<th>Budgets</th>", det && "<th>Extras</th>", hasAmt && "<th>One-time payment</th>", det && "<th>Rollover in</th>",
    "<th>Paycheck extra</th>", (sa || sd ? "<th class=\"wk\">Rollover after what-if</th>" : "<th>Rollover $</th>"), ssa && `<th class="sv gbh">Savings (balance)</th>`, ssd && `<th class="dt gbh">Paid toward debt</th>`, sa && `<th class="sv">To savings</th>`, sd && `<th class="dt">To debt</th>`, (sa || sd) && `<th class="wk">Extra left over</th>`];
  // flag every paycheck whose rollover (after the what-if, once a slider is set) is under the threshold
  const thr = FC.thr, rv = r => (sa || sd) ? z(r.after) : r.av2, low = r => rv(r) < thr, lows = inV.filter(low);
  const mRoll = Math.max(1, ...inV.map(r => Math.max(rv(r), 0))), mExt = Math.max(1, ...inV.map(r => Math.abs(r.pc2)));
  const bar = (v, m) => ` style="--w:${Math.min(Math.abs(v) / m * 100, 100).toFixed(1)}%"`;
  const rollCell = r => { const v = rv(r), cls = ["rc", "bar", (sa || sd) ? "wk" : "", v < 0 ? "neg" : "", low(r) ? "low" : ""].filter(Boolean).join(" ");
    return c(rl, `${low(r) ? `<span class="sr">Under your ${money(thr, 0)} threshold: </span>` : ""}<span>${low(r) ? `<span aria-hidden="true">⚠ </span>` : ""}${money(v)}</span>`, cls, (low(r) ? ` title="Under your ${money(thr)} threshold"` : "") + bar(v, mRoll)); };
  const lowest = inV.reduce((m, r) => Math.min(m, rv(r)), Infinity);
  let h = `<tr><th class="l">Paycheck</th>${cols.filter(Boolean).join("")}</tr>`;
  inV.forEach(r => {
    h += `<tr><td class="l" data-l="">${esc(r.full)}</td>` + (det ? c("Income", money(r.income)) + c("Bills", money(r.scheduled)) + c("Budgets", money(r.budgets)) + c("Extras", money(r.extras)) : "") + (hasAmt ? c("One-time payment", money(r.spend2 - r.spend)) : "")
      + (det ? c("Rollover in", money(r.rin), r.rin < 0 ? "neg" : "") : "")
      + c("Paycheck extra", money(r.pc2), "bar" + (r.pc2 < 0 ? " neg" : " pos"), bar(r.pc2, mExt))
      + rollCell(r)
      + (ssa ? gcell("Savings (balance)", r.sb, "sv") : "") + (ssd ? gcell("Paid toward debt", r.cd, "dt") : "")
      + (sa ? c("To savings", money(r.alloc), "sv") : "") + (sd ? c("To debt", money(r.dpay), "dt") : "")
      + ((sa || sd) ? c("Extra left over", money(ex(r)), "wk" + (ex(r) < 0 ? " neg" : "")) : "") + `</tr>`; });
  const t = f => sum(inV, f), last = inV[inV.length - 1];
  h += `<tr class="tot"><td class="l" data-l="">Total (${inV.length} paychecks)</td>` + (det ? c("Income", money(t(r => r.income))) + c("Bills", money(t(r => r.scheduled))) + c("Budgets", money(t(r => r.budgets))) + c("Extras", money(t(r => r.extras))) : "") + (hasAmt ? c("One-time payment", money(t(r => r.spend2 - r.spend))) : "")
    + (det ? '<td class="nl"></td>' : "")
    + c("Paycheck extra", money(t(r => r.pc2))) + ((sa || sd) ? c("Rollover after what-if", money(z(last.after)), "wk rc") : '<td class="nl"></td>')
    + (ssa ? c("Savings (balance)", money(last.sb), "sv") : "") + (ssd ? c("Paid toward debt", money(last.cd), "dt") : "")
    + (sa ? c("To savings, incl. saved so far", money(F.savings_have + t(r => r.alloc)), "sv", ` title="Includes the ${money(F.savings_have)} already in Saved so far"`) : "") + (sd ? c("To debt", money(t(r => r.dpay)), "dt") : "")
    + ((sa || sd) ? c("Extra left over", money(z(t(ex))), "wk") : "") + `</tr>`;
  if (FC.speak) { clearTimeout(FC.liveT); const tA = t(r => r.alloc), tD = t(r => r.dpay);
    const msg = (lows.length ? `${lows.length} of ${inV.length} paychecks are under your ${money(thr, 0)} threshold.` : `No paycheck is under your ${money(thr, 0)} threshold.`) + (sa || sd ? ` Savings ${money(tA, 0)}, debt ${money(tD, 0)}.` : "");
    FC.liveT = setTimeout(() => { $("f_live").textContent = msg; FC.speak = false; }, 700); }
  $("f_tab").innerHTML = h;
  const ft = $("f_tab"); ft.setAttribute("role", "table"); ft.setAttribute("aria-label", "Paycheck forecast");  // the phone layout restyles the table, which drops its meaning unless the roles are explicit
  ft.querySelectorAll("tbody").forEach(x => x.setAttribute("role", "rowgroup")); ft.querySelectorAll("tr").forEach(x => x.setAttribute("role", "row"));
  ft.querySelectorAll("th").forEach(x => x.setAttribute("role", "columnheader")); ft.querySelectorAll("td").forEach(x => x.setAttribute("role", x.classList.contains("l") ? "rowheader" : "cell")); $("fcrow").classList.toggle("det", det);
  const a = F.anchor, lo = inV[0].start, hi = last.end;
  const ots = F.onetime.filter(o => o.open && o.amount > 0 && o.date >= (lo > F.today ? lo : F.today) && o.date <= hi).sort((p, q) => p.date.localeCompare(q.date));
  $("f_note").innerHTML = (sa ? `<div>The To savings total includes the ${money(F.savings_have)} already in Saved so far. The rows above it are only what this plan adds.</div>` : "") + (det ? `<div>Rollover in + Paycheck extra = Rollover $. The green columns are a what-if (saving and paying debt from each extra) that follows the sliders; the rest are real numbers. Budgets are held at their full limit, so the first row's Rollover $ is the Overview's Safe to spend.</div>` : "")
    + (a ? `<div style="margin-top:6px">Starting point: bank balance ${money(a.bank)} as of ${fmtD(a.as_of)}${a.to_arrive ? `, plus ${money(a.to_arrive)} still to arrive` : ""}, minus ${money(a.to_leave)} still to pay = ${money(a.left)} left after budgets. It re-anchors every time you import a file.</div>` : "")
    + (ots.length ? `<div style="margin-top:6px">One-time expenses counted in Extras: ${ots.map(o => `<b>${esc(o.name)}</b> ${money(o.amount)} on ${fmtD(o.date)}`).join(" · ")}</div>` : "");
  paydayTable(inV);
}


// the paychecks in view and which months bring a third one (paychecks every 2 weeks)
function paydayTable(inV) {
  const det = $("f_dates"); if (det) det.style.display = FC.F.mode === "monthly" ? "none" : "";  // a third paycheck is only a thing when you're paid every 2 weeks
  if (FC.F.mode === "monthly") return;
  const base = D(FC.F.rows[0].start), byM = {}, key = d => d.getFullYear() + "-" + d.getMonth();
  for (let k = -80; k < 160; k++) { const d = new Date(base.getTime() + k * 14 * 864e5); (byM[key(d)] = byM[key(d)] || []).push(d); }
  let h = `<div class="scroll"><table class="grid fit"><tr><th class="l">Payday</th><th class="l">Month</th><th class="l">In the month</th><th>Income</th><th>Paycheck extra</th><th class="l">Note</th></tr>`;
  inV.forEach(r => { const d = D(r.start), list = byM[key(d)], three = list.length === 3;
    h += `<tr${three ? ' style="background:rgba(234,179,8,.2)"' : ""}><td class="l">${d.toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric"})}</td><td class="l">${d.toLocaleDateString("en-US", {month: "short", year: "numeric"})}</td><td class="l">${list.findIndex(x => +x === +d) + 1} of ${list.length}</td><td>${money(r.income)}</td><td>${money(r.pc2)}</td><td class="l">${three ? "3-paycheck month ⭐" : ""}</td></tr>`; });
  const today = D(FC.F.today), up = Object.values(byM).filter(l => l.length === 3 && l[l.length - 1] >= today).sort((p, q) => p[0] - q[0]).slice(0, 3);
  $("f_dates_in").innerHTML = h + `</table></div><p class="hint">With paychecks every 2 weeks, two months a year bring a third one. Coming up: ${up.length ? up.map(l => `<b>${l[0].toLocaleDateString("en-US", {month: "short", year: "numeric"})}</b> (${l.map(x => x.toLocaleDateString("en-US", {month: "short", day: "2-digit"})).join(", ")})`).join(" · ") : "none soon"}. Your bills are monthly, so the third paycheck of those months covers few of them. Its extra is usually your biggest, and a good one to put toward savings or debt.</p>`;
}
