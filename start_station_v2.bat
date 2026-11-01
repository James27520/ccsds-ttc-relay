@echo off
setlocal
echo.
echo  1. Computer 1 - Terminal 1 (telecontrol available inside)
echo  2. Computer 2 - Terminal 2 only
echo  3. Single-computer bench - all three windows
echo  4. Check this computer (no board connection)
echo  0. Exit
choice /c 12340 /n /m "Select 1, 2, 3, 4 or 0: "
if errorlevel 5 exit /b 0
if errorlevel 4 goto check
if errorlevel 3 goto bench
if errorlevel 2 goto terminal2
call "%~dp0start_terminal1.bat"
exit /b
:terminal2
call "%~dp0start_terminal2.bat"
exit /b
:bench
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\station.ps1" -Action all
if errorlevel 1 pause
exit /b
:check
call "%~dp0check_station.bat"
