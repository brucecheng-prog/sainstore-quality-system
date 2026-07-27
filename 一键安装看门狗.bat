@echo off
chcp 65001 >nul 2>&1
title QMS 看门狗安装 + 服务重启（一键）
setlocal
set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 未找到 %PY%
    echo 请确认 venv 环境已安装，或把本文件里的 PY 改成 python
    pause
    exit /b 1
)
cd /d "%~dp0"
echo 工作目录: %CD%
echo.
echo [1/4] 停止旧服务和看门狗...
"%PY%" stop_windows_background.py
echo.
echo [2/4] 独立初始化数据库 schema（确保 operation_log 审计表创建）...
"%PY%" init_db_once.py
if errorlevel 1 (
    echo [警告] 独立初始化返回非零，将交由启动流程再试一次。
) else (
    echo [OK] operation_log 审计表已确认存在。
)
echo.
echo [3/4] 启动新服务（启动前会再次确保 schema 最新）...
"%PY%" start_windows_background.py
if errorlevel 1 (
    echo.
    echo [失败] 服务启动失败，请查看上方错误。
    pause
    exit /b 1
)
echo [OK] 新服务已启动
echo.
echo [4/4] 注册看门狗计划任务（开机自启 + 崩溃自愈）...
"%PY%" install_watcher_service.py --install
echo.
echo =========================================
echo 完成！验证命令：
echo   "%PY%" install_watcher_service.py --status
echo 日志位置：
echo   data\runtime_logs\sync_watcher.log
echo =========================================
pause
