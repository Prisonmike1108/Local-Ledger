"""Personal Finance Ledger: a Python script that serves its own page and reuses the numbers logic
in FinanceDashboard.py, so both apps agree. It reads and writes the same files in finance_data; before any file is
changed it saves a timestamped copy in finance_data/backups, and "Undo" puts the last one back.

    python ledger_html/server.py          # then open http://127.0.0.1:8600
    python ledger_html/server.py --open   # same, and opens the browser

Environment: FINANCE_DATA_DIR points it at another data folder (for example finance_data_test).
"""
import hashlib
import hmac
import ipaddress
import json
import math
import re
import secrets
import shutil
import socket
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import FinanceDashboard as fd  # noqa: E402  (the shared logic: bill status, rollover, savings, categorising, themes)

import os  # noqa: E402

PORT = int(os.environ.get("LEDGER_PORT", 8600))  # a second copy (for testing) can use another port
BACKUPS = fd.DATA_DIR / "backups"
JOURNAL: list[tuple[int, str, Path]] = []  # (change number, data file, its backup) for this session, newest last
GROUP = [0]  # the number of the change being made; one click can save several files, and Undo puts them all back
import threading  # noqa: E402

LOCK = threading.RLock()  # requests take turns, so two devices never write the same file at once
RESTART = [False]  # set by --watch when a code file changed


# ---------- saving with a backup first ----------
def backup(fname: str) -> None:
    src = fd.DATA_DIR / fname
    if not src.exists():
        return
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dst = BACKUPS / f"{datetime.now():%Y%m%d-%H%M%S-%f}_{fname}"
    shutil.copyfile(src, dst)
    JOURNAL.append((GROUP[0], fname, dst))
    old = sorted(BACKUPS.glob(f"*_{fname}"))[:-40]  # keep the newest 40 per file
    for p in old:
        p.unlink(missing_ok=True)


def save(name: str, df: pd.DataFrame, keep_backup: bool = False) -> None:
    backup(f"{name}.csv")
    fd.save(name, df, keep_backup=keep_backup)


def undo() -> str:
    if not JOURNAL:
        return "Nothing to undo."
    g = JOURNAL[-1][0]
    names = []
    while JOURNAL and JOURNAL[-1][0] == g:  # newest first, so a file saved twice ends up as it was before the change
        _g, fname, bk = JOURNAL.pop()
        shutil.copyfile(bk, (fd.REAL_DIR / fname.replace("@real", "")) if fname.endswith("@real") else fd.DATA_DIR / fname)
        names.append(fname.replace("@real", ""))
    return "Undone: restored " + ", ".join(sorted(set(names))) + "."


# ---------- everything worked out before a screen is drawn ----------
class Ctx:
    def __init__(self):
        self.settings = fd.load_settings()
        self.plan, self.income, self.tx = fd.load("plan"), fd.load("income"), fd.load("transactions")
        self.rules, self.budgets, self.debts = fd.load("rules"), fd.load("budgets"), fd.load("debts")
        self.limits = fd.load("limits")
        self.starts = fd.all_period_starts(self.plan, self.income, fd.load("periods"))
        self.tx["period_start"] = fd.assign_period(self.tx["date"], self.starts)
        self.pinc = fd.load_planned_income(self.income)
        self.pnames = {x.lower() for x in self.pinc["source"]}
        # A spend and a refund or reversal of exactly the same amount cancel out: both are left out of the numbers (the
        # Transactions tab still shows them as they are). `shown` keeps the real amount for that.
        self.voided = fd.reversal_pairs(self.tx, self.pnames)
        self.tx["shown"] = self.tx["amount"]
        self.tx.loc[self.tx["id"].isin(self.voided), "amount"] = 0.0
        self.ep_act = fd.effective_plan(self.plan, self.tx, self.starts, self.budgets, False)
        self.ep_hold = fd.effective_plan(self.plan, self.tx, self.starts, self.budgets, True)
        self.inc_eff = fd.effective_income(self.income, self.tx, self.starts, self.pnames)
        master = (fd.load("recurring") if (fd.DATA_DIR / "recurring.csv").exists()
                  else fd.derive_master(self.plan, set(fd.budget_limits(self.budgets))))
        self.planned_set = {str(i).strip().lower() for i in master["item"]} | set(fd.budget_limits(self.budgets))
        xc = fd.sync_extra_categories(fd.load("extra_categories"), self.tx, self.plan, self.rules, self.planned_set,
                                      self.pnames)
        self.xcats = xc
        flagged = {n.lower() for n, f in zip(xc["name"], xc["one_off"]) if f}
        every = set(self.tx["category"]) | set(self.plan["item"]) | set(xc["name"])
        self.one_off = {str(n).lower() for n in every if str(n).strip()
                        and (str(n).lower() in flagged or fd.cat_group(n).lower() in flagged)}
        self.onetime = fd.open_onetime(fd.load("onetime"), self.tx, self.starts)
        self.ot_match = fd.onetime_matches(self.onetime, self.tx, self.pnames,
                                           self.settings.get("onetime_dismissed", []))
        self.onetime["check"] = self.onetime["open"] & self.onetime["name"].isin(set(self.ot_match.values()))
        # a planned one-time expense counts as an extra in its pay period until the real charge lands; while a probable
        # match is waiting for your answer on the Transactions tab, the real charge counts alone so nothing is counted twice
        planned_ot = self.onetime[self.onetime["open"] & ~self.onetime["check"] & (self.onetime["period_start"] != "")]
        if len(planned_ot):
            inj = pd.DataFrame(dict(period_start=planned_ot["period_start"], item=planned_ot["name"], kind="extra",
                                    due_day=np.nan, amount=planned_ot["amount"]))
            self.ep_act = pd.concat([self.ep_act, inj], ignore_index=True)
            self.ep_hold = pd.concat([self.ep_hold, inj], ignore_index=True)
        self.ctype = lambda n: fd.category_type(n, self.planned_set, self.pnames)
        self.savings_R, _rem, _direct = fd.savings_flow(self.tx, self.starts, self.settings)
        self.opening, self.anchor = fd.reconciled_opening(self.starts, self.ep_hold, self.inc_eff, self.tx, self.pnames,
                                                          self.settings)
        self.summary = fd.period_summary(self.starts, self.ep_hold, self.inc_eff,
                                         {**self.settings, "opening_balance": self.opening, "_setaside": self.savings_R})


def clean(o):
    """JSON-safe: numpy numbers to Python, NaN to None."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and math.isnan(o)) or (isinstance(o, np.floating) and np.isnan(o)) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return o


def real_settings() -> dict:
    """Your look (theme, dark mode) belongs to you, not to a data set, so it always
    lives in your real settings file, even while sample data is on."""
    s = dict(fd.DEFAULT_SETTINGS)
    f = fd.REAL_DIR / "settings.json"
    if f.exists():
        s.update(json.loads(f.read_text()))
    return s


def save_real_settings(upd: dict) -> None:
    f = fd.REAL_DIR / "settings.json"
    if f.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        dst = BACKUPS / f"{datetime.now():%Y%m%d-%H%M%S-%f}_settings.json"
        shutil.copyfile(f, dst)
        JOURNAL.append((GROUP[0], "settings.json@real", dst))
    f.write_text(json.dumps({**real_settings(), **upd}))


def set_data_dir(test: bool) -> None:
    """Switch every request between your real data and the made-up sample folder."""
    global BACKUPS
    fd.DATA_DIR = fd.TEST_DIR if test else fd.REAL_DIR
    if test and not (fd.TEST_DIR / "settings.json").exists():
        fd.seed_test_data(fd.TEST_DIR)
    BACKUPS = fd.DATA_DIR / "backups"
    JOURNAL.clear()


def anim_state() -> dict:
    s = real_settings()
    style = s.get("anim_style") if s.get("anim_style") in fd.ANIM_STYLES else "Prismatic"
    f = fd.ANIM_STYLES[style]
    on = bool(s.get("animations", True))
    bg = s.get("anim_bg") or ("Columns" if f["bg"] else "None")  # "" means the background follows the style
    if bg not in fd.ANIM_BGS and bg != "Columns":
        bg = "None"  # a choice that no longer exists (the old Weather: Auto)
    return dict(on=on, style=style, speed=s.get("anim_speed") if s.get("anim_speed") in fd.ANIM_SPEEDS else "Calm", bg=bg)


def anim_css_html() -> str:
    """The animated background and the card entrance, using the same Python that builds the themes, with its
    page names swapped for this page's (stAppViewContainer is the body, st-key-card_ is a card)."""
    s = real_settings()
    a = anim_state()
    ui = fd.build_ui(s.get("theme"), bool(s.get("dark_mode")))
    f = fd.ANIM_STYLES[a["style"]] if a["on"] else dict(bg=False, ring=False, glare=False, flow=False, enter=False)
    kind = a["bg"] if a["on"] else "None"
    css = [f":root{{--spd:{fd.ANIM_SPEEDS.get(a['speed'], 1.0)}}}"]
    if kind != "None":
        css.append('body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;'
                   '-webkit-mask-image:linear-gradient(to bottom,#000 0%,#000 28%,transparent 80%);'
                   'mask-image:linear-gradient(to bottom,#000 0%,#000 28%,transparent 80%)}')
        if kind == "Columns":
            img, size, start, end, steps = fd.glow_columns_css(ui)
            css.append(f"body::before{{opacity:{ui['glow']};background-image:{img};background-repeat:repeat-y;background-size:{size};"
                       f"background-position:{start};animation:col-flow calc(4.2s * var(--spd)) steps({steps}) infinite}}"
                       f"@keyframes col-flow{{to{{background-position:{end}}}}}")
        else:
            css.append(fd.bg_css(ui, kind).replace('[data-testid="stAppViewContainer"]', "body"))
    if f["enter"]:
        css.append("@keyframes fade-in-up{from{opacity:0;transform:translateY(16px)}}"
                   ".card:not(.soon),.kpi,.hero{animation:fade-in-up 400ms cubic-bezier(.22,1,.36,1) backwards}")
    css.append("@media(prefers-reduced-motion:reduce){body::before,body::after,.card,.kpi,.hero{animation:none!important}}")
    return "".join(css)


def theme_payload() -> dict:
    s = real_settings()
    ui = fd.build_ui(s.get("theme"), bool(s.get("dark_mode")))
    return dict(ui={k: v for k, v in ui.items() if isinstance(v, (str, int, float, bool, list, dict))},
                sem=fd.semantic_colors(ui), status=fd.status_palette(ui), dark=bool(ui["dark_mode"]),
                themes=[dict(key=k, name=v["name"]) for k, v in fd.THEMES.items()], theme=s.get("theme"),
                test_mode=fd.DATA_DIR != fd.REAL_DIR,
                anim=anim_state(), anim_opts=dict(styles=list(fd.ANIM_STYLES), backgrounds=list(fd.ANIM_BGS), speeds=list(fd.ANIM_SPEEDS)))


def cat_groups(c: Ctx, cats: list) -> dict:
    """Which group each category goes under in the category dropdowns: Bills, Budgets, Limits, Income, Savings or Extras."""
    bud, lim = set(fd.budget_limits(c.budgets)), {str(x).strip().lower() for x in c.limits["category"]}
    out = {}
    for n in cats:
        low = str(n).strip().lower()
        t = c.ctype(n)
        out[n] = ("Budgets" if low in bud else "Limits" if low in lim else "Bills" if t == "Planned" else "Income" if t == "Income"
                  else "Savings" if t == "Savings" else "Extras")
    return out


def app_version() -> str:
    """The date this copy of the app is up to date as of (the VERSION file that comes with each update), or '' if there isn't one."""
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()[:10]
    except OSError:
        return ""


def meta(c: Ctx) -> dict:
    cur = fd.current_period(c.starts) if c.starts else ""
    cats = fd.known_categories(c.rules, c.plan, c.budgets, c.income, c.tx)
    newest = pd.to_datetime(c.tx["date"], errors="coerce").max() if not c.tx.empty else pd.NaT
    days_old = (date.today() - newest.date()).days if pd.notna(newest) else None
    prompt = (fd.DATA_DIR == fd.REAL_DIR and (days_old is None or days_old >= 2)
              and c.settings.get("import_prompt_snoozed") != date.today().isoformat())
    rs = real_settings()  # read the local settings file once
    return dict(today=date.today().isoformat(), current=cur, test_mode=fd.DATA_DIR != fd.REAL_DIR,
                import_prompt=dict(show=bool(prompt), days_old=days_old, newest=None if pd.isna(newest) else newest.strftime("%a %b %d")),
                periods=[dict(start=s, label=fd.label(s)) for s in c.starts], categories=sorted(cats, key=str.lower),
                data_dir=str(fd.DATA_DIR), category_groups=cat_groups(c, cats), app_name=(rs.get("app_name") or "").strip(), lan=lan_state(), name_asked=bool(rs.get("name_asked") or (rs.get("app_name") or "").strip()), dev_reload=bool(rs.get("dev_reload")), hide_budget_mode=bool(rs.get("hide_budget_mode")), can_undo=bool(JOURNAL), theme_name=c.settings.get("theme"),
                period_mode=fd.period_mode(), period_day=fd.layout_at(date.today())["day"], email_enabled=EM_SCRIPT.exists(),
                needs_setup=not c.starts, version=app_version())  # a brand-new install: no pay periods yet, so the page offers first-run setup


