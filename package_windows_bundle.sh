#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/dist"
BUNDLE_NAME="quality-system-windows-bundle-$(date +%Y%m%d_%H%M%S)"
TMP_DIR="$(mktemp -d)"
TARGET_DIR="$TMP_DIR/$BUNDLE_NAME"

mkdir -p "$DIST_DIR"

rsync -a \
  --exclude '.git' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.cache' \
  --exclude '.workbuddy' \
  --exclude '.DS_Store' \
  --exclude '.deploy_token' \
  --exclude '.windows_sync.json' \
  --exclude 'data/backups' \
  --exclude 'data/*.log' \
  --exclude 'dist' \
  "$SCRIPT_DIR/" "$TARGET_DIR/"

(
  cd "$TMP_DIR"
  zip -qr "$DIST_DIR/$BUNDLE_NAME.zip" "$BUNDLE_NAME"
)

rm -rf "$TMP_DIR"

echo "已生成 Windows 部署压缩包："
echo "$DIST_DIR/$BUNDLE_NAME.zip"
