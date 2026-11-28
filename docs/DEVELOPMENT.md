# Personal Finance Ledger: for developers

Notes for running Personal Finance Ledger from source and changing it. Everyday use is covered in the [main README](../README.md).

## Any OS, by hand

```bash
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python ledger_html/server.py --open
```

It serves on http://127.0.0.1:8600 (change it with the `LEDGER_PORT` environment variable). `--watch` restarts the server when
the Python code changes; the pages in `ledger_html/static/` only need a browser refresh.

## What's in here

| Path | Purpose |
| --- | --- |
| `ledger_html/` | The app: `server.py` (a small standard-library web server) and `static/` (the pages). See its own README. |
| `FinanceDashboard.py` | The shared logic (periods, bill status, rollover, savings, categorising, payoff, imports, themes). No screen. |
| `FinanceEmail.py` | Builds and sends an optional payday email, using the same numbers as the app |
| `EmailArt.py` | Draws the seasonal art in the email |
| `Open Ledger.pyw`, `Stop Ledger.bat`, `Install.bat` | Start, stop and set up on Windows |
| `release/`, `tools/build_release.py`, `.github/workflows/release.yml` | Builds the no-code Windows download |
| `email_assets/`, `themes.json` | Email images and colour themes |

## Data

Data lives in `finance_data/*.csv` next to the scripts (override with the `FINANCE_DATA_DIR` environment variable). That folder,
plus `Transactions/` and `secrets.toml`, is listed in `.gitignore` so personal data and credentials never get pushed.

## Only on this PC

The app listens on `127.0.0.1` only and refuses any request that doesn't come from the PC itself. There are no sign-ins, and
nothing is exposed to the local network.

## Building the Windows download

A GitHub Action builds a Windows zip with its own copy of Python inside and attaches it to a Release.

1. Push a version tag: `git tag v1.0.0` then `git push origin v1.0.0`. (Or run the **Build the Windows download** workflow by hand
   from the Actions tab to get the zip as a build artifact without a Release.)
2. When the build finishes, the zip is on the repo's **Releases** page.
3. The zip holds only the app and a plain-English **START HERE.txt**: no email feature (it hides itself when the email code is
   missing), no data, no secrets. Data lives in a **My Ledger Data** folder beside the app, so updating never touches it.

To build it on your own PC instead (needs internet; downloads Python and the packages):
`python tools/build_release.py --version 1.0.0` writes `dist/Personal-Finance-Ledger-v1.0.0-windows.zip`. Add `--stage-only` to assemble
and test the folder without downloading anything.

## Payday email (optional, source install only)

```bash
python FinanceEmail.py              # send if a payday fell in the last few days and it wasn't sent yet
python FinanceEmail.py --preview    # write email_preview.html, sends nothing
python FinanceEmail.py --test       # send the current period to the test address
python FinanceEmail.py --force      # send the current period now, even if already sent
```

Settings are in `finance_data/email_settings.json` (or the app's Email tab). The Gmail app password is read from the
`GMAIL_APP_PASSWORD` environment variable or from `secrets.toml` next to `FinanceEmail.py` (copy `secrets.toml.example`; it is
git-ignored, so it never goes to GitHub):

```toml
GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"
```

## Working on it

- Run a second copy for testing with `LEDGER_PORT=8610` and `FINANCE_DATA_DIR=<a scratch folder>`. Never test edits against a
  real data folder. `fd.seed_test_data` fills a scratch folder with made-up numbers.
- Check JavaScript with `node --check <file>`.
- Run the what-if math test with `node tests/test_forecast.js` (it needs only Node).

## Optional local settings

These keys in `finance_data/settings.json` are all optional. Leaving them out keeps the default look, and the file is not
part of the repository, so they are a way to personalise one copy.

| Key | Default | What it does |
|-----|---------|--------------|
| `app_name` | "Personal Finance Ledger" | The name shown in the page header and the browser tab |
| `hide_budget_mode` | `false` | Hides the "How you budget" card on the Plan tab |
| `dev_reload` | `false` | While working on the page files, the open tab reloads itself when one changes |

## The desktop app

`desktop_app.py` runs the same ledger in a native window with a tray icon (`python desktop_app.py`, or `--no-window` for the server alone). It needs `requirements-desktop.txt`.

```
python tools/make_icon.py                         # redraws assets/icon.* (only if you change the icon)
python tools/build_desktop.py --version dev --smoke-only   # build the app folder and test it
python tools/build_desktop.py --version 1.2       # Windows: Setup.exe (needs Inno Setup 6, else a zip); Mac: a zip with the .app
```

Each build must run on the kind of computer it targets, so the GitHub Action (`.github/workflows/release.yml`) builds Windows, Mac (Apple silicon) and Mac (Intel) when you push a tag like `v1.2`, then attaches the files to a Release. Run it by hand from the Actions tab to try a build without a tag.
