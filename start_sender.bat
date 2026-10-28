@echo off
setlocal
cd /d "%~dp0"
set "STATION_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "STATION_PYTHON=%~dp0.venv\Scripts\python.exe"
"%STATION_PYTHON%" -m sw.ground_station --role sender %*
if errorlevel 1 (
    echo.
    echo Sender exited with an error. See the Python error above.
    echo Requirements: Python 3.10+, Tkinter, NumPy and pyserial.
    echo Install Python packages with:
    echo python -m pip install -r sw\ground_station\requirements.txt
    pause
    exit /b 1
)
exit /b 0
