@echo off
REM ============================================================
REM  DateClock - one-click builder (Windows batch wrapper)
REM
REM  All the actual logic lives in build.py. This script just
REM  finds a Python and invokes it. If you use Thonny, you can
REM  alternatively open build.py in Thonny and press F5.
REM
REM  Order of preference:
REM    1. "py" launcher (standard python.org installs)
REM    2. "python" on PATH
REM    3. Thonny's bundled Python
REM ============================================================

setlocal
cd /d "%~dp0"

set "PYCMD="

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYCMD=py -3"
    goto :found
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYCMD=python"
    goto :found
)

if exist "%LOCALAPPDATA%\Programs\Thonny\python.exe" (
    set "PYCMD=""%LOCALAPPDATA%\Programs\Thonny\python.exe"""
    goto :found
)
if exist "%ProgramFiles%\Thonny\python.exe" (
    set "PYCMD=""%ProgramFiles%\Thonny\python.exe"""
    goto :found
)
if exist "%ProgramFiles(x86)%\Thonny\python.exe" (
    set "PYCMD=""%ProgramFiles(x86)%\Thonny\python.exe"""
    goto :found
)

echo [ERROR] No Python installation found.
echo.
echo Either install Thonny from https://thonny.org (then re-run this
echo script, OR open build.py in Thonny and press F5), or install
echo standalone Python from https://www.python.org/downloads/windows/
echo with "Add Python to PATH" ticked.
echo.
pause
exit /b 1

:found
echo Using Python: %PYCMD%
echo.
%PYCMD% "%~dp0build.py"
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
pause
endlocal
