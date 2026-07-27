"""
通用工具模块
- creatable_select / creatable_multi_select：可新建选项的下拉框
- render_sidebar()：共享侧边栏导航（所有页面共用）
"""

import streamlit as st
import os
import sys
from datetime import datetime
from config import get_logo_path, BASE_DIR, is_admin_email

# 统一设计令牌（单一来源）：assets/tokens.css
_TOKENS_CSS = ""
try:
    with open(os.path.join(BASE_DIR, "assets", "tokens.css"), "r", encoding="utf-8") as _tf:
        _TOKENS_CSS = _tf.read()
except Exception:
    _TOKENS_CSS = ""


def apply_ui_system():
    """Inject the shared QMS visual language used by every page."""
    # 注入统一设计令牌（assets/tokens.css，单一来源）
    st.html(f"<style>{_TOKENS_CSS}</style>")
    st.html("""
    <style>
    /* 设计令牌统一由 assets/tokens.css 注入，此处不再定义 :root */
    /* F8：移除 .stApp 背景覆盖，背景交由全局画布令牌控制 */
    .stApp { color: var(--qms-ink); }
    header[data-testid="stHeader"] { display: none !important; }
    .block-container {
        max-width: 1540px !important;
        padding: 1.5rem 2rem 3rem !important;
    }
    h1, h2, h3 { color: var(--qms-ink) !important; letter-spacing: -0.02em; }
    h1 { font-size: clamp(1.8rem, 2.5vw, 2.35rem) !important; margin-bottom: .2rem !important; }
    h2 { font-size: 1.45rem !important; }
    h3 { font-size: 1.08rem !important; }
    [data-testid="stCaptionContainer"] { color: var(--qms-muted); }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--qms-line) !important;
        border-radius: var(--qms-radius) !important;
        background: var(--qms-surface);
        box-shadow: 0 10px 26px rgba(16, 42, 67, .06);
    }
    [data-testid="stHorizontalBlock"] { gap: 16px !important; }
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        padding: 8px 14px;
        font-size: 14px;
        line-height: 1.25;
    }
    [data-baseweb="tab-list"] {
        padding: 4px 6px 0;
        background: rgba(255,255,255,.72);
        border: 1px solid var(--qms-line);
        border-radius: 12px 12px 0 0;
    }
    [data-baseweb="tab"] {
        min-height: 44px;
        border-radius: 9px 9px 0 0;
        transition: color .15s ease, background .15s ease;
    }
    [data-baseweb="tab"] p { font-size: 14px !important; font-weight: 650 !important; }
    [data-baseweb="tab"][aria-selected="true"] { background: var(--qms-blue-soft); }
    [data-testid="stExpander"] {
        border: 1px solid var(--qms-line) !important;
        border-radius: 12px !important;
        background: rgba(255,255,255,.82) !important;
        box-shadow: 0 8px 20px rgba(16,42,67,.04);
    }
    [data-testid="stExpander"] summary { padding: 10px 14px !important; }
    [data-testid="stExpander"] summary p { font-size: 14px !important; font-weight: 700 !important; }
    [data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input, [data-testid="stDateInput"] input {
        min-height: 40px;
        font-size: 14px;
    }
    /* Every page uses the same raised KPI tile, including bottom resource areas. */
    div[data-testid="stMetric"] {
        background: var(--qms-surface);
        border: 1px solid var(--qms-line);
        border-radius: 14px;
        padding: 15px 17px;
        box-shadow: 0 10px 24px rgba(16, 42, 67, .07);
        min-height: 88px;
    }
    div[data-testid="stMetric"] label {
        color: var(--qms-muted) !important;
        font-weight: 650;
    }
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
        min-height: 40px;
        border-radius: 9px;
        border: 1px solid var(--qms-line);
        font-weight: 600;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover,
    .stFormSubmitButton > button:hover {
        border-color: var(--qs-border-hover);
        box-shadow: 0 4px 12px rgba(37, 99, 235, .12);
    }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
        background: var(--qms-blue);
        border-color: var(--qms-blue);
        color: white;
    }
    .stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
    .stTextInput input:focus-visible, .stTextArea textarea:focus-visible,
    [data-baseweb="select"] *:focus-visible {
        outline: 3px solid rgba(37, 99, 235, .24) !important;
        outline-offset: 2px;
    }
    .qms-page-header { display:flex; justify-content:space-between; align-items:flex-end; gap:24px; margin:4px 0 22px; }
    .qms-page-header h1 { margin:0 !important; }
    .qms-eyebrow { color:var(--qms-blue); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin-bottom:6px; }
    .qms-page-header p { color:var(--qms-muted); margin:7px 0 0; font-size:14px; }
    .qms-page-actions { display:flex; gap:8px; align-items:center; justify-content:flex-end; }
    .qms-panel, .qms-card { background:var(--qms-surface); border:1px solid var(--qms-line); border-radius:var(--qms-radius); box-shadow:var(--qms-shadow); }
    .qms-panel { padding:20px; }
    .qms-card { padding:16px; }
    .qms-section-title { display:flex; justify-content:space-between; align-items:center; gap:12px; margin:24px 0 12px; color:var(--qms-ink); font-size:17px; font-weight:750; }
    .qms-section-title small { color:var(--qms-muted); font-size:12px; font-weight:500; }
    .qms-action-group { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    .qms-help-text { color:var(--qms-muted); font-size:13px; line-height:1.6; }
    .qms-empty { padding:28px 20px; text-align:center; color:var(--qms-muted); border:1px dashed var(--qms-line); border-radius:var(--qms-radius-sm); background:#fbfcfe; }
    .qms-danger-zone { border:1px solid var(--qs-danger-border); border-radius:var(--qms-radius); background:var(--qs-danger-bg); padding:16px; }
    .qms-status { display:inline-flex; align-items:center; gap:6px; min-height:26px; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:700; line-height:1.2; white-space:nowrap; }
    .qms-status.is-draft { color:var(--qs-neutral-tx); background:var(--qs-neutral-bg); }
    .qms-status.is-pending { color:var(--qs-amber-tx); background:var(--qs-warning-bg); }
    .qms-status.is-approved { color:var(--qs-green-tx); background:var(--qs-success-bg); }
    .qms-status.is-rejected, .qms-status.is-risk { color:var(--qs-red-tx); background:var(--qs-danger-bg); }
    .qms-status.is-neutral { color:var(--qms-muted); background:var(--qs-neutral-bg); }
    /* F6：危险操作按钮（删除等）。红色令牌样式，仅颜色/边框反馈，无位移/缩放动画。 */
    .qms-danger-btn-wrap button {
        background: var(--qs-danger) !important;
        border-color: var(--qs-danger) !important;
        color: var(--qs-white) !important;
        transition: background .15s ease, border-color .15s ease;
    }
    .qms-danger-btn-wrap button:hover:not(:disabled) {
        background: var(--qs-danger-hover) !important;
        border-color: var(--qs-danger-hover) !important;
    }
    /* F14：加载骨架占位，纯色脉冲（简洁，无位移/缩放） */
    .qms-skeleton { display:flex; flex-direction:column; gap:8px; }
    .qms-skeleton > span {
        display:block; height:12px; border-radius:6px;
        background: var(--qs-neutral-bg);
        animation: qms-pulse 1.2s ease-in-out infinite;
    }
    @keyframes qms-pulse { 0%,100% { opacity:.45; } 50% { opacity:1; } }
    .qms-kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; }
    .qms-kpi { background:var(--qms-surface); border:1px solid var(--qms-line); border-radius:var(--qms-radius); padding:16px 18px; box-shadow:var(--qms-shadow); }
    .qms-kpi-label { color:var(--qms-muted); font-size:13px; font-weight:600; }
    .qms-kpi-value { color:var(--qms-ink); font-size:28px; font-weight:800; line-height:1.15; margin:7px 0 4px; }
    .qms-table-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:8px 0 12px; }
    [data-testid="stDataFrame"] { box-shadow:0 1px 3px rgba(16,42,67,.04); }
    [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--qms-line); }
    [data-baseweb="tab"] {
        min-height: 42px;
        padding: 0 14px;
        border-radius: 9px 9px 0 0;
        color: var(--qms-muted);
        font-weight: 600;
    }
    [data-baseweb="tab"][aria-selected="true"] { color: var(--qms-blue); }
    [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea, [data-baseweb="select"] {
        border-radius: 8px;
        border-color: var(--qms-line);
    }
    [data-testid="stDataFrame"] { border: 1px solid var(--qms-line); border-radius: 12px; overflow: hidden; box-shadow: 0 8px 20px rgba(16,42,67,.05); }
    [data-testid="stAlert"] { border-radius: 10px; }
    @media (max-width: 760px) {
        .block-container { padding: 1rem .8rem 2rem !important; }
        [data-baseweb="tab"] { padding: 0 8px; font-size: .82rem; }
        .qms-page-header { align-items:flex-start; flex-direction:column; gap:12px; }
        .qms-page-actions { justify-content:flex-start; width:100%; }
        .qms-panel { padding:14px; }
    }
    </style>
    """)

