@echo off
setlocal
title Coc Di Lam - Khoi Dong

echo =====================================================================
echo  COC DI LAM - KHOI DONG HE THONG PHONG VAN OJT (4 CUA SO CMD)
echo =====================================================================
echo.

set "ROOT_DIR=%~dp0"

echo [*] Giai phong cac tien trinh cu va lock file truoc khi bat...
:: 1. Tat bat ky tien trinh dev_runner.py, uvicorn hoac node dang chiem cong 8000 hoac 3000
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*dev_runner.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%a >nul 2>&1

:: 2. Xoa lock dev cu cua Next.js
if exist "%ROOT_DIR%frontend\.next\dev" rmdir /s /q "%ROOT_DIR%frontend\.next\dev" >nul 2>&1

echo.
echo [1/4] Dang mo cua so 1: Backend FastAPI + TypeSafe AI Jev (Port 8000)...
start "Coc Di Lam - Backend (Port 8000)" /d "%ROOT_DIR%backend" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/4] Dang mo cua so 2: Frontend Next.js 15 (Port 3000)...
start "Coc Di Lam - Frontend (Port 3000)" /d "%ROOT_DIR%frontend" cmd /k "call npm run dev"

echo [3/4] Dang mo cua so 3: Model Orchestrator & Tool Calling Engine (Live Logs)...
start "Coc Di Lam - Model Orchestrator" /d "%ROOT_DIR%backend" cmd /k "python orchestrator_monitor.py"

echo [4/4] Dang mo cua so 4: Live Interview Turn & Neural Audio Engine (Live Logs)...
start "Coc Di Lam - Live Interview & TTS Engine" /d "%ROOT_DIR%backend" cmd /k "python interview_monitor.py"

echo.
echo [*] Dang doi he thong khoi tao trong 6 giay...
ping -n 7 127.0.0.1 >nul

echo.
echo [*] Dang mo trinh duyet tai http://localhost:3000...
start http://localhost:3000

echo.
echo =====================================================================
echo  DA KHOI DONG THANH CONG 4 CUA SO CMD DANG CHAY TRUC TIEP:
echo    [Cua so 1] Coc Di Lam - Backend (Port 8000)
echo    [Cua so 2] Coc Di Lam - Frontend (Port 3000)
echo    [Cua so 3] Coc Di Lam - Model Orchestrator (Live Search & Tool Logs)
echo    [Cua so 4] Coc Di Lam - Live Interview & TTS Engine (Turn Pipeline & Audio)
echo =====================================================================
echo (*) Hay giu ca 4 cua so CMD tren de theo doi toan bo luong xu ly.
echo (*) Khi muon dung he thong, nhap dup file stop.bat.
echo.
pause
