"use strict";
// First-run setup as a four-step full-page wizard (proof of concept):
//   1 How you budget   2 What you take home   3 Recurring bills   4 Bank transactions (optional)
// Nothing is saved until step 3's "Save and continue": then the period, income and bills are written in one go with the
// ledger's own endpoints. Step 4 is the optional import. Replaces the old one-card welcome (showSetup is redefined here).

const W = {step: 0, mode: "biweekly", date: "", month: "", day: 1,
  income: [{source: "Paycheck", amount: "", cad: "bi"}],
  bills: [], saved: false, imported: 0};

const STEPS = ["How you budget", "What you take home", "Recurring bills", "Bank transactions"];
const CADS = {wk: ["Every week", 52], bi: ["Every two weeks", 26], mo: ["Every month", 12], yr: ["Every year", 1]};
const FREQ = {pay: "Every paycheck", Monthly: "Monthly", Quarterly: "Every 3 months", Yearly: "Yearly"};
const QUICK = ["Rent or mortgage", "Electric", "Water", "Internet", "Phone", "Car payment", "Car insurance", "Streaming", "Credit card minimum", "Student loan"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const perYear = () => W.mode === "biweekly" ? 26 : 12;
const toPeriod = r => (+r.amount || 0) * CADS[r.cad][1] / perYear();   // what one paycheck (or one month) brings in
const toMonth = r => (+r.amount || 0) * CADS[r.cad][1] / 12;
const billMonth = b => {  // what a bill costs in an average month
  const a = +b.amount || 0;
  return b.freq === "pay" ? a * perYear() / 12 : b.freq === "Quarterly" ? a / 3 : b.freq === "Yearly" ? a / 12 : a;
};
const unit = () => W.mode === "biweekly" ? "paycheck" : "month";
const cents = v => money(Math.round(v * 100) / 100, 2);

function wzShell() {
  return `<div class="wz">
    <header class="wz-top"><div class="wz-brand"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" opacity=".18"/><path d="M7 16V12M12 16V8M17 16v-6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg><span>Personal Finance Ledger</span></div>
      <ol class="wz-steps" id="wz_steps" aria-label="Setup progress"></ol></header>
    <div class="wz-grid"><div class="wz-card" id="wz_card" aria-live="polite"></div><aside class="wz-sum" id="wz_sum" aria-label="Your ledger so far"></aside></div></div>`;
}

function drawSteps() {
  $("wz_steps").innerHTML = STEPS.map((s, i) => `<li class="${i < W.step ? "done" : i === W.step ? "on" : ""}"${i === W.step ? ' aria-current="step"' : ""}><i>${i < W.step ? "✓" : i + 1}</i><span>${s}</span></li>`).join("");
}

function drawSum() {
  const inc = W.income.reduce((t, r) => t + toMonth(r), 0), bills = W.bills.reduce((t, b) => t + billMonth(b), 0), left = inc - bills;
  const perP = W.income.reduce((t, r) => t + toPeriod(r), 0);
  const when = W.mode === "biweekly" ? (W.date ? `every two weeks from ${dayLbl(W.date)}` : "every two weeks") : `monthly from ${MONTHS[+(W.month || "2026-01").slice(5, 7) - 1]}, starting on day ${W.day}`;
  $("wz_sum").innerHTML = `<h2>Your ledger so far</h2>
    <dl>
      <div><dt>Budgeting</dt><dd>${W.mode === "biweekly" ? "Every two weeks" : "Monthly"}<small>${when}</small></dd></div>
      <div><dt>Take-home pay</dt><dd>${inc > 0 ? cents(perP) + " <em>per " + unit() + "</em>" : "<span class='none'>Not added yet</span>"}${inc > 0 && W.mode === "biweekly" ? `<small>about ${cents(inc)} a month</small>` : ""}</dd></div>
      <div><dt>Recurring bills</dt><dd>${W.bills.length ? W.bills.length + (W.bills.length === 1 ? " bill" : " bills") + " <em>about " + cents(bills) + " a month</em>" : "<span class='none'>None added yet</span>"}</dd></div>
    </dl>
    <div class="wz-left ${left < 0 ? "neg" : ""}"><span>${inc > 0 && W.bills.length ? "Left after bills" : "Left after bills, once you add both"}</span><b>${inc > 0 && W.bills.length ? cents(left) : "—"}</b><small>${inc > 0 && W.bills.length ? "a month, before anything you spend day to day" : ""}</small></div>
    <p class="wz-priv">Everything stays on this computer. The ledger never connects to your bank.</p>`;
}

const nav = (back, next, nextLabel, extra = "") => `<footer class="wz-foot">${back ? `<button class="b" type="button" id="wz_back">Back</button>` : `<span></span>`}${extra}<button class="b pri" type="button" id="wz_next">${nextLabel}</button></footer>`;

// ---- step 1 ----
function step0() {
  const bi = W.mode === "biweekly";
  $("wz_card").innerHTML = `<h1>How do you budget?</h1>
    <p class="lead">This sets what one budget covers. You can change it later on the Plan tab.</p>
    <div class="wz-choices" role="radiogroup" aria-label="How you budget">
      <button type="button" role="radio" aria-checked="${bi}" class="${bi ? "on" : ""}" data-m="biweekly">
        <svg viewBox="0 0 120 34" aria-hidden="true">${Array.from({length: 7}, (_, i) => `<circle cx="${10 + i * 17}" cy="17" r="${i % 2 ? 4 : 8}" ${i % 2 ? 'opacity=".35"' : ""}/>`).join("")}</svg>
        <b>Every two weeks</b><span>Each paycheck is its own budget. Best if you plan around when you get paid.</span></button>
      <button type="button" role="radio" aria-checked="${!bi}" class="${!bi ? "on" : ""}" data-m="monthly">
        <svg viewBox="0 0 120 34" aria-hidden="true"><rect x="6" y="6" width="108" height="22" rx="8"/></svg>
        <b>Monthly</b><span>One budget per month. Best if you think in monthly bills, however often you're paid.</span></button>
    </div>
    ${bi ? `<label class="wz-f"><span>When is a paycheck day?</span><input type="date" id="wz_date" value="${esc(W.date)}"><small>Any paycheck date works, past or coming up. Every two weeks from it becomes a budget.</small></label>`
      : `<div class="wz-row2"><label class="wz-f"><span>Start from month</span><input type="month" id="wz_month" value="${esc(W.month)}"><small>The earliest month you want to track.</small></label>
        <label class="wz-f"><span>Each month starts on day</span><select id="wz_day">${Array.from({length: 28}, (_, i) => `<option value="${i + 1}"${W.day === i + 1 ? " selected" : ""}>${i + 1}</option>`).join("")}</select><small>Day 1 for calendar months, or the day you get paid.</small></label></div>`}
    ${nav(false, true, "Next", `<span class="wz-skip"><button class="lnk" type="button" id="wz_sample">Just looking? Load sample data</button></span>`)}`;
  $("wz_sample").onclick = () => { if (bi && !W.date) return toast("Pick a paycheck date first.", false); if (!bi && !W.month) return toast("Pick the month to start from.", false);
    api("/api/setup/sample", {mode: W.mode, date: W.date, month: W.month, day: W.day}).then(r => { toast(r.message); setTimeout(() => location.reload(), 600); }).catch(fail); };
  $("wz_card").querySelectorAll("[data-m]").forEach(b => b.onclick = () => { W.mode = b.dataset.m; W.income.forEach(r => { r.cad = W.mode === "biweekly" ? "bi" : "mo"; }); W.bills.forEach(x => { if (W.mode === "monthly" && x.freq === "pay") x.freq = "Monthly"; }); step0(); drawSum(); });
  if ($("wz_date")) $("wz_date").oninput = e => { W.date = e.target.value; drawSum(); };
  if ($("wz_month")) $("wz_month").oninput = e => { W.month = e.target.value; drawSum(); };
  if ($("wz_day")) $("wz_day").onchange = e => { W.day = +e.target.value; drawSum(); };
  $("wz_next").onclick = () => { if (bi && !W.date) return toast("Pick a paycheck date first.", false); if (!bi && !W.month) return toast("Pick the month to start from.", false); go(1); };
}

// ---- step 2 ----
function step1() {
  const u = unit();
  $("wz_card").innerHTML = `<h1>What do you take home?</h1>
    <p class="lead">Enter your pay after taxes, the way you know it. The ledger works out the rest. Add anyone else's pay that goes into the same budget.</p>
    <div class="wz-list" id="wz_inc"></div>
    <button class="wz-add" type="button" id="wz_addinc">+ Add another income</button>
    ${nav(true, true, "Next")}`;
  const draw = () => {
    $("wz_inc").innerHTML = W.income.map((r, i) => `<div class="wz-line inc">
      <label><span>Name</span><input type="text" data-i="${i}" data-k="source" value="${esc(r.source)}" placeholder="Paycheck" maxlength="40"></label>
      <label><span>Amount</span><span class="wz-money"><i>$</i><input type="number" min="0" step="0.01" inputmode="decimal" data-i="${i}" data-k="amount" value="${esc(r.amount)}" placeholder="0.00"></span></label>
      <label><span>How often</span><select data-i="${i}" data-k="cad">${Object.entries(CADS).map(([k, v]) => `<option value="${k}"${r.cad === k ? " selected" : ""}>${v[0]}</option>`).join("")}</select></label>
      <div class="wz-calc" data-calc="${i}"></div>
      ${W.income.length > 1 ? `<button class="wz-x" type="button" data-rm="${i}" aria-label="Remove ${esc(r.source || "this income")}">×</button>` : ""}</div>`).join("");
    $("wz_inc").querySelectorAll("[data-k]").forEach(el => el.oninput = el.onchange = () => { const r = W.income[+el.dataset.i]; r[el.dataset.k] = el.value; calc(); drawSum(); });
    $("wz_inc").querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { W.income.splice(+b.dataset.rm, 1); draw(); drawSum(); });
    calc();
  };
  const calc = () => W.income.forEach((r, i) => { const el = $("wz_inc").querySelector(`[data-calc="${i}"]`); if (!el) return;
    el.innerHTML = +r.amount > 0 ? `<b>${cents(toPeriod(r))}</b> per ${u}<small>${cents(toMonth(r))} a month · ${money(Math.round((+r.amount) * CADS[r.cad][1]), 0)} a year</small>` : `<small>The math shows here</small>`; });
  draw();
  $("wz_addinc").onclick = () => { W.income.push({source: "", amount: "", cad: W.mode === "biweekly" ? "bi" : "mo"}); draw(); drawSum(); $("wz_inc").querySelector(".wz-line:last-child input").focus(); };
  $("wz_back").onclick = () => go(-1);
  $("wz_next").onclick = () => { const ok = W.income.filter(r => r.source.trim() && +r.amount > 0);
    if (!ok.length) return toast("Add what you take home, with a name and an amount.", false);
    if (new Set(ok.map(r => r.source.trim().toLowerCase())).size !== ok.length) return toast("Give each income its own name.", false);
    W.income = ok; go(1); };
}

