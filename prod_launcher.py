#!/usr/bin/env python3
"""实验室系统 8501 生产入口守护启动器（unified_app.py，uvicorn）。
用 start_new_session=True（等效 setsid）让进程成为独立会话领导者，
脱离父进程/IDE 会话进程组，避免会话切换时被带死。
绑定 :: (IPv6 双栈)，使 localhost(IPv6 ::1) 与 127.0.0.1 均可访问。
"""
import os
import subprocess

PROJ = "/Users/bruce/Desktop/Workbuddy_Bruce/实验室"
PY = os.path.join(PROJ, "venv/bin/python")
LOG = os.path.join(PROJ, ".prod_8501.log")
PIDFILE = os.path.join(PROJ, ".prod_8501.pid")
PORT = "8501"

# 清空代理，避免 localhost 被系统代理拦截 / 子进程网络失败
env = os.environ.copy()
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    env.pop(k, None)
env["NO_PROXY"] = "localhost,127.0.0.1"
env["no_proxy"] = "localhost,127.0.0.1"
# 双栈监听：让 localhost(IPv6 ::1) 与 127.0.0.1 都能连
env["SERVER_ADDRESS"] = "::"
env["SERVER_PORT"] = PORT

logf = open(LOG, "ab")
proc = subprocess.Popen(
    [PY, "unified_app.py"],
    cwd=PROJ,
    stdout=logf,
    stderr=logf,
    stdin=subprocess.DEVNULL,
    start_new_session=True,   # 关键：等效 setsid，脱离会话
    env=env,
)
with open(PIDFILE, "w") as f:
    f.write(str(proc.pid))
print(f"launched pid {proc.pid} (8501, dual-stack ::)")
