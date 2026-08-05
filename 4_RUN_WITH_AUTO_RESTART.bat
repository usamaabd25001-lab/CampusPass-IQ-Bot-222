@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title CampusPass IQ V10 - Auto Restart

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

:loop
echo [%date% %time%] Starting CampusPass IQ...
python -m app.main
echo [%date% %time%] Bot stopped. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
