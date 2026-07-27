#!/bin/bash
# 品质系统 Streamlit 启动脚本
# 由 launchd 在开机时自动调用

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STDERR_LOG="$SCRIPT_DIR/data/streamlit_stderr.log"
STDOUT_LOG="$SCRIPT_DIR/data/streamlit_stdout.log"
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"

# 如果已经在运行，跳过
if pgrep -f "python.*unified_app.py" > /dev/null 2>&1; then
    echo "[$(date)] Unified QMS already running" >> "$STDOUT_LOG"
    exit 0
fi

cd "$SCRIPT_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "[$(date)] Missing virtualenv python: $PYTHON_BIN" >> "$STDERR_LOG"
    exit 1
fi

exec "$PYTHON_BIN" unified_app.py \
    >> "$STDOUT_LOG" 2>> "$STDERR_LOG"
