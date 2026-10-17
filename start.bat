@echo off
setlocal
chcp 65001 >nul
title Coc Di Lam - Local Servers
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"
if not "%PYTHON_EXE%"=="python" goto RUN
where python >nul 2>&1
if errorlevel 1 (
  echo [LOI] Khong tim thay Python trong PATH.
  set "EXIT_CODE=1"
  goto FAILED
)
:RUN
"%PYTHON_EXE%" "%~dp0dev_runner.py" start --open-browser %*
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" goto FAILED
exit /b 0

:FAILED
echo.
echo [LOI] Launcher khong chay thanh cong. Xem nguyen nhan o log phia tren.
echo Khong tu tat server la, khong xoa cache phien phong van.
if not "%COC_NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
