@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem Update.bat - updates Personal Finance Ledger. Your numbers (the finance_data folder), your private Python setup (.venv) and
rem secrets.toml are never touched. It works two ways:
rem   1. Run from a downloaded, extracted update zip: it finds your installed Personal Finance Ledger on this computer and updates it.
rem   2. Run from inside your installed Personal Finance Ledger folder: it downloads the newest version from GitHub and installs it.
set "REPO=Prisonmike1108/Personal-Finance-Ledger"
set "BRANCH=main"
set "WORK=%TEMP%\PersonalFinanceLedger-Update"
set "LOG=%TEMP%\PersonalFinanceLedger-Update.log"

if /i "%~1"=="run" goto :online

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
if exist "%HERE%\.venv\Scripts\python.exe" goto :online_start
if exist "%HERE%\finance_data" goto :online_start
goto :package

rem ---------- Way 2: inside an installed folder, so fetch from GitHub ----------
:online_start
rem Run from a temporary copy: this file gets replaced by the update, and cmd must not be reading it while that happens.
set "TMPBAT=%TEMP%\PersonalFinanceLedger-Update.bat"
copy /y "%~f0" "%TMPBAT%" >nul 2>&1
if not exist "%TMPBAT%" (
  echo Could not start the update.
  pause
  exit /b 1
)
call "%TMPBAT%" run "%~dp0" & exit /b

:online
set "APP=%~2"
if "%APP:~-1%"=="\" set "APP=%APP:~0,-1%"
title Updating Personal Finance Ledger
echo.
echo   Updating Personal Finance Ledger
echo   ---------------------
echo.
>"%LOG%" echo Update started %DATE% %TIME%
if not exist "%APP%\ledger_html" goto :wrongfolder

echo   Downloading the latest version from GitHub...
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/%REPO%/archive/refs/heads/%BRANCH%.zip' -OutFile '%WORK%\new.zip'" >>"%LOG%" 2>&1
if errorlevel 1 goto :nodownload
if not exist "%WORK%\new.zip" goto :nodownload

echo   Unpacking...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%WORK%\new.zip' -DestinationPath '%WORK%\x' -Force; Get-ChildItem -LiteralPath '%WORK%\x' -Recurse -File | Unblock-File" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
set "SRC="
for /d %%d in ("%WORK%\x\*") do set "SRC=%%~fd"
if not defined SRC goto :fail
if not exist "%SRC%\ledger_html" goto :fail
goto :apply

rem ---------- Way 1: an extracted update zip, so find the installed ledger ----------
:package
title Updating Personal Finance Ledger
echo.
echo   Updating Personal Finance Ledger
echo   ---------------------
echo.
>"%LOG%" echo Update started %DATE% %TIME%
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%" >nul 2>&1
echo   Looking for your Personal Finance Ledger on this computer (this can take a minute)...
set "ULSELF=%HERE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$self=$env:ULSELF.TrimEnd('\'); $up=$env:USERPROFILE; $roots=@(); $roots+=Get-ChildItem -LiteralPath $up -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'AppData' } | ForEach-Object { $_.FullName }; foreach($dr in Get-PSDrive -PSProvider FileSystem){ if($dr.Root -match '^[A-Z]:\\$'){ $roots+=Get-ChildItem -LiteralPath $dr.Root -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '^(Windows|Program Files.*|ProgramData|Users|.Recycle.Bin|System Volume Information)$' } | ForEach-Object { $_.FullName } } }; $seen=@{}; $found=@(Get-ChildItem -LiteralPath $up -Filter 'Open Ledger.pyw' -File -ErrorAction SilentlyContinue); foreach($r in $roots){ $found+=Get-ChildItem -LiteralPath $r -Filter 'Open Ledger.pyw' -File -Recurse -Depth 4 -ErrorAction SilentlyContinue }; foreach($f in $found){ $d=$f.DirectoryName; if($d -ne $self -and -not $seen[$d] -and ((Test-Path -LiteralPath (Join-Path $d '.venv\Scripts\python.exe')) -or (Test-Path -LiteralPath (Join-Path $d 'finance_data')))){ $seen[$d]=1; $d } }" >"%WORK%\found.txt" 2>>"%LOG%"

