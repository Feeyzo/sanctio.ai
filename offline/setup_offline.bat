@echo off
rem ONE-TIME SETUP. Run this while you have internet. It downloads what Sanctio needs.
cd /d "%~dp0.."

python --version >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.11 or newer from python.org,
  echo tick "Add python.exe to PATH" during installation, then run this file again.
  pause
  exit /b 1
)
call npm --version >nul 2>nul
if errorlevel 1 (
  echo Node.js is not installed. Install the LTS version from nodejs.org, then run this file again.
  pause
  exit /b 1
)

echo [1/3] Creating the Python environment...
if not exist backend\.venv python -m venv backend\.venv
if errorlevel 1 goto failed

echo [2/3] Installing the Python packages...
backend\.venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 goto failed

echo [3/3] Building the dashboard website...
pushd frontend
call npm ci --no-audit --no-fund
if errorlevel 1 (popd & goto failed)
call npm run build
if errorlevel 1 (popd & goto failed)
popd

echo.
echo Setup finished. From now on, double-click start_offline.bat (no internet needed).
pause
exit /b 0

:failed
echo.
echo Setup failed. Check your internet connection and run this file again.
pause
exit /b 1
