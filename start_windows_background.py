#!/usr/bin/env python3
"""
后台启动品质系统，不依赖一直打开的命令窗口。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from windows_runtime import (
    LOG_DIR,
    MAINTENANCE_LOCK_FILE,
    REMOTE_SYNC_META_FILE,
    SYNC_WATCHER_PID_FILE,
    SCRIPT_DIR,
    SERVER_META_FILE,
    SERVER_PID_FILE,
    ensure_runtime_dirs,
    guess_lan_ip,
    ensure_runtime_secrets,
    load_runtime_config,
    now_ts,
    read_json,
    read_pid,
    stop_processes_on_port,
    write_json,
    write_pid,
)
from dingtalk_app_client import get_app_push_status
from version import BUILD_DATE, VERSION


REQUIREMENTS_APPLIED_FILE = LOG_DIR / "requirements_applied.json"
MIN_STREAMLIT_VERSION = (1, 59, 0)
SERVER_PORT = 8501


def _clear_project_pycache() -> None:
    """
    清理项目源码目录下的 __pycache__，避免 Win 同步后继续加载旧 pyc。

    注意：
    - 只清理项目源码自身的缓存；
    - 不碰 venv/site-packages，避免影响第三方包。
    """
    targets = [
        SCRIPT_DIR / "__pycache__",
        SCRIPT_DIR / "_online_report_component.pyc",
        SCRIPT_DIR / "_online_report_component_v3.pyc",
        SCRIPT_DIR / "_pages" / "__pycache__",
        SCRIPT_DIR / "pages" / "__pycache__",
        SCRIPT_DIR / "_components" / "__pycache__",
        SCRIPT_DIR / "components" / "__pycache__",
    ]
    for path in targets:
        try:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


def _purge_obsolete_project_artifacts() -> None:
    """
    删除已明确废弃、且不应继续参与运行解析的旧产物。

    当前明确清理：
    - 旧版在线报告组件目录 `_components/online_report`
    - 已被 v3 组件完全替代的旧 Python 声明与生成脚本
    """
    targets = [
        SCRIPT_DIR / "_components" / "online_report",
        SCRIPT_DIR / "_online_report_component.py",
        SCRIPT_DIR / "build_online_report_component.py",
    ]
    for path in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except Exception:
            pass


def _parse_version_tuple(raw: str) -> tuple[int, ...]:
    parts = []
    for token in str(raw).split("."):
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _requirements_state() -> dict:
    return read_json(REQUIREMENTS_APPLIED_FILE)


def _streamlit_too_old(python_exe: Path) -> tuple[bool, str]:
    try:
        raw = subprocess.run(
            [str(python_exe), "-c", "from importlib.metadata import version; print(version('streamlit'))"],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
        ver = (raw.stdout or raw.stderr or "").strip()
        if raw.returncode != 0 or not ver:
            return True, ver or "unknown"
        return _parse_version_tuple(ver) < MIN_STREAMLIT_VERSION, ver
    except Exception:
        return True, "unknown"


def _needs_requirements_apply(python_exe: Path) -> tuple[bool, str]:
    req_file = SCRIPT_DIR / "requirements.txt"
    if not req_file.exists():
        return False, "missing requirements.txt"

    state = _requirements_state()
    req_mtime = int(req_file.stat().st_mtime)
    bad_streamlit, raw_ver = _streamlit_too_old(python_exe)
    if bad_streamlit:
        return True, f"streamlit={raw_ver}"

    # PDF 审核预览至少需要一套可用的渲染引擎。仅比较 requirements.txt
    # 时间戳不够，旧环境可能记录过依赖已安装但实际包已损坏。
    try:
        probe = subprocess.run(
            [str(python_exe), "-c", "import pypdfium2, fitz"],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            return True, "PDF renderer missing (pypdfium2/fitz)"
    except Exception as exc:
        return True, f"PDF renderer probe failed: {exc}"

    if state.get("requirements_mtime") != req_mtime:
        return True, "requirements changed"

    if state.get("python") != str(python_exe):
        return True, "python changed"

    return False, raw_ver


def _ensure_runtime_dependencies(python_exe: Path, env: dict) -> tuple[bool, str]:
    need, reason = _needs_requirements_apply(python_exe)
    if not need:
        return True, f"requirements ok ({reason})"

    req_file = SCRIPT_DIR / "requirements.txt"
    steps = [
        [str(python_exe), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python_exe), "-m", "pip", "install", "-r", str(req_file)],
    ]
    outputs = []
    for cmd in steps:
        res = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        text = (res.stdout or res.stderr or "").strip()
        outputs.append(text[:500])
        if res.returncode != 0:
            return False, f"{' '.join(cmd)} failed: {text[:500]}"

    write_json(
        REQUIREMENTS_APPLIED_FILE,
        {
            "applied_at": now_ts(),
            "requirements_mtime": int(req_file.stat().st_mtime),
            "python": str(python_exe),
            "reason": reason,
            "steps": outputs,
        },
    )
    return True, f"requirements upgraded ({reason})"


def _get_python_executable() -> Path:
    bundled = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
    if bundled.exists():
        return bundled
    return Path(sys.executable)


def _get_background_python_executable() -> Path:
    bundled = SCRIPT_DIR / "venv" / "Scripts" / "pythonw.exe"
    if bundled.exists():
        return bundled
    return _get_python_executable()


def _ensure_sync_watcher(background_python: Path) -> None:
    watcher_pid = read_pid(SYNC_WATCHER_PID_FILE)
    if watcher_pid:
        return

    kwargs = {
        "cwd": str(SCRIPT_DIR),
        "env": os.environ.copy(),
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

    proc = subprocess.Popen(
        [str(background_python), str(SCRIPT_DIR / "windows_sync_watcher.py")],
        **kwargs,
    )
    write_pid(SYNC_WATCHER_PID_FILE, proc.pid)


def _force_release_server_port() -> list[int]:
    """
    兜底释放 8501 端口。

    背景服务历史上经历过：
    - PID 文件已更新，但旧服务子进程仍残留占端口；
    - 看门狗已先 stop_background，但 8501 仍未真正释放。

    此处按端口再扫一遍，确保下次启动不会因为 `Errno 10048` 继续打到旧服务。
    """
    return stop_processes_on_port(SERVER_PORT, exclude_pids={os.getpid()})


def _build_env(config: dict) -> dict:
    lan_ip = guess_lan_ip()
    env = os.environ.copy()
    env["FORCE_PRODUCTION"] = "1"
    # 生产主机必须明确身份，不能再依赖是否存在局域网密码等间接条件判断。
    # 该标识用于权限、健康检查和日志排障，不改变既有业务流程。
    env["QMS_ENVIRONMENT"] = "production"
    env["QMS_INSTANCE_NAME"] = "Windows LAN and public"
    # 不再硬编码 FORCE_LAN_LOGIN：去掉后登录方式按网络自动分流
    # （局域网/私有网络 → 邮箱+共享密码；公网 → Google OAuth）。
    # 仅当 config.lan_force_login=true 时才强制走局域网密码登录。
    if config.get("lan_force_login", False):
        env["FORCE_LAN_LOGIN"] = "1"
    env["LAN_ALLOWED_DOMAIN"] = config.get("lan_allowed_domain", "sainstore.com")
    env["LAN_ACCESS_PASSWORD"] = config.get("lan_access_password", "")
    public_base = str(config.get("public_base_url", "") or os.environ.get("PUBLIC_BASE_URL", "")).strip()
    env["PUBLIC_BASE_URL"] = public_base
    env["COOKIE_SECRET"] = str(config.get("cookie_secret", "")).strip()
    env["PHOTO_API_TOKEN"] = str(config.get("photo_api_token", "")).strip()
    env["NAS_URL"] = str(config.get("nas_url", "")).strip()
    env["NAS_ACCOUNT"] = str(config.get("nas_account", "")).strip()
    env["NAS_PASSWORD"] = str(config.get("nas_password", "")).strip()
    env["DINGTALK_APP_KEY"] = str(config.get("dingtalk_app_key", "")).strip()
    env["DINGTALK_APP_SECRET"] = str(config.get("dingtalk_app_secret", "")).strip()
    env["DINGTALK_AGENT_ID"] = str(config.get("dingtalk_agent_id", "")).strip()
    if public_base:
        env["QMS_ACCESS_URL"] = public_base.rstrip("/")
    elif lan_ip:
        env["SERVER_IP"] = lan_ip
        env["QMS_ACCESS_URL"] = f"http://{lan_ip}:8501"
    env["SERVER_ADDRESS"] = "0.0.0.0"
    env["SERVER_PORT"] = "8501"
    return env


def main() -> int:
    ensure_runtime_dirs()
    config = ensure_runtime_secrets(load_runtime_config())

    required = {
        "lan_access_password": "局域网访问密码",
        "cookie_secret": "会话密钥",
        "photo_api_token": "拍照接口令牌",
        "nas_url": "NAS 地址",
        "nas_account": "NAS 账号",
        "nas_password": "NAS 密码",
        "dingtalk_app_key": "钉钉 AppKey",
        "dingtalk_app_secret": "钉钉 AppSecret",
        "dingtalk_agent_id": "钉钉 AgentId",
    }
    missing = [label for key, label in required.items() if not str(config.get(key, "")).strip()]
    if missing:
        print("后台运行配置缺失：" + "、".join(missing) + "。请先运行 configure_windows_background.py")
        return 1

    background_python = _get_background_python_executable()
    python_exe = _get_python_executable()
    if not python_exe.exists():
        print("未找到 Python 运行环境，请先运行 setup_windows_direct.bat")
        return 1

    existing_pid = read_pid(SERVER_PID_FILE)
    if existing_pid:
        _ensure_sync_watcher(background_python)
        meta = {
            "pid": existing_pid,
            "access_url": _build_env(config).get("QMS_ACCESS_URL", "http://localhost:8501"),
        }
        print(f"品质系统已在后台运行: PID {existing_pid}")
        print(f"访问地址: {meta['access_url']}")
        return 0

    env = _build_env(config)
    access_url = env.get("QMS_ACCESS_URL", "http://localhost:8501")
    out_log = LOG_DIR / "qms_server.out.log"
    err_log = LOG_DIR / "qms_server.err.log"

    # 后台启动通知中继；中继脚本内部会自动避免重复拉起。
    subprocess.run(
        [str(python_exe), str(SCRIPT_DIR / "start_notify_relay.py")],
        cwd=str(SCRIPT_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    _ensure_sync_watcher(background_python)

    # ── 启动前确保数据库 schema 最新 ──
    # 此时服务尚未启动、数据库无锁，可可靠执行 CREATE TABLE（含 operation_log 审计表），
    # 规避运行中因 WAL 幽灵写入 / 模块热重载缓存导致新表未落盘的隐患。
    try:
        _init = subprocess.run(
            [str(python_exe), str(SCRIPT_DIR / "init_db_once.py")],
            cwd=str(SCRIPT_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if _init.returncode == 0:
            print("[schema] 数据库 schema 已确保最新（含 operation_log 审计表）")
        else:
            print(f"[schema][警告] 初始化返回非零: {(_init.stderr or _init.stdout).strip()[:300]}")
    except Exception as _e:
        print(f"[schema][警告] 初始化数据库 schema 失败（不影响启动）: {_e}")

    dep_ok, dep_msg = _ensure_runtime_dependencies(python_exe, env)
    if dep_ok:
        print(f"[deps] {dep_msg}")
    else:
        print(f"[deps][错误] {dep_msg}")
        return 1

    # Win 同步采用 rsync，远端 __pycache__ 不会被覆盖删除。
    # 若源码已更新但旧 pyc 仍可用，Python 可能继续加载旧缓存，形成“源码已新、运行仍旧”的混合版本。
    _clear_project_pycache()
    _purge_obsolete_project_artifacts()
    released_pids = _force_release_server_port()
    if released_pids:
        print(f"[port] 已强制释放 {SERVER_PORT} 端口，占用 PID: {', '.join(map(str, released_pids))}")

    streamlit_module = [
        str(background_python),
        str(SCRIPT_DIR / "unified_app.py"),
    ]

    with out_log.open("a", encoding="utf-8") as stdout, err_log.open("a", encoding="utf-8") as stderr:
        stdout.write(f"\n[{now_ts()}] Starting QMS background server\n")
        stderr.write(f"\n[{now_ts()}] Starting QMS background server\n")
        stdout.flush()
        stderr.flush()

        kwargs = {
            "cwd": str(SCRIPT_DIR),
            "env": env,
            "stdout": stdout,
            "stderr": stderr,
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

        proc = subprocess.Popen(streamlit_module, **kwargs)

    write_pid(SERVER_PID_FILE, proc.pid)
    # 启动成功即解除维护锁（若存在），看门狗恢复正常自愈
    try:
        MAINTENANCE_LOCK_FILE.unlink()
    except FileNotFoundError:
        pass
    dingtalk_status = get_app_push_status(check_auth=True)
    dws_available = bool(shutil.which("dws"))
    write_json(
        SERVER_META_FILE,
        {
            "pid": proc.pid,
            "started_at": now_ts(),
            "access_url": access_url,
            "python": str(background_python),
            "dws_available": dws_available,
            "dingtalk_app_configured": bool(dingtalk_status.get("configured")),
            "dingtalk_app_auth_ok": dingtalk_status.get("auth_ok"),
            "dingtalk_app_message": dingtalk_status.get("message", ""),
            "version": VERSION,
            "build_date": BUILD_DATE,
            "sync_id": read_json(REMOTE_SYNC_META_FILE).get("sync_id", ""),
        },
    )

    print(f"品质系统后台已启动: PID {proc.pid}")
    print(f"访问地址: {access_url}")
    if not dingtalk_status.get("configured") or dingtalk_status.get("auth_ok") is False:
        print(f"警告: 钉钉应用推送不可用：{dingtalk_status.get('message', '未知错误')}")
    elif not dws_available:
        print("提示: 未检测到 dws；已知人员可直接推送，未知人员解析将进入待重试队列。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
