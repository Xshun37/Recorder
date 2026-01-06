@echo off
setlocal EnableExtensions

REM Always run from script directory
cd /d "%~dp0"

REM Launch PowerShell installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

REM Prevent window from closing when double-clicked
echo.
echo Installer finished.
pause

endlocal
exit /b 0