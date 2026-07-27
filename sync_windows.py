#!/usr/bin/env python3
"""
Mac -> Windows 主机代码同步工具。

设计目标：
1. 只同步代码，不覆盖 Windows 主机上的业务数据。
2. 允许 Mac 端保存一次共享目录，后续一键同步。
3. 为被覆盖/删除的代码文件保留一份 Windows 端备份。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

from config import BASE_DIR
from version import BUILD_DATE, VERSION


CONFIG_FILE = Path(BASE_DIR) / ".windows_sync.json"
NAS_SMB_CONFIG = Path(BASE_DIR) / ".nas_smb.json"
REMOTE_META_FILE = ".last_mac_sync.json"
BACKUP_DIR_NAME = "_mac_sync_backups"
SYNC_REQUEST_RELATIVE_FILE = os.path.join("data", "windows_sync_request.json")

PROTECTED_PATTERNS = [
    ".git/",
    "venv/",
    ".venv/",
    "__pycache__/",
    ".cache/",
    ".workbuddy/",
    # 本机代理/技能资料不是品质系统运行依赖，禁止同步进生产根目录，
    # 避免把示例应用和历史说明混入运行包。
    ".agents/",
    # Claude Code 的 Agent 技能目录（.claude/）同样非运行依赖，禁止推到生产包；
    # 仅阻止后续推送，已存在于 Win 的文件不受影响（脚本未用 --delete-excluded）。
    ".claude/",
    ".DS_Store",
    ".deploy_token",
    ".windows_sync.json",
    ".nas_smb.json",
    # 本机运行日志 / PID 属于进程瞬态状态；推送到 Win 会让部署包混入已失效的运行痕迹。
    ".dev_8502.log",
    ".dev_8502.pid",
    ".prod_8501.log",
    ".prod_8501.pid",
    "dist/",
    BACKUP_DIR_NAME + "/",
    "SainStore实验室文件/",
    # 根目录旧版数据库同样属于业务数据，禁止 Mac 本地副本覆盖 Win。
    "quality_system.db",
    # _pages/ 是 Mac 端 pages 的 symlink 目标。rsync -L 已将 pages 展开为实体目录同步到 Win，
    # 若 _pages/ 也同步过去，Streamlit 会扫描到两份 page_*.py 导致同一页面脚本被双重加载
    #（表现为 "multiple elements with the same key" 错误，如 sidebar_logout_bottom 重复）。
    "_pages/",
    # ── 同步清洁：本机开发 / 审计 / Playwright 遗留的非运行文件，禁止推到生产包 ──
    # 这些文件不影响运行，但会弄脏 Win 包、且其中 _audit_trash_*/ 还含旧库备份快照。
    ".playwright-cli/",
    ".ui_audit/",
    "_audit_trash_*/",
    # 各种中文临时文件（UI 设计原型 / 检验报告培训手册 / 审计报告等 HTML·PDF）
    "*.html",
    "*.pdf",
    # 工作底稿和审计说明不属于服务器运行依赖，生产部署仅传递代码与必要静态资源。
    "work/",
    "*.md",
    # data/ 是服务器的运行状态与业务数据边界：数据库、报告、照片、OAuth 凭据、缓存、
    # 备份均由 Win 主机自行维护。禁止整个目录参与 rsync，避免任何遗漏模式把本机内容
    # 覆盖到生产环境；本脚本的重启请求会在同步后以独立受控写入方式创建。
    "data/",
]

# 兼容旧版调用方的细粒度数据排除清单。当前 data/ 已整体受保护，保留本表仅用于
# 文档化此前已识别的业务/凭据边界，不能放宽 data/ 的总保护规则。
DATA_EXCLUDES = [
    "data/*.log",
    "data/relay_url.txt",
    "data/dingtalk_creds_zoom.png",
    "data/client_secret.json",
    "data/auth.json",
    "data/lab_equipment.db",
    "data/quality_hub.db",
    "data/pending_notify/",
    # ── 业务数据保护：绝不允许用 Mac 本地库覆盖 Win 主机上的业务数据 ──
    # 2026-07-09 事故：此前 lab_manager.db 被纳入同步，每次 Mac→Win 同步都会用 Mac 的
    # （0 报告）库整体覆盖 Win 库，导致同事在 Win 上传的检验报告被清空。
    "data/lab_manager.db",
    "data/reports/",
    "data/changes/",
    # ── 在线检验报告文件（业务数据，与 reports/ 对称，绝不允许 Mac 覆盖 Win）──
    "data/online_reports/",
    # ── 凭据文件（Mac 本地凭据不应推到 Win，Win 使用自己的凭据）──
    "data/gcp_credentials.json",
    # ── Mac 本地库的拉取前快照，仅供本地回滚，禁止推到 Win 污染 data/ ──
    "data/*.before_pull.*.db",
    # ── 本地备份目录，非业务数据，无需同步 ──
    "data/backups/",
]

REQUIRED_TARGET_MARKERS = [
    "main.py",
    "database.py",
    "data",
]


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_target_path(target_path: str) -> str:
    normalized = os.path.expanduser((target_path or "").strip())
    if normalized.endswith(os.sep):
        normalized = normalized.rstrip(os.sep)
    return normalized


def load_windows_sync_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_windows_sync_config(target_path: str) -> str:
    normalized = _normalize_target_path(target_path)
    CONFIG_FILE.write_text(
        json.dumps(
            {
                "target_path": normalized,
                "updated_at": _now_ts(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return normalized


def _discover_win_target() -> str:
    """
    自动探测 Windows 主机共享的实际挂载点。
    解决 macOS 因卷名漂移（如「品质系统」→「品质系统-1」）导致写死路径失效的问题。

    扫描 /Volumes 下所有挂载点及其子目录（到第 2 层，兼容 bundle 双层嵌套），
    找到包含 Win 根特征文件（main.py / database.py / data）的目录即视为目标。

    关键修复（2026-07-11）：
    1. 挂载名漂移容错：候选名若形如「品质系统」「品质系统-1」「品质系统-2」视为同一盘，
       优先用实际存在的挂载点，不再因重连改名而失效。
    2. 双层嵌套去重：ZIP 解压到同名文件夹会产生
       quality-system-.../quality-system-... 的重复结构。若子目录名与父目录完全相同，
       直接跳过子目录（它不是真实根），避免返回带重复名称的路径。
    """
    vol_root = "/Volumes"
    if not os.path.isdir(vol_root):
        return ""
    try:
        vols = os.listdir(vol_root)
    except OSError:
        return ""

    # 挂载名漂移容错：把「name」「name-N」归并到同一个基础名
    def _base_vol_name(v: str) -> str:
        # 「品质系统-1」「品质系统-2」→「品质系统」；无后缀则原样返回
        if "-" in v:
            head, _, tail = v.rpartition("-")
            if tail.isdigit():
                return head
        return v

    # 按基础名分组，优先用第一个真实存在的挂载点
    base_map: dict[str, str] = {}
    for vol in vols:
        vol_path = os.path.join(vol_root, vol)
        if not os.path.isdir(vol_path):
            continue
        base = _base_vol_name(vol)
        if base not in base_map:
            base_map[base] = vol_path  # 首个（通常无后缀）优先

    candidates: list[str] = []
    for base, vol_path in base_map.items():
        candidates.append(vol_path)
        # 已知 bundle 为双层嵌套（quality-system-.../quality-system-...），
        # 但为兼容未来结构，扫描到挂载点下第 2 层子目录。
        try:
            subs = os.listdir(vol_path)
        except (OSError, PermissionError):
            subs = []
        for sub in subs:
            sub_path = os.path.join(vol_path, sub)
            if not os.path.isdir(sub_path):
                continue
            candidates.append(sub_path)
            try:
                subsubs = os.listdir(sub_path)
            except (OSError, PermissionError):
                subsubs = []
            for ssub in subsubs:
                ssub_path = os.path.join(sub_path, ssub)
                if os.path.isdir(ssub_path):
                    candidates.append(ssub_path)

    # 逐层检查：收集所有匹配目录
    found: list[str] = []
    for cand in candidates:
        if all(os.path.exists(os.path.join(cand, m)) for m in REQUIRED_TARGET_MARKERS):
            found.append(cand)
    if not found:
        return ""
    # 按路径深度（sep 数量）升序，取最浅的；深度相同则按字典序
    found.sort(key=lambda p: (p.count(os.sep), p))
    return found[0]


def _flatten_double_nesting(cand: str) -> str:
    """
    ⚠️ 维护时段专用 · 危险操作
    当 cand 形如 `parent/child` 且 basename(parent) == basename(child)，
    且 child 含 Win 根特征、parent 不含，说明是解压产物冗余。
    把 child 内容安全移动到 parent，删除空 child，返回 parent（单层路径）。

    ⚠️ 风险：此操作会移动 Win 正在运行的代码与 data/ 业务库。
    必须在 Win 服务已停止的维护窗口执行，否则可能损坏数据库 / 中断同事访问。
    故本函数绝不经由页面加载或自动同步调用，仅由显式「目录去重整理」按钮触发。
    """
    parent = os.path.dirname(cand)
    if not parent or os.path.basename(parent) != os.path.basename(cand):
        return cand
    # parent 自身已含特征文件 → 不是嵌套冗余，不处理
    if all(os.path.exists(os.path.join(parent, m)) for m in REQUIRED_TARGET_MARKERS):
        return cand
    # 安全检查：parent 只能包含 child 本身（及 .DS_Store 等隐藏项），否则放弃
    try:
        entries = [e for e in os.listdir(parent) if not e.startswith(".")]
    except OSError:
        return cand
    if entries != [os.path.basename(cand)]:
        return cand
    # 执行扁平化：逐文件上移，已存在则跳过（绝不覆盖）
    try:
        for name in os.listdir(cand):
            if name.startswith("."):
                continue
            src = os.path.join(cand, name)
            dst = os.path.join(parent, name)
            if os.path.exists(dst):
                continue
            shutil.move(src, dst)
        # 删除已清空的子目录
        if not any(e for e in os.listdir(cand) if not e.startswith(".")):
            os.rmdir(cand)
    except Exception as e:
        print(f"⚠️ 扁平化双层嵌套失败（保留原路径）: {e}")
        return cand
    print(f"🧹 已扁平化双层嵌套目录，项目根回归单层：{parent}")
    return parent


def deduplicate_win_target() -> str:
    """
    显式「目录去重整理」入口（维护时段专用，需先停止 Win 服务）。
    自动定位 Win 项目根；若呈双层嵌套（BUNDLE/BUNDLE），执行扁平化返回单层路径；
    若已是单层则返回当前有效路径。空串表示找不到。
    """
    vol_root = "/Volumes"
    if not os.path.isdir(vol_root):
        return ""
    try:
        vols = os.listdir(vol_root)
    except OSError:
        return ""

    def _base_vol_name(v: str) -> str:
        if "-" in v:
            head, _, tail = v.rpartition("-")
            if tail.isdigit():
                return head
        return v

    base_map: dict[str, str] = {}
    for vol in vols:
        vol_path = os.path.join(vol_root, vol)
        if not os.path.isdir(vol_path):
            continue
        base = _base_vol_name(vol)
        if base not in base_map:
            base_map[base] = vol_path

    candidates: list[str] = []
    for base, vol_path in base_map.items():
        candidates.append(vol_path)
        try:
            subs = os.listdir(vol_path)
        except (OSError, PermissionError):
            subs = []
        for sub in subs:
            sub_path = os.path.join(vol_path, sub)
            if not os.path.isdir(sub_path):
                continue
            candidates.append(sub_path)
            try:
                subsubs = os.listdir(sub_path)
            except (OSError, PermissionError):
                subsubs = []
            for ssub in subsubs:
                ssub_path = os.path.join(sub_path, ssub)
                if os.path.isdir(ssub_path):
                    candidates.append(ssub_path)

    found: list[str] = []
    for cand in candidates:
        if all(os.path.exists(os.path.join(cand, m)) for m in REQUIRED_TARGET_MARKERS):
            found.append(cand)
    if not found:
        return ""
    found.sort(key=lambda p: (p.count(os.sep), p))
    target = found[0]
    flattened = _flatten_double_nesting(target)
    if flattened != target:
        save_windows_sync_config(flattened)
        print(f"🧹 已去重并保存新路径：{flattened}")
    return flattened


def load_nas_smb_config() -> dict:
    """
    读取 NAS SMB 自动挂载配置；文件缺失时生成默认（基于实测环境）。
    凭据不硬编码在源码、不进 git（.nas_smb.json 已在 PROTECTED_PATTERNS）。
    注意：teddy.li 是 DSM FileStation API 账号，实测无法用于 SMB 登录；
    当前真实 SMB 共享账号为 share（无密码），故默认采用之。
    """
    default = {
        # hosts 候选：应对切换网络后 NAS 可达地址变化（IP/域名逐个尝试）
        "hosts": ["192.168.61.16", "sainnas.work", "sainnas.local"],
        "share": "品质系统",
        "user": "share",
        "password": "",
        "fixed_mount": os.path.expanduser("~/Library/Caches/qms_win_mount"),
    }
    if NAS_SMB_CONFIG.exists():
        try:
            cfg = json.loads(NAS_SMB_CONFIG.read_text(encoding="utf-8"))
            default.update(cfg)
            return default
        except Exception:
            pass
    NAS_SMB_CONFIG.write_text(
        json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return default


def _ensure_mounted() -> str:
    """
    当所有现有挂载都探测不到 Win 根时，尝试用 SMB 自动挂载到固定本地目录
    （~/Library/Caches/qms_win_mount，不受 macOS 卷名漂移影响）。
    遍历 hosts 候选逐个尝试。返回挂载后的 Win 根路径；全部失败则返回 ""。
    仅当 NAS 完全断开（无冲突挂载）时才会真正挂载成功——
    macOS 禁止同一共享多重挂载，若已挂到 /Volumes/品质系统-* 则此处会 File exists，
    此时上层 _resolve_saved_target 已通过 _discover_win_target 命中，不会走到这里。
    """
    cfg = load_nas_smb_config()
    fixed = os.path.expanduser(cfg.get("fixed_mount", "~/Library/Caches/qms_win_mount"))
    # 固定点本身若已是可用 Win 根，直接返回
    if os.path.isdir(fixed) and all(
        os.path.exists(os.path.join(fixed, m)) for m in REQUIRED_TARGET_MARKERS
    ):
        return fixed
    os.makedirs(fixed, exist_ok=True)
    share_enc = urllib.parse.quote(cfg.get("share", "品质系统"))
    user = cfg.get("user", "share")
    pwd = cfg.get("password", "")
    user_part = f"{user}:{urllib.parse.quote(pwd, safe='')}@" if pwd else f"{user}@"
    hosts = cfg.get("hosts", ["192.168.61.16"])
    for host in hosts:
        url = f"//{user_part}{host}/{share_enc}"
        try:
            proc = subprocess.run(
                ["mount_smbfs", url, fixed],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            continue
        if proc.returncode == 0 and os.path.isdir(fixed) and all(
            os.path.exists(os.path.join(fixed, m)) for m in REQUIRED_TARGET_MARKERS
        ):
            return fixed
        # File exists 表示共享已被挂到别处（上层探测应已命中），无需重试
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        if "File exists" in err:
            break
    return ""


def _relocate_saved_path(saved: str) -> str:
    """
    挂载名漂移容错：saved 路径因「品质系统」→「品质系统-1」改名而失效时，
    提取其中的 bundle 名（quality-system-windows-bundle-xxxx），
    在当前 /Volumes 下重新按名定位，避免因 macOS 重命名而丢失配置。

    关键修正（2026-07-11）：
    当同一 bundle 存在单层和双层嵌套两个有效候选时，
    始终返回最浅层（路径深度最小）的那个，避免显示/使用冗余的 bundle/bundle 路径。

    返回重新定位后的有效路径；找不到则返回 ""。
    """
    if not saved:
        return ""
    saved_norm = _normalize_target_path(saved)
    # 提取路径中形如 quality-system-windows-bundle-xxxx 的目录名
    bundle_name = ""
    for part in saved_norm.split(os.sep):
        if "quality-system-windows-bundle" in part:
            bundle_name = part
            break
    if not bundle_name:
        return ""
    vol_root = "/Volumes"
    if not os.path.isdir(vol_root):
        return ""
    try:
        vols = os.listdir(vol_root)
    except OSError:
        return ""
    # 同样做挂载名归一（品质系统 / 品质系统-1 视为同一盘，无后缀优先）
    def _base_vol_name(v: str) -> str:
        if "-" in v:
            head, _, tail = v.rpartition("-")
            if tail.isdigit():
                return head
        return v

    base_map: dict[str, str] = {}
    for vol in vols:
        vol_path = os.path.join(vol_root, vol)
        if not os.path.isdir(vol_path):
            continue
        base = _base_vol_name(vol)
        if base not in base_map:
            base_map[base] = vol_path

    # 收集所有匹配候选（可能同时有单层和双层），按深度升序，取最浅
    matched: list[str] = []
    for base, vol_path in base_map.items():
        # 单层候选：/Volumes/品质系统/bundle_name
        cand = os.path.join(vol_path, bundle_name)
        if os.path.isdir(cand) and all(
            os.path.exists(os.path.join(cand, m)) for m in REQUIRED_TARGET_MARKERS
        ):
            matched.append(cand)
        # 双层候选：/Volumes/品质系统/bundle_name/bundle_name
        cand2 = os.path.join(cand, bundle_name)
        if os.path.isdir(cand2) and all(
            os.path.exists(os.path.join(cand2, m)) for m in REQUIRED_TARGET_MARKERS
        ):
            matched.append(cand2)

    if not matched:
        return ""
    # 按路径深度升序 → 最浅的有效路径优先
    matched.sort(key=lambda p: p.count(os.sep))
    return matched[0]


def _resolve_saved_target() -> str:
    """
    读取已保存的 target_path；若其已失效（挂载漂移/卸载），
    先按 bundle 名重新定位（容错改名），再自动探测实际挂载点，
    最后尝试 SMB 自动重挂载。返回最终可用的目标路径。

    关键修正（2026-07-11）：
    即使已保存路径本身有效（目录存在+含特征文件），仍会检查同一 bundle
    是否存在更浅层的有效路径（如单层 vs 双层嵌套），始终返回最浅的可用路径，
    避免显示/使用冗余的 bundle/bundle 双层结构。

    ⚠️ 本函数只做「路径定位」，绝不移动文件。
    双层嵌套去重（_flatten_double_nesting）是危险的文件移动操作，
    必须在 Win 服务停止的维护窗口由显式按钮触发，绝不经此处自动执行。
    """
    saved = load_windows_sync_config().get("target_path", "")

    # 快速路径：saved 有效且为最浅候选 → 直接返回
    if saved and os.path.isdir(saved) and all(
        os.path.exists(os.path.join(saved, m)) for m in REQUIRED_TARGET_MARKERS
    ):
        # 检查是否存在更浅的同 bundle 有效路径
        shallower = _relocate_saved_path(saved)
        if shallower and shallower != saved and shallower.count(os.sep) < saved.count(os.sep):
            save_windows_sync_config(shallower)
            print(f"🔄 已定位到更浅层 Win 路径：{shallower}（原：{saved}）")
            return shallower
        return saved

    # 挂载名漂移：按 bundle 名重新定位（不轻易改写配置）
    relocated = _relocate_saved_path(saved)
    if relocated:
        if relocated != saved:
            save_windows_sync_config(relocated)
            print(f"🔄 已按 bundle 名重定位 Win 挂载点：{relocated}")
        return relocated
    # 仍找不到 → 全量自动探测
    discovered = _discover_win_target()
    if discovered:
        if discovered != saved:
            save_windows_sync_config(discovered)
            print(f"🔄 已自动重探测 Win 挂载点：{discovered}")
        return discovered
    # NAS 可能完全断开 → 尝试自动重新挂载
    mounted = _ensure_mounted()
    if mounted:
        save_windows_sync_config(mounted)
        print(f"🔌 已自动重新挂载 NAS：{mounted}")
        return mounted
    return saved


def validate_windows_sync_target(target_path: str) -> tuple[bool, list[str], str]:
    normalized = _normalize_target_path(target_path)
    messages: list[str] = []

    if not normalized:
        return False, ["请先填写 Win 主机共享目录。"], normalized

    local_root = os.path.abspath(BASE_DIR)
    target_abs = os.path.abspath(normalized)

    if local_root == target_abs:
        return False, ["不能把同步目标指向当前 Mac 本地项目目录。"], normalized

    if not os.path.exists(target_abs):
        hint = ""
        if "/Volumes/" in normalized:
            hint = (
                "\n提示：切换有线/WiFi 后 macOS 可能卸载或重命名了 SMB 挂载点"
                "（如「品质系统」→「品质系统-1」）。请确认 NAS 已重新挂载，"
                "或在 Finder 中重新连接服务器后再试。"
            )
        return False, [f"目录不存在：{normalized}{hint}"], normalized

    if not os.path.isdir(target_abs):
        return False, [f"目标不是文件夹：{normalized}"], normalized

    missing_markers = [
        marker for marker in REQUIRED_TARGET_MARKERS
        if not os.path.exists(os.path.join(target_abs, marker))
    ]
    if missing_markers:
        messages.append("这个目录不像 Win 主机上的品质系统根目录。")
        messages.append(f"缺少关键内容：{', '.join(missing_markers)}")
        messages.append("请把路径指向 Win 主机项目根目录，而不是上一级共享盘。")
        return False, messages, normalized

    if not shutil.which("rsync"):
        return False, ["当前 Mac 缺少 rsync，无法执行代码同步。"], normalized

    messages.append("目录检测通过，可以开始同步。")
    messages.append("同步仅覆盖 Win 端代码（main.py/database.py/pages 等），"
                    "不会覆盖 Win 主机的业务数据库（lab_manager.db）与已上传的报告/变更文件，"
                    "因此同事在 Win 上上传的数据不会丢失。")
    return True, messages, normalized


def _build_rsync_command(target_path: str, backup_dir: str) -> list[str]:
    command = [
        "rsync",
        "-a",
        "-L",
        # SMB/Windows 不保留 macOS 的 Unix owner/group/mode 语义。若同步这些属性，
        # 每次都会把同一批文件误报为变更（f...p），并产生无意义备份。
        "--no-perms",
        "--no-owner",
        "--no-group",
        "--delete",
        "--human-readable",
        "--itemize-changes",
        "--backup",
        f"--backup-dir={backup_dir}",
    ]
    for pattern in PROTECTED_PATTERNS:
        command.extend(["--exclude", pattern])
    for pattern in DATA_EXCLUDES:
        command.extend(["--exclude", pattern])
    command.extend([f"{BASE_DIR}/", f"{target_path}/"])
    return command


def _write_remote_meta(target_path: str, backup_dir: str, changed_count: int, sync_id: str) -> None:
    meta_path = Path(target_path) / REMOTE_META_FILE
    payload = {
        "sync_id": sync_id,
        "synced_at": _now_ts(),
        "source_machine": socket.gethostname(),
        "source_root": BASE_DIR,
        "version": VERSION,
        "build_date": BUILD_DATE,
        "changed_count": changed_count,
        "backup_dir": backup_dir,
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cleanup_remote_runtime_junk(target_path: str) -> list[str]:
    """
    清理 Win 项目根下容易引发“源码已更新但运行仍旧”的残留缓存。

    仅清理项目源码缓存和已废弃的 8800 独立服务 PID/元数据；
    不清理业务数据、备份目录、venv、第三方包缓存。
    """
    removed: list[str] = []
    targets = [
        os.path.join(target_path, "__pycache__"),
        os.path.join(target_path, "_pages", "__pycache__"),
        os.path.join(target_path, "pages", "__pycache__"),
        os.path.join(target_path, "_components", "__pycache__"),
        os.path.join(target_path, "components", "__pycache__"),
        os.path.join(target_path, "_components", "online_report"),
        os.path.join(target_path, "data", "photo_api.pid"),
        os.path.join(target_path, "data", "photo_api_meta.json"),
    ]
    for path in targets:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path)
            elif os.path.isfile(path):
                os.remove(path)
                removed.append(path)
        except Exception:
            pass
    return removed


def _request_windows_restart(target_path: str, changed_count: int, sync_id: str) -> str:
    request_path = Path(target_path) / SYNC_REQUEST_RELATIVE_FILE
    request_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = request_path.with_suffix(".tmp")
    payload = {
        "sync_id": sync_id,
        "requested_at": _now_ts(),
        "source_machine": socket.gethostname(),
        "source_root": BASE_DIR,
        "target_path": target_path,
        "version": VERSION,
        "build_date": BUILD_DATE,
        "changed_count": changed_count,
        "action": "restart_background_service",
    }
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(request_path)
    return str(request_path)


def sync_to_windows(target_path: str) -> dict:
    ok, messages, normalized = validate_windows_sync_target(target_path)
    if not ok:
        raise RuntimeError("\n".join(messages))

    backup_dir = os.path.join(
        normalized,
        BACKUP_DIR_NAME,
        datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    os.makedirs(backup_dir, exist_ok=True)

    command = _build_rsync_command(normalized, backup_dir)
    result = subprocess.run(command, capture_output=True)
    output = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    error = (result.stderr or b"").decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        raise RuntimeError(error or output or "rsync 同步失败")

    changed_lines = [line for line in output.splitlines() if line.strip()]
    sync_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    changed_count = len(changed_lines)
    _write_remote_meta(normalized, backup_dir, changed_count, sync_id)
    cleanup_removed = _cleanup_remote_runtime_junk(normalized)
    restart_request_path = _request_windows_restart(normalized, changed_count, sync_id)

    preview_lines = changed_lines[:120]
    if len(changed_lines) > 120:
        preview_lines.append(f"... 共 {changed_count} 条变更，仅显示前 120 条")

    return {
        "target_path": normalized,
        "backup_dir": backup_dir,
        "changed_count": changed_count,
        "sync_id": sync_id,
        "restart_request_path": restart_request_path,
        "cleanup_removed": cleanup_removed,
        "output_preview": "\n".join(preview_lines),
        "summary": (
            f"同步完成，已清理 {len(cleanup_removed)} 处运行缓存/旧残留，"
            f"仅同步代码，未写入任何业务数据，并已请求 Win 后台自动重启刷新。"
            if changed_count
            else f"同步完成，本次没有代码差异，但已清理 {len(cleanup_removed)} 处运行缓存/旧残留，"
                 f"未写入任何业务数据，并已请求 Win 后台刷新。"
        ),
    }


def _sync_dir(src_dir: str, dst_dir: str) -> None:
    """递归同步目录（覆盖式）。"""
    os.makedirs(dst_dir, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        target_root = os.path.join(dst_dir, rel) if rel != "." else dst_dir
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))


def pull_from_windows(target_path: str) -> dict:
    """
    从 Win 主机拉取业务数据镜像到本地（Win→Mac）。
    仅复制业务数据（lab_manager.db / reports / changes / pending_notify），
    不复制代码，因此不会覆盖本地代码。本地原库会自动备份。
    """
    normalized = _normalize_target_path(target_path)
    if not normalized:
        raise RuntimeError("请先指定 Win 主机共享目录（--target 或先 --save-target）。")
    src_data = os.path.join(normalized, "data")
    dst_data = os.path.join(BASE_DIR, "data")
    if not os.path.exists(src_data):
        raise RuntimeError(f"Win 端 data 目录不存在：{src_data}")

    os.makedirs(dst_data, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 安全备份本地现有业务库
    local_db = os.path.join(dst_data, "lab_manager.db")
    if os.path.exists(local_db):
        shutil.copy(local_db, os.path.join(dst_data, f"lab_manager.before_pull.{ts}.db"))

    copied: list[str] = []

    src_db = os.path.join(src_data, "lab_manager.db")
    if os.path.exists(src_db):
        shutil.copy(src_db, local_db)
        copied.append("lab_manager.db")

    for d in ("reports", "changes", "pending_notify"):
        sdir = os.path.join(src_data, d)
        if os.path.isdir(sdir):
            _sync_dir(sdir, os.path.join(dst_data, d))
            copied.append(d + "/")

    return {"target": normalized, "copied": copied}


def main() -> int:
    parser = argparse.ArgumentParser(description="同步本地品质系统代码到 Windows 主机共享目录")
    parser.add_argument("--target", help="Windows 主机共享目录")
    parser.add_argument("--save-target", help="保存共享目录配置后退出")
    parser.add_argument("--validate", help="只检测共享目录，不执行同步")
    parser.add_argument("--pull", action="store_true",
                        help="从 Win 主机拉取业务数据镜像到本地（Win→Mac），用于本地查看/开发")
    args = parser.parse_args()

    if args.save_target:
        target = save_windows_sync_config(args.save_target)
        print(f"已保存 Win 主机目录：{target}")
        return 0

    if args.validate:
        ok, messages, normalized = validate_windows_sync_target(args.validate)
        print(f"检测目录：{normalized}")
        for message in messages:
            print(f"- {message}")
        return 0 if ok else 1

    if args.pull:
        target = args.target or _resolve_saved_target()
        result = pull_from_windows(target)
        print(f"已从 Win 拉取数据镜像（{result['target']}）：")
        for item in result["copied"]:
            print(f"  - {item}")
        print("提示：本地原 lab_manager.db 已自动备份，可在 data/ 下找到 before_pull 备份。")
        return 0

    target = args.target or _resolve_saved_target()
    result = sync_to_windows(target)
    print(result["summary"])
    print(f"目标目录：{result['target_path']}")
    print(f"备份目录：{result['backup_dir']}")
    if result["output_preview"]:
        print(result["output_preview"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