// ---- step 3 ----
function step2() {
  const bi = W.mode === "biweekly";
  $("wz_card").innerHTML = `<h1>Add your recurring bills</h1>
    <p class="lead">Things you pay on a schedule. Add the main ones now; you can add more, and budgets for groceries and the rest, on the Plan tab.</p>
    <div class="wz-quick" id="wz_quick"><span>Tap to add</span>${QUICK.map(q => `<button type="button" class="wz-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <div class="wz-list" id="wz_bills"></div>
    <button class="wz-add" type="button" id="wz_addbill">+ Add a bill</button>
    ${nav(true, true, "Save and continue", `<span class="wz-skip"><button class="lnk" type="button" id="wz_nobills">I'll add bills later</button></span>`)}`;
  const taken = () => new Set(W.bills.map(b => b.item.trim().toLowerCase()));
  const draw = () => {
    $("wz_bills").innerHTML = W.bills.length ? W.bills.map((b, i) => `<div class="wz-line bill">
      <label><span>Bill</span><input type="text" data-i="${i}" data-k="item" value="${esc(b.item)}" placeholder="Name" maxlength="40"></label>
      <label><span>Amount</span><span class="wz-money"><i>$</i><input type="number" min="0" step="0.01" inputmode="decimal" data-i="${i}" data-k="amount" value="${esc(b.amount)}" placeholder="0.00"></span></label>
      <label><span>Repeats</span><select data-i="${i}" data-k="freq">${Object.entries(FREQ).filter(([k]) => bi || k !== "pay").map(([k, v]) => `<option value="${k}"${b.freq === k ? " selected" : ""}>${v}</option>`).join("")}</select></label>
      <label class="${b.freq === "pay" ? "off" : ""}"><span>${b.freq === "Quarterly" || b.freq === "Yearly" ? "First due" : "Due on day"}</span>
        <span class="wz-due">${b.freq === "Quarterly" || b.freq === "Yearly" ? `<select data-i="${i}" data-k="month" aria-label="Month">${MONTHS.map((m, k) => `<option value="${k + 1}"${+b.month === k + 1 ? " selected" : ""}>${m.slice(0, 3)}</option>`).join("")}</select>` : ""}
        <input type="number" min="1" max="31" step="1" data-i="${i}" data-k="due" value="${esc(b.due)}" ${b.freq === "pay" ? "disabled placeholder=\"—\"" : "placeholder=\"1\""} aria-label="Due day"></span></label>
      <button class="wz-x" type="button" data-rm="${i}" aria-label="Remove ${esc(b.item || "this bill")}">×</button></div>`).join("")
      : `<div class="wz-empty">No bills yet. Tap one above, or add your own.</div>`;
    $("wz_bills").querySelectorAll("[data-k]").forEach(el => el.oninput = el.onchange = () => { const b = W.bills[+el.dataset.i]; b[el.dataset.k] = el.value;
      if (el.dataset.k === "freq") { if ((b.freq === "Quarterly" || b.freq === "Yearly") && !b.month) b.month = new Date().getMonth() + 1; draw(); }
      drawSum(); chips(); });
    $("wz_bills").querySelectorAll("[data-rm]").forEach(x => x.onclick = () => { W.bills.splice(+x.dataset.rm, 1); draw(); drawSum(); chips(); });
    chips();
  };
  const chips = () => { const t = taken(); $("wz_quick").querySelectorAll("[data-q]").forEach(c => { c.disabled = t.has(c.dataset.q.toLowerCase()); }); };
  const add = name => { W.bills.push({item: name, amount: "", due: "", freq: "Monthly", month: ""}); draw(); drawSum(); const row = $("wz_bills").querySelector(".wz-line:last-child"); (name ? row.querySelector('[data-k="amount"]') : row.querySelector('[data-k="item"]')).focus(); };
  $("wz_quick").onclick = e => { const c = e.target.closest("[data-q]"); if (c && !c.disabled) add(c.dataset.q); };
  $("wz_addbill").onclick = () => add("");
  draw();
  $("wz_back").onclick = () => go(-1);
  const finish = skip => {
    const rows = skip ? [] : W.bills.filter(b => b.item.trim() || +b.amount);
    if (!skip) { const bad = rows.find(b => !b.item.trim() || !(+b.amount > 0) || (b.freq !== "pay" && !(+b.due >= 1 && +b.due <= 31)));
      if (bad) return toast(`Finish "${bad.item || "the new bill"}": it needs a name, an amount and a due day.`, false);
      if (new Set(rows.map(b => b.item.trim().toLowerCase())).size !== rows.length) return toast("Give each bill its own name.", false); }
    W.bills = rows; saveAll();
  };
  $("wz_next").onclick = () => finish(false);
  $("wz_nobills").onclick = () => finish(true);
}

// write everything with the ledger's own endpoints: the period first (the others need it), then income, then bills
async function saveAll() {
  const btn = $("wz_next"); btn.disabled = true; btn.textContent = "Saving…";
  try {
    if (!W.saved) {
      await api("/api/setup/period", {mode: W.mode, date: W.date, month: W.month, day: W.day});
      await api("/api/plan/income", {rows: W.income.map(r => ({source: r.source.trim(), amount: Math.round(toPeriod(r) * 100) / 100})), cancels: {}});
      if (W.bills.length) await api("/api/plan/expenses", {rows: W.bills.map(b => ({item: b.item.trim(), amount: +b.amount, freq: b.freq === "pay" ? "Monthly" : b.freq,
        due_day: b.freq === "pay" ? null : +b.due, month: b.freq === "Quarterly" || b.freq === "Yearly" ? +b.month : null})), starts_on: {}, cancels: {}});
      W.saved = true;
    }
    go(1);
  } catch (e) { btn.disabled = false; btn.textContent = "Save and continue"; fail(e); }
}

// ---- step 4 ----
function step3() {
  $("wz_card").innerHTML = `<h1>Bring in your bank transactions</h1>
    <p class="lead">Optional, but it's what makes the ledger useful: it files what you've spent so far. The ledger never connects to your bank. You download a file from your bank's website and give it to the ledger here.</p>
    <label class="wz-drop" id="wz_drop"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
      <span><b id="wz_fname">Choose your bank export</b><small id="wz_fhint">A CSV or Excel file. Click here or drop it in. A range like the last 90 days works well.</small></span>
      <input type="file" id="wz_file" accept=".csv,.xlsx,.xls"></label>
    <div class="wz-msg" id="wz_msg" role="status" aria-live="polite"></div>
    <details class="wz-how"><summary>How do I get this file?</summary><p>Sign in to your bank's website, open your account's transactions, and look for Download or Export. Choose CSV (or Excel) and a date range, then save it. Then pick it here.</p></details>
    ${nav(false, true, W.imported ? "Open my ledger" : "Skip for now and open my ledger", `<span></span>`)}`;
  const drop = $("wz_drop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, () => drop.classList.add("over")));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove("over")));
  $("wz_file").onchange = async () => {
    const f = $("wz_file").files[0]; if (!f) return;
    $("wz_fname").textContent = f.name; $("wz_msg").className = "wz-msg busy"; $("wz_msg").textContent = "Reading your file…";
    try {
      const data = await b64(f), pv = await api("/api/import/preview", {name: f.name, data}), g = pv.guess;
      if (!g.confident) { $("wz_msg").className = "wz-msg warn"; $("wz_msg").textContent = "We couldn't be sure which columns are the date and amount. Open your ledger, then use the import button on the left edge to check them."; return; }
      const r = await api("/api/import/commit", {name: f.name, data, dcol: g.date, acol: g.amount, debit: g.debit, credit: g.credit, scol: g.desc, spending: g.spending === "negative" ? "negative" : "positive", append: true});
      W.imported = 1; $("wz_msg").className = "wz-msg ok"; $("wz_msg").textContent = r.message; $("wz_next").textContent = "Open my ledger";
    } catch (e) { $("wz_msg").className = "wz-msg warn"; $("wz_msg").textContent = "Couldn't read that file: " + (e.message || e); }
  };
  $("wz_next").onclick = () => { $("wz_next").disabled = true; location.reload(); };
}

const STEP_FNS = [step0, step1, step2, step3];
function go(d) { W.step = Math.max(0, Math.min(3, W.step + d)); drawSteps(); STEP_FNS[W.step](); drawSum(); window.scrollTo({top: 0}); const h = $("wz_card").querySelector("h1"); if (h) { h.tabIndex = -1; h.focus({preventScroll: true}); } }

function showSetup() {
  document.body.classList.add("setup");
  $("setup").classList.remove("hide");
  $("setup").innerHTML = wzShell();
  W.date = W.date || S.meta.today; W.month = W.month || S.meta.today.slice(0, 7);
  $("sub").textContent = "Set up your ledger";
  go(0);
}
