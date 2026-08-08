@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Run 1_SETUP_ONCE.bat first.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_tools\configure_local.ps1"
if errorlevel 1 (
  echo Configuration failed.
  pause
  exit /b 1
)

echo.
echo Configuration saved.
echo Before starting locally, STOP the Railway bot service.
echo Then double-click 3_RUN_BOT.bat
pause
