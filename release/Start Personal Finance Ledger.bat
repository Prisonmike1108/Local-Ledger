@echo off
rem Starts Personal Finance Ledger and opens it in your browser. Your numbers live in "My Ledger Data", right next to this file.
cd /d "%~dp0"
set "FINANCE_DATA_DIR=%~dp0My Ledger Data"
start "" "python\pythonw.exe" "app\Open Ledger.pyw"
