@echo off
rem ===========================================================================
rem  init_git.bat -- one-click git init + first commit for this repository
rem
rem  HOW TO USE
rem    1. Install Git for Windows:  https://git-scm.com/download/win
rem    2. Double-click this file (or run it from cmd / PowerShell)
rem    3. Follow the printed instructions to push to GitHub
rem
rem  NOTE: keep this file PURE ASCII with CRLF line endings.
rem        cmd.exe reads .bat as ANSI; a BOM or LF-only endings break it.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===========================================================================
echo   CCSDS TT^&C Relay - git repository initialisation
echo ===========================================================================
echo.

rem ---- 1) locate git ----
set GIT=git
where git >nul 2>nul
if errorlevel 1 (
    if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
    if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
    if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
)
"%GIT%" --version >nul 2>nul
if errorlevel 1 (
    echo [X] Git not found.
    echo.
    echo     Install Git for Windows first:
    echo       https://git-scm.com/download/win
    echo.
    echo     After installing, close and reopen this window, then run again.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('"%GIT%" --version') do echo [OK] %%v
echo.

rem ---- 2) git identity ----
set NAME=
set EMAIL=
for /f "delims=" %%v in ('"%GIT%" config --global user.name 2^>nul') do set NAME=%%v
for /f "delims=" %%v in ('"%GIT%" config --global user.email 2^>nul') do set EMAIL=%%v
if "%NAME%"=="" (
    echo [!] user.name is not configured.
    set /p NAME=    Enter your name: 
    "%GIT%" config --global user.name "!NAME!"
)
if "%EMAIL%"=="" (
    echo [!] user.email is not configured.
    set /p EMAIL=    Enter your email: 
    "%GIT%" config --global user.email "!EMAIL!"
)
echo [OK] author: !NAME! ^<!EMAIL!^>
echo.

rem ---- 3) init ----
if exist ".git" (
    echo [i] .git already exists - skipping init
) else (
    "%GIT%" init -b main
    if errorlevel 1 "%GIT%" init
)
echo.

rem ---- 4) stage + commit ----
echo [i] staging files (respecting .gitignore) ...
"%GIT%" add -A
echo.
echo [i] files to be committed:
"%GIT%" -c core.quotepath=false status --short | more +0
echo.
"%GIT%" commit -m "Initial commit: CCSDS TT&C and frequency-conversion relay payload (FPGA)" ^
 -m "Contents:" ^
 -m "  - rtl/: CCSDS 131.0-B TX/RX chain, rewritten SRRC, clock-divider fix, 10-phase parallel frame sync" ^
 -m "  - fpga/: board-level top, XDC constraints, build and program tcl scripts" ^
 -m "  - sim/: loopback testbench, 10/10 phase PASS" ^
 -m "  - sw/: PC-side codec, parameter table, demo GUI, relay control, verification tools" ^
 -m "  - board/: u-boot interception, SSH, serial helpers" ^
 -m "  - docs/: architecture figures and technical reports" ^
 -m "Verified on hardware: frame_match=1, rx_crc_ok=1, 40-byte exact match, CRC pass."
if errorlevel 1 (
    echo.
    echo [i] nothing to commit, or commit failed ^(see message above^)
)
echo.

rem ---- 5) summary ----
echo ===========================================================================
echo   Repository ready
echo ===========================================================================
"%GIT%" -c core.quotepath=false log --oneline -5
echo.
echo   Tracked files: 
"%GIT%" ls-files | find /c /v ""
echo.
echo ---------------------------------------------------------------------------
echo   NEXT: push to GitHub
echo ---------------------------------------------------------------------------
echo   1) Create an empty repository on GitHub (no README, no .gitignore)
echo      Name suggestion: ccsds-ttc-relay
echo.
echo   2) Then run these two commands here:
echo.
echo        git remote add origin https://github.com/^<your-account^>/ccsds-ttc-relay.git
echo        git push -u origin main
echo.
echo   If you use SSH instead of HTTPS:
echo        git remote add origin git@github.com:^<your-account^>/ccsds-ttc-relay.git
echo        git push -u origin main
echo.
echo ---------------------------------------------------------------------------
pause
endlocal
