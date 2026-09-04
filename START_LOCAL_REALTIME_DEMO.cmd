@echo off
setlocal
title Ontology Dashboard - Local Real-time Demo
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe was not found.
  echo Complete the repository setup described in README.md first.
  pause
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker was not found in PATH.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is not running or is not ready.
  pause
  exit /b 1
)

if not exist "systems\frontend\node_modules" (
  echo [ERROR] Frontend dependencies are missing.
  echo Run npm install in systems\frontend first.
  pause
  exit /b 1
)

if defined GEN_DATA_ROOT goto gen_data_ready
if exist "..\gen_data\app\main.py" set "GEN_DATA_ROOT=%CD%\..\gen_data"
if exist "..\gen-data\app\main.py" set "GEN_DATA_ROOT=%CD%\..\gen-data"

:gen_data_ready
if not defined GEN_DATA_ROOT (
  echo [ERROR] gen_data was not found next to ontology_dashboard.
  echo Set GEN_DATA_ROOT to the gen_data repository directory.
  pause
  exit /b 1
)

if not exist "%GEN_DATA_ROOT%\canonical\dataset\dataset_manifest.json" (
  echo [ERROR] The gen_data canonical dataset manifest was not found.
  echo Checked: %GEN_DATA_ROOT%
  pause
  exit /b 1
)

echo Starting the integrated real-time demo.
echo Defaults: 168h history / 720h run / 60x speed.
echo The browser opens after PostgreSQL, workers, live data, and Frontend are ready.
echo Press Ctrl+C in this window to stop application processes.
echo.

".venv\Scripts\python.exe" scripts\run_local_realtime.py --open-browser %*
set "RUNNER_EXIT=%ERRORLEVEL%"

if not "%RUNNER_EXIT%"=="0" echo [ERROR] Integrated runner exited with code %RUNNER_EXIT%.
pause
exit /b %RUNNER_EXIT%
