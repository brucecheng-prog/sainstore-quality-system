"""
系统版本变动日志 - 记录每次优化和修改（仅本地开发可见）
"""

import streamlit as st
import os, sys, subprocess, shutil, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pages._utils import render_sidebar, render_topbar, ui_empty_state, ui_table
from version import VERSION, BUILD_DATE, BUILD_TYPE
from database import init_db, get_changelogs, delete_changelog
from sync_windows import (
    load_windows_sync_config,
    save_windows_sync_config,
    sync_to_windows,
    validate_windows_sync_target,
    deduplicate_win_target,
    _resolve_saved_target,
)

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")

init_db()

# 渲染侧边栏导航
st.session_state.current_page = "版本日志"
with st.sidebar:
    render_sidebar()
render_topbar("版本日志")



LOCAL_AUDIT_MODE = os.getenv("LAB_AUDIT_LOCAL") == "1"
st.markdown("""
<div class="qms-page-header"><div>
  <div class="qms-eyebrow">RELEASE MANAGEMENT</div>
  <h1>系统版本变动日志</h1>
  <p>记录版本、变更原因和部署证据；远程同步属于独立维护动作</p>
</div></div>
""", unsafe_allow_html=True)
if LOCAL_AUDIT_MODE:
    st.markdown('<div class="qms-danger-zone"><strong>本地验收模式：</strong>当前只验证本机代码和数据，Win 同步按钮已保持禁用。</div>', unsafe_allow_html=True)

# 版本号（统一来自 version.py）
st.caption(f"当前版本: **{VERSION}** ({BUILD_TYPE}) | 构建日期: {BUILD_DATE} | 开发者: Bruce Cheng (程强)")
st.caption(" 版本规则: X.Y.Z → 大版本(架构变更)·小版本(功能优化)·修订(Bug修复)")

st.markdown("---")

# ==================== 版本日志卡片列表 ====================
st.subheader("版本更新记录")

category_colors = {
    "优化": ("#dbeafe", "#1e40af"),
    "修复": ("#fce7f3", "#9d174d"),
    "新增": ("#d1fae5", "#065f46"),
    "重构": ("#fef3c7", "#92400e"),
    "安全": ("#fee2e2", "#991b1b"),
}

logs = get_changelogs()

if logs:
    for entry in logs:
        ver = entry['version']
        title = entry.get('title', '未命名更新')
        category = entry.get('category', '优化')
        desc = entry.get('description', '')
        changes = entry.get('changes', '')
        created_at = entry.get('created_at', '')
        entry_id = entry['id']

        cat_bg, cat_color = category_colors.get(category, ("#f3f4f6", "#374151"))
        show_changes = changes and changes.strip() and changes.strip() != desc.strip()

        # 紧凑小卡片 + 删除按钮
        c1, c2, c3 = st.columns([6, 1, 1])
        with c1:
            with st.expander(f"{ver} · {title} | {created_at[:10]} | {category}"):
                if desc and desc != changes:
                    st.markdown(f"**说明**: {desc}")
                if show_changes:
                    st.markdown("**变动明细**:")
                    for change in [c.strip() for c in changes.split('\n') if c.strip()]:
                        st.markdown(f"- {change}")
                st.caption(f"记录时间: {created_at}")
        with c3:
            if st.button("删除", key=f"del_cl_{entry_id}", help="删除此版本记录"):
                delete_changelog(entry_id)
                st.rerun()

else:
    ui_empty_state("暂无版本变动记录", "首次部署后将自动生成版本日志；本地审计模式下不会触发 Win 同步")

# ==================== 🖥️ 一键同步到 Win 主机 ====================
st.markdown("---")
st.subheader("Win 主机部署管理")
st.caption("以后你只在 Mac 上开发。这里点击一次，只同步代码到 Win 主机，自动保留 Win 上的 data、venv 和上传资料，并通知 Win 主机后台自动重启。")
if LOCAL_AUDIT_MODE:
    st.warning("当前为本地审计模式：Win 同步已锁定。确认本地版本后再关闭本地模式执行同步。")

sync_config = load_windows_sync_config()
# 页面展示时始终用 resolve 后的路径（处理双层嵌套/挂载漂移）
resolved_display = _resolve_saved_target()
default_target = resolved_display or sync_config.get("target_path", "")
win_target = st.text_input(
    "Win 主机共享目录 *",
    value=default_target,
    key="win_sync_target",
    placeholder="/Volumes/QMS_SERVER/quality-system-windows-bundle-xxxx",
    help="先在 Mac 里挂载 Win 共享文件夹，再把 Win 主机项目根目录填到这里。路径会自动检测最浅层有效目录。",
)

