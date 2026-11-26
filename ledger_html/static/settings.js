"use strict";
// The left icon rail and its slide-out panel: pages (gear), appearance, TV mode, import, sample data.
// The Background dropdown, sorted into groups: the weather scenes together (shown without the "Weather: " prefix), Prismatic on its own, the patterns, then None.
function bgOptions(list, cur) {
  const opt = (x, label) => `<option value="${esc(x)}"${x === cur ? " selected" : ""}>${esc(label || x)}</option>`;
  const wx = list.filter(x => x.startsWith("Weather: ")), rest = list.filter(x => !x.startsWith("Weather: ") && x !== "None" && x !== "Prismatic parallax drift");
  return [list.includes("None") ? opt("None") : "",
    list.includes("Prismatic parallax drift") ? `<optgroup label="Animated">${opt("Prismatic parallax drift")}</optgroup>` : "",
    wx.length ? `<optgroup label="Weather">${wx.map(x => opt(x, x.slice(9))).join("")}</optgroup>` : "",
    rest.length ? `<optgroup label="Patterns">${rest.map(x => opt(x)).join("")}</optgroup>` : ""].join("");
}

function b64(file) { return new Promise(res => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.readAsDataURL(file); }); }
const everything = () => { PLAN.loaded = false; FC.init = false; FC.loaded = false; FC.debt = null; return Promise.all([api("/api/theme").then(applyTheme), refreshAll()]); };

// ---- open and close: click a little tab to slide its part out, click it again (or elsewhere, or press Escape) to close ----
const body = document.body;
const syncRail = () => document.querySelectorAll(".rt[data-sec]").forEach(t => t.setAttribute("aria-expanded", String(body.dataset.sec === t.dataset.sec)));
function openSec(s) { body.dataset.sec = s; body.dataset.last = s; syncRail(); }
function closeSec() { delete body.dataset.sec; syncRail(); }
$("rail").onclick = e => { const t = e.target.closest(".rt"); if (!t) return;
  body.dataset.sec === t.dataset.sec ? closeSec() : openSec(t.dataset.sec); };
document.addEventListener("click", e => { if (body.dataset.sec && !e.target.closest("#panel, #rail")) closeSec(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && body.dataset.sec) { const t = document.querySelector(`.rt[data-sec="${body.dataset.sec}"]`); closeSec(); t && t.focus(); } });

// Phone access: opens the ledger to phones on your home Wi-Fi, behind a PIN. Only this PC can change it.
function phoneBox() {
  const L = S.meta.lan || {}, local = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
  if (!local) return `<p class="hint">Phone access is ${L.enabled ? "on" : "off"}. Change it on the PC the ledger runs on.</p>`;
  return `<p class="hint">Use the ledger from a phone on the same Wi-Fi. Every phone has to enter your PIN. The connection is plain HTTP on your home network, so only turn this on at home.</p>
    ${L.weak ? `<p class="hint" style="color:var(--red)"><b>Your PIN is too short.</b> Set one with 6 or more characters. Short PINs are easy to guess.</p>` : ""}
    ${L.enabled ? `<p class="hint"><b>On.</b> ${L.urls && L.urls.length ? "Open " + L.urls.map(u => `<code>${esc(u)}</code>`).join(" or ") + " on your phone." : "Open this PC's network address on your phone."}</p>` : ""}
    <label class="fl">${L.enabled ? "New PIN" : "Choose a PIN"} <u class="hp" title="6 to 32 characters, no spaces. Six or more digits is a good choice. It is stored scrambled, never as typed.">ⓘ</u><input type="password" id="d_pin" autocomplete="new-password" maxlength="32" placeholder="${L.has_pin && !L.enabled && !L.weak ? "leave blank to reuse your last PIN" : "6 or more characters"}"></label>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">${L.enabled ? `<button class="b pri" id="d_lan_pin">Change PIN</button><button class="b" id="d_lan_out" title="Every phone has to enter the PIN again.">Sign out all phones</button><button class="b" id="d_lan_off">Turn off</button>` : `<button class="b pri" id="d_lan_on">Turn on</button>`}</div>
    <p class="hint">The first time, Windows may ask about the firewall: allow it on private networks.</p>`;
}

