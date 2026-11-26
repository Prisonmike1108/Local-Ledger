"""
FinanceEmail.py - emails a Personal Finance Ledger payday summary.

Usage:
    python FinanceEmail.py              send if a payday fell in the last `catchup_days` days and it wasn't sent yet
    python FinanceEmail.py --test       send the current period to the test address (never blocks the real one)
    python FinanceEmail.py --preview    write the email to email_preview.html; sends nothing
    python FinanceEmail.py --force      send the current period now, even if already sent

Options for --test and --preview (used by the dashboard's Email tab):
    --to a@x.com b@y.com      who gets the test (default: the saved test address)
    --period 2026-11-06       which paycheck's numbers to show (default: the current one)
    --hide "Item A" "Item B"  items to leave out (default: the saved list; --hide alone leaves nothing out)
    --season fall             try a season's look (winter, spring, summer, fall; default: the paycheck's own season)

Settings: finance_data/email_settings.json.  The Gmail app password is read from the GMAIL_APP_PASSWORD
environment variable, or from secrets.toml next to this file (GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx").
All numbers come from the same functions the dashboard uses, so they match the Overview.
"""
import argparse
import base64
import csv
import html
import json
import os
import random
import smtplib
import ssl
import sys
import tomllib
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pandas as pd  # noqa: E402
import FinanceDashboard as fd  # noqa: E402  (its UI only runs under __main__, so importing is safe)

DATA = fd.DATA_DIR
# the settings file can be named by the environment, so the dashboard can preview with sample numbers (DATA above comes
# from FINANCE_DATA_DIR) while still using your real email settings
SETTINGS_FILE = Path(os.environ.get("FINANCE_EMAIL_SETTINGS") or DATA / "email_settings.json")
LOG_FILE = DATA / "email_log.csv"
RUNNER_FILE = DATA / "runner_last.json"
PREVIEW_FILE = HERE / "email_preview.html"


def esc(x) -> str:
    return html.escape(str(x))


def runner_note(message: str, ok: bool) -> None:
    RUNNER_FILE.write_text(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "message": message, "ok": ok}))


def already_sent(period: str) -> bool:
    if not LOG_FILE.exists():
        return False
    with LOG_FILE.open(newline="", encoding="utf-8") as f:
        return any(r.get("period_start") == period and r.get("status") == "sent" for r in csv.DictReader(f))


def log_send(period: str, recipients: list[str], status: str) -> None:
    new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at", "period_start", "recipients", "status"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), period, ";".join(recipients), status])


def app_password() -> str:
    pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not pw:
        sec = HERE / "secrets.toml"
        if sec.exists():
            pw = str(tomllib.loads(sec.read_text(encoding="utf-8")).get("GMAIL_APP_PASSWORD", ""))
    return pw.replace(" ", "").strip()


# ---------- numbers ----------
def period_starts() -> list[str]:
    return fd.all_period_starts(fd.load("plan"), fd.load("income"), fd.load("periods"))


