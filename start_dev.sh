#!/bin/zsh
# 实验室品质系统 - 本地开发服务器一键启动（8502，自动登录）
# 用 setsid 完全脱离终端会话，避免被 IDE/会话切换带死。
# 用法：  ./start_dev.sh          启动
#         ./start_dev.sh stop     停止
#         ./start_dev.sh status    查看状态

set -e
PROJ="/Users/bruce/Desktop/Workbuddy_Bruce/实验室"
PY="$PROJ/venv/bin/python"
PORT=8502
LOG="$PROJ/.dev_8502.log"
PIDFILE="$PROJ/.dev_8502.pid"

cd "$PROJ"

# 关键：清空代理，避免 localhost 被系统代理拦截 / 子进程网络失败
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export NO_PROXY="localhost,127.0.0.1"
export no_proxy="localhost,127.0.0.1"

cmd="${1:-start}"

stop_server() {
  pkill -f "streamlit run main.py" 2>/dev/null && echo "已停止旧服务" || echo "无运行中的服务"
  rm -f "$PIDFILE"
}

status_server() {
  if lsof -iTCP:$PORT -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    echo "运行中：http://127.0.0.1:$PORT  (PID $(lsof -tiTCP:$PORT -sTCP:LISTEN))"
  else
    echo "未运行"
  fi
}

case "$cmd" in
  stop)   stop_server; exit 0 ;;
  status) status_server; exit 0 ;;
esac

# start
stop_server
sleep 1
# 用 Python launcher（start_new_session=True，等效 setsid）脱离会话进程组
"$PY" "$PROJ/dev_launcher.py"
echo "启动中，日志：$LOG"

# 等待就绪
for i in $(seq 1 20); do
  sleep 1
  if curl -s --noproxy '*' -o /dev/null -w "%{http_code}" --max-time 3 http://127.0.0.1:$PORT/ 2>/dev/null | grep -q "200"; then
    echo "✅ 就绪：http://127.0.0.1:$PORT"
    exit 0
  fi
done
echo "⚠️ 启动超时，请查看日志：$LOG"
tail -20 "$LOG"
exit 1