def payback_links(c: Ctx, period: str) -> list:
    """Deposits you've said pay back an expense (a brother's order on your card, a friend's share), for one pay period."""
    out = []
    for s in c.settings.get("paybacks", []):
        tid, _, item = str(s).partition("|")
        r = c.tx[(c.tx["id"] == tid) & (c.tx["period_start"] == period) & (c.tx["amount"] > 0)]
        if len(r):
            out.append(dict(tx_id=tid, item=item, amount=float(r["amount"].iloc[0]), income=str(r["category"].iloc[0]), date=str(r["date"].iloc[0])))
    return out


def payback_info(c: Ctx, xt: pd.DataFrame, period: str) -> dict:
    """What the Extras card needs to show paybacks: per expense, how much was paid back (never more than was spent);
    the total; and deposits that look like a payback you haven't linked yet (close in amount to one expense).
    Only this card changes. Income, Left and Safe to spend already count both sides, so they stay as they are."""
    now = {x.key: float(x.now) for x in xt.itertuples()}
    links = payback_links(c, period)
    back: dict = {}
    by_item: dict = {}
    for L in links:
        k = L["item"].strip().lower()
        if k in now:
            back[k] = back.get(k, 0.0) + L["amount"]
            by_item.setdefault(k, []).append(L)
    back = {k: min(v, now[k]) for k, v in back.items()}
    t = c.tx[(c.tx["period_start"] == period) & (c.tx["amount"] > 0)]
    cat = t["category"].str.lower()
    mv = set(c.settings.get("savings_moved") or [])
    t = t[cat.str.contains("income") & ~cat.isin(c.pnames) & ~fd.savings_mask(t["category"]) & ~t["id"].isin(mv)]
    linked = {L["tx_id"] for L in links}
    gone = {str(x).lower() for x in c.settings.get("dismissed_paybacks", [])}
    names = {x.key: x.item for x in xt.itertuples()}
    suggest = []
    for d in t.itertuples():
        if d.id in linked:
            continue
        near = [(abs(v - d.amount), k) for k, v in now.items() if v > 0 and abs(v - d.amount) <= max(20.0, 0.10 * v)
                and back.get(k, 0.0) < 0.5 * v and f"{d.id}|{k}" not in gone]
        if near:
            k = min(near)[1]
            suggest.append(dict(tx_id=d.id, income=d.category, amount=float(d.amount), date=d.date, item=names[k], key=k, now=now[k]))
    return dict(back=back, links=by_item, total=float(sum(back.values())), suggest=suggest[:2])


