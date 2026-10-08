@echo off
cd /d "%~dp0"

rem Pick Python: local .venv first, then the old project's .venv, then system python
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "..\test\.venv\Scripts\python.exe" set PY=..\test\.venv\Scripts\python.exe

echo ============================================
echo   MES launcher
echo   frontend 5000 / backend 5001 / database 5002
echo ============================================
echo.

echo [1/3] starting database server on 5002 ...
start "MES-DB 5002" cmd /k "chcp 65001 >nul && %PY% database\server.py"
timeout /t 3 /nobreak >nul

echo [2/3] starting backend on 5001 ...
start "MES-Backend 5001" cmd /k "chcp 65001 >nul && %PY% backend\app.py"
timeout /t 2 /nobreak >nul

echo [3/3] starting frontend on 5000 ...
start "MES-Frontend 5000" cmd /k "chcp 65001 >nul && %PY% frontend\server.py"
timeout /t 2 /nobreak >nul

echo.
echo All three services started. Opening browser ...
start "" http://127.0.0.1:5000
echo.
echo Default admin account: admin / admin123
echo To stop a service, close its window.
pause