# 检测到双层嵌套结构时给出提示
if default_target:
    parts = default_target.strip(os.sep).split(os.sep)
    if len(parts) >= 2 and parts[-1] == parts[-2] and "bundle" in parts[-1].lower():
        st.caption(
            "当前路径呈 **双层嵌套**（ZIP 解压产物），这是 NAS 上的实际存储结构，"
            "Win 主机正从该内层目录运行。如需整理为单层路径，请使用下方"
            "** 目录去重整理** 按钮（需先停止 Win 服务）。"
        )

st.caption("一次性准备：Win 主机把项目目录设为共享文件夹；Mac 用访达连接 `smb://Win主机IP/共享名`。挂载后一般会出现在 `/Volumes/共享名`。")

col_w1, col_w2 = st.columns(2)
with col_w1:
    if st.button("保存 Win 目录", width="stretch"):
        if not win_target.strip():
            st.error("请先填写 Win 主机共享目录。")
        else:
            saved_target = save_windows_sync_config(win_target)
            st.success(f"已保存：{saved_target}")

with col_w2:
    if st.button("检测 Win 目录", width="stretch"):
        ok, messages, normalized = validate_windows_sync_target(win_target)
        if normalized:
            st.code(normalized)
        if ok:
            for message in messages:
                st.success(message)
        else:
            for message in messages:
                st.error(message)

if st.button("同步到 Win 主机", type="primary", width="stretch", disabled=LOCAL_AUDIT_MODE):
    with st.status("正在同步到 Win 主机...", expanded=True) as status:
        try:
            # 先按 bundle 名重定位（容错 macOS 挂载漂移：品质系统↔品质系统-1），
            # 找不到有效挂载点时才退回用户当前输入框的值。
            resolved = _resolve_saved_target()
            saved_target = resolved or save_windows_sync_config(win_target)
            st.write(f"目标目录: `{saved_target}`")
            result = sync_to_windows(saved_target)
            status.update(label="Win 主机同步完成，已通知后台自动重启", state="complete")
            st.success(result["summary"])
            st.info("Win 主机已收到自动重启请求。通常等待 5-15 秒后刷新同事访问页面，新版本就会生效。")
            st.info(f"本次同步差异数：{result['changed_count']}")
            st.caption(f"Win 端自动备份目录：{result['backup_dir']}")
            restart_request_path = result.get("restart_request_path")
            if restart_request_path:
                with st.expander("查看后台重启请求文件", expanded=False):
                    st.code(restart_request_path)
            if result["output_preview"]:
                with st.expander("查看本次同步明细", expanded=False):
                    st.code(result["output_preview"])
            st.balloons()
        except Exception as e:
            status.update(label="Win 主机同步失败", state="error")
            st.error(str(e))

st.markdown("---")
st.info("当前采用 Windows 局域网服务器长期运行，Mac 端只负责开发与同步代码。")

# ==================== 🧹 目录去重整理（维护时段专用）====================
st.subheader("目录与数据维护")
st.warning(
    "**高危操作，仅限维护窗口**。\n\n"
    "NAS 上的 Win 项目因 ZIP 解压到同名文件夹，形成了"
    "`品质系统/.../BUNDLE/BUNDLE` 的双层嵌套结构，且 Win 服务正从该内层目录运行、"
    "其 `data/` 含实时业务数据库。\n\n"
    "此操作会把内层文件上移到外层、删除空内层，**会移动正在运行的代码与数据库**。\n\n"
    "**必须先停止 Win 服务**（如 `stop_windows_background.bat`），执行完毕后再重启，"
    "否则可能损坏数据库、中断同事访问。普通同步无需此操作。"
)

with st.expander("维护窗口高危操作（默认折叠，请确认已停止 Win 服务）", expanded=False):
    dedup_confirm = st.checkbox(
        "我已停止 Win 服务，确认在维护窗口执行目录去重",
        key="dedup_confirm",
    )
    if st.button("执行目录去重整理", type="primary", disabled=not dedup_confirm, width="stretch"):
        with st.status("正在去重整理...", expanded=True) as status:
            try:
                new_path = deduplicate_win_target()
                if not new_path:
                    status.update(label="未找到有效 Win 目标目录", state="error")
                    st.error("无法定位 Win 主机项目根目录，请先确认 NAS 已挂载。")
                else:
                    status.update(label="去重完成", state="complete")
                    st.success(f"已整理为单层路径：\n\n`{new_path}`")
                    st.info("请手动重启 Win 服务（如 `start_windows_background.bat`）。")
            except Exception as e:
                status.update(label="去重失败", state="error")
                st.error(str(e))


