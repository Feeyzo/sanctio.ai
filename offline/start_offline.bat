@echo off
rem Starts Sanctio (API + dashboard) and SwiftShip on this laptop. No internet needed.
cd /d "%~dp0.."
call offline\settings.bat

if not exist backend\.venv\Scripts\python.exe (
  echo Run setup_offline.bat first, once, while you have internet.
  pause
  exit /b 1
)
if not exist frontend\dist\index.html (
  echo The dashboard is not built yet. Run setup_offline.bat first.
  pause
  exit /b 1
)

echo Starting Sanctio on http://localhost:8000 ...
start "Sanctio (close this window to stop)" /D "%CD%\backend" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
echo Starting SwiftShip on http://localhost:8100 ...
start "SwiftShip (close this window to stop)" /D "%CD%\demo_business" cmd /k ..\backend\.venv\Scripts\python.exe -m uvicorn app:app --port 8100

echo Waiting for both to be ready...
powershell -NoProfile -Command "foreach ($u in 'http://localhost:8000/api/health','http://localhost:8100/health') { $ok=$false; for ($i=0; $i -lt 60 -and -not $ok; $i++) { try { Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok=$true } catch { Start-Sleep 1 } }; if (-not $ok) { exit 1 } }"
if errorlevel 1 (
  echo One of them did not start. Look at the two black windows for the error.
  pause
  exit /b 1
)

echo Resetting the demo data...
pushd backend
.venv\Scripts\python.exe -m scripts.seed_demo
popd

start "" http://localhost:8100
start "" http://localhost:8000
echo.
echo Ready.
echo   SwiftShip (customer side):  http://localhost:8100
echo   Sanctio dashboard:          http://localhost:8000   sign in: demo@swiftship.test / Passw0rd!23
echo To stop, close the "Sanctio" and "SwiftShip" windows.
pause
