# Personal Finance Ledger

A budgeting app that runs on your own Windows PC. Set it to budget **every two weeks** or **monthly**, add your income and
bills, import a CSV or Excel export from your bank, and see what's safe to spend and where your cash is headed.

**Private by design.** Everything stays on your computer. The app never connects to your bank, never signs in to anything,
and only answers requests from your own PC unless you turn on Phone access (off by default, see below). No data is stored in this repo.

## Latest update: <!--VER-->Nov 25, 2026<!--/VER-->

**What's new**

- **Redesigned tabs.** Cash Forecast now leads with the paycheck table (with bars behind each paycheck's extra and rollover) and keeps the What-if planner in a side panel. The threshold slider is gone. Overview puts your safe-to-spend numbers in a side panel next to the bill tables. Plan has a section list on the left that follows you down the page. Transactions and Analysis get the same flatter cards and larger type.
- **New Analysis tab.** Pick a scheduled bill (or all of them) and see what it really cost each pay period in one large chart, with the plan and trend lines. The top shows the biggest movers (bills costing more or less than usual, and missed payments), a date range filter narrows everything to the pay periods you choose, and the bill list can be searched, filtered (costing more, costing less, no change) and sorted. Credit cards and loans can be marked once and are judged against their minimum instead of showing up as swings. The chart shows calendar months (partial months striped), and the chart, summary tiles and movers all follow the bill list filter, so picking Internet or Regular bills shows that group's monthly total.
- **Pick the time the payday email goes out.** The Email tab's Schedule section has a Send time picker. Saving it updates the Windows scheduled task that sends the email, and it shows when the next one goes out.
- **Fixes from a code audit.** Hand-added transactions now reduce Safe to spend, pending holds and refunds that match a spend are no longer counted twice, and phone access is tougher to guess into: PINs need 6 or more characters, wrong tries are limited even when sent all at once, and there is a Sign out all phones button.
- **New background: Prismatic parallax drift.** Pick it in Settings, Appearance, Background. Colors and layering by [Codioful](https://codioful.com/visual/prismatic-parallax-drift) (free to use with credit); the slow drift is added here.
- **New backgrounds: Weather.** Settings, Appearance, Background now has a Weather group: Sunny, Cloudy, Rain, Storm, Snow and Fog, each an animated street scene behind the page.
- **Renamed to Personal Finance Ledger.** The first time you open it you're asked what to call yours. Change it any time in Settings.
- **Income this paycheck.** A new Overview table compares each planned paycheck (from the Plan tab) with what landed, plus extra income, with up and down arrows.
- **One time future expense.** Plan something you'll pay once (a tattoo, a deposit) in the pay period it falls in. When the real charge is imported, the Transactions tab offers to file it and removes the planned entry.
- **Pending filter and badge.** Pending bank holds are flagged in Transactions and can be filtered.
- **Rename extra categories** right in the table on the Plan tab.

- **Phone access (optional).** Turn it on in Settings, pick a PIN, and open the ledger from a phone on your home Wi-Fi. It's off by default, only accepts devices on your home network, and every phone has to enter the PIN.
- **Pending holds are flagged.** Transactions the bank hasn't posted yet show an amber Pending badge, so you can see which ones are holds that already count against Safe to spend.
- **Remember this?** When you file a bank transaction under a category, the ledger offers to remember that merchant, so the next ones file themselves.
- **Older paychecks show up.** Transactions from before your start date now get their own earlier pay periods after you import.
- **Cash Forecast:** it stops at one paycheck's income, and Savings and Debt have dollar boxes that match the sliders.
- **Plan tab:** the expense column says "Expense name", and bills and budgets now say plainly that they're held back from your totals.
- **One-click updates:** download the update zip, double-click `Update.bat`, and it finds your ledger and updates it. Your numbers are never touched.
- **Easier install:** a progress page shows each step while it installs, with no black window.

**Already have the ledger? Update it in three steps.**

1. **[Download the latest update zip](https://github.com/Prisonmike1108/Personal-Finance-Ledger/tree/main/updates)**: click the zip, then the download button.
2. Right-click the zip, choose **Properties**, tick **Unblock** if you see it, click **OK**, then right-click it again and choose **Extract all**.
3. In the extracted folder, double-click **`Update.bat`**. It finds your Personal Finance Ledger on your computer, updates it and reopens it.

Your numbers stay in the `finance_data/` folder, which an update never touches. The top of the ledger shows the date of the version
you have. After this, there's an even easier way: double-click `Update.bat` inside your own Personal Finance Ledger folder. It downloads the newest version straight from GitHub (no account or sign-in needed), updates your ledger and reopens it.

---

## First time? Install it

This download already includes the latest update above, so a new install needs nothing else.

1. On this page click the green **Code** button, then **Download ZIP**.
2. **Before you unzip**, right-click the `.zip` file itself, choose **Properties**, tick **Unblock** at the bottom (if you see it),
   click **OK**, and then unzip it somewhere permanent, like your Documents folder. This stops Windows from blocking the files. See
   [If Windows blocks it](#if-windows-blocks-it-smart-app-control) below.
3. Double-click **`Install.bat`**. There's no black window. A **progress page** opens in your browser with a progress bar and
   the current step, and the installer works in the background. If you don't have Python 3.11 or newer, it installs Python
   for you (click **Yes** if Windows asks for permission), then sets up a private environment, installs what it needs and
   opens the app in a new tab. It takes a few minutes the first time. If the progress page says "One more step", just
   double-click `Install.bat` again. If something fails, the page says so and opens `install.log` with the details.
4. Next time, double-click **`Open Ledger.pyw`**. To shut it down, double-click **`Stop Ledger.bat`**.

(Mac or Linux: see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#any-os-by-hand).)

### If Windows blocks it (Smart App Control)

Windows 11 has a feature called **Smart App Control** that blocks programs it doesn't recognize. This app isn't signed by a
paid publisher, so it can be blocked, and the message usually says an app or file was blocked. Nothing is wrong with the file.

Try these in order:

1. **Unblock the zip first.** Right-click the `.zip` file, choose **Properties**, tick **Unblock**, click **OK**, then unzip it
   again. Run everything from the unzipped folder, not from inside the zip window. This fixes it most of the time.
2. **Run `Help - Windows Blocked It.bat`.** It clears the "downloaded from the internet" mark from every file in the folder
   and tells you whether Smart App Control is on. (If Windows blocks this helper too, go back to step 1.)
3. **Turn Smart App Control off.** Open **Windows Security**, then **App & browser control**, then **Smart App Control
   settings**, and choose **Off**. On some versions of Windows you can't turn it back on afterward, so only do this if you're
   comfortable with that.

## First run

1. The first time, it asks how you budget: **every two weeks** or **monthly**. You can change this later on the **Plan** tab.
   If you'd like to look around first, choose **Load sample data** to see it with made-up numbers.
2. On the **Plan** tab, add your income, your regular bills and your budgets.
3. Bring in your bank transactions (below).

## Bringing in your transactions

The app doesn't connect to your bank, so you bring the transactions in yourself:

1. Log in to your bank's website and download your transactions as a **CSV** (or **.xlsx**) file. A range like the last 90 days works well.
2. In the app, click the **Import** button (the down arrow on the left edge) and choose your file. It works out which column is
   the date, the amount and the description by itself, even when your bank names them oddly or splits money in and money out.
   The first time it shows what it found. Check it, and check the line **money spent shows as**: some banks print spending as
   positive numbers and others as negative. Then click **Import file**.
3. Repeat whenever you want things up to date; once a week is plenty. Importing the same dates twice is safe, because repeats
   are skipped.

New transactions are sorted into categories using rules (**Plan** tab, then **Rules**). You sort a few by hand at first, and
after that most are filed automatically.

## Your data

Your numbers are saved in the `finance_data/` folder inside the app folder. Back it up by
copying that folder. Before every change the old version is saved to a `backups` folder inside it, and the **Undo** button at the
top puts it back.

## Updating

See **Latest update** at the top. In short: double-click `Update.bat`.

(Maintainers: `python tools/build_update.py --date YYYY-MM-DD` builds the zip into `updates/`, replacing the older one, and stamps the date into `VERSION`.)

## Good to know

- It only opens on this computer. Nobody else on your network can see it.
- Closing the browser tab leaves it running quietly in the background. Use **Stop Personal Finance Ledger** (or **Stop Ledger.bat**) to shut it down.
- It's a budgeting tool, not financial advice.
- If something looks wrong, nothing is lost: use **Undo**, or restore a file from the `backups` folder.

Want to change how it works, or build it yourself? See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Phone access

The ledger normally answers only the PC it runs on. To use it from a phone on the same Wi-Fi:

1. On the PC, open the ledger, then **Settings** (the gear), then **Phone access**.
2. Pick a PIN (4 to 32 characters, six digits is a good choice) and click **Turn on**.
3. On your phone, open the address it shows (something like `http://192.168.1.23:8600`) and enter the PIN.

Good to know: the PC has to be on with the ledger running. The first time, Windows may ask about its firewall: allow it on private networks. It only works on your home network (devices on the internet are refused), the connection is plain HTTP, so use it at home, and only this PC can change the setting or the PIN. Turn it off in the same place. Changing the PIN signs every phone out. After five wrong PINs a device waits a minute.
