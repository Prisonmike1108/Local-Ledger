"use strict";
// the what-if math: each paycheck you apply it to gives its own share (sa% to savings, sd% to debt) of its own extra; `after` is the running
// rollover once those shares are taken out. Instead of a percentage, savings or debt can be a fixed dollar amount per paycheck
// (saAmt / sdAmt; null or undefined means "use the %"): a paycheck whose extra is smaller than the amount gives all of its extra. Savings comes
// first, so debt only gets what savings leaves of that paycheck's extra. Its own file so it can be tested without the page (tests/test_forecast.js).
function shares(inV, pos, used, sa, sd, saAmt, sdAmt) {
  const fixed = v => v != null && v !== "" && isFinite(v);
  const alloc = pos.map((p, i) => !used(inV[i]) ? 0 : fixed(saAmt) ? Math.min(Math.max(+saAmt, 0), p) : p * sa / 100);
  const dpay = pos.map((p, i) => !used(inV[i]) ? 0 : Math.min(fixed(sdAmt) ? Math.max(+sdAmt, 0) : p * sd / 100, Math.max(p - alloc[i], 0)));
  let cum = 0; const after = inV.map((r, i) => { cum += alloc[i] + dpay[i]; return r.av2 - cum; });
  return {alloc, dpay, after};
}
