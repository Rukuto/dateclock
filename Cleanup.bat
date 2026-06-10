@echo off
REM ==========================================================================
REM  Double-click this to clean up a partial DateClock install.
REM
REM  Use only if the normal Uninstall failed (e.g., you deleted the
REM  install folder before Windows could run uninstall.ps1).
REM ==========================================================================

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0cleanup.ps1"