# ── 共享 UI 组件（仅表现层，不含业务/鉴权逻辑）──
_STATUS_VARIANTS = {"draft", "pending", "approved", "rejected", "risk", "neutral"}


def ui_status_badge(text, variant="neutral"):
    """渲染与全站设计令牌一致的 status pill。

    variant ∈ draft | pending | approved | rejected | risk | neutral
    返回可直接放入 st.markdown(..., unsafe_allow_html=True) 的 HTML 片段。
    """
    if variant not in _STATUS_VARIANTS:
        variant = "neutral"
    return f'<span class="qms-status is-{variant}">{text}</span>'


def ui_empty_state(title, hint=""):
    """渲染统一的空状态块（.qms-empty）。仅表现层。"""
    hint_html = f'<div style="margin-top:6px;font-size:13px;">{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="qms-empty">'
        f'<div style="font-weight:700;color:var(--qms-ink);font-size:15px;margin-bottom:4px;">{title}</div>'
        f'{hint_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def ui_danger_button(label, key=None, help=None, disabled=False,
                     on_click=None, args=None, kwargs=None,
                     use_container_width=False, **extra):
    """危险操作按钮：红色令牌样式（.qms-btn-danger / F6），仅表现层。

    实际删除动作须由调用方用 components.modal.confirm_dialog() 做二次确认。
    语义与 st.button 一致，可透传 key/help/disabled/on_click/use_container_width 等参数。
    """
    st.markdown('<div class="qms-danger-btn-wrap">', unsafe_allow_html=True)
    clicked = st.button(
        label, key=key, help=help, disabled=disabled,
        on_click=on_click, args=args, kwargs=kwargs,
        use_container_width=use_container_width, **extra
    )
    st.markdown('</div>', unsafe_allow_html=True)
    return clicked


def ui_skeleton(lines=3):
    """加载骨架占位（.qms-skeleton）。纯色脉冲，简洁，替代转圈 spinner。"""
    bars = "".join('<span></span>' for _ in range(lines))
    st.markdown(f'<div class="qms-skeleton">{bars}</div>', unsafe_allow_html=True)


def ui_table(df, **kwargs):
    """统一表格渲染包装（.qms-table 风格由 apply_ui_system 的 [data-testid=stDataFrame] 控制）。

    直接透传 st.dataframe，便于全站统一表格范式与后续治理。
    """
    return st.dataframe(df, **kwargs)


def ui_data_editor(df, **kwargs):
    """统一可编辑表格渲染包装，透传 st.data_editor。"""
    return st.data_editor(df, **kwargs)


# ── 缓存：侧边栏统计查询（短缓存，保证跨页面操作后及时更新）──
# 短缓存（60s）：侧边栏统计需要跨页面操作后及时刷新，但无需每次都查 DB
@st.cache_data(ttl=60, show_spinner=False)
def _cached_lab_stats():
    from database import get_dashboard_stats
    return get_dashboard_stats()

# 短缓存（60s）
@st.cache_data(ttl=60, show_spinner=False)
def _cached_inspection_stats():
    from database import get_inspection_dashboard_stats
    return get_inspection_dashboard_stats()

# 短缓存（60s）
@st.cache_data(ttl=60, show_spinner=False)
def _cached_sample_stats():
    from database import get_sample_dashboard_stats
    return get_sample_dashboard_stats()

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_logo_b64():
    """缓存 Logo base64（1小时），避免每次读磁盘"""
    logo_path = get_logo_path()
    if os.path.exists(logo_path):
        import base64 as _base64
        with open(logo_path, "rb") as _lf:
            return _base64.b64encode(_lf.read()).decode()
    return ""

# ── 导航配置 ──
# 每个元素：(label, icon, page_path_or_children, *flags)
#   - 若第3个元素是字符串 → 普通按钮
#   - 若第3个元素是列表   → 分组标题，列表内含子项
# 子项格式：(label, icon, page_path, *flags)，flags 支持 "local_only"
NAV_ITEMS = [
    ("首页展示总览", "🏠", "pages/page_workbench.py"),
    ("实验室管理", "🔬", [
        ("使用登记",   "📝", "pages/page_usage.py"),
        ("借用归还",   "🔄", "pages/page_borrow.py"),
        ("设备台账",   "🖥️", "pages/page_equipment.py"),
        ("维护记录",   "🔧", "pages/page_maintenance.py"),
    ]),
    ("品质日常管理", "✅", [
        ("检验报告",   "📄", "pages/page_reports.py"),
        ("变更管理",   "🔄", "pages/page_changes.py"),
        ("样品管理",   "🧪", "pages/page_samples.py"),
        ("驻厂登记",   "🏭", "pages/page_factory_registration.py"),
        ("数据看板",   "📊", "pages/page_dashboard.py"),
    ]),
    ("系统", "⚙️", [
        ("版本日志",   "📋", "pages/page_changelog.py"),
        ("关于系统",   "ℹ️", "pages/page_about.py"),
        ("系统监控",   "📈", "pages/page_monitor.py"),
        ("操作审计",   "🔒", "pages/page_audit.py"),
        ("误删找回",   "♻️", "pages/page_recycle.py"),
    ]),
]


def _render_nav_tree(navigation_page_map, show_restricted, using_navigation_api):
    """Render one shared, collapsible two-level navigation tree without touching business state."""
    for item in NAV_ITEMS:
        label, icon, third, *flags = item
        if "local_only" in flags and not show_restricted:
            continue

        if isinstance(third, list):
            with st.expander(f"{icon} {label}", expanded=True):
                for child in third:
                    child_label, child_icon, child_path, *child_flags = child
                    if "local_only" in child_flags and not show_restricted:
                        continue
                    child_page = (navigation_page_map.get(child_path)
                                  if using_navigation_api else child_path)
                    if child_page is None:
                        continue
                    st.page_link(
                        child_page,
                        label=child_label,
                        icon=child_icon,
                        width="stretch",
                    )
        else:
            page_obj = (navigation_page_map.get(third)
                        if using_navigation_api else third)
            if page_obj is not None:
                st.page_link(page_obj, label=label, icon=icon, width="stretch")


