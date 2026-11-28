# Personal Finance Ledger

A budgeting app that runs on your own Windows PC or Mac. Set it to budget **every two weeks** or **monthly**, add your income and
bills, import a CSV or Excel export from your bank, and see what's safe to spend and where your cash is headed.

**Private by design.** Everything stays on your computer. The app never connects to your bank, never signs in to anything,
and only answers requests from your own PC unless you turn on Phone access (off by default, see below). No data is stored in this repo.

## Get the desktop app

**[Download the app](https://github.com/Prisonmike1108/Personal-Finance-Ledger/releases/latest)** and pick your file under *Assets*:

- **Windows:** `Personal-Finance-Ledger-v…-Setup.exe`. Run it, click through, and open **Personal Finance Ledger** from the Start menu. It installs just for you (no administrator password).
- **Mac:** `…-mac-apple-silicon.zip` for any Mac from late 2020 on, or `…-mac-intel.zip` for older ones. Unzip it and drag the app into **Applications**.

The first time, Windows may say it protected your PC (choose **More info**, then **Run anyway**), and a Mac may say the app can't be checked (right-click the app, choose **Open**, then **Open**). That's because the app isn't signed by a paid publisher. Nothing is wrong with the file.

Closing the window sends the ledger to the tray (Windows) or menu bar (Mac); choose **Quit** from that icon to stop it. To update later, install the newer version over the old one.
Your numbers are kept in `%APPDATA%\Personal Finance Ledger\My Ledger Data` on Windows and `~/Library/Application Support/Personal Finance Ledger/My Ledger Data` on a Mac. Installing, updating and uninstalling never touch that folder, so copy it somewhere safe to back up. This edition has no payday email.

## What's in it

- **Overview:** safe to spend this paycheck, the bills due and paid, extras, income, and where the money is going.
- **Cash Forecast:** a paycheck-by-paycheck table of what's left and your rollover, with a What-if planner for putting some of your extra toward savings or debt.
- **Transactions:** import from your bank, sort into categories, and let rules file the rest.
- **Analysis:** what each scheduled bill really cost, the biggest movers, and cards and loans judged against their minimums.
- **Plan:** your income, bills, budgets, limits, one-time expenses and category rules.
- **Looks:** themes, light and dark, and animated backgrounds including weather scenes.
- **Phone access (optional):** use it from a phone on your home Wi-Fi, with a PIN. Off by default.

## If Windows blocks it (Smart App Control)

Windows 11 has a feature called **Smart App Control** that blocks programs it doesn't recognize. This app isn't signed by a
paid publisher, so it can be blocked, and the message usually says an app or file was blocked. Nothing is wrong with the file.

Try these in order:

1. **Unblock the download first.** Right-click the `Setup.exe` file, choose **Properties**, tick **Unblock** at the bottom (if you see it), click **OK**, then run it again. This fixes it most of the time.
2. **Turn Smart App Control off.** Open **Windows Security**, then **App & browser control**, then **Smart App Control
   settings**, and choose **Off**. On some versions of Windows you can't turn it back on afterward, so only do this if you're
   comfortable with that.

## First run

The first time you open it, a short setup walks you through four steps:

1. **How you budget:** every two weeks or monthly, and where to start.
2. **What you take home:** enter your pay the way you know it (every week, every two weeks, monthly or yearly) and the ledger works out the rest. Add anyone else's pay that goes into the same budget.
3. **Recurring bills:** tap common ones (rent, electric, phone) or add your own, with an amount, a due day and how often it repeats.
4. **Bank transactions (optional):** bring in a file from your bank, or skip it and do it later.

Everything can be changed afterward on the **Plan** tab. If you'd like to look around first, choose **Just looking? Load sample data** on the first step to see it with made-up numbers.

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

Your numbers are saved in one folder (see above for where). Back it up by copying that folder. Before every change the old version is saved to a `backups` folder inside it, and the **Undo** button at the top puts it back.

## Updating

Download the newer `Setup.exe` (or Mac zip) from the [latest release](https://github.com/Prisonmike1108/Personal-Finance-Ledger/releases/latest) and install it over the old one. Your numbers aren't touched.

## Good to know

- It only opens on this computer. Nobody else on your network can see it.
- Closing the window leaves it running in the tray (menu bar on a Mac). Choose **Quit** from that icon to shut it down.
- It's a budgeting tool, not financial advice.
- If something looks wrong, nothing is lost: use **Undo**, or restore a file from the `backups` folder.

Want to change how it works, or build it yourself? See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Phone access

The ledger normally answers only the PC it runs on. To use it from a phone on the same Wi-Fi:

1. On the PC, open the ledger, then **Settings** (the gear), then **Phone access**.
2. Pick a PIN (4 to 32 characters, six digits is a good choice) and click **Turn on**.
3. On your phone, open the address it shows (something like `http://192.168.1.23:8600`) and enter the PIN.

Good to know: the PC has to be on with the ledger running. The first time, Windows may ask about its firewall: allow it on private networks. It only works on your home network (devices on the internet are refused), the connection is plain HTTP, so use it at home, and only this PC can change the setting or the PIN. Turn it off in the same place. Changing the PIN signs every phone out. After five wrong PINs a device waits a minute.

## Run it from the source (advanced)

If you'd rather run the code than the installer: click **Code**, then **Download ZIP** on this page, right-click the `.zip` and **Unblock** it (if you see that option), unzip it somewhere permanent and double-click **`Install.bat`**. It sets up Python and a private environment for you and opens the ledger in your browser. Next time, double-click **`Open Ledger.pyw`**; **`Stop Ledger.bat`** shuts it down. Your numbers are then in the `finance_data/` folder. On a Mac or Linux, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#any-os-by-hand).
