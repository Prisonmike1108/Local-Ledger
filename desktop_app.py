"""Personal Finance Ledger as a desktop app: the same local ledger, in its own window, with a tray icon.

    python desktop_app.py               # window + tray icon (what the installed app does)
    python desktop_app.py --no-window   # just the local server, no window (used by the build's smoke test)

The ledger itself is unchanged: ledger_html/server.py still serves the pages on this PC only. This file starts that
server in the background, shows it in a native window (no browser, nothing to bookmark), and keeps a tray icon so
closing the window doesn't stop anything. Pick Quit from the tray icon to stop it.

Your numbers live in one folder that updates and reinstalls never touch:
    Windows  %APPDATA%\\Personal Finance Ledger\\My Ledger Data
    Mac      ~/Library/Application Support/Personal Finance Ledger/My Ledger Data
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "Personal Finance Ledger"
FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # where the bundled files are (the source folder when not packaged)
DEFAULT_PORT = 8600


def app_dir() -> Path:
    """The per-user folder for this app (data, settings that aren't numbers, the window's own storage)."""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / APP_NAME


APP_DIR = app_dir()
DATA = Path(os.environ.get("FINANCE_DATA_DIR") or APP_DIR / "My Ledger Data")
os.environ["FINANCE_DATA_DIR"] = str(DATA)  # the ledger reads this once, when it is imported below
SHOW_FLAG = APP_DIR / "show.flag"  # a second launch drops this file; the running copy sees it and brings its window forward


def is_ours(port: int) -> bool:
    """True when this port is already answering as the ledger (another copy of the app is running)."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/meta", headers={"X-Ledger": "1"})
        return "needs_setup" in json.loads(urllib.request.urlopen(req, timeout=2).read())
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def pick_port() -> int | None:
    """8600 when it's free. None when a running copy of the ledger already has it. Otherwise the next free port."""
    want = int(os.environ.get("LEDGER_PORT", DEFAULT_PORT))
    if port_free(want):
        return want
    if is_ours(want):
        return None
    return next((p for p in range(want + 1, want + 40) if port_free(p)), want)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def tray_image():
    from PIL import Image
    for name in ("icon.png", "assets/icon.png"):
        f = BASE / name
        if f.exists():
            return Image.open(f)
    return Image.new("RGBA", (64, 64), (46, 125, 98, 255))


def main() -> int:
    no_window = "--no-window" in sys.argv
    APP_DIR.mkdir(parents=True, exist_ok=True)
    port = pick_port()
    if port is None:  # already running: ask that copy to show its window, then leave
        SHOW_FLAG.write_text(str(time.time()))
        return 0
    os.environ["LEDGER_PORT"] = str(port)
    sys.path.insert(0, str(BASE))
    from ledger_html import server  # noqa: E402  (after the environment above is set)

    srv = server.ThreadingHTTPServer(("127.0.0.1", port), server.Handler)  # this PC only
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        if server.lan_cfg().get("enabled"):  # phone access was left on
            server.lan_start()
    except Exception as e:
        print(f"Phone access could not start: {e}")
    url = f"http://127.0.0.1:{port}"
    print(f"{APP_NAME} at {url}   data: {DATA}", flush=True)
    if no_window:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            srv.shutdown()
        return 0

    import webview
    state = {"quit": False, "tray": False}
    window = webview.create_window(APP_NAME, url, width=1440, height=900, min_size=(960, 640), text_select=True)

    def quit_app(*_a) -> None:
        state["quit"] = True
        try:
            if icon:
                icon.stop()
        except Exception:
            pass
        window.destroy()

    def show(*_a) -> None:
        window.show()
        try:
            window.restore()
        except Exception:
            pass

    def on_closing():
        if state["quit"] or not state["tray"]:
            return True  # no tray icon to come back from: closing the window quits
        window.hide()
        return False

    window.events.closing += on_closing

    icon = None
    try:
        import pystray
        icon = pystray.Icon(APP_NAME, tray_image(), APP_NAME, menu=pystray.Menu(
            pystray.MenuItem("Open the ledger", show, default=True),
            pystray.MenuItem("Open my data folder", lambda *_: open_folder(DATA)),
            pystray.MenuItem("Quit", quit_app)))
        icon.run_detached()
        state["tray"] = True
    except Exception as e:  # no tray on this desktop: the app still works, closing the window just quits
        print(f"No tray icon: {e}")

    def watch_flag() -> None:
        while not state["quit"]:
            time.sleep(1)
            if SHOW_FLAG.exists():
                SHOW_FLAG.unlink(missing_ok=True)
                try:
                    show()
                except Exception:
                    pass

    threading.Thread(target=watch_flag, daemon=True).start()
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # exports (CSV, Excel) save from the window
    except Exception:
        pass
    webview.start(private_mode=False, storage_path=str(APP_DIR / "window"))
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