def income_lines(c: Ctx, period: str) -> list:
    """The income table on the Overview: each planned paycheck (the amount on the Plan tab, kept per pay period) against
    what actually landed, how it compares with the plan and with last paycheck, then the extra income deposits."""
    ended = fd.period_end(date.fromisoformat(period)) < date.today()
    prev = max((s for s in c.starts if s < period), default=None)
    ie = c.inc_eff
    pv = ie[ie.period_start == prev] if prev else ie.iloc[0:0]
    last_of = lambda src: float(pv.loc[pv["source"].str.lower() == src.lower(), "amount"].sum()) if len(pv) and (pv["source"].str.lower() == src.lower()).any() else None
    got = fd.paycheck_actuals(c.tx, c.starts, c.pnames)
    got = dict(zip(got.loc[got.period_start == period, "key"], got.loc[got.period_start == period, "amount"]))
    stored = c.income[(c.income.period_start == period) & c.income["source"].str.lower().isin(c.pnames)]
    plan_rows = (stored.groupby("source", as_index=False, sort=False)["amount"].sum() if len(stored) else c.pinc[["source", "amount"]])
    out = []
    for r in plan_rows.itertuples():
        a = got.get(r.source.lower())
        state, word = (("paid", "Received") if a is not None else ("overdue", "Not received") if ended else ("neutral", "Expected"))
        out.append(dict(item=r.source, type="Paycheck", planned=float(r.amount), actual=None if a is None else float(a), state=state, status=word,
                        vs_plan=None if a is None else float(a - r.amount),
                        vs_last=None if a is None or last_of(r.source) is None else float(a - last_of(r.source))))
    xi = ie[(ie.period_start == period) & (ie.kind == "extra")].groupby("source", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    pays = {}
    for L in payback_links(c, period):
        pays.setdefault(L["income"].lower(), []).append(L["item"])
    for r in xi.itertuples():
        lo = last_of(r.source)
        out.append(dict(item=r.source, type="Extra", planned=None, actual=float(r.amount), state="paid", status="Received", vs_plan=None,
                        vs_last=None if lo is None else float(r.amount - lo),
                        note="pays back " + ", ".join(pays[r.source.lower()]) if r.source.lower() in pays else ""))
    return out


def overview(c: Ctx, period: str) -> dict:
    today = date.today()
    p_start = date.fromisoformat(period)
    row = lambda df: df[df.period_start == period].iloc[0]
    r = row(c.summary)
    b_hold = float(c.ep_hold[(c.ep_hold.period_start == period) & (c.ep_hold.kind == "budget")]["amount"].sum())
    b_act = float(c.ep_act[(c.ep_act.period_start == period) & (c.ep_act.kind == "budget")]["amount"].sum())
    unspent_b = max(b_hold - b_act, 0.0)
    eplan_a = pd.concat([c.ep_hold[c.ep_hold.period_start != period], c.ep_act[c.ep_act.period_start == period]],
                        ignore_index=True)
    summary_a = fd.period_summary(c.starts, eplan_a, c.inc_eff,
                                  {**c.settings, "opening_balance": c.opening, "_setaside": c.savings_R})
    r_a = row(summary_a)
    eplan = c.ep_hold
    cur = eplan[(eplan.period_start == period) & (eplan.amount > 0)].copy()
    prev = [s for s in c.starts if s < period]
    pv = eplan.pivot_table(index="item", columns="period_start", values="amount", aggfunc="sum")

    def vs_last(rw):
        if rw["item"] not in pv.index:
            return None
        for s in reversed(prev):
            v = pv.at[rw["item"], s] if s in pv.columns else np.nan
            if pd.notna(v) and v > 0:
                return float(rw["amount"] - v)
        return None

    cur["vs_last"] = cur.apply(vs_last, axis=1) if len(cur) else None
    bl = fd.budget_limits(c.budgets)
    cur["type"] = np.where(cur["kind"] == "extra", "Extra",
                           np.where(cur["item"].str.lower().isin(set(bl)), "Budget", "Scheduled"))
    cur["order"] = cur["kind"].map({k: i for i, k in enumerate(fd.KINDS)})
    cur = cur.sort_values(["order", "due_day", "amount"], ascending=[True, True, False])
    sched = cur[cur["kind"] != "extra"]
    marks = fd.load("paid_marks")
    marked = set(marks.loc[marks["period_start"] == period, "item"].str.lower())
    stat = fd.bill_status(period, sched, c.tx, c.starts, {k: v[1] for k, v in bl.items()}, marked=marked)
    bills = stat[sched["type"] == "Scheduled"]
    paid_idx = bills.index[bills["state"] == "paid"]
    todo_idx = bills.index.difference(paid_idx)
    lines = []
    for i in sched.index:
        t = sched.loc[i]
        is_b = t["type"] == "Budget"
        lines.append(dict(item=t["item"], type=t["type"], due_day=t["due_day"], planned=float(t["amount"]),
                          actual=stat.loc[i, "actual"], state=stat.loc[i, "state"], status=stat.loc[i, "status"],
                          used=(float(np.nan_to_num(stat.loc[i, "actual"])) / float(t["amount"]) * 100
                                if is_b and t["amount"] else None), vs_last=t["vs_last"],
                          paid_other=bool(t["item"].lower() in marked)))
    chips = []
    for i in bills.index:
        dd = sched.loc[i, "due_day"]
        if pd.isna(dd):
            continue
        d_ = fd.occurrence(period, dd)
        chips.append(dict(date=(d_ or p_start).isoformat(), item=sched.loc[i, "item"], amount=float(sched.loc[i, "amount"]),
                          state=stat.loc[i, "state"], status=stat.loc[i, "status"]))
    chips.sort(key=lambda x: x["date"])
    n_over = int((bills["state"] == "overdue").sum())
    in_p = eplan[eplan.period_start == period]
    funds = float(r.available - r.income + r.expenses) + float(r.income)
    parts = [dict(name="Bills paid", amount=float(sched.loc[paid_idx, "amount"].sum()), kind="Scheduled"),
             dict(name="Bills to pay", amount=float(sched.loc[todo_idx, "amount"].sum()), kind="Scheduled"),
             dict(name="Budgets", amount=float(sched.loc[sched["type"] == "Budget", "amount"].sum()), kind="Budget"),
             dict(name="Extras", amount=float(in_p.loc[in_p.kind == "extra", "amount"].sum()), kind="Extra")]
    bill_names = {str(n).lower() for n in sched.loc[bills.index, "item"]}
    txp = c.tx[c.tx["period_start"] == period]
    cat_l = txp["category"].str.lower()
    out_tx = txp[(txp["amount"] < 0) & ~fd.savings_mask(txp["category"]) & ~cat_l.str.contains("income")].copy()
    ocat = out_tx["category"].str.lower()
    # each day's spending split three ways, the same kinds as the rest of the Overview: bills paid (scheduled), budget categories, and extras
    out_tx["kind"] = np.where(ocat.isin(bill_names), "sched", np.where(ocat.isin(set(bl)), "budget", "extra"))
    out_tx["day"] = out_tx["date"].astype(str).str[:10]
    by_day = (-out_tx.groupby(["day", "kind"])["amount"].sum()).to_dict()
    daily = []
    for n in range(fd.period_days(period)):
        d_ = p_start + timedelta(days=n)
        k = lambda kind: float(by_day.get((d_.isoformat(), kind), 0.0))
        daily.append(dict(date=d_.isoformat(), sched=k("sched"), budget=k("budget"), extra=k("extra"), spent=k("budget") + k("extra"),
                          today=d_ == today, future=d_ > today))  # `spent` stays the everyday total (budgets + extras), bills are shown apart
    # extras this paycheck
    xt, typical_x, n_x = fd.extras_insight(eplan, c.starts, period, one_off=c.one_off)
    spent_x = float(xt["now"].sum())
    spare = spent_x + float(r.net)
    pb = payback_info(c, xt, period)
    extras = [dict(item=x.item, now=float(x.now), typical=float(x.typical), times=int(x.times), when_spent=float(x.when_spent),
                   back=pb["back"].get(x.key, 0.0), links=pb["links"].get(x.key, []))
              for x in xt[xt["now"] > 0].sort_values("now", ascending=False).itertuples()]
    # where the money went
    _inc_a, spend_a = fd.actuals(txp)
    lim = {k: v[1] for k, v in bl.items()}
    sched_names = {n.lower() for n in cur.loc[cur["kind"] != "extra", "item"]}
    went = []
    for name, amt in spend_a.items():
        if amt > 0:
            k = name.lower()
            went.append(dict(category=name, actual=float(amt), budget=lim.get(k),
                             type="Budget" if k in lim else "Scheduled" if k in sched_names else "Extra"))
    went.sort(key=lambda x: -x["actual"])
    # spending limits: a yardstick for a category (like Gas), shown in the same table as bills and budgets. Unlike a budget
    # it sets no money aside, so nothing here touches Safe to spend; the spending itself still counts as an Extra.
    spent_l = {str(k).lower(): float(v) for k, v in spend_a.items()}
    taken = {str(i).lower() for i in cur.loc[cur["kind"] != "extra", "item"]}  # a bill or budget of the same name wins
    for k, (nm, cap) in fd.budget_limits(c.limits).items():
        if k in taken:
            continue
        spent = spent_l.get(k, 0.0)
        pct = spent / cap * 100
        state = "over" if pct > 100 else "warn" if pct >= 80 else "ok"
        status = f"Over by {fd.money(spent - cap)}" if pct > 100 else f"{pct:.0f}% of limit used"
        lines.append(dict(item=nm, type="Limit", due_day=None, planned=cap, actual=spent, state=state, status=status,
                          used=pct, vs_last=None, paid_other=False))
    twins, ideas = twin_and_ideas(c, xt, cur, bl, n_x)
    left_help = "Rollover + income - bills - full budgets - extras."
    return dict(
        period=period, label=fd.label(period), start=period, end=fd.period_end(p_start).isoformat(), days=fd.period_days(period), mode=fd.period_mode(p_start),
        today=today.isoformat(), safe=float(r.available), held=unspent_b, funds=funds, parts=parts, daily=daily,
        chips=chips, tally=dict(paid=len(paid_idx), total=len(bills), still=float(sched.loc[todo_idx, "amount"].sum()),
                                overdue=n_over),
        kpis=dict(income=float(r.income), expenses=float(r_a.expenses), left=float(r_a.available)),
        lines=lines, income_lines=income_lines(c, period), extras=extras, twins=twins, ideas=ideas, extras_spare=spare - pb["total"], extras_spent=spent_x - pb["total"], extras_back=pb["total"], paybacks=pb["suggest"], went=went[:15], left_help=left_help,
        marks_options=[l["item"] for l in lines if l["type"] == "Scheduled" and l["state"] != "paid" or l["paid_other"]])


def transactions(c: Ctx) -> list:
    t = c.tx.copy()
    rows = []
    moved = set(c.settings.get("savings_moved") or [])
    ok = set(_savings_eligible(c, list(t["id"]))["id"])
    for r in t.itertuples():
        rows.append(dict(id=r.id, date=r.date, description=r.description, amount=float(r.shown), category=r.category, reversed=r.id in c.voided,
                         pending=bool(r.pending), period=r.period_start, type=c.ctype(r.category) if r.category else "Uncategorized",
                         moved=r.id in moved, can_save=r.id in ok, ot_match=c.ot_match.get(r.id, "")))
    return rows


# ---------- editing ----------
def tx_delete(ids: list) -> int:
    tx = fd.load("transactions")
    n = int(tx["id"].isin(ids).sum())
    save("transactions", tx[~tx["id"].isin(ids)])
    return n


def tx_category(ids: list, category: str) -> int:
    tx = fd.load("transactions")
    full, n = fd.apply_bulk_category(tx, set(ids), category)
    save("transactions", full)
    return int(n)


def tx_add(row: dict) -> str:
    tx = fd.load("transactions")
    day = pd.to_datetime(str(row["date"]), errors="coerce")
    if pd.isna(day):
        raise ValueError("That date doesn't look right.")
    new = pd.DataFrame([dict(id="", date=day.strftime("%Y-%m-%d"), description=str(row.get("description", "")).strip(),
                             amount=float(row["amount"]), category=str(row.get("category", "")).strip(), pending=False)])
    new["id"] = "m-" + fd.make_ids(new)  # "m-" marks a hand-entered row: the bank balance doesn't have it yet, so it reduces what's left
    save("transactions", pd.concat([tx, new], ignore_index=True))
    return new["id"].iloc[0]


def category_suggest(tid: str) -> dict:
    """What the new-category box needs about a transaction: its text, a short keyword for a rule, its day and month."""
    c = Ctx()
    t = c.tx[c.tx["id"] == tid]
    if t.empty:
        raise ValueError("Transaction not found.")
    r = t.iloc[0]
    return dict(desc=str(r["description"]), keyword=fd.description_keyword(str(r["description"])), date=str(r["date"])[:10],
                amount=abs(float(r["amount"])), bank=not str(tid).startswith("m-"))


def keyword_matches(kw: str) -> dict:
    c = Ctx()
    hit = c.tx["description"].str.upper().str.contains(kw.upper(), regex=False) if kw.strip() else pd.Series(False, index=c.tx.index)
    return dict(n=int(hit.sum()), uncategorized=int((hit & (c.tx["category"] == "")).sum()))


def learn_info(ids: list, category: str) -> dict:
    """After bank transactions were filed under an existing category by hand: should the page offer to remember it as a rule?
    Only when they are all the same merchant (one keyword) and no rule already covers that merchant. It sets nothing."""
    c = Ctx()
    category = str(category or "").strip()
    t = c.tx[c.tx["id"].isin(ids) & ~c.tx["id"].astype(str).str.startswith("m-")]  # hand-entered ones have no bank text to learn from
    t = t[t["category"].astype(str).str.strip().str.lower() == category.lower()] if category else t.iloc[0:0]  # only if it really is filed there
    if t.empty:
        return dict(ask=False)
    kws = {fd.description_keyword(str(d)) for d in t["description"]}
    if len(kws) != 1 or not (kw := next(iter(kws))):
        return dict(ask=False)
    rules = [str(k).strip().upper() for k in c.rules["keyword"] if str(k).strip()]
    if any(r in str(d).upper() for d in t["description"] for r in rules):  # a rule already covers it: nothing new to learn
        return dict(ask=False)
    m = keyword_matches(kw)
    return dict(ask=True, keyword=kw, desc=str(t.iloc[0]["description"]), n=m["n"], uncategorized=m["uncategorized"])


def rule_add(b: dict) -> str:
    """Remember 'description contains <keyword>' as a rule for <category>, then file every uncategorized transaction it matches.
    Transactions that already have a category are never changed."""
    kw, cat = str(b.get("keyword", "")).strip(), str(b.get("category", "")).strip()
    if not cat:
        raise ValueError("Pick a category.")
    if len(kw) < 3:
        raise ValueError("Use at least 3 characters, so the rule doesn't catch too much.")
    c = Ctx()
    cat = {x.lower(): x for x in fd.known_categories(c.rules, c.plan, c.budgets, c.income, c.tx)}.get(cat.lower(), cat)
    rules = c.rules
    dup = ((rules["keyword"].str.strip().str.upper() == kw.upper()) & (rules["category"].str.lower() == cat.lower())).any()
    r2 = rules if dup else pd.concat([rules, pd.DataFrame([dict(keyword=kw, category=cat)])], ignore_index=True)
    if not dup:
        save("rules", r2)
    t2, n_more = fd.categorize(fd.load("transactions")[fd.SCHEMAS["transactions"]], r2)
    if n_more:
        save("transactions", t2)
    return f"Remembered: {kw} \u2192 {cat}." + (f" Filed {n_more} more." if n_more else " Future imports will file it automatically.")


def new_category(b: dict) -> str:
    """Put a (maybe brand-new) category on transactions; optionally plan it as a bill or budget and remember a keyword rule."""
    c = Ctx()
    name = str(b["name"]).strip()
    if not name:
        raise ValueError("Give the category a name.")
    canon = {x.lower(): x for x in fd.known_categories(c.rules, c.plan, c.budgets, c.income, c.tx)}
    is_new = name.lower() not in canon
    near = fd.similar_names(name, list(canon.values())) if is_new else []
    name = canon.get(name.lower(), name)
    full, n = fd.apply_bulk_category(fd.load("transactions"), set(b.get("ids", [])), name)
    save("transactions", full)
    notes = [f"Moved {n} transaction{'s' if n != 1 else ''} to {name}."]
    kw = str(b.get("keyword", "")).strip()
    if kw:
        rules = c.rules
        dup = ((rules["keyword"].str.strip().str.upper() == kw.upper()) & (rules["category"].str.lower() == name.lower())).any()
        r2 = rules if dup else pd.concat([rules, pd.DataFrame([dict(keyword=kw, category=name)])], ignore_index=True)
        if not dup:
            save("rules", r2)
        t2, n_more = fd.categorize(fd.load("transactions")[fd.SCHEMAS["transactions"]], r2)
        if n_more:
            save("transactions", t2)
        notes.append(f"Rule saved: {kw} → {name}" + (f" ({n_more} more categorized)." if n_more else "."))
    if is_new and b.get("kind") == "Planned":
        if b.get("how") == "Bill":
            rec_f = fd.DATA_DIR / "recurring.csv"
            m = fd.clean_recurring(fd.load("recurring") if rec_f.exists() else fd.derive_master(c.plan, set(fd.budget_limits(c.budgets))))
            if name.lower() not in set(m["item"].str.lower()):
                month = b.get("month") or np.nan
                new_m = fd.clean_recurring(pd.concat([m, pd.DataFrame([dict(item=name, due_day=int(b.get("due", 1)), amount=float(b.get("amount", 0)),
                                                                            freq=b.get("freq", "Monthly"), month=month)])], ignore_index=True))
                fd.backup_recurring()
                new_plan, _ = fd.sync_recurring(c.plan, new_m, c.starts, date.today(), {}, {name.lower(): date.fromisoformat(fd.current_period(c.starts))})
                save("recurring", new_m)
                save("plan", new_plan, keep_backup=True)
                notes.append(f"Added to Bills & budgets as a {str(b.get('freq', 'Monthly')).lower()} bill due on day {int(b.get('due', 1))}.")
        elif name.lower() not in fd.budget_limits(c.budgets):
            save("budgets", pd.concat([c.budgets, pd.DataFrame([dict(category=name, limit=float(b.get("limit", 0)))])], ignore_index=True))
            notes.append(f"Added to Bills & budgets as a {fd.money(float(b.get('limit', 0)))} budget.")
    elif is_new:
        notes.append("Saved as an Extra.")
    xl = float(b.get("xlimit") or 0)
    if b.get("kind") == "Extra" and xl > 0:  # an optional yardstick for the new extra: shows under/over, holds nothing back
        taken = {str(i).lower() for i in _master(c)["item"]} | set(fd.budget_limits(c.budgets))
        if name.lower() in taken:
            notes.append(f"{name} is already a bill or budget, so a limit wasn't added.")
        else:
            others = c.limits[c.limits["category"].astype(str).str.lower() != name.lower()]
            save("limits", pd.concat([others, pd.DataFrame([dict(category=name, limit=xl)])], ignore_index=True))
            notes.append(f"Limit set: {fd.money(xl)} per paycheck. The Overview shows whether you're under or over it; nothing is held back.")
    if near:
        notes.append(f"Heads up: '{name}' looks like '{near[0]}'.")
    return " ".join(notes)


def savings_seen(add: bool) -> str:
    """Bank transfers to savings that Saved so far doesn't include yet: add them, or ignore them."""
    c = Ctx()
    s = c.settings
    _R, _rem, direct = fd.savings_flow(c.tx, c.starts, s)
    seen = set(s.get("savings_seen") or [])
    unseen = {i: a for i, a in direct.items() if i not in seen}
    if not unseen:
        raise ValueError("Nothing new to add.")
    amt = float(sum(unseen.values()))
    backup("settings.json")
    fd.save_settings({**s, "savings_seen": sorted(seen | set(unseen)), "savings_have": round(_have_default(c) + (amt if add else 0.0), 2),
                      "savings_apy": float(s.get("savings_apy") or 4.0)})
    return f"Added {fd.money(amt)} to Saved so far." if add else "Okay, left out of Saved so far."


def snooze_import() -> str:
    s = fd.load_settings()
    backup("settings.json")
    fd.save_settings({**s, "import_prompt_snoozed": date.today().isoformat()})
    return "Okay."


def tx_autocat() -> str:
    """Run your rules over every transaction that has no category yet."""
    tx = fd.load("transactions")
    full, n = fd.categorize(tx, fd.load("rules"))
    save("transactions", full)
    return f"Auto-categorized {n} transactions."


def _savings_eligible(c: Ctx, ids: list) -> pd.DataFrame:
    """Extra-income deposits (an Income category that isn't a paycheck) not already moved to savings."""
    moved = set(c.settings.get("savings_moved") or [])
    t = c.tx[c.tx["id"].isin(ids) & (c.tx["amount"] > 0) & ~c.tx["id"].isin(moved)]
    # (.astype(bool): with no rows, map() hands back an empty non-boolean Series and pandas would treat it as column names)
    return t[t["category"].map(lambda x: isinstance(x, str) and bool(x.strip()) and c.ctype(x) == "Income" and x.lower() not in c.pnames).astype(bool)]


def _have_default(c: Ctx) -> float:
    return float(c.settings.get("savings_have") or max(fd.savings_total(c.tx), 0.0))


def savings_move(ids: list) -> str:
    c = Ctx()
    ok = _savings_eligible(c, ids)
    if ok.empty:
        raise ValueError("Move to savings works on extra income only: pick deposits in an Income category that isn't a paycheck.")
    amt = float(ok["amount"].sum())
    new = set(ok["id"])
    s = c.settings
    backup("settings.json")
    fd.save_settings({**s, "savings_moved": sorted(set(s.get("savings_moved") or []) | new),
                      "savings_moved_on": {**(s.get("savings_moved_on") or {}), **{i: date.today().isoformat() for i in new}},
                      "savings_have": round(_have_default(c) + amt, 2), "savings_apy": float(s.get("savings_apy") or 4.0)})
    return f"Moved {fd.money(amt)} to savings ({len(new)} deposit{'s' if len(new) != 1 else ''}). It's still in Income, but no longer counts in Left."


def savings_take_back(ids: list) -> str:
    c = Ctx()
    s = c.settings
    moved = set(s.get("savings_moved") or [])
    back = [i for i in ids if i in moved]
    if not back:
        raise ValueError("Nothing to take back.")
    amt = float(c.tx[c.tx["id"].isin(back)]["amount"].sum())
    backup("settings.json")
    fd.save_settings({**s, "savings_moved": [i for i in moved if i not in set(back)],
                      "savings_moved_on": {k: v for k, v in (s.get("savings_moved_on") or {}).items() if k not in set(back)},
                      "savings_have": round(max(_have_default(c) - amt, 0.0), 2), "savings_apy": float(s.get("savings_apy") or 4.0)})
    return f"Took {fd.money(amt)} back out of savings. It counts in Left again."


# ---------- the Plan tab ----------
def _master(c: Ctx) -> pd.DataFrame:
    rec_file = fd.DATA_DIR / "recurring.csv"
    bnames = set(fd.budget_limits(c.budgets))
    m = fd.load("recurring") if rec_file.exists() else fd.derive_master(c.plan, bnames)
    return fd.clean_recurring(m).sort_values(["due_day", "item"], na_position="last").reset_index(drop=True)


def plan_state(c: Ctx, period: str) -> dict:
    master = _master(c)
    inc_list = c.pinc.sort_values("amount", ascending=False).reset_index(drop=True)
    xinc = c.inc_eff[(c.inc_eff.period_start == period) & (c.inc_eff.kind == "extra")]
    xinc = xinc.groupby("source", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
    spend = c.tx[c.tx["amount"] < 0].assign(key=lambda d: d["category"].str.lower())
    recent = spend[pd.to_datetime(spend["date"], errors="coerce") >= pd.Timestamp(date.today() - timedelta(days=90))]
    uses = spend.groupby("key").agg(n=("id", "count"), last=("date", "max"))
    last90 = -recent.groupby("key")["amount"].sum()
    xc = [dict(name=r.name, one_off=bool(r.one_off), n=int(uses["n"].get(r.name.lower(), 0)),
               last90=float(last90.get(r.name.lower(), 0.0)), last=uses["last"].get(r.name.lower(), ""))
          for r in c.xcats.itertuples()]
    by_p = c.ep_hold[c.ep_hold.kind == "extra"].groupby("period_start")["amount"].sum()
    cur = fd.current_period(c.starts)
    ci = c.starts.index(cur)
    shown = c.starts[max(0, ci - 10):ci + 2]
    names = sorted({*c.rules["category"], *c.tx["category"], *c.plan["item"], *c.budgets["category"]} - {""}, key=str.lower)
    rows = lambda df: df.where(pd.notna(df), None).to_dict("records")
    nudges = fd.paycheck_nudges(inc_list, c.tx, c.starts, c.settings.get("dismissed_nudges", []))
    return dict(
        nudges=nudges, income=rows(inc_list), master=[dict(item=r.item, due_day=r.due_day, amount=float(r.amount), freq=r.freq,
                                             month=None if pd.isna(r.month) else int(r.month)) for r in master.itertuples()],
        rules=rows(c.rules[["keyword", "category"]]), budgets=rows(c.budgets), limits=rows(c.limits), xincome=rows(xinc), xcats=xc, onetime=rows(c.onetime),
        extras_by_period=[dict(start=s, amount=float(by_p.get(s, 0.0)), current=s == cur) for s in shown],
        runs_through=fd.label(c.starts[-1]), mode=fd.period_mode(), period_day=fd.layout_at(date.today())["day"], next_start=fd.next_start(cur).isoformat(), pending=next((g for g in fd.period_layout() if g["from"] > date.today().isoformat()), None), can_undo_rec=fd.has_rec_backup(), names=names, freqs=fd.FREQS,
        months=fd.MONTH_NAMES, today=date.today().isoformat(), income_missing_file=not (fd.DATA_DIR / "planned_income.csv").exists(),
        rec_missing_file=not (fd.DATA_DIR / "recurring.csv").exists())


def _clean_master(rows: list, c: Ctx) -> tuple[pd.DataFrame, list, list]:
    df = pd.DataFrame(rows, columns=["item", "due_day", "amount", "freq", "month"])
    no_month = [r["item"] for r in rows if r.get("freq") in fd.FREQS[1:] and not r.get("month")]
    edited = fd.clean_recurring(df)
    bnames = set(fd.budget_limits(c.budgets))
    clash = [n for n in edited["item"] if n.lower() in bnames]
    edited = edited[~edited["item"].str.lower().isin(bnames)].reset_index(drop=True)
    return edited, clash, no_month


def expenses_preview(rows: list) -> dict:
    c = Ctx()
    master = _master(c)
    edited, clash, no_month = _clean_master(rows, c)
    removed = [n for n in master["item"] if n.lower() not in set(edited["item"].str.lower())]
    before = {r.item.lower(): (r.due_day, float(r.amount), r.freq, r.month) for r in master.itertuples()}
    same = lambda a, b: (pd.isna(a) and pd.isna(b)) or a == b
    changed = [r.item for r in edited.itertuples()
               if r.item.lower() not in before or abs(before[r.item.lower()][1] - float(r.amount)) >= 0.005
               or not same(before[r.item.lower()][0], r.due_day) or before[r.item.lower()][2] != r.freq
               or not same(before[r.item.lower()][3], r.month)]
    return dict(removed=removed, changed=changed, clash=clash, no_month=no_month)


def expenses_save(rows: list, starts_on: dict, cancels: dict) -> str:
    c = Ctx()
    edited, _clash, _nm = _clean_master(rows, c)
    d = lambda m: {k: date.fromisoformat(v) for k, v in (m or {}).items()}
    fd.backup_recurring()
    new_plan, stats = fd.sync_recurring(c.plan, edited, c.starts, date.today(), d(cancels), d(starts_on))
    save("recurring", edited)
    save("plan", new_plan, keep_backup=True)
    msg = "Saved. Bills due from today on now follow your list; anything already due is unchanged."
    return msg + (f" Removed {stats['cancelled']} cancelled entries." if cancels else "")


def income_preview(rows: list) -> dict:
    c = Ctx()
    edited = fd.clean_income_list(pd.DataFrame(rows, columns=["source", "amount"]))
    return dict(removed=[n for n in c.pinc["source"] if n.lower() not in set(edited["source"].str.lower())])


def income_save(rows: list, cancels: dict) -> str:
    c = Ctx()
    edited = fd.clean_income_list(pd.DataFrame(rows, columns=["source", "amount"]))
    inc_list = c.pinc.sort_values("amount", ascending=False).reset_index(drop=True)
    fd.backup_recurring()
    new_inc, stats = fd.sync_income(c.income, edited, c.starts, date.today(), {k: date.fromisoformat(v) for k, v in (cancels or {}).items()})
    before = {r.source.lower(): float(r.amount) for r in inc_list.itertuples()}
    changed = {r.source.lower() for r in edited.itertuples() if abs(before.get(r.source.lower(), -1.0) - float(r.amount)) >= 0.005}
    cp = fd.current_period(c.starts)
    ov = fd.load("income_overrides")
    ov = ov[~((ov["period_start"] == cp) & ov["source"].str.lower().isin(changed))]
    ov = pd.concat([ov, pd.DataFrame({"period_start": cp, "source": sorted(changed)})], ignore_index=True)
    save("planned_income", edited)
    save("income", new_inc, keep_backup=True)
    save("income_overrides", ov)
    return "Saved. Paychecks from this pay period on now follow your planned income; earlier ones are unchanged."


def _chain_after(last: str, n: int) -> list[str]:
    """The `n` pay periods that follow the one starting on `last`, laid out the way this ledger is set up."""
    out, d = [], date.fromisoformat(last)
    for _ in range(n):
        d = fd.next_start(d)
        out.append(d.isoformat())
    return out


def add_periods(n: int) -> str:
    c = Ctx()
    return _extend(c, _chain_after(c.starts[-1], int(n)))


def backfill_periods(c: Ctx, cap: int = 130) -> int:
    """Pay periods before the first one, back to the oldest bank transaction, laid out the way the first one is.
    Without them an older paycheck falls in no period and never shows. Returns how many were added."""
    if not c.starts or c.tx.empty:
        return 0
    oldest = pd.to_datetime(c.tx["date"], errors="coerce").min()
    if pd.isna(oldest):
        return 0
    oldest, first = oldest.date(), date.fromisoformat(c.starts[0])
    if oldest >= first:
        return 0
    seg, new_s, d = fd.layout_at(first), [], first
    while d > oldest and len(new_s) < cap:
        if seg["mode"] == "monthly":
            y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
            d = fd.month_start(y, m, seg["day"])
        else:
            d = d - timedelta(days=fd.PERIOD_DAYS)
        new_s.append(d.isoformat())
    if not new_s:
        return 0
    lay = fd.period_layout()
    if lay:  # the layout has to reach back as far as the periods do, or the older ones are measured the wrong length
        _save_layout([{**lay[0], "from": min(new_s)}] + lay[1:])
    save("periods", pd.DataFrame({"period_start": sorted(set(c.starts) | set(new_s))}))
    return len(new_s)


def maybe_extend() -> None:
    """A ledger set up on this version keeps three pay periods ahead by itself (a person who only imports bank files never
    has to add periods), and reaches back to the oldest bank transaction. Older ledgers are left alone: they add periods
    when they choose to."""
    if not fd.load_settings().get("auto_periods"):
        return
    c = Ctx()
    if not c.starts:
        return
    if backfill_periods(c):
        c = Ctx()
    today_iso = date.today().isoformat()
    ahead = sum(1 for x in c.starts if x > today_iso)
    if ahead >= 3 and fd.period_end(c.starts[-1]) >= date.today():
        return
    new_s, d = [], date.fromisoformat(c.starts[-1])
    while (ahead + sum(1 for x in new_s if x > today_iso)) < 3 and len(new_s) < 600:
        d = fd.next_start(d)
        new_s.append(d.isoformat())
    if new_s:
        GROUP[0] += 1
        _extend(c, new_s)


def _extend(c: Ctx, new_s: list[str]) -> str:
    master = _master(c)
    inc_list = c.pinc.sort_values("amount", ascending=False).reset_index(drop=True)
    new_inc = [dict(period_start=s, source=r.source, amount=float(r.amount)) for s in new_s for r in inc_list.itertuples()]
    save("periods", pd.DataFrame({"period_start": sorted(set(c.starts) | set(new_s))}))
    save("plan", pd.concat([c.plan, pd.DataFrame(fd.recurring_rows(master, new_s))], ignore_index=True))
    save("income", pd.concat([c.income, pd.DataFrame(new_inc, columns=fd.SCHEMAS["income"])], ignore_index=True))
    return f"Added {len(new_s)} pay periods."


def rules_save(rows: list) -> str:
    df = pd.DataFrame(rows, columns=["keyword", "category"]).fillna("")
    df = df[(df["keyword"].astype(str).str.strip() != "") & (df["category"].astype(str).str.strip() != "")]
    save("rules", df)
    return "Rules saved."


def budgets_save(rows: list) -> str:
    df = pd.DataFrame(rows, columns=["category", "limit"])
    df["category"] = df["category"].fillna("").astype(str).str.strip()
    df["limit"] = pd.to_numeric(df["limit"], errors="coerce").fillna(0.0)
    save("budgets", df[df["category"] != ""])
    return "Budgets saved."


def limits_save(rows: list) -> str:
    """Spending limits: a category and a number to measure it against. Holds no money back."""
    c = Ctx()
    df = pd.DataFrame(rows, columns=["category", "limit"])
    df["category"] = df["category"].fillna("").astype(str).str.strip()
    df["limit"] = pd.to_numeric(df["limit"], errors="coerce").fillna(0.0)
    df = df[df["category"] != ""].drop_duplicates("category", keep="last")
    save("limits", df)
    taken = {str(i).lower() for i in _master(c)["item"]} | set(fd.budget_limits(c.budgets))
    clash = [n for n in df["category"] if n.lower() in taken]
    return "Limits saved." + (f" {', '.join(clash)} {'is' if len(clash) == 1 else 'are'} already a bill or budget, so "
                              f"{'its' if len(clash) == 1 else 'their'} limit is left out of the table." if clash else "")


def xcats_save(rows: list) -> str:
    c = Ctx()
    canon_all = {x.lower(): x for x in fd.known_categories(c.rules, c.plan, c.budgets, c.income, c.tx)}
    r2, t2, p2, b2 = c.rules, fd.load("transactions")[fd.SCHEMAS["transactions"]], c.plan, c.budgets
    flags = {r["name"].lower(): bool(r.get("one_off")) for r in rows}
    merged = 0
    for r in rows:
        new_n = str(r.get("rename_to") or "").strip()
        if new_n and new_n.lower() != r["name"].lower():
            new_n = canon_all.get(new_n.lower(), new_n)
            r2, t2, p2, b2, _cnt = fd.rename_category(r["name"], new_n, r2, t2, p2, b2)
            flags[new_n.lower()] = flags.get(new_n.lower(), False) or flags.pop(r["name"].lower(), False)
            merged += 1
    if merged:
        save("rules", r2); save("transactions", t2); save("plan", p2); save("budgets", b2)
    xc2 = fd.sync_extra_categories(pd.DataFrame(columns=["name", "one_off"]), t2, p2, r2, c.planned_set, c.pnames)
    xc2["one_off"] = [flags.get(n.lower(), False) for n in xc2["name"]]
    save("extra_categories", xc2)
    return "Extra categories saved." + (f" {merged} renamed or merged." if merged else "")


def rename_all(old: str, new: str) -> str:
    c = Ctx()
    r2, t2, p2, b2, cnt = fd.rename_category(old, new, c.rules, fd.load("transactions")[fd.SCHEMAS["transactions"]], c.plan, c.budgets)
    if (fd.DATA_DIR / "recurring.csv").exists():
        rec = fd.load("recurring")
        rec.loc[rec["item"].str.lower() == old.strip().lower(), "item"] = new
        save("recurring", fd.clean_recurring(rec))
    save("rules", r2); save("transactions", t2); save("plan", p2); save("budgets", b2)
    return f"Renamed '{old}' to '{new}': {cnt['rules']} rules, {cnt['transactions']} transactions, {cnt['plan_rows']} plan lines."


# ---------- the Analysis tab ----------
def bills_trend(c: Ctx, start: str = "", end: str = "") -> dict:
    """What each scheduled bill really cost, pay period by pay period, with how it is trending and which ones moved.
    Only pay periods that the bank transactions cover are used (so a bill with no payment in a covered period that has ended
    shows as missed). A bill's amount in a period is what was spent under its name, the same rule the status column uses."""
    today = date.today()
    covered = fd.tx_driven_periods(c.tx, c.starts, today)
    periods = [p_ for p_ in c.starts if p_ in covered and date.fromisoformat(p_) <= today]
    everything = list(periods)  # the full span the data covers, for the date filter's limits
    # a pay period is in when any of its days fall between the two dates
    periods = [p_ for p_ in periods if (not start or fd.period_end(date.fromisoformat(p_)).isoformat() >= start) and (not end or p_ <= end)]
    bills = c.plan[c.plan["kind"] == "bill"]
    spent = c.tx[(c.tx["amount"] < 0) & (c.tx["category"].astype(str) != "")].copy()
    spent["key"] = spent["category"].astype(str).str.lower()
    by = {(p_, k): g for (p_, k), g in spent.groupby(["period_start", "key"])}
    out, alerts = [], []
    tot = {p_: 0.0 for p_ in periods}
    # credit cards and loans: what you pay swings with how much extra you put on, so they are judged against their minimum
    # (the planned amount) instead of against their own history, and they stay out of the costing-more / costing-less alerts
    cards = {str(x).strip().lower() for x in c.settings.get("card_bills", [])}
    all_names = sorted(bills["item"].unique(), key=str.lower)
    # calendar months, for the monthly chart: a month is "full" when the transactions cover all of it (give or take 2 days at each end)
    tx_dates = pd.to_datetime(c.tx["date"], errors="coerce").dropna()
    months = []
    if len(tx_dates):
        first, last = tx_dates.min().date(), tx_dates.max().date()
        m = date(first.year, first.month, 1)
        lo_d, hi_d = (date.fromisoformat(start) if start else None), (date.fromisoformat(end) if end else None)
        while m <= last:
            m_end = date(m.year + (m.month == 12), m.month % 12 + 1, 1) - timedelta(days=1)
            if (lo_d is None or m_end >= lo_d) and (hi_d is None or m <= hi_d):
                months.append(dict(key=m.strftime("%Y-%m"), label=m.strftime("%b %Y"), full=bool(first <= m + timedelta(days=2) and last >= m_end - timedelta(days=2) and m_end < today)))
            m = m_end + timedelta(days=1)
    spent["month"] = spent["date"].astype(str).str[:7]
    paid_m = spent.groupby(["key", "month"])["amount"].sum().to_dict()
    for name in all_names:
        rows = bills[bills["item"] == name]
        series = []
        for p_ in periods:
            r = rows[rows["period_start"] == p_]
            if r.empty:
                continue
            g = by.get((p_, name.lower()))
            paid = float(-g["amount"].sum()) if g is not None else 0.0
            ended = fd.period_end(date.fromisoformat(p_)) < today
            due = fd.occurrence(p_, r["due_day"].iloc[0]) if pd.notna(r["due_day"].iloc[0]) else None
            on = date.fromisoformat(str(g["date"].max())[:10]) if g is not None else None
            pt = dict(period=p_, label=fd.label(p_), planned=float(r["amount"].sum()),
                      paid=paid if paid > 0 else None, paid_on=on.isoformat() if on else None,
                      days_late=(on - due).days if (on and due) else None, missed=bool(paid <= 0 and ended))
            series.append(pt)
            if paid > 0:
                tot[p_] += paid
        paid_v = [x["paid"] for x in series if x["paid"] is not None]
        if not series:
            continue
        is_card = name.lower() in cards
        plan_m = {}
        for r_ in rows.itertuples():  # what was planned, in the calendar month each payment falls due
            due_ = fd.occurrence(r_.period_start, r_.due_day) if pd.notna(r_.due_day) else None
            k_ = (due_ or date.fromisoformat(r_.period_start)).strftime("%Y-%m")
            plan_m[k_] = plan_m.get(k_, 0.0) + float(r_.amount)
        monthly = [dict(k=m_["key"], paid=float(-paid_m.get((name.lower(), m_["key"]), 0.0)), planned=plan_m.get(m_["key"])) for m_ in months]
        info = dict(name=name, card=is_card, monthly=monthly, due_day=None if pd.isna(rows["due_day"].iloc[-1]) else int(rows["due_day"].iloc[-1]), series=series)
        if paid_v:
            latest, prior = paid_v[-1], paid_v[:-1][-3:]
            base = float(np.median(prior)) if prior else None
            amt = latest - base if base is not None else None
            pct = amt / base * 100 if base else None
            slope = None
            if len(paid_v) >= 3 and np.mean(paid_v) > 0:
                slope = float(np.polyfit(range(len(paid_v)), paid_v, 1)[0] * (len(paid_v) - 1) / np.mean(paid_v) * 100)  # % drift across the whole range
            info.update(latest=latest, avg=float(np.mean(paid_v)), low=min(paid_v), high=max(paid_v), baseline=base,
                        change_amt=amt, change_pct=pct, drift_pct=slope,
                        dir="up" if (pct or 0) >= 2 else "down" if (pct or 0) <= -2 else "steady")
            if is_card:
                over = [x["paid"] - x["planned"] for x in series if x["paid"] is not None]
                info.update(dir="card", minimum=series[-1]["planned"], over_latest=over[-1], over_avg=float(np.mean(over)),
                            at_min=sum(1 for o in over if o <= 0.5), n_paid=len(over), over_total=float(sum(max(o, 0) for o in over)))
            elif pct is not None and abs(pct) >= 3 and abs(amt) >= 1:
                alerts.append(dict(name=name, kind="up" if amt > 0 else "down", pct=pct, amt=amt, latest=latest, baseline=base))
            elif slope is not None and abs(slope) >= 10:
                alerts.append(dict(name=name, kind="creep" if slope > 0 else "slide", pct=slope, amt=None, latest=latest, baseline=None))
        if series[-1]["missed"]:
            alerts.append(dict(name=name, kind="missed", pct=None, amt=None, latest=None, baseline=series[-1]["planned"]))
        out.append(info)
    alerts.sort(key=lambda a: (a["kind"] != "missed", -abs(a["amt"] if a["amt"] is not None else (a["pct"] or 0) / 10)))
    # the all-bills total leaves out a pay period that is not over yet: it is only part paid, so it would read as a drop
    return dict(bills=out, alerts=alerts, all_bills=[dict(name=n, card=n.lower() in cards) for n in all_names], months=months, span=dict(first=everything[0] if everything else "", last=fd.period_end(date.fromisoformat(everything[-1])).isoformat() if everything else "",
                                                    all=[dict(period=p_, label=fd.label(p_)) for p_ in everything]),
                periods=[dict(period=p_, label=fd.label(p_), total=tot[p_], days=(fd.period_end(date.fromisoformat(p_)) - date.fromisoformat(p_)).days + 1) for p_ in periods
                                                   if fd.period_end(date.fromisoformat(p_)) < today])


# ---------- the Cash Forecast ----------
def forecast_state(c: Ctx) -> dict:
    today = date.today()
    rw_bl = set(fd.budget_limits(c.budgets))
    opening = c.opening - sum(c.savings_R.values())  # money moved to savings is gone from the runway too
    tr, typical, _n = fd.trend_table(c.starts, c.ep_act, c.inc_eff, rw_bl, opening, project_extras=False, one_off=c.one_off)
    tr_hold, _, _ = fd.trend_table(c.starts, c.ep_hold, c.inc_eff, rw_bl, opening, project_extras=False, one_off=c.one_off)
    open_rows = tr["phase"] != "past"
    tr.loc[open_rows, "budgets"] = tr_hold.loc[open_rows, "budgets"]
    master = (fd.load("recurring") if (fd.DATA_DIR / "recurring.csv").exists() else fd.derive_master(c.plan, rw_bl))
    budget_total = sum(v[1] for v in fd.budget_limits(c.budgets).values())
    base = fd.runway_table(tr, 0.0, fd.clean_recurring(master), c.pinc, budget_total, opening)
    onetime = fd.load("onetime")
    base["onetime"] = 0.0
    for o in c.onetime[c.onetime["open"] & ~c.onetime["check"]].itertuples():
        d = pd.to_datetime(o.date)
        hit = (base["phase"] != "past") & (pd.to_datetime(base["start"]) <= d) & (d <= pd.to_datetime(base["end"]))
        base.loc[hit, "onetime"] += o.amount
        if not o.period_start:  # inside the known periods it is already in their extras; beyond them, add it here
            base.loc[hit, "extras"] += o.amount
    base["spend"] = base[["scheduled", "budgets", "extras", "projected"]].sum(axis=1)
    base["pc_extra"] = base["income"] - base["spend"]
    base["available"] = opening + base["pc_extra"].cumsum()
    cur_idx = base.index[base["phase"] == "current"]
    lo = max(int(cur_idx[0]) - 3, 0) if len(cur_idx) else 0
    if c.anchor:
        at = base.index[base["period_start"] == c.anchor["period"]]
        if len(at):
            lo = max(int(at[0]) - 1, 0)
    rows = [dict(start=r.period_start, end=r.end.isoformat(), full=r.full, phase=r.phase, income=r.income,
                 scheduled=r.scheduled, budgets=r.budgets, extras=r.extras, onetime=r.onetime, spend=r.spend,
                 pc_extra=r.pc_extra, available=r.available) for r in base.iloc[lo:].itertuples()]
    live = c.debts[(c.debts["name"] != "") & (c.debts["current_balance"] > 0)]
    ready = live[live["min_payment"] > 0]
    spans = [(pd.Timestamp(e) - pd.Timestamp(b)).days + 1 for b, e in zip(base["start"], base["end"])]
    per_year = 26 if not spans or abs(sum(spans) / len(spans) - 14) < .01 else 365 / (sum(spans) / len(spans))  # periods per year
    ppm = per_year / 12  # periods per month
    exp_month = float(base[base["phase"] == "future"]["spend"].mean() * per_year / 12) if (base["phase"] == "future").any() else 0.0
    s = c.settings
    have_default = round(float(s.get("savings_have") or max(fd.savings_total(c.tx), 0.0)), 2)
    anchor = None
    if c.anchor:
        a = c.anchor
        anchor = dict(bank=a["bank"], as_of=a["as_of"], to_arrive=a.get("to_arrive", 0), to_leave=a["to_leave"], left=a["left"], period=a["period"])
    return dict(rows=rows, ppm=ppm, mode=fd.period_mode(), email_enabled=EM_SCRIPT.exists(), today=today.isoformat(), threshold=float(s["debt_threshold"]), savings_have=have_default,
                savings_apy=float(s.get("savings_apy") or 4.0), exp_month=exp_month, anchor=anchor,
                goal=dict(name=str(s.get("goal_name") or ""), target=float(s.get("goal_target") or 0.0), have=float(s.get("goal_have") or 0.0)),
                debts=[dict(name=r.name, current_balance=float(r.current_balance), min_payment=None if pd.isna(r.min_payment) else float(r.min_payment),
                            apr=None if pd.isna(r.apr) else float(r.apr), start_balance=float(r.start_balance), in_email=bool(r.in_email))
                       for r in c.debts.itertuples()],
                debt_ready=[dict(name=r.name, apr=None if pd.isna(r.apr) else float(r.apr)) for r in ready.itertuples()],
                onetime=[dict(name=r.name, date=r.date, amount=float(r.amount), open=bool(r.open)) for r in c.onetime.itertuples()],
                unseen=(lambda d: dict(n=len(d), amount=float(sum(d.values()))))(
                    {i: a for i, a in fd.savings_flow(c.tx, c.starts, s)[2].items() if i not in set(s.get("savings_seen") or [])}),
                moved=[dict(id=r.id, date=r.date, description=r.description, amount=float(r.amount))
                       for r in c.tx[c.tx["id"].isin(set(s.get("savings_moved") or []))].sort_values("date", ascending=False).itertuples()])


def debt_summary(extra: float, through: str) -> dict:
    debts = fd.load("debts")
    live = debts[(debts["name"] != "") & (debts["current_balance"] > 0)]
    rd = live[live["min_payment"] > 0].reset_index(drop=True)
    owed = float(live["current_balance"].sum())
    if rd.empty:
        return dict(has_debt=False, owed=owed)
    bals = [float(x) for x in rd["current_balance"]]
    aprs = [float(x) if pd.notna(x) else 0.0 for x in rd["apr"]]
    mins = [float(x) for x in rd["min_payment"]]
    solo = [fd.simulate_payoff([b], [a], [m]) for b, a, m in zip(bals, aprs, mins)]
    base_m = [r["months"] for r in solo]
    free_base = None if any(m is None for m in base_m) else max(base_m, default=0)
    base_int = sum(r["interest"] for r in solo)
    free_new, saved, owed_by = free_base, 0.0, owed
    sim = fd.simulate_payoff(bals, aprs, mins, extra, rollover=True) if extra > 0 else None
    if sim:
        free_new = sim["months"]
        saved = (base_int - sim["interest"]) if free_base is not None else None
    t = (sim or fd.simulate_payoff(bals, aprs, mins, 0.0, rollover=True))["totals"]
    mo = max((date.fromisoformat(through) - date.today()).days, 0) / 30.4375
    i0 = int(mo)
    t0, t1 = t[min(i0, len(t) - 1)], t[min(i0 + 1, len(t) - 1)]
    owed_by = max(t0 + (t1 - t0) * (mo - i0), 0.0) + float(live.loc[~(live["min_payment"] > 0), "current_balance"].sum())
    return dict(has_debt=True, owed=owed, owed_by=owed_by, free_base=free_base, free_new=free_new, saved=saved)


LOOK_KEYS = {"theme", "dark_mode", "animations", "anim_style", "anim_bg", "anim_speed", "app_name", "name_asked"}  # the ledger's name is yours too


def settings_update(upd: dict) -> str:
    look = {k: v for k, v in upd.items() if k in LOOK_KEYS}
    if look:
        save_real_settings(look)  # your look is yours: saved to your real settings even on sample data
    rest = {k: v for k, v in upd.items() if k not in LOOK_KEYS and not str(k).startswith("lan_")}
    if rest:
        s = fd.load_settings()
        backup("settings.json")
        fd.save_settings({**s, **rest})
    return "Saved."


def debts_save(rows: list) -> str:
    df = pd.DataFrame(rows, columns=["name", "start_balance", "current_balance", "min_payment", "apr", "in_email"])
    df["in_email"] = df["in_email"].fillna(True)
    save("debts", fd.finalize_debts(df))
    return "Debts saved."


def payback_set(tx_id: str, item: str, link: bool) -> str:
    """Say a deposit pays back an expense (or take that back). Presentation only: it changes the Extras card, never the money."""
    s = fd.load_settings()
    kept = [x for x in s.get("paybacks", []) if str(x).partition("|")[0] != tx_id]
    backup("settings.json")
    fd.save_settings({**s, "paybacks": kept + ([f"{tx_id}|{item}"] if link else [])})
    return "Linked. The Extras card now shows what you really spent." if link else "Unlinked."


def onetime_apply(tx_id: str, name: str) -> str:
    """You said an imported charge IS the planned one-time expense: file it under that name and retire the plan entry."""
    tx = fd.load("transactions")
    hit = tx[tx["id"] == tx_id]
    if hit.empty:
        raise ValueError("That transaction is gone.")
    amt = abs(float(hit["amount"].iloc[0]))
    tx_category([tx_id], name)
    ot = fd.load("onetime")
    same = ot[ot["name"].str.strip().str.lower() == name.strip().lower()]
    if len(same):
        save("onetime", ot.drop((same["amount"] - amt).abs().sort_values().index[:1]))
    return f"Filed it as {name} and removed the planned entry."


def onetime_save(rows: list) -> str:
    df = pd.DataFrame(rows, columns=["name", "date", "amount"])
    df = df.dropna(subset=["date", "amount"]).copy()
    df["name"] = df["name"].fillna("").astype(str).str.strip().replace("", "One-time")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df[df["amount"] > 0]
    save("onetime", df)
    return "Saved. The forecast now includes them."


# ---------- bank import, sample data, password, Overview suggestions ----------
def _read_upload(name: str, b64: str) -> pd.DataFrame:
    import base64
    import io
    buf = io.BytesIO(base64.b64decode(b64))
    buf.name = name
    return fd.read_table(buf, name)


def import_preview(name: str, b64: str) -> dict:
    raw = _read_upload(name, b64)
    cols = list(raw.columns)
    return dict(columns=cols, guess=fd.guess_import(raw), rows=len(raw),
                sample=raw.head(4).fillna("").astype(str).to_dict("records"))


def import_commit(b: dict) -> str:
    raw = _read_upload(b["name"], b["data"])
    c = Ctx()
    spec = dict(dcol=b["dcol"], acol=str(b.get("acol") or ""), scol=b["scol"], debit=str(b.get("debit") or ""),
                credit=str(b.get("credit") or ""), spending="negative" if b.get("spending") == "negative" else "positive")
    for k in ("dcol", "acol", "scol", "debit", "credit"):
        if spec[k] and spec[k] not in raw.columns:
            raise ValueError(f"The file has no column called '{spec[k]}'. Pick the columns again.")
    if not spec["acol"] and not (spec["debit"] and spec["credit"]):
        raise ValueError("Pick the amount column, or both the money-out and money-in columns.")
    allx, n_new, n_cat, n_skip = fd.ingest_mapped(raw, spec["dcol"], spec["acol"], spec["scol"], fd.load("transactions"), c.rules,
                                                  bool(b.get("append", True)), spec["debit"], spec["credit"], spec["spending"])
    save("transactions", allx)
    backup("settings.json")
    fd.save_settings(fd.capture_bank_balance(raw, fd.load_settings(), spec))
    return (f"Imported {n_new} new transactions, {n_cat} auto-categorized."
            + (f" Kept {allx.attrs['carried']} categories you had set." if allx.attrs.get("carried") else "")
            + fd.skipped_note(n_skip))


def _layout_choice(b: dict) -> tuple[str, int]:
    mode = str(b.get("mode") or "biweekly")
    if mode not in fd.MODES:
        raise ValueError("Pick how you budget: every two weeks, or monthly.")
    return mode, max(1, min(int(b.get("day") or 1), 28))  # a start day up to the 28th, so every month has it


def _save_layout(layout: list, **more) -> None:
    backup("settings.json")  # so Undo can put the old layout back along with the data
    fd.save_settings({**fd.load_settings(), "period_layout": layout, **more})


def setup_period(b: dict) -> str:
    """First run: how you budget and where it starts. Refuses once any pay period exists, so it can never overwrite real data."""
    if Ctx().starts:
        raise ValueError("The ledger is already set up.")
    mode, day = _layout_choice(b)
    if mode == "monthly":
        y, m = (int(x) for x in str(b.get("month") or date.today().strftime("%Y-%m")).split("-"))
        start = fd.month_start(y, m, day)
    else:
        start = date.fromisoformat(str(b["date"]))  # a real date, or this raises
    _save_layout([{"from": start.isoformat(), "mode": mode, "day": day}], auto_periods=True)
    save("periods", pd.DataFrame({"period_start": [start.isoformat()]}))
    return "Your first " + ("month" if mode == "monthly" else "pay period") + " is set."


def setup_sample(b: dict) -> str:
    """First run: fill the ledger with made-up sample numbers to look around. Refuses once any pay period exists."""
    if Ctx().starts:
        raise ValueError("The ledger is already set up.")
    mode, day = _layout_choice(b)
    data = fd.sample_data(mode, day)
    _save_layout([{"from": data["periods"]["period_start"].iloc[0], "mode": mode, "day": day}], auto_periods=True)
    for name, df in data.items():
        save(name, df)
    return "Loaded sample data. Your real numbers can replace it any time."


def period_switch(b: dict) -> str:
    """Change how you budget, starting with the next period. The current period and everything before it stay as they are;
    the periods after it are laid out again the new way (their bills and income are rebuilt from your recurring list and
    planned income). One Undo puts it all back."""
    mode, day = _layout_choice(b)
    c = Ctx()
    if not c.starts:
        raise ValueError("Set up your first period first.")
    cur = fd.current_period(c.starts)
    new_from = fd.next_start(cur).isoformat()
    ahead = [x for x in c.starts if x >= new_from]
    same = fd.layout_at(new_from)
    if mode == same["mode"] and (mode == "biweekly" or day == same["day"]):
        return "That's already how it's set up."
    keep = [g for g in fd.period_layout() if g["from"] < new_from]
    _save_layout(keep + [{"from": new_from, "mode": mode, "day": day}], auto_periods=True)
    master, inc_list = _master(c), c.pinc.sort_values("amount", ascending=False).reset_index(drop=True)
    new_s, d = [], date.fromisoformat(new_from)
    for _ in range(max(len(ahead), 6)):
        new_s.append(d.isoformat())
        d = fd.next_start(d)
    before = lambda df: df[df["period_start"] < new_from]
    new_inc = [dict(period_start=x, source=r.source, amount=float(r.amount)) for x in new_s for r in inc_list.itertuples()]
    save("periods", pd.DataFrame({"period_start": [x for x in c.starts if x < new_from] + new_s}))
    save("plan", pd.concat([before(c.plan), pd.DataFrame(fd.recurring_rows(master, new_s))], ignore_index=True))
    save("income", pd.concat([before(c.income), pd.DataFrame(new_inc, columns=fd.SCHEMAS["income"])], ignore_index=True))
    for name in ("paid_marks", "income_overrides"):
        if (fd.DATA_DIR / f"{name}.csv").exists():
            save(name, before(fd.load(name)))
    return f"Switched to {'monthly' if mode == 'monthly' else 'every two weeks'} starting {fd.label(new_from).split(' – ')[0]}."


def twin_and_ideas(c: Ctx, xt: pd.DataFrame, cur: pd.DataFrame, bl: dict, n_x: int) -> tuple[list, list]:
    known = sorted({n for n in cur.loc[cur["kind"] != "extra", "item"]} | {v[0] for v in bl.values()})
    gone = set(c.settings.get("dismissed_twins", []))
    twins = []
    for x in xt[xt["now"] > 0].itertuples():
        if " - " in x.item:  # a group piece, e.g. UK Trip - Groceries, is meant to be separate
            continue
        near = fd.similar_names(x.item, known)
        if near and f"{x.key}|{near[0].lower()}" not in gone:
            twins.append(dict(item=x.item, key=x.key, into=near[0]))
    dismissed = set(c.settings.get("dismissed_budget_ideas", []))
    pick = xt[(xt["times"] >= max(3, (n_x * 2 + 2) // 3)) & ~xt["key"].isin(dismissed) & ~xt["one_off"]
              & ~xt["key"].isin(set(bl))].sort_values("times", ascending=False).head(2)
    ideas = [dict(item=x.item, key=x.key, times=int(x.times), n=n_x, each=float(x.when_spent),
                  limit=float(np.ceil(x.when_spent / 10.0) * 10)) for x in pick.itertuples()]
    return twins[:2], ideas


def idea_accept(item: str, limit: float) -> str:
    save("budgets", pd.concat([fd.load("budgets"), pd.DataFrame([dict(category=item, limit=float(limit))])], ignore_index=True))
    return f"{item} is now a {fd.money(limit)} budget. It counts in every paycheck from now on."


def dismiss(kind: str, value: str) -> str:
    s = fd.load_settings()
    backup("settings.json")
    fd.save_settings({**s, kind: list(s.get(kind, [])) + [value]})
    return "Okay."


# ---------- the payday email (settings for FinanceEmail.py, which the Windows scheduled task runs every payday) ----------
EM_SCRIPT = ROOT / "FinanceEmail.py"
POKE_DIR = ROOT / "email_assets" / "pokemon"


def em_file() -> Path:
    return fd.REAL_DIR / "email_settings.json"  # the settings are always your real ones, even on sample data


def em_load() -> dict:
    try:
        return json.loads(em_file().read_text(encoding="utf-8-sig")) if em_file().exists() else {}  # tolerates a BOM from Notepad
    except Exception:
        return {}


def run_email(flag: str, *extra: str) -> tuple[bool, str]:
    import os
    import subprocess
    env = dict(os.environ)
    if fd.DATA_DIR != fd.REAL_DIR:  # sample data: the numbers come from the test folder, the settings stay your real ones
        env["FINANCE_DATA_DIR"] = str(fd.TEST_DIR)
        env["FINANCE_EMAIL_SETTINGS"] = str(em_file())
    try:
        r = subprocess.run([sys.executable, str(EM_SCRIPT), flag, *extra], capture_output=True, text=True, timeout=120,
                           cwd=str(ROOT), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return False, str(e)


# ---------- the time of day the payday email goes out (the Windows scheduled task that runs FinanceEmail.py) ----------
# The ledger doesn't send mail itself: a Task Scheduler job runs FinanceEmail.py, and the job's start time is the send time.
# These read that job and, when you save a new time, change just the time of day, leaving its every-other-Friday schedule alone.
FIND_TASK_PS = r"""
$ErrorActionPreference = 'Stop'
$out = @()
foreach ($t in (Get-ScheduledTask)) {
  $mine = $t.Actions | Where-Object { "$($_.Arguments)" -like '*FinanceEmail.py*' }
  if (-not $mine) { continue }
  $i = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath
  $g = $t.Triggers | Select-Object -First 1
  $out += [pscustomobject]@{
    name = $t.TaskName; path = $t.TaskPath; state = "$($t.State)"; start = "$($g.StartBoundary)"
    next = $(if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) { $i.NextRunTime.ToString('s') } else { '' })
    last = $(if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('s') } else { '' })
  }
}
ConvertTo-Json -InputObject @($out) -Compress
"""

SET_TASK_TIME_PS = r"""
$ErrorActionPreference = 'Stop'
$t = Get-ScheduledTask -TaskName $env:LEDGER_TASK -TaskPath $env:LEDGER_TASK_PATH
$trigs = @($t.Triggers)
foreach ($g in $trigs) { if ($g.StartBoundary) { $g.StartBoundary = $g.StartBoundary.Substring(0, 10) + 'T' + $env:LEDGER_TIME + ':00' } }
Set-ScheduledTask -TaskName $env:LEDGER_TASK -TaskPath $env:LEDGER_TASK_PATH -Trigger $trigs | Out-Null
"""


def _powershell(script: str, extra_env: dict | None = None, timeout: int = 30) -> tuple[bool, str]:
    """Run a PowerShell snippet (Windows only). Values go in through the environment, never pasted into the script."""
    import subprocess
    if os.name != "nt":
        return False, "Scheduled tasks are only managed on Windows."
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=timeout, env={**os.environ, **(extra_env or {})},
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()
    except Exception as e:
        return False, str(e)


TASK_CACHE: dict = {"at": 0.0, "info": None}


def task_find(fresh: bool = False) -> dict:
    """The scheduled task that sends the payday email, with its time of day and next run; or why there is none.
    Task Scheduler takes a few seconds to search, so the answer is kept for a minute (and dropped when the time changes)."""
    import time
    if not fresh and TASK_CACHE["info"] is not None and time.time() - TASK_CACHE["at"] < 60:
        return TASK_CACHE["info"]
    info = _task_lookup()
    TASK_CACHE.update(at=time.time(), info=info)

    return info


def _task_lookup() -> dict:
    ok, out = _powershell(FIND_TASK_PS)
    if not ok:
        return dict(found=False, reason=out.splitlines()[0] if out else "Task Scheduler could not be read.")
    try:
        tasks = [t for t in json.loads(out or "[]") if t.get("start")]
    except ValueError:
        return dict(found=False, reason="Task Scheduler gave an answer that could not be read.")
    if not tasks:
        return dict(found=False, reason="No Windows scheduled task runs the payday email on this PC.")
    t = next((x for x in tasks if "payday" in x["name"].lower()), tasks[0])
    m = re.search(r"T(\d{2}):(\d{2})", t["start"])
    return dict(found=True, name=t["name"], path=t["path"], time=f"{m[1]}:{m[2]}" if m else "", next=t["next"], last=t["last"],
                enabled=t["state"] != "Disabled")


def task_set_time(task: dict, hhmm: str) -> None:
    """Change only the time of day of that task's start. Raises ValueError with the reason if Windows refuses."""
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hhmm):
        raise ValueError("That time doesn't look right.")
    ok, out = _powershell(SET_TASK_TIME_PS, dict(LEDGER_TASK=task["name"], LEDGER_TASK_PATH=task["path"], LEDGER_TIME=hhmm))
    if not ok:
        raise ValueError(out.splitlines()[0] if out else "Windows would not change the task.")


def _clock(hhmm: str) -> str:
    h, m = int(hhmm[:2]), hhmm[3:]
    return f"{h % 12 or 12}:{m} {'AM' if h < 12 else 'PM'}"


def email_state() -> dict:
    c = Ctx()
    em = em_load()
    poke = sorted((p.stem for p in POKE_DIR.glob("*.png")), key=str.lower) if POKE_DIR.exists() else []
    hid = list(em.get("hidden", []))
    inc = {str(i) for i in [*c.pinc["source"], *c.inc_eff["source"]] if str(i).strip()}  # paycheck and extra-income lines the email lists
    items = sorted({*(str(i) for i in c.plan["item"] if str(i).strip()), *inc, *hid}, key=str.lower)
    try:
        last = json.loads((fd.REAL_DIR / "runner_last.json").read_text())
    except Exception:
        last = None
    try:
        lg = pd.read_csv(fd.REAL_DIR / "email_log.csv", dtype=str).fillna("").tail(8).iloc[::-1]
        sends = [dict(sent=r.sent_at, period=r.period_start, to=len([a for a in str(r.recipients).split(";") if a.strip()]), status=r.status)
                 for r in lg.itertuples()]
    except Exception:
        sends = []
    nxt = next((s for s in c.starts if date.fromisoformat(s) >= date.today()), None)
    return dict(settings={k: em.get(k, d) for k, d in dict(to=[], cc=[], bcc=[], hidden=[], greetings=[], notes=[], love_note="",
                                                          pokemon=["pikachu"], pokemon_walk=[], catchup_days=7, test_to="", sender="").items()},
                pokemon=poke, items=items, item_groups={**cat_groups(c, items), **{n: "Income" for n in items if n in inc}}, periods=[dict(start=s, label=fd.label(s)) for s in c.starts],
                current=fd.current_period(c.starts), last=last, sends=sends, next_payday=nxt, test_mode=fd.DATA_DIR != fd.REAL_DIR,
                script_ok=EM_SCRIPT.exists())


def _addrs(v) -> list:
    import re
    if isinstance(v, list):
        v = "\n".join(map(str, v))
    return [x.strip() for x in re.split(r"[\n,;]+", v or "") if x.strip()]


def email_save(b: dict) -> str:
    em = em_load()
    rows = lambda v: [x.strip() for x in (v if isinstance(v, list) else str(v or "").splitlines()) if str(x).strip()]
    new = {**em, "to": _addrs(b.get("to")), "cc": _addrs(b.get("cc")), "bcc": _addrs(b.get("bcc")), "hidden": list(b.get("hidden", [])),
           "pokemon": list(b.get("pokemon", [])), "pokemon_walk": list(b.get("pokemon_walk", [])), "greetings": rows(b.get("greetings")),
           "notes": rows(b.get("notes")), "love_note": str(b.get("love_note", "")).strip(), "catchup_days": int(b.get("catchup_days", 7))}
    f = em_file()
    if f.exists():  # a timestamped copy first, like every other file
        BACKUPS.mkdir(parents=True, exist_ok=True)
        dst = BACKUPS / f"{datetime.now():%Y%m%d-%H%M%S-%f}_email_settings.json"
        shutil.copyfile(f, dst)
        JOURNAL.append((GROUP[0], "email_settings.json@real", dst))
    f.write_text(json.dumps(new, indent=2), encoding="utf-8")
    note = ""
    send_time = str(b.get("send_time") or "").strip()
    if send_time:  # the send time lives in the scheduled task, so a changed time updates that task
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", send_time):
            return "Email settings saved. That send time doesn't look right, so it was not changed."
        task = task_find()
        if task.get("found") and task.get("time") != send_time:
            try:
                task_set_time(task, send_time)
                TASK_CACHE["info"] = None
                note = f" The payday email now sends at {_clock(send_time)}."
            except ValueError as e:
                note = f" The send time was not changed: {e}"
    return "Email settings saved." + note


def email_args(b: dict) -> list:
    import re
    season = str(b.get("season") or "Auto")
    period = str(b["period"])
    hide = [str(x) for x in b.get("hide", [])]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) or season.lower() not in ("auto", "spring", "summer", "fall", "winter")             or any(not re.fullmatch(r"[\w][\w .&'-]{0,59}", x) for x in hide):  # nothing that could pass for an option
        raise ValueError("Those email options don't look right.")
    return ["--period", period, *(["--season", season.lower()] if season != "Auto" else []), "--hide", *hide]


def email_preview(b: dict) -> dict:
    ok, out = run_email("--preview", *email_args(b))
    pv = ROOT / "email_preview.html"
    if ok and pv.exists():
        return dict(ok=True, html=pv.read_text(encoding="utf-8"))
    return dict(ok=False, error=out or "Couldn't build the preview.")


def email_test(b: dict) -> str:
    to = _addrs(b.get("to"))
    if not to:
        raise ValueError("Add an address to send the test to.")
    import re
    if any(not re.fullmatch(r"[^\s@,;<>\"'-][^\s@,;<>\"']*@[^\s@,;<>\"']+\.[^\s@,;<>\"']+", x) for x in to):
        raise ValueError("One of those email addresses doesn't look right.")
    ok, out = run_email("--test", *email_args(b), "--to", *to)
    if not ok:
        raise ValueError(out or "Failed.")
    return out or "Sent."


def email_send_now() -> str:
    if fd.DATA_DIR != fd.REAL_DIR:
        raise ValueError("Real sends are switched off while sample data is on.")
    if not em_load().get("to"):
        raise ValueError("There are no recipients saved.")
    ok, out = run_email("--force")
    if not ok:
        raise ValueError(out or "Failed.")
    return out or "Sent."


# ---------- phone access (opt-in): the ledger on your home Wi-Fi, behind a PIN ----------
# Off unless you turn it on in Settings on this PC. When on, a second listener accepts private home-network addresses only
# (never the internet), every such device must enter your PIN, and only this PC can change the setting. Kept in its own
# file so Undo can't revert it. The PIN is stored as a salted hash.
LAN: dict = {"srv": None, "fails": {}, "all": []}
LAN_LOCK = threading.Lock()  # the wrong-PIN counters change under this lock, not under the one requests take turns on
LAN_TRIES, LAN_WINDOW, LAN_ALL = 5, 60, 20  # tries a device gets per minute, and tries all devices together get per minute
PIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personal Finance Ledger</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#15122b;color:#eee;font:16px system-ui,sans-serif}
form{width:min(320px,88vw);background:#231f45;border-radius:14px;padding:22px;box-shadow:0 6px 30px #0006}h1{font-size:1.1rem;margin:0 0 4px}p{margin:0 0 14px;color:#b7b2da;font-size:.9rem}
input,button{width:100%;box-sizing:border-box;font:inherit;padding:11px;border-radius:9px;border:1px solid #5a52a8;background:#15122b;color:#eee}button{margin-top:10px;background:#7b6df0;border:0;font-weight:600}#e{color:#ff9aa8;min-height:1.2em;margin-top:8px;font-size:.88rem}</style></head>
<body><form id="f"><h1>Personal Finance Ledger</h1><p>Enter your PIN to open it on this device.</p><input id="p" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN" autofocus>
<button>Open</button><div id="e"></div></form><script>f.onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/lan/login",{method:"POST",headers:{"Content-Type":"application/json","X-Ledger":"1"},body:JSON.stringify({pin:p.value})});
if(r.ok)location.reload();else{const j=await r.json().catch(()=>({}));e.textContent=j.error||"Wrong PIN.";p.value="";p.focus()}}</script></body></html>"""


def lan_file() -> Path:
    """Where the PIN hash and signing secret live: this PC's local app-data folder, not beside your numbers (a cloud-synced
    folder such as OneDrive would copy it). An earlier version kept it in the data folder, so it is moved on first use."""
    env = os.environ.get("LEDGER_PHONE_FILE")
    if env:
        return Path(env)
    f = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")) / "PersonalFinanceLedger" / "phone_access.json"
    old = fd.REAL_DIR / "phone_access.json"
    if not f.exists() and old.exists():
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(f))
        except OSError:
            return old
    return f


def lan_cfg() -> dict:
    try:
        return json.loads(lan_file().read_text())
    except (OSError, ValueError):
        return {}


def _lan_write(cfg: dict) -> None:
    lan_file().parent.mkdir(parents=True, exist_ok=True)
    lan_file().write_text(json.dumps(cfg))


def _pin_hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120_000).hex()


def _private_ip(addr: str) -> bool:
    """A home-network address (192.168.x.x, 10.x.x.x, 172.16-31.x.x, link-local): never a public internet address."""
    try:
        ip = ipaddress.ip_address(addr)
        ip = getattr(ip, "ipv4_mapped", None) or ip
        return ip.is_private and not ip.is_unspecified
    except ValueError:
        return False


def _lan_token(cfg: dict) -> str:
    return hmac.new(cfg["secret"].encode(), ("auth|" + cfg["hash"]).encode(), "sha256").hexdigest()


def lan_ips() -> list:
    """This PC's home-network addresses, the likely one first."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # nothing is sent: it only picks the network card that would be used
            found.append(s.getsockname()[0])
    except OSError:
        pass
    # looking up this computer's own name can stall for many seconds on a Mac or a network with odd DNS, so give it two seconds at most
    named: list = []

    def by_name() -> None:
        try:
            named.extend(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
    t = threading.Thread(target=by_name, daemon=True)
    t.start()
    t.join(2)
    found += named
    out = []
    for a in found:
        if a not in out and _private_ip(a) and not a.startswith("127."):
            out.append(a)
    return out


def lan_state() -> dict:
    cfg = lan_cfg()
    return dict(enabled=bool(cfg.get("enabled")), has_pin=bool(cfg.get("hash")), running=LAN["srv"] is not None, port=PORT,
                weak=bool(cfg.get("hash")) and int(cfg.get("len") or 0) < 6,
                urls=[f"http://{a}:{PORT}" for a in lan_ips()] if cfg.get("enabled") else [])  # no lookup at all while phone access is off


def lan_start() -> None:
    if LAN["srv"] is None:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        LAN["srv"] = srv


def lan_stop() -> None:
    srv, LAN["srv"] = LAN["srv"], None
    if srv is not None:
        srv.shutdown()
        srv.server_close()


def lan_set(enabled: bool, pin: str, signout: bool = False) -> str:
    cfg = lan_cfg()
    pin = (pin or "").strip()
    if pin:
        if not 6 <= len(pin) <= 32 or " " in pin:
            raise ValueError("The PIN must be 6 to 32 characters with no spaces. Six or more digits is a good choice.")
        salt = secrets.token_hex(16)
        cfg.update(salt=salt, hash=_pin_hash(pin, salt), len=len(pin), secret=secrets.token_hex(32))  # a new secret signs every phone out
    if signout:
        cfg["secret"] = secrets.token_hex(32)  # every phone has to enter the PIN again
    if enabled and not cfg.get("hash"):
        raise ValueError("Pick a PIN first. Every phone has to enter it.")
    cfg["enabled"] = bool(enabled)
    cfg.setdefault("secret", secrets.token_hex(32))
    if signout and not pin and enabled == bool(lan_cfg().get("enabled")):
        _lan_write(cfg)
        LAN["fails"].clear()
        return "Every phone has been signed out. They'll ask for the PIN again."
    _lan_write(cfg)
    LAN["fails"].clear()
    if enabled:
        try:
            lan_start()
        except OSError as e:
            cfg["enabled"] = False
            _lan_write(cfg)
            raise ValueError(f"Couldn't open the ledger to your network: {e}")
        urls = lan_ips()
        where = ("Open http://%s:%s on a phone on the same Wi-Fi." % (urls[0], PORT)) if urls else "Open this PC's network address on a phone on the same Wi-Fi."
        return "Phone access is on. " + where + (" If Windows asks about the firewall, allow it on private networks." if not pin else "")
    lan_stop()
    return "Phone access is off."


class Handler(BaseHTTPRequestHandler):
    timeout = 60  # a device that opens a connection and says nothing is let go after a minute

    def _is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _send(self, obj, code: int = 200, ctype: str = "application/json") -> None:
        body = obj if isinstance(obj, bytes) else json.dumps(clean(obj)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "SAMEORIGIN")  # no other website can put the ledger in a frame
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _lan_gate(self, post: bool, host: str) -> bool:
        """A request from another device. Allowed only when phone access is on, from a home-network address, to a home-network
        Host name, and with the right PIN (a cookie the PIN page sets). Sends its own reply when it says no."""
        cfg = lan_cfg()
        ip = self.client_address[0]
        if not cfg.get("enabled") or not cfg.get("hash") or not _private_ip(ip):
            self._send({"error": "This ledger only opens on the PC it runs on."}, 403)
            return False
        me = socket.gethostname().lower()
        if not (_private_ip(host) or host in (me, me + ".local")):
            self._send({"error": "Blocked: unexpected address."}, 403)
            return False
        path = urlparse(self.path).path
        if post and path == "/api/lan/login":
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= 4096:
                self._send({"error": "Bad request."}, 400)
                return False
            try:
                pin = str(json.loads(self.rfile.read(n) or b"{}").get("pin") or "")
            except (ValueError, AttributeError):
                self._send({"error": "Bad request."}, 400)
                return False
            now = time.time()
            with LAN_LOCK:  # the try is counted BEFORE the slow check, so a burst of parallel tries still runs into the limit
                count, since = LAN["fails"].get(ip, (0, now))
                if now - since > LAN_WINDOW:
                    count, since = 0, now
                recent = [t for t in LAN["all"] if now - t < LAN_WINDOW]
                blocked = count >= LAN_TRIES or len(recent) >= LAN_ALL
                if not blocked:
                    LAN["fails"][ip] = (count + 1, since)
                    recent.append(now)
                LAN["all"] = recent
            if blocked:
                self._send({"error": "Too many tries. Wait a minute."}, 429)
                return False
            if hmac.compare_digest(_pin_hash(pin, cfg["salt"]), cfg["hash"]):
                with LAN_LOCK:
                    LAN["fails"].pop(ip, None)
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Set-Cookie", f"ledger_auth={_lan_token(cfg)}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.end_headers()
                self.wfile.write(body)
            else:
                time.sleep(0.3)
                self._send({"error": "Wrong PIN."}, 401)
            return False
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        if "ledger_auth" in jar and hmac.compare_digest(jar["ledger_auth"].value, _lan_token(cfg)):
            if sys.platform == "win32":  # a phone in use counts as activity, so the PC's idle sleep timer starts over
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetThreadExecutionState(0x00000001)  # ES_SYSTEM_REQUIRED
                except Exception:
                    pass
            return True
        if post or path.startswith("/api/"):
            self._send({"error": "PIN needed."}, 401)
        else:
            self._send(PIN_PAGE.encode(), 200, "text/html; charset=utf-8")
        return False

    def _guard(self, post: bool) -> bool:
        """This ledger answers this PC, plus (only if you turn on phone access) PIN-holding devices on your home network.
        Turn away odd Host names (DNS rebinding tricks) and, for changes, other websites (they can't send our custom
        header or a matching Origin)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            if not self._lan_gate(post, host):
                return False
        elif host not in ("localhost", "127.0.0.1", "::1"):
            self._send({"error": "Blocked: unexpected address."}, 403)
            return False
        if post:
            origin = self.headers.get("Origin")
            if self.headers.get("X-Ledger") != "1" or (origin and urlparse(origin).netloc != (self.headers.get("Host") or "")):
                self._send({"error": "Blocked: this request didn't come from the ledger page."}, 403)
                return False
        return True

    def do_GET(self) -> None:
        if self._guard(False):
            with LOCK:  # one request at a time: two devices can't write the same file at once
                self._get()

    def do_POST(self) -> None:
        if not self._guard(True):
            return
        with LOCK:
            self._post()

    def _get(self) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        rel = u.path.lstrip("/") or "index.html"
        try:
            if u.path == "/api/theme":
                return self._send(theme_payload())
            if u.path == "/api/devstamp":  # only for the optional dev_reload setting: the newest change time among the page's files
                if not real_settings().get("dev_reload"):
                    return self._send({"stamp": 0})
                return self._send({"stamp": max((f.stat().st_mtime for f in (HERE / "static").rglob("*") if f.is_file()), default=0)})
            if u.path == "/api/meta":
                maybe_extend()
                m = meta(Ctx())
                if not self._is_local():
                    m["data_dir"] = ""  # a phone has no use for the PC's folder path
                return self._send(m)
            if u.path.startswith("/api/email") and not self._is_local():
                return self._send({"error": "Email settings are only available on the PC itself."}, 403)
            if u.path == "/api/overview":
                c = Ctx()
                return self._send(overview(c, q.get("period") or fd.current_period(c.starts)))
            if u.path == "/api/transactions":
                return self._send(transactions(Ctx()))
            if u.path == "/api/animcss":
                return self._send(anim_css_html().encode(), ctype="text/css; charset=utf-8")
            if u.path == "/api/email/task":  # looked up apart from the Email tab itself, because Task Scheduler is slow to answer
                return self._send(task_find())
            if u.path == "/api/email":
                return self._send(email_state())
            if u.path.startswith("/email_assets/pokemon/") and u.path.endswith(".png"):
                f = POKE_DIR / Path(u.path).name
                if f.is_file():
                    return self._send(f.read_bytes(), ctype="image/png")
                return self._send({"error": "not found"}, 404)
            if u.path == "/api/analysis":
                return self._send(clean(bills_trend(Ctx(), q.get("from") or "", q.get("to") or "")))
            if u.path == "/api/forecast":
                return self._send(forecast_state(Ctx()))
            if u.path == "/api/forecast/debt":
                return self._send(debt_summary(float(q.get("extra", 0)), q.get("through") or date.today().isoformat()))
            if u.path == "/api/plan":
                c = Ctx()
                return self._send(plan_state(c, q.get("period") or fd.current_period(c.starts)))
            f = HERE / "static" / rel
            if f.is_file() and HERE / "static" in f.resolve().parents:
                types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css", ".svg": "image/svg+xml"}
                return self._send(f.read_bytes(), ctype=types.get(f.suffix, "application/octet-stream"))
            self._send({"error": "not found"}, 404)
        except Exception as e:  # show the problem in the page instead of a blank screen
            import traceback
            traceback.print_exc()
            self._send({"error": str(e) if self._is_local() else "Something went wrong."}, 500)

    def _post(self) -> None:
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= 60_000_000:  # a negative or silly length would make the read wait for ever
            return self._send({"error": "Bad request."}, 400)
        try:
            b = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send({"error": "Bad request."}, 400)
        if urlparse(self.path).path.startswith("/api/email/") and not self._is_local():
            return self._send({"error": "Email settings and sending are only available on the PC itself."}, 403)
        GROUP[0] += 1
        extra: dict = {}  # anything a route wants to hand back besides the message (the new row's id for Add)
        try:
            p = urlparse(self.path).path
            if p == "/api/import/preview":
                return self._send(import_preview(b["name"], b["data"]))
            if p == "/api/tx/delete":
                msg = f"Deleted {tx_delete(b['ids'])} transaction(s)."
            elif p == "/api/tx/category":
                msg = f"Moved {tx_category(b['ids'], b['category'])} to {b['category'] or 'Uncategorized'}."
            elif p == "/api/tx/add":
                extra["id"] = tx_add(b)  # the page needs the new row's id to ask about a brand-new category
                msg = "Added the transaction."
            elif p == "/api/category/suggest":
                return self._send(category_suggest(b["id"]))
            elif p == "/api/category/matches":
                return self._send(keyword_matches(str(b.get("keyword", ""))))
            elif p == "/api/category/learn":
                return self._send(learn_info(b.get("ids", []), b.get("category", "")))
            elif p == "/api/category/rule":
                msg = rule_add(b)
            elif p == "/api/category/new":
                msg = new_category(b)
            elif p == "/api/savings/seen":
                msg = savings_seen(bool(b.get("add")))
            elif p == "/api/import/snooze":
                msg = snooze_import()
            elif p == "/api/tx/autocat":
                msg = tx_autocat()
            elif p == "/api/savings/move":
                msg = savings_move(b["ids"])
            elif p == "/api/savings/back":
                msg = savings_take_back(b["ids"])
            elif p == "/api/nudge/accept":
                c0 = Ctx()
                upd = c0.pinc.sort_values("amount", ascending=False).reset_index(drop=True)
                upd.loc[upd["source"].str.lower() == str(b["source"]).lower(), "amount"] = float(b["actual"])
                msg = income_save(upd[["source", "amount"]].to_dict("records"), {})
            elif p == "/api/nudge/dismiss":
                msg = dismiss("dismissed_nudges", f"{b['source']}|{float(b['actual']):.2f}")
            elif p == "/api/plan/expenses/preview":
                return self._send(expenses_preview(b["rows"]))
            elif p == "/api/plan/income/preview":
                return self._send(income_preview(b["rows"]))
            elif p == "/api/plan/expenses":
                msg = expenses_save(b["rows"], b.get("starts_on"), b.get("cancels"))
            elif p == "/api/plan/income":
                msg = income_save(b["rows"], b.get("cancels"))
            elif p == "/api/plan/periods":
                msg = add_periods(b["n"])
            elif p == "/api/plan/undo_rec":
                msg = "Restored your plan from before the last save." if fd.restore_recurring() else "Nothing to restore."
            elif p == "/api/plan/rules":
                msg = rules_save(b["rows"])
            elif p == "/api/plan/limits":
                msg = limits_save(b["rows"])
            elif p == "/api/plan/budgets":
                msg = budgets_save(b["rows"])
            elif p == "/api/plan/xcats":
                msg = xcats_save(b["rows"])
            elif p == "/api/email/save":
                msg = email_save(b)
            elif p == "/api/email/preview":
                return self._send(email_preview(b))
            elif p == "/api/email/test":
                msg = email_test(b)
            elif p == "/api/email/send":
                msg = email_send_now()
            elif p == "/api/import/commit":
                msg = import_commit(b)
            elif p == "/api/setup/period":
                msg = setup_period(b)
            elif p == "/api/setup/sample":
                msg = setup_sample(b)
            elif p == "/api/period/switch":
                msg = period_switch(b)
            elif p == "/api/mode":
                set_data_dir(bool(b["test"]))
                msg = "Sample data is on." if b["test"] else "Back to your real data."
            elif p == "/api/test/shuffle":
                import random
                msg = "Shuffled the test data: " + fd.seed_test_data(fd.TEST_DIR, shuffle=random.randrange(1, 1_000_000)) + "."
            elif p == "/api/test/reset":
                fd.seed_test_data(fd.TEST_DIR)
                msg = "Test data reset to the original sample."
            elif p == "/api/idea/accept":
                msg = idea_accept(b["item"], b["limit"])
            elif p == "/api/idea/dismiss":
                msg = dismiss("dismissed_budget_ideas", b["key"])
            elif p == "/api/twin/merge":
                msg = rename_all(b["old"], b["new"]).replace("Renamed", "Merged")
            elif p == "/api/twin/dismiss":
                msg = dismiss("dismissed_twins", f"{b['key']}|{b['new'].lower()}")
            elif p == "/api/settings":
                msg = settings_update(b["set"])
            elif p == "/api/forecast/debts":
                msg = debts_save(b["rows"])
            elif p == "/api/payback/link":
                msg = payback_set(b["id"], b["item"], True)
            elif p == "/api/payback/unlink":
                msg = payback_set(b["id"], "", False)
            elif p == "/api/payback/dismiss":
                msg = dismiss("dismissed_paybacks", f"{b['id']}|{str(b['item']).lower()}")
            elif p == "/api/onetime/apply":
                msg = onetime_apply(b["id"], b["name"])
            elif p == "/api/onetime/dismiss":
                msg = dismiss("onetime_dismissed", f"{b['name']}|{b['id']}")
            elif p == "/api/forecast/onetime":
                msg = onetime_save(b["rows"])
            elif p == "/api/plan/rename":
                msg = rename_all(b["old"], b["new"])
            elif p == "/api/marks":  # bills paid some other way (check, cash, another account), for one pay period
                marks = fd.load("paid_marks")
                keep = marks[marks["period_start"] != b["period"]]
                new = pd.DataFrame({"period_start": b["period"], "item": b["items"]})
                save("paid_marks", pd.concat([keep, new], ignore_index=True))
                msg = "Saved."
            elif p == "/api/lan/set":
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._send({"error": "Change phone access on the PC itself."}, 403)
                msg = lan_set(bool(b.get("enabled")), str(b.get("pin") or ""), bool(b.get("signout")))
            elif p == "/api/undo":
                msg = undo()
            else:
                return self._send({"error": "not found"}, 404)
            self._send(dict(ok=True, message=msg, can_undo=bool(JOURNAL), **extra))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send(dict(ok=False, error=str(e) if self._is_local() else "Something went wrong."), 500)

    def log_message(self, *a) -> None:
        pass


if __name__ == "__main__":
    if "--test" in sys.argv:
        set_data_dir(True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)  # this PC only: nothing opens the ledger to other devices
    url = f"http://127.0.0.1:{PORT}"
    if lan_cfg().get("enabled") and not RESTART[0]:  # phone access was left on: open the network listener again
        try:
            lan_start()
        except OSError as e:
            print(f"Phone access could not start: {e}")
    print(f"Personal Finance Ledger at {url}   data: {fd.DATA_DIR}   (Ctrl+C to stop)")
    if "--open" in sys.argv:
        webbrowser.open(url)
    if "--watch" in sys.argv:  # restart by itself when this script or FinanceDashboard.py changes, so a refresh picks it up
        import threading
        import time

        def watch() -> None:
            files = [Path(__file__).resolve(), ROOT / "FinanceDashboard.py"]
            last = {f: f.stat().st_mtime for f in files}
            while True:
                time.sleep(1.5)
                try:
                    if any(f.stat().st_mtime != last[f] for f in files):
                        time.sleep(0.6)  # let an editor finish saving
                        last.update({f: f.stat().st_mtime for f in files})
                        try:  # never restart into a file with a typo: keep the working copy running until it's fixed
                            for f in files:
                                compile(f.read_text(encoding="utf-8"), str(f), "exec")
                        except SyntaxError as e:
                            print(f"Not restarting: {e}")
                            continue
                        RESTART[0] = True
                        srv.shutdown()
                        return
                except OSError:
                    pass
        threading.Thread(target=watch, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    if RESTART[0]:
        import subprocess
        time.sleep(0.5)
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *[a for a in sys.argv[1:] if a != "--open"]],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
