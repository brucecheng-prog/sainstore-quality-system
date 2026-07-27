#!/usr/bin/env python3
"""
Windows 本地运行时辅助函数。
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
LOG_DIR = DATA_DIR / "runtime_logs"
RUNTIME_CONFIG_FILE = DATA_DIR / "windows_runtime.json"
SERVER_PID_FILE = DATA_DIR / "qms_server.pid"
SERVER_META_FILE = DATA_DIR / "qms_server_meta.json"
PHOTO_API_PID_FILE = DATA_DIR / "photo_api.pid"
PHOTO_API_META_FILE = DATA_DIR / "photo_api_meta.json"
RELAY_PID_FILE = DATA_DIR / "notify_relay.pid"
SYNC_WATCHER_PID_FILE = DATA_DIR / "sync_watcher.pid"
SYNC_REQUEST_FILE = DATA_DIR / "windows_sync_request.json"
SYNC_APPLIED_FILE = DATA_DIR / "windows_sync_applied.json"
REMOTE_SYNC_META_FILE = SCRIPT_DIR / ".last_mac_sync.json"
MAINTENANCE_LOCK_FILE = DATA_DIR / "maintenance.lock"  # 存在时看门狗不自愈拉起服务（停机维护用）


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_runtime_config() -> dict:
    if not RUNTIME_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_runtime_config(config: dict) -> dict:
    ensure_runtime_dirs()
    payload = dict(config or {})
    payload["updated_at"] = now_ts()
    RUNTIME_CONFIG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def ensure_runtime_secrets(config: dict | None = None) -> dict:
    """Return a persisted production-safe runtime configuration.

    The runtime file lives in ``data/`` and is deliberately excluded from
    Mac-to-Windows code sync.  This keeps server credentials stable across
    deployments while allowing legacy installations to migrate away from the
    historical hard-coded cookie value.
    """
    payload = dict(config or load_runtime_config())
    changed = False
    legacy_cookie = "windows-direct-qms"
    if not str(payload.get("cookie_secret", "")).strip() or payload.get("cookie_secret") == legacy_cookie:
        payload["cookie_secret"] = secrets.token_urlsafe(48)
        changed = True
    if not str(payload.get("photo_api_token", "")).strip():
        payload["photo_api_token"] = secrets.token_urlsafe(32)
        changed = True
    if changed:
        payload = save_runtime_config(payload)
    return payload


def guess_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith(("127.", "169.254.")):
            return ip
    except Exception:
        pass
    return ""


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stdout or "").strip()
            return bool(output) and "INFO:" not in output.upper()
        except Exception:
            return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid if pid_is_running(pid) else None


def write_pid(pid_file: Path, pid: int) -> None:
    ensure_runtime_dirs()
    pid_file.write_text(str(pid), encoding="utf-8")


def clear_pid(pid_file: Path) -> None:
    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def stop_pid(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def pids_listening_on_port(port: int) -> list[int]:
    if port <= 0:
        return []

    if os.name != "nt":
        return []

    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        text = result.stdout or ""
    except Exception:
        return []

    pids: list[int] = []
    seen: set[int] = set()
    needle = f":{int(port)}"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "LISTENING" not in line.upper():
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid_text = parts[-1]
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid > 0 and pid not in seen:
            seen.add(pid)
            pids.append(pid)
    return pids


def stop_processes_on_port(port: int, exclude_pids: set[int] | None = None) -> list[int]:
    exclude = set(exclude_pids or set())
    stopped: list[int] = []
    for pid in pids_listening_on_port(port):
        if pid in exclude:
            continue
        try:
            if stop_pid(pid):
                stopped.append(pid)
        except Exception:
            pass
    return stopped


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict) -> None:
    ensure_runtime_dirs()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def port_is_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port_state(host: str, port: int, want_open: bool, timeout: float = 20.0, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_open(host, port) == want_open:
            return True
        time.sleep(interval)
    return port_is_open(host, port) == want_open
