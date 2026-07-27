#!/usr/bin/env python3
"""
查看 Windows 后台运行状态。
"""

from __future__ import annotations

import json
import shutil

from dingtalk_app_client import get_app_push_status

from windows_runtime import (
    RELAY_PID_FILE,
    RUNTIME_CONFIG_FILE,
    SERVER_META_FILE,
    SERVER_PID_FILE,
    PHOTO_API_PID_FILE,
    PHOTO_API_META_FILE,
    SYNC_APPLIED_FILE,
    SYNC_REQUEST_FILE,
    SYNC_WATCHER_PID_FILE,
    load_runtime_config,
    port_is_open,
    read_json,
    read_pid,
)


def main() -> int:
    config = load_runtime_config()
    meta = read_json(SERVER_META_FILE)
    sync_applied = read_json(SYNC_APPLIED_FILE)
    server_pid = read_pid(SERVER_PID_FILE)
    photo_api_pid = read_pid(PHOTO_API_PID_FILE)
    relay_pid = read_pid(RELAY_PID_FILE)
    sync_watcher_pid = read_pid(SYNC_WATCHER_PID_FILE)

    payload = {
        "config_exists": RUNTIME_CONFIG_FILE.exists(),
        "password_configured": bool(config.get("lan_access_password")),
        "server_running": bool(server_pid),
        "legacy_photo_api_running": bool(photo_api_pid),
        "legacy_photo_api_pid": photo_api_pid,
        "server_pid": server_pid,
        "relay_running": bool(relay_pid),
        "relay_pid": relay_pid,
        "sync_watcher_running": bool(sync_watcher_pid),
        "sync_watcher_pid": sync_watcher_pid,
        "pending_sync_request": SYNC_REQUEST_FILE.exists(),
        "port_8501_open": port_is_open("127.0.0.1", 8501),
        "legacy_port_8800_open": port_is_open("127.0.0.1", 8800),
        "access_url": meta.get("access_url", ""),
        "dws_available": bool(shutil.which("dws")),
        "dingtalk_app": get_app_push_status(check_auth=True),
        "started_at": meta.get("started_at", ""),
        "version": meta.get("version", ""),
        "build_date": meta.get("build_date", ""),
        "sync_id": meta.get("sync_id", ""),
        "last_sync_restart": sync_applied,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
