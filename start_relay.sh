#!/bin/bash
# 品质系统通知中继完整启动脚本
# 启动 relay_server.py + cloudflared 隧道
# 使用: bash start_relay.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELAY_LOG="/tmp/relay_server.log"
CF_LOG="/tmp/cloudflared.log"
RELAY_URL="$SCRIPT_DIR/data/relay_url.txt"
GIST_ID="ad7c44d00f1c191a2a8a0ce32e243857"

echo "🚀 启动品质系统通知中继..."

# 1. 启动 relay_server
pgrep -f "relay_server.py" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   relay_server 已在运行"
else
    cd "$SCRIPT_DIR"
    nohup /Users/bruce/.workbuddy/binaries/python/envs/default/bin/python relay_server.py > "$RELAY_LOG" 2>&1 &
    sleep 2
    if pgrep -f "relay_server.py" > /dev/null 2>&1; then
        echo "   ✅ relay_server 已启动"
    else
        echo "   ❌ relay_server 启动失败, 查看日志: $RELAY_LOG"
    fi
fi

# 2. 启动 cloudflared 隧道
pgrep -f "cloudflared tunnel" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   cloudflared 隧道已在运行"
    if [ -f "$RELAY_URL" ]; then
        CURRENT_URL=$(cat $RELAY_URL)
        echo "   🌐 公网地址: $CURRENT_URL"
        # 确保 Gist 同步到最新
        echo "$CURRENT_URL" | gh gist edit "$GIST_ID" --filename "relay_url.txt" - 2>/dev/null
    fi
else
    cd "$SCRIPT_DIR"
    nohup cloudflared tunnel --url http://localhost:8765 > "$CF_LOG" 2>&1 &
    echo "   ⏳ 等待隧道建立..."
    for i in $(seq 1 15); do
        sleep 2
        TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
        if [ -n "$TUNNEL_URL" ]; then
            echo "$TUNNEL_URL" > "$RELAY_URL"
            echo "   🌐 公网地址: $TUNNEL_URL"
            # 自动更新 GitHub Gist (公网服务器从这里读取 relay URL)
            echo "   📡 更新 Gist 公告板..."
            echo "$TUNNEL_URL" | gh gist edit "$GIST_ID" --filename "relay_url.txt" - 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "   ✅ Gist 已更新，公网服务器自动识别"
            else
                echo "   ⚠️  Gist 更新失败 (网络问题？公网服务器将使用上次缓存的 URL)"
            fi
            break
        fi
    done
    if [ ! -f "$RELAY_URL" ]; then
        echo "   ⚠️ 隧道建立超时，查看日志: $CF_LOG"
        echo "   手动启动: cloudflared tunnel --url http://localhost:8765"
    fi
fi

# 3. 验证
curl -s "http://localhost:8765/health" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ 中继服务健康检查通过"
else
    echo "   ❌ 中继服务无响应"
fi

echo ""
echo "=============================="
echo "   中继启动完成"
echo "   本地: http://localhost:8765/health"
if [ -f "$RELAY_URL" ]; then
    echo "   公网: $(cat $RELAY_URL)/health"
fi
echo "=============================="