def build_summary(period: str | None = None, compare: list[str] | None = None) -> dict:
    plan, income, tx = fd.load("plan"), fd.load("income"), fd.load("transactions")
    budgets, debts = fd.load("budgets"), fd.load("debts")
    settings = fd.load_settings()
    starts = fd.all_period_starts(plan, income, fd.load("periods"))
    if not starts:
        raise RuntimeError("No pay periods set up yet.")
    tx["period_start"] = fd.assign_period(tx["date"], starts)
    period = period or fd.current_period(starts)
    if period not in starts:
        raise RuntimeError(f"{period} isn't one of your paycheck dates.")

    ep_hold = fd.effective_plan(plan, tx, starts, budgets, True)  # budgets held at their full limit
    pinc = fd.load_planned_income(income)
    pnames = {x.lower() for x in pinc["source"]}
    inc_eff = fd.effective_income(income, tx, starts, pnames)
    savings_R, _rem, _direct = fd.savings_flow(tx, starts, settings)
    opening, _anchor = fd.reconciled_opening(starts, ep_hold, inc_eff, tx, pnames, settings)
    summary = fd.period_summary(starts, ep_hold, inc_eff,
                                {**settings, "opening_balance": opening, "_setaside": savings_R})
    row = summary[summary.period_start == period].iloc[0]
    i = list(summary.period_start).index(period)

    items = ep_hold[(ep_hold.period_start == period) & (ep_hold.amount > 0)].copy()
    bl = set(fd.budget_limits(budgets))
    items["type"] = items.apply(
        lambda r: "Extra" if r.kind == "extra" else "Budget" if str(r["item"]).lower() in bl else "Scheduled", axis=1)
    # what each item was the last time it came up before this paycheck (a monthly bill skips every other paycheck, so
    # this looks back past the one before); NaN when it's new
    earlier = ep_hold[(ep_hold.period_start < period) & (ep_hold.amount > 0)].copy()
    earlier["k"] = earlier["item"].str.lower()
    prev_amt = (earlier.groupby(["k", "period_start"])["amount"].sum().reset_index()
                .sort_values("period_start").groupby("k")["amount"].last())
    items["prev"] = items["item"].str.lower().map(prev_amt)
    items["due"] = [fd.occurrence(period, d) for d in items["due_day"]]
    items["order"] = items["kind"].map({k: n for n, k in enumerate(fd.KINDS)})
    items["due_sort"] = [d or date.max for d in items["due"]]
    items = items.sort_values(["order", "due_sort", "amount"], ascending=[True, True, False])

    # spending face-off (groceries vs dining out, by default). The email goes out on payday morning, when the new
    # paycheck has no spending yet, so the headline is the paycheck that just ENDED, next to the one before it.
    sp = fd.spend_by_category(tx, starts)
    sp["key"] = sp["category"].str.lower()

    def spent(p: str | None, name: str) -> tuple[float, int]:
        if p is None:
            return 0.0, 0
        m = sp[(sp.period_start == p) & (sp.key == name.strip().lower())]
        return max(-float(m["net"].sum()), 0.0), int(m["count"].sum())

    prev, prev2 = (starts[i - 1] if i > 0 else None), (starts[i - 2] if i > 1 else None)
    limits = fd.budget_limits(budgets)
    if compare is None:  # Groceries and Dining Out, plus every other budget you add
        compare = ["Groceries", "Dining Out"]
        seen = {n.lower() for n in compare}
        compare += [name for key, (name, _l) in limits.items() if key not in seen]
    face = [dict(name=n, last=spent(prev, n)[0], count=spent(prev, n)[1], before=spent(prev2, n)[0],
                 now=spent(period, n)[0], limit=limits.get(n.strip().lower(), (n, None))[1])
            for n in compare] if prev else []

    inc_rows = inc_eff[inc_eff.period_start == period][["source", "amount"]]
    nxt = next((s for s in starts if s > period), None)
    in_email = debts[debts["in_email"].astype(str).str.lower().isin(["true", "1", "yes"])] if len(debts) else debts
    return dict(period=period, label=fd.label(period), income=float(row.income), expenses=float(row.expenses),
                left=float(row.available), items=items, income_rows=inc_rows,
                next_payday=nxt, debts=in_email, face=face, face_label=fd.label(prev) if prev else "",
                face_has_before=prev2 is not None)


# ---------- email body ----------
# Built for mail apps: tables and inline styles only, one 600px column that shrinks to the phone's width, and no
# row wider than two columns, so nothing needs to reflow on a small screen.
NAVY, GOLD, INK, MUTED, LINE, PAGE, TILE = "#16284a", "#e0b23c", "#1c2433", "#69748a", "#e8ecf3", "#eef2f8", "#f5f7fb"
FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _day(d: date) -> str:
    return f"{d:%a %b} {d.day}"


