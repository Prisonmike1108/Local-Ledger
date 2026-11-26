"use strict";
// The Email tab: settings for the payday email (FinanceEmail.py), try-it-out, send, and recent sends. Loaded after settings.js.
const EM = {S: null, loaded: false};
const title2 = s => s.replace(/\b\w/g, c => c.toUpperCase());

// a search-and-pick box: type to filter the list, press Enter or click to bring one in as a card; click the x to take it back out
function multi(host, o) {
  let sel = [...o.selected], active = 0, shown = [], focusAfter = false; const fmt = o.format || (x => x);
  const thumb = x => o.thumbs ? `<img src="/email_assets/pokemon/${encodeURIComponent(x)}.png" alt="">` : "";
  const draw = () => {
    host.innerHTML = `<div class="chips2">${sel.map(x => `<span class="chip2">${thumb(x)}${esc(fmt(x))}<button type="button" data-x="${esc(x)}" aria-label="Remove ${esc(fmt(x))}">×</button></span>`).join("")}
      <div class="cb"><input type="text" role="combobox" aria-expanded="false" autocomplete="off" placeholder="${esc(sel.length ? "Search to add another…" : (o.placeholder || "Search…"))}"><div class="cbl hide" role="listbox"></div></div></div>`;
    const inp = host.querySelector("input"), list = host.querySelector(".cbl");
    const rebuild = () => {
      const q = inp.value.trim().toLowerCase();
      shown = o.options.filter(x => !sel.includes(x) && (!q || fmt(x).toLowerCase().includes(q)));
      if (o.groups) { const ord = o.order || [], gi = x => { const k = ord.indexOf(o.groups[x] || "Extras"); return k < 0 ? ord.length : k; }; shown = shown.map((x, i) => [x, i]).sort((a, b) => gi(a[0]) - gi(b[0]) || a[1] - b[1]).map(a => a[0]); }  // grouped, each group keeping its order
      shown = shown.slice(0, o.groups ? 400 : 60);  // a grouped list shows every group (Income comes last), the plain one is capped active = Math.min(active, Math.max(shown.length - 1, 0));
      list.innerHTML = shown.length ? shown.map((x, i) => { const g = o.groups ? (o.groups[x] || "Extras") : null, head = g && (i === 0 || g !== (o.groups[shown[i - 1]] || "Extras")) ? `<div class="cbg">${esc(g)}</div>` : "";
        return head + `<div class="cbo${i === active ? " on" : ""}" role="option" data-i="${i}">${thumb(x)}${esc(fmt(x))}</div>`; }).join("") : `<div class="cbo none">${q ? "Nothing matches" : "Everything is already added"}</div>`;
      list.querySelectorAll(".cbo[data-i]").forEach(el => el.onmousedown = e => { e.preventDefault(); add(shown[+el.dataset.i]); });
    };
    const show = () => { list.classList.remove("hide"); inp.setAttribute("aria-expanded", "true"); rebuild(); };
    const hide = () => { list.classList.add("hide"); inp.setAttribute("aria-expanded", "false"); };
    const add = v => { if (!v) return; sel.push(v); focusAfter = true; o.onChange && o.onChange(sel); draw(); };
    inp.onfocus = show; inp.oninput = () => { active = 0; show(); }; inp.onblur = hide;
    inp.onkeydown = e => {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, shown.length - 1); rebuild(); list.querySelector(".on")?.scrollIntoView({block: "nearest"}); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); rebuild(); list.querySelector(".on")?.scrollIntoView({block: "nearest"}); }
      else if (e.key === "Enter") { e.preventDefault(); add(shown[active]); }
      else if (e.key === "Escape") { hide(); inp.blur(); }
      else if (e.key === "Backspace" && !inp.value && sel.length) { sel.pop(); focusAfter = true; o.onChange && o.onChange(sel); draw(); }
    };
    host.querySelectorAll("[data-x]").forEach(b => b.onclick = () => { sel = sel.filter(x => x !== b.dataset.x); o.onChange && o.onChange(sel); draw(); });
    if (focusAfter) { focusAfter = false; inp.focus(); }
  };
  draw(); return {get: () => sel, reset: v => { sel = [...v]; draw(); }};
}

