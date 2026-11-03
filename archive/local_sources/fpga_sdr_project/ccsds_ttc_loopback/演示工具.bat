@echo off
rem ===========================================================================
rem  CCSDS demo launcher
rem    left  : type the parameters
rem    middle: the generated CCSDS packet
rem    bottom: the decoded content at the receiver
rem
rem  IMPORTANT: keep this file PURE ASCII and WITHOUT a BOM.
rem  cmd.exe reads a .bat as ANSI; a UTF-8 BOM or any non-ASCII byte breaks the
rem  first lines ("'???rem' is not recognized as an internal or external command").
rem ===========================================================================
setlocal
set PY=C:\Users\23638\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
set GUI=E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc\ccsds_demo_gui.py

if not exist "%PY%" (
    echo [X] Python not found: %PY%
    pause
    exit /b 1
)
if not exist "%GUI%" (
    echo [X] demo script not found: %GUI%
    pause
    exit /b 1
)

echo Starting CCSDS demo tool ...
"%PY%" "%GUI%"
if errorlevel 1 (
    echo.
    echo [X] runtime error - send the message above to the developer
    pause
)
endlocal