def _recover_user_name_from_sidebar():
    """最终降级：当 session_state.user_name 为空时，尝试从 cookie / 邮箱恢复显示名。

    覆盖场景：
    - _try_cookie_login() 因 st.context.cookies 异常而静默失败
    - Streamlit 刷新后 session_state 重置但 cookie 仍有效
    - 旧格式 cookie（无 name 段）需要查库映射中文姓名
    """
    import hashlib, time as _time

    # ① 直接读 cookie（绕过可能失败的 _try_cookie_login）
    try:
        cookies = st.context.cookies
        auth_token = (cookies.get("qs_auth") or "").strip()
        if auth_token:
            # Keep recovery validation on exactly the same secret as the OAuth
            # callback.  A hard-coded fallback would accept forged legacy
            # cookies when a deployment lost its environment configuration.
            from oauth_handler import _COOKIE_SECRET
            secret = _COOKIE_SECRET
            parts = auth_token.split("|")
            email, name = "", ""

            if len(parts) == 4:
                # 新格式：email|exp|name|sig
                e, exp_ts, n, sig = parts
                payload = f"{e}|{exp_ts}|{n}"
                expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
                if sig == expected and _time.time() < int(exp_ts):
                    email, name = e, n
            elif len(parts) == 3:
                # 旧格式：email|exp|sig
                e, exp_ts, sig = parts
                payload = f"{e}|{exp_ts}"
                expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
                if sig == expected and _time.time() < int(exp_ts):
                    email = e

            # 有名字直接返回
            if name and name.strip():
                # 回写 session_state 让后续代码也能用
                st.session_state["user_name"] = name.strip()
                if email and not st.session_state.get("user_email"):
                    st.session_state["user_email"] = email
                return name.strip()

            # 无名字但有邮箱 → 查 quality_users 映射
            if email:
                from database import get_quality_users_list
                users = get_quality_users_list()
                if users:
                    prefix = (email.split("@")[0] or "").strip().lower()
                    for u in users:
                        s = str(u).strip() if u else ""
                        if not s: continue
                        sl = s.lower()
                        if sl.startswith(prefix) and len(s) > len(prefix):
                            np_ = s[len(prefix):].strip()
                            if np_ and any(ord(c) > 127 for c in np_):
                                st.session_state["user_name"] = np_
                                if not st.session_state.get("user_email"):
                                    st.session_state["user_email"] = email
                                return np_
                # 库映射也失败 → 返回邮箱前缀
                return email.split("@")[0]
    except Exception:
        pass

    # ② cookie 也读不到 → 从已有的 user_email 做最后一次映射
    existing_email = (st.session_state.get("user_email") or "").strip()
    if existing_email and "@" in existing_email:
        try:
            from database import get_quality_users_list
            users = get_quality_users_list()
            if users:
                prefix = existing_email.split("@")[0].strip().lower()
                for u in users:
                    s = str(u).strip() if u else ""
                    if not s: continue
                    sl = s.lower()
                    if sl.startswith(prefix) and len(s) > len(prefix):
                        np_ = s[len(prefix):].strip()
                        if np_ and any(ord(c) > 127 for c in np_):
                            st.session_state["user_name"] = np_
                            return np_
            return existing_email.split("@")[0]
        except Exception:
            pass

    return ""


