#!/usr/bin/env python3
"""
在 Windows 服务器上，把「同步看门狗」注册为长期运行计划任务（开机自启 + 崩溃自愈）。

原理：
  - 用系统计划任务（schtasks）每分钟触发一次 windows_sync_watcher.py；
  - 看门狗自身带「重复实例防护」：已在运行则瞬间退出，因此每分钟触发不会重复；
  - 看门狗退出/崩溃后，下一分钟计划任务会重新拉起它 -> 实现长期运行、崩溃自愈；
  - 看门狗启动时会自愈拉起品质系统服务，因此 Win 重启后服务也会自动恢复。

用法（在 Windows 服务器的 实验室 目录下，用 venv 的 python 执行）：
    python install_watcher_service.py --install     # 注册并立即启动
    python install_watcher_service.py --uninstall   # 移除计划任务
    python install_watcher_service.py --status      # 查看状态
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TASK_NAME = "QMS_SyncWatcher"


def _python_exe() -> Path:
    bundled = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
    if bundled.exists():
        return bundled
    return Path(sys.executable)


def install() -> int:
    if sys.platform != "win32":
        print("此脚本只能在 Windows 服务器上运行。请在 Win 服务器的 实验室 目录执行。")
        return 1

    py = _python_exe()
    watcher = SCRIPT_DIR / "windows_sync_watcher.py"
    if not watcher.exists():
        print(f"未找到看门狗脚本: {watcher}")
        return 1

    # 每分钟触发一次；看门狗自带重复防护，因此不会多开。
    # /RU SYSTEM 使任务在系统启动时（无需登录）即以最高权限运行。
    trigger = f'"{py}" "{watcher}"'
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/RU", "SYSTEM",
        "/SC", "MINUTE",
        "/MO", "1",
        "/TR", trigger,
        "/RL", "HIGHEST",
        "/F",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print("注册失败:")
        print(result.stderr.strip())
        return result.returncode

    # 立即启动一次（无需等下一分钟）
    run = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, text=True)
    if run.stdout.strip():
        print(run.stdout.strip())

    print(f"[OK] 已注册计划任务 [{TASK_NAME}]，看门狗现在长期运行（崩溃/重启均会自动恢复）。")
    print("     日志：data/runtime_logs/sync_watcher.log")
    print("     查看：python install_watcher_service.py --status")
    return 0


def uninstall() -> int:
    if sys.platform != "win32":
        print("此脚本只能在 Windows 服务器上运行。")
        return 1
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    out = (result.stdout or result.stderr).strip()
    if out:
        print(out)
    print(f"[OK] 已移除计划任务 [{TASK_NAME}]（看门狗不再自启，需手动 start_windows_background.py）。")
    return result.returncode


def status() -> int:
    if sys.platform != "win32":
        print("此脚本只能在 Windows 服务器上运行。")
        return 1
    result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True)
    out = (result.stdout or result.stderr).strip()
    print(out or "(任务不存在)")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="注册/移除 QMS 同步看门狗计划任务")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="注册并启动")
    group.add_argument("--uninstall", action="store_true", help="移除")
    group.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()

    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
