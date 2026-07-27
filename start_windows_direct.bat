@echo off
setlocal
cd /d %~dp0

if not exist venv\Scripts\python.exe (
    echo 未检测到 Python 虚拟环境。
    echo 请先双击运行 setup_windows_direct.bat
    pause
    exit /b 1
)

set /p LAN_ACCESS_PASSWORD=请输入同事访问密码:
if "%LAN_ACCESS_PASSWORD%"=="" (
    echo 访问密码不能为空。
    pause
    exit /b 1
)

set FORCE_PRODUCTION=1
set FORCE_LAN_LOGIN=1
set QMS_ENVIRONMENT=production
set QMS_INSTANCE_NAME=Windows LAN and public
set LAN_ALLOWED_DOMAIN=sainstore.com
set PUBLIC_BASE_URL=
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import ensure_runtime_secrets; print(ensure_runtime_secrets().get('cookie_secret',''))"`) do set COOKIE_SECRET=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import ensure_runtime_secrets; print(ensure_runtime_secrets().get('photo_api_token',''))"`) do set PHOTO_API_TOKEN=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('nas_url',''))"`) do set NAS_URL=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('nas_account',''))"`) do set NAS_ACCOUNT=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('nas_password',''))"`) do set NAS_PASSWORD=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('dingtalk_app_key',''))"`) do set DINGTALK_APP_KEY=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('dingtalk_app_secret',''))"`) do set DINGTALK_APP_SECRET=%%i
for /f "usebackq delims=" %%i in (`venv\Scripts\python.exe -c "from windows_runtime import load_runtime_config; print(load_runtime_config().get('dingtalk_agent_id',''))"`) do set DINGTALK_AGENT_ID=%%i
set SERVER_IP=
set QMS_ACCESS_URL=

for /f %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} ^| Select-Object -First 1 -ExpandProperty IPAddress)"') do set SERVER_IP=%%i
if not "%SERVER_IP%"=="" (
    set QMS_ACCESS_URL=http://%SERVER_IP%:8501
)

call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 激活虚拟环境失败。
    pause
    exit /b 1
)

echo.
echo 系统启动中...
echo 本机访问: http://localhost:8501
if not "%QMS_ACCESS_URL%"=="" (
    echo 同事访问: %QMS_ACCESS_URL%
) else (
    echo 同事访问: 请用本机 IP + 8501 端口
)
echo 登录方式: 公司邮箱 + 你刚输入的访问密码
echo.

where dws >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 当前 Win 主机未检测到 dws，钉钉消息会先写入 data\pending_notify，暂时无法即时发送。
    echo [建议] 先在这台主机完成 dws 登录，再重启系统。
)

echo 启动钉钉通知中继...
venv\Scripts\python.exe start_notify_relay.py

set SERVER_ADDRESS=0.0.0.0
set SERVER_PORT=8501
python unified_app.py

pause