function panel() {
  const t = S.theme, p = $("panel"), pages = [...$("tabs").children].filter(b => b.style.display !== "none");
  const cur = ($("tabs").querySelector(".on") || {}).dataset?.t;
  p.innerHTML = `
  <div class="psec" data-s="menu"><div class="ptitle">Menu</div><div class="pnav"><ul>${pages.map(b => `<li data-t="${b.dataset.t}" class="${b.dataset.t === cur ? "on" : ""}" role="button" tabindex="0"><p>${esc(b.textContent)}</p></li>`).join("")}</ul></div></div>
  <div class="psec" data-s="look"><div class="ptitle">Appearance</div><div class="pbox">
    <label class="fl">Ledger name <u class="hp" title="Shown at the top of the page and in the browser tab. Leave blank for the default.">ⓘ</u><input type="text" id="d_name" maxlength="40" placeholder="Personal Finance Ledger" value="${esc(S.meta.app_name || "")}"></label>
    <label class="fl">Theme<select id="d_theme">${t.themes.map(x => `<option value="${x.key}"${x.key === t.theme ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
    <div class="sw">${["dark", "primary", "accent", "light"].map(k => `<span title="${k}" style="background:${t.ui[k]}"></span>`).join("")}</div>
    <label class="tog"><input type="checkbox" id="d_dark" ${t.dark ? "checked" : ""}> Dark mode</label>
    <label class="tog" style="margin-top:8px"><input type="checkbox" id="d_anim" ${t.anim.on ? "checked" : ""}> Animations <u class="hp" title="Off gives the plain, still theme: no moving colours behind the page and no cards rising in.">ⓘ</u></label>
    ${t.anim.on ? (() => { const wx = t.anim.bg.startsWith("Weather: "), moving = !wx && t.anim.bg !== "None"; return `<div class="pbox" style="margin-top:8px">
      <label class="fl">Background <u class="hp" title="The moving picture behind the page. Weather and Animated draw their own colors; Patterns use your theme's colors.">ⓘ</u><select id="d_abg">${bgOptions(t.anim_opts.backgrounds, t.anim.bg)}</select></label>
      ${moving ? `<label class="fl">Speed <u class="hp" title="How fast the background moves.">ⓘ</u><select id="d_aspd">${t.anim_opts.speeds.map(x => `<option${x === t.anim.speed ? " selected" : ""}>${esc(x)}</option>`).join("")}</select></label>` : ""}
      ${wx ? "" : `<label class="fl">Card effects <u class="hp" title="Prismatic: the glowing ring, glare and rising cards. Cascade: cards rising in. Shimmer: the ring and glare on cards (coming soon here). Gentle: only cards rising in. This no longer changes the background.">ⓘ</u><select id="d_astyle">${t.anim_opts.styles.map(x => `<option${x === t.anim.style ? " selected" : ""}>${esc(x)}</option>`).join("")}</select></label>`}</div>`; })() : ""}
    <label class="fl" style="margin-top:10px">Text size <u class="hp" title="Makes the whole page smaller or larger on this device. Saved in this browser.">ⓘ</u>
    <select id="d_font">${[[11.5, "Smallest"], [12.5, "Smaller"], [13.5, "Default"], [15, "Larger"], [16.5, "Largest"]].map(([v, n]) => `<option value="${v}"${Math.abs(parseFloat(getComputedStyle(document.documentElement).fontSize) - v) < .3 ? " selected" : ""}>${n}</option>`).join("")}</select></label></div></div>
  <div class="psec" data-s="lan"><div class="ptitle">Phone access</div><div class="pbox">${phoneBox()}</div></div>
  <div class="psec" data-s="tv"><div class="ptitle">TV mode</div><div class="pbox"><p class="hint">A big-screen view of the Overview and Cash Forecast, without the editing controls. Cast that tab to your TV.</p>
    <label class="fl">TV size <u class="hp" title="Match the window you cast: 1080p for a normal PC window, 4K if your screen is 4K at 100% scaling.">ⓘ</u><select id="d_tv"><option value="1080">1080p</option><option value="4k">4K</option></select></label>
    <button class="b" id="d_tvgo" style="margin-top:10px">Open TV mode</button></div><p class="hint pfoot">${S.meta.test_mode ? "Using sample data" : "Using your data"}</p></div>
  <div class="psec" data-s="imp"><div class="ptitle">Import bank transactions</div><p class="hint">Import a bank export any time.</p><div id="d_imp_res"></div>
    <div class="pbox"><label class="tog"><input type="radio" name="imode" value="append" checked> Append (skip duplicates)</label><p class="hint">Adds new rows and skips anything already imported.</p>
    <label class="tog"><input type="radio" name="imode" value="replace"> Replace this file's dates</label><p class="hint">Swaps out bank rows on the dates the file covers; hand-entered ones stay.</p>
    <input type="file" id="d_file" accept=".csv,.xlsx,.xls"><div id="d_map"></div></div></div>
  <div class="psec" data-s="test"><div class="ptitle">Test data</div><div class="pbox"><label class="tog"><input type="checkbox" id="d_test" ${S.meta.test_mode ? "checked" : ""}> Use sample data</label><p class="hint">Made-up numbers in their own folder. Your real data is untouched.</p>
    ${S.meta.test_mode ? `<div class="ctrl"><button class="b" id="d_shuf">Shuffle test data</button><button class="b" id="d_reset">Reset test data</button></div>` : ""}</div></div>`;
  p.querySelectorAll(".pnav li").forEach(li => li.onclick = () => { const b = $("tabs").querySelector(`[data-t="${li.dataset.t}"]`); if (b) b.click(); closeSec(); });
  p.querySelectorAll(".pnav li").forEach(li => li.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); li.click(); } });
  const look = () => api("/api/settings", {set: {theme: $("d_theme").value, dark_mode: $("d_dark").checked}}).then(() => api("/api/theme")).then(th => { applyTheme(th); panel(); renderOverview(); if (FC.init) computeAll(); }).catch(fail);
  $("d_theme").onchange = $("d_dark").onchange = look;
  const lanSet = enabled => { const pin = ($("d_pin") || {}).value || ""; api("/api/lan/set", {enabled, pin}).then(r => { toast(r.message); return api("/api/meta"); }).then(m => { S.meta = m; panel(); }).catch(fail); };
  if ($("d_lan_on")) $("d_lan_on").onclick = () => lanSet(true);
  if ($("d_lan_pin")) $("d_lan_pin").onclick = () => { if (!$("d_pin").value.trim()) return toast("Type the new PIN first."); lanSet(true); };
  if ($("d_lan_off")) $("d_lan_off").onclick = () => lanSet(false);
  if ($("d_lan_out")) $("d_lan_out").onclick = () => api("/api/lan/set", {enabled: true, signout: true}).then(r => toast(r.message)).catch(fail);
  $("d_name").onchange = () => { const n = $("d_name").value.trim(); api("/api/settings", {set: {app_name: n, name_asked: true}}).then(() => { S.meta.app_name = n; applyName(n); toast("Name saved."); }).catch(fail); };
  // animation choices save to your real settings (shared with the payday email) and the page restyles at once
  const anim = () => api("/api/settings", {set: {animations: $("d_anim").checked, ...($("d_abg") ? {...($("d_astyle") ? {anim_style: $("d_astyle").value} : {}), anim_bg: $("d_abg").value, ...($("d_aspd") ? {anim_speed: $("d_aspd").value} : {})} : {})}}).then(() => api("/api/theme")).then(th => { applyTheme(th); panel(); }).catch(fail);
  ["d_anim", "d_astyle", "d_abg", "d_aspd"].forEach(id => $(id) && ($(id).onchange = anim));
  $("d_font").onchange = e => { document.documentElement.style.fontSize = e.target.value + "px"; try { localStorage.setItem("ft_font", e.target.value); } catch (err) {} if (FC.cargs && !$("fc").classList.contains("hide")) chart(...FC.cargs); };
  $("d_tvgo").onclick = () => window.open(`/?tv=${$("d_tv").value}`, "_blank");
  if ($("d_test")) $("d_test").onchange = e => api("/api/mode", {test: e.target.checked}).then(r => { toast(r.message); S.sel.clear(); return everything(); }).then(panel).catch(fail);
  if ($("d_shuf")) $("d_shuf").onclick = () => api("/api/test/shuffle", {}).then(r => { toast(r.message); return everything(); }).then(panel).catch(fail);
  if ($("d_reset")) $("d_reset").onclick = () => api("/api/test/reset", {}).then(r => { toast(r.message); return everything(); }).then(panel).catch(fail);
  $("d_file").onchange = async e => { const f = e.target.files[0]; if (!f) return; const data = await b64(f);
    try { showMapping(f, data, await api("/api/import/preview", {name: f.name, data})); } catch (err) { fail(err); } };
}

// Which column is which, and how this bank shows money spent. Filled in with the best guess; the person checks it, then imports.
function showMapping(f, data, pv) {
  const g = pv.guess, box = $("d_map");
  const opt = (sel, none) => (none ? `<option value=""${sel === "" ? " selected" : ""}>${none}</option>` : "") + pv.columns.map(c => `<option${c === sel ? " selected" : ""}>${esc(c)}</option>`).join("");
  const eg = (pv.sample && pv.sample[0]) ? Object.values(pv.sample[0]).filter(v => v).slice(0, 4).map(esc).join(" · ") : "";
  box.innerHTML = `<p class="hint">${pv.rows.toLocaleString()} rows. Check the columns${eg ? `. The first row reads: <i>${eg}</i>` : ""}</p>
    <label class="fl">Date column<select id="m_d">${opt(g.date)}</select></label>
    <label class="fl">Amount column<select id="m_a">${opt(g.amount, "Two columns: money out and money in")}</select></label>
    <div id="m_split" class="${g.split ? "" : "hide"}"><label class="fl">Money out (debit) column<select id="m_db">${opt(g.debit)}</select></label>
      <label class="fl">Money in (credit) column<select id="m_cr">${opt(g.credit)}</select></label></div>
    <label class="fl">Description column<select id="m_s">${opt(g.desc)}</select></label>
    <div id="m_sp" class="${g.split || g.spending === "typed" ? "hide" : ""}"><label class="fl">In your file, money spent shows as
      <select id="m_sg"><option value="positive"${g.spending !== "negative" ? " selected" : ""}>positive numbers (like 45.20)</option><option value="negative"${g.spending === "negative" ? " selected" : ""}>negative numbers (like -45.20)</option></select></label>
      <p class="hint">If your spending shows up as income afterwards, this is the setting to flip.</p></div>
    <button class="b pri" id="m_go" style="margin-top:8px">Import file</button>`;
  $("m_a").onchange = () => { const two = $("m_a").value === ""; $("m_split").classList.toggle("hide", !two); $("m_sp").classList.toggle("hide", two || g.spending === "typed"); };
  $("m_go").onclick = () => api("/api/import/commit", {name: f.name, data, dcol: $("m_d").value, acol: $("m_a").value, debit: $("m_db").value, credit: $("m_cr").value,
      scol: $("m_s").value, spending: $("m_sg").value, append: document.querySelector("input[name=imode]:checked").value === "append"})
    .then(r => { box.innerHTML = ""; $("d_file").value = ""; toast(r.message); return refreshAll().then(() => { $("d_imp_res").innerHTML = `<div class="ok">${esc(r.message)}</div>`; }); }).catch(fail);
}
// keep the menu's "current page" highlight right whenever a tab changes
$("tabs").addEventListener("click", () => setTimeout(() => { const cur = ($("tabs").querySelector(".on") || {}).dataset?.t; document.querySelectorAll(".pnav li").forEach(li => li.classList.toggle("on", li.dataset.t === cur)); }, 0));
// (app.js calls panel() once the theme and data have loaded)

// TV mode: ?tv=1080 or ?tv=4k, a bigger, read-only view
const tvq = new URLSearchParams(location.search).get("tv");
if (tvq) { document.body.classList.add("tv"); document.body.style.zoom = tvq === "4k" ? 2 : 1.35; $("tabs").querySelector('[data-t=ov]').click(); }
