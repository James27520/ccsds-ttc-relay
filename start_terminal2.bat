@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\station.ps1" -Action 2
set "STATION_EXIT=%ERRORLEVEL%"
if not "%STATION_EXIT%"=="0" pause
exit /b %STATION_EXIT%
