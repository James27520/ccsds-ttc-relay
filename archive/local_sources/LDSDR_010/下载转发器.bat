@echo off
chcp 936 >nul
title 下载转发器到 LDSDR (JTAG)
echo.
echo  ============================================
echo   下载 PL 转发器 + PS 程序到 LDSDR 板
echo   约需 15 秒，期间不要断电
echo  ============================================
echo.
"E:\Vivado_2018\SDK\2018.3\bin\xsct.bat" "E:\LDSDR_010\program_device.tcl"
echo.
echo  ============================================
echo   完成。现在可以打开 relay_gui.py 看状态了
echo  ============================================
pause
