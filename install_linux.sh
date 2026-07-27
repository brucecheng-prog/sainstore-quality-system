#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker，请先安装 Docker / Docker Compose。"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "未检测到 docker compose 插件，请先安装 docker-compose-plugin。"
  exit 1
fi

mkdir -p data
mkdir -p "SainStore实验室文件"

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${SERVER_IP}" ]]; then
  SERVER_IP="127.0.0.1"
fi

if [[ ! -f .env ]]; then
  COOKIE_SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  cat > .env <<EOF
HOST_PORT=8501
TZ=Asia/Shanghai
FORCE_PRODUCTION=1
PUBLIC_BASE_URL=http://${SERVER_IP}:8501
ALLOWED_DOMAINS=sainstore.com
COOKIE_SECRET=${COOKIE_SECRET}
COMPANY_LOGO_PATH=
LOCAL_ANALYTICS_DIR=
NAS_URL=
NAS_ACCOUNT=
NAS_PASSWORD=
NAS_BASE_PATH=
NAS_STAGING_PATH=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
EOF
  echo "已自动生成 .env，公网地址默认写成 http://${SERVER_IP}:8501"
fi

docker compose up -d --build

echo
echo "部署完成。"
echo "本机访问: http://localhost:8501"
echo "局域网访问: http://${SERVER_IP}:8501"
echo
echo "查看状态: docker compose ps"
echo "查看日志: docker compose logs -f"
