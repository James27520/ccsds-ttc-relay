@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\station.ps1" -Action setup
set "STATION_EXIT=%ERRORLEVEL%"
pause
exit /b %STATION_EXIT%