# The look follows the season of the paycheck's date: header color, accent, soft backgrounds, emoji and greeting.
SEASONS = {
    "winter": dict(head="#1d3557", accent="#8ecae6", page="#edf3f9", tile="#f2f7fb", note="#e6f2fa", bars="#4a90c2",
                   emoji="&#10052;&#65039;", trim="&#10052;&#65039; &#9731;&#65039; &#127784;&#65039;",
                   name="Winter", greet="Stay cozy, it's payday!"),
    "spring": dict(head="#2d6a4f", accent="#f29bb8", page="#f0f7f1", tile="#f4f9f4", note="#fdeaf1", bars="#52b788",
                   emoji="&#127799;", trim="&#127799; &#127793; &#128029;",
                   name="Spring", greet="Fresh paycheck, fresh start!"),
    "summer": dict(head="#0b6e8f", accent="#ffc93c", page="#eef8fb", tile="#f3fafc", note="#fff4cf", bars="#1fa3c4",
                   emoji="&#9728;&#65039;", trim="&#9728;&#65039; &#127754; &#127817;",
                   name="Summer", greet="Sunny days and payday!"),
    "fall":   dict(head="#7a3b12", accent="#e58a1f", page="#f9f2ea", tile="#fbf6ef", note="#fdebd2", bars="#b5651d",
                   emoji="&#127810;", trim="&#127810; &#127809; &#127875;",
                   name="Fall", greet="Sweater weather and payday!"),
}


def season_of(d: date) -> str:
    return "winter" if d.month in (12, 1, 2) else "spring" if d.month <= 5 else "summer" if d.month <= 8 else "fall"


ART_CID = "kl-season-art"  # the header animation travels inside the email and is shown by this id
BOUNCE_CID = "kl-bounce"    # so does the little hopper at the bottom
BAND_CID = "kl-band"        # confetti strips between the sections (one picture, shown many times)
WALK_CID = "kl-walk-"       # a confetti strip with a Pokemon strolling along it: kl-walk-0, kl-walk-1, ... one per Pokemon
SIDE_CID = "kl-side"        # confetti columns down both sides of the card on wide screens


def season_art(season: str):
    """The season's looping header animation (a GIF file), or None if it can't be drawn (e.g. Pillow is missing)."""
    try:
        import EmailArt
        return EmailArt.ensure_gif(season, SEASONS[season]["head"])
    except Exception:
        return None


def bounce_art(names: list[str]):
    """The strip of chosen Pokemon for the footer, or None if there are none or it can't be drawn."""
    if not names:
        return None
    try:
        import EmailArt
        return EmailArt.ensure_pokemon(names)
    except Exception:
        return None


def walker_art(names: list[str]) -> dict:
    """{content-id: GIF file} for each chosen strolling Pokemon that can be drawn (the others are quietly left out)."""
    out = {}
    try:
        import EmailArt
    except Exception:
        return out
    spots = (0.5, 0.2, 0.8)  # where each one stands along its strip, so they aren't all in the same place
    for name in names:
        try:
            out[f"{WALK_CID}{len(out)}"] = EmailArt.ensure_walker(name, spots[len(out) % len(spots)])
        except Exception:
            continue
    return out


def gather_assets(season: str, pokemon: list[str] | None = None, walkers: list[str] | None = None) -> dict:
    """{content-id: GIF file} for everything that moves. Empty (so the plain layout is used) if any can't be drawn.
    The Pokemon strips are optional: with none chosen the footer just shows the season's emoji, and the confetti strips
    between sections stay plain. `pokemon` dance at the bottom; `walkers` stroll along the strips between sections."""
    try:
        import EmailArt
        found = {ART_CID: season_art(season),
                 BAND_CID: EmailArt.ensure_confetti("band", "#ffffff"),
                 SIDE_CID: EmailArt.ensure_confetti("side", SEASONS[season]["page"])}
    except Exception:
        return {}
    if not all(v is not None for v in found.values()):
        return {}
    bounce = bounce_art(["pikachu"] if pokemon is None else pokemon)
    return {**found, **({BOUNCE_CID: bounce} if bounce else {}), **walker_art(walkers or [])}


