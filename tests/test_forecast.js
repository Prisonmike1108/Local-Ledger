// Tests for the Cash Forecast what-if math. Run with: node tests/test_forecast.js
"use strict";
const fs = require("fs"), vm = require("vm"), path = require("path"), assert = require("assert");
const code = fs.readFileSync(path.join(__dirname, "..", "ledger_html", "static", "whatif.js"), "utf8");  // the math lives in its own file, so no page is needed
const out = {};
vm.runInNewContext(code + "\n__out.shares = shares;", {__out: out});
const {shares} = out;
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: expected ${b}, got ${a}`);

// three paychecks: extras 500, 1000, 250; rollover after each (before any set-aside) 400, 1400, 1650
const inV = [{av2: 400}, {av2: 1400}, {av2: 1650}], pos = [500, 1000, 250];
const all = () => true;

{ const r = shares(inV, pos, all, 40, 30);  // every paycheck gives its own share
  [200, 400, 100].forEach((v, i) => near(r.alloc[i], v, "savings share " + i));
  [150, 300, 75].forEach((v, i) => near(r.dpay[i], v, "debt share " + i));
  [50, 350, 425].forEach((v, i) => near(r.after[i], v, "rollover after " + i)); }  // 400-350, 1400-1050, 1650-1225

{ const r = shares(inV, pos, x => x === inV[1], 40, 30);  // only the second paycheck: the others give nothing
  near(r.alloc[0], 0, "unticked paycheck gives no savings"); near(r.alloc[1], 400, "ticked paycheck's own share"); near(r.alloc[2], 0, "unticked paycheck gives no savings");
  near(r.dpay[1], 300, "ticked paycheck's debt share");
  near(r.after[0], 400, "rollover before the ticked paycheck is untouched"); near(r.after[1], 1400 - 700, "rollover after the ticked paycheck"); near(r.after[2], 1650 - 700, "the cut carries into later paychecks"); }

{ const r = shares(inV, pos, () => false, 40, 30);  // nothing ticked: nothing set aside
  assert.deepStrictEqual(r.alloc, [0, 0, 0]); assert.deepStrictEqual(r.dpay, [0, 0, 0]); assert.deepStrictEqual(r.after, [400, 1400, 1650]); }

{ const r = shares(inV, [500, 0, 250], all, 100, 0);  // a paycheck with no extra gives nothing, even at 100%
  near(r.alloc[1], 0, "no extra, no share"); near(r.alloc[0] + r.alloc[2], 750, "full shares of the others"); }

{ const r = shares(inV, pos, all, 0, 0);  // sliders at zero leave the rollover exactly as it was
  assert.deepStrictEqual(r.after, [400, 1400, 1650]); }

{ const r = shares(inV, pos, all, 0, 0, 300, null);  // a fixed $300 to savings: a paycheck with less extra gives all it has
  [300, 300, 250].forEach((v, i) => near(r.alloc[i], v, "fixed savings " + i));
  [100, 800, 800].forEach((v, i) => near(r.after[i], v, "rollover after fixed savings " + i)); }  // 400-300, 1400-600, 1650-850

{ const r = shares(inV, pos, all, 0, 0, null, 200);  // a fixed $200 to debt
  [200, 200, 200].forEach((v, i) => near(r.dpay[i], v, "fixed debt " + i)); }

{ const r = shares(inV, pos, all, 0, 0, 400, 400);  // savings goes first; debt gets only what is left of each extra
  [400, 400, 250].forEach((v, i) => near(r.alloc[i], v, "savings first " + i));
  [100, 400, 0].forEach((v, i) => near(r.dpay[i], v, "debt gets what is left " + i)); }

{ const r = shares(inV, pos, all, 80, 50, null, null);  // percentages that add past 100 never take more than the extra
  pos.forEach((p, i) => assert.ok(r.alloc[i] + r.dpay[i] <= p + 1e-9, "never more than the extra " + i)); }

{ const r = shares(inV, pos, x => x === inV[1], 0, 0, 300, 100);  // fixed amounts only on the ticked paychecks
  near(r.alloc[0], 0, "unticked gives nothing"); near(r.alloc[1], 300, "ticked fixed savings"); near(r.dpay[1], 100, "ticked fixed debt"); near(r.alloc[2], 0, "unticked gives nothing"); }

{ const r = shares(inV, pos, all, 40, 30, "", undefined);  // an empty box means "use the percentage"
  near(r.alloc[0], 200, "blank savings amount falls back to the %"); near(r.dpay[0], 150, "undefined debt amount falls back to the %"); }

console.log("test_forecast.js: all checks passed");
