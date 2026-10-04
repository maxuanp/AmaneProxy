@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
title AmaneProxy setup
echo ============================================
echo  AmaneProxy  one-click setup
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [x] python.exe not found.
  echo     Install Python 3.10+ from https://www.python.org/downloads/windows/
  echo     and tick "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

echo [1/3] resolving files and sing-box kernel ...
python "%ROOT%\setup.py" --root "%ROOT%"
if errorlevel 1 (
  echo.
  echo [x] setup.py failed. If it failed while downloading sing-box, you can
  echo     put sing-box.exe manually into the bin folder and rerun this file.
  echo.
  pause
  exit /b 1
)

echo.
echo [2/3] installing logon autostart + keep-alive task ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\install-autostart.ps1" -Root "%ROOT%"

echo.
echo [3/3] done.
echo   panel : http://127.0.0.1:18111
echo   tray  : tray icon on the taskbar (Windows 11 may hide it under the ^^ chevron)
echo   next  : open the panel and fill in your own proxy servers
echo.
echo   If the panel says sing-box is not running, run status.ps1 to see why.
echo.
pause
