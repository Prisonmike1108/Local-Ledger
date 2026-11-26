"""Builds the dated update zip that people who already have Personal Finance Ledger download and unzip over their folder.

    python tools/build_update.py                 # uses the date in the VERSION file
    python tools/build_update.py --date 2026-12-05   # also writes that date into VERSION first

The zip holds only the app's code, never anyone's numbers: no finance_data, no .venv, no secrets.toml. Unzipping it into an
existing Personal Finance Ledger folder replaces the code and leaves everything personal where it was. Windows .bat files are written
with Windows line endings so they run no matter how the repo was checked out. Output: updates/Personal-Finance-Ledger-update-<date>.zip in the repo, which is where people download it. Older update zips in that
folder are removed, so there is always exactly one: the newest.
"""
import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# in the repo but not part of an update: tests, build tools, GitHub's own files, and the separate packaged-app launchers
SKIP_DIRS = {"tests", "tools", ".github", "release", "dist", "updates", "finance_data", "__pycache__", ".venv"}
SKIP_FILES = {".gitignore", ".gitattributes", "secrets.toml", "install.log"}

READ_ME = """LOCAL LEDGER UPDATE - as of {nice}
================================

This update replaces the ledger's program files. Your numbers are NOT in it and are not touched.

How to install it (about a minute)
----------------------------------
1. Right-click this .zip file, choose Properties, tick "Unblock" at the bottom if you see it, and click OK.
2. Right-click the zip again and choose "Extract all".
3. In the extracted folder, double-click "Update.bat". It finds your Personal Finance Ledger on this computer, updates it
   (your numbers are not touched) and opens it. If it finds more than one copy it asks which one.

Next time you can double-click "Update.bat" inside your own Personal Finance Ledger folder to get the newest version from GitHub.

How to tell it worked: the top of the ledger says "Updated {nice}".

Your data lives in the finance_data folder inside your Personal Finance Ledger folder. Leave that folder alone.
"""


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def wanted(name: str) -> bool:
    parts = Path(name).parts
    return not (set(parts[:-1]) & SKIP_DIRS) and parts[-1] not in SKIP_FILES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD; written into VERSION. Default: whatever VERSION says")
    a = ap.parse_args()
    if a.date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
            sys.exit("--date must look like 2026-12-05")
        (ROOT / "VERSION").write_text(a.date + "\n", encoding="utf-8")
    date = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        sys.exit("VERSION must hold a date like 2026-11-20")
    import datetime
    nice = datetime.date.fromisoformat(date).strftime("%b %d, %Y").replace(" 0", " ")
    rd = ROOT / "README.md"  # keep the "Latest update" date at the top of the README in step with VERSION
    txt = rd.read_text(encoding="utf-8")
    new = re.sub(r"(<!--VER-->).*?(<!--/VER-->)", lambda m: m.group(1) + nice + m.group(2), txt)
    if new != txt:
        rd.write_text(new, encoding="utf-8")
    files = [f for f in tracked() if wanted(f)]
    out = ROOT / "updates"
    out.mkdir(exist_ok=True)
    zpath = out / f"Personal-Finance-Ledger-update-{date}.zip"
    for old in [*out.glob("Personal-Finance-Ledger-update-*.zip"), *out.glob("Local-Ledger-update-*.zip")]:  # only the newest stays (the old name too)
        old.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            data = (ROOT / f).read_bytes()
            if f.lower().endswith(".bat"):  # Windows line endings, whatever the checkout used
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(f, data)
        z.writestr("UPDATE - READ ME.txt", READ_ME.format(nice=nice).replace("\n", "\r\n"))
    print(f"{zpath}  ({len(files) + 1} files, {zpath.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
