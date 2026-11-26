"""
FinanceDashboard.py - the Personal Finance Ledger's shared logic (paycheck-period budgeting).

There is no screen in this file any more. The web page lives in ledger_html/ (run `python ledger_html/server.py`, or
double-click "Open Ledger.pyw"), and FinanceEmail.py sends the payday email. Both import this file for the numbers
(bill status, rollover, savings, categorising, payoff, themes), so they always agree.

Data lives in ./finance_data/*.csv next to this script (override with the FINANCE_DATA_DIR environment variable).
Nothing leaves your machine.
"""

import calendar
import difflib
import hashlib
import json
import os
import random
from html import escape as html_escape
import re
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path


import numpy as np
import pandas as pd

# ======================================================================
# DATA LAYER
# ======================================================================
DATA_DIR = Path(os.environ.get("FINANCE_DATA_DIR", Path(__file__).parent / "finance_data"))
REAL_DIR = DATA_DIR  # your real data. DATA_DIR is only switched to TEST_DIR while Test data is on
TEST_DIR = DATA_DIR.parent / f"{DATA_DIR.name}_test"  # made-up sample data, kept apart from your real files
PERIOD_DAYS = 14
FLIP_SIGN = True  # your bank exports spending as positive; flipped on every import. Set False if that ever changes.
KINDS = ["bill", "budget", "extra"]

SCHEMAS = {
    "periods":      ["period_start"],
    "plan":         ["period_start", "item", "kind", "due_day", "amount"],
    "income":       ["period_start", "source", "amount"],
    "transactions": ["id", "date", "description", "amount", "category", "pending"],
    "rules":        ["keyword", "category"],
    "onetime":      ["name", "date", "amount"],  # known one-time expenses ahead (Cash Forecast only, not transactions)
    "budgets":      ["category", "limit"],  # money set aside for the paycheck: held back from Safe to spend
    "limits":       ["category", "limit"],  # a yardstick only: shows under/over for a category, holds nothing back
    "debts":       ["name", "start_balance", "current_balance", "min_payment", "apr", "in_email"],
    "recurring":    ["item", "due_day", "amount", "freq", "month"],  # freq/month: how often, and which month it starts
    "planned_income": ["source", "amount"],
    "paid_marks":   ["period_start", "item"],
    "income_overrides": ["period_start", "source"],
    "extra_categories": ["name", "one_off"],
}
NUMERIC = {"amount", "due_day", "month", "limit", "start_balance", "current_balance", "min_payment", "apr"}
DEFAULT_TX_FOLDER = ""  # unused: bank files are imported with the Import button, not read from a folder
DEFAULT_SETTINGS = {"debt_threshold": 500.0, "opening_balance": 0.0,
                    "tx_folder": DEFAULT_TX_FOLDER, "auto_import": False, "last_import": "", "overview_actuals": False,
                    "theme": "soft", "dark_mode": False, "terminal_style": False,
                    "animations": True, "anim_speed": "Calm", "anim_style": "Prismatic", "anim_bg": "",  # "" = follow the style
                    "anim_menu": True,
                    "savings_moved": [],  # ids of extra-income deposits you moved to savings (still Income, but not spendable)
                    "dismissed_nudges": [], "dismissed_budget_ideas": [], "dismissed_twins": [], "bank_balance": {},
                    "import_prompt_snoozed": "", "savings_have": 0.0, "savings_apy": 4.0}

SAVINGS_WORD = "savings"  # any category with this in its name is set-aside money, not income or spending


def savings_mask(cat: pd.Series) -> pd.Series:
    return cat.fillna("").astype(str).str.lower().str.contains(SAVINGS_WORD, regex=False)


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        elif c in ("pending", "in_email", "one_off"):
            df[c] = df[c].map(lambda v: str(v).strip().lower() in ("true", "1", "yes")).astype(bool)
        else:
            df[c] = df[c].fillna("").astype(str).str.strip().replace({"None": "", "nan": ""})
    return df.reset_index(drop=True)


def load(name: str) -> pd.DataFrame:
    cols = SCHEMAS[name]
    f = DATA_DIR / f"{name}.csv"
    df = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=cols)
    if name == "debts" and "in_email" not in df.columns and len(df):
        df["in_email"] = "True"
    for c in cols:
        if c not in df:
            df[c] = None
    return coerce(df[cols])


