@echo off
setlocal
cd /d %~dp0

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_LAUNCHER=py -3.11"
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo 未检测到 Python。请先安装 Python 3.11，并勾选 Add Python to PATH。
        pause
        exit /b 1
    )
    set "PY_LAUNCHER=python"
)

if not exist venv (
    echo 正在创建虚拟环境...
    call %PY_LAUNCHER% -m venv venv
    if %errorlevel% neq 0 (
        echo 创建虚拟环境失败。
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 激活虚拟环境失败。
    pause
    exit /b 1
)

python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo 升级 pip 失败。
    pause
    exit /b 1
)

pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo 安装依赖失败。
    pause
    exit /b 1
)

echo.
echo Python 环境准备完成。
echo 下一步请双击 start_windows_direct.bat 启动系统。
pause