set N=0
for /f "usebackq delims=" %%p in ("%WORK%\found.txt") do (
  set /a N+=1
  set "F!N!=%%p"
)
if "%N%"=="0" goto :askpath
set "APP="
if "%N%"=="1" set "APP=!F1!"
if "%N%"=="1" goto :found
echo.
echo   I found more than one Personal Finance Ledger. Which one should be updated?
for /l %%i in (1,1,%N%) do echo     %%i. !F%%i!
set "PICK="
set /p "PICK=  Type its number and press Enter: "
for /l %%i in (1,1,%N%) do if "!PICK!"=="%%i" set "APP=!F%%i!"
if not defined APP goto :notfound
goto :found

:askpath
echo.
echo   I could not find it by myself.
echo   Open your Personal Finance Ledger folder (the one with Open Ledger.pyw in it), click the address bar,
echo   copy the folder path, paste it here and press Enter.
set "APP="
set /p "APP=  Folder: "
if not defined APP goto :notfound
set "APP=%APP:"=%"
if "%APP:~-1%"=="\" set "APP=%APP:~0,-1%"
if not exist "%APP%\Open Ledger.pyw" goto :notfound

:found
echo.
echo   Found it: %APP%
set "SRC=%HERE%"
goto :apply

rem ---------- Shared: close the ledger, copy the new files in, reopen ----------
:apply
set "OLDV=unknown"
if exist "%APP%\VERSION" set /p OLDV=<"%APP%\VERSION"
echo   Closing the ledger if it is open...
call "%APP%\Stop Ledger.bat" >nul 2>&1

echo   Installing the update (your numbers are not touched)...
robocopy "%SRC%" "%APP%" /E /NFL /NDL /NJH /NJS /NP /XD finance_data .venv updates .git __pycache__ /XF secrets.toml install.log update.log status.js "UPDATE - READ ME.txt" >>"%LOG%" 2>&1
if errorlevel 8 goto :fail

rem Pick up any new Python packages the update needs (quick when there are none).
if exist "%APP%\.venv\Scripts\python.exe" "%APP%\.venv\Scripts\python.exe" -m pip install -r "%APP%\requirements.txt" -q --disable-pip-version-check >>"%LOG%" 2>&1

set "NEWV=unknown"
if exist "%APP%\VERSION" set /p NEWV=<"%APP%\VERSION"
rmdir /s /q "%WORK%" >nul 2>&1
echo.
if "%OLDV%"=="%NEWV%" (echo   Done. You have the newest version ^(%NEWV%^).) else (echo   Done. Updated from %OLDV% to %NEWV%.)
echo   Opening the ledger...
start "" "%APP%\Open Ledger.pyw"
timeout /t 5 >nul
exit /b 0

:wrongfolder
echo   This does not look like the Personal Finance Ledger folder.
echo   Update.bat needs to stay in the same folder as Open Ledger.pyw.
goto :end

:notfound
echo.
echo   I could not find a Personal Finance Ledger to update.
echo   If you have not installed it yet, double-click Install.bat instead.
goto :end

:nodownload
echo.
echo   Could not download the update straight from GitHub.
echo   If you are online, the repo is probably private, so GitHub wants you signed in.
echo   Opening the download page: sign in, click the newest zip, click the download button,
echo   then right-click the zip, choose Extract all, and double-click Update.bat inside it.
start "" "https://github.com/%REPO%/tree/%BRANCH%/updates"
goto :end

:fail
echo.
echo   Something went wrong, so the update did not finish.
echo   Your numbers were not touched. Opening the log so it can be sent to whoever shared this with you...
start notepad "%LOG%"
goto :end

:end
echo.
pause
exit /b 1
