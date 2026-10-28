@echo off
setlocal
cd /d "%~dp0"
set "STATION_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "STATION_PYTHON=%~dp0.venv\Scripts\python.exe"
"%STATION_PYTHON%" -m sw.ground_station.ui_v2 --role receiver --online-business
if errorlevel 1 (
    echo Station UI could not start. See the error above.
    pause
    exit /b 1
)
