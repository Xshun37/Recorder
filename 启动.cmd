@echo off
setlocal EnableExtensions

REM Always run from script directory
cd /d "%~dp0"

REM Launch PowerShell installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"

REM Prevent window from closing when double-clicked
echo.
echo Starter finished.
pause

endlocal
exit /b 0