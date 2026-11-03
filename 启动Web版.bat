@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title OTA 终端模拟器 Web 工作台

set PORT=8080

echo ============================================================
echo   OTA 终端模拟器 Web 工作台
echo ============================================================
echo.

REM ---- 1. 清理占用端口的进程 ----
echo [1/4] 检查端口 %PORT% ...
set FOUND_PID=
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    set FOUND_PID=%%a
)
if not "!FOUND_PID!"=="" (
    echo       端口被进程 !FOUND_PID! 占用，正在结束...
    taskkill /F /PID !FOUND_PID! >nul 2>&1
    ping -n 2 127.0.0.1 >nul
) else (
    echo       端口空闲
)

REM ---- 2. 清理旧的 web_server 进程 ----
echo [2/4] 检查残留进程 ...
set KILLED=0
for /f "skip=1 tokens=*" %%i in ('wmic process where "name='python.exe'" get processid^,commandline 2^>nul') do (
    set LINE=%%i
    echo !LINE! | findstr /i "web_server.py" >nul
    if not errorlevel 1 (
        for /f "tokens=1" %%p in ("!LINE!") do (
            set PID=%%p
        )
    )
)
echo       检查完成

REM ---- 3. 查找 Python ----
echo [3/4] 查找 Python ...
set PY=
if exist "D:\Dev\Python\python.exe" (
    set PY=D:\Dev\Python\python.exe
    goto :found_py
)
for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set PY=%%i
        goto :found_py
    )
)
:found_py
if "!PY!"=="" (
    echo       [ERROR] 未找到 Python，请先安装或修改本脚本中的路径
    pause
    exit /b 1
)
echo       使用: !PY!

REM ---- 4. 检查依赖并启动 ----
echo [4/4] 检查依赖 ...
"!PY!" -c "import paho.mqtt" >nul 2>&1
if errorlevel 1 (
    echo       缺少 paho-mqtt，正在安装...
    "!PY!" -m pip install paho-mqtt -q
)

if exist "__pycache__" (
    rmdir /s /q "__pycache__" 2>nul
)

echo.
echo ============================================================
echo   启动中... 浏览器将自动打开 http://127.0.0.1:%PORT%
echo   关闭本窗口即可停止服务
echo ============================================================
echo.

start "" "http://127.0.0.1:%PORT%/?t=%RANDOM%"
"!PY!" web_server.py 127.0.0.1 %PORT%

pause
