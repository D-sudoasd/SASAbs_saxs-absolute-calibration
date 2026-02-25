@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%~dp0saxsabs_workbench.pyw" %*
) else (
    python "%~dp0saxsabs_workbench.pyw" %*
)

endlocal