@st.fragment
def _render_datasource_fragment():
    """数据源状态卡片 + 重连按钮。

    用 @st.fragment 包裹，使点击「重连 Win」只局部刷新本卡片，
    不再触发整页重跑（否则会重新查询侧边栏统计、重建导航树）。
    """
    try:
        from database import get_global_datasource_status, invalidate_remote_cache
        ds = get_global_datasource_status()
        if ds["is_remote"] or ds["source"] == "local":
            # Mac 环境：显示远程/本地状态
            st.markdown(
                f'<div class="qms-datasource-card" style="padding:11px 12px;border-radius:10px;'
                f'background:#102a43;border:1px solid rgba(219,234,254,.28);font-size:13px;">'
                f'<div style="color:#f8fafc;font-weight:700;margin-bottom:5px;line-height:1.35;">'
                f'{ds["icon"]} 数据源：{ds["label"]}</div>'
                f'<div style="color:#bfdbfe;font-size:12px;line-height:1.5;word-break:break-word;">'
                f'{ds.get("detail", "")[:80]}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            # 手动刷新按钮（远程断开时提供重试）
            if ds["source"] == "local" and sys.platform == "darwin":
                if st.button("重连 Win", key=f"sidebar_reconnect_{_current_page_id()}", width="stretch"):
                    invalidate_remote_cache()
                    st.rerun()
    except Exception:
        pass  # 数据源检测异常时静默跳过，不影响导航


def render_sidebar(logo_b64=None, lab_stats=None, inspection_stats=None, sample_stats=None):
    """
    渲染共享侧边栏导航。
    在所有页面（page_workbench.py 和 _pages/*.py）的 with st.sidebar 块中调用。

    性能优化：统计查询使用 st.cache_data 缓存，导航使用 st.page_link 实现客户端即时切换。
    """
    apply_ui_system()
    using_navigation_api = st.session_state.get("_using_navigation_api", False)

    # Shared workbench shell: keep every page on the same dark navigation rail.
    # The page body remains light so tables/forms stay readable and print-friendly.
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] {
        background: #102a43 !important;
        border-right: 0 !important;
    }
    section[data-testid="stSidebar"] * { color: #dbeafe; }
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] strong { color: #f8fafc !important; }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stCaption,
    section[data-testid="stSidebar"] small { color: #9fb3c8 !important; }
    section[data-testid="stSidebar"] a {
        color: #dbeafe !important;
        border-radius: 9px;
        transition: background .15s ease, color .15s ease;
    }
    section[data-testid="stSidebar"] a:hover {
        background: #243f63 !important;
        color: #ffffff !important;
    }
    section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
        padding: 9px 12px 9px 18px;
        margin: 3px 0;
        font-size: 14px !important;
        font-weight: 650 !important;
        border-left: 2px solid transparent;
    }
    section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {
        border-left-color: #60a5fa;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        border: 0 !important;
        background: transparent !important;
        margin: 3px 0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
        min-height: 44px;
        padding: 7px 10px !important;
        border-radius: 9px;
        background: rgba(36, 63, 99, .52);
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background: #2b4e78;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
        font-size: 17px !important;
        font-weight: 800 !important;
        letter-spacing: .01em;
        color: #f8fafc !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
        padding: 6px 0 4px 8px !important;
        border-left: 1px solid rgba(147, 197, 253, .32);
        margin-left: 14px;
    }
    section[data-testid="stSidebar"] hr {
        border-color: rgba(219,234,254,.16) !important;
    }
    section[data-testid="stSidebar"] button {
        color: #dbeafe !important;
        border-color: rgba(219,234,254,.22) !important;
        background: transparent !important;
    }
    section[data-testid="stSidebar"] button:hover {
        background: #243f63 !important;
        border-color: #60a5fa !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 仅在旧版多页面模式下隐藏原生导航；st.navigation 模式必须保留原生导航
    if not using_navigation_api:
        st.markdown("""
        <style>
        [data-testid="stSidebarNav"] {
            display: none;
        }
        </style>
        """, unsafe_allow_html=True)

    # 延迟加载统计数据（带缓存）
    if lab_stats is None:
        try:
            lab_stats = _cached_lab_stats()
        except Exception:
            lab_stats = {"total": 0, "available": 0, "in_use": 0, "borrowed": 0}
    if inspection_stats is None:
        try:
            inspection_stats = _cached_inspection_stats()
        except Exception:
            inspection_stats = {"total": 0, "this_month": 0, "pending": 0}
    if sample_stats is None:
        try:
            sample_stats = _cached_sample_stats()
        except Exception:
            sample_stats = {"total": 0, "in_stock": 0, "out_stock": 0, "expired": 0, "near_expiry": 0}

    # ── Logo + 标题 ──
    # 如果未传入 logo_b64，自动从固定路径加载（缓存）
    if not logo_b64:
        logo_b64 = _cached_logo_b64()

    if logo_b64:
        st.markdown(
            f'<div style="text-align:center;padding:8px 0 4px 0;">'
            f'<img src="data:image/png;base64,{logo_b64}"'
            f'style="width:160px;opacity:0.9;" alt="SainStore"></div>',
            unsafe_allow_html=True
        )

    st.markdown(
        '<h3 style="margin:2px 0 0 0;color:#1e293b;font-size:15px;text-align:center;">'
        '品质系统管理</h3>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<p style="margin:4px 0 8px 0;color:#64748b;font-size:11px;text-align:center;letter-spacing:0.3px;">'
        'Quality Management System</p>',
        unsafe_allow_html=True
    )

    # ── 关键数据摘要（紧凑型）──
    st.markdown("---")
    st.markdown(f"""
    <div style="display:flex;gap:8px;padding:0 4px;margin:6px 0;">
        <div style="flex:1;text-align:center;background:#f8fafc;border-radius:10px;padding:10px 6px;border:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;margin-bottom:2px;">🔧 设备</div>
            <div style="font-size:18px;font-weight:700;color:#1e293b;">{lab_stats['total']}<span style="font-size:10px;font-weight:400;color:#94a3b8;">台</span></div>
        </div>
        <div style="flex:1;text-align:center;background:#f8fafc;border-radius:10px;padding:10px 6px;border:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;margin-bottom:2px;">📄 报告</div>
            <div style="font-size:18px;font-weight:700;color:#1e293b;">{inspection_stats['total']}<span style="font-size:10px;font-weight:400;color:#94a3b8;">份</span></div>
        </div>
        <div style="flex:1;text-align:center;background:#f8fafc;border-radius:10px;padding:10px 6px;border:1px solid #e2e8f0;">
            <div style="font-size:11px;color:#64748b;margin-bottom:2px;">🧪 样品</div>
            <div style="font-size:18px;font-weight:700;color:#1e293b;">{sample_stats['total']}<span style="font-size:10px;font-weight:400;color:#94a3b8;">个</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    # ── 判断本地 / 管理员可见性 ──
    is_admin = False
    try:
        _email = (st.session_state.get("user_email") or "").strip().lower()
        is_admin = is_admin_email(_email)
    except Exception:
        pass
    show_restricted = is_admin  # 与 main.py 的管理员页面注册条件一致

    # ── 导航区：一级业务域 / 二级功能页；三级功能留在页面内部 Tab ──
    navigation_page_map = st.session_state.get("_nav_page_objects", {})
    _render_nav_tree(navigation_page_map, show_restricted, using_navigation_api)

    st.markdown("---")

    # ── 全局数据源指示器（Mac 开发环境显示 Win 连接状态）──
    # 用 @st.fragment 包裹，点击「重连 Win」只局部刷新本卡片，不触发整页重跑
    _render_datasource_fragment()

    st.caption(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.caption("© SainStore | Bruce Cheng 程强")

    # ── 底部：当前用户身份（紧凑一行，不含退出按钮——顶部栏已有）──
    # 多层降级：session_state → cookie直读 → 邮箱前缀 → 库查映射 → "用户"
    _sb_user = (st.session_state.get("user_name") or "").strip()
    if not _sb_user or _sb_user == "用户":
        _sb_user = _recover_user_name_from_sidebar()
    if not _sb_user or _sb_user == "用户":
        _email_pfx = (st.session_state.get("user_email") or "").split("@")[0]
        _sb_user = _email_pfx or ("(已登录)" if st.session_state.get("authenticated") else "(未登录)")
    # 在线状态指示（当前用户必然在线；后续可扩展为从 operation_log 读最近活跃同事）
    _sb_online = "🟢 在线" if st.session_state.get("authenticated") else "⚪ 离线"
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'padding:6px 8px;margin-top:4px;border-radius:6px;background:#f1f5f9;">'
        f'  <span style="font-size:12px;color:#475569;font-weight:500;">{_sb_user}</span>'
        f'  <span style="font-size:11px;color:#16a34a;font-weight:600;">{_sb_online}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def creatable_selectbox(label, options, key_prefix, format_func=None, default_value=None):
    """
    通用可手动新增的下拉框组件。

    在 options 列表最前面强行加入「[手动添加...]」选项。
    选中后展示文本输入框，允许用户直接输入新值。

    Args:
        label:    下拉框标签文本（如 "选择设备 *"）
        options:  选项值列表，可以是字符串/int/任意对象
        key_prefix: session_state 键前缀（需全局唯一）
        format_func: 可选的显示格式化函数，签名: (option_value) -> str
        default_value: 默认选中的选项值（None 则默认选中「手动添加」）

    Returns:
        (value, is_new)
          - 选中已有选项 → (选项原始值, False)
          - 手动输入新文本 → (新输入字符串, True)
          - 未做有效选择   → (None, False)
    """
    MANUAL_TAG = "[手动添加...]"

    # 显示标签
    if format_func:
        labels = [format_func(o) for o in options]
    else:
        labels = [str(o) for o in options]

    full_labels = [MANUAL_TAG] + labels
    label_to_value = {l: v for l, v in zip(labels, options)}

    select_key = f"{key_prefix}_sb"
    input_key = f"{key_prefix}_inp"

    # session state 初始化
    if input_key not in st.session_state:
        st.session_state[input_key] = ""

    # 确定默认索引：有 default_value 则定位到它，否则从 0（手动添加）开始
    if default_value is not None:
        try:
            default_idx = full_labels.index(
                next(l for l, v in zip(full_labels, [MANUAL_TAG] + options)
                     if v == default_value and l != MANUAL_TAG)
            )
        except (StopIteration, ValueError):
            default_idx = 0
    else:
        default_idx = None

    selected_label = st.selectbox(
        label, full_labels, key=select_key,
        index=default_idx if select_key not in st.session_state else None,
    )

    if selected_label == MANUAL_TAG:
        clean = label.strip().replace("*", "").replace(":", "").strip()
        new_val = st.text_input(
            f"请输入新的{clean}",
            key=input_key,
            placeholder=f"输入{clean}名称",
        )
        if new_val.strip():
            return new_val.strip(), True
        return None, False

    # 选中已有选项 → 清空文本框残留值
    if st.session_state.get(input_key, ""):
        st.session_state[input_key] = ""

    return label_to_value.get(selected_label), False


def creatable_select(label, options, key, default_index=0):
    """
    可创建新选项的下拉框

    如果选中最后一项 '[新增手动输入]'，自动弹出文本框供输入新值。
    返回选中的值（可能是新输入的值）。
    """
    full_options = list(options) + ['[新增手动输入]']

    # 确保 session state 中有默认值
    select_key = f"{key}_select"
    input_key = f"{key}_input"

    if select_key not in st.session_state:
        st.session_state[select_key] = full_options[min(default_index, len(full_options)-1)]
    if input_key not in st.session_state:
        st.session_state[input_key] = ""

    # 渲染下拉框
    selected = st.selectbox(
        label,
        full_options,
        key=select_key,
        index=full_options.index(st.session_state[select_key])
        if st.session_state[select_key] in full_options else 0
    )

    # 如果选了最后一项，显示文本框
    if selected == '[新增手动输入]':
        new_val = st.text_input(f"输入新 {label.split('(')[0].strip()}", key=input_key,
                                placeholder="输入新值后按回车确认")
        return new_val.strip() if new_val.strip() else None

    return selected if selected != '[新增手动输入]' else None


def creatable_multi_select(label, options, key):
    """
    可创建新选项的多选下拉框
    """
    full_options = list(options) + ['[新增手动输入]']
    input_key = f"{key}_input"

    selected = st.multiselect(label, options=full_options, key=key)

    has_manual = '[新增手动输入]' in selected

    result = [s for s in selected if s != '[新增手动输入]']

    if has_manual:
        new_val = st.text_input("输入新选项", key=input_key,
                                placeholder="输入后自动添加")
        if new_val.strip():
            result.append(new_val.strip())

    return result


# ═══════════════════════════════════════════════════════════════
# 全局通用 Excel 导入 / 导出 / 模板下载 组件
# ═══════════════════════════════════════════════════════════════

import io
import pandas as _pd
from datetime import date as _date


def render_import_export_buttons(
    db_conn,
    table_name,
    template_df,
    export_df=None,
    key_prefix="",
    import_handler=None,
    import_file_handler=None,
    import_help_text=None,
):
    """
    全局通用 Excel 导入/导出/模板下载三合一组件。

    在页面顶部或列表上方渲染并排操作区，所有文件流均在内存中处理，
    不在服务器上生成本地临时文件。

    使用方式::

        from database import get_connection
        from pages._utils import render_import_export_buttons

        conn = get_connection()
        template = pd.DataFrame(columns=['col_a', 'col_b', ...])
        render_import_export_buttons(conn, 'table_name', template, key_prefix='my_')

    Args:
        db_conn:      sqlite3.Connection 或 None（None时自动获取）
        table_name:   表名，用于 SQL 查询和导出文件名
        template_df:  pd.DataFrame，**仅含列名**（定义模板表头和导入校验依据）
                      注意：不要包含 id、created_at 等自生成字段
        export_df:    pd.DataFrame（可选），自定义导出数据；传 None 则自动 SELECT *
        key_prefix:   唯一前缀，同一页面多次调用时避免 streamlit key 冲突
        import_handler: callable(import_df, db_conn) -> tuple[int, str] | None
                        可选的自定义导入处理器；为空时走默认 append 导入
        import_file_handler: callable(uploaded_file, db_conn) -> tuple[bool, dict] | None
                        可选的原始文件处理器；适合多 sheet / 非模板文件的自动清洗导入
        import_help_text: 自定义导入区提示文案
    """
    # ── 0. 准备数据 ──
    if export_df is not None:
        data_to_export = export_df
    else:
        try:
            if db_conn is None:
                from database import get_connection
                db_conn = get_connection()
            data_to_export = _pd.read_sql_query(f"SELECT * FROM {table_name}", db_conn)
        except Exception:
            data_to_export = _pd.DataFrame()

    today_str = _date.today().strftime("%Y%m%d")
    template_cols = template_df.columns.tolist()

    # ── 1. 按钮操作行（左侧紧凑操作组：导出与模板紧邻并排，不拉伸）──
    col_export, col_template, col_spacer = st.columns([0.16, 0.18, 0.66])

    with col_export:
        output_buffer = io.BytesIO()
        with _pd.ExcelWriter(output_buffer, engine='openpyxl') as writer:
            data_to_export.to_excel(writer, index=False, sheet_name=table_name[:31])
        output_buffer.seek(0)

        st.download_button(
            label=f"导出 ({len(data_to_export)} 条)",
            data=output_buffer,
            file_name=f"{table_name}_导出数据_{today_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}export_btn",
            width="content",
            icon=":material/download:",
        )

    with col_template:
        template_buffer = io.BytesIO()
        empty_template = _pd.DataFrame(columns=template_cols)
        with _pd.ExcelWriter(template_buffer, engine='openpyxl') as writer:
            empty_template.to_excel(writer, index=False, sheet_name=f"{table_name}_模板"[:31])
        template_buffer.seek(0)

        st.download_button(
            label="下载导入模板",
            data=template_buffer,
            file_name=f"{table_name}_导入模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}template_btn",
            width="content",
            icon=":material/description:",
        )

    # ── 2. 导入区（expander 保持界面整洁）──
    with st.expander("批量导入数据", expanded=False):
        st.caption(import_help_text or "请使用上方「下载导入模板」获取标准格式表格，按模板填写后上传。")
        uploaded_file = st.file_uploader(
            "上传 Excel 文件 (*.xlsx)",
            type=["xlsx"],
            key=f"{key_prefix}import_file",
        )

        if uploaded_file is not None:
            if import_file_handler is not None:
                try:
                    if db_conn is None:
                        from database import get_connection
                        db_conn = get_connection()
                    handled, payload = import_file_handler(uploaded_file, db_conn)
                except Exception as e:
                    st.error(f"自动清洗导入失败：{e}")
                    st.stop()

                if handled:
                    summary = payload or {}
                    preview_df = summary.get("preview_df")
                    if summary.get("message"):
                        st.info(summary["message"])
                    if preview_df is not None and not preview_df.empty:
                        ui_table(preview_df.head(10), width="stretch", hide_index=True)
                    if summary.get("warnings"):
                        for warning in summary["warnings"]:
                            st.warning(warning)
                    if summary.get("success"):
                        st.success(summary.get("success"))
                        st.rerun()
                    st.stop()

            # 2.1 读取
            try:
                import_df = _pd.read_excel(uploaded_file, engine='openpyxl')
            except Exception as e:
                st.error(f"Excel 文件读取失败：{e}")
                st.stop()

            if import_df.empty:
                st.warning("文件为空，请检查后重新上传。")
                st.stop()

            st.info(f"已读取 **{len(import_df)}** 条记录，**{len(import_df.columns)}** 列")
            ui_table(import_df.head(5), width="stretch", hide_index=True)

            # 2.2 列名校验（大小写不敏感）
            expected_lower = [c.lower().strip() for c in template_cols]
            actual_lower   = [c.lower().strip() for c in import_df.columns.tolist()]
            missing = sorted(set(expected_lower) - set(actual_lower))
            extra   = sorted(set(actual_lower)   - set(expected_lower))

            if missing:
                st.error(f"缺少必需列：**{', '.join(missing)}**")
                with st.expander("查看期望列 vs 上传列"):
                    st.markdown(f"**期望列**：`{'`, `'.join(expected_lower)}`")
                    st.markdown(f"**上传列**：`{'`, `'.join(actual_lower)}`")
                st.stop()

            # 2.3 列名映射 + 裁剪多余列
            rename_map = {}
            for tc in template_cols:
                for ac in import_df.columns:
                    if tc.lower().strip() == ac.lower().strip():
                        rename_map[ac] = tc
                        break

            import_df.rename(columns=rename_map, inplace=True)

            # 丢弃模板中不存在的额外列
            if extra:
                st.warning(f"多余列将被忽略：**{', '.join(extra)}**")
                keep_cols = [c for c in import_df.columns if c.lower().strip() in expected_lower]
                import_df = import_df[keep_cols]

            # 补全缺失列（全为 None/空字符串，兼容 NOT NULL）
            for tc in template_cols:
                if tc not in import_df.columns:
                    import_df[tc] = ''

            # 重排列序为模板顺序
            import_df = import_df[template_cols]

            # 2.4 预览最终数据
            st.caption("列名校验通过，预览前 5 行：")
            ui_table(import_df.head(5), width="stretch", hide_index=True)

            # 2.5 确认导入
            col_confirm, col_reset = st.columns([1, 1])
            with col_confirm:
                if st.button("确认导入", type="primary", key=f"{key_prefix}confirm_import",
                             width="stretch"):
                    try:
                        if db_conn is None:
                            from database import get_connection
                            db_conn = get_connection()
                        if import_handler is not None:
                            affected_count, message = import_handler(import_df, db_conn)
                        else:
                            import_df.to_sql(table_name, db_conn, if_exists='append', index=False)
                            db_conn.commit()
                            affected_count, message = len(import_df), f"成功导入 {len(import_df)} 条记录"

                        st.success(f"{message}！页面即将刷新…")
                        st.rerun()
                    except Exception as e:
                        st.error(f"数据库写入失败：{e}")
                        if db_conn is not None:
                            db_conn.rollback()
            with col_reset:
                if st.button("重新选择文件", key=f"{key_prefix}reset_import",
                             width="stretch"):
                    st.rerun()


# ═══════════════════════════════════════════════════════════════
# 全局通用可编辑表格 + 导入导出 一体化组件
# 基于 st.data_editor，支持增删改 + SQLite 联动
# ═══════════════════════════════════════════════════════════════

def render_editable_table(df, table_name, db_conn, key_prefix,
                          disabled_cols=None, hidden_cols=None,
                          column_config_overrides=None,
                          column_name_map=None,
                          page_size=15, primary_key='id'):
    """
    通用可编辑表格组件 (基于 st.data_editor)，增删改自动联动 SQLite。

    - 双击编辑单元格 → 自动 UPDATE
    - 勾选行按 Delete 键删除 → 确认后 DELETE
    - num_rows="dynamic" 允许在表格底部新增空行 → 填写后自动 INSERT
    - disabled_cols 保护关键只读字段 (如 状态、ID、审核人)
    - hidden_cols 隐藏内部列 (如 id)

    使用方式::

        from database import get_connection, get_equipment
        from pages._utils import render_editable_table

        conn = get_connection()
        df = _pd.DataFrame(get_equipment())
        render_editable_table(df, 'equipment', conn, 'eq_',
                              disabled_cols=['id', 'status'])

    Args:
        df:            pd.DataFrame —— 要展示的数据
        table_name:    str —— SQLite 表名
        db_conn:       sqlite3.Connection 或 None（为None时自动获取）
        key_prefix:    str —— session_state key 前缀
        disabled_cols: list[str] —— 禁止编辑的列名
        hidden_cols:   list[str] —— 完全隐藏的列名
        column_config_overrides: dict —— 额外 column_config 覆盖
        column_name_map: dict[str, str] | None —— 显示列名 → DB列名 的映射。
                          用于处理显示列名与数据库列名不一致的场景
                          (如 'category_name' → 'category_id')。
                          未在映射中的列名保持原样。
        page_size:     int —— 每页行数
        primary_key:   str —— 主键列名
    """
    import pandas as pd

    if disabled_cols is None:
        disabled_cols = []
    if hidden_cols is None:
        hidden_cols = []
    if column_config_overrides is None:
        column_config_overrides = {}
    if column_name_map is None:
        column_name_map = {}
    if db_conn is None:
        from database import get_connection
        db_conn = get_connection()

    # 工具函数：将显示列名映射为 DB 列名
    def _to_db_col(display_col):
        return column_name_map.get(display_col, display_col)

    # 获取数据库中实际存在的列名（用于 INSERT 时过滤不存在的列）
    db_col_names = set()
    try:
        table_info = db_conn.execute(f'PRAGMA table_info({table_name})').fetchall()
        db_col_names = {row[1] for row in table_info}
    except Exception:
        db_col_names = set(df.columns)  # 回退：使用 DataFrame 的列名

    # ── 分页状态 ──
    page_key = f"{key_prefix}_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)

    # ── 构建 column_config ──
    col_config = {}

    def _infer_column_type(series):
        """根据 pandas dtype 推断合适的 Streamlit column_config 类型"""
        dtype = series.dtype
        if pd.api.types.is_integer_dtype(dtype):
            return st.column_config.NumberColumn
        elif pd.api.types.is_float_dtype(dtype):
            return st.column_config.NumberColumn
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            return st.column_config.DatetimeColumn
        elif pd.api.types.is_bool_dtype(dtype):
            return st.column_config.CheckboxColumn
        else:
            # 检查是否看似日期字符串
            try:
                non_null = series.dropna()
                if len(non_null) > 0:
                    sample = non_null.iloc[0]
                    if isinstance(sample, str) and (len(sample) in (10, 19)) and (
                            sample.count('-') == 2):
                        return st.column_config.TextColumn  # 字符串日期保持 TextColumn
            except Exception:
                pass
            return st.column_config.TextColumn

    for col in df.columns:
        config_class = _infer_column_type(df[col])

        if col in hidden_cols:
            col_config[col] = st.column_config.Column(label=col, disabled=True)
            continue

        if col in disabled_cols:
            col_config[col] = config_class(label=col, disabled=True)
        elif col in column_config_overrides:
            col_config[col] = column_config_overrides[col]
        else:
            col_config[col] = config_class(label=col)

    # ── 过滤出展示用的列 ──
    display_cols = [c for c in df.columns if c not in hidden_cols]

    # ── 分页切片 ──
    start = st.session_state[page_key] * page_size
    end = min(start + page_size, total_rows)
    page_df = df.iloc[start:end].copy()

    # 展示分页信息
    if total_pages > 1:
        plc, prc = st.columns([2, 1])
        with plc:
            st.caption(f"第 {st.session_state[page_key] + 1}/{total_pages} 页 (共 {total_rows} 条)")
        with prc:
            pg_col1, pg_col2, pg_col3 = st.columns([1, 1, 1])
            with pg_col1:
                if st.button("上一页", key=f"{key_prefix}prev", disabled=st.session_state[page_key] == 0,
                             width="stretch"):
                    st.session_state[page_key] = max(0, st.session_state[page_key] - 1)
                    st.rerun()
            with pg_col2:
                page_input = st.number_input("页码", min_value=1, max_value=total_pages,
                                             value=st.session_state[page_key] + 1,
                                             key=f"{key_prefix}page_num", label_visibility="collapsed")
                if page_input != st.session_state[page_key] + 1:
                    st.session_state[page_key] = page_input - 1
                    st.rerun()
            with pg_col3:
                if st.button("下一页", key=f"{key_prefix}next",
                             disabled=st.session_state[page_key] >= total_pages - 1,
                             width="stretch"):
                    st.session_state[page_key] = min(total_pages - 1, st.session_state[page_key] + 1)
                    st.rerun()
    else:
        st.caption(f"共 {total_rows} 条记录")

    # ── 渲染 st.data_editor ──
    editor_key = f"{key_prefix}editor"
    edited = ui_data_editor(
        page_df[display_cols] if hidden_cols else page_df,
        key=editor_key,
        width="stretch",
        num_rows="dynamic",
        column_config=col_config,
        hide_index=True,
        height=min(page_size * 38 + 38, 600),
    )

    # ── 操作按钮行 ──
    oc1, oc2, oc3 = st.columns([1, 1, 1])

    with oc1:
        if st.button("保存修改", key=f"{key_prefix}save", width="stretch", type="primary"):
            session_data = st.session_state.get(editor_key, {})
            edited_rows = session_data.get("edited_rows", {})
            deleted_rows = session_data.get("deleted_rows", [])
            added_rows = session_data.get("added_rows", [])

            changes_made = False

            with st.spinner("正在同步到数据库..."):
                # ── 处理编辑行 ──
                if edited_rows:
                    try:
                        for row_idx_str, edits in edited_rows.items():
                            row_idx = int(row_idx_str)
                            actual_idx = start + row_idx
                            if actual_idx >= total_rows:
                                continue
                            pk_val = df.iloc[actual_idx][primary_key]
                            if not edits:
                                continue
                            # 映射显示列名 → DB 列名，并过滤掉不存在的 DB 列
                            db_edits = {}
                            for display_col, val in edits.items():
                                db_col = _to_db_col(display_col)
                                if db_col and db_col in db_col_names:
                                    db_edits[db_col] = val
                            if not db_edits:
                                continue
                            set_clause = ",".join([f'"{c}" = ?' for c in db_edits.keys()])
                            values = list(db_edits.values()) + [pk_val]
                            db_conn.execute(
                                f'UPDATE {table_name} SET {set_clause} WHERE {primary_key} = ?',
                                values
                            )
                        db_conn.commit()
                        changes_made = True
                        st.toast(f"已更新 {len(edited_rows)} 处修改")
                    except Exception as e:
                        st.error(f"保存修改失败: {e}")
                        db_conn.rollback()

                # ── 处理新增行 ──
                if added_rows:
                    try:
                        for added in added_rows:
                            if not added or all(v == '' or v is None for v in added.values()):
                                continue
                            # 映射显示列名 → DB 列名，并过滤掉不存在的 DB 列
                            db_added = {}
                            for display_col, val in added.items():
                                db_col = _to_db_col(display_col)
                                # 只保留真正的 DB 列（且值非空字符串可用于 INSERT）
                                if db_col and db_col in db_col_names:
                                    db_added[db_col] = val
                            if not db_added:
                                continue
                            cols = list(db_added.keys())
                            vals = list(db_added.values())
                            placeholders = ",".join(["?"] * len(cols))
                            col_names = ",".join([f'"{c}"' for c in cols])
                            db_conn.execute(
                                f'INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})',
                                vals
                            )
                        db_conn.commit()
                        changes_made = True
                        st.toast(f"已新增 {len(added_rows)} 条记录")
                    except Exception as e:
                        st.error(f"添加记录失败: {e}")
                        db_conn.rollback()

                # ── 处理删除行 ──
                if deleted_rows:
                    try:
                        for row_idx in sorted(deleted_rows, reverse=True):
                            actual_idx = start + row_idx
                            if actual_idx >= total_rows:
                                continue
                            pk_val = df.iloc[actual_idx][primary_key]
                            db_conn.execute(
                                f'DELETE FROM {table_name} WHERE {primary_key} = ?',
                                (pk_val,)
                            )
                        db_conn.commit()
                        changes_made = True
                        st.toast(f"已删除 {len(deleted_rows)} 条记录")
                    except Exception as e:
                        st.error(f"删除记录失败: {e}")
                        db_conn.rollback()

            if changes_made:
                st.session_state[page_key] = 0
                st.rerun()
            elif not edited_rows and not added_rows and not deleted_rows:
                st.info("没有检测到任何修改。请在表格中编辑、新增或删除数据后再保存。")

    with oc2:
        if st.button("刷新数据", key=f"{key_prefix}refresh", width="stretch"):
            st.session_state[page_key] = 0
            st.rerun()

    with oc3:
        st.caption("双击单元格编辑 | 勾选行 + Delete 删除 | 底部空行新增")


# ═══════════════════════════════════════════════════════════════
# 一体化组件：导入导出 + 可编辑表格 (一键渲染)
# ═══════════════════════════════════════════════════════════════

def render_data_section(df, table_name, db_conn, template_df, key_prefix,
                        disabled_cols=None, hidden_cols=None,
                        column_config_overrides=None,
                        column_name_map=None,
                        export_df=None, page_size=15, primary_key='id',
                        allow_import_export=True, allow_edit=True):
    """
    一体化数据管理区：导入导出按钮 + 可编辑表格。

    自动渲染完整的导入/导出/编辑/删除功能，一个函数搞定整个数据管理区。

    使用方式::

        from database import get_connection, get_equipment
        from pages._utils import render_data_section

        conn = get_connection()
        df = pd.DataFrame(get_equipment())
        template = pd.DataFrame(columns=['name', 'model', 'serial_number', ...])
        render_data_section(df, 'equipment_list', conn, template, 'eq_',
                            disabled_cols=['id', 'status'],
                            hidden_cols=['id'])

    Args:
        df, table_name, db_conn, key_prefix,
        disabled_cols, hidden_cols, column_config_overrides,
        export_df, page_size, primary_key → 同 render_editable_table
        template_df: pd.DataFrame —— 导入模板结构
        allow_import_export: bool —— 是否显示导入导出按钮
        allow_edit: bool —— 是否显示编辑功能（仅浏览模式为False）
    """
    if allow_import_export:
        render_import_export_buttons(db_conn, table_name, template_df,
                                     export_df=export_df, key_prefix=key_prefix)

    if allow_edit:
        render_editable_table(df, table_name, db_conn, key_prefix,
                              disabled_cols=disabled_cols,
                              hidden_cols=hidden_cols,
                              column_config_overrides=column_config_overrides,
                              column_name_map=column_name_map,
                              page_size=page_size, primary_key=primary_key)
    else:
        # 只读模式：简单的 st.dataframe
        if hidden_cols:
            display = df[[c for c in df.columns if c not in hidden_cols]]
        else:
            display = df
        ui_table(display, width="stretch", hide_index=True,
                     height=min(page_size * 38 + 38, 600))


# ═══════════════════════════════════════════════════════════════
# 顶部栏（Redesign）：当前页标题 + 全局搜索(Ctrl+K) + 通知 + 用户菜单
# 纯前端 shell，不读写任何业务数据；退出登录经 ?logout=1 接回 main.py
# ═══════════════════════════════════════════════════════════════

# 页面脚本路径 → 中文名 / 导航 URL（与 st.Page 默认 url_path 对应）
_PAGE_INFO = {
    "pages/page_workbench.py": ("品质工作台", "/page_workbench"),
    "pages/page_usage.py": ("使用登记", "/page_usage"),
    "pages/page_borrow.py": ("借用归还", "/page_borrow"),
    "pages/page_equipment.py": ("设备台账", "/page_equipment"),
    "pages/page_maintenance.py": ("维护记录", "/page_maintenance"),
    "pages/page_reports.py": ("检验报告", "/page_reports"),
    "pages/page_samples.py": ("样品管理", "/page_samples"),
    "pages/page_changes.py": ("变更管理", "/page_changes"),
    "pages/page_dashboard.py": ("数据看板", "/page_dashboard"),
    "pages/page_changelog.py": ("版本日志", "/page_changelog"),
    "pages/page_about.py": ("关于系统", "/page_about"),
    "pages/page_monitor.py": ("系统监控", "/page_monitor"),
    "pages/page_audit.py": ("操作审计", "/page_audit"),
    "pages/page_recycle.py": ("误删找回", "/page_recycle"),
}


def _current_page_id():
    """返回当前页面脚本名，用作 widget key 后缀。

    用于避免在 st.navigation 页面切换瞬间新旧两页同跑导致的
    'multiple elements with the same key' 错误（如 sidebar_logout_bottom 重复）。
    """
    try:
        from streamlit.runtime.scriptrunner.script_run_context import get_script_run_ctx
        _ctx = get_script_run_ctx()
        return (_ctx.page_script_name if _ctx else "") or "app"
    except Exception:
        return "app"


_PAGE_SEARCH_ALIASES = {
    "首页": "首页展示总览",
    "工作台": "首页展示总览",
    "品质工作台": "首页展示总览",
    "报告": "检验报告",
    "报告管理": "检验报告",
    "在线报告": "检验报告",
    "验货报告": "检验报告",
    "qc报告": "检验报告",
    "样品": "样品管理",
    "设备": "设备台账",
    "台账": "设备台账",
    "借用": "借用归还",
    "归还": "借用归还",
    "维护": "维护记录",
    "变更": "变更管理",
    "驻厂": "驻厂登记",
    "看板": "数据看板",
    "数据": "数据看板",
    "监控": "系统监控",
    "审计": "操作审计",
    "回收站": "误删找回",
    "找回": "误删找回",
}


def _match_page(query):
    """按页面名称和常用别名匹配，返回页面脚本路径或 ``None``。

    这是导航跳转搜索，不查询报告、样品或设备的业务数据；调用方必须在
    无匹配时明确提示，避免用户误以为搜索无反应。
    """
    q = (query or "").strip().lower()
    if not q:
        return None
    _flat = []
    for _item in NAV_ITEMS:
        _label, _icon, _third, *_flags = _item
        if isinstance(_third, list):
            for _child in _third:
                _cl, _ci, _cp, *_cf = _child
                _flat.append((_cl, _cp))
        else:
            _flat.append((_label, _third))

    _label_to_path = {_label.lower(): _path for _label, _path in _flat}
    _alias = _PAGE_SEARCH_ALIASES.get(q)
    if _alias:
        return _label_to_path.get(_alias.lower())
    if q in _label_to_path:
        return _label_to_path[q]
    for _label, _path in _flat:
        if q in _label.lower():
            return _path
    return None


def render_topbar(page_title=None):
    """主区域顶部栏：当前页标题 + 全局搜索(命令面板) + 通知 + 用户菜单。

    改用原生 Streamlit 组件实现（st.switch_page / st.page_link / st.popover / 搜索表单），
    不再依赖 st.html 注入的内联 <script>（Streamlit 1.59 会剥离/沙箱化脚本，
    导致 Ctrl+K / 通知 / 头像交互失效）。纯前端 shell，不读写任何业务数据；
    退出登录经 ?logout=1 接回 main.py 顶层逻辑。
    """

    # 当前页面中文名（调用方传入优先；未传时尝试从 ctx 推断）
    if not page_title:
        try:
            from streamlit.runtime.scriptrunner.script_run_context import get_script_run_ctx
            _ctx = get_script_run_ctx()
            _pname = _ctx.page_script_name if _ctx else ""
            page_title = _PAGE_INFO.get(_pname, ("品质系统", ""))[0]
        except Exception:
            page_title = "品质系统"
    if not page_title:
        page_title = "品质系统"

    _user = (st.session_state.get("user_name") or "").strip()
    if not _user or _user == "用户":
        _user = (st.session_state.get("user_email") or "").split("@")[0]
    _is_admin = bool(st.session_state.get("is_admin", False))
    _is_auth = bool(st.session_state.get("authenticated", False))
    # 未登录时显示友好文案而非 "?"
    if not _user and not _is_auth:
        _user = "(未登录)"
    _initials = (_user[:1] if _user and _user != "(未登录)" else "?").upper()

    try:
        _ins = _cached_inspection_stats()
        _notif = int(_ins.get("pending", 0) or 0)
    except Exception:
        _notif = 0

    # ── 顶部栏布局（原生 Streamlit 组件，不再依赖被 Streamlit 剥离的内联脚本）──
    _pid = _current_page_id()
    # 当 Streamlit 页面切换/冷启动时 page_script_name 可能为空，_current_page_id() 回退为 "app"；
    # 所有页面表单 key 相同，导致切换页面时触发 "multiple identical forms" 冲突。
    # 用 page_title 做二次区分，确保每页 key 唯一（"检验报告" 等标题稳定且唯一）。
    if _pid == "app":
        import re as _re
        _slug = _re.sub(r'[^\w\u4e00-\u9fff]', '', page_title or 'app')
        _pid = f"app_{_slug}"

    # widget key 必须跨 rerun 稳定。此前用递增后缀规避重复组件错误，结果提交表单时
    # 输入框已换成新 key，导致 _go/_q 丢失，搜索和退出都会表现为“点击没反应”。
    # 每个页面仅渲染一次顶部栏；以稳定页面标识隔离不同页面即可。
    _topbar_key = _pid

    _c_brand, _c_search, _c_right = st.columns([3.0, 4.6, 2.6])
    with _c_brand:
        st.markdown(
            f'<span class="qs-tb-brand"><span class="qs-tb-dot"></span>'
            f'<b>品质系统</b>&nbsp;<span class="qs-tb-crumb">/ {page_title}</span></span>',
            unsafe_allow_html=True,
        )
    with _c_search:
        with st.form(f"topbar_search_{_topbar_key}", border=False):
            _q0, _q1 = st.columns([1, 0.16])
            with _q0:
                _q = st.text_input(
                    "搜索页面",
                    placeholder="搜索功能、页面… (Enter 跳转)",
                    label_visibility="collapsed",
                    key=f"topbar_q_{_topbar_key}",
                )
            with _q1:
                _go = st.form_submit_button("🔍", use_container_width=True, help="跳转到匹配页面")
            if _go and _q and _q.strip():
                _target = _match_page(_q.strip())
                if _target:
                    st.switch_page(_target)
                else:
                    st.warning("未找到匹配页面。可搜索：报告、样品、设备、借用、变更、看板、监控等。")
    with _c_right:
        # ── 右侧组件组：通知 | 分隔线 | 用户（三列内联，杜绝 popover 掉出对齐）──
        _role = "管理员" if _is_admin else "用户"
        _role_color = "#16a34a" if _is_admin else "#6366f1"
        _hash_val = sum(ord(c) for c in (_user or "?")) % 360
        _avatar_color = f"hsl({_hash_val}, 65%, 52%)"

        _nc, _sc, _uc = st.columns([1.15, 0.06, 2.2])

        with _nc:
            # ── 通知铃铛（用 st.page_link 做客户端导航，避免 <a> 全页刷新丢失 session）──
            if _notif:
                st.page_link(
                    "pages/page_reports.py",
                    label=f"🔔 {_notif}",
                    icon=":material/notifications:",
                    use_container_width=True,
                )
            else:
                st.page_link(
                    "pages/page_reports.py",
                    label="🔔",
                    icon=":material/notifications_none:",
                    use_container_width=True,
                )

        with _sc:
            # ── 竖分隔线 ──
            st.markdown(
                '<div style="height:24px;width:1px;background:#e2e8f0;'
                'border-radius:1px;margin:auto;"></div>',
                unsafe_allow_html=True,
            )

        with _uc:
            # ── 用户区（popover 作为本列唯一小部件，保证对齐）──
            with st.popover(
                f" {_initials}  **{_user or '?'}** ",
                help=f"{_user}（{_role}）— 点击查看账户",
                use_container_width=True,
            ):
                st.markdown(
                    f'<div style="text-align:center;padding:6px 0 10px;margin-bottom:6px;">'
                    f'<span style="'
                    f'width:52px;height:52px;border-radius:50%;'
                    f'background:{_avatar_color};color:#fff;'
                    f'font-weight:700;font-size:22px;'
                    f'display:inline-flex;align-items:center;justify-content:center;'
                    f'box-shadow:0 2px 6px rgba(0,0,0,.15);'
                    f'">{_initials}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{ _user or '?' }**")
                _role_tag_color = "#16a34a" if _is_admin else "#6366f1"
                _role_tag_bg = "#f0fdf4" if _is_admin else "#eef2ff"
                st.markdown(
                    f'<span style="'
                    f'font-size:12px;color:{_role_tag_color};background:{_role_tag_bg};'
                    f'padding:2px 12px;border-radius:12px;font-weight:500;">'
                    f'{_role}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown("---")
                if st.button("退出登录", key=f"topbar_logout_{_topbar_key}", use_container_width=True):
                    # 双重保险：同时写 session_state 和 query_params（与侧边栏退出逻辑一致）
                    st.session_state["_logged_out"] = True
                    for _lk in [
                        "authenticated", "user_email", "user_name",
                        "user_picture", "is_admin", "oauth_state",
                        "_login_checked", "_last_oauth_code",
                    ]:
                        st.session_state.pop(_lk, None)
                    st.query_params["logout"] = "1"
                    st.rerun()

    # 顶部栏视觉样式（仅轻量外观，不影响交互）
    st.markdown(
        "<style>"
        ".qs-tb-brand{display:inline-flex;align-items:center;gap:8px;font-weight:800;"
        "color:var(--qs-ink);font-size:15px;white-space:nowrap;}"
        ".qs-tb-dot{width:10px;height:10px;border-radius:3px;background:var(--qs-primary);display:inline-block;}"
        ".qs-tb-crumb{color:var(--qs-muted);font-weight:500;font-size:13px;}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="height:1px;background:var(--qs-topbar-border);margin:10px 0 16px;"></div>',
        unsafe_allow_html=True,
    )
