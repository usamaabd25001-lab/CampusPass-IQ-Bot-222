@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo CampusPass IQ - Windows setup (run once)
echo ==================================================

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python Launcher was not found.
  echo Install Python 3.12 x64 and enable "Add python.exe to PATH".
  pause
  exit /b 1
)

py -3.12 -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 was not found.
  echo Install Python 3.12 x64, then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating isolated Python environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo [1/4] Python environment already exists.
)

call ".venv\Scripts\activate.bat"

echo [2/4] Updating pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo [3/4] Installing CampusPass dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [4/4] Checking project files...
python -m compileall -q app scripts ops alembic
if errorlevel 1 goto :failed

echo.
echo SETUP COMPLETED SUCCESSFULLY.
echo Next: double-click 2_CONFIGURE_BOT.bat
pause
exit /b 0

:failed
echo.
echo SETUP FAILED. Keep this window open and take a photo of the red error.
pause
exit /b 1
