"""Double-click to open Personal Finance Ledger (HTML edition) in your browser. Starts the server quietly in the background if it
isn't already running (no terminal window), and restarts itself when the code changes, so one link is all you need:
http://127.0.0.1:8600   Pin this file, or make a shortcut to it on your desktop.
With --no-browser it only starts the server (for a Windows Startup shortcut) and does not open a tab."""
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8600
URL = f"http://127.0.0.1:{PORT}"


def up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.4):
            return True
    except OSError:
        return False


VENV = HERE / ".venv" / "Scripts" / "pythonw.exe"  # the private environment Install.bat makes, when it exists
PY = str(VENV) if VENV.exists() else sys.executable

if not up():
    subprocess.Popen([PY, str(HERE / "ledger_html" / "server.py"), "--watch"],
                     cwd=str(HERE), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(60):  # up to about 15 seconds for it to start
        if up():
            break
        time.sleep(0.25)
if "--no-browser" not in sys.argv:
    webbrowser.open(URL)
