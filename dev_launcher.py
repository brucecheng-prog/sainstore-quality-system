#!/usr/bin/env python3
"""实验室系统 8502 开发服务器守护启动器。
用 start_new_session=True（内部 setsid）让 streamlit 进程成为独立会话领导者，
脱离父进程/IDE 会话进程组，避免会话切换时被 SIGHUP/SIGTERM 带死。
"""
import os
import sys
import subprocess

PROJ = "/Users/bruce/Desktop/Workbuddy_Bruce/实验室"
PY = os.path.join(PROJ, "venv/bin/python")
LOG = os.path.join(PROJ, ".dev_8502.log")
PIDFILE = os.path.join(PROJ, ".dev_8502.pid")
PORT = "8502"

# 清空代理，避免 localhost 被系统代理拦截 / 子进程网络失败
env = os.environ.copy()
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    env.pop(k, None)
env["NO_PROXY"] = "localhost,127.0.0.1"
env["no_proxy"] = "localhost,127.0.0.1"
env["QMS_ENVIRONMENT"] = "development"
env["QMS_INSTANCE_NAME"] = "Manual developer"

logf = open(LOG, "ab")
proc = subprocess.Popen(
    [PY, "-m", "streamlit", "run", "main.py",
     "--server.port", PORT, "--server.address", "::",
     "--server.headless", "true", "--browser.gatherUsageStats", "false"],
    cwd=PROJ,
    stdout=logf,
    stderr=logf,
    stdin=subprocess.DEVNULL,
    start_new_session=True,   # 关键：等效 setsid，脱离会话
    env=env,
)
with open(PIDFILE, "w") as f:
    f.write(str(proc.pid))
print(f"launched pid {proc.pid}")
