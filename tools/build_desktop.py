"""Builds the desktop app: one build per computer type, run on that type of computer (the GitHub Action does both).

    python tools/build_desktop.py --version 1.2          # Windows: installer (or a zip when Inno Setup isn't installed); Mac: a zip with the .app
    python tools/build_desktop.py --version dev --smoke-only   # build the app folder and test it, make no installer

What it does:
  1. PyInstaller turns desktop_app.py + the ledger into an app folder with its own Python (no Python needed to run it).
  2. A smoke test starts the built app on a spare port with an empty data folder and checks it answers like a new install.
  3. Windows: Inno Setup wraps the folder in Personal-Finance-Ledger-v<version>-Setup.exe. Mac: the .app is zipped with ditto.
This edition has no payday email (FinanceEmail.py and EmailArt.py are not included), and no third-party artwork.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "Personal Finance Ledger"
WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
SEP = ";" if WIN else ":"


def say(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def run(cmd: list, **kw) -> None:
    say("$ " + " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def pyinstaller(out: Path) -> Path:
    work = out / "_pyi"
    shutil.rmtree(work, ignore_errors=True)
    icon = ROOT / "assets" / ("icon.ico" if WIN else "icon.icns")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
           "--distpath", out / "app", "--workpath", work, "--specpath", work, "--icon", icon,
           "--add-data", f"{ROOT / 'ledger_html' / 'static'}{SEP}ledger_html/static",
           "--add-data", f"{ROOT / 'themes.json'}{SEP}.",
           "--add-data", f"{ROOT / 'VERSION'}{SEP}.",
           "--add-data", f"{ROOT / 'assets' / 'icon.png'}{SEP}.",
           "--hidden-import", "openpyxl", "--hidden-import", "pystray._win32" if WIN else "pystray._darwin" if MAC else "pystray._xorg",
           "--paths", ROOT,
           "--exclude-module", "tkinter", "--exclude-module", "matplotlib", "--exclude-module", "scipy",
           "--exclude-module", "IPython", "--exclude-module", "pytest", "--exclude-module", "FinanceEmail", "--exclude-module", "EmailArt",
           ROOT / "desktop_app.py"]
    run(cmd)
    shutil.rmtree(work, ignore_errors=True)
    return out / "app" / (f"{NAME}.app" if MAC else NAME)


def app_binary(app: Path) -> Path:
    return app / "Contents" / "MacOS" / NAME if MAC else app / f"{NAME}.exe"


def smoke_test(app: Path, out: Path) -> None:
    """Start the built app with no window on a spare port and an empty data folder, and make sure it behaves like a new install."""
    data = out / "_smoke_data"
    shutil.rmtree(data, ignore_errors=True)
    port = 8793
    env = {**os.environ, "FINANCE_DATA_DIR": str(data), "LEDGER_PORT": str(port)}
    proc = subprocess.Popen([str(app_binary(app)), "--no-window"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        def get(path, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(),
                                         headers={"X-Ledger": "1"}, method="GET" if body is None else "POST")
            return urllib.request.urlopen(req, timeout=15).read()
        meta = None
        deadline = time.time() + 120  # never wait longer than this, whatever the app does
        while time.time() < deadline:
            try:
                meta = json.loads(get("/api/meta"))
                break
            except Exception:
                time.sleep(0.5)
        assert meta is not None, "the built app didn't start:\n" + (proc.stdout.read(4000).decode(errors="replace") if proc.poll() is not None else "(still running, but not answering)")
        assert meta["needs_setup"] is True, "a new install should ask for setup"
        assert meta["email_enabled"] is False, "this edition has no email"
        page = get("/").decode("utf-8", "replace")
        assert "<script" in page and "app.js" in page, "the page didn't load"
        assert get("/weather/rain.svg").startswith(b"<svg") or b"<svg" in get("/weather/rain.svg")[:400], "the weather backgrounds are missing"
        month = time.strftime("%Y-%m")
        assert json.loads(get("/api/setup/period", {"mode": "monthly", "month": month, "day": 1})).get("ok"), "setup failed"
        meta = json.loads(get("/api/meta"))
        ov = json.loads(get("/api/overview?period=" + meta["current"]))
        assert ov["days"] in (28, 29, 30, 31)
        say("smoke test passed: starts clean, serves the pages, asks for setup, monthly ledger works, no email")
    finally:
        proc.kill()
        shutil.rmtree(data, ignore_errors=True)


def inno(app: Path, out: Path, version: str) -> Path | None:
    iscc = shutil.which("iscc") or next((str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                                                          Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe") if p.exists()), None)
    if not iscc:
        return None
    run([iscc, f"/DAppVersion={version}", f"/DSourceDir={app}", f"/DOutDir={out}", f"/DIconFile={ROOT / 'assets' / 'icon.ico'}",
         ROOT / "tools" / "installer.iss"])
    return out / f"Personal-Finance-Ledger-v{version}-Setup.exe"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--smoke-only", action="store_true", help="build the app folder and test it; make no installer or zip")
    a = ap.parse_args()
    version = a.version.lstrip("v")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", version):
        sys.exit("version can only hold letters, numbers, dots, dashes and underscores")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "app", ignore_errors=True)
    app = pyinstaller(out)
    say(f"built {app}")
    smoke_test(app, out)
    if a.smoke_only:
        return
    if WIN:
        exe = inno(app, out, version)
        if exe:
            say(f"done: {exe} ({exe.stat().st_size / 1e6:.0f} MB)")
            return
        say("Inno Setup isn't installed, so making a zip of the app folder instead")
        z = shutil.make_archive(str(out / f"Personal-Finance-Ledger-v{version}-windows-portable"), "zip", out / "app", NAME)
        say(f"done: {z}")
    elif MAC:
        z = out / f"Personal-Finance-Ledger-v{version}-mac.zip"
        z.unlink(missing_ok=True)
        run(["ditto", "-c", "-k", "--keepParent", app, z])  # ditto keeps the app's signature and links intact; plain zip can break them
        say(f"done: {z} ({z.stat().st_size / 1e6:.0f} MB)")
    else:
        sys.exit("Windows and Mac only")


if __name__ == "__main__":
    main()
