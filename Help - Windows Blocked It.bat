@echo off
rem Helper for when Windows blocks Personal Finance Ledger (Smart App Control or "protected your PC").
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo Personal Finance Ledger - Windows blocked it?
echo ==================================
echo.
echo Step 1: clearing the "downloaded from the internet" mark from every file in this folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
echo Done. Now try Install.bat again.
echo.

set "SAC="
for /f "tokens=3" %%S in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy" /v VerifiedAndReputablePolicyState 2^>nul') do set "SAC=%%S"
if "%SAC%"=="0x1" echo Smart App Control status: ON
if "%SAC%"=="0x2" echo Smart App Control status: ON, in evaluation mode
if "%SAC%"=="0x0" echo Smart App Control status: OFF, so it is not what is blocking you.
if not defined SAC echo Smart App Control status: not found on this PC.
echo.
echo If it is still blocked, you have two options:
echo.
echo   A. Start over from the download. Right-click the .zip file itself, choose Properties,
echo      tick "Unblock" at the bottom, click OK, and only then extract it. Do not run
echo      anything from inside the zip window.
echo.
echo   B. Turn Smart App Control off. Windows Security, then App and browser control, then
echo      Smart App Control settings, then Off. This app is not signed by a publisher that
echo      Smart App Control knows, which is why it can block it. On some versions of
echo      Windows you cannot turn it back on afterward, so only do this if you are okay with that.
echo.
choice /c YN /m "Open the Windows Security page for Smart App Control now"
if errorlevel 2 goto :end
start "" "windowsdefender://appbrowser"

:end
echo.
pause
exit /b 0
