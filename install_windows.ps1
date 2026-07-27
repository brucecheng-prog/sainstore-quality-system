$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ScriptDir "data"
$SourceDir = Join-Path $ScriptDir "SainStore实验室文件"
$EnvFile = Join-Path $ScriptDir ".env"

Set-Location $ScriptDir

function Get-ServerIp {
    try {
        $ipList = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and
            $_.IPAddress -notlike "169.254.*"
        }
        foreach ($item in $ipList) {
            if ($item.IPAddress) {
                return $item.IPAddress
            }
        }
    } catch {
    }
    return "127.0.0.1"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "未检测到 Docker。请先安装并启动 Docker Desktop。" -ForegroundColor Red
    exit 1
}

try {
    docker compose version | Out-Null
} catch {
    Write-Host "未检测到 docker compose。请确认 Docker Desktop 已成功安装并启动。" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null

$serverIp = Get-ServerIp

if (-not (Test-Path $EnvFile)) {
    $cookieSecret = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $envLines = @(
        "HOST_PORT=8501"
        "TZ=Asia/Shanghai"
        "FORCE_PRODUCTION=1"
        "PUBLIC_BASE_URL=http://$($serverIp):8501"
        "ALLOWED_DOMAINS=sainstore.com"
        "COOKIE_SECRET=$cookieSecret"
        "COMPANY_LOGO_PATH="
        "LOCAL_ANALYTICS_DIR="
        "NAS_URL="
        "NAS_ACCOUNT="
        "NAS_PASSWORD="
        "NAS_BASE_PATH="
        "NAS_STAGING_PATH="
        "GOOGLE_CLIENT_ID="
        "GOOGLE_CLIENT_SECRET="
    )
    Set-Content -Path $EnvFile -Value $envLines -Encoding UTF8
    Write-Host "已自动生成 .env，默认地址为 http://$($serverIp):8501" -ForegroundColor Cyan
}

Write-Host "开始构建并启动系统，请稍等..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host ""
Write-Host "部署完成。" -ForegroundColor Green
Write-Host "本机访问: http://localhost:8501" -ForegroundColor Green
Write-Host "局域网访问: http://$($serverIp):8501" -ForegroundColor Green
Write-Host ""
Write-Host "查看状态: docker compose ps" -ForegroundColor Green
Write-Host "查看日志: docker compose logs -f" -ForegroundColor Green
