"use strict";
// Click a column heading to sort any table in the ledger; click again to flip it, a third time to put it back.
// Numbers ($1,234.50, 45%), dates (Nov 12, 2026-11-12, "Nov 10 – Nov 23, 2026") and words each sort the way you'd expect,
// and empty cells ("—") always go last. The Transactions table sorts through app.js instead, because it only draws the
// newest 600 rows and has to sort all of them. Tables you can edit (class "ed") sort as a view only: any redraw (Add a row,
// a move arrow, a save) puts them back in their real order, so the order arrows and row numbers never disagree.
(function () {
  const MONTHS = {jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11};
  const MISSING = new Set(["", "—", "-", "–"]);
  const saved = new Map();  // table key -> {col, dir}: read-only tables keep their sort when the page redraws them
  const clean = s => s.replace(/\s+/g, " ").trim();

  function cellText(td) {
    if (!td) return "";
    if (td.dataset && td.dataset.sort != null) return clean(td.dataset.sort);  // a cell can say what to sort by (like a bar cell with a number and a note)
    const f = td.querySelector("input,select,textarea");
    if (f) {
      if (f.type === "checkbox") return f.checked ? "1" : "0";
      if (f.tagName === "SELECT") return clean(f.selectedOptions[0] ? f.selectedOptions[0].textContent : "");
      return clean(f.value || "");
    }
    return clean(td.textContent);
  }
  function numberOf(t) {
    let s = t.replace(/[,$\s%]/g, "").replace(/[−–]/g, "-"), sign = 1;
    if (s[0] === "▼") { sign = -1; s = s.slice(1); } else if (s[0] === "▲") s = s.slice(1);
    const p = /^\((.*)\)$/.exec(s); if (p) { s = p[1]; sign = -sign; }
    return /^[+-]?\d+(\.\d+)?$/.test(s) ? sign * parseFloat(s) : null;
  }
  // a date from text, or null. Without a year, the year runs on from the rows above (Dec then Jan means a new year).
  function dateOf(t, ctx) {
    let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t);
    if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3]);
    m = /^([A-Za-z]{3})[a-z]*\.?\s+(\d{4})$/.exec(t);  // "Nov 2026"
    if (m && MONTHS[m[1].toLowerCase()] != null) return Date.UTC(+m[2], MONTHS[m[1].toLowerCase()], 1);
    const found = [...t.matchAll(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?!\d)(?:,?\s+(\d{4}))?/gi)];
    if (!found.length) return null;
    const first = found[0], last = found[found.length - 1], mo = MONTHS[first[1].toLowerCase()], day = +first[2];
    const given = first[3] || (/\b(20\d{2})\b/.exec(t) || [])[1];
    let year;
    if (given) { year = +given; if (!first[3] && found.length > 1 && mo > MONTHS[last[1].toLowerCase()]) year -= 1; }  // "Dec 22 – Jan 04, 2027": the year belongs to the end
    else { if (ctx.last != null && mo < ctx.last) ctx.year += 1; ctx.last = mo; year = ctx.year; }
    return Date.UTC(year, mo, day);
  }
  const headerRow = table => [...table.rows].find(r => r.querySelector("th"));
  const isPinned = r => r.classList.contains("tot") || [...r.cells].some(c => c.colSpan > 1);  // totals and notes stay at the bottom
  const keyOf = (table, ths) => ((table.closest("[id]") || {}).id || "") + "|" + ths.map(t => clean(t.textContent)).join("|");

  function applySort(table, col, dir) {
    const header = headerRow(table), body = header.parentNode;
    const rows = [...table.rows].filter(r => r !== header && r.parentNode === body);
    rows.forEach((r, i) => { if (r._o == null) r._o = i; });
    const data = rows.filter(r => !isPinned(r)), pinned = rows.filter(isPinned);
    const orig = data.slice().sort((a, b) => a._o - b._o);
    const texts = new Map(orig.map(r => [r, cellText(r.cells[col])]));
    const present = orig.filter(r => !MISSING.has(texts.get(r)));
    const keys = new Map();
    if (present.length && present.every(r => numberOf(texts.get(r)) !== null)) orig.forEach(r => keys.set(r, MISSING.has(texts.get(r)) ? null : numberOf(texts.get(r))));
    else {
      const ctx = {year: new Date().getFullYear(), last: null}, dates = new Map();
      present.forEach(r => dates.set(r, dateOf(texts.get(r), ctx)));
      if (present.length && [...dates.values()].every(v => v !== null)) orig.forEach(r => keys.set(r, dates.has(r) ? dates.get(r) : null));
      else orig.forEach(r => keys.set(r, MISSING.has(texts.get(r)) ? null : texts.get(r)));
    }
    data.sort((a, b) => {
      if (!dir) return a._o - b._o;
      const ka = keys.get(a), kb = keys.get(b);
      if (ka == null || kb == null) return ka == null && kb == null ? a._o - b._o : ka == null ? 1 : -1;  // empty cells last, whichever way it sorts
      const c = typeof ka === "number" ? ka - kb : String(ka).localeCompare(String(kb), undefined, {numeric: true, sensitivity: "base"});
      return c * dir || a._o - b._o;
    });
    body.append(...data, ...pinned.sort((a, b) => a._o - b._o));
  }

  let observer, timer;
  const watch = () => observer.observe(document.body, {childList: true, subtree: true});
  const quietly = fn => { observer.disconnect(); try { fn(); } finally { watch(); } };

  function decorate(table) {
    if (table.hasAttribute("data-nosort") || table.id === "ttab") return;
    const header = headerRow(table); if (!header) return;
    const ths = [...header.cells];
    if (!ths.some(th => !th.hasAttribute("data-sortable"))) return;  // already done: this table hasn't been redrawn
    ths.forEach(th => {
      const ok = !th.classList.contains("x") && clean(th.textContent) !== "" && !th.querySelector("input,button,select");
      th.setAttribute("data-sortable", ok ? "1" : "0");
      if (ok) { th.tabIndex = 0; th.title = th.title || "Click to sort"; }
    });
    [...table.rows].forEach((r, i) => { if (r !== header && r._o == null) r._o = i; });
    if (table.classList.contains("ed")) return;  // editable: always starts in its real order
    const s = saved.get(keyOf(table, ths));
    if (s && s.col < ths.length && ths[s.col].getAttribute("data-sortable") === "1") {
      applySort(table, s.col, s.dir);
      ths[s.col].setAttribute("aria-sort", s.dir === 1 ? "ascending" : "descending");
    }
  }
  function scan() { quietly(() => document.querySelectorAll("table").forEach(decorate)); }

  function sortBy(th) {
    const table = th.closest("table"), ths = [...th.parentNode.cells], col = ths.indexOf(th);
    const cur = th.getAttribute("aria-sort"), dir = cur === "ascending" ? -1 : cur === "descending" ? 0 : 1;
    quietly(() => {
      ths.forEach(x => x.removeAttribute("aria-sort"));
      if (dir) th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      applySort(table, col, dir);
    });
    if (!table.classList.contains("ed")) { const k = keyOf(table, ths); dir ? saved.set(k, {col, dir}) : saved.delete(k); }
  }
  document.addEventListener("click", e => { const th = e.target.closest('th[data-sortable="1"]'); if (th) sortBy(th); });
  document.addEventListener("keydown", e => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches('th[data-sortable="1"]')) { e.preventDefault(); sortBy(e.target); } });

  observer = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(scan, 30); });
  scan(); watch();
})();
