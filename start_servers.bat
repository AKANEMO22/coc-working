@echo off
echo Starting Cóc Đi Làm Dev Servers...
start "CocDiLam-Backend" /min /d "%~dp0backend" python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
start "CocDiLam-Frontend" /min /d "%~dp0frontend" cmd /c npm run dev
echo Servers started in background!