def build_html(s: dict, cfg: dict, hidden: list[str] | None = None, season: str | None = None,
               art: bool = False, confetti: bool = False, bounce: bool = True,
               walkers: list[str] | None = None) -> tuple[str, str]:
    th = SEASONS.get((season or "").lower()) or SEASONS[season_of(date.fromisoformat(s["period"]))]
    NAVY, GOLD, PAGE, TILE = th["head"], th["accent"], th["page"], th["tile"]  # this email's seasonal colors
    hide = {h.lower() for h in (cfg.get("hidden", []) if hidden is None else hidden)}
    shown = s["items"][~s["items"]["item"].str.lower().isin(hide)]
    money = fd.money
    good = s["left"] >= 0
    tone, tone_bg = ("#16794a", "#e8f6ee") if good else ("#b3261e", "#fdecea")

    def rows(pairs: list[tuple[str, str, str]]) -> str:
        """Two-column rows: name (with a small note under it) on the left, amount on the right."""
        out = ""
        for n, (name, note, amt) in enumerate(pairs):
            top = "" if n == 0 else f"border-top:1px solid {LINE};"
            sub = f'<div style="font-size:12px;color:{MUTED};margin-top:2px">{esc(note)}</div>' if note else ""
            out += (f'<tr><td style="{top}padding:10px 0;font-size:15px;color:{INK}">{esc(name)}{sub}</td>'
                    f'<td align="right" valign="top" style="{top}padding:10px 0 10px 12px;font-size:15px;'
                    f'font-weight:600;color:{INK};white-space:nowrap">{esc(amt)}</td></tr>')
        return out

    def section(emoji: str, title: str, pairs: list[tuple[str, str, str]]) -> str:
        if not pairs:
            return ""
        return (f'<tr><td class="kl-pad" style="padding:22px 28px 0 28px">'
                f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
                f'color:{NAVY};padding-bottom:4px;border-bottom:2px solid {GOLD}">{emoji}&nbsp; {esc(title)}</div>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows(pairs)}</table>'
                f'</td></tr>')

    def change_tag(now: float, before) -> str:
        """A small light-red (bill went up) or light-green (went down) note: the $ and % change since last paycheck."""
        if before is None or pd.isna(before) or before <= 0:
            return ""
        d = now - float(before)
        if abs(d) < 0.005:
            return f'<div style="font-size:11px;font-weight:400;color:{MUTED};margin-top:2px">no change</div>'
        up = d > 0
        fg, bg = ("#b3261e", "#fdecea") if up else ("#16794a", "#e8f6ee")
        return (f'<div style="margin-top:3px"><span style="display:inline-block;font-size:11px;font-weight:600;color:{fg};'
                f'background:{bg};border-radius:8px;padding:1px 7px">{"&#9650;" if up else "&#9660;"} '
                f'{esc(money(abs(d)))} ({d / float(before):+.1%})</span></div>')

    def bill_grid(emoji: str, title: str, trips: list[tuple[str, str, str, str]]) -> str:
        """Bills as a three-column grid: name on the left, due date in the middle, amount on the right."""
        if not trips:
            return ""
        head = "font-size:11px;font-weight:700;letter-spacing:.08em;color:" + MUTED + ";padding:8px 0 4px 0"
        out = (f'<tr><td style="{head}">BILL</td><td align="center" style="{head};padding-left:8px;padding-right:8px">DUE</td>'
               f'<td align="right" style="{head}">AMOUNT</td></tr>')
        for n, (name, due, amt, change) in enumerate(trips):
            top = "" if n == 0 else f"border-top:1px solid {LINE};"
            out += (f'<tr><td style="{top}padding:10px 0;font-size:15px;color:{INK}">{esc(name)}</td>'
                    f'<td align="center" style="{top}padding:10px 8px;font-size:14px;color:{INK};white-space:nowrap">'
                    f'{esc(due)}</td>'
                    f'<td align="right" style="{top}padding:10px 0;font-size:15px;font-weight:600;color:{INK};'
                    f'white-space:nowrap">{esc(amt)}{change}</td></tr>')
        return (f'<tr><td class="kl-pad" style="padding:22px 28px 0 28px">'
                f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
                f'color:{NAVY};padding-bottom:4px;border-bottom:2px solid {GOLD}">{emoji}&nbsp; {esc(title)}</div>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{out}</table>'
                f'</td></tr>')

    def tile(label: str, value: str) -> str:
        return (f'<td width="50%" style="padding:0 5px"><table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0"><tr><td align="center" style="background:{TILE};border-radius:14px;'
                f'padding:14px 6px"><div style="font-size:11px;font-weight:700;letter-spacing:.08em;color:{MUTED}">'
                f'{esc(label)}</div><div style="font-size:20px;font-weight:700;color:{INK};margin-top:4px">'
                f'{esc(value)}</div></td></tr></table></td>')

    def face_off() -> str:
        """Two or more categories side by side for the paycheck that just ended: a bar each, scaled to the biggest."""
        f = s.get("face") or []
        if len(f) < 2:
            return ""
        # the same three-column grid as Bills: budget on the left, its limit in the middle, what was spent on the right
        head = "font-size:11px;font-weight:700;letter-spacing:.08em;color:" + MUTED + ";padding:8px 0 4px 0"
        out = (f'<tr><td style="{head}">BUDGET</td><td align="center" style="{head};padding-left:8px;padding-right:8px">'
               f'LIMIT</td><td align="right" style="{head}">SPENT</td></tr>')
        for n, x in enumerate(f):
            top = "" if n == 0 else f"border-top:1px solid {LINE};"
            note = f'{x["count"]} purchase{"s" if x["count"] != 1 else ""}'
            over = bool(x["limit"]) and x["last"] > x["limit"] + 0.005
            tag = change_tag(x["last"], x["before"]) if s.get("face_has_before") else ""
            out += (f'<tr><td style="{top}padding:10px 0;font-size:15px;color:{INK}">{esc(x["name"])}'
                    f'<div style="font-size:12px;color:{MUTED};margin-top:2px">{note}</div></td>'
                    f'<td align="center" style="{top}padding:10px 8px;font-size:14px;color:{INK};white-space:nowrap">'
                    f'{esc(money(x["limit"])) if x["limit"] else "&mdash;"}</td>'
                    f'<td align="right" style="{top}padding:10px 0;font-size:15px;font-weight:600;'
                    f'color:{"#b3261e" if over else INK};white-space:nowrap">{esc(money(x["last"]))}{tag}</td></tr>')
        names =" vs ".join(esc(x["name"]) for x in f) if len(f) == 2 else "Budgets"
        return (f'<tr><td class="kl-pad" style="padding:22px 28px 0 28px">'
                f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
                f'color:{NAVY};padding-bottom:4px;border-bottom:2px solid {GOLD}">&#127869;&nbsp; {names}</div>'
                f'<div style="font-size:12px;color:{MUTED};margin-top:6px">Last paycheck, {esc(s["face_label"])}</div>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{out}</table>'
                '</td></tr>')

    of_type = lambda t: shown[shown["type"] == t]
    # only scheduled items, meaning anything with a due date (budgets, extras and "every paycheck" items are left out)
    bills = [(r.item, _day(r.due), money(r.amount), "") for r in of_type("Scheduled").itertuples()
             if isinstance(r.due, date) and pd.notna(r.due_day)]
    income = [(r.source, "", money(r.amount)) for r in s["income_rows"].itertuples() if str(r.source).lower() not in hide]  # the leave-out list covers income lines too; the totals still count them
    debts = [(r.name, f"minimum {money(r.min_payment)}", money(r.current_balance)) for r in s["debts"].itertuples()]

    greet = random.choice(cfg["greetings"]) if cfg.get("greetings") else th["greet"]
    verdict = ("left after every bill and budget is covered" if good
               else "short after bills and budgets this paycheck")
    body = [
        # header: the moving seasonal strip when there is one (a plain emoji when there isn't), then the title
        (f'<tr><td style="background:{NAVY};border-radius:20px 20px 0 0;font-size:0;line-height:0">'
         f'<img src="cid:{ART_CID}" width="600" alt="" style="display:block;width:100%;max-width:600px;height:auto;'
         f'border:0;border-radius:20px 20px 0 0"></td></tr>'
         f'<tr><td align="center" style="background:{NAVY};border-bottom:4px solid {GOLD};padding:0 24px 14px 24px">'
         if art else
         f'<tr><td align="center" style="background:{NAVY};border-radius:20px 20px 0 0;border-bottom:4px solid {GOLD};'
         f'padding:26px 24px 22px 24px"><div style="font-size:34px;line-height:1">{th["emoji"]}</div>') +
        f'<div style="font-size:24px;font-weight:800;color:#ffffff;margin-top:8px">Personal Finance Ledger</div>'
        f'<div style="font-size:14px;color:#c9d3e6;margin-top:4px">{esc(s["label"])}</div></td></tr>',
        # greeting + the big number
        f'<tr><td class="kl-pad" align="center" style="padding:24px 28px 0 28px">'
        f'<div style="font-size:17px;color:{INK}">{esc(greet)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px">'
        f'<tr><td align="center" style="background:{tone_bg};border-radius:18px;padding:20px 12px">'
        f'<div class="kl-hero" style="font-size:40px;font-weight:800;color:{tone};line-height:1.1">'
        f'{esc(money(s["left"]))}</div>'
        f'<div style="font-size:14px;color:{tone};margin-top:6px">{esc(verdict)}</div></td></tr></table></td></tr>',
        # income / expenses tiles
        f'<tr><td class="kl-pad" style="padding:10px 23px 0 23px"><table role="presentation" width="100%" '
        f'cellpadding="0" cellspacing="0" border="0"><tr>{tile("INCOME", money(s["income"]))}'
        f'{tile("PLANNED OUT", money(s["expenses"]))}</tr></table></td></tr>',
        face_off(),
        section("&#128176;", "Income", income),
        bill_grid("&#129534;", "Bills", bills),
        section("&#127919;", "Debts", debts),
    ]
    if confetti:  # a confetti strip above every section after the tiles; every other one carries a strolling Pokemon
        def band(cid: str) -> str:
            return (f'<tr><td style="padding:14px 0 0 0;font-size:0;line-height:0"><img src="cid:{cid}" width="600" alt="" '
                    f'style="display:block;width:100%;max-width:600px;height:auto;border:0"></td></tr>')
        strips, n_band = [], -1
        for row in body[3:]:
            if not row:
                strips.append("")
                continue
            n_band += 1
            cid = walkers[(n_band // 2) % len(walkers)] if walkers and n_band % 2 == 0 else BAND_CID
            strips.append(band(cid) + row)
        body = body[:3] + strips
    foot = []
    for n in cfg.get("notes", []):
        foot.append(esc(n))
    if foot:
        body.append(f'<tr><td class="kl-pad" style="padding:22px 28px 0 28px">'
                    + "".join(f'<div style="font-size:14px;color:{INK};background:{TILE};border-radius:12px;'
                              f'padding:11px 14px;margin-bottom:8px">{x}</div>' for x in foot) + "</td></tr>")
    if cfg.get("love_note"):
        body.append(f'<tr><td class="kl-pad" align="center" style="padding:14px 28px 0 28px"><div style="font-size:16px;'
                    f'color:{INK};background:{th["note"]};border-radius:14px;padding:14px 16px">&#128155;&nbsp; '
                    f'{esc(cfg["love_note"])}</div></td></tr>')
    body.append(f'<tr><td align="center" style="padding:22px 28px 26px 28px;font-size:12px;color:{MUTED}">' +
                (f'<img src="cid:{BOUNCE_CID}" width="544" alt="" style="display:block;margin:0 auto 6px auto;width:100%;max-width:544px;height:auto;border:0">'
                 if art and bounce else f'<div style="font-size:18px;letter-spacing:6px;margin-bottom:8px">{th["trim"]}</div>') +
                f'{th["name"]} edition &middot; sent with care by Personal Finance Ledger &middot; numbers as of '
                f'{esc(_day(date.today()))}</td></tr>')

    # confetti columns beside the card: hidden unless the screen is wide (and unless the mail app understands that
    # rule), so a phone or a basic client only ever sees the card
    est = 900 + 46 * len(shown) + 40 * len(s["income_rows"])  # roughly how tall the email is, in pixels
    side_img = (f'<img src="cid:{SIDE_CID}" width="130" alt="" '
                f'style="display:block;width:130px;height:auto;border:0">')
    side = ('<td class="kl-side" valign="top" style="display:none;width:0;max-height:0;overflow:hidden;'
            'font-size:0;line-height:0;mso-hide:all">'
            + side_img * max(3, min(10, -(-est // 420))) + "</td>") if confetti else ""
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light"><title>Payday summary</title>'
        '<style>@media only screen and (min-width:900px){.kl-side{display:table-cell !important;width:130px !important;'
        'max-height:none !important;overflow:visible !important}}'
        '@media only screen and (max-width:480px){.kl-outer{padding:0 !important}'
        '.kl-pad{padding-left:18px !important;padding-right:18px !important}.kl-hero{font-size:34px !important}}'
        '</style></head>'
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        f'<div style="display:none;max-height:0;overflow:hidden">{esc(money(s["left"]))} {esc(verdict)}.</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAGE}">'
        f'<tr><td class="kl-outer" align="center" style="padding:20px 10px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:900px"><tr>'
        + side + f'<td valign="top" align="center">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:600px;background:#ffffff;border-radius:20px;font-family:{FONT}">'
        + "".join(body) + "</table></td>" + side + "</tr></table></td></tr></table></body></html>")
    text = (f"Personal Finance Ledger payday summary - {s['label']}\n{money(s['left'])} {verdict}.\n"
            f"Income {money(s['income'])}, planned out {money(s['expenses'])}.")
    return page, text


# ---------- sending ----------
def send(cfg: dict, to: list[str], subject: str, page: str, text: str, copies: bool = True,
         assets: dict | None = None) -> None:
    pw = app_password()
    if not pw:
        raise RuntimeError("No Gmail app password found. Set GMAIL_APP_PASSWORD in secrets.toml.")
    cc, bcc = (list(cfg.get("cc", [])), list(cfg.get("bcc", []))) if copies else ([], [])
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, formataddr(("Personal Finance Ledger", cfg["sender"])), ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    for cid_, file_ in (assets or {}).items():  # the animations ride along inside the message; nothing is hosted
        msg.get_payload()[-1].add_related(Path(file_).read_bytes(), maintype="image", subtype="gif",
                                          cid=f"<{cid_}>", filename=f"{cid_}.gif", disposition="inline")
    with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), int(cfg.get("smtp_port", 587)), timeout=30) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(cfg["sender"], pw)
        s.send_message(msg, to_addrs=list(to) + cc + bcc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--to", nargs="+")
    ap.add_argument("--period")
    ap.add_argument("--hide", nargs="*")
    ap.add_argument("--season", choices=list(SEASONS))
    a = ap.parse_args()
    try:
        cfg = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        cur = fd.current_period(period_starts())
        trial = a.test or a.preview  # only trials may pick their own recipients, paycheck and leave-out list
        if not (trial or a.force):
            if (date.today() - date.fromisoformat(cur)).days > int(cfg.get("catchup_days", 7)):
                runner_note("No payday in the last few days, so nothing to send.", True)
                return 0
            if already_sent(cur):
                runner_note(f"Already sent for the {cur} paycheck.", True)
                return 0
        period = (a.period if trial and a.period else cur)
        s = build_summary(period, cfg.get("compare"))
        season = (a.season if trial else None) or season_of(date.fromisoformat(period))
        assets = gather_assets(season, cfg.get("pokemon"), cfg.get("pokemon_walk"))  # all the moving pictures, or none
        page, text = build_html(s, cfg, a.hide if trial else None, season, art=bool(assets), confetti=bool(assets),
                                bounce=BOUNCE_CID in assets, walkers=sorted(c for c in assets if c.startswith(WALK_CID)))
        if a.preview:
            for cid_, file_ in assets.items():  # a browser can't follow the in-message id, so the preview carries them
                page = page.replace(f"cid:{cid_}", "data:image/gif;base64," + base64.b64encode(file_.read_bytes()).decode())
            PREVIEW_FILE.write_text(page, encoding="utf-8")
            print(f"Preview written to {PREVIEW_FILE}")
            return 0
        to = (a.to or [cfg.get("test_to") or cfg["sender"]]) if a.test else cfg["to"]
        subject = ("[TEST] " if a.test else "") + f"Payday summary: {s['label']}"
        send(cfg, to, subject, page, text, copies=not a.test, assets=assets)  # a test goes only to the test recipients
        log_send(period, to, "test" if a.test else "sent")
        runner_note(f"Sent the {period} {'test' if a.test else 'summary'} to {', '.join(to)}.", True)
        print(("Test sent to " if a.test else "Sent to ") + ", ".join(to))
        return 0
    except Exception as e:  # report it for the dashboard / Task Scheduler instead of dying silently
        runner_note(f"Failed: {e}", False)
        print("Failed:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