# ==================== 📤 远程代码部署（网页端推送，无需 SMB/VPN）====================
st.markdown("---")
st.subheader("远程代码部署")
st.caption(
    "离开公司、无法挂载 SMB 时使用。直接在浏览器中上传修改过的 .py 文件，"
    "写入 Win 服务器磁盘并自动重启，内网+公网同时生效。"
)

# 检测运行环境
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IS_WIN_PRODUCTION = sys.platform == "win32" or os.environ.get("FORCE_PRODUCTION") == "1"

if _IS_WIN_PRODUCTION:
    st.success("**Win 生产环境** — 上传的文件将直接写入本服务器磁盘并自动重启")
    deploy_target = _PROJECT_ROOT
    # 显示当前项目根目录
    st.code(deploy_target, language="text")
else:
    st.info("**Mac 开发环境** — 此功能在 Win 生产环境（内网/公网）上使用；Mac 端请用上方「 同步到 Win 主机」按钮")

# ---- 权限检查：仅管理员可部署 ----
def _can_deploy() -> bool:
    """管理员才能远程部署代码。"""
    uname = st.session_state.get("user_name", "")
    if not uname:
        return False
    # 与 page_reports 的 _current_user_can_delete_report 保持一致
    is_admin = (
        uname.endswith("(开发者)")
        or uname == "Bruce Cheng"
        or uname == "bruce.cheng"
        or uname.lower() in ("admin", "root")
    )
    return is_admin

if not _can_deploy():
    st.warning("仅管理员可使用远程代码部署功能。当前登录身份无权操作。")
else:
    st.caption("管理员权限已确认")

    # ---- 文件上传区 ----
    uploaded_files = st.file_uploader(
        "选择要部署的 .py 文件（支持多选）",
        type=["py"],
        accept_multiple_files=True,
        help="上传你在 Mac 上改过的 .py 文件。文件将覆盖服务器上的同名文件。",
        key="remote_deploy_files",
    )

    if uploaded_files:
        st.markdown("**待部署文件预览：**")
        preview_data = []
        will_overwrite = []
        for uf in uploaded_files:
            target_path = os.path.join(deploy_target, uf.name)
            exists = os.path.exists(target_path)
            size_kb = len(uf.getvalue()) / 1024
            preview_data.append({
                "文件名": uf.name,
                "大小": f"{size_kb:.1f} KB",
                "状态": "将覆盖已有文件" if exists else "新文件",
                "路径": target_path,
            })
            if exists:
                will_overwrite.append(uf.name)

        ui_table(preview_data, width="stretch", hide_index=True)

        if will_overwrite:
            st.warning(f"以下 {len(will_overwrite)} 个文件将被 **覆盖**：\n\n" +
                       "\n".join(f"- `{f}`" for f in will_overwrite) +
                       "\n\n部署前会自动备份旧版本到 `_remote_deploy_backups/` 目录。")

        # ---- 安全确认 ----
        col_d1, col_d2 = st.columns([1, 3])
        with col_d1:
            auto_restart = st.checkbox("自动重启服务", value=True,
                                       help="部署完成后自动重启 Streamlit 使新代码立即生效")
        with col_d2:
            confirm_deploy = st.checkbox(
                f"确认部署 {len(uploaded_files)} 个文件（{len(will_overwrite)} 个将覆盖）",
                key="deploy_confirm",
                help="勾选后点击「执行部署」按钮开始写入磁盘",
            )

        if st.button(
            "执行远程部署",
            type="primary",
            disabled=not confirm_deploy,
            width="stretch",
        ):
            _do_remote_deploy(uploaded_files, deploy_target, auto_restart)


