"""Builds the download for people who don't want to touch code: a Windows zip with everything inside, including its own
copy of Python. Unzip, double-click "Start Personal Finance Ledger", done. This edition has no payday email.

    python tools/build_release.py --version 1.0.0            # full build (needs internet, Windows)
    python tools/build_release.py --version dev --stage-only  # just assemble and test the folder, using the Python you have

The GitHub Action in .github/workflows/release.yml runs this when a tag like v1.0.0 is pushed and attaches the zip to a
Release, so the build happens on GitHub's machines instead of yours.

What goes in the zip (nothing else):
    Personal Finance Ledger/
        Start Personal Finance Ledger.bat    Stop Personal Finance Ledger.bat    START HERE.txt
        app/                       the ledger itself (no email code, no personal files)
        python/                    Python plus pandas, numpy and openpyxl (full build only)
        My Ledger Data/            made on first run: the person's own numbers, never overwritten by an update
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = "3.13.1"  # keep in step with the Python the ledger is developed on
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GETPIP_URL = "https://bootstrap.pypa.io/get-pip.py"
# Optional: paste the SHA-256 the build prints, so a later build refuses a download that changed.
EMBED_SHA256 = ""
GETPIP_SHA256 = ""

APP_FILES = ["FinanceDashboard.py", "themes.json", "Open Ledger.pyw"]  # plus ledger_html/server.py and ledger_html/static/
PORT = 8600


def say(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def fetch(url: str, dest: Path, want: str) -> None:
    say(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    say(f"  {dest.name}: {dest.stat().st_size / 1e6:.1f} MB, sha256 {got}")
    if want and got != want:
        sys.exit(f"{dest.name} doesn't match the pinned checksum.\n  expected {want}\n  got      {got}")


def stage_app(app: Path) -> None:
    app.mkdir(parents=True)
    for name in APP_FILES:
        shutil.copy2(ROOT / name, app / name)
    (app / "ledger_html").mkdir()
    shutil.copy2(ROOT / "ledger_html" / "server.py", app / "ledger_html" / "server.py")
    shutil.copytree(ROOT / "ledger_html" / "static", app / "ledger_html" / "static", ignore=shutil.ignore_patterns("__pycache__"))
    # keep the app honest about what this edition is: no email code is shipped, so the Email tab hides itself
    assert not (app / "FinanceEmail.py").exists() and not (app / "EmailArt.py").exists()


def embed_python(py: Path, work: Path) -> Path:
    zpath = work / "python-embed.zip"
    fetch(EMBED_URL, zpath, EMBED_SHA256)
    py.mkdir(parents=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(py)
    pth = next(py.glob("python*._pth"))
    stem = pth.stem.removesuffix("._pth") if pth.stem.endswith("._pth") else pth.stem
    # let it find the packages we install, and run the normal site setup (the embeddable build skips both by default)
    pth.write_text(f"{stem}.zip\n.\nLib\\site-packages\nimport site\n", encoding="ascii")
    gp = work / "get-pip.py"
    fetch(GETPIP_URL, gp, GETPIP_SHA256)
    exe = py / "python.exe"
    run([exe, gp, "--no-warn-script-location", "--disable-pip-version-check"])
    run([exe, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check", "--only-binary=:all:",
         "-r", ROOT / "release" / "requirements-friend.txt"])
    # trim what the ledger never uses, to keep the download smaller
    site = py / "Lib" / "site-packages"
    for junk in ("pip", "setuptools", "pkg_resources", "wheel", "_distutils_hack"):
        shutil.rmtree(site / junk, ignore_errors=True)
    for d in site.glob("pip-*"):
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(site / "pandas" / "tests", ignore_errors=True)
    for d in site.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    return exe


def run(cmd: list) -> None:
    say("$ " + " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def smoke_test(python: Path, app: Path) -> None:
    """Start the packaged ledger on a spare port with an empty data folder and make sure it answers like a new install."""
    data = app.parent / "_smoke_data"
    shutil.rmtree(data, ignore_errors=True)
    port = 8791
    env = {**os.environ, "FINANCE_DATA_DIR": str(data), "LEDGER_PORT": str(port)}
    proc = subprocess.Popen([str(python), str(app / "ledger_html" / "server.py")], env=env, cwd=str(app),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        def get(path, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(),
                                         headers={"X-Ledger": "1"}, method="GET" if body is None else "POST")
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        meta = None
        for _ in range(60):
            try:
                meta = get("/api/meta")
                break
            except Exception:
                time.sleep(0.5)
        assert meta is not None, "the packaged ledger didn't start:\n" + (proc.stdout.read(4000).decode(errors="replace") if proc.poll() is not None else "")
        assert meta["needs_setup"] is True, "a new install should ask for setup"
        assert meta["email_enabled"] is False, "this edition has no email"
        for mode, extra in (("monthly", {"month": time.strftime("%Y-%m"), "day": 1}), ):
            assert get("/api/setup/period", {"mode": mode, **extra}).get("ok"), f"{mode} setup failed"
        meta = get("/api/meta")
        assert meta["period_mode"] == "monthly" and len(meta["periods"]) >= 4, "periods didn't extend by themselves"
        ov = get("/api/overview?period=" + meta["current"])
        assert ov["days"] in (28, 29, 30, 31)
        say("smoke test passed: starts clean, asks for setup, monthly ledger works, no email")
    finally:
        proc.kill()
        shutil.rmtree(data, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="like 1.0.0 (a leading v is fine)")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--stage-only", action="store_true", help="assemble and test the folder with the Python you're running; no downloads, no zip")
    a = ap.parse_args()
    version = a.version.lstrip("v")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", version):
        sys.exit("version can only hold letters, numbers, dots, dashes and underscores")
    out = Path(a.out)
    top = out / "Personal Finance Ledger"
    shutil.rmtree(top, ignore_errors=True)
    top.mkdir(parents=True)
    stage_app(top / "app")
    for f in ("Start Personal Finance Ledger.bat", "Stop Personal Finance Ledger.bat", "START HERE.txt"):
        shutil.copy2(ROOT / "release" / f, top / f)
    (top / "VERSION.txt").write_text(version + "\n", encoding="utf-8")
    say(f"assembled {top}")
    if a.stage_only:
        smoke_test(Path(sys.executable), top / "app")
        say("stage-only: done (no zip made)")
        return
    work = out / "_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    exe = embed_python(top / "python", work)
    smoke_test(exe, top / "app")
    zpath = out / f"Personal-Finance-Ledger-v{version}-windows.zip"
    zpath.unlink(missing_ok=True)
    say(f"zipping to {zpath}")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(top.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out).as_posix())
    shutil.rmtree(work, ignore_errors=True)
    say(f"done: {zpath} ({zpath.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
