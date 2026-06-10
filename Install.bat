@echo off
REM ==========================================================================
REM  Double-click this file to install DateClock.
REM
REM  It just runs install.ps1 with PowerShell's execution policy bypassed
REM  for this single invocation. Your system-wide PS policy is not changed.
REM ==========================================================================

cd /d "%~dp0"

if not exist "dist\DateClock.exe" (
    echo.
    echo ERROR: dist\DateClock.exe is missing.
    echo Run build.bat first to produce the executable.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
