#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d "venv" ]]; then
  echo "未找到 venv，请先准备好本地环境。"
  exit 1
fi

export FORCE_PRODUCTION=1

if [[ -n "${1:-}" ]]; then
  export PUBLIC_BASE_URL="${1%/}"
  export OAUTH_REDIRECT_URI="${1%/}"
  echo "使用固定公网地址: $PUBLIC_BASE_URL"
else
  echo "未提供固定公网地址，将依赖请求头自动识别。"
  echo "如果要走 Google OAuth，建议传入固定地址，例如:"
  echo "  ./start_public.sh https://qc.example.com"
fi

export SERVER_ADDRESS=0.0.0.0
export SERVER_PORT=8501

exec ./venv/bin/python unified_app.py
