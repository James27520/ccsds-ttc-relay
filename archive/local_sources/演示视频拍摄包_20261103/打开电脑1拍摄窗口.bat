@echo off
setlocal
set "STATION_PYW=%~dp0..\ccsds-ttc-relay\.venv\Scripts\pythonw.exe"
if not exist "%STATION_PYW%" (
    echo Run setup_station.bat in the repository first.
    pause
    exit /b 1
)
start "" "%STATION_PYW%" "%~dp0terminal1_layout.pyw"