async function loadEmail() { try { EM.S = await api("/api/email"); EM.loaded = true; renderEmail(); } catch (e) { fail(e); } }

function renderEmail() {
  const E = EM.S, s = E.settings, host = $("em");
  if (!E.script_ok) { host.innerHTML = `<div class="card soon">FinanceEmail.py isn't in the same folder as the dashboard, so the payday email isn't set up.</div>`; return; }
  const nxt = E.next_payday ? new Date(E.next_payday + "T00:00:00").toLocaleDateString("en-US", {weekday: "short", month: "short", day: "numeric"}) : null;
  host.innerHTML = `<div class="emgrid"><div class="card" id="em_set"><h2 class="lab">Payday email settings</h2><p class="hint">A summary of the paycheck goes out every payday morning. These settings are saved for the scheduled send and the buttons on the right.</p>
    <h3 class="emsec">Recipients</h3><label class="fl">Send to <u class="hp" title="One address per line. Everyone here gets the summary each payday.">ⓘ</u><textarea id="e_to" rows="3">${esc(s.to.join("\n"))}</textarea></label>
    <details class="more" ${s.cc.length || s.bcc.length ? "open" : ""}><summary>More recipients (Cc and Bcc)</summary><div class="two2"><label class="fl">Cc<input type="text" id="e_cc" value="${esc(s.cc.join(", "))}"></label><label class="fl">Bcc<input type="text" id="e_bcc" value="${esc(s.bcc.join(", "))}"></label></div></details>
    <h3 class="emsec">What's in it</h3><div class="fl">Leave out of the email <u class="hp" title="Bills, budgets, extras or income lines that shouldn't be listed. The totals still count them.">ⓘ</u><div id="e_hidden"></div></div>
    <label class="fl">Greetings <u class="hp" title="One per line. Each email opens with one picked at random.">ⓘ</u><textarea id="e_greet" rows="3">${esc(s.greetings.join("\n"))}</textarea></label>
    <label class="fl">Notes <u class="hp" title="One per line. Shown at the bottom of every email.">ⓘ</u><textarea id="e_notes" rows="3">${esc(s.notes.join("\n"))}</textarea></label>
    <label class="fl">Sign-off note<input type="text" id="e_love" value="${esc(s.love_note)}"></label>
    <h3 class="emsec">Pokémon</h3><div class="fl">Pokémon that dance at the bottom <u class="hp" title="Each one dances in its own spot along the bottom of every email. Pick none for no strip. To add more, drop a transparent PNG named after the Pokémon into email_assets/pokemon. Save, then Preview to see it.">ⓘ</u><div id="e_poke"></div></div>
    <div class="fl" style="margin-top:10px">Pokémon that stroll between sections <u class="hp" title="Each one waddles in place on the confetti between sections. Every other strip gets one; with several picked they take turns and stand in different spots. Pick none to keep the strips plain.">ⓘ</u><div id="e_walk"></div></div>
    <h3 class="emsec">Schedule</h3>
    <label class="fl">Send time <u class="hp" title="The time of day the payday email goes out. It is the start time of the Windows scheduled task that sends it, so saving a new time changes that task for you. If the PC is asleep or off then, it sends when it next wakes.">ⓘ</u><input type="time" id="e_time" step="300" value="" disabled style="width:150px"></label>
    <p class="hint" id="e_tnote">Checking Task Scheduler…</p>
    <label class="fl">Catch-up days <u class="hp" title="If the PC was off on payday, the summary still goes out when it next runs within this many days.">ⓘ</u><input type="number" id="e_catch" min="0" max="13" value="${s.catchup_days}" style="width:100px"></label>
    <div class="edbar embar"><button class="b" id="e_save">Save email settings</button><span class="dirty hide" id="e_dirty">Unsaved changes</span></div></div>
    <div class="emright">
      <div class="card"><h2 class="lab">Try it out</h2><p class="hint">Send yourself a test, or just look at it. Pick any paycheck and what to leave out. Nothing here is saved, and a test never counts as the payday send.${E.test_mode ? " Test data is on, so these use the sample numbers." : ""}</p>
        <label class="fl">Send test to <u class="hp" title="One or more addresses, separated by commas. Cc and Bcc are skipped on a test.">ⓘ</u><input type="text" id="e_tto" value="${esc(s.test_to || s.sender)}"></label>
        <label class="fl" style="margin-top:8px">Data as of paycheck<select id="e_per">${E.periods.map(p => `<option value="${p.start}"${p.start === E.current ? " selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
        <div class="fl" style="margin-top:8px">Leave out (this test only) <u class="hp" title="Starts with your saved list, so a test matches the real email. Change it to try other combinations; nothing here is saved.">ⓘ</u><div id="e_thide"></div></div>
        <label class="fl" style="margin-top:8px">Season look <u class="hp" title="Each email is themed for the season of its paycheck. Auto uses that; pick one to see how the others look.">ⓘ</u><select id="e_season">${["Auto", "Winter", "Spring", "Summer", "Fall"].map(x => `<option>${x}</option>`).join("")}</select></label>
        <div class="ctrl" style="margin-top:12px"><button class="b" id="e_prev">Preview</button><button class="b" id="e_test">Send test</button></div></div>
      <div class="card"><h2 class="lab">Payday send</h2><p class="hint">The real one. It goes out by itself every payday morning, with your saved settings. The button sends this paycheck's summary right now.</p>
        <div>${nxt ? `Next payday email: <b>${nxt}</b>` : "No later paycheck in your plan, so nothing is scheduled."}</div>
        <div class="hint" style="margin-top:6px">${E.last ? `${E.last.ok ? "✅" : "⚠️"} Last run ${esc(E.last.at || "")}: ${esc(E.last.message || "")}` : "Hasn't run yet."}</div>
        <div class="hint">Sends from ${esc(s.sender || "(no sender set)")}.</div>${E.test_mode ? `<div class="hint">Real sends are switched off while sample data is on.</div>` : ""}
        <button class="b" id="e_send" style="margin-top:10px" ${s.to.length === 0 || E.test_mode ? "disabled" : ""}>Send this paycheck's summary now to ${s.to.length} recipient${s.to.length !== 1 ? "s" : ""}</button></div>
      <div class="card"><h2 class="lab">Recent sends</h2>${E.sends.length ? `<table><tr><th class="l">Sent</th><th class="l">Paycheck</th><th class="l">To</th><th class="l">Status</th></tr>${E.sends.map(r => `<tr><td class="l">${esc(r.sent)}</td><td class="l">${esc(r.period)}</td><td class="l">${r.to} people</td><td class="l">${r.status === "sent" ? "✓ Sent" : esc(r.status)}</td></tr>`).join("")}</table>` : `<span class="mu">Nothing sent yet.</span>`}</div></div></div>`;

  const hidden = multi($("e_hidden"), {options: E.items, groups: E.item_groups, order: CAT_GROUPS, selected: s.hidden, placeholder: "Pick bills, budgets, extras or income…", onChange: () => dirty()});
  const poke = multi($("e_poke"), {options: E.pokemon, selected: s.pokemon.filter(p => E.pokemon.includes(p)), format: title2, thumbs: true, placeholder: "Pick Pokémon…", onChange: () => dirty()});
  const walk = multi($("e_walk"), {options: E.pokemon, selected: s.pokemon_walk.filter(p => E.pokemon.includes(p)), format: title2, thumbs: true, placeholder: "Pick Pokémon…", onChange: () => dirty()});
  const thide = multi($("e_thide"), {options: E.items, groups: E.item_groups, order: CAT_GROUPS, selected: s.hidden, placeholder: "Nothing left out"});
  const form = () => ({to: $("e_to").value, cc: $("e_cc").value, bcc: $("e_bcc").value, hidden: hidden.get(), pokemon: poke.get(), pokemon_walk: walk.get(),
    greetings: $("e_greet").value, notes: $("e_notes").value, love_note: $("e_love").value, catchup_days: +$("e_catch").value || 0, send_time: $("e_time").value});
  const snap = () => JSON.stringify(form()); let orig = snap();
  function dirty() { const d = snap() !== orig; $("e_save").classList.toggle("pri", d); $("e_dirty").classList.toggle("hide", !d); }
  ["e_to", "e_cc", "e_bcc", "e_greet", "e_notes", "e_love", "e_catch", "e_time"].forEach(id => $(id).oninput = dirty);
  // The send time lives in the Windows scheduled task, which is slow to look up, so it fills in after the tab is up.
  const clock12 = t => { const [h, m] = t.split(":").map(Number); return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
  api("/api/email/task").then(t => {
    const box = $("e_time"), note = $("e_tnote"); if (!box || !note) return;
    if (!t.found) { note.textContent = `${t.reason} The send time can be set here once a scheduled task for the email exists.`; return; }
    box.value = t.time; box.disabled = false; orig = snap(); dirty();
    const when = t.next ? new Date(t.next).toLocaleString("en-US", {weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "";
    note.textContent = !t.enabled ? "The scheduled task is turned off in Windows, so nothing will send on its own."
      : `Goes out at ${clock12(t.time)} on paydays.${when ? ` Next send: ${when}.` : ""} If the PC is asleep then, it sends when it wakes.`;
  }).catch(() => { const note = $("e_tnote"); if (note) note.textContent = "Could not check Task Scheduler."; });
  $("e_save").onclick = () => api("/api/email/save", form()).then(r => { toast(r.message); return loadEmail(); }).catch(fail);

  const testBody = () => ({period: $("e_per").value, hide: thide.get(), season: $("e_season").value, to: $("e_tto").value});
  $("e_prev").onclick = () => { $("e_prev").disabled = true; api("/api/email/preview", testBody()).then(r => { $("e_prev").disabled = false; if (!r.ok) return fail(new Error(r.error));
    $("pvframe").srcdoc = r.html; $("dlg3").showModal(); }).catch(e => { $("e_prev").disabled = false; fail(e); }); };
  $("e_test").onclick = () => { if (!$("e_tto").value.trim()) return toast("Add an address to send the test to.", true); $("e_test").disabled = true;
    api("/api/email/test", testBody()).then(r => { $("e_test").disabled = false; toast(r.message); }).catch(e => { $("e_test").disabled = false; fail(e); }); };
  $("e_send").onclick = () => confirmSend(s.to, E.periods.find(p => p.start === E.current)?.label || "").then(ok => { if (!ok) return;
    api("/api/email/send", {}).then(r => { toast(r.message); return loadEmail(); }).catch(fail); });
}

// "Send this paycheck's summary now?": real inboxes, can't be unsent, so it asks first
function confirmSend(addrs, label) {
  return new Promise(res => {
    const f = $("dform");
    f.innerHTML = `<h3>Send this paycheck's summary now?</h3><p>This emails the <b>${esc(label)}</b> summary to:</p><ul>${addrs.map(a => `<li>${esc(a)}</li>`).join("")}</ul><div class="warn">It goes to real inboxes and can't be unsent.</div>
      <div class="dbtn"><button class="b" value="cancel" formnovalidate>Cancel</button><button class="b pri" value="ok">Send now</button></div>`;
    const d = $("dlg2"); d.onclose = () => res(d.returnValue === "ok"); d.returnValue = ""; d.showModal();
  });
}
