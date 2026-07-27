#!/usr/bin/env python3
"""
停止后台运行的品质系统与通知中继。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from windows_runtime import (
    MAINTENANCE_LOCK_FILE,
    RELAY_PID_FILE,
    SCRIPT_DIR,
    SERVER_META_FILE,
    SERVER_PID_FILE,
    PHOTO_API_META_FILE,
    PHOTO_API_PID_FILE,
    SYNC_WATCHER_PID_FILE,
    clear_pid,
    now_ts,
    read_pid,
    stop_pid,
    write_json,
)

def main(stop_watcher: bool = True) -> int:
    stopped_any = False
    server_pid = read_pid(SERVER_PID_FILE)
    if server_pid and stop_pid(server_pid):
        print(f"已停止品质系统后台进程: PID {server_pid}")
        stopped_any = True
    else:
        print("品质系统后台进程未运行")

    clear_pid(SERVER_PID_FILE)
    try:
        SERVER_META_FILE.unlink()
    except FileNotFoundError:
        pass

    photo_pid = read_pid(PHOTO_API_PID_FILE)
    if photo_pid and stop_pid(photo_pid):
        print(f"已停止手机拍照服务: PID {photo_pid}")
        stopped_any = True
    else:
        print("手机拍照服务未运行")
    clear_pid(PHOTO_API_PID_FILE)
    try:
        PHOTO_API_META_FILE.unlink()
    except FileNotFoundError:
        pass

    # 用户主动停机：写维护锁，看门狗不再自愈拉起
    if stop_watcher:
        try:
            write_json(MAINTENANCE_LOCK_FILE, {"stopped_at": now_ts()})
        except Exception:
            pass

    if stop_watcher:
        watcher_pid = read_pid(SYNC_WATCHER_PID_FILE)
        if watcher_pid and stop_pid(watcher_pid):
            print(f"已停止同步监听进程: PID {watcher_pid}")
            stopped_any = True
        clear_pid(SYNC_WATCHER_PID_FILE)

    python_exe = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    if stop_watcher:
        subprocess.run(
            [str(python_exe), str(SCRIPT_DIR / "start_notify_relay.py"), "--stop"],
            cwd=str(SCRIPT_DIR),
        )
        clear_pid(RELAY_PID_FILE)

    return 0 if stopped_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
