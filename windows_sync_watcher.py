#!/usr/bin/env python3
"""
监听 Mac -> Windows 同步请求，收到请求后自动重启品质系统后台服务。

同时作为「长期运行看门狗」：
  - 启动即自愈：若服务未运行则拉起（配合计划任务开机自启，实现重启自愈）
  - 存活巡检：服务意外退出且非维护状态，自动重启（5 分钟冷却防风暴）
  - 同步热重启：收到 Mac 推送的 windows_sync_request.json 时重启以加载新代码
  - 重复实例防护：已有看门狗在跑则本实例直接退出

维护约定：data/maintenance.lock 存在时，看门狗不自愈拉起（用于停机维护）。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from stop_windows_background import main as stop_background
from windows_runtime import (
    LOG_DIR,
    MAINTENANCE_LOCK_FILE,
    SERVER_META_FILE,
    SCRIPT_DIR,
    SERVER_PID_FILE,
    SYNC_APPLIED_FILE,
    SYNC_REQUEST_FILE,
    SYNC_WATCHER_PID_FILE,
    clear_pid,
    now_ts,
    port_is_open,
    read_json,
    read_pid,
    wait_for_port_state,
    write_json,
    write_pid,
)

LOG_FILE = LOG_DIR / "sync_watcher.log"
PORT = 8501
LIVENESS_INTERVAL = 60       # 每 60 秒巡检一次服务存活
LIVENESS_COOLDOWN = 300      # 自愈最小间隔 5 分钟，防止重启风暴
WATCHER_HEARTBEAT = LOG_DIR / "watcher_heartbeat"  # 心跳文件：Mac 侧读其 mtime 即可确认看门狗仍在运行
WATCHER_SELF_MTIME = SCRIPT_DIR / ".watcher_self_mtime"  # 记录看门狗脚本 mtime，用于跨版本强制接管


def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync_watcher")
    if not logger.handlers:
        try:
            handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        except Exception:
            pass
    return logger


def _get_python_executable() -> Path:
    bundled = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
    if bundled.exists():
        return bundled
    return Path(sys.executable)


def _pid_alive(pid: int) -> bool:
    """Windows 下检查指定 PID 的进程是否真实存活。

    解决经典『stale PID 文件』陷阱：若看门狗崩溃但 PID 文件残留，
    新实例若仅凭 PID 文件判定『已在运行』会直接退出，导致看门狗彻底死透、
    服务挂了也没人拉起。此处用 kernel32.OpenProcess 实测进程是否存在。
    """
    if not pid:
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        # 回退：os.kill(pid, 0) 在 Windows 上进程不存在会抛 OSError
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False


def _already_running(logger: logging.Logger) -> bool:
    """重复实例防护 + 陈旧 PID 清理（无跨版本强杀，避免竞态）。

    - read_pid 已用 pid_is_running 过滤，读到的 PID 必为存活 -> 正常退出（避免多开）
    - 若 PID 文件记录进程已死（stale PID）-> 清理后接管，确保崩溃后自愈
    代码热更新由『处理完 sync 请求后看门狗自杀、计划任务拉起新版本』保证，
    不在此处跨版本强杀（强杀会引发多实例竞态，反而让看门狗失稳）。
    """
    pid = read_pid(SYNC_WATCHER_PID_FILE)
    if pid and pid != os.getpid():
        if _pid_alive(pid):
            logger.info("看门狗已在运行 (PID %s)，本实例退出", pid)
            return True
        # PID 文件残留（进程已死）——清理并接管，确保崩溃后仍能自愈
        logger.warning("发现残留看门狗 PID 文件 (%s)，对应进程已不存在，清理并接管", pid)
        try:
            clear_pid(SYNC_WATCHER_PID_FILE)
        except Exception:
            pass
    return False


def _meta_matches_request(request_payload: dict) -> bool:
    meta = read_json(SERVER_META_FILE)
    if not meta:
        return False
    expected_sync_id = str(request_payload.get("sync_id", "")).strip()
    expected_version = str(request_payload.get("version", "")).strip()
    expected_build_date = str(request_payload.get("build_date", "")).strip()

    if expected_sync_id and str(meta.get("sync_id", "")).strip() != expected_sync_id:
        return False
    if expected_version and str(meta.get("version", "")).strip() != expected_version:
        return False
    if expected_build_date and str(meta.get("build_date", "")).strip() != expected_build_date:
        return False
    return True


def _restart_server(request_payload: dict) -> tuple[bool, str, int]:
    stop_background(stop_watcher=False)
    stopped_cleanly = wait_for_port_state("127.0.0.1", 8501, want_open=False, timeout=25)

    python_exe = _get_python_executable()
    attempt_messages: list[str] = []

    for attempt in range(1, 3):
        result = subprocess.run(
            [str(python_exe), str(SCRIPT_DIR / "start_windows_background.py")],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "启动失败").strip()
            attempt_messages.append(f"第 {attempt} 次启动失败: {error}")
            continue

        port_ready = wait_for_port_state("127.0.0.1", 8501, want_open=True, timeout=35)
        version_ready = _meta_matches_request(request_payload)
        if port_ready and version_ready:
            output = (result.stdout or "重启完成").strip()
            if attempt == 1 and stopped_cleanly:
                return True, output, attempt
            suffix = "（冷重启校验通过）" if stopped_cleanly else "（端口关闭超时后补启成功）"
            return True, f"{output} {suffix}", attempt

        attempt_messages.append(
            f"第 {attempt} 次启动后校验未通过: "
            f"port_ready={port_ready}, version_ready={version_ready}"
        )
        stop_background(stop_watcher=False)
        wait_for_port_state("127.0.0.1", 8501, want_open=False, timeout=20)

    if not stopped_cleanly:
        attempt_messages.insert(0, "旧进程端口关闭超时，已尝试强制切换")
    return False, " | ".join(attempt_messages) or "后台进程重启失败", 2


def _apply_sync_request(logger: logging.Logger) -> None:
    payload = read_json(SYNC_REQUEST_FILE)
    if not payload:
        try:
            SYNC_REQUEST_FILE.unlink()
        except FileNotFoundError:
            pass
        return

    logger.info(
        "收到同步请求: sync_id=%s version=%s build=%s changed=%s",
        payload.get("sync_id"), payload.get("version"),
        payload.get("build_date"), payload.get("changed_count"),
    )
    server_pid = read_pid(SERVER_PID_FILE)
    success, message, attempts = _restart_server(payload)
    applied_payload = {
        "requested_at": payload.get("requested_at", ""),
        "sync_id": payload.get("sync_id", ""),
        "version": payload.get("version", ""),
        "build_date": payload.get("build_date", ""),
        "source_machine": payload.get("source_machine", ""),
        "changed_count": payload.get("changed_count", 0),
        "target_path": payload.get("target_path", ""),
        "handled_at": now_ts(),
        "previous_server_pid": server_pid,
        "attempts": attempts,
        "success": success,
        "message": message,
    }
    write_json(SYNC_APPLIED_FILE, applied_payload)
    try:
        SYNC_REQUEST_FILE.unlink()
    except FileNotFoundError:
        pass
    logger.info("同步请求处理完成: success=%s attempts=%s msg=%s", success, attempts, message)


def _is_maintenance() -> bool:
    return MAINTENANCE_LOCK_FILE.exists()


def _ensure_server_alive(logger: logging.Logger, last_restart: dict) -> None:
    """看门狗存活巡检：服务未运行且非维护态则自愈拉起。"""
    if _is_maintenance():
        logger.debug("维护锁存在，跳过存活巡检")
        return
    if SYNC_REQUEST_FILE.exists():
        return  # 同步请求交由 _apply_sync_request 处理
    pid = read_pid(SERVER_PID_FILE)
    if pid:
        return  # 服务在运行
    if port_is_open("127.0.0.1", PORT):
        return  # 端口已开（可能 PID 文件滞后）
    now = time.time()
    if now - last_restart.get("ts", 0.0) < LIVENESS_COOLDOWN:
        return  # 冷却期内不重复拉起
    logger.warning("检测到服务未运行，触发自愈启动")
    try:
        subprocess.run(
            [str(_get_python_executable()), str(SCRIPT_DIR / "start_windows_background.py")],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        last_restart["ts"] = now
        logger.info("自愈启动已发起")
    except Exception as exc:
        logger.error("自愈启动失败: %s", exc)


def watch_loop(interval: int = 5) -> int:
    logger = _setup_logging()
    if _already_running(logger):
        return 0
    write_pid(SYNC_WATCHER_PID_FILE, os.getpid())
    try:
        WATCHER_SELF_MTIME.write_text(str(Path(__file__).resolve().stat().st_mtime))
    except Exception:
        pass
    logger.info("同步看门狗已启动 (PID %s)", os.getpid())

    last_restart = {"ts": 0.0}
    _ensure_server_alive(logger, last_restart)  # 启动即自愈一次

    ticks = 0
    watcher_script = Path(__file__).resolve()
    watcher_start_mtime = watcher_script.stat().st_mtime
    while True:
        try:
            if SYNC_REQUEST_FILE.exists():
                _apply_sync_request(logger)
            ticks += 1
            if ticks * interval >= LIVENESS_INTERVAL:
                ticks = 0
                # 心跳：标记看门狗仍在运行（Mac 侧读 watcher_heartbeat mtime 即可确认存活）
                try:
                    WATCHER_HEARTBEAT.touch()
                    srv_pid = read_pid(SERVER_PID_FILE)
                    logger.info("存活巡检 OK（服务 PID=%s）", srv_pid or "未知")
                except Exception:
                    pass
                _ensure_server_alive(logger, last_restart)
        except Exception as exc:
            logger.exception("看门狗循环异常: %s", exc)
            write_json(
                SYNC_APPLIED_FILE,
                {"handled_at": now_ts(), "success": False, "message": str(exc)},
            )
            try:
                SYNC_REQUEST_FILE.unlink()
            except FileNotFoundError:
                pass
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(watch_loop())