def save(name: str, df: pd.DataFrame, keep_backup: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if name in ("plan", "income") and not keep_backup:
        drop_backup()  # Undo only applies to the most recent Apply, so any other plan edit clears it
    coerce(df.reindex(columns=SCHEMAS[name])).to_csv(DATA_DIR / f"{name}.csv", index=False)


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    f = DATA_DIR / "settings.json"
    if f.exists():
        s.update(json.loads(f.read_text()))
    return s


def save_settings(s: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "settings.json").write_text(json.dumps(s))


# ---------- periods ----------
# A pay period is either "biweekly" (14 days, one per paycheck) or "monthly" (from one day of the month to the day before
# the next). Which one is saved in this data folder's settings.json as `period_layout`, a list of
# {"from": "2026-12-01", "mode": "monthly", "day": 1}: each entry applies from its date on, so a person can switch later and
# the periods before the switch keep the length they had. No layout means biweekly, which is how the ledger always worked.
MODES = ("biweekly", "monthly")
_LAYOUT: dict = {}


def period_layout() -> list[dict]:
    """The saved layout for the current data folder, oldest first (empty = biweekly throughout). Re-read when the file changes."""
    f = DATA_DIR / "settings.json"
    try:
        stamp = (str(f), f.stat().st_mtime_ns)
    except OSError:
        return []
    if _LAYOUT.get("stamp") != stamp:
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig")).get("period_layout") or []
        except Exception:
            raw = []
        segs = []
        for x in raw:
            try:
                date.fromisoformat(str(x["from"]))
                if x.get("mode") in MODES:
                    segs.append(dict(from_=str(x["from"]), mode=x["mode"], day=max(1, min(int(x.get("day") or 1), 31))))
            except Exception:
                continue
        segs = sorted(({"from": g["from_"], "mode": g["mode"], "day": g["day"]} for g in segs), key=lambda g: g["from"])
        _LAYOUT.update(stamp=stamp, layout=segs)
    return _LAYOUT["layout"]


def _as_date(d) -> date:
    return d if isinstance(d, date) and not isinstance(d, datetime) else (d.date() if isinstance(d, datetime) else date.fromisoformat(str(d)[:10]))


def layout_at(d) -> dict:
    """The layout entry in force on a date: {mode, day}."""
    seg, iso = {"mode": "biweekly", "day": 1}, _as_date(d).isoformat()
    for g in period_layout():
        if g["from"] <= iso:
            seg = g
    return seg


def period_end(start) -> date:
    """The last day of the pay period that starts on `start`."""
    s_ = _as_date(start)
    seg = layout_at(s_)
    if seg["mode"] == "monthly":
        y, m = s_.year, s_.month
        nxt = date(y, m, min(seg["day"], calendar.monthrange(y, m)[1]))
        if nxt <= s_:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            nxt = date(y, m, min(seg["day"], calendar.monthrange(y, m)[1]))
        return nxt - timedelta(days=1)
    return s_ + timedelta(days=PERIOD_DAYS - 1)


def next_start(start) -> date:
    return period_end(start) + timedelta(days=1)


def period_days(start) -> int:
    return (period_end(start) - _as_date(start)).days + 1


def period_mode(on=None) -> str:
    """'biweekly' or 'monthly' for the period containing `on` (default: today)."""
    return layout_at(on or date.today())["mode"]


def label(start: str) -> str:
    s = date.fromisoformat(start)
    e = period_end(s)
    return f"{s:%b %d} – {e:%b %d, %Y}"


def all_period_starts(plan, income, periods) -> list[str]:
    s = set(periods["period_start"]) | set(plan["period_start"]) | set(income["period_start"])
    return sorted(x for x in s if x)


def current_period(starts: list[str]) -> str:
    today = date.today().isoformat()
    past = [s for s in starts if s <= today]
    return past[-1] if past else starts[0]


def assign_period(dates: pd.Series, starts: list[str]) -> pd.Series:
    """The pay period (its start date, as text) each date falls in; "" when it falls in none."""
    if not starts or dates.empty:
        return pd.Series([""] * len(dates), index=dates.index, dtype=str)
    ts = pd.to_datetime(pd.Series(starts)).sort_values()
    arr = ts.to_numpy().astype("datetime64[ns]")
    iso = ts.dt.strftime("%Y-%m-%d").to_numpy()
    dv = pd.to_datetime(dates, errors="coerce").to_numpy().astype("datetime64[ns]")
    idx = np.searchsorted(arr, dv, side="right") - 1
    ok = (idx >= 0) & ~np.isnat(dv)
    ends = np.array([np.datetime64(period_end(d_)) for d_ in ts.dt.date]).astype("datetime64[ns]")  # each period's last day
    ok[ok] = dv[ok] <= ends[idx[ok]]
    return pd.Series(np.where(ok, iso[np.clip(idx, 0, None)], ""), index=dates.index)


def period_summary(starts, plan, income, settings) -> pd.DataFrame:
    rows, running = [], settings["opening_balance"]
    aside = settings.get("_setaside") or {}  # money taken out of what's spendable (moved to savings), per pay period
    for s in starts:
        inc = income.loc[income.period_start == s, "amount"].sum()
        exp = plan.loc[plan.period_start == s, "amount"].sum()
        running += inc - exp - float(aside.get(s, 0.0))
        rows.append(dict(period_start=s, label=label(s), income=inc, expenses=exp, net=inc - exp,
                         available=running, debt_available=running - settings["debt_threshold"]))
    return pd.DataFrame(rows)


def bank_balance_from(raw: pd.DataFrame, spec: dict | None = None) -> dict | None:
    """The account balance a bank export reports: the balance after its newest posted row, less pending debits (holds
    that haven't posted yet). A pending DEPOSIT is not in that balance yet, so it is left out: it is usually the
    next paycheck landing a day or two early, and belongs to that paycheck. (`v` = 2 marks this rule; balances saved
    by older versions also added pending deposits.) None when the export has no Balance column."""
    bcol = next((c for c in raw.columns if str(c).strip().lower() in ("balance", "running balance", "ledger balance", "running bal.", "running bal")), None)
    if bcol is None:
        return None
    g = spec or guess_import(raw)
    dcol, acol, scol = g["dcol"] if "dcol" in g else g["date"], g.get("acol", g.get("amount", "")), g["scol"] if "scol" in g else g["desc"]
    dates, _ = _dates_amounts(raw, dcol, acol, scol, with_amount=bool(acol))
    pend = pending_mask(raw, dcol).to_numpy()
    bal = _to_number(raw[bcol])
    ok = (~pend) & dates.notna().to_numpy() & bal.notna().to_numpy()
    if not ok.any():
        return None
    d, b = dates[ok], bal[ok]
    newest = d.max()
    ties = list(d[d == newest].index)
    row = ties[0] if d.iloc[0] >= d.iloc[-1] else ties[-1]  # newest-first files list the newest row first
    parsed = parse_bank(raw, dcol, acol, scol, g.get("debit", ""), g.get("credit", ""), g.get("spending", "positive"))
    holds = float(parsed.loc[parsed["pending"] & (parsed["amount"] < 0), "amount"].sum())
    return dict(as_of=newest.strftime("%Y-%m-%d"), balance=round(float(b.loc[row]) + holds, 2), v=2)


def capture_bank_balance(raw: pd.DataFrame, settings: dict, spec: dict | None = None) -> dict:
    """Settings with the bank balance from this import remembered (only if it's at least as new as the one kept)."""
    info = bank_balance_from(raw, spec)
    if info and info["as_of"] >= (settings.get("bank_balance") or {}).get("as_of", ""):
        return {**settings, "bank_balance": info}
    return settings


def reconciled_opening(starts: list[str], eplan: pd.DataFrame, inc_eff: pd.DataFrame, tx: pd.DataFrame,
                       pnames: set, settings: dict) -> tuple[float, dict | None]:
    """The opening balance that makes the rollover agree with the real bank balance.
    Left for the paycheck the balance was taken in = bank balance + paychecks still to land - what's still to pay.
    That fixes the starting point, so mistakes in older history can't carry forward. Without a known bank balance
    this is just the stored opening balance."""
    mv = set(settings.get("savings_moved") or [])  # deposits moved to savings: still income, but not spendable
    opening = float(settings["opening_balance"])
    bb = settings.get("bank_balance") or {}
    if not bb or not starts:
        return opening, None
    p = assign_period(pd.Series([bb["as_of"]]), starts).iloc[0]
    if not p:
        return opening, None
    bank_rows = tx[~tx["id"].str.startswith("m-")]
    newest = str(bank_rows["date"].max()) if len(bank_rows) else ""
    if not newest or newest < (pd.Timestamp(bb["as_of"]) - pd.Timedelta(days=2)).strftime("%Y-%m-%d"):
        return opening, None  # the transactions behind that balance are missing, so it can't be used
    # rows the bank balance already includes: bank transactions up to its date (and the holds it was reduced by).
    # Hand-entered rows, and anything dated after the balance, are not in it yet, so they still reduce what's left.
    hand = tx["id"].str.startswith("m-")
    in_bank = tx[~hand & ((tx["date"] <= bb["as_of"]) | tx["pending"].astype(bool))]
    not_in_bank = tx[hand | ((tx["date"] > bb["as_of"]) & ~tx["pending"].astype(bool))]
    # Pending deposits: one dated inside this paycheck is about to land, so it counts; one dated in a LATER paycheck
    # (next payday's pay arriving early) is not this paycheck's money. A balance saved by an older version also
    # counted every pending deposit, so those for later paychecks are taken back out here.
    credit = ~hand & tx["pending"].astype(bool) & (tx["amount"] > 0)
    in_p = assign_period(tx["date"], starts) == p
    bank = float(bb["balance"]) + (float(tx.loc[credit & in_p, "amount"].sum()) if bb.get("v")
                                   else -float(tx.loc[credit & ~in_p, "amount"].sum()))
    # A pending hold dated in a LATER paycheck is already taken out of the bank balance, but it belongs to that paycheck's
    # expenses. Put it back here so it is deducted once (in its own paycheck) and not twice.
    later = ~hand & tx["pending"].astype(bool) & (tx["amount"] < 0) & (assign_period(tx["date"], starts) > p)
    bank -= float(tx.loc[later, "amount"].sum())
    # Money set aside for savings that is still sitting in that balance (a deposit tagged Savings, or one you moved to
    # savings) isn't spendable, so it comes back out of what's left. A transfer to savings that has already left the
    # account cancels it: the bank balance dropped by that much on its own, so nothing is taken out twice.
    _r, rem_in, _d = savings_flow(in_bank, starts, settings)
    pend_ids = set(in_bank.loc[in_bank["pending"].astype(bool), "id"])
    day_of = dict(zip(in_bank["id"], in_bank["date"]))
    p_of = assign_period(pd.Series([day_of[i_] for i_ in rem_in]), starts) if rem_in else pd.Series(dtype=str)
    held = 0.0
    for (i_, amt_), p_i in zip(rem_in.items(), p_of):
        if i_ not in pend_ids or (bool(bb.get("v")) and p_i == p):
            held += amt_
    bank -= held
    planned_total = float(eplan.loc[eplan.period_start == p, "amount"].sum())
    sp = spend_by_category(in_bank, starts)
    spent = float(np.maximum(-sp.loc[sp.period_start == p, "net"], 0.0).sum())
    to_leave = max(planned_total - spent, 0.0)
    planned_in = float(inc_eff[(inc_eff.period_start == p) & (inc_eff["kind"] == "planned")]["amount"].sum())
    landed = paycheck_actuals(in_bank, starts, pnames)
    late = not_in_bank[(assign_period(not_in_bank["date"], starts) == p) & (not_in_bank["amount"] > 0)
                       & not_in_bank["category"].str.lower().str.contains("income")
                       & ~not_in_bank["category"].str.lower().isin(pnames)
                       & ~savings_mask(not_in_bank["category"]) & ~not_in_bank["id"].isin(mv)]
    to_arrive = max(planned_in - float(landed.loc[landed.period_start == p, "amount"].sum()), 0.0) \
        + float(late["amount"].sum())
    left = bank + to_arrive - to_leave
    aside_r, _o, _d2 = savings_flow(tx, starts, settings)
    old = period_summary(starts, eplan, inc_eff, {**settings, "_setaside": aside_r}).set_index("period_start").loc[p, "available"]
    offset = left - float(old)
    return opening + offset, dict(period=p, as_of=bb["as_of"], bank=bank, to_leave=to_leave,
                                  to_arrive=to_arrive, left=left, offset=offset)


# ---------- transactions ----------
def make_ids(df: pd.DataFrame) -> pd.Series:
    key = df["date"] + "|" + df["description"] + "|" + df["amount"].round(2).astype(str)
    n = key.groupby(key).cumcount().astype(str)
    return (key + "|" + n).map(lambda s: hashlib.md5(s.encode()).hexdigest()[:12])


def debit_credit_sign(raw: pd.DataFrame):
    """If the export has a Debit/Credit style type column, return -1/+1/0 per row (else None)."""
    for c in raw.columns:
        if c.strip().lower() in ("transaction type", "type", "debit/credit", "credit/debit", "dr/cr"):
            v = raw[c].fillna("").astype(str).str.lower()
            if v.str.contains("debit|withdraw|credit|deposit").mean() > 0.5:
                return np.where(v.str.contains("debit|withdraw"), -1, np.where(v.str.contains("credit|deposit"), 1, 0))
    return None


DESC_DATE = re.compile(r"Date\s+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)


def _to_number(col: pd.Series) -> pd.Series:
    t = (col.astype(str).str.replace(r"^\((.*)\)$", r"-\1", regex=True).str.replace(r"[$,\s]", "", regex=True))
    return pd.to_numeric(t, errors="coerce")


def _dates_amounts(raw: pd.DataFrame, dcol: str, acol: str, scol: str, with_amount: bool = True):
    """Dates and amounts with fallbacks for pending rows: other date columns, then the 'Date 09/28/26'
    that debit-card descriptions carry; other amount columns if the main one is blank."""
    dates = pd.to_datetime(raw[dcol], errors="coerce")
    for c in raw.columns:
        if c != dcol and "date" in c.lower():
            dates = dates.fillna(pd.to_datetime(raw[c], errors="coerce"))
    in_desc = raw[scol].fillna("").astype(str).str.extract(DESC_DATE, expand=False)
    dates = dates.fillna(pd.to_datetime(in_desc, format="mixed", errors="coerce"))
    for c in raw.columns:  # pending holds: the transaction id often starts with a YYYYMMDD date
        if "transaction id" in c.lower() or c.strip().lower() == "id":
            ids = raw[c].fillna("").astype(str).str.extract(r"^\s*(20\d{6})", expand=False)
            from_id = pd.to_datetime(ids, format="%Y%m%d", errors="coerce")
            latest = dates.max()
            if pd.notna(latest):  # ignore ids dated way in the future
                from_id = from_id.where(from_id <= latest + pd.Timedelta(days=7))
            dates = dates.fillna(from_id)
            break
    if dates.isna().any() and dates.notna().any():  # last resort: pending rows are the newest, so use the latest date
        dates = dates.fillna(dates.max())
    if not with_amount:  # separate debit and credit columns: parse_bank works the amount out from those
        return dates, pd.Series(np.nan, index=raw.index)
    amt = _to_number(raw[acol])
    for c in raw.columns:
        if c != acol and "amount" in c.lower():
            amt = amt.fillna(_to_number(raw[c]))
    return dates, amt


def pending_mask(raw: pd.DataFrame, dcol: str) -> pd.Series:
    """Rows still pending at the bank: a status column says so, or there is no posting date yet."""
    m = raw[dcol].isna() | raw[dcol].astype(str).str.strip().eq("")
    for c in raw.columns:
        if "status" in c.lower():
            m = m | raw[c].fillna("").astype(str).str.lower().str.contains("pend")
    return m


def parse_bank(raw: pd.DataFrame, dcol: str, acol: str, scol: str, debit: str = "", credit: str = "",
               spending: str = "positive") -> pd.DataFrame:
    """Transactions from a bank export. Inside the ledger, money spent is negative and money earned is positive.
    The amount comes one of three ways: a Debit and a Credit column (`debit` and `credit`, `acol` blank), a single amount
    column where `spending` says which sign the bank uses for money spent ("positive" or "negative"), or a single amount
    column plus a Debit/Credit type column, which decides per row."""
    split = bool(debit and credit and not acol)
    dates, amt = _dates_amounts(raw, dcol, acol, scol, with_amount=not split)
    df = pd.DataFrame({
        "date": dates.dt.strftime("%Y-%m-%d"),
        "description": raw[scol].fillna("").astype(str).str.strip(),
        "amount": amt,
        "category": "",
    })
    flip = 1.0 if spending == "negative" else (-1.0 if FLIP_SIGN else 1.0)
    sign = None if split else debit_credit_sign(raw)
    if split:  # money in minus money out, whichever sign the bank prints on each
        cr, db = _to_number(raw[credit]), _to_number(raw[debit])
        df["amount"] = (cr.abs().fillna(0.0) - db.abs().fillna(0.0)).where(~(cr.isna() & db.isna())).to_numpy()
    elif sign is not None:  # a Debit/Credit column is authoritative per row; rows it can't classify use the flip rule
        df["amount"] = np.where(sign == 0, df["amount"] * flip, df["amount"].abs() * sign)
    else:
        df["amount"] = df["amount"] * flip
    df["pending"] = pending_mask(raw, dcol).to_numpy()
    df = df.dropna(subset=["date", "amount"]).reset_index(drop=True)
    df["id"] = make_ids(df)
    df.attrs["skipped"] = int(len(raw) - len(df))  # rows with no usable date or amount
    return df


def categorize(df: pd.DataFrame, rules: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Stamp a category on rows that have none, using first-match 'contains' rules."""
    rl = [(k.strip().upper(), c.strip()) for k, c in zip(rules["keyword"], rules["category"])
          if k.strip() and c.strip()]
    df = df.copy()
    cats, stamped = df["category"].tolist(), 0
    for i, desc in enumerate(df["description"].str.upper().tolist()):
        if cats[i].strip():
            continue
        core = re.sub(r"^POS HOLD,?\s*", "", desc)  # pending holds truncate the merchant text
        for kw, cat in rl:
            if kw in desc or (len(core) >= 10 and kw.startswith(core)):
                cats[i], stamped = cat, stamped + 1
                break
        else:  # no rule of yours matched: a transfer out of checking to savings is recognized by its description
            if float(df["amount"].iloc[i]) < 0 and SAVINGS_TRANSFER.search(desc):
                cats[i], stamped = "Savings", stamped + 1
    df["category"] = cats
    return df, stamped


_DESC_LEAD = re.compile(r"^(?:#\d+\s+|POS HOLD,?\s*|POS DEBIT\s+|POS\s+|WITHDRAWAL DEBIT CARD\s+|WITHDRAWAL\s+|"
                        r"DEBIT CARD PURCHASE\s+|PURCHASE AUTHORIZED ON \d+/\d+\s+|CHECKCARD\s+|RECURRING PAYMENT\s+|"
                        r"ACH DEBIT\s+|ONLINE PAYMENT\s+)+")
_DESC_PROCESSOR = re.compile(r"^(?:SQ|DD|TST|PAR|PP|PY|GOOGLE|AMZN MKTP)\s*\*\s*")
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


def description_keyword(desc: str, max_words: int = 3) -> str:
    """The part of a bank description that identifies the merchant, to use as an auto-categorize rule: it drops the
    card/ACH lead-in ('WITHDRAWAL DEBIT CARD', '#630713403712 POS'), payment-processor tags ('SQ *'), then keeps the first
    few words, stopping at a store number, phone number, date, 'TYPE:' or a dash, and dropping a trailing state code."""
    s = re.sub(r"\s+", " ", str(desc or "").upper().strip())
    prev = None
    while prev != s:  # leads can stack ('#123 POS ...')
        prev = s
        s = _DESC_LEAD.sub("", s)
    s = _DESC_PROCESSOR.sub("", s)
    words: list[str] = []
    for w in s.split(" "):
        if (not w or w.endswith(":") or w in ("DATE", "-", "–") or w.startswith("#")
                or re.fullmatch(r"[\d\-\(\)\.]+", w) or re.fullmatch(r"X+\d+", w)
                or (words and re.search(r"\.(COM|GOV|ORG|NET|UK|CO)\b", w))):
            break
        words.append(w)
        if len(words) >= max_words:
            break
    while len(words) > 1 and _STATE_CODE.match(words[-1]):
        words.pop()
    kw = " ".join(words).strip(" *-")
    return kw if len(kw) >= 3 else s[:24].strip()


SAVINGS_TRANSFER = re.compile(r"\bTO\b.*\bSAVINGS\b", re.I)  # 'Transfer To ... Share 19 ... to Savings 0019'


def savings_flow(tx: pd.DataFrame, starts: list[str], settings: dict) -> tuple[dict, dict, dict]:
    """How money set aside for savings leaves what you can spend.

    Two kinds of deposit can be set aside while they sit in checking: one tagged Savings (never counted as income) and
    one you moved to savings (still counted as Income). A transfer to savings leaves the account (negative, tagged
    Savings) and is matched against them oldest first.
      * a deposit you moved takes its amount out of spendable in the pay period you moved it, until the real transfer
        posts; from then on it comes out in the pay period of that transfer (the day the money really left)
      * a transfer matched to a tagged deposit changes nothing (that deposit never counted)
      * a transfer matching nothing (you moved the money straight at the bank) simply reduces spendable that day
    Returns (amount taken out per pay period, still-in-checking amount per deposit id, unmatched amount per transfer id)."""
    if tx.empty or not starts:
        return {}, {}, {}
    ids = set(settings.get("savings_moved") or [])
    moved_on = settings.get("savings_moved_on") or {}
    t = tx[["id", "date", "amount", "category", "pending"]].copy()
    t["pending"] = t["pending"].astype(bool)
    sav = savings_mask(t["category"])
    ear = t[(t["amount"] > 0) & (t["id"].isin(ids) | sav)].assign(moved=lambda d: d["id"].isin(ids))
    items = [dict(id=r.id, date=r.date, rem=float(r.amount), moved=bool(r.moved))
             for r in ear.sort_values(["date", "id"]).itertuples()]
    now_p = current_period(starts)
    aside: dict = {}
    direct: dict = {}

    def add(p_: str, a_: float) -> None:
        aside[p_ or now_p] = aside.get(p_ or now_p, 0.0) + a_

    def period_of(d_: str) -> str:
        return assign_period(pd.Series([d_]), starts).iloc[0] if d_ else ""

    for o in t[sav & (t["amount"] < 0) & ~t["pending"]].sort_values(["date", "id"]).itertuples():
        left, p_o = -float(o.amount), period_of(o.date)
        for it in items:
            if left <= 0.004:
                break
            if it["rem"] <= 0.004 or it["date"] > o.date:
                continue
            take = min(it["rem"], left)
            it["rem"] -= take
            left -= take
            if it["moved"]:
                add(p_o, take)
        if left > 0.004:
            add(p_o, left)
            direct[o.id] = left
    for it in items:
        if it["moved"] and it["rem"] > 0.004:
            add(period_of(moved_on.get(it["id"], "")), it["rem"])
    return aside, {it["id"]: it["rem"] for it in items}, direct


def actuals(txp: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Returns (income_by_category, spend_by_category) for one period's transactions."""
    t = txp.copy()
    t["category"] = t["category"].replace("", "Uncategorized")
    is_inc = t["category"].str.lower().str.contains("income")
    is_sav = savings_mask(t["category"])
    inc = t[is_inc & ~is_sav].groupby("category")["amount"].sum().clip(lower=0)
    spend = (-t[~is_inc & ~is_sav].groupby("category")["amount"].sum()).clip(lower=0)
    return inc, spend


def spend_by_category(tx: pd.DataFrame, starts: list[str]) -> pd.DataFrame:
    """Net signed amount and transaction count per (pay period, category), income excluded."""
    cols = ["period_start", "category", "net", "count"]
    if tx.empty or not starts:
        return pd.DataFrame(columns=cols)
    t = tx[["date", "category", "amount"]].copy()
    t["period_start"] = assign_period(t["date"], starts)
    t = t[t["period_start"] != ""]
    t["category"] = t["category"].replace("", "Uncategorized")
    t = t[~t["category"].str.lower().str.contains("income") & ~savings_mask(t["category"])]
    if t.empty:
        return pd.DataFrame(columns=cols)
    g = t.groupby(["period_start", "category"])["amount"].agg(["sum", "count"]).reset_index()
    return g.rename(columns={"sum": "net"})[cols]


def budget_limits(budgets: pd.DataFrame) -> dict:
    return {str(c).strip().lower(): (str(c).strip(), float(l)) for c, l in zip(budgets["category"], budgets["limit"])
            if str(c).strip() and pd.notna(l) and l > 0}


def tx_driven_periods(tx: pd.DataFrame, starts: list[str], today: date | None = None) -> set:
    """Pay periods whose numbers come from the bank transactions. A period that already ended but began well before
    your first transaction (more than 2 days) is only partly covered, so it keeps what was recorded for it
    (the old sheet's history) instead of being overwritten by a few days of data."""
    if tx.empty or not starts:
        return set()
    today = today or date.today()
    periods = set(assign_period(tx["date"], starts)) - {""}
    first = pd.to_datetime(tx["date"], errors="coerce").min()
    if pd.isna(first):
        return periods
    first = first.date()
    out = set()
    for p_ in periods:
        start = date.fromisoformat(p_)
        ended = period_end(start) < today
        if not (ended and start < first - timedelta(days=2)):
            out.add(p_)
    return out


def live_extras(plan: pd.DataFrame, tx: pd.DataFrame, starts: list[str], budgets: pd.DataFrame) -> pd.DataFrame:
    """Extras = spending whose category isn't income, isn't a budgeted category, and isn't a scheduled item."""
    cols = ["period_start", "item", "amount", "count"]
    g = spend_by_category(tx, starts)
    if g.empty:
        return pd.DataFrame(columns=cols)
    sched = plan[plan.kind != "extra"]
    skip = set(zip(sched.period_start, sched.item.str.lower()))
    bud = set(budget_limits(budgets))
    g = g[[(p, c.lower()) not in skip and c.lower() not in bud for p, c in zip(g["period_start"], g["category"])]]
    g = g.assign(amount=(-g["net"]).clip(lower=0))
    g = g[g["amount"] > 0].rename(columns={"category": "item"})
    return g[cols].reset_index(drop=True)


def effective_plan(plan: pd.DataFrame, tx: pd.DataFrame, starts: list[str], budgets: pd.DataFrame,
                   include_budgeted: bool = False, today: date | None = None) -> pd.DataFrame:
    """Everything that counts toward a period's planned spending:
      * scheduled items (bills etc.) from the plan,
      * budgeted categories from the Budgets table, in every period: the limit for periods without
        transactions; for periods that have them, actual spend, or the full limit (or actual if higher) when
        `include_budgeted` is on and the pay period hasn't ended yet (closed periods always use what was
        really spent, so history and your rollover never change; periods from the old sheet keep what it recorded),
      * extras: spending in the transactions that is neither of the above (hand-planned extras only
        count for periods that have no transactions yet)."""
    lim = budget_limits(budgets)
    spend = spend_by_category(tx, starts)
    actual = {(r.period_start, r.category.lower()): max(-r.net, 0.0) for r in spend.itertuples()}
    today_d = today or date.today()
    tx_periods = tx_driven_periods(tx, starts, today_d)
    today = today_d.isoformat()

    sched = plan[plan.kind != "extra"]
    scheduled = sched[~sched.item.str.lower().isin(lim)].copy()
    amounts = scheduled["amount"].to_numpy(dtype=float, copy=True)
    first_at: dict = {}
    for pos, k in enumerate(zip(scheduled["period_start"], scheduled["item"].str.lower())):
        paid = actual.get(k, 0.0)
        if paid > 0:  # a bill that has cleared counts at what you actually paid (extra duplicate rows count as 0)
            amounts[pos] = 0.0
            first_at.setdefault(k, pos)
    for k, pos in first_at.items():
        amounts[pos] = actual[k]
    scheduled["amount"] = amounts
    rows = []
    for s_ in starts:
        for key, (name, limit) in lim.items():
            stored = sched[(sched.period_start == s_) & (sched.item.str.lower() == key)]["amount"].sum()
            if s_ in tx_periods:
                amt = actual.get((s_, key), 0.0)
                still_open = period_end(date.fromisoformat(s_)) >= today_d
                if include_budgeted and still_open:  # hold the full budget (or actual if over) until the period ends
                    amt = max(amt, limit)
            elif s_ > today or not stored:
                amt = limit
            else:
                amt = stored
            rows.append(dict(period_start=s_, item=name, kind="budget", due_day=np.nan, amount=amt))
    budgeted = pd.DataFrame(rows, columns=["period_start", "item", "kind", "due_day", "amount"])

    live = live_extras(plan, tx, starts, budgets)
    live = live[live["period_start"].isin(tx_periods)]
    live = live.assign(kind="extra", due_day=np.nan)[["period_start", "item", "kind", "due_day", "amount"]]
    stored_x = plan[(plan.kind == "extra") & ~plan.period_start.isin(tx_periods)]
    out = pd.concat([scheduled, budgeted, stored_x, live], ignore_index=True)
    for c in ("amount", "due_day"):  # empty pieces (e.g. no transactions yet) would otherwise leave object dtype
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def open_onetime(onetime: pd.DataFrame, tx: pd.DataFrame, starts: list[str], today: date | None = None) -> pd.DataFrame:
    """One-time expenses you've planned (name, date, amount) with an `open` flag and the pay period each falls in
    ("" when it is beyond the periods the ledger knows). A row is open until its pay period is over, or until a real
    spend in a category with the same name shows up in that period (the charge has landed, so the real one counts)."""
    today = today or date.today()
    cols = ["name", "date", "amount", "period_start", "open"]
    rows = []
    for o in onetime.itertuples():
        d = pd.to_datetime(o.date, errors="coerce")
        amt = pd.to_numeric(o.amount, errors="coerce")
        if pd.isna(d) or pd.isna(amt) or not amt > 0:
            continue
        p_ = assign_period(pd.Series([d.strftime("%Y-%m-%d")]), starts).iloc[0] if starts else ""
        over = bool(p_) and period_end(date.fromisoformat(p_)) < today
        landed = bool(p_) and not tx.empty and bool(
            ((tx["period_start"] == p_) & (tx["category"].str.lower() == str(o.name).strip().lower()) & (tx["amount"] < 0)).any())
        rows.append(dict(name=str(o.name), date=d.strftime("%Y-%m-%d"), amount=float(amt), period_start=p_ or "",
                         open=not (over or landed)))
    return pd.DataFrame(rows, columns=cols)


def onetime_matches(ot: pd.DataFrame, tx: pd.DataFrame, skip_cats: set, dismissed: list, days: int = 7) -> dict:
    """Real spending that looks like a one-time expense you planned: close to the same amount, within a week of its
    date, not a bill or budget category, not already filed under the expense's name, and not turned down before.
    Returns {transaction id: expense name}, so the Transactions tab can offer to file it and retire the planned entry."""
    out: dict = {}
    if ot.empty or tx.empty:
        return out
    spend = tx[(tx["amount"] < 0) & ~tx["category"].str.lower().isin(skip_cats) & ~savings_mask(tx["category"])]
    when = pd.to_datetime(spend["date"], errors="coerce")
    gone = {str(x).lower() for x in dismissed}
    for o in ot[ot["open"]].itertuples():
        near = spend[((when - pd.Timestamp(o.date)).abs() <= pd.Timedelta(days=days))
                     & ((spend["amount"].abs() - o.amount).abs() <= max(2.0, 0.05 * o.amount))]
        for r in near.itertuples():
            if r.category.strip().lower() != str(o.name).strip().lower() and f"{o.name}|{r.id}".lower() not in gone:
                out.setdefault(r.id, o.name)
    return out


def reversal_pairs(tx: pd.DataFrame, skip_cats: set, days: int = 45) -> set:
    """Money that went out and came back unchanged: a spend and a deposit of exactly the same amount, the deposit coming
    later (within `days`) in a spending-type category (a refund, a reversal, a transfer out and back). Together they are
    nothing, so both ids are returned to be left out of the numbers. A deposit in an Income category, a paycheck name or
    Savings, and hand-entered rows, never pair. Each row pairs at most once, with the nearest earlier spend."""
    if tx.empty:
        return set()
    t = tx[["id", "date", "amount", "category"]].copy()
    t["cents"] = (t["amount"].round(2).abs() * 100).round().astype(int)
    t["when"] = pd.to_datetime(t["date"], errors="coerce")
    cat = t["category"].str.lower()
    ok = ~t["id"].astype(str).str.startswith("m-") & t["when"].notna() & (t["cents"] > 0) & ~savings_mask(t["category"])         & ~cat.str.contains("income")
    back = t[ok & (t["amount"] > 0) & ~cat.isin(skip_cats)].sort_values("when")
    out_ = t[ok & (t["amount"] < 0)]
    pool: dict = {}
    for r in out_.sort_values("when").itertuples():
        pool.setdefault(r.cents, []).append(r)
    paired: set = set()
    for r in back.itertuples():
        near = [o for o in pool.get(r.cents, []) if o.when <= r.when and (r.when - o.when).days <= days]
        if near:
            o = max(near, key=lambda x: x.when)
            pool[r.cents].remove(o)
            paired |= {o.id, r.id}
    return paired


def read_table(src, name: str | None = None) -> pd.DataFrame:
    """Read a CSV or Excel export as text. For Excel, prefers a sheet named 'transactions', else the first."""
    name = (name or getattr(src, "name", str(src))).lower()
    if name.endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(src)
        sheet = next((sn for sn in xl.sheet_names if sn.strip().lower() == "transactions"), xl.sheet_names[0])
        return xl.parse(sheet, dtype=str)
    data = src.read() if hasattr(src, "read") else Path(src).read_bytes()
    try:
        text = data.decode("utf-8-sig")  # also drops the invisible marker some banks put at the start
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return read_csv_text(text)


_DATE_LIKE = re.compile(r"^\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})")


def read_csv_text(text: str) -> pd.DataFrame:
    """A bank CSV as text columns. Some banks put a summary block above the real header, some print a trailing comma on
    every row but not on the header (Chase), and some have no header row at all. The table starts where the file's usual
    number of columns starts: at its heading row if it has one, and otherwise the columns are called Column 1, Column 2..."""
    import csv
    import io
    from collections import Counter
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("That file is empty.")
    cells = []
    for ln in lines[:300]:
        try:
            cells.append(next(csv.reader([ln])))
        except Exception:
            cells.append([])
    counts = [len(c) for c in cells]
    usual = Counter(c for c in counts if c >= 2).most_common(1)
    usual = usual[0][0] if usual else 0
    data_like = lambda row: any(_DATE_LIKE.match(c) for c in row) or any(
        c.strip() and _to_number(pd.Series([c])).notna().iloc[0] for c in row)
    head_like = lambda row: sum(1 for c in row if c.strip()) >= 2 and not data_like(row)
    run = next((i for i in range(len(counts)) if usual and counts[i:i + 3] == [usual] * len(counts[i:i + 3]) and counts[i] == usual), 0)
    if head_like(cells[run]):
        header, start = True, run
    elif run > 0 and head_like(cells[run - 1]):
        header, start = True, run - 1
    else:
        header, start = False, run
    body = "\n".join(lines[start:])
    if header:
        raw = pd.read_csv(io.StringIO(body), dtype=str, index_col=False, on_bad_lines="skip")  # index_col=False: a trailing comma on every row isn't an index
        raw.columns = [str(c).strip() for c in raw.columns]
    else:
        raw = pd.read_csv(io.StringIO(body), dtype=str, header=None, index_col=False, on_bad_lines="skip")
        raw.columns = [f"Column {i + 1}" for i in range(raw.shape[1])]
    return raw.dropna(axis=1, how="all")


_DATE_NAMES = ["posting date", "posted date", "post date", "transaction date", "trans date", "trans. date", "date"]
_AMOUNT_NAMES = ["amount", "transaction amount", "debit/credit amount", "amt"]
_DESC_NAMES = ["description", "memo", "details", "payee", "merchant", "name", "narrative", "transaction description",
               "original description"]
_DEBIT_NAMES = ["debit", "debits", "withdrawal", "withdrawals", "money out", "paid out", "debit amount", "amount debit"]
_CREDIT_NAMES = ["credit", "credits", "deposit", "deposits", "money in", "paid in", "credit amount", "amount credit"]


def _pick(cols, exact, contains=(), avoid=()):
    """The first column named exactly one of `exact` (in that order), else one whose name contains one of `contains`."""
    low = {c: str(c).strip().lower() for c in cols}
    for n in exact:
        for c in cols:
            if low[c] == n:
                return c
    for n in contains:
        for c in cols:
            if n in low[c] and not any(a in low[c] for a in avoid):
                return c
    return None


def guess_columns(cols: list[str]) -> tuple[str, str, str]:
    """(date, amount, description) column names from the headings alone."""
    d = _pick(cols, _DATE_NAMES, ["date"], ["due", "statement"])
    a = _pick(cols, _AMOUNT_NAMES, ["amount"], ["balance"])
    s = _pick(cols, _DESC_NAMES, ["description", "detail", "memo", "payee", "merchant"])
    return d or cols[0], a or cols[0], s or cols[0]


def guess_import(raw: pd.DataFrame) -> dict:
    """What each column of a bank export is, from its headings and then from what's inside it:
    {date, amount, desc, debit, credit, split, spending}. `split` is True when the bank gives money out and money in as
    two columns (then `amount` is blank). `spending` is how money spent shows in a single amount column: "positive",
    "negative", or "typed" when a Debit/Credit type column says it row by row."""
    cols = list(raw.columns)
    nums = {c: _to_number(raw[c]) for c in cols}
    isnum = {c: nums[c].notna().mean() >= 0.8 for c in cols}
    isdate = lambda c: pd.to_datetime(raw[c], errors="coerce").notna().mean() >= 0.8
    d_head = _pick(cols, _DATE_NAMES, ["date"], ["due", "statement"])
    d = d_head or next((c for c in cols if not isnum[c] and isdate(c)), cols[0])
    a = _pick(cols, _AMOUNT_NAMES, ["amount"], ["balance"])
    a_head = a
    debit = _pick(cols, _DEBIT_NAMES, ["debit", "withdraw"], ["credit"])
    credit = _pick(cols, _CREDIT_NAMES, ["credit", "deposit"], ["debit"])
    split = a is None and debit is not None and credit is not None
    if a is None and not split:  # no heading says "amount": the number column that isn't a balance, a date or an id
        cand = [c for c in cols if isnum[c] and c != d and not any(w in str(c).lower() for w in ("balance", "bal.", "check", "number", "id", "no."))]
        a = max(cand, key=lambda c: nums[c].notna().sum()) if cand else cols[0]
    taken = {d, a, debit, credit}
    s = s_head = _pick(cols, _DESC_NAMES, ["description", "detail", "memo", "payee", "merchant", "name"])
    if s is None:  # the wordiest column that isn't something else
        text = [c for c in cols if c not in taken and not isnum[c] and not isdate(c)]
        s = max(text, key=lambda c: raw[c].fillna("").astype(str).str.len().mean()) if text else cols[0]
    spending, sure = "positive", True
    if split:
        spending = "split"
    elif debit_credit_sign(raw) is not None:
        spending = "typed"
    else:
        n = nums[a].dropna()
        n = n[n != 0]
        neg, pos = int((n < 0).sum()), int((n > 0).sum())
        spending = "negative" if neg > pos else "positive"
        sure = len(n) > 0 and max(neg, pos) / len(n) >= 0.7  # a clear majority, so the sign is easy to read
    # "confident" = every column was found by its heading, and the sign of spending is clear: safe to import without asking
    confident = bool(d_head and s_head and (a_head or split) and sure)
    return dict(date=d, amount="" if split else a, desc=s, debit=debit or "", credit=credit or "", split=split, spending=spending,
                confident=confident)


def carry_categories(gone: pd.DataFrame, new: pd.DataFrame) -> list[str]:
    """Categories you chose on rows an import is about to swap out, handed to the rows that replace them.
    The same row coming back (a refreshed pending hold; any row in replace mode) keeps its category. A pending row
    that has now posted, usually under different text, passes its category to the posted row that matches it: the
    same direction (a deposit only matches a deposit), the same merchant text, one pending row to one posted row."""
    cats = [""] * len(new)
    chosen = gone[gone["category"].astype(str).str.strip() != ""]
    if chosen.empty or new.empty:
        return cats
    same = dict(zip(chosen["id"], chosen["category"]))
    for i, rid in enumerate(new["id"].tolist()):
        if rid in same:
            cats[i] = same[rid]
    lost = chosen[chosen["pending"].astype(bool) & ~chosen["id"].isin(set(new["id"]))]
    desc = new["description"].astype(str).str.upper().tolist()
    posted = (~new["pending"].astype(bool)).tolist()
    amt = new["amount"].astype(float).tolist()
    used: set = set()
    for r in lost.sort_values("date").itertuples():
        core = re.sub(r"^POS HOLD,?\s*", "", str(r.description).upper()).strip()
        if len(core) < 8:
            continue
        best, best_gap = None, None
        for i in range(len(new)):
            if i in used or cats[i] or not posted[i] or (amt[i] > 0) != (float(r.amount) > 0):
                continue
            if core in desc[i] or len(os.path.commonprefix([core, desc[i]])) >= 10:
                gap = abs(abs(amt[i]) - abs(float(r.amount)))
                if best is None or gap < best_gap:
                    best, best_gap = i, gap
        if best is not None:
            cats[best] = r.category
            used.add(best)
    return cats


def ingest_mapped(raw, dcol, acol, scol, tx, rules, append: bool = True, debit: str = "", credit: str = "",
                  spending: str = "positive"):
    """Parse a bank export, de-duplicate, auto-categorize. Only what the file covers is touched, so importing an
    older file (a previous paycheck) never disturbs newer transactions:
      * pending holds already stored are refreshed only by a file at least as new as the hold;
      * replace mode swaps out bank rows inside the file's own date range, nothing outside it (hand entries stay).
    Categories you chose by hand survive both: see carry_categories. The number kept is in all_tx.attrs["carried"].
    Returns (all_tx, n_new, n_categorized, n_skipped)."""
    cols = SCHEMAS["transactions"]
    new = parse_bank(raw, dcol, acol, scol, debit, credit, spending)
    skipped = new.attrs.get("skipped", 0)
    if new.empty:
        return tx[cols].copy(), 0, 0, skipped
    lo, hi = str(new["date"].min()), str(new["date"].max())
    if append:
        base, gone = tx[cols], tx[cols].iloc[0:0]
    else:
        in_span = tx["date"].between(lo, hi) & ~tx["id"].str.startswith("m-")
        base, gone = tx[~in_span][cols], tx.loc[in_span, cols]
    reach = (pd.Timestamp(hi) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    old_hold = base["pending"] & (base["date"] <= reach)  # holds this file is new enough to replace
    gone, base = pd.concat([gone, base[old_hold]], ignore_index=True), base[~old_hold]
    new = new[~new["id"].isin(base["id"])].copy()
    new["category"] = carry_categories(gone, new)
    carried = int((new["category"].astype(str).str.strip() != "").sum())
    allx, n = categorize(pd.concat([base, new[cols]], ignore_index=True), rules)
    allx.attrs["carried"] = carried
    return allx, len(new), n, skipped


def skipped_note(skipped: int) -> str:
    return f" {skipped} rows were skipped (no usable date or amount)." if skipped else ""


# ---------- import from the old Expenses workbook ----------
def chain_starts(first: date, n: int, mode: str = "biweekly", day: int = 1) -> list[str]:
    """`n` period starts in a row from `first`, for a layout that may not be saved yet."""
    out, d = [], first
    for _ in range(n):
        out.append(d.isoformat())
        if mode == "monthly":
            y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        else:
            d += timedelta(days=PERIOD_DAYS)
    return out


def month_start(year: int, month: int, day: int) -> date:
    """The day a monthly period starts in a given month (a day past the month's end, like the 31st, becomes its last day)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def sample_data(mode: str = "biweekly", day: int = 1) -> dict:
    today = date.today()
    if mode == "monthly":
        y, m = today.year, today.month - 2
        y, m = (y - 1, m + 12) if m < 1 else (y, m)
        first = month_start(y, m, day)
        if first > today:  # a start day later than today's date: the current month began last month
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
            first = month_start(y, m, day)
        starts = chain_starts(first, 6, "monthly", day)
    else:
        first = today - timedelta(days=today.weekday()) - timedelta(days=PERIOD_DAYS)
        starts = chain_starts(first, 6)
    scale = 2 if mode == "monthly" else 1  # a month holds about two paychecks
    bills = [("Rent", 1, 1500), ("Internet", 7, 60), ("Phone", 20, 80), ("Car Insurance", 23, 150), ("Netflix", 28, 9)]
    plan, inc = [], []
    for s in starts:
        plan += [dict(period_start=s, item=n, kind="bill", due_day=d, amount=a) for n, d, a in bills]
        plan += [dict(period_start=s, item="Groceries", kind="budget", due_day=None, amount=400 * scale),
                 dict(period_start=s, item="Dining Out", kind="budget", due_day=None, amount=120 * scale)]
        inc += [dict(period_start=s, source="Paycheck" if scale == 1 else "Income", amount=2200 * scale)]
    return {
        "periods": pd.DataFrame({"period_start": starts}), "plan": pd.DataFrame(plan), "income": pd.DataFrame(inc),
        "rules": pd.DataFrame([("STARBUCKS", "Dining Out"), ("NETFLIX", "Netflix"), ("SAFEWAY", "Groceries"),
                               ("PAYROLL", "Paycheck Income")], columns=["keyword", "category"]),
        "budgets": pd.DataFrame([("Groceries", 400 * scale), ("Dining Out", 120 * scale)], columns=["category", "limit"]),
    }


def make_test_data(today: date | None = None, shuffle: int | None = None) -> dict:
    """A made-up household dated around today, so every screen has something realistic to show: two paychecks, ten
    bills, three budgets, three debts, and spending so far in this paycheck and the six before it. The bank balance
    is set so this paycheck has about $420 left. Nothing in it is anyone's real data.
    `shuffle` (any number) turns the dials instead: pay, bills, budgets, debts, savings and how much is left all move
    higher or lower, the same way every time for the same number, so you can try different scenarios."""
    today = today or date.today()
    yday = today - timedelta(days=1)
    cur = today - timedelta(days=6)  # this paycheck began six days ago
    starts = [(cur + timedelta(days=PERIOD_DAYS * i)).isoformat() for i in range(-6, 9)]
    bills = [("Rent", 1, 1450.0), ("Internet", 5, 70.0), ("Streaming", 9, 16.99), ("Car Payment", 12, 365.0),
             ("Electric", 14, 105.0), ("Credit Card A", 15, 125.0), ("Student Loan", 18, 210.0), ("Phone", 20, 95.0),
             ("Car Insurance", 25, 180.0), ("Gym", 28, 35.0)]
    master = pd.DataFrame(bills, columns=["item", "due_day", "amount"])
    budgets = [("Groceries", 400.0), ("Dining Out", 150.0), ("Gas", 120.0)]
    sources = [("Alex Income", 1500.0), ("Jordan Income", 700.0)]
    notes, left_target, saved, debt_f, jackpot = "", 420.0, 0.0, 1.0, 0.0
    if shuffle is not None:  # turn the dials: everything moves higher or lower by its own random amount
        srng = np.random.default_rng(shuffle)
        base_bills, base_budgets = sum(a for _, _, a in bills), sum(l for _, l in budgets)
        inc_f = float(srng.uniform(0.7, 1.45))
        bills = [(n, d, round(a * float(srng.uniform(0.8, 1.35) if n == "Rent" else srng.uniform(0.85, 1.25)), 2))
                 for n, d, a in bills]
        budgets = [(n, float(round(l * float(srng.uniform(0.6, 1.6)) / 10) * 10)) for n, l in budgets]
        sources = [(n, round(a * inc_f, 2)) for n, a in sources]
        debt_f = float(srng.uniform(0.5, 1.8))
        left_target = float(round(srng.uniform(-300, 2500)))
        saved = float(round(srng.uniform(0, 12000), -2))
        notes = (f"pay {inc_f - 1:+.0%}, bills {sum(a for _, _, a in bills) / base_bills - 1:+.0%}, budgets "
                 f"{sum(l for _, l in budgets) / base_budgets - 1:+.0%}, debts {debt_f - 1:+.0%}, savings "
                 f"${saved:,.0f}, about ${left_target:,.0f} left in the bank after what's still to pay")
        if srng.random() < 1 / 25:  # about one shuffle in 25 is a jackpot: a huge windfall lands in the bank
            jackpot = float(round(srng.uniform(500_000, 1_500_000), -3))
            notes += f". 🎉 JACKPOT: a ${jackpot:,.0f} windfall landed in your account yesterday"
        master = pd.DataFrame(bills, columns=["item", "due_day", "amount"])
    plan = pd.concat([pd.DataFrame(recurring_rows(master, starts)),
                      pd.DataFrame([dict(period_start=s_, item=n, kind="budget", due_day=None, amount=l)
                                    for s_ in starts for n, l in budgets])], ignore_index=True)
    income = pd.DataFrame([dict(period_start=s_, source=n, amount=a) for s_ in starts for n, a in sources])

    rng = np.random.default_rng(2026 if shuffle is None else shuffle)  # fixed, so the same spending comes back every time
    rows: list[dict] = []

    def add(d: date, desc: str, amt: float, cat: str) -> None:
        if d <= yday:  # the "bank" only knows up to yesterday
            rows.append(dict(date=d.isoformat(), description=desc, amount=round(float(amt), 2), category=cat))

    for s_ in starts:
        d0 = date.fromisoformat(s_)
        draws = rng.uniform(0, 1, 12)  # drawn for every paycheck, used or not, so amounts never shift with the date
        if d0 > yday:
            continue
        add(d0, "ACME CORP PAYROLL", sources[0][1], "Alex Income")
        add(d0, "BETA LLC DIRECT DEP", sources[1][1], "Jordan Income")
        for n, due, a in bills:
            occ = occurrence(s_, due)
            if occ is not None:
                add(occ, f"AUTOPAY {n.upper()}", -a, n)
        for k, off in enumerate((1, 5, 9, 12)):
            add(d0 + timedelta(off), f"SAFEWAY #{1000 + off}", -(55 + 65 * draws[k]), "Groceries")
        for k, off in enumerate((3, 8, 11)):
            add(d0 + timedelta(off), ("CHIPOTLE", "PIZZA PLACE", "COFFEE SHOP")[k], -(14 + 34 * draws[4 + k]), "Dining Out")
        for k, off in enumerate((2, 10)):
            add(d0 + timedelta(off), "SHELL OIL 5741", -(38 + 14 * draws[7 + k]), "Gas")
        add(d0 + timedelta(4), "AMAZON MKTPLACE", -(18 + 57 * draws[9]), "Amazon")
        if d0.toordinal() % 3 == 0:
            add(d0 + timedelta(7), "CVS PHARMACY", -(12 + 26 * draws[10]), "Pharmacy")
    if jackpot:  # the windfall: counted as extra income in this paycheck, and sitting in the bank balance
        add(yday, "ESTATE SETTLEMENT WIRE", jackpot, "Windfall Income")
    tx = pd.DataFrame(rows, columns=["date", "description", "amount", "category"])
    tx["id"] = make_ids(tx)
    tx["pending"] = False

    cur_s = cur.isoformat()  # set the bank balance so this paycheck has about $420 left
    still_bills = sum(a for _, due, a in bills if (occurrence(cur_s, due) or date.min) >= today)
    spent_cur = {n: -sum(r["amount"] for r in rows if r["category"] == n and cur <= date.fromisoformat(r["date"]) <= yday)
                 for n, _ in budgets}
    still_budgets = sum(max(l - spent_cur[n], 0.0) for n, l in budgets)
    balance = round(still_bills + still_budgets + left_target + jackpot, 2)

    frames = dict(
        periods=pd.DataFrame({"period_start": starts}), plan=plan, income=income, transactions=tx,
        rules=pd.DataFrame([("SAFEWAY", "Groceries"), ("CHIPOTLE", "Dining Out"), ("SHELL OIL", "Gas"),
                            ("AMAZON", "Amazon"), ("CVS", "Pharmacy"), ("PAYROLL", "Alex Income"),
                            ("DIRECT DEP", "Jordan Income")], columns=["keyword", "category"]),
        budgets=pd.DataFrame(budgets, columns=["category", "limit"]),
        debts=pd.DataFrame([("Credit Card A", 5200 * debt_f, 3400 * debt_f, next(a for n, _, a in bills if n == "Credit Card A"), 22.99, True),
                            ("Car Loan", 18000 * debt_f, 11200 * debt_f, next(a for n, _, a in bills if n == "Car Payment"), 6.9, True),
                            ("Student Loan", 12000 * debt_f, 8300 * debt_f, next(a for n, _, a in bills if n == "Student Loan"), 4.5, False)],
                           columns=SCHEMAS["debts"]).round(2),
        recurring=master, planned_income=pd.DataFrame(sources, columns=["source", "amount"]))
    settings = {**DEFAULT_SETTINGS, "opening_balance": 0.0, "debt_threshold": 300.0, "tx_folder": "",
                "bank_balance": {"as_of": yday.isoformat(), "balance": balance, "v": 2},
                "import_prompt_snoozed": today.isoformat()}
    if shuffle is not None:
        settings["savings_have"] = saved
    return dict(frames=frames, settings=settings, notes=notes)


def seed_test_data(folder: Path, today: date | None = None, shuffle: int | None = None) -> str:
    """(Re)build the sample-data folder from scratch (shuffled higher or lower numbers when `shuffle` is given).
    It refuses to touch your real data or any folder that isn't named *_test. Returns a short note on what moved."""
    note = ""
    global DATA_DIR
    if not folder.name.endswith("_test") or folder.resolve() == REAL_DIR.resolve():
        raise ValueError("Test data only ever goes in its own *_test folder.")
    keep = DATA_DIR
    try:
        if folder.exists():
            shutil.rmtree(folder)
        DATA_DIR = folder
        d = make_test_data(today, shuffle)
        for name, df in d["frames"].items():
            save(name, df)
        save_settings(d["settings"])
        note = d.get("notes", "")
    finally:
        DATA_DIR = keep
    return note


def known_categories(rules, plan, budgets, income, tx) -> list[str]:
    """Every category name already in use, one spelling per name (case-insensitive), sorted."""
    canon: dict[str, str] = {}
    for col in (rules["category"], budgets["category"], plan["item"], income["source"], tx["category"]):
        for name in col:
            name = str(name).strip()
            if name:
                canon.setdefault(name.lower(), name)
    canon.setdefault(SAVINGS_WORD, "Savings")  # always there to pick, so a deposit can be set aside
    return sorted(canon.values(), key=str.lower)


def category_type(name: str, planned: set, income_names: set) -> str:
    """Planned (a bill on the Plan tab or a budget), Income (a paycheck, or 'income' in the name), Savings ('savings'
    in the name: set aside, so it counts as neither income nor spending), Extra (anything else), or Uncategorized."""
    low = str(name).strip().lower()
    if not low or low == "uncategorized":
        return "Uncategorized"
    if SAVINGS_WORD in low:
        return "Savings"
    if low in income_names or "income" in low:
        return "Income"
    return "Planned" if low in planned else "Extra"


def savings_total(tx: pd.DataFrame) -> float:
    """Everything tagged Savings in the transactions (deposits up, withdrawals down)."""
    return float(tx.loc[savings_mask(tx["category"]), "amount"].sum())


def sync_extra_categories(xc: pd.DataFrame, tx: pd.DataFrame, plan: pd.DataFrame, rules: pd.DataFrame,
                          planned: set, income_names: set) -> pd.DataFrame:
    """The extra-category list: every extra name in use (transactions, past plans, rules), keeping each one's
    one-off flag. Names nobody uses any more, or that are now planned or income, drop off."""
    flags = {str(r.name).strip().lower(): bool(r.one_off) for r in xc.itertuples()}
    keep = {}
    for col in (tx["category"], plan.loc[plan["kind"] == "extra", "item"], rules["category"]):
        for n in col:
            n = str(n).strip()
            if n and n.lower() not in keep and category_type(n, planned, income_names) == "Extra":
                keep[n.lower()] = dict(name=n, one_off=flags.get(n.lower(), False))
            g = cat_group(n)
            if g != n and g.lower() not in keep and category_type(g, planned, income_names) == "Extra":
                keep[g.lower()] = dict(name=g, one_off=flags.get(g.lower(), False))
    out = pd.DataFrame(list(keep.values()), columns=["name", "one_off"])
    return out.sort_values("name", key=lambda c: c.str.lower()).reset_index(drop=True)


def cat_group(name: str) -> str:
    """'UK Trip - Dining Out' -> 'UK Trip'. A name without ' - ' is its own group."""
    n = str(name).strip()
    return n.split(" - ", 1)[0].strip() if " - " in n else n


def similar_names(new: str, existing: list[str]) -> list[str]:
    """Existing categories that look like near-duplicates of a new name (e.g. 'Onpoint Card' vs 'Onpoint')."""
    n = new.strip().lower()
    out = []
    for e in existing:
        el = e.lower()
        if not n or el == n:
            continue
        contained = len(n) >= 4 and len(el) >= 4 and (el in n or n in el)
        if contained or difflib.SequenceMatcher(None, n, el).ratio() >= 0.8:
            out.append(e)
    return out[:3]


REC_FILES = ("plan", "income", "recurring", "planned_income")


def drop_backup() -> None:
    for n in ("plan.bak.csv", "income.bak.csv"):
        (DATA_DIR / n).unlink(missing_ok=True)
    for n in REC_FILES:
        (DATA_DIR / f"{n}.rec.bak.csv").unlink(missing_ok=True)
        (DATA_DIR / f"{n}.rec.none").unlink(missing_ok=True)


def backup_recurring() -> None:
    """Snapshot the plan, income and both planned lists before a Planned-tab save (for a one-click undo)."""
    drop_backup()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for n in REC_FILES:
        f = DATA_DIR / f"{n}.csv"
        if f.exists():
            shutil.copy(f, DATA_DIR / f"{n}.rec.bak.csv")
        else:
            (DATA_DIR / f"{n}.rec.none").write_text("")


def has_rec_backup() -> bool:
    return any((DATA_DIR / f"{n}.rec.bak.csv").exists() for n in REC_FILES)


def restore_recurring() -> bool:
    if not has_rec_backup():
        return False
    for n in REC_FILES:
        bak, none_flag, f = DATA_DIR / f"{n}.rec.bak.csv", DATA_DIR / f"{n}.rec.none", DATA_DIR / f"{n}.csv"
        if bak.exists():
            shutil.copy(bak, f)
        elif none_flag.exists():
            f.unlink(missing_ok=True)
        bak.unlink(missing_ok=True)
        none_flag.unlink(missing_ok=True)
    return True


def clean_recurring(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["item"] = d["item"].fillna("").astype(str).str.strip()
    d = d[d["item"] != ""]
    d["due_day"] = pd.to_numeric(d["due_day"], errors="coerce")
    d.loc[(d["due_day"] < 1) | (d["due_day"] > 31), "due_day"] = np.nan
    d["due_day"] = d["due_day"].round()
    d["amount"] = pd.to_numeric(d["amount"], errors="coerce").fillna(0.0)
    for c in ("freq", "month"):  # older lists don't have these: they were all monthly
        if c not in d:
            d[c] = np.nan if c == "month" else ""
    d["freq"] = [{f.lower(): f for f in FREQS}.get(str(v).strip().lower(), "Monthly") for v in d["freq"]]
    d["month"] = pd.to_numeric(d["month"], errors="coerce")
    d.loc[(d["month"] < 1) | (d["month"] > 12), "month"] = np.nan
    d["month"] = d["month"].round()
    d.loc[d["freq"] == "Monthly", "month"] = np.nan
    d.loc[(d["freq"] != "Monthly") & d["month"].isna(), "freq"] = "Monthly"  # no month picked yet: stays monthly
    d = d.assign(_k=d["item"].str.lower()).drop_duplicates("_k", keep="last").drop(columns="_k")
    return d[["item", "due_day", "amount", "freq", "month"]].reset_index(drop=True)


FREQS = ["Monthly", "Quarterly", "Yearly"]  # anything else in an old file (like "Twice a year") reads as Monthly
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]


def freq_months(freq, month) -> set[int] | None:
    """The calendar months a bill comes due in: None for monthly (every month), else the months its cycle hits,
    counting from the starting month (Quarterly from 1 = Jan, Apr, Jul, Oct; Yearly from 1 = Jan only)."""
    step = {"quarterly": 3, "yearly": 12}.get(str(freq or "").strip().lower())
    if not step or month is None or pd.isna(month):
        return None
    return {(int(month) - 1 + k) % 12 + 1 for k in range(0, 12, step)}


def occurrence(period: str, due_day, months: set | None = None) -> date | None:
    """The date a bill with this due day lands inside the pay period (None if it doesn't land in it).
    A blank due day means 'every paycheck', which lands on the period's first day. `months` limits which calendar
    months it can land in (for quarterly and yearly bills)."""
    start = date.fromisoformat(period)
    end = period_end(start)
    if due_day is None or pd.isna(due_day) or int(due_day) <= 0:
        return start
    for y, m in sorted({(start.year, start.month), (end.year, end.month)}):
        cand = date(y, m, min(int(due_day), calendar.monthrange(y, m)[1]))
        if start <= cand <= end and (months is None or m in months):
            return cand
    return None


def derive_master(plan: pd.DataFrame, budget_names: set, today: date | None = None) -> pd.DataFrame:
    """First-time recurring list built from the bills already in the plan: each bill's next upcoming entry,
    or its most recent one if it showed up in the last ~6 weeks."""
    today = today or date.today()
    rows = plan[(plan.kind != "extra") & ~plan.item.str.lower().isin(budget_names)].copy()
    if rows.empty:
        return pd.DataFrame(columns=SCHEMAS["recurring"])
    rows["occ"] = [occurrence(p_, d_) or date.fromisoformat(p_) for p_, d_ in zip(rows.period_start, rows.due_day)]
    out = []
    for _, g in rows.groupby(rows["item"].str.lower()):
        up = g[g["occ"] >= today].sort_values("occ")
        if len(up):
            r = up.iloc[0]
        else:
            recent = g[g["occ"] >= today - timedelta(days=45)].sort_values("occ")
            if recent.empty:
                continue
            r = recent.iloc[-1]
        out.append(dict(item=r["item"], due_day=r["due_day"], amount=r["amount"]))
    m = clean_recurring(pd.DataFrame(out, columns=SCHEMAS["recurring"]))
    return m.sort_values(["due_day", "item"], na_position="last").reset_index(drop=True)


def recurring_rows(master: pd.DataFrame, periods: list[str], since: date | None = None) -> list[dict]:
    """Plan rows for the recurring list in these pay periods (only bills due on/after `since`, if given)."""
    rows = []
    for p_ in periods:
        for r in master.itertuples():
            occ = occurrence(p_, r.due_day, freq_months(getattr(r, "freq", ""), getattr(r, "month", None)))
            if occ is not None and (since is None or occ >= since):
                rows.append(dict(period_start=p_, item=r.item, due_day=r.due_day, amount=float(r.amount),
                                 kind="bill" if pd.notna(r.due_day) else "budget"))
    return rows


def sync_recurring(plan: pd.DataFrame, master: pd.DataFrame, starts: list[str], today: date | None = None,
                   cancellations: dict | None = None, effective: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Make every bill due today or later match the recurring list. Bills already due stay as they were.
    `cancellations` maps a removed expense to its effective date: its bills due on/after that date are removed.
    `effective` maps a new or changed expense to its start date: its bills due on/after that date follow the list
    (instead of today), so a new expense can reach back into this pay period."""
    today = today or date.today()
    cancel = {k.strip().lower(): v for k, v in (cancellations or {}).items()}
    eff = {k.strip().lower(): v for k, v in (effective or {}).items()}
    names = {r.item.lower() for r in master.itertuples()}
    new = plan.copy()
    sched = new["kind"] != "extra"
    occ = pd.Series([occurrence(p_, d_) or date.fromisoformat(p_) for p_, d_ in zip(new.period_start, new.due_day)],
                    index=new.index, dtype=object)
    low = new["item"].str.lower()
    cancelled = pd.Series(False, index=new.index)
    for k, cd in cancel.items():
        cancelled |= sched & (low == k) & (occ >= cd)
    cutoff = pd.Series([eff.get(k, today) for k in low], index=new.index, dtype=object)
    future = sched & low.isin(names) & (occ >= cutoff)
    new = new[~(cancelled | future)]
    rows = []
    for r in master.itertuples():
        rows += recurring_rows(master.loc[[r.Index]], starts, since=eff.get(r.item.lower(), today))
    if rows:
        new = pd.concat([new, pd.DataFrame(rows)], ignore_index=True)
    return new, dict(cancelled=int(cancelled.sum()), scheduled=len(rows))


def clean_income_list(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["source"] = d["source"].fillna("").astype(str).str.strip()
    d = d[d["source"] != ""]
    d["amount"] = pd.to_numeric(d["amount"], errors="coerce").fillna(0.0)
    d = d.assign(_k=d["source"].str.lower()).drop_duplicates("_k", keep="last").drop(columns="_k")
    return d[["source", "amount"]].reset_index(drop=True)


def derive_planned_income(income: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """First-time planned income: sources that showed up in most of the last six paychecks, at their next
    planned amount (or latest amount)."""
    today = today or date.today()
    if income.empty:
        return pd.DataFrame(columns=SCHEMAS["planned_income"])
    recent = [p_ for p_ in sorted(income["period_start"].unique()) if date.fromisoformat(p_) <= today][-6:]
    if not recent:
        recent = sorted(income["period_start"].unique())[:6]
    seen = income[income["period_start"].isin(recent)].groupby(income["source"].str.lower())["period_start"].nunique()
    rows = []
    for k in seen[seen >= len(recent) // 2 + 1].index:
        g = income[income["source"].str.lower() == k].sort_values("period_start")
        up = g[g["period_start"] >= today.isoformat()]
        r = up.iloc[0] if len(up) else g.iloc[-1]
        rows.append(dict(source=r["source"], amount=r["amount"]))
    return clean_income_list(pd.DataFrame(rows, columns=SCHEMAS["planned_income"]))


def load_planned_income(income: pd.DataFrame) -> pd.DataFrame:
    if (DATA_DIR / "planned_income.csv").exists():
        return clean_income_list(load("planned_income"))
    return derive_planned_income(income)


def sync_income(income: pd.DataFrame, planned: pd.DataFrame, starts: list[str], today: date | None = None,
                cancellations: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Make every paycheck from the current pay period on follow the planned income list. Earlier paychecks stay
    as they were, and once a real deposit lands it counts instead of the plan. A removed source with an
    effective date drops its paychecks on/after that date."""
    today = today or date.today()
    past_or_now = [p_ for p_ in starts if date.fromisoformat(p_) <= today]
    from_day = date.fromisoformat(past_or_now[-1]) if past_or_now else today
    cancel = {k.strip().lower(): v for k, v in (cancellations or {}).items()}
    names = {r.source.lower() for r in planned.itertuples()}
    new = income.copy()
    payday = pd.Series([date.fromisoformat(p_) for p_ in new["period_start"]], index=new.index, dtype=object)
    low = new["source"].str.lower()
    cancelled = pd.Series(False, index=new.index)
    for k, cd in cancel.items():
        cancelled |= (low == k) & (payday >= cd)
    future = low.isin(names) & (payday >= from_day)
    new = new[~(cancelled | future)]
    rows = [dict(period_start=p_, source=r.source, amount=float(r.amount))
            for p_ in starts if date.fromisoformat(p_) >= from_day for r in planned.itertuples()]
    if rows:
        new = pd.concat([new, pd.DataFrame(rows)], ignore_index=True)
    return new, dict(cancelled=int(cancelled.sum()), scheduled=len(rows))


def paycheck_actuals(tx: pd.DataFrame, starts: list[str], planned_names: set) -> pd.DataFrame:
    """What actually landed for each planned paycheck, per pay period (from the transactions)."""
    cols = ["period_start", "key", "amount"]
    if tx.empty or not starts or not planned_names:
        return pd.DataFrame(columns=cols)
    t = tx[["date", "category", "amount"]].copy()
    t["period_start"] = assign_period(t["date"], starts)
    t["key"] = t["category"].str.lower()
    t = t[(t["period_start"] != "") & t["key"].isin(planned_names)]
    if t.empty:
        return pd.DataFrame(columns=cols)
    g = t.groupby(["period_start", "key"])["amount"].sum().clip(lower=0).reset_index()
    return g[g["amount"] > 0][cols].reset_index(drop=True)


def paycheck_nudges(pinc: pd.DataFrame, tx: pd.DataFrame, starts: list[str], dismissed: list | None = None) -> list[dict]:
    """Planned paychecks whose last two actual deposits both differ from the plan (and roughly agree with each
    other), which usually means a raise or a deduction change."""
    acts = paycheck_actuals(tx, starts, {x.lower() for x in pinc["source"]})
    out, dismissed = [], set(dismissed or [])
    for r in pinc.itertuples():
        a = acts[acts["key"] == r.source.lower()].sort_values("period_start")["amount"].tolist()
        if len(a) < 2:
            continue
        a1, a2 = a[-2], a[-1]
        differs = abs(a1 - r.amount) >= 0.005 and abs(a2 - r.amount) >= 0.005
        steady = abs(a1 - a2) <= max(1.0, 0.02 * a2)
        if differs and steady and f"{r.source}|{a2:.2f}" not in dismissed:
            out.append(dict(source=r.source, planned=float(r.amount), actual=float(a2)))
    return out


def load_income_overrides() -> set:
    """(pay period, income source) pairs where the amount you entered beats the bank deposit."""
    o = load("income_overrides")
    return set(zip(o["period_start"], o["source"].str.lower()))


def effective_income(income: pd.DataFrame, tx: pd.DataFrame, starts: list[str], planned_names: set,
                     use_actual: bool = True, overrides: set | None = None) -> pd.DataFrame:
    """Planned income (stored per pay period) plus extra income. Extra income is any income category that
    isn't on the planned list: straight from the transactions for pay periods that have them, otherwise the
    hand-entered or historical amounts."""
    cols = ["period_start", "source", "amount", "kind"]
    tx_periods = tx_driven_periods(tx, starts)
    low = income["source"].str.lower()
    planned = income[low.isin(planned_names)].assign(kind="planned").copy()
    overrides = load_income_overrides() if overrides is None else overrides
    landed = paycheck_actuals(tx, starts, planned_names) if use_actual else pd.DataFrame(columns=["period_start", "key", "amount"])
    for row in landed.itertuples():  # use the real paycheck once it lands, unless you entered one for it
        if (row.period_start, row.key) in overrides:
            continue
        m = (planned["period_start"] == row.period_start) & (planned["source"].str.lower() == row.key)
        if m.any():
            planned.loc[m, "amount"] = 0.0
            planned.loc[m.idxmax(), "amount"] = row.amount
        else:
            name = next((n for n in income["source"] if n.lower() == row.key), row.key.title())
            planned = pd.concat([planned, pd.DataFrame([dict(period_start=row.period_start, source=name,
                                                             amount=row.amount, kind="planned")])], ignore_index=True)
    stored_x = income[~low.isin(planned_names) & ~income["period_start"].isin(tx_periods)].assign(kind="extra")
    live = pd.DataFrame(columns=cols)
    if not tx.empty and starts:
        t = tx[["date", "category", "amount"]].copy()
        t["period_start"] = assign_period(t["date"], starts)
        cat = t["category"].str.lower()
        t = t[t["period_start"].isin(tx_periods) & cat.str.contains("income") & ~cat.isin(planned_names)
              & ~savings_mask(t["category"])]
        if not t.empty:
            g = t.groupby(["period_start", "category"])["amount"].sum().clip(lower=0).reset_index()
            live = g[g["amount"] > 0].rename(columns={"category": "source"}).assign(kind="extra")[cols]
    out = pd.concat([planned[cols], stored_x[cols], live], ignore_index=True)
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)
    return out


def bill_status(period: str, rows: pd.DataFrame, tx: pd.DataFrame, starts: list[str], budget_lim: dict,
                today: date | None = None, marked: set | None = None) -> pd.DataFrame:
    """Paid / due / overdue status for each scheduled line in a pay period, from the transactions.
    A bill counts as paid when a transaction in the pay period carries its name as the category.
    Budget lines show how much of the budget is used instead."""
    today = today or date.today()
    p_start = date.fromisoformat(period)
    p_end = period_end(p_start)
    spent, last_on = {}, {}
    if not tx.empty and starts:
        t = tx[["date", "category", "amount"]].copy()
        t["period_start"] = assign_period(t["date"], starts)
        t = t[(t["period_start"] == period) & (t["amount"] < 0) & (t["category"] != "")]
        if not t.empty:
            t["key"] = t["category"].str.lower()
            spent = (-t.groupby("key")["amount"].sum()).to_dict()
            last_on = t.groupby("key")["date"].max().to_dict()
    has_data = period in tx_driven_periods(tx, starts, today)
    out = []
    for r in rows.itertuples():
        k = r.item.lower()
        paid = spent.get(k, 0.0)
        if r.kind == "budget" and k in budget_lim:
            limit = budget_lim[k]
            pct = paid / limit * 100 if limit else 0
            state = "over" if pct > 100 else "warn" if pct >= 80 else "ok"
            label = f"Over by {money(paid - limit)}" if pct > 100 else f"{pct:.0f}% of budget used"
            out.append(dict(actual=paid, status=label, state=state))
            continue
        if paid > 0:
            on = date.fromisoformat(last_on[k])
            out.append(dict(actual=paid, status=f"Paid {on:%b %d}", state="paid"))
            continue
        if k in (marked or set()):  # paid some other way (check, another account...)
            out.append(dict(actual=np.nan, status="Marked paid", state="paid"))
            continue
        if not has_data and p_end < today:
            out.append(dict(actual=np.nan, status="No bank data", state="nodata"))
            continue
        due = None
        if pd.notna(r.due_day):
            due = occurrence(period, r.due_day)
            if due is None:  # due day falls just outside the window (e.g. the 24th in a 25th-8th period): nearest one
                cands = []
                for y, m in sorted({(p_start.year, p_start.month), (p_end.year, p_end.month)}):
                    cands.append(date(y, m, min(int(r.due_day), calendar.monthrange(y, m)[1])))
                due = min(cands, key=lambda d_: min(abs((d_ - p_start).days), abs((d_ - p_end).days)))
        if due is None:  # every-paycheck item: any time this period
            state, label = ("overdue", "Not paid") if p_end < today else ("upcoming", "This pay period")
        elif due < today:
            state, label = "overdue", ("Overdue" if p_end >= today else "Not paid")
        elif due == today:
            state, label = "soon", "Due today"
        elif (due - today).days <= 3:
            n = (due - today).days
            state, label = "soon", f"Due in {n} day{'s' if n != 1 else ''}"
        else:
            state, label = "upcoming", f"Due {due:%b %d}"
        out.append(dict(actual=np.nan, status=label, state=state))
    return pd.DataFrame(out, index=rows.index, columns=["actual", "status", "state"])


def trend_table(starts: list[str], eplan: pd.DataFrame, inc_eff: pd.DataFrame, budget_names: set,
                opening: float, today: date | None = None, project_extras: bool = True, lookback: int = 6,
                one_off: set | None = None):
    """Per pay period: income, spending split into scheduled / budgets / extras, plus typical extras added to
    future pay periods, and the running Available that results. Returns (table, typical_extras, n_used)."""
    today = today or date.today()
    rows = []
    for p_ in starts:
        e = eplan[eplan.period_start == p_]
        is_bud = e["item"].str.lower().isin(budget_names)
        start = date.fromisoformat(p_)
        end = period_end(start)
        rows.append(dict(period_start=p_, start=start, end=end,
                         phase="past" if end < today else "future" if start > today else "current",
                         income=float(inc_eff.loc[inc_eff.period_start == p_, "amount"].sum()),
                         scheduled=float(e.loc[(e.kind != "extra") & ~is_bud, "amount"].sum()),
                         budgets=float(e.loc[(e.kind != "extra") & is_bud, "amount"].sum()),
                         extras=float(e.loc[e.kind == "extra", "amount"].sum()),
                         regular=float(e.loc[(e.kind == "extra") & ~e["item"].str.lower().isin(one_off or set()),
                                             "amount"].sum())))
    t = pd.DataFrame(rows)
    if t.empty:
        return t, 0.0, 0
    done = t[t["phase"] == "past"].tail(lookback)
    typical = float(done["regular"].median()) if len(done) else 0.0  # one-off categories (a trip) are left out
    t["projected"] = np.where((t["phase"] == "future") & project_extras, typical, 0.0)
    if project_extras:  # the paycheck you're in isn't over: expect it to reach a typical amount of extras
        now_ = t["phase"] == "current"
        t.loc[now_, "projected"] = np.maximum(typical - t.loc[now_, "regular"], 0.0)
    t["spend"] = t[["scheduled", "budgets", "extras", "projected"]].sum(axis=1)
    t["available"] = opening + (t["income"] - t["spend"]).cumsum()
    t["short"] = [f"{d:%b %d}" + (f" '{d:%y}" if d.month == 1 or i == 0 else "") for i, d in enumerate(t["start"])]
    t["full"] = [label(p_) for p_ in t["period_start"]]
    return t, typical, len(done)


def runway_table(trend: pd.DataFrame, typical: float, master: pd.DataFrame, pinc: pd.DataFrame,
                 budget_total: float, opening: float, today: date | None = None, months: int = 12) -> pd.DataFrame:
    """The trend table, extended past the end of the plan to about a year from today using the recurring
    expenses, planned paychecks, budgets and typical extras, with the running Available recomputed."""
    today = today or date.today()
    t = trend.copy()
    if t.empty:
        return t
    last = t["start"].iloc[-1]
    horizon = today + timedelta(days=round(months * 30.4))
    rows, d = [], next_start(last)
    while d <= horizon:
        p_ = d.isoformat()
        rows.append(dict(period_start=p_, start=d, end=period_end(d), phase="future",
                         income=float(pinc["amount"].sum()),
                         scheduled=float(sum(r["amount"] for r in recurring_rows(master, [p_]))),
                         budgets=float(budget_total), extras=0.0, projected=float(typical), short=f"{d:%b %d}",
                         full=label(p_)))
        d = next_start(d)
    if rows:
        t = pd.concat([t, pd.DataFrame(rows)], ignore_index=True)
    t["spend"] = t[["scheduled", "budgets", "extras", "projected"]].sum(axis=1)
    t["available"] = opening + (t["income"] - t["spend"]).cumsum()
    return t


def extras_insight(eplan: pd.DataFrame, starts: list[str], period: str, today: date | None = None,
                   lookback: int = 6, one_off: set | None = None) -> tuple[pd.DataFrame, float, int]:
    """Extras for a pay period next to how they usually run. Returns (table, typical_total, n_paychecks):
    table rows are categories with this paycheck's amount, the typical amount per paycheck, how many of the
    recent paychecks they showed up in, and the median when they do (a ready-made budget suggestion)."""
    today = today or date.today()
    done = [p_ for p_ in starts if period_end(date.fromisoformat(p_)) < today
            and p_ != period][-lookback:]
    ex = eplan[eplan.kind == "extra"].assign(key=lambda d: d["item"].str.lower())
    hist = ex[ex.period_start.isin(done)]
    by = hist.groupby(["key", "period_start"])["amount"].sum().unstack(fill_value=0.0).reindex(columns=done, fill_value=0.0)
    now = ex[ex.period_start == period].groupby("key")["amount"].sum()
    names = {k: g["item"].iloc[-1] for k, g in ex.groupby("key")}
    keys = sorted(set(now.index) | set(by.index))
    rows = []
    for k in keys:
        series = by.loc[k] if k in by.index else pd.Series(0.0, index=done)
        hits = series[series > 0]
        rows.append(dict(key=k, item=names.get(k, k), now=float(now.get(k, 0.0)),
                         typical=float(series.mean()) if len(done) else 0.0, times=int(len(hits)),
                         when_spent=float(hits.median()) if len(hits) else 0.0, one_off=k in (one_off or set())))
    table = pd.DataFrame(rows, columns=["key", "item", "now", "typical", "times", "when_spent", "one_off"])
    regular = hist[~hist["key"].isin(one_off or set())]
    totals = regular.groupby("period_start")["amount"].sum().reindex(done, fill_value=0.0)
    return table, float(totals.median()) if len(done) else 0.0, len(done)


def finalize_debts(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the debts table before saving. The starting balance (used for % paid in the progress bars and the
    email) isn't typed by hand any more: a new debt starts at the balance you enter, and it only ever goes up
    if the balance does, so progress is measured from the peak."""
    d = df.copy()
    d["name"] = d["name"].fillna("").astype(str).str.strip()
    d = d[d["name"] != ""].copy()
    cur = pd.to_numeric(d["current_balance"], errors="coerce").fillna(0.0)
    start = pd.to_numeric(d["start_balance"], errors="coerce")
    d["current_balance"] = cur
    d["start_balance"] = pd.concat([start.fillna(cur), cur], axis=1).max(axis=1)
    return d.reset_index(drop=True)


def apply_bulk_category(full: pd.DataFrame, ids: set, category: str) -> tuple[pd.DataFrame, int]:
    """Put `category` on every transaction whose id is in `ids`. Returns (all transactions, how many changed)."""
    out = full.copy()
    hit = out["id"].isin(ids)
    out.loc[hit, "category"] = category
    return out, int(hit.sum())


def simulate_payoff(balances: list[float], aprs: list[float], mins: list[float], extra: float = 0.0,
                    rollover: bool = False, cap: int = 600, lump: float = 0.0, lump_month: int = 0,
                    extra_from: int = 1, strategy: str = "apr") -> dict:
    """Month-by-month payoff. Each month: interest accrues, every debt gets its minimum, then the extra (plus,
    with `rollover`, the minimums of debts already finished) goes to the highest-APR debt first (or, with
    strategy="balance", the smallest balance first).
    `lump` is a one-time payment made in month `lump_month` (0 = right now); `extra` starts in month `extra_from`.
    Returns the total balance by month (index 0 = now), each debt's balance by month (`by_debt`), the month each
    debt hits zero, total interest, and the number of months until everything is paid (None if not within `cap`
    months)."""
    n = len(balances)
    bal = [float(b) for b in balances]
    if strategy == "balance":
        order = lambda: sorted((j for j in range(n) if bal[j] > 0), key=lambda j: (bal[j], -aprs[j]))
    else:
        order = lambda: sorted((j for j in range(n) if bal[j] > 0), key=lambda j: (-aprs[j], bal[j]))

    def pay_pool(amount: float) -> None:
        for i in order():
            if amount <= 0:
                break
            take = min(amount, bal[i])
            bal[i] -= take
            amount -= take

    if lump > 0 and lump_month <= 0:
        pay_pool(lump)
    paid = [None if b > 0.005 else 0 for b in bal]
    totals, interest = [sum(bal)], 0.0
    by_debt = [list(bal)]
    for m in range(1, cap + 1):
        for i in range(n):
            if bal[i] > 0:
                it = bal[i] * aprs[i] / 1200.0
                bal[i] += it
                interest += it
        if lump > 0 and m == lump_month:
            pay_pool(lump)
        freed = sum(mins[i] for i in range(n) if paid[i] is not None and paid[i] < m) if rollover else 0.0
        for i in range(n):
            if bal[i] > 0:
                bal[i] -= min(mins[i], bal[i])
        pay_pool((extra if m >= extra_from else 0.0) + freed)
        for i in range(n):
            if bal[i] <= 0.005 and paid[i] is None:
                bal[i], paid[i] = 0.0, m
        totals.append(sum(bal))
        by_debt.append(list(bal))
        if all(x <= 0.005 for x in bal):
            return dict(totals=totals, by_debt=by_debt, paid=paid, interest=interest, months=m)
    return dict(totals=totals, by_debt=by_debt, paid=paid, interest=interest, months=None)


def money(x) -> str:
    x = float(x) + 0.0  # turns -0.0 into 0.0
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def rename_category(old: str, new: str, rules, tx, plan, budgets):
    """Rename/merge a category everywhere. If the new name already exists in the same pay period
    (or budgets table), the old row is dropped instead of creating a duplicate."""
    old_l, new = old.strip().lower(), new.strip()
    new_l = new.lower()
    rules, tx, plan, budgets = rules.copy(), tx.copy(), plan.copy(), budgets.copy()

    m = rules["category"].str.lower() == old_l
    n_rules = int(m.sum())
    rules.loc[m, "category"] = new
    rules = rules.drop_duplicates().reset_index(drop=True)

    m = tx["category"].str.lower() == old_l
    n_tx = int(m.sum())
    tx.loc[m, "category"] = new

    is_old = plan["item"].str.lower() == old_l
    is_x = plan["kind"] == "extra"
    taken = set(zip(plan.loc[~is_old & (plan["item"].str.lower() == new_l), "period_start"],
                    is_x[~is_old & (plan["item"].str.lower() == new_l)]))
    dup = is_old & pd.Series([(a, b) in taken for a, b in zip(plan["period_start"], is_x)], index=plan.index)
    n_plan = int(is_old.sum())
    plan = plan[~dup].copy()
    plan.loc[plan["item"].str.lower() == old_l, "item"] = new

    is_old_b = budgets["category"].str.lower() == old_l
    if is_old_b.any():
        if (budgets["category"].str.lower() == new_l).any():
            budgets = budgets[~is_old_b]
        else:
            budgets.loc[is_old_b, "category"] = new
    return rules, tx, plan, budgets, dict(rules=n_rules, transactions=n_tx, plan_rows=n_plan)


# ---------- themes (Power BI style cards) ----------
BUILTIN_THEMES = {
    # the default: a gentle light look. Pastel surfaces, a soft lavender-white canvas, mid-tone accents (deep enough that the
    # big KPI numbers stay readable) and a quieter background glow
    "soft": dict(name="Soft", primary="#6670b8", dark="#3f4468", light="#eceef8", canvas="#f7f6fb",
                 border="#e0e1f0", accent="#e8a0b8",
                 types={"Scheduled": "#6670b8", "Budget": "#a9b4e8", "Extra": "#e8a0b8"},
                 kpi=["#2f9e82", "#e0687f", "#5b8def", "#9b7fe0"], glow=0.2),
    "forest": dict(name="Forest", primary="#1f4d3a", dark="#123226", light="#e4eee8", canvas="#f5f8f5",
                   border="#d3e0d7", accent="#b08d57",
                   types={"Scheduled": "#1f4d3a", "Budget": "#7fae93", "Extra": "#b08d57"}),
    "navy": dict(name="Navy", primary="#1e3a5f", dark="#0e2440", light="#e3eaf4", canvas="#f5f7fb",
                 border="#d0dbe9", accent="#c9a227",
                 types={"Scheduled": "#1e3a5f", "Budget": "#86a8d3", "Extra": "#c9a227"}),
    "burgundy": dict(name="Burgundy", primary="#7b2d3b", dark="#46141f", light="#f4e4e7", canvas="#fbf6f6",
                     border="#e8d2d6", accent="#b8864b",
                     types={"Scheduled": "#7b2d3b", "Budget": "#d7a1ab", "Extra": "#b8864b"}),
    "slate": dict(name="Slate", primary="#3b4a5c", dark="#1f2a37", light="#e6ebf1", canvas="#f5f7f9",
                  border="#d3dae2", accent="#7c8da3",
                  types={"Scheduled": "#3b4a5c", "Budget": "#9fb0c4", "Extra": "#b7791f"}),
    "teal": dict(name="Teal", primary="#0f766e", dark="#0a3f3b", light="#dcefed", canvas="#f2f9f8",
                 border="#c5e0dd", accent="#d08c3b",
                 types={"Scheduled": "#0f766e", "Budget": "#6cc0b8", "Extra": "#d08c3b"}),
    "terracotta": dict(name="Terracotta", primary="#9a4f2e", dark="#55291a", light="#f3e6db", canvas="#fbf7f2",
                       border="#e6d5c4", accent="#6b7f5a",
                       types={"Scheduled": "#9a4f2e", "Budget": "#dba883", "Extra": "#6b7f5a"}),
    "plum": dict(name="Plum", primary="#5b3a73", dark="#33204a", light="#ece3f2", canvas="#f9f6fb",
                 border="#dccbe6", accent="#b08d57",
                 types={"Scheduled": "#5b3a73", "Budget": "#b9a0cf", "Extra": "#b08d57"}),
    "charcoal": dict(name="Charcoal", primary="#2b2f36", dark="#14161a", light="#e9eaec", canvas="#f6f6f7",
                     border="#d9dbde", accent="#b9814a",
                     types={"Scheduled": "#2b2f36", "Budget": "#9aa0a8", "Extra": "#b9814a"}),
    # livelier palettes: each carries its own four KPI colors (Income, Expenses, Left, Left after budgets)
    "sunset": dict(name="Sunset", primary="#c2410c", dark="#4a1d0a", light="#fdeadb", canvas="#fff8f3",
                   border="#f3d3bd", accent="#be185d",
                   types={"Scheduled": "#c2410c", "Budget": "#f4a77a", "Extra": "#be185d"},
                   kpi=["#16a34a", "#dc2626", "#f59e0b", "#be185d"]),
    "ocean": dict(name="Ocean", primary="#0369a1", dark="#082f49", light="#dff0fa", canvas="#f3f9fd",
                  border="#c7e0ef", accent="#0d9488",
                  types={"Scheduled": "#0369a1", "Budget": "#7cc4e8", "Extra": "#0d9488"},
                  kpi=["#0d9488", "#f43f5e", "#0ea5e9", "#6366f1"]),
    "aurora": dict(name="Aurora", primary="#6d28d9", dark="#2e1065", light="#ede4fb", canvas="#f8f5fe",
                   border="#ddd0f5", accent="#10b981",
                   types={"Scheduled": "#6d28d9", "Budget": "#b9a1ec", "Extra": "#10b981"},
                   kpi=["#10b981", "#f43f5e", "#6d28d9", "#06b6d4"]),
    "midnight": dict(name="Midnight", primary="#4338ca", dark="#1e1b4b", light="#e5e7fb", canvas="#f6f6fd",
                     border="#d4d6f3", accent="#06b6d4",
                     types={"Scheduled": "#4338ca", "Budget": "#a5b4fc", "Extra": "#06b6d4"},
                     kpi=["#10b981", "#f43f5e", "#4338ca", "#06b6d4"]),
    "citrus": dict(name="Citrus", primary="#4d7c0f", dark="#1a2e05", light="#eef5d9", canvas="#fafcf1",
                   border="#dbe6b8", accent="#ea580c",
                   types={"Scheduled": "#4d7c0f", "Budget": "#b5d86a", "Extra": "#ea580c"},
                   kpi=["#4d7c0f", "#ea580c", "#0ea5e9", "#a855f7"]),
}
DEFAULT_KPI = ["#22a06b", "#e5604d", "#3b82f6", "#a855f7"]  # green, coral, blue, purple: themes without their own set
# how the four card colors are pulled into a theme: lean toward its primary, then its dark shade, then drain color.
# themes.json can change these for everything, and any one theme can override them with its own "kpi_tuning"
KPI_TUNING = dict(blend=0.18, deepen=0.08, mute=0.30)
DEFAULT_THEME = "soft"


def get_theme(name: str | None = None) -> dict:
    return THEMES.get(name or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def _mix(a: str, b: str, t: float) -> str:
    """Blend hex color a toward hex color b by fraction t."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _mute(c: str, t: float) -> str:
    """Drain color from hex c toward the gray of the same brightness by fraction t (0 = unchanged, 1 = gray)."""
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return _mix(c, f"#{y:02x}{y:02x}{y:02x}", t)


PRISM_STOPS = ["#ff5f9e", "#ffa94d", "#ffe066", "#4fe3a2", "#4cc9f0", "#8f7bff"]  # pink, orange, yellow, green, cyan, violet


# each theme's own spectrum: the colours its charts, rings, banner strip and tab underline run through
BUILTIN_SPECTRA = {
    "soft":       ["#f4a6c0", "#f7c59f", "#f6e3a1", "#a8dcc0", "#9fd3ea", "#b5a8ee"],  # pastel rainbow
    "forest":     ["#d9b36a", "#a8c97f", "#5fae7e", "#2f8a68", "#7fb8a4", "#c9a65f"],  # moss, fern and gold
    "navy":       ["#c9a227", "#e8c46a", "#9bbbe0", "#5b8bc9", "#3b6bb0", "#86a8d3"],  # brass and deep blues
    "burgundy":   ["#e0788c", "#c9506a", "#d9954f", "#e6b072", "#d7a1ab", "#a8435b"],  # wine, rose and amber
    "slate":      ["#8aa0b8", "#6fa8b8", "#9fb0c4", "#d9a441", "#b7791f", "#7c8da3"],  # steel with a copper spark
    "teal":       ["#5eead4", "#2dd4bf", "#14a89f", "#38bdf8", "#e0a24f", "#f4c26b"],  # lagoon and sand
    "terracotta": ["#e07a5f", "#f2a65a", "#e9c46a", "#a8bd84", "#7f9468", "#c9754d"],  # clay, sun and sage
    "plum":       ["#d17bb5", "#b06bd0", "#8a5bd0", "#e8a0b8", "#d9b36a", "#8f6bb8"],  # orchid and berry
    "charcoal":   ["#e5a35c", "#d98a4a", "#b0b6bf", "#6fa3c8", "#8fb8a0", "#c9b27c"],  # ember on graphite
    "sunset":     ["#ff4d6d", "#ff7a45", "#ffb347", "#ffd166", "#f06292", "#c2185b"],  # hot sky
    "ocean":      ["#2dd4bf", "#22d3ee", "#38bdf8", "#3b82f6", "#6366f1", "#34d399"],  # surf to deep water
    "aurora":     ["#34d399", "#2dd4bf", "#38bdf8", "#8b5cf6", "#d946ef", "#f472b6"],  # northern lights
    "midnight":   ["#22d3ee", "#60a5fa", "#818cf8", "#a78bfa", "#e879f9", "#34d399"],  # neon night
    "citrus":     ["#a3e635", "#facc15", "#fb923c", "#f43f5e", "#22d3ee", "#84cc16"],  # lime, lemon, blood orange
}


# ---------- themes.json ----------
# The themes live in themes.json next to this script, so you can change a color or add a theme without touching code.
# The built-in themes above are the fallback: if the file is missing or broken, they are used and a warning shows in
# the Appearance panel. A theme that has a problem is skipped (and named in that warning); the rest still load.
THEMES_FILE = Path(__file__).resolve().parent / "themes.json"
THEME_WARNINGS: list[str] = []
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX.match(v))


def _theme_problem(t) -> str | None:
    """Why a theme from themes.json can't be used, in plain words (None when it's fine)."""
    if not isinstance(t, dict):
        return "it isn't a block of settings"
    if not isinstance(t.get("name"), str) or not t["name"].strip():
        return "it needs a name"
    for k in ("primary", "dark", "light", "canvas", "border", "accent"):
        if not _is_hex(t.get(k)):
            return f"{k} must be a color like #6670b8"
    ty = t.get("types")
    if not isinstance(ty, dict) or not all(_is_hex(ty.get(k)) for k in ("Scheduled", "Budget", "Extra")):
        return "types needs Scheduled, Budget and Extra colors"
    for k, n in (("kpi", 4), ("spectrum", 6)):
        if k in t and not (isinstance(t[k], list) and len(t[k]) == n and all(_is_hex(c) for c in t[k])):
            return f"{k} must be a list of {n} colors"
    if "glow" in t and not (isinstance(t["glow"], (int, float)) and 0 <= t["glow"] <= 1):
        return "glow must be a number from 0 to 1"
    kt = t.get("kpi_tuning")
    if kt is not None and not (isinstance(kt, dict) and all(k in ("blend", "deepen", "mute") and isinstance(v, (int, float))
                                                              and 0 <= v <= 1 for k, v in kt.items())):
        return "kpi_tuning can hold blend, deepen and mute, each a number from 0 to 1"
    return None


def load_themes() -> tuple[dict, dict, str, dict]:
    """(themes, spectra, default theme, card-color tuning) from themes.json, or the built-ins if it can't be used."""
    THEME_WARNINGS.clear()
    builtin = (dict(BUILTIN_THEMES), dict(BUILTIN_SPECTRA), "soft", dict(KPI_TUNING))
    if not THEMES_FILE.exists():
        return builtin
    try:
        raw = json.loads(THEMES_FILE.read_text(encoding="utf-8"))
        block = raw["themes"]
        if not isinstance(block, dict):
            raise ValueError('"themes" must be a list of named themes')
    except Exception as e:
        THEME_WARNINGS.append(f"themes.json couldn't be read ({type(e).__name__}: {e}), so the built-in themes are in use.")
        return builtin
    themes, spectra = {}, {}
    for key, t in block.items():
        why = _theme_problem(t)
        if why:
            THEME_WARNINGS.append(f"Theme \"{key}\" in themes.json was skipped: {why}.")
            continue
        themes[key] = {k: v for k, v in t.items() if k != "spectrum"}
        if "spectrum" in t:
            spectra[key] = t["spectrum"]
    if not themes:
        THEME_WARNINGS.append("themes.json has no usable themes, so the built-in themes are in use.")
        return builtin
    default = raw.get("default_theme") if raw.get("default_theme") in themes else next(iter(themes))
    tuning = dict(KPI_TUNING)
    kt = raw.get("kpi_tuning")
    if isinstance(kt, dict):
        tuning.update({k: float(v) for k, v in kt.items() if k in tuning and isinstance(v, (int, float))})
    return themes, spectra, default, tuning


THEMES, SPECTRA, DEFAULT_THEME, KPI_TUNING = load_themes()


def build_ui(name: str | None, dark: bool = False) -> dict:
    """Full palette for a theme in light or dark mode."""
    t = get_theme(name)
    # the four card colors (and everything built from them) lean toward the theme's own primary and dark shade, so a
    # number never looks louder than the rest of the palette; they stay recognizably green, red, blue and purple
    tune = {**KPI_TUNING, **(t.get("kpi_tuning") or {})}
    kpi = [_mute(_mix(_mix(c, t["primary"], tune["blend"]), t["dark"], tune["deepen"]), tune["mute"])
           for c in t.get("kpi", DEFAULT_KPI)]
    if dark:  # brighter on a dark canvas so the numbers keep their pop
        kpi = [_mix(c, "#ffffff", 0.22) for c in kpi]
    common = dict(name=t["name"], accent=t["accent"], b1=t["dark"], b2=t["primary"], dark_mode=dark, kpi=kpi,
                  spec=SPECTRA.get(name or DEFAULT_THEME, PRISM_STOPS),
                  glow=t.get("glow", 0.32))  # how strong the animated background glow is for this theme
    if not dark:
        # easy on the eyes: a slightly deeper, warmer canvas, and cards that are off-white instead of pure white
        canvas = _mix(_mix(t["canvas"], "#000000", 0.11), "#e3d6c3", 0.4)  # a touch of warm cream
        return dict(common, primary=t["primary"], dark=t["dark"], light=_mix(t["light"], canvas, 0.35), canvas=canvas,
                    border=_mix(t["border"], canvas, 0.2), types=t["types"], surface=_mix(canvas, "#ffffff", 0.28),
                    text=t["dark"], muted="#5b6371",
                    chart_text="#374151", page_text="#1f2937", base="light", on_primary="#ffffff")
    canvas = _mix(t["dark"], "#000000", 0.35)
    lifted = _mix(t["primary"], "#ffffff", 0.45)
    return dict(common, primary=lifted, dark=t["dark"], light=_mix(canvas, "#ffffff", 0.05), canvas=canvas,
                border=_mix(canvas, "#ffffff", 0.17), surface=_mix(canvas, "#ffffff", 0.07), text="#e8ecea",
                muted="#9aa3ad", chart_text="#d1d5db", page_text="#e5e7eb", base="dark", on_primary=canvas,
                # Budget is a mid-tone, not the light pastel, so it reads apart from the lifted Scheduled color on dark
                types={"Scheduled": lifted, "Budget": _mix(t["types"]["Budget"], canvas, 0.45), "Extra": t["accent"]})


def semantic_colors(ui: dict) -> dict:
    """Good, warning and bad colors that belong to the chosen theme: the same greens and reds as its Income and
    Expenses cards, and an amber nudged toward the theme's accent, so a paid bill, a bar near its limit and an overdue
    bill all look like part of the same palette instead of stock traffic-light colors."""
    return dict(good=ui["kpi"][0], bad=ui["kpi"][1], warn=_mix("#f59e0b", ui["accent"], 0.2))


def tint_pair(ui: dict, c: str) -> tuple[str, str]:
    """(background, text) for a color: a pale tint with dark text on light themes, a deep tint with light text on dark."""
    if ui["dark_mode"]:
        return _mix(ui["canvas"], c, 0.28), _mix(c, "#ffffff", 0.4)
    return _mix(c, "#ffffff", 0.86), _mix(c, "#000000", 0.38)


def status_palette(ui: dict) -> dict:
    """(background, text) for each bill/budget state, built from the theme's own colors. Light themes get a pale tint
    with darker text; dark mode gets a deep tint with lighter text."""
    sem = semantic_colors(ui)

    good, warn, bad = tint_pair(ui, sem["good"]), tint_pair(ui, sem["warn"]), tint_pair(ui, sem["bad"])
    return {"paid": good, "ok": ("transparent", good[1]), "soon": warn, "warn": warn, "overdue": bad, "over": bad,
            "neutral": (_mix(ui["canvas"], ui["primary"], 0.12), ui["text"])}


def glow_columns_css(ui: dict, n: int = 16, cell: int = 7, gap: int = 1) -> tuple[str, str, str, str, int]:
    """The pieces of the animated background (the prismic 'colour columns' effect, in pure CSS). Each of the n columns is a
    tall tile of cells: a ramp that brightens from the canvas colour up to a theme colour (a fading tail ending in a bright
    head), then a few empty cells before the next drop. Sliding the tile down one or two cells per tick makes the drops
    fall; every column starts at a staggered offset and every other column falls twice as fast, so the colours cascade
    across the page in diagonal waves. Returns the CSS layer lists plus the number of animation steps."""
    kp = ui["kpi"]
    base = [ui["primary"], kp[0], ui["accent"], kp[2], kp[3], kp[1],
            _mix(ui["primary"], ui["accent"], 0.5), _mix(kp[0], kp[2], 0.5)]
    colors = [base[i % 8] if i < 8 else _mix(base[i % 8], base[(i + 1) % 8], 0.5) for i in range(n)]
    ramp, blank = 11, 5
    cells = ramp + blank
    pitch = cell + gap
    tile = cells * pitch
    images = []
    for c in colors:
        stops = []
        for i in range(cells):
            y = i * pitch
            if i < ramp:
                shade = _mix(ui["canvas"], c, 0.08 + 0.92 * (i / (ramp - 1)) ** 1.5)
                stops.append(f"{shade} {y}px {y + cell}px, transparent {y + cell}px {y + pitch}px")
            else:
                stops.append(f"transparent {y}px {y + pitch}px")
        images.append("linear-gradient(to bottom, " + ", ".join(stops) + ")")
    width = f"calc({100 / n:g}vw - {gap}px)"
    sizes = ", ".join(f"{width} {tile}px" for _ in colors)
    offs = [((i * 3) % cells) * pitch for i in range(n)]  # a different starting phase per column
    start = ", ".join(f"calc({i} * {100 / n:g}vw) {offs[i]}px" for i in range(n))
    end = ", ".join(f"calc({i} * {100 / n:g}vw) {offs[i] + tile * (1 if i % 2 == 0 else 2)}px" for i in range(n))
    return ", ".join(images), sizes, start, end, cells


ANIM_BGS = ["Columns", "Shooting stars", "Color drip", "Gradient lines", "Angled pattern", "Octagons",
            "Shifting pattern", "Triangles", "Stars", "Prismatic parallax drift", "Weather: Sunny", "Weather: Cloudy",
            "Weather: Rain", "Weather: Storm", "Weather: Snow", "Weather: Fog", "None"]


def _scatter(n: int, seed: int) -> list[tuple[float, float]]:
    """n repeatable pseudo-random points as percentages of a box (the same every time, so a pattern never jumps)."""
    x, out = seed, []
    for _ in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        px = x / 0x7FFFFFFF * 100
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((px, x / 0x7FFFFFFF * 100))
    return out


def bg_css(ui: dict, kind: str) -> str:
    """CSS for one animated background, replacing the colour columns on the page's two background layers (::before is
    the main one, ::after a second one for effects that need it). Speeds follow --spd, so the Speed setting applies."""
    dark, sp = ui["dark_mode"], list(ui["spec"])
    ink = ui["dark"]

    def tint(c: str, a: float = 1.0) -> str:  # a spectrum colour that reads on this theme's canvas, with an alpha
        c2 = _mix(c, "#ffffff", 0.25) if dark else _mix(c, ink, 0.12)
        return c2 if a >= 1 else f"color-mix(in srgb, {c2} {round(a * 100)}%, transparent)"

    def secs(s: float) -> str:
        return f"calc({s:g}s * var(--spd))"

    def props(prefix: str, n: int, syntax: str = "<number>", init: str = "0") -> str:
        return "".join(f"@property --{prefix}{i} {{ syntax: '{syntax}'; inherits: false; initial-value: {init}; }}"
                       for i in range(1, n + 1))

    fade = "linear-gradient(to bottom, #000 0%, #000 55%, transparent 100%)"
    reset = ('[data-testid="stAppViewContainer"]::before { background-image: none; background-size: auto; '
             'background-position: 0 0; background-repeat: repeat; animation: none; opacity: 1; '
             f'-webkit-mask-image: {fade}; mask-image: {fade}; transform: none; }}')
    layer2 = ('[data-testid="stAppViewContainer"]::after { content: ""; position: fixed; inset: 0; z-index: -1; '
              'pointer-events: none; ')

    def dots(n: int, seed: int, radius: float, colors: list[str]) -> tuple[list[str], list[str]]:
        imgs = []
        for i, (px, py) in enumerate(_scatter(n, seed)):
            col = colors[i % len(colors)]
            imgs.append(f"radial-gradient(circle at {px:.1f}% {py:.1f}%, {col} 0, {col} {radius:g}px, "
                        f"transparent {radius + 0.9:g}px)")
        return imgs, imgs

    if kind.startswith("Weather: "):
        # One street in the chosen weather, an animated picture kept in ledger_html/static/weather/ (the same scenes as the
        # Claude chat "seasons" mod). Laid over the page like the other backgrounds, faded back so the cards stay readable.
        name = kind.split(": ", 1)[1].lower()
        return (reset + '[data-testid="stAppViewContainer"]::before { '
                f'opacity: {0.6 if dark else 0.45}; background: url(/weather/{name}.svg) center / cover no-repeat; '
                '-webkit-mask-image: none; mask-image: none; }')

    if kind == "Prismatic parallax drift":
        # The colors and layering are Codioful's "Prismatic parallax drift" (codioful.com/visual/prismatic-parallax-drift, free to
        # use with credit). Their CSS is a still picture; the drift is added here, in three layers that move at different speeds
        # (the parallax): the diagonal stripes run from the upper left to the lower right, the fine red lines run down faster,
        # and the two glows sway slowly against each other. The stripes and lines move by exactly one tile, so the loop never jumps.
        glow = ("radial-gradient(ellipse farthest-corner at 50% 75%, transparent 0%, transparent 52.13%, rgba(131, 56, 236, 0.4) 73.74%, "
                "rgba(131, 56, 236, 1) 100%), radial-gradient(ellipse farthest-corner at 0% 0%, transparent 0%, transparent 47.4%, "
                "rgba(255, 20, 147, 0.4) 78.17%, rgba(255, 20, 147, 1) 100%), "
                "linear-gradient(0deg, rgba(255, 0, 64, 0.5) 1px, transparent 1px), "
                "repeating-linear-gradient(45deg, rgba(255, 0, 255, 0.5) 0%, rgba(0, 255, 255, 0.5) 49.9%, rgba(255, 0, 255, 0.5) 50%, "
                "rgba(0, 255, 255, 0.5) 99.9%, rgba(0, 255, 255, 0.5) 100%), "
                "linear-gradient(150deg, rgba(255, 107, 53, 1) 0%, rgba(239, 71, 111, 1) 100%)")
        return (reset + props("pp", 3)
                + '[data-testid="stAppViewContainer"]::before { '
                  f'opacity: {0.55 if dark else 0.4}; background: {glow}; '
                  'background-size: 150% 150%, 150% 150%, 100% 2vh, 25vw 25vh, auto; '
                  'background-blend-mode: exclusion, exclusion, difference, screen, normal; '
                  'background-position: calc(var(--pp1) * 100%) calc(var(--pp1) * 100%), calc((1 - var(--pp1)) * 100%) calc((1 - var(--pp1)) * 100%), '
                  '0 calc(var(--pp2) * 2vh), calc(var(--pp3) * 25vw) calc(var(--pp3) * 25vh), 0 0; '
                  '-webkit-mask-image: none; mask-image: none; '
                  f'animation: ft-pp1 {secs(44)} ease-in-out infinite alternate, ft-pp2 {secs(6)} linear infinite, '
                  f'ft-pp3 {secs(26)} linear infinite; }}'
                  '@keyframes ft-pp1 { from { --pp1: 0; } to { --pp1: 1; } }'
                  '@keyframes ft-pp2 { from { --pp2: 0; } to { --pp2: 1; } }'
                  '@keyframes ft-pp3 { from { --pp3: 0; } to { --pp3: 1; } }')

    if kind == "Shooting stars":
        star_cols = [tint(c, 0.95) for c in sp]
        imgs, _ = dots(46, 7, 1.6, star_cols)
        n = 6
        streak_y = [14, 38, 62, 88, 118, 150]
        durs, delays = [9, 13, 11, 17, 15, 12], [0, -4, -7, -2, -10, -5]
        streaks = ", ".join(f"linear-gradient(90deg, transparent, {tint(sp[(i * 2) % 6], 1)})" for i in range(n))
        sizes = ", ".join("260px 3px" for _ in range(n))
        poss = ", ".join(f"calc(var(--t{i}) * 200vw - 260px) {streak_y[i - 1]}vh" for i in range(1, n + 1))
        kfs = "".join(f"@keyframes ft-sh{i} {{ 0% {{ --t{i}: 0; }} 16% {{ --t{i}: 1; }} 100% {{ --t{i}: 1; }} }}"
                      for i in range(1, n + 1))
        anims = ", ".join(f"ft-sh{i} {secs(durs[i - 1])} linear {delays[i - 1]}s infinite" for i in range(1, n + 1))
        return (props("t", n) + kfs + reset
                + f'[data-testid="stAppViewContainer"]::before {{ background-image: {", ".join(imgs)}; '
                  f'background-size: 100% 100%; animation: ft-twinkle {secs(7)} ease-in-out infinite alternate; }}'
                  '@keyframes ft-twinkle { from { opacity: .45; } to { opacity: 1; } }'
                + layer2 + f'inset: -50%; transform: rotate(30deg); background-repeat: no-repeat; opacity: .85; '
                           f'background-image: {streaks}; background-size: {sizes}; background-position: {poss}; '
                           f'animation: {anims}; }}')

    if kind == "Color drip":
        n = 14
        xs = [4 + i * (92 / (n - 1)) + (-1) ** i * 1.2 for i in range(n)]
        durs = [8, 11, 7, 13, 9, 15, 10, 12, 7.5, 14, 9.5, 11.5, 8.5, 13.5]
        delays = [0, -3, -6, -1, -9, -4, -7, -2, -11, -5, -8, -10, -12, -3.5]
        drips = ", ".join(f"linear-gradient(to bottom, transparent, {tint(sp[i % 6], 0.9)})" for i in range(n))
        sizes = ", ".join("3px 190px" for _ in range(n))
        poss = ", ".join(f"{xs[i - 1]:.1f}% calc(var(--t{i}) * (100vh + 380px) - 190px)" for i in range(1, n + 1))
        kfs = "".join(f"@keyframes ft-dr{i} {{ 0% {{ --t{i}: 0; }} 72% {{ --t{i}: 1; }} 100% {{ --t{i}: 1; }} }}"
                      for i in range(1, n + 1))
        anims = ", ".join(f"ft-dr{i} {secs(durs[i - 1])} cubic-bezier(.45,.05,.8,.6) {delays[i - 1]}s infinite"
                          for i in range(1, n + 1))
        return (props("t", n) + kfs + reset
                + f'[data-testid="stAppViewContainer"]::before {{ background-repeat: no-repeat; opacity: .85; '
                  f'background-image: {drips}; background-size: {sizes}; background-position: {poss}; '
                  f'animation: {anims}; }}')

    if kind == "Gradient lines":
        a, b, c = tint(sp[1], 0.5), tint(sp[3], 0.5), tint(sp[5], 0.5)
        return (props("m", 2, "<length>", "0px") + reset
                + '@keyframes ft-gl1 { from { --m1: 0px; } to { --m1: 60vw; } }'
                  '@keyframes ft-gl2 { from { --m2: 0px; } to { --m2: 40vw; } }'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: .9; background-repeat: repeat-x, repeat-x, repeat; '
                  f'background-image: linear-gradient(90deg, transparent, {a} 55%, transparent), '
                  f'linear-gradient(90deg, transparent, {b} 50%, transparent), '
                  f'repeating-linear-gradient(90deg, transparent 0 26px, {tint(sp[0], 0.22)} 26px 27px); '
                  f'background-size: 60vw 100%, 40vw 100%, auto; '
                  f'background-position: var(--m1) 0, calc(-1 * var(--m2)) 0, 0 0; '
                  f'animation: ft-gl1 {secs(16)} linear infinite, ft-gl2 {secs(23)} linear infinite; }}')

    if kind == "Angled pattern":
        def rows(c1: str, c2: str) -> str:
            return (f"linear-gradient(112deg, {c1} 0 36%, transparent 36% 50%, {c2} 50% 86%, transparent 86%)")
        band = "linear-gradient(to bottom, #000 0 64px, transparent 64px)"  # every other row of 64px
        both = f"{band}, {fade}"
        mask = (f"-webkit-mask-image: {both}; mask-image: {both}; -webkit-mask-size: 100% 128px, 100% 100%; "
                "mask-size: 100% 128px, 100% 100%; -webkit-mask-repeat: repeat, no-repeat; mask-repeat: repeat, no-repeat; "
                "-webkit-mask-composite: source-in; mask-composite: intersect; ")
        return (reset
                + '@keyframes ft-ang-r { to { background-position: 150px 0; } }'
                  '@keyframes ft-ang-l { to { background-position: -150px 0; } }'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: .42; {mask} '
                  f'background-image: {rows(tint(sp[0], 0.55), tint(sp[2], 0.4))}; background-size: 150px 128px; '
                  f'animation: ft-ang-r {secs(14)} linear infinite; }}'
                + layer2 + f'opacity: .42; {mask}-webkit-mask-position: 0 64px, 0 0; mask-position: 0 64px, 0 0; '
                           f'background-image: {rows(tint(sp[3], 0.55), tint(sp[5], 0.4))}; background-size: 150px 128px; '
                           f'animation: ft-ang-l {secs(18)} linear infinite; }}')

    if kind == "Octagons":
        s, gap = 84, 2
        fill = f"color-mix(in srgb, {tint(sp[4], 1)} 17%, transparent)"
        cv = ui["canvas"]
        cut = lambda ang: f"linear-gradient({ang}deg, {cv} var(--c), transparent var(--c))"
        return (props("c", 1, "<length>", "0px").replace("--c1", "--c") + reset
                + '@keyframes ft-oct { from { --c: 0px; } to { --c: 36px; } }'
                  f'@keyframes ft-octmove {{ to {{ background-position: {s * 2}px {s * 2}px; }} }}'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: 1; '
                  f'background-image: linear-gradient(to right, {cv} 0 {gap}px, transparent {gap}px), '
                  f'linear-gradient(to bottom, {cv} 0 {gap}px, transparent {gap}px), '
                  f'{cut(135)}, {cut(225)}, {cut(315)}, {cut(45)}, '
                  f'linear-gradient({fill}, {fill}); background-size: {s}px {s}px; '
                  f'animation: ft-oct {secs(7)} ease-in-out infinite alternate, ft-octmove {secs(40)} linear infinite; }}')

    if kind == "Shifting pattern":
        c1, c2, c3, c4 = (tint(sp[i], 0.30) for i in (0, 2, 3, 5))
        return (reset
                + '@keyframes ft-shift { 0%, 24.99% { background-position: 0 0, 0 0; } '
                  '25%, 49.99% { background-position: 48px 0, -28px 28px; } '
                  '50%, 74.99% { background-position: 48px 48px, -28px 0; } '
                  '75%, 100% { background-position: 0 48px, 0 -28px; } }'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: .9; '
                  f'background-image: conic-gradient(from 45deg at 50% 50%, {c1} 0 25%, transparent 0 50%, {c2} 0 75%, transparent 0), '
                  f'conic-gradient(from 0deg at 50% 50%, {c3} 0 25%, transparent 0 50%, {c4} 0 75%, transparent 0); '
                  f'background-size: 96px 96px, 56px 56px; '
                  f'animation: ft-shift {secs(8)} steps(1, end) infinite; }}')

    if kind == "Triangles":
        def tile(w: int, h: int, c: tuple[str, str, str], a: float) -> str:
            cols = [_mix(x, ink, 0.1) if not dark else _mix(x, "#ffffff", 0.2) for x in c]
            svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
                   f"<polygon points='{w / 2},0 0,{h} {w},{h}' fill='{cols[0]}' fill-opacity='{a}'/>"
                   f"<polygon points='0,0 {w / 2},0 0,{h}' fill='{cols[1]}' fill-opacity='{a * .8:.3f}'/>"
                   f"<polygon points='{w / 2},0 {w},0 {w},{h}' fill='{cols[2]}' fill-opacity='{a * .65:.3f}'/></svg>")
            enc = svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E")
            return f'url("data:image/svg+xml,{enc}")'
        t1 = tile(120, 104, (sp[0], sp[2], sp[4]), 0.20)
        t2 = tile(220, 190, (sp[1], sp[3], sp[5]), 0.16)
        return (reset
                + '@keyframes ft-tri { to { background-position: 120px 104px, -220px 190px; } }'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: 1; background-image: {t1}, {t2}; '
                  f'background-size: 120px 104px, 220px 190px; animation: ft-tri {secs(60)} linear infinite; }}')

    if kind == "Stars":
        cols = [tint(c, 0.8) for c in sp]
        i1, _ = dots(18, 11, 1.2, cols)
        i2, _ = dots(12, 23, 1.7, cols[::-1])
        i3, _ = dots(8, 37, 2.4, cols)
        imgs = i1 + i2 + i3
        sizes = ", ".join([*(["320px 320px"] * len(i1)), *(["520px 520px"] * len(i2)), *(["860px 860px"] * len(i3))])
        return (reset
                + '@keyframes ft-par { to { background-position: '
                  + ", ".join([*(["0 -320px"] * len(i1)), *(["0 -520px"] * len(i2)), *(["0 -860px"] * len(i3))])
                + '; } }'
                + f'[data-testid="stAppViewContainer"]::before {{ opacity: .95; background-image: {", ".join(imgs)}; '
                  f'background-size: {sizes}; animation: ft-par {secs(90)} linear infinite; }}')
    return ""  # Columns (the default, already in theme_css) and None are handled by the caller


ANIM_SPEEDS = {"Calm": 1.0, "Medium": 0.5, "Lively": 0.22}  # multiplies every animation's duration
# which effects each style turns on: bg = falling colour columns, ring = spinning spectrum ring on the top cards,
# glare = the sweeping rainbow glare, flow = drifting banner strip / title / tab underline / pulsing dots / progress bar /
# hover lines, enter = cards rising in and the typewriter title
ANIM_STYLES = {
    "Prismatic": dict(bg=True, ring=True, glare=True, flow=True, enter=True),
    "Cascade":   dict(bg=True, ring=False, glare=False, flow=False, enter=True),
    "Shimmer":   dict(bg=False, ring=True, glare=True, flow=True, enter=True),
    "Gentle":    dict(bg=False, ring=False, glare=False, flow=False, enter=True),
}
