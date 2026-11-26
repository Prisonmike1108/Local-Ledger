@echo off
rem One-click setup for Personal Finance Ledger (Windows). Double-click this file.
rem It runs in the background with no black window and shows its progress in a browser tab.
rem Everything it prints goes to install.log in this folder.
setlocal EnableExtensions
cd /d "%~dp0"

if /i "%~1"=="worker" goto :worker

rem First run: start a hidden copy of this file to do the work, then close this window.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath cmd.exe -ArgumentList '/c call \"%~f0\" worker' -WindowStyle Hidden" >nul 2>&1
if errorlevel 1 start "" /min "%~f0" worker
exit /b 0


:worker
set "SF=%~dp0installer\status.js"
set "LOG=%~dp0install.log"
set "TRIED="
set "CURSTEP=1"
>"%LOG%" echo Personal Finance Ledger setup started %date% %time%

call :status 1 3 8 working "Getting ready" "Opening this progress page and checking your PC."
start "" "%~dp0installer\progress.html"

rem Clear the "downloaded from the internet" mark from the files in this folder so Windows
rem stops blocking them one by one. Harmless if it was already clear.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >>"%LOG%" 2>&1

rem Note whether Smart App Control is on (0x1 on, 0x2 evaluation, 0x0 off). Only recorded in the log.
set "SAC="
for /f "tokens=3" %%S in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy" /v VerifiedAndReputablePolicyState 2^>nul') do set "SAC=%%S"
>>"%LOG%" echo Smart App Control state: %SAC%

call :status 2 10 40 working "Checking for Python" "Looking for Python 3.11 or newer."
call :findpython
if defined PY goto :havepython

call :status 2 12 45 working "Installing Python" "This takes about a minute. If Windows asks for permission, click Yes."
call :installpython
call :findpython
if not defined PY goto :nopython

:havepython
>>"%LOG%" echo Using Python: %PY%
call :status 3 45 55 working "Setting up a private space" "Creating a private Python environment just for the ledger."
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv >>"%LOG%" 2>&1
if not exist ".venv\Scripts\python.exe" goto :fail

call :status 4 55 92 working "Installing the ledger" "Downloading and installing the ledger's parts. This is the longest step, usually one to three minutes."
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check >>"%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check --no-input >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

call :status 5 95 99 working "Opening the ledger" "Starting the ledger. It opens in a new browser tab in a few seconds."
start "" /wait ".venv\Scripts\pythonw.exe" "Open Ledger.pyw"
call :status 5 100 100 done "All set" "Personal Finance Ledger is open in another tab. You can close this one. Next time, double-click Open Ledger.pyw."
exit /b 0


:status
rem Usage: call :status STEP PERCENT NEXT_PERCENT STATE "Title" "Message"
rem Writes the file the progress page reads. Keep titles and messages free of quotes and & | < > ^ characters.
set "CURSTEP=%~1"
>"%SF%" echo window.LL={step:%~1,pct:%~2,next:%~3,state:"%~4",title:"%~5",msg:"%~6"};
exit /b 0


:findpython
rem Sets PY to a command that runs Python 3.11 or newer, or leaves it empty.
set "PY="
for %%C in ("py -3" "python") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=%%~C"
    )
)
rem A fresh install is not on PATH in this window yet, so also look where the installer puts it.
for %%V in (313 312 311) do call :trypath %%V
exit /b 0

:trypath
if not defined PY if exist "%LocalAppData%\Programs\Python\Python%1\python.exe" set PY="%LocalAppData%\Programs\Python\Python%1\python.exe"
if not defined PY if exist "%ProgramFiles%\Python%1\python.exe" set PY="%ProgramFiles%\Python%1\python.exe"
exit /b 0


:installpython
rem Uses winget, which comes with current Windows 10 and 11.
where winget >nul 2>&1
if errorlevel 1 exit /b 1
set "TRIED=1"
winget install -e --id Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements >>"%LOG%" 2>&1
exit /b 0


:nopython
if defined TRIED goto :pythonhidden
call :status 2 12 12 error "Python could not be installed" "Windows would not let this installer add Python. Install Python 3.11 or newer from the page that just opened, tick Add python.exe to PATH, then double-click Install.bat again."
start "" "https://www.python.org/downloads/"
exit /b 1

:pythonhidden
call :status 2 40 40 error "One more step" "Python was installed, but this installer cannot see it yet. Double-click Install.bat again to finish."
exit /b 1


:fail
call :status %CURSTEP% 50 50 error "Setup stopped" "Something went wrong. Notepad is opening install.log, which has the details. If Windows said it blocked something, double-click Help - Windows Blocked It.bat, then run Install.bat again."
start "" notepad "%LOG%"
exit /b 1
