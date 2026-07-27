#!/usr/bin/env python3
"""
后台启动 notify_relay 监控，避免 Win 主机上的待发送消息长期积压。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from windows_runtime import (
    RELAY_PID_FILE,
    clear_pid,
    pid_is_running,
    read_pid,
    write_pid,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def _pid_is_running(pid: int) -> bool:
    return pid_is_running(pid)


def _get_background_python_executable() -> Path:
    bundled = SCRIPT_DIR / "venv" / "Scripts" / "pythonw.exe"
    if bundled.exists():
        return bundled
    return Path(sys.executable)


def _load_existing_pid() -> int | None:
    return read_pid(RELAY_PID_FILE)


def _stop_existing_pid() -> int | None:
    existing_pid = _load_existing_pid()
    if not existing_pid:
        clear_pid(RELAY_PID_FILE)
        return None

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(existing_pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
    else:
        try:
            os.kill(existing_pid, 15)
        except OSError:
            pass
    clear_pid(RELAY_PID_FILE)
    return existing_pid


def main() -> int:
    if "--stop" in sys.argv:
        stopped_pid = _stop_existing_pid()
        if stopped_pid:
            print(f"notify_relay 已停止: PID {stopped_pid}")
        else:
            print("notify_relay 未运行")
        return 0

    if "--status" in sys.argv:
        existing_pid = _load_existing_pid()
        if existing_pid:
            print(f"notify_relay 运行中: PID {existing_pid}")
        else:
            print("notify_relay 未运行")
        return 0

    existing_pid = _load_existing_pid()
    if existing_pid:
        print(f"notify_relay 已在后台运行: PID {existing_pid}")
        return 0

    python_exe = _get_background_python_executable()
    relay_script = SCRIPT_DIR / "notify_relay.py"
    cmd = [str(python_exe), str(relay_script), "--watch", "--interval", "30"]

    kwargs = {
        "cwd": str(SCRIPT_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }

    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    write_pid(RELAY_PID_FILE, proc.pid)
    print(f"notify_relay 已启动: PID {proc.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