def _do_remote_deploy(files, target_dir: str, do_restart: bool):
    """执行远程代码部署：写文件 + 备份 + 可选重启。"""
    backup_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_base = os.path.join(target_dir, "_remote_deploy_backups", backup_ts)

    with st.status("正在远程部署...", expanded=True) as status:
        deployed = []
        skipped = []
        errors = []

        try:
            # Phase 1: 备份将被覆盖的文件
            status.update(label="第 1 步：备份现有文件...")
            for uf in files:
                target_path = os.path.join(target_dir, uf.name)
                if os.path.exists(target_path):
                    os.makedirs(backup_base, exist_ok=True)
                    backup_path = os.path.join(backup_base, uf.name)
                    shutil.copy2(target_path, backup_path)
                    deployed.append({"file": uf.name, "action": "备份+覆盖", "backup": backup_path})

            # Phase 2: 写入新文件
            status.update(label="第 2 步：写入新文件到磁盘...")
            for uf in files:
                target_path = os.path.join(target_dir, uf.name)
                try:
                    content = uf.getvalue()
                    with open(target_path, "wb") as f:
                        f.write(content)
                    st.write(f"已写入: `{uf.name}` ({len(content) // 1024} KB)")

                    # 验证写入完整性
                    with open(target_path, "rb") as verify_f:
                        if verify_f.read() != content:
                            raise IOError("写入后校验不一致！")
                except Exception as e:
                    errors.append({"file": uf.name, "error": str(e)})
                    st.write(f"写入失败: `{uf.name}` → {e}")

            # Phase 3: 语法校验已部署的 .py 文件
            status.update(label="第 3 步：语法校验...")
            import py_compile
            syntax_ok = True
            for uf in files:
                if uf.name.endswith(".py"):
                    target_path = os.path.join(target_dir, uf.name)
                    try:
                        py_compile.compile(target_path, doraise=True)
                        st.write(f"语法通过: `{uf.name}`")
                    except py_compile.PyCompileError as pe:
                        syntax_ok = False
                        errors.append({"file": uf.name, "error": f"语法错误: {pe}"})
                        st.write(f"语法错误: `{uf.name}` → {pe}")

            if not syntax_ok and errors:
                # 语法错误 → 回滚所有已写入文件
                status.update(label="语法错误，正在回滚...", state="error")
                st.error("检测到语法错误！正在从备份恢复原始文件...")
                for entry in deployed:
                    orig_path = os.path.join(target_dir, entry["file"])
                    backup_path = entry.get("backup", "")
                    if backup_path and os.path.exists(backup_path):
                        shutil.copy2(backup_path, orig_path)
                        st.write(f"已回滚: `{entry['file']}`")
                st.error("部署失败：部分文件存在语法错误，已自动回滚到备份版本。")
                return

            # Phase 4: 可选重启
            if do_restart:
                status.update(label="第 4 步：请求重启服务...")
                restart_payload = {
                    "action": "restart_background_service",
                    "source": "remote_web_deploy",
                    "requested_at": datetime.now().isoformat(),
                    "files_deployed": [uf.name for uf in files],
                    "backup_dir": backup_base,
                    "deployed_by": st.session_state.get("user_name", "unknown"),
                }
                restart_file = os.path.join(target_dir, ".sync_request.json")
                temp_restart = restart_file + ".tmp"
                with open(temp_restart, "w", encoding="utf-8") as rf:
                    json.dump(restart_payload, rf, ensure_ascii=False, indent=2)
                os.replace(temp_restart, restart_file)
                st.write(f"重启请求已写入: `.sync_request.json`")

            # 完成
            status.update(
                label=f"远程部署完成！({len(files) - len(errors)}/{len(files)} 成功)",
                state="complete"
            )

            st.success(
                f"**部署成功** \n\n"
                f"- 写入文件: {len(files) - len(errors)} 个\n"
                f"- 覆盖文件: {len([d for d in deployed])} 个（已备份到 `_remote_deploy_backups/{backup_ts}/`）\n"
                f"- 语法校验: 全部通过\n"
                + (f"- 自动重启: 已触发（5-15 秒后生效）\n" if do_restart else "")
            )

            if deployed:
                with st.expander("查看备份位置", expanded=False):
                    st.code(backup_base)

            if errors:
                st.error(f"**部分文件出错** ({len(errors)} 个):")
                for err in errors:
                    st.write(f"- `{err['file']}`: {err['error']}")

            st.balloons()

        except Exception as e:
            status.update(label="远程部署异常", state="error")
            st.error(f"部署过程发生异常: {e}")
            # 尝试回滚
            if deployed:
                st.write("尝试回滚已写入的文件...")
                for entry in deployed:
                    orig_path = os.path.join(target_dir, entry["file"])
                    backup_path = entry.get("backup", "")
                    if backup_path and os.path.exists(backup_path):
                        try:
                            shutil.copy2(backup_path, orig_path)
                            st.write(f"已回滚: `{entry['file']}`")
                        except Exception as rollback_err:
                            st.write(f"回滚失败: `{entry['file']}` → {rollback_err}")
