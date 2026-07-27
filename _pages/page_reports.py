"""
品质系统管理 - 检验报告上传
"""

import online_report_pdf as opdf
from _online_report_component_ororo import render_online_report_ororo
from _online_report_component_v3 import render_online_report
import online_report_db as odb
from database import log_activity
from dingtalk_notify import (
    notify_report_submitted,
    notify_report_approved,
    notify_report_rejected,
    is_same_user,
)
from pages._utils import render_sidebar, render_topbar, render_import_export_buttons, ui_empty_state, ui_danger_button, ui_skeleton, ui_table
from components.modal import confirm_dialog
import streamlit as st
import pandas as pd
import os
import sys
import base64
import re
import io
import zipfile
import unicodedata
import inspect
from datetime import date, datetime
import database as db
from database import (
    init_db, add_inspection_report, get_inspection_reports, get_unified_reports,
    update_report_status,
    get_report_daily_stats, get_bg_list, get_bu_list, get_brand_list, get_quality_users_list,
    approve_report_with_archival,
    update_report_info, update_report_review_comment,
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============ 在线 QC 检验报告（闭环，独立新表 online_reports） ============

# NAS 上传模块（可选，本地开发环境使用）
# 不在页面导入阶段探测 NAS。Streamlit 切换一级菜单会重新执行本文件，
# 这里同步探测会把每次进入页面都阻塞到 NAS 超时（最慢 15 秒）。
# 真正的上传、下载、归档操作仍由各自函数负责连接并处理失败。
NAS_AVAILABLE = False
try:
    from nas_client import (
        upload_file as nas_upload,
        ensure_single_folder,
        check_connection,
        NAS_BASE_PATH,
        get_nas_routes,
        upload_report_to_nas,
        process_zip_images,
        download_file as nas_download,
    )
    # 模块可导入即允许进入业务页；网络状态只在实际操作时判断。
    NAS_AVAILABLE = True
except (ImportError, Exception):
    pass

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# 渲染侧边栏导航
st.session_state.current_page = "检验报告"
with st.sidebar:
    render_sidebar()
render_topbar("检验报告")


st.markdown("""
<style>
/* ===== Design tokens (与培训手册预览一致) ===== */
:root{
  --rp-bg:#F5F5F4; --rp-card:#FFFFFF; --rp-ink:#1A1A1A; --rp-ink2:#6B6B6B; --rp-ink3:#9A9A9A;
  --rp-line:rgba(0,0,0,.08); --rp-line2:rgba(0,0,0,.14);
  --rp-green:#16A34A; --rp-green-bg:#F0FDF4; --rp-green-tx:#15803D;
  --rp-red:#DC2626; --rp-red-bg:#FEF2F2; --rp-red-tx:#B91C1C;
  --rp-amber:#D97706; --rp-amber-bg:#FFFBEB; --rp-amber-tx:#B45309;
  --rp-blue:#2563EB; --rp-blue-bg:#EFF6FF; --rp-blue-tx:#1D4ED8;
  --rp-purple:#7C3AED; --rp-purple-bg:#FAF5FF; --rp-purple-tx:#6D28D9;
  --rp-r-sm:6px; --rp-r-md:10px; --rp-r-lg:14px;
}
/* ===== Page title ===== */
.report-page-title { display:flex; justify-content:space-between; align-items:flex-end; gap:20px; margin:4px 0 18px; }
.report-page-title h1 { margin:0 !important; font-size:19px; font-weight:600; }
.report-page-title .eyebrow { color:var(--rp-blue); font-size:12px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; margin-bottom:6px; }
.report-page-title .sub { color:#61758f; font-size:14px; margin-top:7px; }
.report-flow-note { border-left:4px solid var(--rp-blue); padding:10px 14px; background:var(--rp-blue-bg); color:#24415f; border-radius:0 9px 9px 0; font-size:13px; line-height:1.65; }
.report-pdf-note { border-left-color:var(--rp-amber); background:var(--rp-amber-bg); }
.report-danger-note { border-left-color:var(--rp-red); background:var(--rp-red-bg); }

/* ===== CARD: Streamlit 边框容器 -> 报告卡片 ===== */
/* 主选择器：stVerticalBlockBorderWrapper (新版 Streamlit) */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--rp-card); border:0.5px solid var(--rp-line) !important;
  border-radius:var(--rp-r-lg) !important; padding:16px 18px !important;
  margin-bottom:12px; transition:border-color .15s;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover{ border-color:var(--rp-line2) !important; }
/* 兜底：旧版 / 无 testid 的边框容器（通过内容标记识别） */
[data-testid="stVerticalBlock"] > [style*="border"],
div[style*="border-radius:10px"][style*="border:1px solid"]{
  background:var(--rp-card); border:0.5px solid var(--rp-line) !important;
  border-radius:var(--rp-r-lg) !important; padding:16px 18px !important;
  margin-bottom:12px;
}
/* 状态左侧色条（按卡片内药丸自动识别） */
[data-testid="stVerticalBlockBorderWrapper"]:has(.status-warning){ border-left:3px solid var(--rp-amber) !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.status-pass){ border-left:3px solid var(--rp-blue) !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.status-reject){ border-left:3px solid var(--rp-red) !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.status-archive){ border-left:3px solid var(--rp-purple) !important; }

/* ===== PILL: 状态药丸（替代原本无样式的纯文本） ===== */
.status-pill{ display:inline-flex; align-items:center; gap:4px; font-size:11.5px; font-weight:600; padding:4px 11px; border-radius:99px; white-space:nowrap; border:1px solid transparent; }
.status-warning{ background:var(--rp-amber-bg); color:var(--rp-amber-tx); border-color:rgba(217,119,6,.18); }
.status-pass{ background:var(--rp-green-bg); color:var(--rp-green-tx); border-color:rgba(22,163,74,.18); }
.status-reject{ background:var(--rp-red-bg); color:var(--rp-red-tx); border-color:rgba(220,38,38,.18); }
.status-draft{ background:rgba(0,0,0,.05); color:var(--rp-ink2); border-color:var(--rp-line); }
.status-archive{ background:var(--rp-purple-bg); color:var(--rp-purple-tx); border-color:rgba(124,58,237,.18); }

/* ===== BUTTONS: Streamlit 原生按钮 -> 扁平药丸 ===== */
[data-testid="stBaseButton-primary"]{
  background:var(--rp-green) !important; color:#fff !important;
  border:1px solid var(--rp-green) !important; border-radius:var(--rp-r-md) !important;
  font-weight:500 !important; font-size:12.5px !important; transition:opacity .12s;
}
[data-testid="stBaseButton-primary"]:hover{ opacity:.88; }
[data-testid="stBaseButton-secondary"]{
  background:#fff !important; color:var(--rp-ink) !important;
  border:1px solid var(--rp-line2) !important; border-radius:var(--rp-r-md) !important;
  font-weight:500 !important; font-size:12.5px !important;
}
[data-testid="stBaseButton-secondary"]:hover{ background:var(--rp-bg) !important; }

/* ===== METRIC CARDS ===== */
[data-testid="stMetric"]{
  background:var(--rp-card) !important; border:0.5px solid var(--rp-line) !important;
  border-radius:var(--rp-r-md) !important; padding:14px 16px !important;
}
[data-testid="stMetric"] label{ font-size:12px !important; color:var(--rp-ink2) !important; }

/* ===== DATAFRAME / TABLE ===== */
[data-testid="stDataFrame"] th, [data-testid="stTable"] th{
  background:var(--rp-bg) !important; color:var(--rp-ink2) !important;
  font-size:11.5px !important; font-weight:600 !important; text-transform:uppercase; letter-spacing:.04em;
  border-bottom:1px solid var(--rp-line) !important;
}
[data-testid="stDataFrame"] td, [data-testid="stTable"] td{
  border-bottom:1px solid var(--rp-line) !important; color:var(--rp-ink) !important;
}
[data-testid="stDataFrame"] tr:hover td, [data-testid="stTable"] tr:hover td{ background:rgba(0,0,0,.012) !important; }

/* ===== 保留：应用内特定样式 ===== */
.report-detail-action button { min-height:40px !important; width:100% !important; font-weight:700 !important; }
.report-detail-file { padding:10px 12px; border:1px solid #e1e8f0; border-radius:10px; background:#fbfdff; }
.report-detail-review { margin-top:10px; padding:14px 16px; border:1px solid #dbe5f0; border-radius:12px; background:#f8fbff; }
/* 历史报告列表保留为兼容数据查询，但不再作为主管工作入口。 */
[div[role="tablist"] > div[role="tab"]:last-child] { display:none !important; }
[div[data-testid="stTabs"] div[role="tab"][data-key="4"]] { display:none !important; }
[div[data-testid="stTabs"] div[role="tabpanel"][data-key="4"]] { display:none !important; }
[div[role="tabpanel"]:has(.legacy-report-list-marker)] { display:none !important; }
</style>
""", unsafe_allow_html=True)


def _flash(msg, kind="ok"):
    """设置在线报告模块的 flash 提示（模块级，供 _online_report_tab 及 _approve_and_gen_pdf 等共用）。"""
    st.session_state["or_flash"] = (kind, msg)


def _render_version_history(rid):
    """渲染报告版本历史，并提供恢复入口。"""
    vers = odb.list_versions(rid)
    if not vers:
        st.caption("暂无历史版本（报告通过 / 首次锁定后自动生成版本）")
        return
    for v in vers:
        c1, c2, c3 = st.columns([1.1, 2.6, 1])
        with c1:
            st.markdown(f"**v{v['version']}** · `{v['trigger']}`")
        with c2:
            st.caption(f"{v['created_at']} · {v['changed_by']}")
            if v.get("change_reason"):
                st.caption(f"原因：{v['change_reason']}")
        with c3:
            if st.button("恢复", key=f"or_restore_{v['id']}", width="stretch"):
                odb.restore_version(
    rid, v["id"], st.session_state.get(
        "user_name", ""), "手动恢复")
                _flash(f"已恢复至 v{v['version']}")
                st.rerun()


def _render_audit_log(rid):
    """渲染报告操作日志。"""
    logs = odb.list_audit(rid)
    if not logs:
        st.caption("暂无操作记录")
        return
    for lg in logs:
        st.markdown(
            f"`{lg['ts']}` · **{lg['actor']}** · {lg['action']}"
            + (f"· {lg['detail']}" if lg.get("detail") else "")
        )


def _render_permission_panel(user_role):
    """管理员权限面板：限制指定用户为只读（可选，不影响默认权限）。"""
    st.divider()
    with st.expander("权限管理（仅管理员可见）", expanded=False):
        cur = st.session_state.get(
    "user_name", "") or st.session_state.get(
        "user_email", "")
        st.caption(
            f"当前登录：**{cur}** · 角色：`{user_role}`"
        )
        st.info(
            "**不需要额外授权**——能登录系统的同事默认都能写报告和上传照片。"
            "角色范围：检验员可新建和编辑自己的草稿；审核员可审核待审核报告；"
            "只读只能查看；管理员拥有完整权限。"
        )
        list_roles_fn = getattr(odb, "list_roles", None)
        roles = list_roles_fn() if callable(list_roles_fn) else []
        if roles:
            for r in roles:
                st.markdown(f"- **{r['user_name']}** → `{r['role']}`")
        else:
            st.caption("（暂无显式角色；已授权用户默认是检验员 uploader）")
        st.markdown("---")
        with st.form("or_role_form", clear_on_submit=True):
            uname = st.text_input("登录邮箱",
     placeholder="如：zhangsan@sainstore.com")
            role = st.selectbox(
    "分配角色", ["uploader", "reviewer", "viewer", "admin"], index=0,
    format_func={"uploader": "检验员", "reviewer": "审核员", "viewer": "只读", "admin": "管理员"}.get)
            if st.form_submit_button("保存角色"):
                if not uname.strip():
                    st.error("请填写用户名 / 邮箱")
                else:
                    set_role_fn = getattr(odb, "set_role", None)
                    if not callable(set_role_fn):
                        st.error("当前运行环境尚未加载到最新权限接口，请先完成 Win 服务升级后再试。")
                        return
                    set_role_fn(uname.strip().lower(), role)
                    add_audit_fn = getattr(odb, "add_audit", None)
                    if callable(add_audit_fn):
                        add_audit_fn(
                            st.session_state.get("user_name", ""), "set_role",
                            "online_report_role", uname.strip(), f"设为 {role}",
                        )
                    _flash(f"已将 {uname.strip()} 设为 {role}")
                    st.rerun()


def _or_get_role(user_name: str, is_admin: bool = False) -> str:
    """兼容旧运行环境：缺少治理接口时默认放行为 uploader，不让整页崩溃。"""
    get_role_fn = getattr(odb, "get_role", None)
    if callable(get_role_fn):
        return get_role_fn(user_name, is_admin=is_admin)
    return "admin" if is_admin else "uploader"


def _render_online_report_safe(**kwargs):
    """
    兼容旧版组件签名。

    Win 端若暂时仍加载到旧 pyc，render_online_report 可能不支持 photo / locked 参数。
    这里按函数实际签名裁剪 kwargs，避免整页因 unexpected keyword argument 直接报错。
    """
    # 仅按 data.template_code 分流组件；通用模板仍走原来的 renderer。
    data = kwargs.get("data") or {}
    fn = render_online_report_ororo if data.get(
        "template_code") == "ororo" else render_online_report
    try:
        sig = inspect.signature(fn)
        accepted = set(sig.parameters.keys())
        filtered = {k: v for k, v in kwargs.items() if k in accepted}
        return fn(**filtered)
    except Exception:
        fallback = {
            "data": kwargs.get("data"),
            "mode": kwargs.get("mode", "edit"),
            "key": kwargs.get("key", "online_report"),
        }
        height = kwargs.get("height")
        if height is not None:
            fallback["height"] = height
        return fn(**fallback)


def _new_window_editor_link(label, rid=None, primary=False, width="content"):
    """生成一个看起来像 Streamlit 按钮的 <a> 链接，在新标签页打开全屏编辑器。"""
    href = "/page_reports?or_full=1"
    if rid is not None:
        href += f"&or_rid={rid}"
    # 携带当前已签名的 auth token（or_tk）：新标签页不依赖浏览器 cookie 也能恢复登录态，
    # 彻底避免「新建报告→点编辑→跳登录界面」。
    # 关键修复：原实现从 st.context.cookies 读取 qs_auth 作为 or_tk，但在部分部署下，
    # 列表页渲染链接时 st.context.cookies 读不到该 cookie（新标签页首屏更是如此），
    # 导致 or_tk 缺失、新标签页跳登录。现改为用 session_state 里已恢复的真实邮箱/姓名
    # 重新签发签名 token——只要当前会话已登录（session_state 有 user_email），编辑链接
    # 必带有效 or_tk，新标签页用 or_tk 恢复登录态，100% 不跳登录。
    _email = (st.session_state.get("user_email") or "").strip()
    _name = (st.session_state.get("user_name") or "").strip()
    _tk = ""
    if _email:
        try:
            import main as _main_mod
            import time as _tm
            _exp = int(_tm.time() + 6 * 24 * 3600)
            _tk = _main_mod._encode_auth_token(_email, _exp, _name)
        except Exception:
            _tk = ""
    if _tk:
        import urllib.parse as _up
        href += f"&or_tk={_up.quote(_tk, safe='')}"
    # F17 修复：原先把整段 inline style（含 font-family 空格）塞进 <a>，
    # 会被 Streamlit markdown 转义成可见文本（<a ...>编辑</a>）。改为令牌类 .qms-edit-link，
    # 样式统一由 assets/tokens.css 注入，既消除转义、又贴合全站设计系统。
    cls = "qms-edit-link is-primary" if primary else "qms-edit-link"
    return f'<a class="{cls}" href="{href}" target="_blank" rel="noopener">{label}</a>'


def _close_fullscreen():
    """注入JS：先让父窗口获得焦点，再尝试关闭当前窗口；若浏览器阻止关闭，则跳转回主系统在线报告页面。"""
    st.html(
        """<script>
setTimeout(()=>{
  try { if (window.top.opener) window.top.opener.focus(); } catch(e){}
  try { window.top.close(); } catch(e){}
  // 如果 close 被浏览器阻止，至少让当前窗口回到主系统
  setTimeout(()=>{ try { window.top.location.href = '/page_reports'; } catch(e){} }, 400);
},300)
</script>""",
        unsafe_allow_javascript=True,
    )


def _fullscreen_save(data):
    """全屏编辑器下保存草稿（不返回列表，保持编辑状态）"""
    ss = st.session_state
    if ss.get("or_edit_id"):
        odb.update_draft(ss["or_edit_id"], data)
        rid = ss["or_edit_id"]
        rk = f"r{rid}"
    else:
        rid, no = odb.create_draft(
    data, created_by=ss.get(
        "user_email", "") or ss.get(
            "user_name", ""))
        ss["or_edit_id"] = rid
        rk = ss.get("or_photo_key")
    if rk:
        odb.link_photos_by_key(rk, rid)
    ss["or_draft"] = data
    rep = odb.get_online_report(rid)
    ss["or_seq"] = ss.get("or_seq", 0) + 1
    st.toast(f"草稿已保存：{rep['report_no']} — 可继续编辑，完成后点击「提交审核」")
    st.rerun()


def _fullscreen_export_pdf(data):
    """全屏编辑器下导出当前表单为草稿 PDF（供打印给供应商签字）。"""
    ss = st.session_state
    rid = ss.get("or_edit_id")
    if not rid:
        # 导出前先自动创建草稿，确保有 report_no
        rid, no = odb.create_draft(
    data, created_by=ss.get(
        "user_email", "") or ss.get(
            "user_name", ""))
        ss["or_edit_id"] = rid
    else:
        odb.update_draft(rid, data)
        no = odb.get_online_report(rid)["report_no"]

    data = data or {}
    data["repno"] = no
    # 在 data 中标记为草稿，便于模板区分（如需要可后续消费）
    data["_draft_export"] = True

    ok, path = opdf.render_report_pdf(data, report_no=no)
    if not ok:
        ss["or_flash"] = ("error", f"导出 PDF 失败：{path}")
        st.rerun()
        return

    with open(path, "rb") as fh:
        pdf_bytes = fh.read()
    # 用报告名称作为文件名（优先），无则回退到编号
    _basic2 = (data.get("basic") or {}) if isinstance(data, dict) else {}
    _title2 = str(_basic2.get("title") or "").strip()
    if _title2:
        import re as _re2
        _safe2 = _re2.sub(
    r'[\\/:*?"<>|]+',
    "-",
    _title2)[
        :80].strip(".-") or no
        fname = f"{_safe2}.pdf"
    else:
        fname = f"DRAFT_{no}.pdf"
    ss["or_export_pdf_bytes"] = pdf_bytes
    ss["or_export_pdf_name"] = fname
    # 更换组件 key，清掉本次 component value，保证公网/钉钉环境下一次点击只处理一次。
    ss["or_seq"] = ss.get("or_seq", 0) + 1
    st.toast(f"草稿 PDF 已生成：{fname}")
    st.rerun()


def _fullscreen_submit(data):
    """全屏编辑器下提交审核（保存后提交并关闭窗口）"""
    ss = st.session_state
    rid = ss.get("or_edit_id")

    # 如果已存在报告，先检查状态，防止重复提交
    if rid:
        rep = odb.get_online_report(rid)
        if rep and rep["status"] == odb.STATUS_PENDING:
            st.success(f"报告 {rep['report_no']} 已提交审核，当前状态：待审核。窗口即将关闭。")
            st.html(
                """<script>
setTimeout(()=>{
  try { if (window.top.opener) window.top.opener.focus(); } catch(e){}
  try { window.top.close(); } catch(e){}
  setTimeout(()=>{ try { window.top.location.href = '/page_reports'; } catch(e){} }, 500);
},1200)
</script>""",
                unsafe_allow_javascript=True,
            )
            return
        if rep and rep["status"] == odb.STATUS_APPROVED:
            st.success(f"报告 {rep['report_no']} 已审核通过。窗口即将关闭。")
            st.html(
                """<script>
setTimeout(()=>{
  try { if (window.top.opener) window.top.opener.focus(); } catch(e){}
  try { window.top.close(); } catch(e){}
  setTimeout(()=>{ try { window.top.location.href = '/page_reports'; } catch(e){} }, 500);
},1200)
</script>""",
                unsafe_allow_javascript=True,
            )
            return

    if rid:
        if not odb.update_draft(rid, data):
            st.error("报告内容保存失败，未执行提交审核。请确认报告仍为草稿或已驳回状态。")
            return
        rk = f"r{rid}"
    else:
        rid, no = odb.create_draft(
    data, created_by=ss.get(
        "user_email", "") or ss.get(
            "user_name", ""))
        ss["or_edit_id"] = rid
        rk = ss.get("or_photo_key")
    if rk:
        odb.link_photos_by_key(rk, rid)
    pdf_ok, pdf_msg = _prepare_online_pdf(rid, data)
    if not pdf_ok:
        st.error(f"提交审核前处理失败：{pdf_msg}")
        return
    if not odb.submit_for_review(rid):
        st.error("报告提交审核失败，请检查报告状态后重试。")
        return
    # 钉钉推送审核人（与上传报告路径一致），失败不影响提交成功
    _or_basic = (data or {}).get("basic", {}) or {}
    _or_product = _or_basic.get(
        "product") or _or_basic.get("supplier") or "(未填产品)"
    _or_inspector = _or_basic.get("inspector") or ss.get("user_name", "")
    try:
        _nok, _nmsg = notify_report_submitted(
    rid, _or_product, "在线QC检验报告", _or_inspector)
        if not _nok:
            st.warning(f"已提交审核，但钉钉通知审核人失败：{_nmsg}")
    except Exception as _e:
        st.warning(f"已提交审核，但钉钉通知异常：{_e}")
    rep = odb.get_online_report(rid)
    # 二次读取校验，避免只显示“提交成功”但数据库仍停留在草稿。
    rep = odb.get_online_report(rid)
    if not rep or rep.get("status") != odb.STATUS_PENDING:
        st.error("提交状态校验失败：数据库未进入「待审核」，请勿关闭页面并重试。")
        return
    st.success(
        f"已提交审核：{rep['report_no']} — 状态已变为「待审核」。PDF 纸质档案可在本页先行打印，主管审核通过后报告正式归档。")
    st.html(
        """<script>
setTimeout(()=>{
  try {
    if (window.top.opener) {
      window.top.opener.location.href = '/page_reports?tab=review&_refresh=' + Date.now();
      window.top.opener.focus();
    }
  } catch(e){}
  try { window.top.close(); } catch(e){}
  setTimeout(()=>{ try { window.top.location.href = '/page_reports'; } catch(e){} }, 500);
},1800)
</script>""",
        unsafe_allow_javascript=True,
    )


def _build_photo_cfg(rid, user_name):
    """构建照片后端配置（api_base/token/report_key/created_by），传入组件启用 NAS 图片。"""
    import os
    import uuid
    import socket

    base = ""
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers() or {}
        host = (
    headers.get(
        "X-Forwarded-Host",
        "") or headers.get(
            "Host",
             "") or "").strip()
        proto = (headers.get("X-Forwarded-Proto", "") or "").strip() or "http"
        if host and "localhost" not in host and "127.0.0.1" not in host:
            base = f"{proto}://{host}".rstrip("/")
    except Exception:
        base = ""

    if not base:
        base = (
    os.environ.get(
        "PUBLIC_BASE_URL",
        "") or os.environ.get(
            "QMS_ACCESS_URL",
             "")).strip().rstrip("/")
    if not base:
        # 统一走 8501；本地未配置固定地址时，退回局域网 IP，保证手机同网可打开。
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            lan_ip = "localhost"
        base = f"http://{lan_ip}:8501"
    token = os.environ.get("PHOTO_API_TOKEN", "")
    if rid:
        rk = f"r{int(rid)}"
    else:
        if "or_photo_key" not in st.session_state:
            st.session_state["or_photo_key"] = "tmp_" + uuid.uuid4().hex[:12]
        rk = st.session_state["or_photo_key"]
    return {
        "api_base": base,
        "token": token,
        "report_key": rk,
        "report_id": int(rid) if rid else None,
        "created_by": user_name,
    }


def _fullscreen_editor(rid):
    """全屏新窗口编辑器：隐藏侧边栏，最大化显示在线报告表单"""
    # 隐藏侧边栏、header、footer、菜单
    st.markdown("""<style>
        .main .block-container { max-width: 100% !important; padding: 0.5rem 2rem !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        #MainMenu { display: none !important; }
        header { display: none !important; }
        footer { display: none !important; }
        /* 隐藏顶部"检验报告管理"标题和 Tab 栏，只保留编辑器内容 */
        .main .block-container > div > h1 { display: none !important; }
        [role="tablist"] { display: none !important; }
        .stTabs [data-baseweb="tab-list"] { display: none !important; }
        .stApp { background: #f0f2f5; }
        .st-emotion-cache-1jicfl2 { padding: 0.5rem 1rem; }
    </style>""", unsafe_allow_html=True)

    ss = st.session_state
    ss.setdefault("or_seq", 0)
    ss.setdefault("or_flash", None)

    # 加载报告数据
    if rid:
        try:
            rep = odb.get_online_report(int(rid))
            if rep:
                # ── 全屏编辑器独立认证恢复（新标签页会话可能丢失登录态）──
                _fs_user = st.session_state.get(
    "user_email", "") or st.session_state.get(
        "user_name", "")
                _fs_admin = bool(st.session_state.get("is_admin", False))
                # Cookie 登录态恢复兜底（局域网/生产环境新标签页依赖 cookie）
                if not _fs_user and not _fs_admin:
                    try:
                        _cookies = st.context.cookies
                        _auth_cookie = _cookies.get("qs_auth", "")
                        if _auth_cookie:
                            import hashlib as _hashlib
                            import time as _time_mod
                            import os as _os_mod
                            from oauth_handler import _COOKIE_SECRET
                            _secret = _COOKIE_SECRET
                            _parts = _auth_cookie.split("|")
                            # 支持新格式 email|exp|name|sig（4段）和旧格式
                            # email|exp|sig（3段）
                            if len(_parts) in (3, 4):
                                if len(_parts) == 4:
                                    _c_email, _c_exp, _c_name, _c_sig = _parts
                                    _payload = f"{_c_email}|{_c_exp}|{_c_name}"
                                else:
                                    _c_email, _c_exp, _c_sig = _parts
                                    _c_name = ""
                                    _payload = f"{_c_email}|{_c_exp}"
                                _expected = _hashlib.sha256(
                                    f"{_payload}:{_secret}".encode()).hexdigest()[:16]
                                if _c_sig == _expected:
                                    try:
                                        _c_exp_int = int(_c_exp)
                                    except (ValueError, TypeError):
                                        _c_exp_int = 0
                                    if _c_exp_int and _time_mod.time() < _c_exp_int:
                                        _fs_user = _c_email
                                        _fs_admin = db.is_admin(_c_email) if hasattr(
                                            db, 'is_admin') else False
                                        st.session_state.user_email = _c_email
                                        st.session_state.user_name = _c_name or _c_email.split(
                                            "@")[0]
                                        st.session_state.is_admin = _fs_admin
                    except Exception:
                        pass
                _fs_can_admin = _fs_admin
                # ── 所有者校验：非 admin 且非创建者禁止编辑 ──
                if not _fs_can_admin and rep.get(
                    "created_by") and rep["created_by"] != _fs_user:
                    st.error("您没有权限编辑此报告（仅创建者或管理员可编辑）。")
                    _close_fullscreen()
                    return
                data = rep["data"]
                rno = rep["report_no"]
                mode = "edit"
                ss["or_edit_id"] = int(rid)
            else:
                st.error("报告不存在或已被删除")
                _close_fullscreen()
                return
        except (ValueError, TypeError):
            st.error("无效的报告 ID")
            _close_fullscreen()
            return
    else:
        creator = ss.get("user_email", "") or ss.get("user_name", "")
        new_rid, _new_rno = odb.create_draft({}, created_by=creator)
        odb.add_audit(
    creator,
    "create",
    "online_reports",
    str(new_rid),
     _new_rno)
        ss["or_edit_id"] = int(new_rid)
        ss["or_draft"] = None
        st.query_params["or_full"] = "1"
        st.query_params["or_rid"] = str(new_rid)
        st.rerun()
        return

    # 标题区
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown(f"""
        <div class="report-page-title">
          <div><div class="eyebrow">ONLINE INSPECTION REPORT</div>
          <h1>在线 QC 检验报告</h1>
          <div class="sub">报告编号：<code>{rno}</code> · 先生成纸质 PDF 给工厂签字，再直接提交线上审核</div></div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("&nbsp;")
        if st.button("关闭并返回"):
            _close_fullscreen()

    # 待审核报告编辑提示
    if mode == "edit" and rep and rep.get("status") == odb.STATUS_PENDING:
        st.warning("当前报告处于 **待审核** 状态，您正在编辑已提交的内容。修改后请重新点击「提交审核」以更新给审核人。")

    # 如果有待下载的 PDF，在顶部显眼位置渲染下载按钮
    if ss.get("or_export_pdf_bytes") and ss.get("or_export_pdf_name"):
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.success(
                    f"草稿 PDF 已生成：{ss['or_export_pdf_name']}（{len(ss['or_export_pdf_bytes'])//1024} KB）")
            with c2:
                st.download_button("下载草稿 PDF", ss["or_export_pdf_bytes"],
                                   file_name=ss["or_export_pdf_name"],
                                   mime="application/pdf", key=f"or_export_pdf_top_{ss['or_seq']}",
                                   width="stretch")
        # 保留结果直到下一次导出，避免公网环境下用户看不到成功反馈。

    # 组件渲染
    # 锁定规则：待审核/已通过时锁定（不可编辑）；已驳回解锁（检验员可修改后重新提交）
    _locked_statuses = (odb.STATUS_PENDING, odb.STATUS_APPROVED)
    _locked = bool(rid and rep and rep.get("status")
                   and rep.get("status") in _locked_statuses)
    # 传递 report_id 和 report_no 给组件，供 fetch 直通 PDF 导出 API 使用（绕开公网
    # setComponentValue 失效问题）
    _rno = (rep or {}).get("report_no") or (data or {}).get("repno", "")
    val = _render_online_report_safe(data=data, mode=mode, key=f"or_full_{ss['or_seq']}",
                                     photo=_build_photo_cfg(
                                         rid, st.session_state.get("user_name", "")),
                                     locked=_locked,
                                     height=860,
                                     report_id=rid,
                                     report_no=_rno)

    # 处理组件返回值
    if val and val.get("type") == "save_draft":
        _fullscreen_save(val["data"])
    elif val and val.get("type") == "submit":
        _fullscreen_submit(val["data"])
    elif val and val.get("type") == "export_pdf":
        _fullscreen_export_pdf(val["data"])

    # 状态提示（兜底，来自 flash）
    if ss.get("or_flash"):
        kind, msg = ss["or_flash"]
        (st.success if kind == "ok" else st.error)(msg)
        ss["or_flash"] = None


st.title("检验报告管理")

# Tab 顺序：审核 → 上传 → 在线报告 → 历史追溯。
# 2026-07-16：删除"每日统计"（数据已在审核中心顶部 metric 中覆盖，冗余）
# F7：统一 Tab 顺序（在线报告 → 审核中心 → 上传报告 → 历史记录），删除重复分支
tab_online, tab_review, tab_upload, tab_list = st.tabs(
    ["在线报告", "审核中心", "上传报告", "历史记录"])

# 本地存储目录（NAS 不可用时的回退方案）
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "reports")
IMAGE_DIR = os.path.join(UPLOAD_DIR, "images")
FLASH_NOTICE_KEY = "report_flash_notice"


def _filename_readability_score(name):
    if not name:
        return -999

    score = 0
    for ch in name:
        code = ord(ch)
        if ch == "\ufffd":
            score -= 10
        elif 0x2500 <= code <= 0x257F:
            score -= 6
        elif unicodedata.category(ch).startswith("C") and ch not in ("\t", "\n", "\r"):
            score -= 4
        elif "\u4e00" <= ch <= "\u9fff":
            score += 3
        elif ch.isalnum():
            score += 1
        elif ch in "._()-[]{}&+,，（）【】":
            score += 1
    return score


def _repair_filename_mojibake(name):
    if not name:
        return name

    name = str(name).replace("\\", "/").split("/")[-1].strip()
    if not name:
        return name

    candidates = {name}
    for source_encoding in ("cp437", "latin1"):
        try:
            raw_bytes = name.encode(source_encoding)
        except Exception:
            continue

        for target_encoding in ("utf-8", "gbk", "gb18030", "big5"):
            try:
                repaired = raw_bytes.decode(target_encoding).strip()
                if repaired:
                    candidates.add(repaired.replace(
                        "\\", "/").split("/")[-1].strip())
            except Exception:
                continue

    best_name = max(candidates, key=_filename_readability_score)
    return best_name or name


def _queue_flash_notice(level, message):
    st.session_state[FLASH_NOTICE_KEY] = {
        "level": level,
        "message": message,
    }


def _render_flash_notice():
    notice = st.session_state.pop(FLASH_NOTICE_KEY, None)
    if not notice:
        return

    level = notice.get("level", "info")
    message = notice.get("message", "")
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def _build_notify_notice(action_text, notify_ok, notify_msg, notify_label):
    detail = (notify_msg or "无返回信息").strip()
    if notify_ok:
        if "待发送" in detail or "排队" in detail:
            return "info", f"{action_text} {notify_label}已进入待发送队列：{detail}"
        return "success", f"{action_text} {notify_label}已发送：{detail}"
    return "warning", f"{action_text} 但{notify_label}失败：{detail}"


def _current_user_can_review(report=None):
    """仅管理员、显式审核员或开发者可审核在线报告。"""
    user_name = st.session_state.get("user_name", "")
    if st.session_state.get("is_admin", False):
        return True
    if user_name.endswith("(开发者)"):
        return True
    user_email = (st.session_state.get("user_email") or "").strip().lower()
    if user_email and _or_get_role(user_email) == "reviewer":
        return True
    return False


def _online_report_type(data):
    """把在线模板的类型值映射到上传报告的统一 NAS 路由。"""
    basic = (data or {}).get("basic", {}) or {}
    raw = str(basic.get("reportType") or basic.get(
        "report_type") or basic.get("type") or "")
    if "出货" in raw or "Final" in raw or "Loading" in raw:
        return "出货检验"
    if "驻厂" in raw or "Production" in raw:
        return "驻厂验货"
    if "来料" in raw or "Incoming" in raw:
        return "来料检验"
    return "其他"


def _prepare_online_pdf(rid, data):
    """提交审核前生成纸质 PDF，仅暂存服务器本地（不依赖 NAS）。

    审核通过后才由 _archive_online_report 上传 NAS 并归档、清除服务器副本。
    """
    rep = odb.get_online_report(rid)
    if not rep:
        return False, "在线报告不存在"
    data = dict(data or {})
    report_no = rep.get("report_no") or data.get("repno") or f"QC-{rid}"
    data["repno"] = report_no
    ok, path = opdf.render_report_pdf(data, report_no=report_no)
    if not ok:
        return False, f"PDF 生成失败：{path}"
    # 仅暂存服务器本地，不依赖 NAS；nas_staging_path 置空（删除旧的 NAS 暂存逻辑）。
    odb.set_pdf_storage(
    rid,
    pdf_path=path,
    nas_staging_path="",
     nas_pdf_path=None)
    return True, path


def _archive_online_report(rid, reviewer="", comment=""):
    """在线报告审核通过后，读服务器本地 PDF → 上传 NAS 正式归档 → 清除服务器副本。"""
    rep = odb.get_online_report(rid)
    if not rep:
        return False, "在线报告不存在"
    pdf_path = rep.get("pdf_path", "") or ""
    if not NAS_AVAILABLE:
        return False, "NAS 当前不可用，不能在未归档状态下通过审核"
    # 直接读服务器本地副本
    pdf_bytes = None
    if pdf_path and os.path.exists(pdf_path):
        try:
            with open(pdf_path, "rb") as fh:
                pdf_bytes = fh.read()
        except Exception:
            pdf_bytes = None
    if not pdf_bytes:
        return False, f"找不到可归档的 PDF（服务器本地暂存缺失: {pdf_path}）"
    try:
        data = rep.get("data", {}) or {}
        basic = data.get("basic", {}) or {}
        report_type = _online_report_type(data)
        year = str(basic.get("date", "") or datetime.now().year)[:4]
        report_base, _ = get_nas_routes(report_type, year)
        filename = odb.build_online_report_archive_filename(rep)
        ok_up, formal_path = nas_upload(
    report_base.rstrip("/"), filename, pdf_bytes)
        if not ok_up:
            return False, f"正式归档失败：{formal_path}"
        # 自动归档后清除服务器本地副本
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
        odb.set_pdf_storage(
    rid,
    pdf_path="",
    nas_staging_path="",
     nas_pdf_path=formal_path)
        return True, formal_path
    except Exception as exc:
        return False, f"在线报告归档异常：{exc}"


def _current_user_can_delete_report():
    if not st.session_state.get("authenticated") or not st.session_state.get("user_email"):
        return False
    return bool(st.session_state.get("is_admin", False))


def _delete_report(report_id):
    delete_fn = getattr(db, "delete_inspection_report", None)
    if not callable(delete_fn):
        return False, "当前运行版本暂不支持删除检验报告，请先同步最新代码到 Win 主机。"
    return delete_fn(report_id)


def _repair_report_filenames_fallback():
    get_conn = getattr(db, "get_connection", None)
    if not callable(get_conn):
        return False, "当前运行版本暂不支持修复历史文件名，请先同步最新代码到 Win 主机。"

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, filename FROM inspection_reports").fetchall()
        scanned = 0
        updated = 0

        for row in rows:
            rpt_id = row["id"] if hasattr(row, "keys") else row[0]
            filename = row["filename"] if hasattr(row, "keys") else row[1]
            scanned += 1

            if not filename:
                continue

            repaired = _repair_filename_mojibake(filename)
            if repaired != filename and _filename_readability_score(
                repaired) > _filename_readability_score(filename):
                conn.execute(
                    "UPDATE inspection_reports SET filename = ? WHERE id = ?",
                    (repaired, rpt_id),
                )
                updated += 1

        conn.commit()
        return True, f"已扫描 {scanned} 条报告，修复 {updated} 条乱码文件名"
    finally:
        conn.close()


def _repair_report_filenames():
    repair_fn = getattr(db, "repair_inspection_report_filenames", None)
    if callable(repair_fn):
        return repair_fn()
    return _repair_report_filenames_fallback()


def _update_report_filename(report_id, filename):
    update_fn = getattr(db, "update_inspection_report_filename", None)
    if callable(update_fn):
        return update_fn(report_id, filename)

    get_conn = getattr(db, "get_connection", None)
    if not callable(get_conn):
        return False, "当前运行版本暂不支持手动修改文件名，请先同步最新代码到 Win 主机。"

    filename = (filename or "").strip()
    if not filename:
        return False, "文件名不能为空"

    conn = get_conn()
    try:
        cursor = conn.execute(
            "UPDATE inspection_reports SET filename = ? WHERE id = ?",
            (filename, report_id),
        )
        conn.commit()
        updated = cursor.rowcount if cursor.rowcount is not None else 0
        if updated <= 0:
            return False, "未找到对应报告记录"
        return True, "文件名已更新"
    finally:
        conn.close()


_render_flash_notice()


def _extract_zip_images_local(zip_bytes, zip_filename, base_folder=None):
    """本地回退模式下解压 ZIP 图片压缩包，将图片保存到本地目录并返回图片路径列表。"""
    saved_paths = []
    if not zip_bytes or not zip_filename:
        return saved_paths

    folder_name = os.path.splitext(zip_filename)[
                                   0] or f"zip_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    if base_folder is None:
        base_folder = os.path.join(IMAGE_DIR, folder_name)
    else:
        base_folder = os.path.join(base_folder, folder_name)
    os.makedirs(base_folder, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            for member in zf.infolist():
                bare_name = os.path.basename(member.filename)
                if member.is_dir() or not bare_name:
                    continue
                if bare_name.startswith('.') or '__MACOSX' in member.filename:
                    continue
                ext = os.path.splitext(bare_name)[1].lower()
                if ext not in ('.jpg', '.jpeg', '.png',
                               '.gif', '.bmp', '.webp'):
                    continue
                # 处理重名：追加序号
                target_name = bare_name
                target_path = os.path.join(base_folder, target_name)
                if os.path.exists(target_path):
                    name_no_ext, ext_part = os.path.splitext(bare_name)
                    counter = 1
                    while os.path.exists(target_path):
                        target_name = f"{name_no_ext}_{counter:02d}{ext_part}"
                        target_path = os.path.join(base_folder, target_name)
                        counter += 1
                with open(target_path, 'wb') as out:
                    out.write(zf.read(member))
                saved_paths.append(target_path)
    except zipfile.BadZipFile:
        st.warning(f"「{zip_filename}」不是有效 ZIP，已跳过")
    except Exception as e:
        st.warning(f"「{zip_filename}」本地解压失败: {e}")
    return saved_paths


def _reupload_images(rpt, images, zip_files):
    """重新上传检验图片（清理旧图片后写入新图片），更新同一报告记录。"""
    rid = rpt["id"]
    report_type = rpt.get("report_type", "")
    inspection_date = rpt.get("inspection_date") or str(date.today())
    try:
        report_year = str(datetime.strptime(inspection_date, "%Y-%m-%d").year)
        date_short = datetime.strptime(
    inspection_date, "%Y-%m-%d").strftime("%Y%m%d")
    except Exception:
        report_year = str(date.today().year)
        date_short = date.today().strftime("%Y%m%d")

    # ── 1. 清理旧图片（NAS + 本地）──
    old_img = rpt.get("image_paths", "") or ""
    old_nas_pic = rpt.get("nas_picture_path", "") or ""
    try:
        from nas_client import NAS_AVAILABLE as _NAS, delete_file as _del
        if _NAS:
            for p in [x.strip() for x in old_nas_pic.split("|") if x.strip()]:
                try: _del(p)
                except Exception: pass
    except Exception:
        pass
    for p in [x.strip() for x in old_img.split("|") if x.strip()]:
        if p and not p.startswith("/QA/") and os.path.exists(p):
            try:
                if os.path.isdir(p): shutil.rmtree(p)
                else: os.remove(p)
            except Exception: pass

    # ── 2. 上传新图片 ──
    image_paths = []
    nas_picture_path = ""
    nas_fallback = False

    if NAS_AVAILABLE:
        try:
            from nas_client import (
                upload_file as _nas_upload, ensure_single_folder as _esf,
                get_nas_routes as _gnr, process_zip_images as _pzi,
            )
            _, picture_base = _gnr(report_type, report_year)
            brand_name = (rpt.get("brand") or rpt.get("product_name") or "报告")
            sku = rpt.get("sku", "") or ""
            if sku:
                single_img_folder = f"{brand_name}_{sku}_验货图片_{date_short}"
            else:
                single_img_folder = f"{brand_name}_验货图片_{date_short}"
            picture_base_clean = picture_base.rstrip("/")
            _esf(picture_base_clean, single_img_folder)
            nas_img_folder = f"{picture_base_clean}/{single_img_folder}"
            for idx, img in enumerate(images):
                ext = os.path.splitext(img.name)[1].lower() or ".jpg"
                img_name = f"{single_img_folder}_{idx+1:02d}{ext}"
                ok_up, result = _nas_upload(
    nas_img_folder, img_name, img.getbuffer())
                if ok_up:
                    image_paths.append(result)
                else:
                    nas_fallback = True
                    break
            if image_paths:
                nas_picture_path = nas_img_folder
            # ZIP 压缩包
            for zf in zip_files:
                ok_zip, nas_zip_folder, _, _ = _pzi(
    zf.getvalue(), zf.name, report_type, report_year)
                if ok_zip:
                    nas_picture_path = (
    nas_picture_path +
    "|" +
     nas_zip_folder) if nas_picture_path else nas_zip_folder
                else:
                    nas_fallback = True
        except Exception:
            nas_fallback = True

    # 本地回退
    if (not NAS_AVAILABLE or nas_fallback) and (images or zip_files):
        os.makedirs(IMAGE_DIR, exist_ok=True)
        for img in images:
            ts_img = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            img_path = os.path.join(IMAGE_DIR, f"{ts_img}_{img.name}")
            with open(img_path, "wb") as f:
                f.write(img.getbuffer())
            image_paths.append(img_path)
        for zf in zip_files:
            saved = _extract_zip_images_local(zf.getvalue(), zf.name)
            image_paths.extend(saved)

    if not image_paths:
        return False, "未上传任何有效图片"

    db.update_report_images(rid, "|".join(image_paths), nas_picture_path)
    return True, f"已更新 {len(image_paths)} 张图片" + \
                            ("（NAS）" if nas_picture_path else "（本地）")


def _reupload_report_files(rpt, report_files):
    """重新上传报告文件（清理旧文件后写入新文件），更新同一报告记录。"""
    rid = rpt["id"]
    inspection_date = rpt.get("inspection_date") or str(date.today())

    # ── 1. 清理旧报告文件（NAS 暂存 + 本地）──
    old_file = rpt.get("file_path", "") or ""
    for p in [x.strip() for x in old_file.split("|") if x.strip()]:
        if p and not p.startswith("/QA/") and os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

    # ── 2. 上传新报告文件 ──
    filename = ""
    file_path = ""
    nas_staging_path = ""
    payloads = []
    for rf in report_files:
        if rf.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(rf.getbuffer())) as zf:
                    for member in zf.infolist():
                        fixed = _repair_filename_mojibake(
                            member.filename).replace("\\", "/")
                        if fixed.startswith(
                            "__MACOSX/") or member.is_dir() or fixed.endswith("/"):
                            continue
                        if os.path.splitext(fixed)[1].lower() not in (
                            ".pdf", ".docx", ".doc"):
                            continue
                        payloads.append(
    (os.path.basename(fixed), zf.read(member)))
            except Exception as e:
                return False, f"ZIP「{rf.name}」解压失败: {e}"
        else:
            payloads.append(
    (_repair_filename_mojibake(
        rf.name), rf.getbuffer()))

    if not payloads:
        return False, "未找到有效的报告文件（PDF/Word）"

    # 始终暂存服务器本地（审核通过后才上传 NAS 正式归档）
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for idx, (rpt_fname, rpt_content) in enumerate(payloads):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        lp = os.path.join(UPLOAD_DIR, f"{ts}_{idx+1:02d}_{rpt_fname}")
        with open(lp, "wb") as f:
            f.write(rpt_content)
        filename = (filename + "|" + rpt_fname) if filename else rpt_fname
        file_path = (file_path + "|" + lp) if file_path else lp

    db.update_report_file(rid, filename, file_path, nas_staging_path="")
    return True, f"已更新报告文件：{filename}"


def _read_file(file_path, filename):
    """读取报告文件内容（优先NAS，回退本地）"""
    if not file_path or not filename:
        return None

    # 历史数据可能把多附件用 | 拼接，逐个尝试而不是把整串当成路径。
    path_items = [item.strip() for item in str(
        file_path).split('|') if item.strip()]
    name_items = [item.strip()
                             for item in str(filename).split('|') if item.strip()]
    for path_item, name_item in zip(path_items, name_items or [
                                    ''] * len(path_items)):
        content = _read_single_file(
    path_item, name_item or os.path.basename(path_item))
        if content:
            return content
    return None


def _read_single_file(file_path, filename):
    """读取单个附件，供多附件兼容层调用。"""
    if not file_path or not filename:
        return None

    # NAS 路径
    if file_path.startswith('/QA/') or 'sainnas.work' in file_path:
        if NAS_AVAILABLE:
            try:
                from nas_client import list_files
                nas_dir = os.path.dirname(file_path)
                all_files = list_files(nas_dir)
                for f in all_files:
                    if f['name'] == os.path.basename(file_path):
                        from nas_client import _api_call
                        result = _api_call('SYNO.FileStation.Download', version='2',
                                           path=file_path, mode='download')
                        if result.get('success'):
                            # 实际下载需通过HTTP获取文件内容
                            pass
            except Exception:
                pass
        return None

    # 本地路径或 Win 生产库写入的 Windows 路径。
    # Mac 开发端实时读 Win 数据库时，数据库中的 E:\... 路径需要映射到已挂载的 SMB target。
    path_candidates = [file_path]
    if re.match(r"^[A-Za-z]:[\\/]", str(file_path)):
        try:
            import json as _json
            _cfg_path = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__))),
             ".windows_sync.json")
            with open(_cfg_path, "r", encoding="utf-8") as _fh:
                _target = _json.load(_fh).get("target_path", "")
            _norm_win = str(file_path).replace("\\", "/")
            _basename = os.path.basename(_norm_win)
            # Win records store an absolute Windows path. Resolve the stable
            # report location first, then fall back to the full relative path.
            if _target and _basename:
                path_candidates.insert(
    0,
    os.path.join(
        _target,
        "data",
        "reports",
         _basename))
            _target_name = os.path.basename(str(_target).rstrip("/"))
            _marker = f"/{_target_name}/"
            if _target and _marker in _norm_win:
                _relative = _norm_win.split(_marker, 1)[1]
                path_candidates.insert(
    0, os.path.join(
        _target, *_relative.split("/")))
        except Exception:
            pass
    for _candidate in path_candidates:
        if os.path.exists(_candidate) and os.path.isfile(_candidate):
            try:
                with open(_candidate, 'rb') as f:
                    return f.read()
            except Exception:
                pass

    # 尝试从 data/reports/ 或 data/changes/ 查找
    search_dirs = [UPLOAD_DIR, IMAGE_DIR]
    base_lab = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    search_dirs.append(os.path.join(base_lab, 'data', 'changes'))

    for search_dir in search_dirs:
        candidate = os.path.join(search_dir, filename)
        if os.path.exists(candidate) and os.path.isfile(candidate):
            try:
                with open(candidate, 'rb') as f:
                    return f.read()
            except Exception:
                pass

    return None


def _mime_type_for_filename(filename):
    ext = os.path.splitext((filename or '').lower())[1]
    return {
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.zip': 'application/zip',
    }.get(ext, 'application/octet-stream')


def _show_pdf_preview(file_bytes, filename):
    """PDF 在线预览——优先 Streamlit 原生渲染，失败时显示清晰引导"""
    size_kb = len(file_bytes) / 1024
    rendered = False

    # 策略1: Streamlit 原生 st.pdf()（1.38+）
    try:
        st.pdf(file_bytes)
        rendered = True
    except Exception:
        pass

    # 策略2: 任何情况下都在预览区下方提供明确的操作指引
    # （st.pdf 可能静默空白、embed 被 Chrome CSP 拦截，用户需要可靠出口）
    if not rendered:
        st.markdown(f"""
        <div style="padding:20px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;text-align:center">
     <div style="font-size:32px;margin-bottom:8px"></div>
          <div style="font-weight:600;color:#1e293b;margin-bottom:4px">{filename}</div>
          <div style="color:#64748b;font-size:13px;margin-bottom:12px">PDF 文件（{size_kb:.0f} KB）</div>
          <div style="color:#94a3b8;font-size:12px">
      请使用上方「 新窗口查看报告」按钮在线预览<br/>
      或下方「 下载报告文件」保存到本地打开
          </div>
        </div>
        """, unsafe_allow_html=True)


def _render_open_in_new_tab(
    file_bytes, filename, mime_type="application/pdf", button_label=" 新窗口查看附件"):
    """在新标签页中打开附件。将 base64 放在隐藏 textarea 中，避免塞入 onclick 属性导致超长失败。"""
    try:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        safe_name = (
    filename or "preview").replace(
        "\\",
        "_").replace(
            "'",
             "_")

        # base64 放入隐藏 textarea → JS 从 DOM 读取，不受 onclick 属性长度限制
        popup_html = f"""
        <div style="margin:0.25rem 0 0.75rem 0;width:100%">
          <textarea id="b64store_{safe_name}" style="display:none">{b64}</textarea>
          <button id="btn_open_{safe_name}"
            style="background:#2563eb;color:#fff;border:none;border-radius:9px;padding:10px 12px;cursor:pointer;font-size:14px;font-weight:700;width:100%;min-height:40px"
            title="在新标签页中打开 {safe_name}">{button_label}</button>
        </div>
        <script>
        (function(){{
          var btn=document.getElementById('btn_open_{safe_name}');
          if(btn) btn.onclick=function(){{
            var src=document.getElementById('b64store_{safe_name}');
            if(!src)return;
            var raw=atob(src.value),buf=new Uint8Array(raw.length);
            for(var i=0;i<raw.length;i++)buf[i]=raw.charCodeAt(i);
            var blob=new Blob([buf],{{type:'{mime_type}'}}),url=URL.createObjectURL(blob);
            var w=window.open(url,'_blank');
            if(!w)alert('浏览器拦截了弹窗，请允许弹窗后重试。');
            setTimeout(function(){{URL.revokeObjectURL(url)}},60000);
          }};
        }})();
        </script>
        """
        st.html(popup_html, unsafe_allow_javascript=True)
    except Exception:
        st.warning("新窗口预览按钮生成失败，请改用下载查看")


# ==================== Tab 1: 上传 ====================
with tab_upload:
    st.subheader("上传检验报告")
    st.caption("支持 PDF、Word、ZIP 压缩包文件及图片上传。提交后将自动推送至主管审核。")

    bg_list = get_bg_list()
    bu_list = get_bu_list()
    brand_list = get_brand_list()
    quality_users = get_quality_users_list()

    with st.form("report_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            inspector = st.selectbox("检验员 *",
                                     options=quality_users if quality_users else [
                                         ""],
                                     format_func=lambda x: x)
            bg = st.selectbox("BG", [""] + bg_list)
        with col2:
            report_type = st.selectbox(
                "报告类型", ["来料检验", "驻厂验货", "出货检验", "过程检验", "可靠性测试", "其他"])
            bu = st.selectbox("BU", [""] + bu_list)

        col1, col2 = st.columns(2)
        with col1:
            brand = st.selectbox("品牌", [""] + brand_list)
        with col2:
            sku = st.text_input("SKU", placeholder="例如：101-63-KK-RC")

        product_name = st.text_input("产品名称 *", placeholder="检验产品名称")

        # ── 检验日期：用于自动归档到对应年度目录 ──
        inspection_date = st.date_input("检验日期 *", value=date.today(),
                                        help="报告将按此日期的年份归档到NAS对应年度目录")

        col_sup, col_empty = st.columns(2)
        with col_sup:
            supplier = st.text_input("供应商", placeholder="例如：深圳XX电子有限公司")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            report_files = st.file_uploader("上传报告文件", type=["pdf", "docx", "doc", "zip"],
                                            accept_multiple_files=True,
                                            help="支持 PDF/Word/ZIP 压缩包，可同时上传多份报告")
            if report_files:
                zip_count = sum(
    1 for f in report_files if f.name.lower().endswith('.zip'))
                pdf_count = len(report_files) - zip_count
                parts = []
                if pdf_count: parts.append(f"{pdf_count} 份文档")
                if zip_count: parts.append(f"{zip_count} 个 ZIP 压缩包")
                st.caption(f" 已选择 {', '.join(parts)}")
        with col_f2:
            images = st.file_uploader("上传检验照片", type=["png", "jpg", "jpeg", "webp"],
                                      accept_multiple_files=True,
                                      help="可多选检验照片，支持 PNG/JPG/JPEG/WEBP 格式")
            if images:
                st.caption(f" 已选择 {len(images)} 张照片")

        # ── 图片压缩包独立上传入口 ──
        st.divider()
        zip_files = st.file_uploader("上传图片压缩包（ZIP / RAR） 上传图片压缩包（ZIP / RAR）", type=["zip", "rar"],
                                     accept_multiple_files=True,
                                     help="用于批量上传验货照片的压缩包，可同时上传多份压缩文件。请直接对图片文件夹右键压缩。")
        if zip_files:
            st.caption(f"已选择 {len(zip_files)} 个压缩包")

        notes = st.text_area("备注说明")

        submitted = st.form_submit_button(
    "提交报告", type="primary", width="content")

    if submitted:
        if not inspector or not product_name:
            st.error("检验员和产品名称不能为空！")
        else:
            # ── 预处理：将 ZIP 解压展开为可上传的报告文件列表 ──
            # all_report_payloads: [(filename, bytes_buffer), ...]  ——
            # 最终要上传的报告文件清单
            all_report_payloads = []  # [(filename, bytes), ...]

            if report_files:
                import io as io_module
                import zipfile as zf_module
                supported_exts = ('.pdf', '.docx', '.doc')
                for rf in report_files:
                    if rf.name.lower().endswith('.zip'):
                        # ZIP 压缩包 → 解压提取内部报告
                        try:
                            with zf_module.ZipFile(io_module.BytesIO(rf.getbuffer())) as zf:
                                inner_reports = []
                                for member in zf.infolist():
                                    fixed_member_name = _repair_filename_mojibake(
                                        member.filename)
                                    normalized_path = fixed_member_name.replace(
                                        "\\", "/")
                                    if normalized_path.startswith('__MACOSX/'):
                                        continue
                                    if member.is_dir() or normalized_path.endswith('/'):
                                        continue
                                    if not normalized_path.lower().endswith(supported_exts):
                                        continue
                                    inner_reports.append(
    (member, os.path.basename(normalized_path)))
                                if not inner_reports:
                                    st.error(
                                        f"ZIP「{rf.name}」内未找到 PDF/Word 文件，请检查压缩包内容")
                                    st.stop()
                                for member, fixed_name in inner_reports:
                                    all_report_payloads.append(
                                        (_repair_filename_mojibake(
                                            fixed_name), zf.read(member))
                                    )
                        except Exception as e:
                            st.error(f"ZIP「{rf.name}」解压失败: {e}")
                            st.stop()
                    else:
                        # 普通报告文件 → 直接加入
                        all_report_payloads.append(
                            (_repair_filename_mojibake(rf.name), rf.getbuffer()))

            has_reports = len(all_report_payloads) > 0
            has_images = bool(images)
            has_zips = bool(zip_files)

            if not has_reports and not has_images and not has_zips:
                st.error("请至少上传一份报告文件、检验照片或图片压缩包！")
                st.stop()

            # ── 文件上传：报告文件始终暂存服务器本地；照片/压缩包仍实时传 NAS（逻辑不变）──
            filename = ""
            file_path = ""
            nas_report_path = ""
            nas_staging_path = ""
            nas_picture_path = ""
            image_paths = []
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_year = str(inspection_date.year)
            date_short = inspection_date.strftime("%Y%m%d")
            nas_fallback = False  # 仅 ZIP 上传失败时用，不再阻断报告提交

            # 报告文件名基础前缀
            brand_part = f"{brand}（{sku}）" if sku else (
                f"{brand}" if brand else "")
            supplier_part = f"{supplier}" if supplier else ""
            name_parts = [
    p for p in [
        brand_part,
        supplier_part,
         product_name] if p]
            base_name = "".join(name_parts) if name_parts else "报告"

            # ── 1. 报告文件：始终暂存服务器本地（审核通过后才上传 NAS 正式归档）──
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            if has_reports:
                for rpt_idx, (rpt_fname, rpt_content) in enumerate(
                    all_report_payloads):
                    local_fname = f"{timestamp}_{rpt_idx+1:02d}_{rpt_fname}"
                    local_path = os.path.join(UPLOAD_DIR, local_fname)
                    with open(local_path, "wb") as f:
                        f.write(rpt_content)
                    if not filename:
                        filename = rpt_fname
                    else:
                        filename += f"| {rpt_fname}"
                    if not file_path:
                        file_path = local_path
                    else:
                        file_path += f"| {local_path}"
                st.toast(f"报告已暂存服务器，待审核：{filename}")

            # ── 2. 检验照片 + 压缩包：实时传 NAS（保持原有逻辑，NAS 不可用时回退本地）──
            if NAS_AVAILABLE:
                if images:
                    report_base, picture_base = get_nas_routes(
                        report_type, report_year)
                    brand_name = brand if brand else product_name
                    if sku:
                        single_img_folder = f"{brand_name}_{sku}_验货图片_{date_short}"
                    else:
                        single_img_folder = f"{brand_name}_验货图片_{date_short}"
                    picture_base_clean = picture_base.rstrip('/')
                    ensure_single_folder(picture_base_clean, single_img_folder)
                    nas_img_folder = f"{picture_base_clean}/{single_img_folder}"
                    for idx, img in enumerate(images):
                        ext = os.path.splitext(img.name)[1].lower() or '.jpg'
                        img_name = f"{single_img_folder}_{idx+1:02d}{ext}"
                        ok_up, result = nas_upload(
    nas_img_folder, img_name, img.getbuffer())
                        if ok_up:
                            image_paths.append(result)
                        else:
                            st.warning(f"NAS 上传照片「{img.name}」失败，已跳过")
                    if image_paths:
                        nas_picture_path = nas_img_folder
            st.toast(f" {len(image_paths)} 张照片已归档")
            if zip_files:
                nas_zip_folders = []
                for zf_idx, zf in enumerate(zip_files):
                    ok_zip, nas_zip_folder, zip_count, zip_msg = process_zip_images(
                        zf.getvalue(), zf.name, report_type, report_year
                    )
                    if ok_zip:
                        nas_zip_folders.append(nas_zip_folder)
                        st.toast(f"「{zf.name}」: {zip_count} 张照片已归档")
                    else:
                        st.error(f"「{zf.name}」上传失败: {zip_msg}")
                        nas_fallback = True
                        break
                    if nas_zip_folders:
                        if nas_picture_path:
                            nas_picture_path += "|" + "|".join(nas_zip_folders)
                        else:
                            nas_picture_path = "|".join(nas_zip_folders)
            else:
                os.makedirs(IMAGE_DIR, exist_ok=True)
                if images:
                    for img in images:
                        ts_img = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        img_name = f"{ts_img}_{img.name}"
                        img_path = os.path.join(IMAGE_DIR, img_name)
                        with open(img_path, "wb") as f:
                            f.write(img.getbuffer())
                        image_paths.append(img_path)
                if zip_files:
                    for zf in zip_files:
                        local_zip_paths = _extract_zip_images_local(
                            zf.getvalue(), zf.name, base_folder=IMAGE_DIR)
                        if local_zip_paths:
                            image_paths.extend(local_zip_paths)
                            st.toast(
                                f"「{zf.name}」本地解压 {len(local_zip_paths)} 张照片")
                        else:
                            st.warning(f"「{zf.name}」未找到可解压图片，建议连接 NAS 后重新上传")

            # ── 数据库落库 ──
            ok, msg = add_inspection_report({
                'report_type': report_type,
                'inspector': inspector,
                'product_name': product_name,
                'bg': bg, 'bu': bu, 'brand': brand, 'sku': sku,
                'supplier': supplier,
                'filename': filename,
                'file_path': file_path,
                'image_paths': '|'.join(image_paths),
                'nas_report_path': '',  # 审核通过后由归档流程写入正式路径
                'nas_staging_path': nas_staging_path,
                'nas_picture_path': nas_picture_path,
                'status': '待审核',
                'reviewer': 'teddy.li黎晓锋',
                'inspection_date': str(inspection_date),
            })

            storage_label = "服务器本地" if nas_picture_path else "服务器本地+照片NAS"
            if ok:
                log_activity(
    inspector,
    "提交检验报告",
    "data_edit",
    f"{report_type} - {product_name}",
     "检验报告")
                notify_ok, notify_msg = notify_report_submitted(
                    0, product_name, report_type, inspector)
                notice_level, notice_text = _build_notify_notice(
                    f"{msg}（存储：{storage_label}）。",
                    notify_ok,
                    notify_msg,
                    "主管审核通知",
                )
                _queue_flash_notice(notice_level, notice_text)
                st.rerun()
            else:
                st.error(msg)

# ==================== Tab 2: 历史记录（仅追溯与状态） ====================
with tab_list:
    st.markdown(
    '<span class="legacy-report-list-marker"></span>',
     unsafe_allow_html=True)
    st.subheader("历史报告记录")
    st.caption("上传报告和在线报告提交审核后都会自动进入此处；本页仅用于追溯、状态查看和文件查阅，主管审核统一在“审核中心”完成。")

    col_f1, _ = st.columns([1, 2])
    with col_f1:
        filter_status = st.selectbox(
            "状态筛选", ["全部", "待审核", "已通过", "已驳回"], key='report_status')

    st_filter = filter_status if filter_status != "全部" else None
    row_options = [10, 20, 50, 100]
    _default_rows = st.session_state.get("report_page_size", 20)
    _rp_key = "report_page_size_sel"
    page_size_sel = st.selectbox(
        "每页行数", options=row_options,
        index=row_options.index(
            _default_rows) if _default_rows in row_options else 1,
        key=_rp_key, label_visibility="collapsed",
    )
    if st.session_state.get(_rp_key, 20) != st.session_state.get(
        "report_page_size", 20):
        st.session_state["report_page_size"] = st.session_state[_rp_key]
        st.rerun()
    _page_size = st.session_state.get("report_page_size", 20)
    # 2026-07-16：统一查询（上传报告 + 在线报告），草稿不进入历史
    reports, total = get_unified_reports(status=st_filter, per_page=_page_size)

    st.markdown(f"共 **{total}** 份报告 · 当前显示 **{len(reports)}** 条（含上传+在线）")

    if _current_user_can_delete_report():
        with st.popover(" 修复历史乱码文件名（仅开发者/管理员）", width="content"):
            st.info("只修复数据库里历史报告记录的乱码文件名，不会删除数据，也不会改动 NAS 里的文件。")
            if st.button("开始修复历史乱码文件名", type="primary",
                         key="repair_report_filenames"):
                ok, msg = _repair_report_filenames()
                if ok:
                    log_activity(
                        st.session_state.get("user_name", ""),
                        "修复检验报告文件名乱码",
                        "data_edit",
                        msg,
                        "检验报告"
                    )
                    _queue_flash_notice("success", f" {msg}")
                    st.rerun()
                else:
                    st.error(msg)

    # 导入导出
    rpt_template = pd.DataFrame(columns=[
        'report_type', 'inspector', 'product_name', 'brand', 'sku',
        'filename', 'status'
    ])
    render_import_export_buttons(None, 'inspection_reports', rpt_template, key_prefix='rpt_')

    if not reports:
        ui_empty_state("暂无报告", "尚无检验/测试报告记录")
    else:
        # 2026-07-16：统一列表含 source 列区分来源
        df = pd.DataFrame(reports)
        cols = ['source', 'id', 'report_no', 'report_type', 'inspector', 'product_name', 'brand', 'sku',
                'filename', 'status', 'reviewer', 'created_at']
        df_d = df[[c for c in cols if c in df.columns]].copy()
        # 来源列转为图标
        if 'source' in df_d.columns:
            df_d['来源'] = df_d['source'].map({'upload': '上传', 'online': '在线'})
            df_d.drop(columns=['source'], inplace=True)
        rename = {'id': 'ID', 'report_no': '在线报告编号', 'report_type': '报告类型', 'inspector': '检验员', 'product_name': '产品名称',
                  'brand': '品牌', 'sku': 'SKU', 'filename': '文件',
                  'status': '状态', 'reviewer': '审核人',
                  'created_at': '提交时间'}
        df_d.rename(columns={k: v for k, v in rename.items() if k in df_d.columns}, inplace=True)

        # 文件列只保留纯文件名，不暴露服务器内部物理路径
        if '文件' in df_d.columns:
            import os as _os
            def _clean_filename(x):
                if not x:
                    return '—'
                # 含路径分隔符（Windows \ 或 Unix /）则提取 basename
                if '\\' in x or '/' in x or (len(x) > 1 and x[1] == ':'):
                    return _os.path.basename(x)
                return x
            df_d['文件'] = df_d['文件'].apply(_clean_filename)

        def color_status(val):
            c = {'待审核': 'background-color: #fff3cd', '已通过': 'background-color: #d4edda',
                 '已驳回': 'background-color: #f8d7da'}
            return c.get(val, '')
        styled = df_d.style.map(color_status, subset=['状态'])

        # ── 每页显示行数：查询层和展示层使用同一页大小 ──
        col_ps1, col_ps2 = st.columns([1, 4])
        with col_ps1:
            st.caption(f"每页 {_page_size} 条")
        _display_count = min(_page_size, len(df_d))

        with col_ps2:
            st.caption(f"共 **{len(df_d)}** 条记录 · 当前显示 **{_display_count}** 行")

        # 可选中表格：点击行自动展开预览（动态高度随行数调整）
        sel = ui_table(
            styled,
            width="stretch",
            hide_index=True,
            height=min(40 * _display_count + 48, 800),
            selection_mode="single-row",
            on_select="rerun",
            key="report_table"
        )

        # 获取选中行
        selected_rows = []
        if hasattr(sel, 'selection') and sel.selection:
            selected_rows = sel.selection.get('rows', [])
        elif isinstance(sel, dict):
            selected_rows = sel.get('selection', {}).get('rows', [])

        if selected_rows:
            selected_idx = selected_rows[0]
            rpt = reports[selected_idx]
            _src = rpt.get('source', 'upload')  # 来源分流

            # ── 详细信息 + 文件预览 ──
            st.markdown("---")
            src_icon = '' if _src == 'upload' else ''
            src_label = '上传报告' if _src == 'upload' else '在线报告'
            st.subheader(f"{src_icon} {src_label} #{rpt.get('id', '')} — {rpt.get('product_name', '')}")

            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                st.markdown(f"**报告类型**: {rpt.get('report_type', '')}")
                st.markdown(f"**品牌/SKU**: {rpt.get('brand','')} / {rpt.get('sku','')}")
                st.markdown(f"**检验员**: {rpt.get('inspector','')}")
            with col_info2:
                _rp_st = rpt.get('status', '')
                _rp_cls = {"草稿": "status-draft", "待审核": "status-warning",
                            "已通过": "status-pass", "已驳回": "status-reject"}.get(_rp_st, "status-draft")
                st.markdown(f"**状态**: <span class=\"status-pill {_rp_cls}\">{_rp_st}</span>", unsafe_allow_html=True)
                st.markdown(f"**审核人**: {rpt.get('reviewer','')}")
                if _src == 'upload':
                    st.markdown(f"**供应商**: {rpt.get('supplier','')}")
            with col_info3:
                st.markdown(f"**提交时间**: {rpt.get('created_at','')}")
                insp_date = rpt.get('inspection_date', '')
                if insp_date:
                    st.markdown(f"**检验日期**: {insp_date}")
                if rpt.get('reject_reason'):
                    st.markdown(f"**驳回原因**: :red[{rpt['reject_reason']}]")

            if _current_user_can_delete_report() and _src == 'upload':
                st.markdown("---")
                current_filename = rpt.get('filename', '') or ''
                admin_col1, admin_col2, admin_spacer = st.columns([0.18, 0.16, 0.66])
                with admin_col1:
                    with st.popover("手动修改文件名（仅开发者/管理员）", width="content"):
                        st.info("用于修复个别自动识别不了的历史乱码文件名，只修改系统显示名称，不改 NAS 文件。")
                        new_filename = st.text_input(
                            "文件名",
                            value=current_filename,
                            key=f"manual_filename_{rpt['id']}",
                        )
                        if st.button("保存新文件名", type="primary", key=f"save_manual_filename_{rpt['id']}"):
                            ok, msg = _update_report_filename(rpt['id'], new_filename)
                            if ok:
                                log_activity(
                                    st.session_state.get("user_name", ""),
                                    "手动修改检验报告文件名",
                                    "data_edit",
                                    f"报告#{rpt['id']} -> {new_filename}",
                                    "检验报告"
                                )
                                _queue_flash_notice("success", f"{msg}")
                                st.rerun()
                            else:
                                st.error(msg)

                with admin_col2:
                    with st.popover("删除报告（仅开发者/管理员）", width="content"):
                        st.warning("删除后该报告记录会从系统列表中移除，请确认后再操作。")
                        if ui_danger_button("确认删除这条报告", key=f"delete_report_{rpt['id']}", type="primary"):
                            confirm_dialog(
                                "确认删除报告",
                                f"确定要删除报告 **#{rpt['id']}** 吗？此操作不可撤销。",
                                state_key=f"del_rpt_{rpt['id']}",
                                state_value=rpt['id'],
                                confirm_label="确认删除",
                                confirm_type="primary",
                            )
                    # F3：二次确认后执行删除
                    if st.session_state.get(f"del_rpt_{rpt['id']}"):
                        st.session_state[f"del_rpt_{rpt['id']}"] = None
                        ok, msg = _delete_report(rpt['id'])
                        if ok:
                            log_activity(
                                st.session_state.get("user_name", ""),
                                "删除检验报告",
                                "data_edit",
                                f"报告#{rpt['id']} - {rpt.get('product_name','')}",
                                "检验报告"
                            )
                            _queue_flash_notice("success", f"{msg}")
                            st.rerun()
                        else:
                            st.error(msg)

            # ════════════════════════════════════════════
            #  2026-07-16：历史报告统一列表，按来源分流
            #  - 在线报告：显示「🔎 查看报告」按钮（st.dialog）
            #  - 上传报告：保留下方纠错入口（重新上传/编辑信息）
            #  - 纠错仅对 upload 源开放，online 源无此功能
            # ════════════════════════════════════════════
            st.markdown("---")

            # 查看报告按钮（所有来源通用）
            _view_col, _space_col = st.columns([1.5, 5])
            with _view_col:
                if _src == 'upload':
                    if st.button(" 查看报告", key=f"hist_view_{rpt['id']}", type="primary", width="stretch"):
                        _show_upload_report_dialog(rpt['id'])
                else:
                    if st.button(" 查看报告", key=f"hist_view_on_{rpt['id']}", type="primary", width="stretch"):
                        _show_online_report_dialog(rpt['id'])


            # ── 修正操作（仅上传报告）：重新上传 / 编辑报告信息 ──
            if _src == 'upload':
                _editable_status = rpt.get('status') in ('待审核', '草稿', '已驳回')
                _is_owner = (st.session_state.get("user_name", "") == (rpt.get('inspector', '') or ''))
                _can_reupload = _editable_status and (_is_owner or _current_user_can_delete_report())
                _can_edit_info = _current_user_can_delete_report()
                if _can_reupload or _can_edit_info:
                    _ru_col, _ed_col = st.columns([1, 1])
                    if _can_reupload:
                        with _ru_col:
                            with st.expander("重新上传（修正错误上传）", expanded=True):
                                st.caption("仅替换文件 / 图片，不新建记录、不改报告编号，且会自动清理旧文件避免 NAS 重叠。")
                                rcol1, rcol2 = st.columns(2)
                                with rcol1:
                                    with st.container(border=True):
                                        st.markdown("** 重新上传检验图片**")
                                        re_images = st.file_uploader(
                                            "上传检验照片", type=["png", "jpg", "jpeg", "webp"],
                                            accept_multiple_files=True, key=f"re_img_{rpt['id']}"
                                        )
                                        re_zips = st.file_uploader(
                                            "上传图片压缩包（ZIP/RAR）", type=["zip", "rar"],
                                            accept_multiple_files=True, key=f"re_zip_{rpt['id']}"
                                        )
                                        if st.button("替换图片", type="primary", key=f"re_img_btn_{rpt['id']}"):
                                            if not re_images and not re_zips:
                                                st.error("请至少选择一张图片或一个压缩包")
                                            else:
                                                ok, msg = _reupload_images(rpt, re_images or [], re_zips or [])
                                                if ok:
                                                    log_activity(
                                                        st.session_state.get("user_name", ""),
                                                        "重新上传检验图片", "data_edit",
                                                        f"报告#{rpt['id']} - {rpt.get('product_name','')}",
                                                        "检验报告"
                                                    )
                                                    _queue_flash_notice("success", f" {msg}")
                                                    st.rerun()
                                                else:
                                                    st.error(msg)
                                with rcol2:
                                    with st.container(border=True):
                                        st.markdown("** 重新上传报告文件**")
                                        re_files = st.file_uploader(
                                            "上传报告文件", type=["pdf", "docx", "doc", "zip"],
                                            accept_multiple_files=True, key=f"re_file_{rpt['id']}"
                                        )
                                        if st.button("替换报告文件", type="primary", key=f"re_file_btn_{rpt['id']}"):
                                            if not re_files:
                                                st.error("请选择报告文件")
                                            else:
                                                ok, msg = _reupload_report_files(rpt, re_files)
                                                if ok:
                                                    log_activity(
                                                        st.session_state.get("user_name", ""),
                                                        "重新上传报告文件", "data_edit",
                                                        f"报告#{rpt['id']} - {rpt.get('product_name','')}",
                                                        "检验报告"
                                                    )
                                                    _queue_flash_notice("success", f"{msg}")
                                                    st.rerun()
                                                else:
                                                    st.error(msg)
                    if _can_edit_info:
                        with _ed_col:
                            with st.expander("编辑报告信息（修正填写错误）", expanded=True):
                                st.caption("修改产品名 / 品牌 / SKU / BG / BU / 供应商 / 检验日期等基本信息。")
                                ecol1, ecol2, ecol3 = st.columns(3)
                                with ecol1:
                                    edit_product = st.text_input("产品名称", value=rpt.get('product_name', ''), key=f"edit_prod_{rpt['id']}")
                                    edit_brand = st.selectbox("品牌", options=get_brand_list(),
                                                              index=get_brand_list().index(rpt.get('brand', '')) if rpt.get('brand', '') in get_brand_list() else 0,
                                                              key=f"edit_brand_{rpt['id']}")
                                    edit_sku = st.text_input("SKU", value=rpt.get('sku', ''), key=f"edit_sku_{rpt['id']}")
                                with ecol2:
                                    edit_bg = st.selectbox("BG", options=get_bg_list(),
                                                           index=get_bg_list().index(rpt.get('bg', '')) if rpt.get('bg', '') in get_bg_list() else 0,
                                                           key=f"edit_bg_{rpt['id']}")
                                    edit_bu = st.selectbox("BU", options=get_bu_list(),
                                                           index=get_bu_list().index(rpt.get('bu', '')) if rpt.get('bu', '') in get_bu_list() else 0,
                                                           key=f"edit_bu_{rpt['id']}")
                                    edit_supplier = st.text_input("供应商", value=rpt.get('supplier', ''), key=f"edit_sup_{rpt['id']}")
                                with ecol3:
                                    edit_date = st.text_input("检验日期", value=rpt.get('inspection_date', ''), key=f"edit_date_{rpt['id']}")
                                    _report_type_options = ["来料检验", "驻厂验货", "出货检验", "过程检验", "可靠性测试", "其他"]
                                    edit_type = st.selectbox("报告类型",
                                                             options=_report_type_options,
                                                             index=_report_type_options.index(rpt.get('report_type', '')) if rpt.get('report_type', '') in _report_type_options else 0,
                                                             key=f"edit_type_{rpt['id']}")
                                if st.button("保存修改", type="primary", key=f"save_edit_{rpt['id']}"):
                                    ok, msg = update_report_info(
                                        rpt['id'],
                                        product_name=edit_product.strip() or None,
                                        brand=edit_brand.strip() or None,
                                        sku=edit_sku.strip() or None,
                                        bg=edit_bg.strip() or None,
                                        bu=edit_bu.strip() or None,
                                        supplier=edit_supplier.strip() or None,
                                        inspection_date=edit_date.strip() or None,
                                        report_type=edit_type.strip() or None,
                                    )
                                    if ok:
                                        log_activity(
                                            st.session_state.get("user_name", ""),
                                            "编辑报告基本信息", "data_edit",
                                            f"报告#{rpt['id']} - {rpt.get('product_name','')}",
                                            "检验报告"
                                        )
                                        _queue_flash_notice("success", f"{msg}"); st.rerun()
                                    else:
                                        st.error(f"{msg}")

# ==================== Tab 3: 在线报告（在线 QC 检验报告闭环） ====================
def _online_report_tab():
    """在线 QC 检验报告完整闭环：新建 → 在线填写 → 先导出纸质 PDF → 提交审核 → 通过后正式归档 PDF。
    与历史上传报告（inspection_reports 表）完全独立，互不影响。"""

    st.markdown("""
    <div class="report-page-title">
      <div><div class="eyebrow">ONLINE INSPECTION REPORT</div>
      <h1>在线 QC 检验报告</h1>
      <div class="sub">检验员填写、拍照/二维码采集、生成纸质 PDF、提交审核，主管通过后归档</div></div>
    </div>
    <div class="report-flow-note report-pdf-note"><strong>纸质档案节点：</strong>报告填写完成后即可在检验报告页面生成 PDF 并打印给工厂签字；不需要等待主管审核。签字纸档与在线报告分开管理，主管审核只决定线上报告是否归档。</div>
    """, unsafe_allow_html=True)

    # ---- 远程 Win 生产库连接（Mac 开发环境：直读 Win 实时数据） ----
    _remote_db_path = None
    _remote_conn = None
    _using_remote = False
    if sys.platform == "darwin":
        try:
            _remote_db_path = db._resolve_remote_audit_db()
        except Exception:
            _remote_db_path = None
        if _remote_db_path:
            import sqlite3 as _sqlite3
            try:
                _remote_conn = _sqlite3.connect(f"file:{_remote_db_path}?mode=rw", uri=True, timeout=10)
                _remote_conn.row_factory = _sqlite3.Row
                _remote_conn.execute("SELECT COUNT(*) FROM online_reports")
                _using_remote = True
            except Exception:
                try:
                    if _remote_conn:
                        _remote_conn.close()
                    _remote_conn = None
                    _remote_conn_r = _sqlite3.connect(f"file:{_remote_db_path}?mode=ro", uri=True, timeout=10)
                    _remote_conn_r.row_factory = _sqlite3.Row
                    _remote_conn_r.execute("SELECT COUNT(*) FROM online_reports")
                    _remote_conn = _remote_conn_r
                    _using_remote = True
                except Exception:
                    _remote_conn = None
                    _using_remote = False

    # 数据源指示器
    if _using_remote:
        st.success("数据源：Win 生产库 —— 同事创建的报告即时可见，管理员可删除错误报告")
    elif sys.platform == "darwin":
        st.info("当前读取本地库（未检测到 Win 生产库连接，Mac 上看不到同事在 Win 新建的报告）")

    def _or_list_reports():
        """列表查询：严格隔离——无论是否管理员，仅返回自己创建的报告（创建人数据不外泄）。"""
        if _remote_conn:
            rows = _remote_conn.execute(
                "SELECT * FROM online_reports WHERE created_by=? ORDER BY id DESC",
                (created_by,),
            ).fetchall()
            return [dict(r) for r in rows]
        return odb.list_online_reports(owner=created_by)

    def _or_counts_by_status():
        """状态统计：仅统计当前用户自己创建的报告（与列表过滤一致）。"""
        if _remote_conn:
            result = {}
            for s in ("草稿", "待审核", "已通过", "已驳回"):
                c = _remote_conn.execute(
                    "SELECT COUNT(*) FROM online_reports WHERE status=? AND created_by=?", (s, created_by)
                ).fetchone()[0]
                result[s] = c
            return result
        return odb.counts_by_status(owner=created_by)

    def _or_get_report(rid):
        """单条查询：非 owner 且非 admin 返回 None（防 URL 直接越权访问）。"""
        if _remote_conn:
            r = _remote_conn.execute(
                "SELECT * FROM online_reports WHERE id=?", (rid,)
            ).fetchone()
            if r:
                d = dict(r)
                if not _can_admin and d.get("created_by") and d["created_by"] != created_by:
                    return None
                return d
            return None
        rep = odb.get_online_report(rid)
        if rep and not _can_admin and rep.get("created_by") and rep["created_by"] != created_by:
            return None
        return rep

    def _or_create_draft(template_code=None):
        """Create the draft in the same database used by the visible list."""
        creator = st.session_state.get("user_email", "") or st.session_state.get("user_name", "")
        if _remote_conn:
            import json as _json
            from datetime import datetime as _dt
            now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            prefix = f"QC-{_dt.now().strftime('%Y%m%d')}-"
            try:
                _remote_conn.execute("BEGIN IMMEDIATE")
                row = _remote_conn.execute(
                    "SELECT report_no FROM online_reports WHERE report_no LIKE ? ORDER BY report_no DESC LIMIT 1",
                    (prefix + "%",),
                ).fetchone()
                seq = int(str(row[0]).split("-")[-1]) + 1 if row and str(row[0]).split("-")[-1].isdigit() else 1
                report_no = f"{prefix}{seq:04d}"
                initial_data = {"repno": report_no}
                if template_code == "ororo":
                    initial_data.update({"template_code": "ororo", "template_version": "1.0"})
                cur = _remote_conn.execute(
                    "INSERT INTO online_reports (report_no,title,product_name,supplier,inspector,verdict,status,data_json,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (report_no, "未命名报告", "", "", "", "", odb.STATUS_DRAFT, _json.dumps(initial_data, ensure_ascii=False), creator, now, now),
                )
                _remote_conn.commit()
                _new_rid = int(cur.lastrowid)
                odb.add_audit(creator, "create", "online_reports", str(_new_rid), report_no)
                return _new_rid, report_no
            except Exception:
                try:
                    _remote_conn.rollback()
                except Exception:
                    pass
                raise
        initial_data = {"template_code": "ororo", "template_version": "1.0"} if template_code == "ororo" else {}
        _new_rid, _new_rno = odb.create_draft(initial_data, created_by=creator)
        odb.add_audit(creator, "create", "online_reports", str(_new_rid), _new_rno)
        return _new_rid, _new_rno

    def _or_delete_report(rid, report_no):
        """删除：优先远程写；回退本地 odb。"""
        if _remote_conn:
            try:
                # 同时清理关联的在线报告 PDF
                rep = _or_get_report(rid)
                if rep and rep.get("pdf_path"):
                    import os as _os
                    pdf = rep["pdf_path"]
                    if _os.path.exists(pdf):
                        _os.remove(pdf)
                _remote_conn.execute("DELETE FROM online_reports WHERE id=?", (rid,))
                _remote_conn.commit()
                # 删除后立即失效工作台和侧栏统计，返回主页无需手动刷新。
                st.cache_data.clear()
                return True
            except Exception as e:
                st.error(f"远程删除失败: {e}")
                return False
        try:
            odb.delete_online_report(rid)
            # 删除后立即失效工作台和侧栏统计，返回主页无需手动刷新。
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"删除失败: {e}")
            return False

    # ---- 当前用户与权限（复用既有 _current_user_can_review 语义） ----
    user_name = st.session_state.get("user_name", "")
    created_by = st.session_state.get("user_email", "") or user_name
    # 治理层角色：admin 全权；本地、局域网和外网均无隐式管理员回退。
    _authenticated = bool(st.session_state.get("authenticated"))
    _user_email = (st.session_state.get("user_email") or "").strip().lower()
    _sess_admin = bool(st.session_state.get("is_admin", False)) and _authenticated and bool(_user_email)
    _can_admin = _sess_admin
    # 角色必须按登录邮箱匹配，避免同名人员或昵称变化造成越权。
    user_role = _or_get_role(_user_email or user_name, is_admin=_can_admin)

    def _can_review(rpt):
        return _current_user_can_review({"reviewer": rpt.get("reviewer", "")})

    def _can_delete():
        return _current_user_can_delete_report()

    def _is_owner(rep):
        """当前用户是否为报告创建者（admin 自动视为 owner）。"""
        if _can_admin:
            return True
        return bool(
            _authenticated and user_role == "uploader"
            and rep.get("created_by") and rep["created_by"] == created_by
        )

    def _can_delete_draft(rep):
        """Deletion is authorized twice: before display and before execution."""
        return bool(
            _authenticated
            and rep
            and rep.get("status") == "草稿"
            and (_can_admin or _is_owner(rep))
        )

    ss = st.session_state
    ss.setdefault("or_mode", "list")      # list | edit | view
    ss.setdefault("or_edit_id", None)
    ss.setdefault("or_view_id", None)
    ss.setdefault("or_draft", None)
    ss.setdefault("or_seq", 0)            # 组件 key 计数器（每次保存后 +1，避免重复处理））
    ss.setdefault("or_flash", None)
    ss.setdefault("_reject_target", None)

    # 工作台「新建报告」通过 query 参数进入在线报告 Tab，并自动创建空白草稿。
    if st.query_params.get("new") == "1" and ss["or_mode"] == "list":
        if user_role not in ("admin", "uploader"):
            st.query_params.pop("new", None)
            st.query_params.pop("or_template", None)
            _flash("当前角色没有新建报告权限。", "err")
            st.rerun()
        template_code = st.query_params.get("or_template")
        new_rid, new_no = _or_create_draft(template_code=template_code)
        ss["or_mode"] = "edit"
        ss["or_edit_id"] = new_rid
        ss["or_draft"] = {"repno": new_no, **({"template_code": "ororo", "template_version": "1.0"} if template_code == "ororo" else {})}
        st.query_params.pop("new", None)
        st.query_params.pop("or_template", None)
        st.query_params["tab"] = "online"
        st.rerun()

    # ---- 顶部状态小统计 ----
    c = _or_counts_by_status()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📝 草稿", c.get("草稿", 0))
    m2.metric("⏳ 待审核", c.get("待审核", 0))
    m3.metric("✅ 已通过", c.get("已通过", 0))
    m4.metric("❌ 已驳回", c.get("已驳回", 0))

    if ss["or_flash"]:
        kind, msg = ss["or_flash"]
        (st.success if kind == "ok" else st.error)(msg)
        ss["or_flash"] = None

    # ============ 列表模式 ============
    if ss["or_mode"] == "list":
        create_generic, create_ororo, _create_spacer = st.columns([1, 1, 4], gap="small")
        with create_generic:
            create_generic_clicked = st.button("新建通用报告", type="primary", width="stretch", key="or_create_draft", disabled=user_role not in ("admin", "uploader"))
        with create_ororo:
            create_ororo_clicked = st.button("新建 Ororo 专用报告", type="primary", width="stretch", key="or_create_ororo", disabled=user_role not in ("admin", "uploader"))
        if user_role == "reviewer":
            st.caption("当前角色：审核员。可查看并审核待审核报告，不能新建或编辑检验报告。")
        elif user_role == "viewer":
            st.caption("当前角色：只读。仅可查看报告，不能新建、编辑、审核或删除。")

        if user_role in ("admin", "uploader"):
            with st.expander("从历史通用报告快速开始", expanded=False):
                st.caption("完整 SKU 精确优先；也可输入如 28-020、产品名或品牌查询同系列。仅列出已通过/已归档的通用报告，不包含 Ororo。")
                _hist_query = st.text_input("SKU / 产品 / 品牌", key="or_history_query", placeholder="例如：28-020-158-E 或 28-020")
                _hist_rows = odb.find_reusable_general_reports(_hist_query) if len(_hist_query.strip()) >= 2 else []
                if _hist_rows:
                    _hist_options = {r["id"]: f"{r['report_no']}｜SKU {r['sku'] or '—'}｜{r['product'] or '未命名'}｜{r['brand'] or '—'}｜{r['updated_at'][:10]}" for r in _hist_rows}
                    _hist_id = st.selectbox("选择作为检验基础的历史报告", list(_hist_options), format_func=lambda rid: _hist_options[rid], key="or_history_source")
                    _target_sku = st.text_input("本次 SKU", value=_hist_query if "-" in _hist_query else "", key="or_history_target_sku", placeholder="例如：28-020-158-E")
                    if st.button("引用此报告为新的通用草稿", type="primary", key="or_create_from_history"):
                        try:
                            _draft_data = odb.build_reused_general_draft(_hist_id, _target_sku)
                            _new_rid, _new_no = odb.create_draft(_draft_data, created_by=created_by)
                            odb.add_audit(user_name, "create", "online_report", str(_new_rid), f"引用历史报告 {_hist_options[_hist_id].split('｜')[0]}")
                            ss["or_mode"], ss["or_edit_id"] = "edit", _new_rid
                            ss["or_draft"] = odb.get_online_report(_new_rid).get("data", {})
                            _flash(f"已从历史报告创建新草稿：{_new_no}。请复核 SKU、订单、实测结果和照片。", "ok")
                            st.rerun()
                        except Exception as _history_exc:
                            st.error(f"引用历史报告失败：{_history_exc}")
                elif _hist_query.strip():
                    st.info("未找到可引用的已通过通用报告；你仍可新建空白报告。")
        if create_generic_clicked or create_ororo_clicked:
            try:
                template_code = "ororo" if create_ororo_clicked else None
                new_rid, new_no = _or_create_draft(template_code=template_code)
                template_name = "Ororo 专用报告" if template_code else "通用报告"
                ss["or_flash"] = ("ok", f"已创建{template_name}草稿 {new_no}，报告列表已刷新；点击该报告右侧「编辑」继续填写。")
                st.rerun()
            except Exception as exc:
                st.error(f"创建在线报告失败：{exc}")

        rows = _or_list_reports()
        if not rows:
            ui_empty_state("暂无在线报告", "点击上方「新建在线报告」开始填写第一份检验报告")
        else:
            for r in rows:
                rid = r["id"]
                st.divider() if False else None
                with st.container(border=True):
                    c1, c2, c3, c4, c5 = st.columns([2.4, 1.5, 1.0, 1.7, 2.2])
                    with c1:
                        st.markdown(f"**{r['report_no']}** \n{r['title'] or '—'}")
                    with c2:
                        st.caption(f"供应商：{r['supplier'] or '—'}")
                        st.caption(f"检验员：{r['inspector'] or '—'}")
                    with c3:
                        _st = r["status"]
                        _st_cls = {"草稿": "status-draft", "待审核": "status-warning",
                                    "已通过": "status-pass", "已驳回": "status-reject"}.get(_st, "status-draft")
                        st.markdown(f'<span class="status-pill {_st_cls}">{_st}</span>', unsafe_allow_html=True)
                    with c4:
                        st.caption(f"更新：{(r['updated_at'] or '—')[:16]}")
                        if r.get("reviewer"):
                            st.caption(f"审核：{r['reviewer']}")
                    with c5:
                        # ── 操作按钮区：编辑/查看 + 删除（草稿仅创建者/管理员可删）──
                        _can_del_this = _can_delete_draft(r)

                        # ── 删除确认弹窗：由 st.button 设置 session_state 触发（无页面刷新）──
                        # 关键：弹窗弹出后立即清除触发标志 → 取消后不会死循环重弹
                        _del_trig_key = f"or_del_trig_{rid}"
                        if _can_del_this and ss.get(_del_trig_key):
                            ss.pop(_del_trig_key, None)
                            confirm_dialog(
                                title="确认删除",
                                message=f"确定要删除草稿 **{r['report_no']}** 吗？\n\n此操作不可恢复，报告数据及关联文件将被永久删除。",
                                state_key=f"or_del_confirm_{rid}",
                                state_value=rid,
                                cancel_label="取消",
                                confirm_label="确认删除",
                                confirm_type="primary",
                            )
                        # 弹窗确认后执行删除
                        if ss.get(f"or_del_confirm_{rid}"):
                            _del_rid = ss.pop(f"or_del_confirm_{rid}")
                            _latest = _or_get_report(_del_rid)
                            if not _can_delete_draft(_latest):
                                _flash("删除被拒绝：当前登录状态、报告归属或草稿状态已变化。", "err")
                            else:
                                try:
                                    odb.delete_online_report(_del_rid)
                                    odb.add_audit(user_name, "delete", "online_report", str(_del_rid), f"删除草稿 {_latest['report_no']}")
                                    log_activity(user_name, "delete_online_report", f"删除在线检验报告草稿: {_latest['report_no']}")
                                    _flash(f"已删除草稿：{_latest['report_no']}", "ok")
                                except Exception as _del_exc:
                                    _flash(f"删除失败：{_del_exc}", "err")
                            st.rerun()

                        # ── 等高对齐 CSS 注入（仅作用于本行按钮区，不污染全局）──
                        st.markdown("""
                        <style>
                        [data-testid="stHorizontalBlock"].qms-action-row {
                            align-items: center !important;
                        }
                        [data-testid="stHorizontalBlock"].qms-action-row > div {
                            display: flex !important;
                            align-items: center !important;
                        }
                        </style>""", unsafe_allow_html=True)

                        # ── 双按钮行：st.columns + 原生 st.button（稳定、无刷新、取消正常）──
                        _bc_left, _bc_right = st.columns([1.3, 0.9], gap="small")
                        # 给 columns 容器加标记类，让上面的 CSS 只影响这一行
                        st.markdown(
                            '<script>'
                            'document.currentScript.closest("[data-testid=\'column\']")'
                            '.parentElement.classList.add("qms-action-row");'
                            '</script>',
                            unsafe_allow_html=True,
                        )

                        with _bc_left:
                            # 左列：编辑 / 查看
                            if _st in ("草稿", "已驳回"):
                                if _is_owner(r):
                                    st.markdown(_new_window_editor_link("✏️ 编辑", rid=rid), unsafe_allow_html=True)
                                else:
                                    if st.button("👁 查看", key=f"or_view_{rid}", use_container_width=True):
                                        ss["or_mode"] = "view"
                                        ss["or_view_id"] = rid
                                        st.rerun()
                            elif _st == "待审核" and user_role == "admin":
                                st.markdown(_new_window_editor_link("🔧 强制修改", rid=rid), unsafe_allow_html=True)
                            else:
                                if st.button("👁 查看", key=f"or_view_{rid}", use_container_width=True):
                                    ss["or_mode"] = "view"
                                    ss["or_view_id"] = rid
                                    st.rerun()
                            # 已通过：管理员可强制修改
                            if _st == "已通过" and user_role == "admin":
                                if st.button("🔧 强制修改", key=f"or_force_{rid}", use_container_width=True, type="primary"):
                                    _r = _or_get_report(rid)
                                    if _r:
                                        ss["or_mode"] = "edit"
                                        ss["or_edit_id"] = rid
                                        ss["_force_edit_reason_required"] = True
                                        ss["or_draft"] = _r.get("data", {})
                                        st.rerun()

                        with _bc_right:
                            # 右列：删除（原生 st.button，点击设 session_state 标志 → 下次渲染弹窗）
                            if _can_del_this:
                                if st.button("🗑 删除", key=f"or_del_btn_{rid}",
                                             use_container_width=True, type="secondary"):
                                    ss[_del_trig_key] = True
                                    st.rerun()

                        # ── PDF 下载（已通过报告，跨全宽放在操作区下方）──
                        _or_dl = r.get("nas_pdf_path") or r.get("pdf_path")
                        if _st == "已通过" and _or_dl and os.path.exists(_or_dl):
                            with open(_or_dl, "rb") as fh:
                                st.download_button("📄 PDF", fh.read(),
                                                 file_name=os.path.basename(_or_dl),
                                                 mime="application/pdf", key=f"or_dl_{rid}",
                                                 use_container_width=True)

        # ── 管理员权限面板（仅 admin 可见）──
        if user_role == "admin":
            _render_permission_panel(user_role)

        # 驳回原因弹层
        if ss["_reject_target"]:
            rt = ss["_reject_target"]
            rep = _or_get_report(rt)
            rno = rep["report_no"] if rep else rt
            with st.popover(f"驳回原因（必填）· {rno}", width="content"):
                rr = st.text_area("驳回原因", key="or_reject_reason")
                if st.button("确认驳回", key="or_confirm_reject"):
                    if rr.strip():
                        # 驳回：优先远程写，回退本地
                        _rejected = False
                        if _remote_conn:
                            try:
                                _remote_conn.execute(
                                    "UPDATE online_reports SET status='已驳回', reviewer=?, updated_at=? WHERE id=?",
                                    (user_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rt)
                                )
                                _remote_conn.commit()
                                _rejected = True
                            except Exception:
                                pass
                        if not _rejected:
                            odb.reject_report(rt, reviewer=user_name, comment=rr)
                        odb.add_audit(user_name, "reject", "online_report", str(rt), rr)
                        _flash(f"已驳回 {rno}", "err")
                        ss["_reject_target"] = None
                        st.rerun()
                    else:
                        st.error("请填写驳回原因")

    # ============ 编辑模式 ============
    elif ss["or_mode"] == "edit":
        # 返回按钮放在最前：点击后会 st.rerun() 中断脚本，避免重复处理组件返回值
        if st.button("← 返回列表", key="or_back_edit"):
            ss["or_mode"] = "list"
            ss["or_edit_id"] = None
            ss["or_draft"] = None
            st.rerun()

        if ss["or_edit_id"]:
            rep = _or_get_report(ss["or_edit_id"])
            if not rep:
                st.warning("您没有权限编辑此报告（仅创建者或管理员可编辑）。")
                ss["or_edit_id"] = None
                ss["or_draft"] = None
                st.stop()
            rno = rep["report_no"] if rep else "—"
        else:
            rno = "（保存后生成）"
        if ss.get("_force_edit_reason_required"):
            ss["_force_edit_reason"] = st.text_area(
                "变更原因（必填，将记入版本历史与操作日志）*", key="or_force_reason", height=70)
        st.markdown(f"**报告编号**：`{rno}` · 编辑中（点击右上角按钮可保存草稿 / 提交审核）")

        # 组件 key 带 seq：每次保存后 +1 强制重挂载 → 返回值重置为默认，杜绝重复处理
        # 锁定规则：待审核/已通过时锁定（不可编辑）；已驳回解锁（检验员可修改后重新提交）
        _locked_statuses = (odb.STATUS_PENDING, odb.STATUS_APPROVED)
        _locked = bool(rep and rep.get("status") and rep.get("status") in _locked_statuses)
        val = _render_online_report_safe(data=ss["or_draft"], mode="edit",
                                         key=f"or_editor_{ss['or_seq']}",
                                         photo=_build_photo_cfg(ss.get("or_edit_id"), user_name),
                                         locked=_locked, height=860,
                                         report_id=ss.get("or_edit_id"), report_no=rno)
        if val and val.get("type") == "save_draft":
            _handle_online_save(val["data"])
        elif val and val.get("type") == "submit":
            _handle_online_submit(val["data"])

    # ============ 查看模式（只读报告视图 / 审核） ============
    elif ss["or_mode"] == "view":
        if st.button("← 返回列表", key="or_back_view"):
            ss["or_mode"] = "list"
            ss["or_view_id"] = None
            st.rerun()

        rep = _or_get_report(ss["or_view_id"])
        if not rep:
            st.error("报告不存在或已被删除")
            ss["or_mode"] = "list"
            st.rerun()
        else:
            st.markdown(f"**报告编号**：`{rep['report_no']}` **状态**：`{rep['status']}`")
            if rep["status"] == "待审核" and _can_review(rep):
                ca, cb = st.columns([0.13, 0.13])
                with ca:
                    if st.button("通过并生成 PDF", type="primary", key="or_appv"):
                        _approve_and_gen_pdf(rep["id"])
                        st.rerun()
                with cb:
                    if st.button("驳回", key="or_rejv"):
                        ss["_reject_target"] = rep["id"]
                        st.rerun()
            _or_dl = rep.get("nas_pdf_path") or rep.get("pdf_path")
            if rep["status"] == "已通过" and _or_dl and os.path.exists(_or_dl):
                with open(_or_dl, "rb") as fh:
                    st.download_button("下载正式 PDF", fh.read(),
                                     file_name=os.path.basename(_or_dl),
                                     mime="application/pdf", key="or_dlv")
            # 只读报告渲染
            _render_online_report_safe(data=rep["data"], mode="view", key="or_viewer",
                                       photo=_build_photo_cfg(rep["id"], user_name))

            # ── 治理层：版本历史 + 操作日志（管理员可见）──
            if user_role == "admin":
                with st.expander(" 版本历史", expanded=False):
                    _render_version_history(rep["id"])
                with st.expander("操作日志", expanded=False):
                    _render_audit_log(rep["id"])


def _handle_online_save(data):
    ss = st.session_state
    rid = ss.get("or_edit_id")
    if rid:
        rep = odb.get_online_report(rid)
        status = rep["status"] if rep else "草稿"
        if status == "已通过":
            # 锁定报告强制修改：须填原因 + 先快照版本
            reason = (ss.get("_force_edit_reason") or "").strip()
            if not reason:
                _flash("已通过报告修改须填写变更原因", "err")
                return
            odb.create_version(rid, rep["data_json"], rep.get("pdf_path"),
                               ss.get("user_name", ""), reason, "admin_edit")
            odb.add_audit(ss.get("user_name", ""), "force_edit", "online_report", str(rid), reason)
            if not odb.update_draft(rid, data, force=True):
                _flash("报告内容保存失败，未执行提交审核", "err")
                return
            ss["_force_edit_reason_required"] = False
            ss["_force_edit_reason"] = ""
        else:
            if status != "草稿":
                odb.create_version(rid, rep["data_json"], rep.get("pdf_path"),
                                   ss.get("user_name", ""), "", "edit")
            odb.update_draft(rid, data)
        ss["or_draft"] = data
        ss["or_seq"] = ss.get("or_seq", 0) + 1
        odb.link_photos_by_key(f"r{rid}", rid)
        _flash(f"草稿已保存：{rep['report_no']}")
        st.rerun()
    else:
        rid, no = odb.create_draft(data, created_by=ss.get("user_email", "") or ss.get("user_name", ""))
        ss["or_edit_id"] = rid
        ss["or_draft"] = data
        odb.add_audit(ss.get("user_name", ""), "create", "online_report", str(rid), no)
        if ss.get("or_photo_key"):
            odb.link_photos_by_key(ss["or_photo_key"], rid)
        ss["or_seq"] = ss.get("or_seq", 0) + 1
        _flash(f"草稿已保存：{no}")
        st.rerun()


def _handle_online_submit(data):
    ss = st.session_state
    rid = ss.get("or_edit_id")
    if rid:
        rep = odb.get_online_report(rid)
        status = rep["status"] if rep else "草稿"
        if status == "已通过":
            reason = (ss.get("_force_edit_reason") or "").strip()
            if not reason:
                _flash("已通过报告修改须填写变更原因", "err")
                return
            odb.create_version(rid, rep["data_json"], rep.get("pdf_path"),
                               ss.get("user_name", ""), reason, "admin_edit")
            odb.add_audit(ss.get("user_name", ""), "force_edit", "online_report", str(rid), reason)
            if not odb.update_draft(rid, data, force=True):
                _flash("报告内容保存失败，未执行提交审核", "err")
                return
            ss["_force_edit_reason_required"] = False
            ss["_force_edit_reason"] = ""
        else:
            if status != "草稿":
                odb.create_version(rid, rep["data_json"], rep.get("pdf_path"),
                                   ss.get("user_name", ""), "", "edit")
            if not odb.update_draft(rid, data):
                _flash("报告内容保存失败，未执行提交审核", "err")
                return
        odb.link_photos_by_key(f"r{rid}", rid)
    else:
        rid, no = odb.create_draft(data, created_by=ss.get("user_email", "") or ss.get("user_name", ""))
        ss["or_edit_id"] = rid
        odb.add_audit(ss.get("user_name", ""), "create", "online_report", str(rid), no)
        if ss.get("or_photo_key"):
            odb.link_photos_by_key(ss["or_photo_key"], rid)
    # Do not continue to PDF/NAS processing if the edited payload was not
    # persisted. A false success here leaves the report as a draft forever.
    if ss.get("or_edit_id") == rid and not odb.get_online_report(rid, with_data=False):
        _flash("报告记录不存在，未执行提交审核", "err")
        st.rerun()
    pdf_ok, pdf_msg = _prepare_online_pdf(rid, data)
    if not pdf_ok:
        _flash(f"提交审核前处理失败：{pdf_msg}", "err")
        st.rerun()
    if not odb.submit_for_review(rid):
        _flash("报告提交审核失败，请检查报告状态后重试", "err")
        st.rerun()
    rep = odb.get_online_report(rid)
    if not rep or rep.get("status") != odb.STATUS_PENDING:
        _flash("提交状态校验失败：数据库未进入「待审核」，请勿关闭页面并重试", "err")
        st.rerun()
    _or_basic = (data or {}).get("basic", {}) or {}
    _or_product = _or_basic.get("product") or _or_basic.get("supplier") or "(未填产品)"
    _or_inspector = _or_basic.get("inspector") or ss.get("user_name", "")
    try:
        _nok, _nmsg = notify_report_submitted(rid, _or_product, "在线QC检验报告", _or_inspector)
        if not _nok:
            _flash(f"已提交审核，但钉钉通知失败：{_nmsg}", "err")
    except Exception as _e:
        _flash(f"已提交审核，但钉钉通知异常：{_e}", "err")
    odb.add_audit(ss.get("user_name", ""), "submit", "online_report", str(rid), rep["report_no"] if rep else "")
    ss["or_mode"] = "list"
    ss["or_edit_id"] = None
    ss["or_draft"] = None
    ss["or_seq"] = ss.get("or_seq", 0) + 1
    _flash(f"已提交审核：{rep['report_no'] if rep else rid}")
    st.rerun()


def _approve_and_gen_pdf(rid, reviewer_signature="", comment="审核通过"):
    ss = st.session_state
    rep = odb.get_online_report(rid)
    if not rep:
        _flash("在线报告不存在", "err")
        return
    if rep.get("status") != odb.STATUS_PENDING:
        _flash(f"当前报告状态为「{rep.get('status','')}」，不能重复审核", "err")
        return
    reviewer = (reviewer_signature or ss.get("user_name", "")).strip()
    if not reviewer:
        _flash("审核通过前必须填写审核人签字", "err")
        return
    # Store the reviewer in the report and regenerate the staging PDF before
    # archiving, so the final PDF contains the signature in section 8.
    signed_data = dict(rep.get("data", {}) or {})
    conclusion = dict(signed_data.get("conclusion", {}) or {})
    conclusion["sign2"] = reviewer
    signed_data["conclusion"] = conclusion
    if not odb.update_draft(rid, signed_data):
        _flash("审核人签字保存失败，未执行归档", "err")
        return
    ok_pdf, pdf_msg = _prepare_online_pdf(rid, signed_data)
    if not ok_pdf:
        _flash(f"审核未完成，带签字 PDF 生成失败：{pdf_msg}", "err")
        return
    ok_archive, archive_msg = _archive_online_report(
        rid, reviewer=reviewer, comment=comment or "审核通过"
    )
    if not ok_archive:
        _flash(f"审核未完成，PDF 归档失败：{archive_msg}", "err")
        return
    odb.approve_report(rid, reviewer=reviewer, comment=comment or "审核通过")
    # 锁定时快照一版权威版本（后续强制修改可追溯）
    odb.create_version(rid, rep["data_json"], rep.get("pdf_path"),
                       reviewer, comment or "审核通过", "approve")
    odb.add_audit(reviewer, "approve", "online_report", str(rid), rep["report_no"])
    basic = rep.get("data", {}).get("basic", {}) or {}
    submitter = basic.get("inspector") or rep.get("created_by") or ""
    try:
        notify_ok, notify_msg = notify_report_approved(
            rid, basic.get("product") or rep.get("product_name") or "在线检验报告", submitter
        )
        notice = _build_notify_notice("审核通过并归档。", notify_ok, notify_msg, "钉钉通知")
        _flash(f"{notice[1]} 归档位置：{archive_msg}", "ok" if notice[0] == "success" else "err")
    except Exception as exc:
        _flash(f"审核通过并归档，钉钉通知异常：{exc}。归档位置：{archive_msg}", "err")


def _render_pdf_pages_as_images(pdf_bytes: bytes, max_pages: int = 50):
    """用 pypdfium2 将 PDF 每页渲染为 PIL Image 列表，失败时返回 None。

    为什么不用 st.pdf/iframe：
    - 浏览器内置 PDF 插件对大文件/数据 URL 兼容差（CSP/MIME/iframe sandbox）
    - Streamlit data URL 路径会随文件增大快速膨胀
    - 转换为图片后用 st.image 渲染是 100% 可靠、与文件大小解耦的方案
    """
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        n = min(len(pdf), max_pages)
        pages = []
        for i in range(n):
            pil_img = pdf[i].render(scale=1.5).to_pil()
            pages.append(pil_img)
        return pages, len(pdf)
    except Exception:
        pass

    # Windows 部分环境可导入 pypdfium2，但其内置 DLL 无法打开特定 PDF。
    # PyMuPDF 作为独立引擎兜底，避免审核弹窗退化成空白或错误提示。
    try:
        import fitz
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = min(pdf.page_count, max_pages)
        pages = []
        for i in range(n):
            page = pdf.load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            from PIL import Image
            pages.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
        total = pdf.page_count
        pdf.close()
        return pages, total
    except Exception:
        return None, 0


@st.dialog("报告", width="large")
def _show_upload_report_dialog(rid: int):
    """点击「查看报告」弹出 PDF 内容（逐页转图片渲染），仅显示报告本体，不含其他操作。"""
    try:
        rows, _ = get_inspection_reports(page=1, per_page=10000)
        rpt = next((r for r in rows if r.get("id") == rid), None)
        if not rpt:
            st.warning("该报告已不存在或已完成审核。")
            return
        filename = rpt.get("filename", "") or ""
        preview_bytes = _read_file(rpt.get("file_path", ""), filename)
        if not preview_bytes:
            st.warning("报告文件无法读取")
            return
        # 紧凑的文件名 + 下载按钮（一行）
        head, dl = st.columns([6, 1])
        with head:
            st.caption(f"{filename.split('/')[-1]}")
        with dl:
            st.download_button(
                "下载", preview_bytes,
                file_name=filename.split("/")[-1],
                mime=_mime_type_for_filename(filename),
                key=f"dialog_dl_{rid}",
            )
        # 仅渲染 PDF 报告本体
        if filename.lower().endswith(".pdf"):
            pages, total = _render_pdf_pages_as_images(preview_bytes)
            if pages:
                st.caption(f"共 {total} 页")
                for i, img in enumerate(pages, 1):
                    st.image(img, caption=f"第 {i} / {total} 页", use_container_width=True)
                return
            # 不再使用 data: iframe 作为静默兜底：Chrome 在 Streamlit 弹窗中
            # 可能只显示一块白框。依赖缺失时明确报错，便于后台自动补装。
            st.error("PDF 页面渲染失败：当前运行环境缺少或无法加载 pypdfium2。")
            st.info("请重新打开报告；如果仍失败，使用上方“下载”按钮不会影响原文件。")
            return
        # 非 PDF 文件
        st.info(f"文件类型：{filename.split('.')[-1].upper()}，请使用上方「下载」按钮查看。")
    except Exception as exc:
        st.error(f"报告加载异常：{exc}")


@st.dialog("在线报告详情", width="large")
def _show_online_report_dialog(rid: int):
    """点击「查看报告」弹出的在线报告模态对话框。"""
    try:
        rep = odb.get_online_report(rid)
        if not rep:
            st.warning("该在线报告已不存在或已完成审核。")
            return
        data = rep.get("data", {}) or {}
        basic = data.get("basic", {}) or {}
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**报告 {rep.get('report_no','')}**")
            st.markdown(f"报告类型：{basic.get('type','在线 QC')}")
            st.markdown(f"品牌/SKU：{basic.get('brand','')} / {basic.get('sku','')}")
        with c2:
            st.markdown(f"状态：**{rep.get('status','')}**")
            st.markdown(f"检验员：{basic.get('inspector') or rep.get('created_by','')}")
            st.markdown(f"供应商：{basic.get('supplier','')}")
        with c3:
            st.markdown(f"提交时间：{rep.get('submitted_at') or rep.get('updated_at','')}")
            st.markdown(f"检验日期：{basic.get('date','')}")
        st.divider()
        # 完整报告内容（复用审核详情渲染）
        with st.container(border=True):
            st.markdown("### 报告内容")
            _render_online_report_safe(
                data=data, mode="view",
                key=f"dialog_online_detail_{rid}",
                photo=_build_photo_cfg(rid, st.session_state.get("user_name", "")),
            )
        st.divider()
        # 审核操作
        st.markdown("### 审核操作")
        reviewer_signature = st.text_input(
            "审核人签字（写入报告第 8 节）",
            value=st.session_state.get("user_name", ""),
            key=f"dialog_online_signature_{rid}",
            placeholder="请输入审核人姓名或签字名称",
        )
        comment = st.text_area(
            "审核员审批意见 / 驳回原因",
            key=f"dialog_online_comment_{rid}", height=80,
            placeholder="通过可填写备注；驳回必须填写具体原因",
        )
        a, b = st.columns(2)
        with a:
            if st.button("通过并归档", type="primary", key=f"dialog_online_approve_{rid}"):
                _approve_and_gen_pdf(rid, reviewer_signature=reviewer_signature, comment=comment)
                st.rerun()
        with b:
            if st.button("驳回", key=f"dialog_online_reject_{rid}"):
                reason = comment.strip()
                if not reason:
                    st.error("驳回必须填写原因")
                else:
                    odb.reject_report(rid, reviewer=st.session_state.get("user_name", ""), comment=reason)
                    # 驳回后清除服务器本地 PDF 副本（在线报告可重新提交再生成）
                    _op = rep.get("pdf_path", "") or ""
                    if _op and os.path.exists(_op):
                        try: os.remove(_op)
                        except Exception: pass
                    odb.add_audit(st.session_state.get("user_name", ""), "reject", "online_report", str(rid), reason)
                    try:
                        submitter = basic.get("inspector") or rep.get("created_by", "")
                        notify_ok, notify_msg = notify_report_rejected(
                            rid, basic.get("product") or rep.get("product_name") or "在线检验报告", submitter, reason,
                        )
                        level, text = _build_notify_notice("在线报告已驳回。", notify_ok, notify_msg, "提交人通知")
                    except Exception as exc:
                        level, text = "warning", f"在线报告已驳回，但钉钉通知异常：{exc}"
                    _queue_flash_notice(level, text)
                    st.rerun()
    except Exception as exc:
        st.error(f"在线报告加载异常：{exc}")


def _render_review_center():
    """统一审核中心：把上传报告和在线报告放到同一条主管审核队列。"""
    odb.init_online_report_table()
    upload_rows, upload_total = get_inspection_reports(status="待审核", page=1, per_page=10000)
    online_rows = []
    for summary in odb.list_online_reports():
        if summary.get("status") == odb.STATUS_PENDING:
            # 列表查询默认不解析大字段，审核中心需要完整 data 读取检验员、产品模式和照片状态。
            online_rows.append(odb.get_online_report(summary["id"]) or summary)

    st.markdown(
        '<div class="report-page-title"><div><div class="eyebrow">UNIFIED REVIEW CENTER</div>'
        '<h1>统一审核中心</h1><div class="sub">上传报告与在线检验报告统一审核、归档和通知</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="report-flow-note"><strong>审核规则：</strong>在线报告提交前已生成纸质 PDF，检验员可立即打印给工厂签字；主管审核只决定线上报告是否通过并归档。驳回必须填写原因。</div>',
        unsafe_allow_html=True,
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("⏳ 待审核总数", len(upload_rows) + len(online_rows))
    m2.metric("📤 上传报告", len(upload_rows))
    m3.metric("📝 在线报告", len(online_rows))

    st.caption("队列每 15 秒自动刷新，提交、审核和归档结果无需手动刷新页面。")

    if not upload_rows and not online_rows:
        st.success("当前没有待审核报告。")
        return

    st.subheader("待审核队列")
    for rpt in upload_rows:
        rid = rpt.get("id")
        with st.container(border=True):
            head, badge = st.columns([5, 1])
            with head:
                st.markdown(f"** 上传报告 #{rid} · {rpt.get('product_name') or '未命名产品'}**")
                st.caption(f"{rpt.get('report_type','')} · 检验员：{rpt.get('inspector','')} · {rpt.get('created_at','')}")
            with badge:
                st.markdown('<span class="status-pill status-warning">待审核</span>', unsafe_allow_html=True)
            with st.expander("审核操作", expanded=False):
                reviewer_signature = st.text_input(
                    "审核人签字（上传 PDF 将追加审核签字页）",
                    value=st.session_state.get("user_name", ""),
                    key=f"unified_upload_signature_{rid}",
                )
                comment = st.text_area("审核意见 / 驳回原因", key=f"unified_upload_comment_{rid}", height=70,
                                       placeholder="通过可填写备注；驳回必须填写具体原因")
                v, a, b, c = st.columns([1.2, 1.2, 1.2, 3])
                with v:
                    if st.button(" 查看报告", key=f"unified_upload_view_{rid}"):
                        _show_upload_report_dialog(rid)
                with a:
                    if st.button("通过并归档", type="primary", key=f"unified_upload_approve_{rid}"):
                        if not (reviewer_signature or "").strip():
                            st.error("请先填写审核人签字")
                            continue
                        if rpt.get("file_path"):
                            if not NAS_AVAILABLE:
                                ok, msg = False, "NAS 当前不可用，不能在未归档状态下通过审核"
                            else:
                                ok, msg = approve_report_with_archival(
                                    rid, brand=rpt.get("brand", ""), sku=rpt.get("sku", ""),
                                    inspection_date=rpt.get("inspection_date", ""),
                                    reviewer=reviewer_signature, comment=comment,
                                )
                        else:
                            # 仅允许没有 NAS 暂存记录的历史报告走旧状态迁移，不影响新提交的归档约束。
                            ok, msg = update_report_status(rid, "已通过")
                            if ok:
                                update_report_info(rid, reviewer=reviewer_signature)
                        if ok:
                            notify_ok, notify_msg = notify_report_approved(
                                rid, rpt.get("product_name", ""), rpt.get("inspector", "")
                            )
                            level, text = _build_notify_notice("上传报告已通过。", notify_ok, notify_msg, "检验员通知")
                            _queue_flash_notice(level, f"{text} {msg}")
                            st.rerun()
                        st.error(f"归档失败：{msg}")
                with b:
                    if st.button("驳回", key=f"unified_upload_reject_{rid}"):
                        reason = (st.session_state.get(f"unified_upload_comment_{rid}") or "").strip()
                        if not reason:
                            st.error("驳回必须填写原因")
                        else:
                            update_report_status(rid, "已驳回", reason)
                            notify_ok, notify_msg = notify_report_rejected(
                                rid, rpt.get("product_name", ""), rpt.get("inspector", ""), reason
                            )
                            level, text = _build_notify_notice("上传报告已驳回。", notify_ok, notify_msg, "检验员通知")
                            _queue_flash_notice(level, text)
                            st.rerun()

    # 在线报告必须与上传报告出现在同一个主管待审队列。
    # 每条在线报告在提交前已生成纸质 PDF；主管在此查看、通过归档或填写原因驳回。
    for rpt in online_rows:
        rid = rpt.get("id")
        data = rpt.get("data", {}) or {}
        basic = data.get("basic", {}) or {}
        submitter = basic.get("inspector") or rpt.get("created_by") or ""
        with st.container(border=True):
            head, badge = st.columns([5, 1])
            with head:
                st.markdown(f"** 在线报告 {rpt.get('report_no','')} · {basic.get('product') or rpt.get('product_name') or '未命名产品'}**")
                st.caption(f"{basic.get('type') or '在线 QC'} · 提交人：{submitter or '未填写'} · {rpt.get('updated_at') or rpt.get('created_at','')}")
            with badge:
                st.markdown('<span class="status-pill status-warning">待审核</span>', unsafe_allow_html=True)
            st.info("纸质 PDF 已在提交审核前生成；通过后将正式归档到与上传报告一致的 NAS 报告路径。")
            with st.expander("审核操作", expanded=False):
                reviewer_signature = st.text_input(
                    "审核人签字（写入报告第 8 节）",
                    value=st.session_state.get("user_name", ""),
                    key=f"unified_online_signature_{rid}",
                    placeholder="请输入审核人姓名或签字名称",
                )
                comment = st.text_area("审核意见 / 驳回原因", key=f"unified_online_comment_{rid}", height=70,
                                       placeholder="通过可填写备注；驳回必须填写具体原因")
                v, a, b, _ = st.columns([1.2, 1.2, 1.2, 3])
                with v:
                    if st.button(" 查看报告", key=f"unified_online_view_{rid}"):
                        _show_online_report_dialog(rid)
                with a:
                    if st.button("通过并归档", type="primary", key=f"unified_online_approve_{rid}"):
                        _approve_and_gen_pdf(rid, reviewer_signature=reviewer_signature, comment=comment)
                        st.rerun()
                with b:
                    if st.button("驳回", key=f"unified_online_reject_{rid}"):
                        reason = (st.session_state.get(f"unified_online_comment_{rid}") or "").strip()
                        if not reason:
                            st.error("驳回必须填写原因")
                        else:
                            odb.reject_report(rid, reviewer=st.session_state.get("user_name", ""), comment=reason)
                            # 驳回后清除服务器本地 PDF 副本（在线报告可重新提交再生成）
                            _op = rpt.get("pdf_path", "") or ""
                            if _op and os.path.exists(_op):
                                try: os.remove(_op)
                                except Exception: pass
                            odb.add_audit(st.session_state.get("user_name", ""), "reject", "online_report", str(rid), reason)
                            try:
                                notify_ok, notify_msg = notify_report_rejected(
                                    rid, basic.get("product") or rpt.get("product_name") or "在线检验报告", submitter, reason
                                )
                                level, text = _build_notify_notice("在线报告已驳回。", notify_ok, notify_msg, "提交人通知")
                            except Exception as exc:
                                level, text = "warning", f"在线报告已驳回，但钉钉通知异常：{exc}"
                            _queue_flash_notice(level, text)
                            st.rerun()


# ---- 全屏新窗口编辑器检测：所有提交/PDF流程函数加载完成后再拦截 ----
_qpf = st.query_params
if "or_full" in _qpf:
    _qpf_val = _qpf["or_full"]
    if isinstance(_qpf_val, list):
        _qpf_val = _qpf_val[0] if _qpf_val else ""
    if str(_qpf_val) == "1":
        _rid = _qpf.get("or_rid", None)
        if isinstance(_rid, list):
            _rid = _rid[0] if _rid else None
        _fullscreen_editor(_rid)
        st.stop()

def _render_unified_review_detail():
    """审核中心选中一条记录后的详情工作区，复用报告详情的审核信息层级。"""
    selected = st.session_state.get("review_selected")
    if not selected:
        return
    source, rid = selected
    st.markdown("---")
    st.subheader("报告详情与审核工作区")
    if source == "upload":
        try:
            rows, _ = get_inspection_reports(page=1, per_page=10000)
            rpt = next((r for r in rows if r.get("id") == rid), None)
            if not rpt:
                st.warning("该报告已不存在或已完成审核。")
                st.session_state.pop("review_selected", None)
                return
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**报告 #{rid}**")
                st.markdown(f"报告类型：{rpt.get('report_type','')}")
                st.markdown(f"品牌/SKU：{rpt.get('brand','')} / {rpt.get('sku','')}")
                st.markdown(f"检验员：{rpt.get('inspector','')}")
            with c2:
                st.markdown(f"状态：**{rpt.get('status','')}**")
                st.markdown(f"审核人：{rpt.get('reviewer','')}")
                st.markdown(f"供应商：{rpt.get('supplier','')}")
            with c3:
                st.markdown(f"提交时间：{rpt.get('created_at','')}")
                st.markdown(f"检验日期：{rpt.get('inspection_date','')}")
                if rpt.get("reject_reason"):
                    st.error(f"驳回原因：{rpt['reject_reason']}")
            with st.container(border=True):
                st.markdown("### 审核操作")
                filename = rpt.get("filename", "") or ""
                preview_bytes = _read_file(rpt.get("file_path", "") or rpt.get("nas_report_path", ""), filename)
                if not preview_bytes and rpt.get("nas_report_path") and NAS_AVAILABLE:
                    try:
                        preview_bytes, filename = nas_download(rpt["nas_report_path"])
                    except Exception:
                        preview_bytes = None
                if preview_bytes:
                    x, y, z = st.columns([1, 3, 1])
                    with x:
                        st.markdown("文件")
                    with y:
                        st.caption(filename.split("/")[-1])
                    with z:
                        st.download_button("下载", preview_bytes, file_name=filename.split("/")[-1],
                                           mime=_mime_type_for_filename(filename), key=f"unified_detail_dl_{rid}")
                reviewer_signature = st.text_input(
                    "审核人签字（上传 PDF 将追加审核签字页）",
                    value=st.session_state.get("user_name", "") or rpt.get("reviewer", ""),
                    key=f"unified_detail_upload_signature_{rid}",
                )
                comment = st.text_area("审核员审批意见 / 驳回原因", value=rpt.get("review_comment", "") or "",
                                       placeholder="通过可填写备注；驳回必须填写具体原因", key=f"unified_detail_comment_{rid}", height=80)
                a, b = st.columns(2)
                with a:
                    if st.button("通过并归档", type="primary", key=f"unified_detail_approve_{rid}"):
                        if not (reviewer_signature or "").strip():
                            st.error("请先填写审核人签字")
                            return
                        if rpt.get("file_path"):
                            if not NAS_AVAILABLE:
                                ok, msg = False, "NAS 当前不可用，不能在未归档状态下通过审核"
                            else:
                                ok, msg = approve_report_with_archival(
                                    rid, brand=rpt.get("brand", ""), sku=rpt.get("sku", ""),
                                    inspection_date=rpt.get("inspection_date", ""),
                                    reviewer=reviewer_signature, comment=comment,
                                )
                        else:
                            ok, msg = update_report_status(rid, "已通过")
                            if ok:
                                update_report_info(rid, reviewer=reviewer_signature)
                        if ok:
                            notify_ok, notify_msg = notify_report_approved(rid, rpt.get("product_name", ""), rpt.get("inspector", ""))
                            level, text = _build_notify_notice("报告已通过。", notify_ok, notify_msg, "检验员通知")
                            _queue_flash_notice(level, f"{text} {msg}")
                            st.session_state.pop("review_selected", None)
                            st.rerun()

                        st.error(f"归档失败：{msg}")
                with b:
                    if st.button("驳回", key=f"unified_detail_reject_{rid}"):
                        reason = (st.session_state.get(f"unified_detail_comment_{rid}") or "").strip()
                        if not reason:
                            st.error("驳回必须填写原因")
                        else:
                            update_report_review_comment(rid, reason)
                            update_report_status(rid, "已驳回", reason)
                            notify_ok, notify_msg = notify_report_rejected(rid, rpt.get("product_name", ""), rpt.get("inspector", ""), reason)
                            level, text = _build_notify_notice("报告已驳回。", notify_ok, notify_msg, "检验员通知")
                            _queue_flash_notice(level, text)
                            st.session_state.pop("review_selected", None)
                            st.rerun()
        except Exception as exc:
            st.error(f"上传报告详情加载异常：{exc}")
            if st.button("↺ 重试", key=f"unified_retry_upload_{rid}"):
                st.rerun()
    else:
        try:
            rep = odb.get_online_report(rid)
            if not rep:
                st.warning("该在线报告已不存在或已完成审核。")
                st.session_state.pop("review_selected", None)
                return
            data = rep.get("data", {}) or {}
            basic = data.get("basic", {}) or {}
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**报告 {rep.get('report_no','')}**")
                st.markdown(f"报告类型：{basic.get('type','在线 QC')}")
                st.markdown(f"品牌/SKU：{basic.get('brand','')} / {basic.get('sku','')}")
            with c2:
                st.markdown(f"状态：**{rep.get('status','')}**")
                st.markdown(f"检验员：{basic.get('inspector') or rep.get('created_by','')}")
                st.markdown(f"供应商：{basic.get('supplier','')}")
            with c3:
                st.markdown(f"提交时间：{rep.get('submitted_at') or rep.get('updated_at','')}")
                st.markdown(f"检验日期：{basic.get('date','')}")
                st.markdown(f"产品模式：{'旧品（照片仅 NAS）' if basic.get('productMode') == 'old' else '新品（照片进入 PDF）'}")
            with st.container(border=True):
                st.markdown("### 在线报告审核操作")
                reviewer_signature = st.text_input(
                    "审核人签字（写入报告第 8 节）",
                    value=st.session_state.get("user_name", ""),
                    key=f"unified_online_detail_signature_{rid}",
                    placeholder="请输入审核人姓名或签字名称",
                )
                _render_online_report_safe(data=data, mode="view", key=f"unified_online_detail_{rid}",
                                           photo=_build_photo_cfg(rid, st.session_state.get("user_name", "")))
                comment = st.text_area("审核员审批意见 / 驳回原因", key=f"unified_online_detail_comment_{rid}", height=80,
                                       placeholder="通过可填写备注；驳回必须填写具体原因")
                a, b = st.columns(2)
                with a:
                    if st.button("通过并归档", type="primary", key=f"unified_online_detail_approve_{rid}"):
                        _approve_and_gen_pdf(rid, reviewer_signature=reviewer_signature, comment=comment)
                        st.session_state.pop("review_selected", None)
                        st.rerun()
                with b:
                    if st.button("驳回", key=f"unified_online_detail_reject_{rid}"):
                        reason = (st.session_state.get(f"unified_online_detail_comment_{rid}") or "").strip()
                        if not reason:
                            st.error("驳回必须填写原因")
                        else:
                            submitter = basic.get("inspector") or rep.get("created_by", "")
                            odb.reject_report(rid, reviewer=st.session_state.get("user_name", ""), comment=reason)
                            odb.add_audit(st.session_state.get("user_name", ""), "reject", "online_report", str(rid), reason)
                            notify_ok, notify_msg = notify_report_rejected(rid, basic.get("product") or rep.get("product_name", "在线检验报告"), submitter, reason)
                            level, text = _build_notify_notice("在线报告已驳回。", notify_ok, notify_msg, "提交人通知")
                            _queue_flash_notice(level, text)
                            st.session_state.pop("review_selected", None)
                            st.rerun()
        except Exception as exc:
            st.error(f"报告详情加载异常：{exc}")
            st.button("↺ 重试", key=f"unified_retry_{rid}", on_click=lambda: st.rerun())


def _render_review_workspace_content():
    """审核中心工作区。点击「查看报告」通过 st.dialog 弹窗直接弹出报告详情。"""
    try:
        _render_review_center()
    except Exception as exc:
        st.error(f"审核中心加载异常：{exc}")
        if st.button("↺ 刷新页面"):
            st.rerun()


# 队列独立刷新，避免主管依赖手工刷新才能看到提交、审核和归档结果。
if hasattr(st, "fragment"):
    _render_review_workspace = st.fragment(run_every="15s")(_render_review_workspace_content)
else:
    _render_review_workspace = _render_review_workspace_content


# ============ 全屏新窗口编辑器（通过 window.open 打开的新标签页） ============

# ---- 在线报告 Tab（2026-07-12 恢复：用户确认需要，在线 QC 闭环功能完整保留） ----
with tab_online:
    _online_report_tab()


# ---- 统一审核中心：上传报告 + 在线报告 ----
with tab_review:
    # 仅系统管理员和审核员可查看待审核队列；普通检验员无权访问
    _rc_admin = bool(st.session_state.get("is_admin", False))
    _rc_dev = st.session_state.get("user_name", "").endswith("(开发者)")
    if not (_rc_admin or _rc_dev):
        st.markdown(
            '<div style="padding:40px;text-align:center;color:#666;">'
      '<h3> 审核中心</h3>'
            '<p>待审核队列仅允许<strong>系统管理员</strong>和<strong>审核员</strong>查看。</p>'
            '<p>如有疑问请联系管理员。</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        _render_review_workspace()
