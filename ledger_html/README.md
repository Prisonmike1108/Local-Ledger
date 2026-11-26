# Personal Finance Ledger: the web page and server

A Python script that serves its own web page and reuses the numbers logic that lives in `../FinanceDashboard.py`,
so the page and the payday email always agree. It reads and writes the files in `../finance_data`.

## Running it
- **Normal use:** double-click `../Open Ledger.pyw`. It starts the server quietly and opens `http://127.0.0.1:8600`.
  A Windows scheduled task ("at log on") can also start it by itself with `--watch`.
- **By hand:** `python ledger_html/server.py --open` (add `--watch` to restart on code changes).
- **Page files** (`static/*`): refresh the browser. **Python** (`server.py`, `FinanceDashboard.py`): `--watch` restarts the
  server by itself within a couple of seconds, and refuses to restart into a file with a syntax error.
- **A second copy for testing:** `LEDGER_PORT=8610` and `FINANCE_DATA_DIR=<a scratch copy of the data>`. Never test
  edits against the real folder.

## How it fits together
- `server.py`: standard-library HTTP server + pandas. Builds one context per request (`Ctx`), serves JSON
  (`/api/...`) and the static page. Every file change goes through `save()` which first copies the old file to
  `finance_data/backups/` (newest 40 per file); the Undo button restores the last change (all files in one click).
- **Budgets vs limits:** a budget (`budgets.csv`) sets money aside, so it is held back from Safe to spend. A spending limit
  (`limits.csv`, Plan tab > Spending limits) is only a yardstick for a category like Gas: the Overview table shows it as type
  "Limit" with under/close/over (80% and 100% like budgets), and it changes no totals. The spending still counts as an Extra.
  A limit named like an existing bill or budget is ignored (the bill or budget wins).
- Sorting: click any table heading (`static/sort.js`; asc, desc, back to normal). Read-only tables keep their sort when the page
  redraws; editable ones (class `ed`) sort as a view and reset on any redraw so the Order arrows stay honest. Transactions
  sorts all rows in `app.js` (the table only draws the newest 600).
- `static/`: `index.html`, `style.css`, `app.js` (Overview, Transactions), `plan.js`, `forecast.js`, `email.js`,
  `settings.js` (icon rail and slide-out panel).
- **Pay periods** are either `biweekly` (14 days) or `monthly` (from a start day to the day before the next). The layout is saved in
  the data folder's `settings.json` as `period_layout`, a list of `{"from", "mode", "day"}`, each entry applying from its date on, so
  a switch only affects periods after it. No layout means biweekly, which is how the ledger always worked. All the maths asks
  `fd.period_end(start)`, `fd.next_start(start)` and `fd.period_days(start)` instead of assuming 14 days. First run asks which
  one (`/api/setup/period`); the Plan tab's "How you budget" card switches later (`/api/period/switch`, one Undo reverses it).
  Ledgers set up on this version keep three periods ahead by themselves (`auto_periods`); older ones add periods when they choose.
  In monthly mode `app.js` rewords "paycheck" and "pay period" as "month" (`monthWords`).
- **Bank imports** (`fd.read_table`, `fd.guess_import`, `fd.parse_bank`): a bank CSV may have a summary block above the header, a
  trailing comma on every row, a byte-order mark, or no header at all (`read_csv_text`). Columns are guessed from their headings,
  then from their contents. The amount is a Debit column plus a Credit column, one amount column where the bank prints money spent
  as positive or negative (detected from which sign is in the majority, shown to the person to confirm), or an amount column
  plus a Debit/Credit type column that decides per row. Inside the ledger spending is always negative. The one-click import
  dialog only imports unasked when `guess.confident` (every column found by its heading, sign clear) and it isn't the first import;
  otherwise it opens the mapping screen (`showMapping` in `settings.js`) for a check.
- **Email is optional:** `/api/meta` reports `email_enabled` from whether `FinanceEmail.py` exists. The friend download leaves
  the email code out, so the Email tab hides itself.
- Calculations (bill status, rollover, savings flow, categorize, payoff simulation, themes, animation CSS) are imported
  from `FinanceDashboard.py`, which is a plain logic module with no screen of its own.
- Settings (theme, dark mode, animations, savings, threshold, email) are shared with `FinanceEmail.py`.
  Look settings always live in the real `settings.json`, even on sample data.

## Safety rules (server.py)
- **This PC only.** The server binds to `127.0.0.1` and `_guard` refuses any client that isn't this PC. There are no sign-ins,
  people or roles, and nothing is opened to the home network. Never port-forward it.
- Requests must have a normal Host (`localhost`, `127.0.0.1` or `::1`, so no DNS rebinding) and changes must carry
  `X-Ledger: 1` with a matching Origin.
- Requests take turns (`LOCK`).
- **First run:** with no pay periods yet, `/api/meta` says `needs_setup` and the page shows a welcome card (first payday, or
  made-up sample data). `/api/setup/*` refuse once any pay period exists, so they can never overwrite data.
- The payday email never sends from tests: Preview is safe; Send test and Send now go to real inboxes (Send now asks first
  and is disabled on sample data).

## Tests that were run (on scratch data, never the real folder)
Every read endpoint for every pay period; delete, add, move, edit, undo; plan saves with effective dates; new categories
(bill, budget, extra); move to savings and take back; import and dedupe; email save/undo and send guards;
cross-site and spoofed-Host requests; requests from another device.

## Still to do
- Animations second pass: shimmer ring and glare on cards, rainbow banner title, Terminal style.
- TV mode is simple. Undo history is per server run (backups stay on disk).
- Tidy the old `poc/` and `mockup/` folders (untracked scratch work).

## Working notes
- Commit and push only when asked. Git on this PC has no global author, so commits use the project's local config.
- Run Python tests with `python -X utf8 -I` (isolated mode ignores `PYTHONIOENCODING`).
- Don't print or log secrets (email settings, password hashes, API keys) in tool output.
