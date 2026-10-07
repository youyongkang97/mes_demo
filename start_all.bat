@echo off
chcp 65001 >nul
title 下料站 MES（简单版）- 三端一键启动
cd /d "%~dp0"

rem 依次找 Python：本目录的 .venv → 旁边旧项目 test 的 .venv（如果你有，可以先用它跑起来）
rem → 都没有就用系统 python。正式使用建议按 README 在本目录建自己的 .venv。
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "..\test\.venv\Scripts\python.exe" set PY=..\test\.venv\Scripts\python.exe

echo ============================================
echo   下料站 MES（简单版）- 三端一键启动
echo   前端 5000 / 后端 5001 / 数据库端 5002
echo ============================================
echo.

echo [1/3] 启动数据库端服务器 (5002)...
start "MES-数据库端 5002" cmd /k "chcp 65001 >nul && %PY% database\server.py"
timeout /t 3 /nobreak >nul

echo [2/3] 启动后端应用服务 (5001)...
start "MES-后端 5001" cmd /k "chcp 65001 >nul && %PY% backend\app.py"
timeout /t 2 /nobreak >nul

echo [3/3] 启动前端服务器 (5000)...
start "MES-前端 5000" cmd /k "chcp 65001 >nul && %PY% frontend\server.py"
timeout /t 2 /nobreak >nul

echo.
echo 全部服务已启动，正在打开浏览器...
start "" http://127.0.0.1:5000
echo.
echo 默认管理员账号：admin / admin123 （首次启动自动创建，请尽快修改密码）
echo 提示：关闭对应服务窗口即可停止该服务。
pause
