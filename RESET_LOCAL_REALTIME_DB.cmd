@echo off
setlocal
title Ontology Dashboard - Reset Local Demo Database
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv\Scripts\python.exe was not found.
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

echo Starting only the repository-owned local PostgreSQL service...
docker compose -f infra\docker-compose.yml --profile polyglot up -d --wait postgres
if errorlevel 1 (
  echo [ERROR] Local PostgreSQL could not be started.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" scripts\reset_local_realtime_postgres.py %*
set "RESET_EXIT=%ERRORLEVEL%"

if not "%RESET_EXIT%"=="0" echo Database reset was not completed.
pause
exit /b %RESET_EXIT%
