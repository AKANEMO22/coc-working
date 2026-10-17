@echo off
setlocal
cd /d "%~dp0"
python "%~dp0dev_runner.py" stop
exit /b %errorlevel%
