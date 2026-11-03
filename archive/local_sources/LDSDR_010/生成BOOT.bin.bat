@echo off
chcp 936 >nul
title 生成 SD 卡启动镜像 BOOT.bin
echo.
echo  ============================================
echo   生成 BOOT.bin  (FSBL + 码流 + 应用程序)
echo  ============================================
echo.
set SDK=E:\Vivado_2018\SDK\2018.3
rem bootgen.exe 需要 lib\win64.o 里的 DLL，否则会静默写出垃圾数据
set PATH=%SDK%\lib\win64.o;%SDK%\bin\unwrapped\win64.o;%PATH%
del /q "E:\LDSDR_010\BOOT.bin" 2>nul
"%SDK%\bin\unwrapped\win64.o\bootgen.exe" -image "E:\LDSDR_010\relay.bif" -o "E:\LDSDR_010\BOOT.bin"
if not exist "E:\LDSDR_010\BOOT.bin" (
  echo.
  echo   失败：BOOT.bin 没有生成
  pause
  exit /b 1
)
echo.
echo   已生成 E:\LDSDR_010\BOOT.bin
echo.
echo   下一步：双击 [写SD卡BOOT.bat] 把它写进 SD 卡
echo.
pause
