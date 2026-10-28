@echo off
setlocal
cd /d "%~dp0"
set "STATION_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "STATION_PYTHON=%~dp0.venv\Scripts\python.exe"
"%STATION_PYTHON%" -m sw.ground_station.ui_v2 --all
if errorlevel 1 (
    echo UI review could not start. See the error above.
    pause
    exit /b 1
)
