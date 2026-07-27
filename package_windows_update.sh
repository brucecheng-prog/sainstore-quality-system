#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/dist"
PACKAGE_NAME="quality-system-windows-update-$(date +%Y%m%d_%H%M%S)"
TMP_DIR="$(mktemp -d)"
TARGET_DIR="$TMP_DIR/$PACKAGE_NAME"

mkdir -p "$DIST_DIR"

# 更新包只包含代码和部署脚本，不覆盖服务器上的业务数据
rsync -a \
  --exclude '.git' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.cache' \
  --exclude '.workbuddy' \
  --exclude '.DS_Store' \
  --exclude '.deploy_token' \
  --exclude '.windows_sync.json' \
  --exclude 'dist' \
  --exclude 'data' \
  "$SCRIPT_DIR/" "$TARGET_DIR/"

mkdir -p "$TARGET_DIR/update_keep"
cat > "$TARGET_DIR/update_keep/README.txt" <<'EOF'
更新包不会包含 data 目录。

请把这个更新包解压到 Windows 主机上的旧项目目录中，覆盖代码文件即可。
不要删除原来的 data 文件夹。
不要删除原来的 SainStore实验室文件 文件夹。
EOF

(
  cd "$TMP_DIR"
  zip -qr "$DIST_DIR/$PACKAGE_NAME.zip" "$PACKAGE_NAME"
)

rm -rf "$TMP_DIR"

echo "已生成 Windows 更新包："
echo "$DIST_DIR/$PACKAGE_NAME.zip"
