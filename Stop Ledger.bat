@echo off
rem Stops Personal Finance Ledger (whatever is listening on port 8600). "Open Ledger.pyw" starts it again.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8600 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
echo Personal Finance Ledger stopped.
