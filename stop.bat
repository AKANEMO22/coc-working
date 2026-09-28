@echo off
setlocal
title Coc Di Lam - Dung He Thong

echo =====================================================================
echo  DANG DUNG TOAN BO HE THONG COC DI LAM (PORTS 8000, 3000, MONITORS)...
echo =====================================================================
echo.

:: 1. Dung tien trinh dev_runner.py (tien trinh tu dong restart ngam) neu co
echo [*] Dung supervisor dev_runner.py...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*dev_runner.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 2. Giai phong cong 8000 (Backend FastAPI) va cong 3000 (Frontend Next.js) kem cay tien trinh con (/t)
echo [*] Giai phong port 8000 va port 3000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%a >nul 2>&1

:: 3. Quet sach cac tien trinh Next.js, Uvicorn, Monitor bang PowerShell WMI
echo [*] Quet sach cac tien trinh Node.js va Python con sot lai...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.main:app*' -or $_.CommandLine -like '*orchestrator_monitor.py*' -or $_.CommandLine -like '*interview_monitor.py*' -or ($_.Name -eq 'node.exe' -and $_.CommandLine -like '*next*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 4. Dong cac cua so CMD cua Coc Di Lam
echo [*] Dong cac cua so CMD cua Coc Di Lam...
taskkill /fi "windowtitle eq Coc Di Lam*" /f /t >nul 2>&1

:: 5. Xoa dev cache va lock cua Next.js
echo [*] Don dep bo nho cache...
if exist "%~dp0frontend\.next\dev" rmdir /s /q "%~dp0frontend\.next\dev" >nul 2>&1

echo.
echo =====================================================================
echo  DA DUNG TOAN BO MAY CHU VA GIAI PHONG PORT 8000 & 3000 TRIET DE!
echo  (Trang localhost:3000 bay gio se hoan toan khong the truy cap duoc nua)
echo =====================================================================
echo.
pause
