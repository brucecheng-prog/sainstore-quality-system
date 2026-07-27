#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d "venv" ]]; then
  echo "未找到 venv，请先准备好本地环境。"
  exit 1
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [[ -z "$LAN_IP" ]]; then
  LAN_IP="请手动查看本机IP"
fi

echo "请输入局域网共享访问密码（同事登录会用到）："
read -s LAN_PASSWORD
echo

if [[ -z "$LAN_PASSWORD" ]]; then
  echo "访问密码不能为空。"
  exit 1
fi

export FORCE_PRODUCTION=1
export FORCE_LAN_LOGIN=1
export LAN_ALLOWED_DOMAIN="sainstore.com"
export LAN_ACCESS_PASSWORD="$LAN_PASSWORD"
if [[ "$LAN_IP" != "请手动查看本机IP" ]]; then
  export SERVER_IP="$LAN_IP"
  export QMS_ACCESS_URL="http://$LAN_IP:8501"
fi

echo "局域网启动中..."
echo "本机访问: http://localhost:8501"
echo "同事访问: http://$LAN_IP:8501"
echo "登录方式: 公司邮箱 + 共享访问密码"

export SERVER_ADDRESS=0.0.0.0
export SERVER_PORT=8501

exec ./venv/bin/python unified_app.py
