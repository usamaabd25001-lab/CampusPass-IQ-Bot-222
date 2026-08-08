@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

title CampusPass IQ V10 - Laptop Server

if not exist ".venv\Scripts\python.exe" (
  echo Run 1_SETUP_ONCE.bat first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo Run 2_CONFIGURE_BOT.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
echo ==================================================
echo CampusPass IQ is starting...
echo Keep this window OPEN.
echo Stop with Ctrl+C only when needed.
echo Local health: http://127.0.0.1:8080/ping
echo ==================================================
python -m app.main

echo.
echo The bot stopped. Read the last error above.
pause
