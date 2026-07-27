@echo off
setlocal
cd /d %~dp0

if not exist venv\Scripts\python.exe (
    echo 未检测到 Python 虚拟环境。
    echo 请先双击运行 setup_windows_direct.bat
    pause
    exit /b 1
)

venv\Scripts\python.exe windows_background_status.py
echo.
pause
