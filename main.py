"""
品质系统管理平台 - 主入口 v2.0.0
Google OAuth 2.0 授权登录 | 本地开发免登录 | Cookie 持久化6天
"""

import streamlit as st
import os
import json
import hashlib
import ipaddress
import secrets
import requests
import time as time_module
from datetime import datetime, timedelta
from config import BASE_DIR, DATA_DIR, get_logo_path, get_optional_analytics_pages, is_admin_email
from database import log_activity, init_db
from pages._utils import apply_ui_system, _TOKENS_CSS

# 可靠读取浏览器 cookie，根治「刷新 / 新标签页后变未登录」问题。
# 旧逻辑依赖 st.context.cookies，在部分 Streamlit 版本 / 部署（新标签页、刷新）下
# 偶发读不到 qs_auth cookie，导致判定未登录。streamlit-cookies-manager 通过前端组件
# 直接读取 document.cookie 并回传，100% 可靠（不依赖 Streamlit 请求头转发）。
# 包未安装时 CookieManager 置 None，init_session 自动退回旧逻辑，保证系统不崩溃。
try:
    from streamlit_cookies_manager import CookieManager
except Exception:  # pragma: no cover - 包缺失兜底
    CookieManager = None

# Logo 路径
LOGO_PATH = get_logo_path()
AUTH_FILE = os.path.join(DATA_DIR, "auth.json")
CLIENT_SECRETS_FILE = os.path.join(DATA_DIR, "client_secret.json")

# Cookie / Token 签名密钥：与 oauth_handler.py 共享，确保服务端 OAuth 回调设置的
# cookie 能被 Streamlit 侧正确解析。优先从环境变量读取；未设置时生成一次性随机密钥。
# 生产环境必须配置 COOKIE_SECRET，否则每次重启服务都会使已有登录 Cookie 失效。
from oauth_handler import _COOKIE_SECRET

# Google OAuth 端点
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# ---- 页面配置 ----
st.set_page_config(
    page_title="品质系统管理平台",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "",
    layout="wide",
    initial_sidebar_state="expanded"
)
apply_ui_system()

# 注入统一设计令牌（assets/tokens.css，单一来源）
st.html(f"<style>{_TOKENS_CSS}</style>")

# 全局兜底：无条件隐藏 Streamlit 原生英文导航（覆盖登录页/换页闪现等瞬态场景）
# 原因：render_sidebar() 仅在 not using_navigation_api 时注入隐藏 CSS，
#       st.navigation 模式下登录态切换/换页瞬间会短暂泄漏英文原生导航。
st.html("<style>[data-testid='stSidebarNav']{display:none !important;}</style>")

# 一次性提醒：生产环境必须配置 COOKIE_SECRET
if not os.environ.get("COOKIE_SECRET") and not st.session_state.get("_cookie_secret_warned"):
    st.session_state["_cookie_secret_warned"] = True
    st.warning("COOKIE_SECRET 环境变量未设置，已使用本次启动自动生成的随机密钥。生产环境请务必配置 COOKIE_SECRET，否则服务重启后登录状态会失效。")

# 禁用 Streamlit C 键 Clear Cache 弹窗（干扰复制操作）
# ===== 跨设备显示一致性与响应式 UI 统一规范 (QS-UI v1.0) =====
# 目标：Mac 本地 / Win 内网 / Win 公网 / 不同浏览器缩放 / Windows DPI(125%) / 不同分辨率
#       下显示一致、布局自适应、不横向溢出、功能不变。
st.html("""
<style>
/* ---- 设计令牌（统一颜色/间距语义，供全站复用） ---- */
/* 设计令牌统一由 assets/tokens.css 注入（单一来源），此处 :root 已移除 */

/* ---- 关键：锁定根字号，杜绝浏览器/系统最小字号与 DPI 缩放导致 rem 组件无规律放大 ---- */
html { font-size: 16px !important; }
.stApp, body { font-size: 14px !important; }

/* 隐藏 Clear Cache 弹窗 */
div[data-testid="stNotification"] { display: none !important; }

/* ===== 统一页面内容宽度与留白（不铺满全屏，左对齐，贴近左侧导航） ===== */
.block-container {
    max-width: 1500px !important;
    padding-left: 1.75rem !important;
    padding-right: 1.75rem !important;
    padding-top: 1.5rem !important;
    margin-left: 0 !important;
    margin-right: auto !important;
    overflow-x: hidden !important;
}
/* 表格类容器允许更宽（1500~1600），用于数据密集页 */
.table-wide { max-width: 1600px !important; margin-left: 0 !important; }

/* ===== 统一字号（标题/卡片/正文/按钮/输入/表格） ===== */
h1 { font-size: 28px !important; font-weight: 700 !important; }
h2 { font-size: 22px !important; font-weight: 700 !important; }
h3 { font-size: 18px !important; font-weight: 600 !important; }
.main .block-container { font-size: 14px !important; }
div[data-testid="stMarkdownContainer"] p,
div[data-testid="stMarkdownContainer"] span { font-size: 14px !important; line-height: 1.6 !important; }
.stCaption, .caption { font-size: 13px !important; }
thead th, tbody td { font-size: 14px !important; }
/* 防止超长无空格字符串（文件路径/邮箱）撑破布局导致横向溢出 */
div[data-testid="stMarkdownContainer"], .stDataFrame, table { overflow-wrap: anywhere; word-break: break-word; }

/* ===== 统一按钮高度 / 字号（不小于 13px）/ 最大宽度（不铺满） ===== */
.stButton > button,
.stDownloadButton > button,
.stLinkButton > button,
.stFormSubmitButton > button {
    height: 38px !important;
    font-size: 14px !important;
    padding-top: 0.25rem !important;
    padding-bottom: 0.25rem !important;
    max-width: 220px !important;
}

/* ===== 统一输入框 / 筛选框尺寸（按业务语义限宽，不再铺满全屏） ===== */
.stTextInput > div > div > input,
.stNumberInput input,
.stDateInput input,
.stSelectbox [data-baseweb="select"],
.stMultiselect [data-baseweb="select"] {
    max-width: 420px !important;
    font-size: 14px !important;
}
.stTextArea textarea { max-width: 1000px !important; font-size: 14px !important; }

/* ===== 统一卡片 / 容器标题 ===== */
[data-testid="stContainer"] h3,
.element-container h3 { font-size: 18px !important; }

/* ===== 响应式指标卡网格：4 → 2 → 1 列自动回流（看板 KPI / 统计卡） ===== */
.metric-grid, .stat-grid {
    display: grid !important;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 16px !important;
    width: 100% !important;
}
.stat-grid { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
.stat-card {
    background: #ffffff;
    border: 1px solid var(--qs-line);
    border-radius: var(--qs-radius);
    padding: 14px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.stat-card .stat-label { font-size: 12px; color: var(--qs-sub); margin-bottom: 4px; }
.stat-card .stat-value { font-size: 24px; font-weight: 700; color: var(--qs-ink); line-height: 1.1; }

/* ===== 窄屏（≤1200px）多列布局自动换行（4列→2列→1列），避免拥挤/溢出 =====
   仅作用于 ≥3 列的 Streamlit 行（KPI/图表/筛选），不影响两列并排表单的桌面布局 */
@media (max-width: 1200px) {
    div[data-testid="stColumns"]:has(> div[data-testid="stColumn"]:nth-child(3)) {
        flex-wrap: wrap !important;
    }
    div[data-testid="stColumns"]:has(> div[data-testid="stColumn"]:nth-child(3)) > div[data-testid="stColumn"] {
        flex: 1 1 260px !important;
        min-width: 260px !important;
    }
}
/* 极窄屏（≤760px）所有多列行强制单列，保证手机/小窗可读 */
@media (max-width: 760px) {
    div[data-testid="stColumns"] { flex-wrap: wrap !important; }
    div[data-testid="stColumns"] > div[data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
}

</style>
<script>
(function() {
    function blockClearCache() {
        document.querySelectorAll('[data-testid="stNotification"]').forEach(el => el.remove());
        document.querySelectorAll('div').forEach(el => {
            if (el.innerText && el.innerText.includes('Clear caches')) el.remove();
        });
    }
    /* 全局按钮色彩语义：绿=通过/成功，红=驳回/删除/不可逆，橙=替换/维护，
       蓝=查看/上传/保存/提交/同步/NAS，白底描边=下载/返回/取消/检测/次要 */
    function fixButtonColors() {
        var rules = [
            { re: /(确认驳回|驳回|删除|永久删除|清空|取消发布|撤销|恢复出厂)/, bg:'#dc2626', bd:'#dc2626', fg:'#ffffff' },
            { re: /(审核通过|确认通过|通过审核|同意|启用|归档通过)/, bg:'#16a34a', bd:'#16a34a', fg:'#ffffff' },
            { re: /(替换|重新上传|维护|报修|修复)/, bg:'#ea580c', bd:'#ea580c', fg:'#ffffff' },
            { re: /(下载|返回|取消|关闭|退出|检测|重置筛选)/, bg:'#ffffff', bd:'#cbd5e1', fg:'#334155' },
            { re: /(查看|新窗口|NAS|上传|保存|提交|同步|导入|导出|生成|刷新|登录)/, bg:'#2563eb', bd:'#2563eb', fg:'#ffffff' }
        ];
        document.querySelectorAll('button').forEach(function(btn){
            var t = (btn.innerText||'').trim();
            if (!t) return;
            for (var i=0;i<rules.length;i++){
                if (rules[i].re.test(t)) {
                    btn.style.setProperty('background-color', rules[i].bg, 'important');
                    btn.style.setProperty('border-color', rules[i].bd, 'important');
                    btn.style.setProperty('color', rules[i].fg, 'important');
                    break;
                }
            }
        });
    }
    /* 替换 Streamlit 默认英文 UI 文案为中文本地化 */
    function fixStreamlitTexts() {
        document.querySelectorAll('[data-testid="stSelectboxPlaceholder"]').forEach(function(el){
            if (el.innerText && el.innerText.indexOf('Choose an option') !== -1) el.innerText = '请选择';
        });
        document.querySelectorAll('button').forEach(function(b){
            if (b.innerText && b.innerText.trim() === 'Browse files') b.innerText = '选择文件';
        });
        document.querySelectorAll('[data-testid="stFileUploaderDropzone"]').forEach(function(el){
            if (el.innerText && el.innerText.indexOf('Drag and drop file here') !== -1)
                el.innerText = el.innerText.split('Drag and drop file here').join('拖拽文件到此处');
        });
    }
    function redirectDingTalkToCaptureHub() {
        try {
            var ua = navigator.userAgent || '';
            var isDingTalk = /DingTalk/i.test(ua);
            var p = window.location.pathname || '/';
            if (!isDingTalk) return;
            if (p === '/' || p === '/app' || p === '/main' || p === '/index.html') {
                window.location.replace('/reports');
            }
        } catch (e) {}
    }
    document.addEventListener('keydown', function(e) {
        if (e.key === 'c' && !e.ctrlKey && !e.metaKey) {
            e.stopImmediatePropagation();
            e.preventDefault();
            return false;
        }
    }, true);
    setInterval(function(){ blockClearCache(); fixButtonColors(); fixStreamlitTexts(); redirectDingTalkToCaptureHub(); }, 500);

    setTimeout(redirectDingTalkToCaptureHub, 200);
})();
</script>
""")


# ---- 工具函数 ----
def get_redirect_uri():
    """
    自动检测 redirect_uri。
    优先级：环境变量 > PUBLIC_BASE_URL > 请求头检测 > localhost 默认
    """
    # 1. 环境变量（优先级最高）
    env_uri = os.environ.get("OAUTH_REDIRECT_URI")
    if env_uri:
        return env_uri

    # 1.5. 固定公网基础地址（适用于隧道/反向代理）
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base_url:
        return public_base_url

    # 2. 从请求头检测（处理隧道/反向代理场景）
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers:
            host = headers.get("X-Forwarded-Host", "")
            if not host:
                host = headers.get("Host", "")
            proto = headers.get("X-Forwarded-Proto", "https")
            if host and "localhost" not in host and "127.0.0.1" not in host:
                return f"{proto}://{host}"
    except Exception:
        pass

    return "http://localhost:8501"


def load_auth_config():
    """加载授权配置"""
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"authorized_emails": [], "admin_emails": [], "allow_all_google": False}


def is_authorized(email):
    """检查邮箱是否被授权：管理员 > 白名单 > 域名匹配 > 全局允许"""
    config = load_auth_config()
    email_lower = email.lower()

    if email_lower in [e.lower() for e in config.get("admin_emails", [])]:
        return True

    if email_lower in [e.lower() for e in config.get("authorized_emails", [])]:
        return True

    allowed = os.environ.get("ALLOWED_DOMAINS", "")
    allowed += "," + ",".join(config.get("allowed_domains", []))
    allowed_domains = [d.strip() for d in allowed.split(",") if d.strip()]
    for domain in allowed_domains:
        if email_lower.endswith("@" + domain):
            return True

    if config.get("allow_all_google", False):
        return True

    return False


def is_admin(email):
    """检查是否为管理员"""
    config = load_auth_config()
    return email.lower() in [e.lower() for e in config.get("admin_emails", [])]


def save_auth_config(config):
    """保存授权配置"""
    os.makedirs(DATA_DIR, exist_ok=True)
    config["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_client_secrets():
    """加载 Google OAuth 客户端密钥"""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return None
    with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_oauth_config():
    """
    获取 OAuth 配置。
    公网/生产环境: 从环境变量读取
    本地开发: 从文件读取（client_secret.json）
    """
    # 1. 优先：环境变量
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}

    # 2. 文件（本地开发）
    secrets = load_client_secrets()
    if secrets:
        web = secrets.get("web", secrets.get("installed", {}))
        return {
            "client_id": web.get("client_id", ""),
            "client_secret": web.get("client_secret", ""),
        }
    return None


def init_session():
    """初始化会话状态（包含 cookie 检测和本地免登录）"""
    defaults = {
        "authenticated": False,
        "user_email": "",
        "user_name": "",
        "user_picture": "",
        "is_admin": False,
        "oauth_state": "",
        "_login_checked": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # OAuth callback has already set a fresh server-side qs_auth cookie.  A
    # previous manual logout may still exist in this Streamlit session; clear
    # that in-memory marker before any logout/cookie gate can erase the new
    # authenticated session again.
    if st.query_params.get("oauth_login") == "1":
        st.session_state.pop("_logged_out", None)
        # 不要用 st.query_params.pop() 清除该参数：它会触发一次 Streamlit
        # 重跑，恰好可能发生在 CookieManager 尚未读取到服务端刚写入的 qs_auth
        # cookie 时，造成「Google 已授权但又回到登录页」。直接在浏览器端完成
        # 清理，不中断当前这次恢复登录的脚本执行。
        st.html("""
        <script>
        document.cookie = "qs_logged_out=; max-age=0; path=/; SameSite=Lax";
        window.history.replaceState({}, document.title, window.location.pathname);
        </script>
        """, unsafe_allow_javascript=True)

    # 已退出标志（logout 处理器设置 _logged_out=True）：一旦退出，跳过一切会话恢复
    # （cookie / or_tk），强制保持未登录，直到用户主动重新登录。该标志持久于
    # session_state，刷新 / 重跑均生效，彻底解决「CookieManager 前端缓存旧 qs_auth
    # 导致退出后仍自动恢复登录」的问题（单纯清 cookie 因前端组件 state 缓存而无效）。
    _logged_out = bool(st.session_state.get("_logged_out", False))
    if _logged_out:
        st.session_state.authenticated = False
        st.session_state.user_email = ""
        st.session_state.user_name = ""
        st.session_state.user_picture = ""
        st.session_state.is_admin = False
        # 写入「已注销」持久标记 + 清除 auth cookie（用 st.html 直接操作 document.cookie）。
        # 必须放在此处（init_session 正常脚本流，不在 st.rerun 紧跟），浏览器才会真正执行
        # JS——若放在 logout 处理器紧跟 st.rerun()，st.rerun 会丢弃 st.html 导致其不执行，
        # 表现为退出后 cookie 纹丝不动、qs_auth 残留、刷新又自动登录。
        # qs_logged_out 跨刷新 / 重开浏览器均生效；init_session 恢复前读它并拒绝恢复。
        st.html("""
        <script>
        document.cookie = "qs_auth=; max-age=0; path=/";
        document.cookie = "qs_logged_out=1; max-age=2592000; path=/; SameSite=Lax";
        </script>
        """, unsafe_allow_javascript=True)
        # 清除登录表单残留值（显式 key），避免退出后表单预填旧邮箱/密码导致免密直入
        for _fk in ("lan_email", "lan_password"):
            st.session_state.pop(_fk, None)
        if not st.session_state.get("network_zone") or st.session_state.get("network_zone") == "未知":
            _capture_client_info()
        # 注意：不 return，继续往下渲染登录页；但后续 cookie / or_tk 恢复均被 _logged_out 拦截

    # 如果已经认证且身份字段完整，直接返回
    if st.session_state.authenticated:
        _nm = (st.session_state.get("user_name") or "").strip()
        _em = (st.session_state.get("user_email") or "").strip()
        if (_nm and _nm != "用户") or _em:
            return
        # 已认证但身份字段缺失（如重启后首跑、session 中只残留了
        # authenticated 标记而姓名/邮箱未回写）→ 不提前 return，继续往下走
        # cookie / token / 侧边栏兜底恢复，把身份重新填回，避免「显示未登录
        # 却能进系统」的脱节。若最终仍恢复不到身份，文末会强制视为未登录。

    # 可靠恢复登录态（根治「刷新 / 新标签页后变未登录」）：
    # 用 streamlit-cookies-manager 通过前端组件读取 document.cookie，取代偶发的
    # st.context.cookies。组件首次加载前 ready() 为 False，此时跳过等待而非 st.stop()
    # （避免退出/首屏出现白屏），由组件自然回传触发下次重跑时再读。
    # 包不可用时退回旧逻辑保证系统可运行。
    cookie_mgr = None
    if CookieManager is not None:
        try:
            # 复用已加载（ready）的 CookieManager 实例：每次 new 一个实例首次 ready()
            # 为 False（组件尚未回传），会导致写入/删除操作被跳过。复用 session_state
            # 中已回传过的实例可保证 ready，从而使退出时写 qs_logged_out / 删 qs_auth 可靠。
            cookie_mgr = st.session_state.get("_cookie_mgr") or CookieManager()
            st.session_state["_cookie_mgr"] = cookie_mgr
        except Exception:
            cookie_mgr = None
    if not _logged_out:
        if cookie_mgr is not None and cookie_mgr.ready():
            # 已注销标记（用户点「退出」时写入的持久 cookie）：跨刷新 / 重开浏览器均生效，
            # 确保退出后不会因 CookieManager 读回 qs_auth 而自动恢复登录（单纯依赖
            # session_state._logged_out 会在页面 reload 后随 session 重建而丢失，导致
            # 退出后刷新又自动登录——这正是反复出 bug 的根因）。检测到该标记则清掉
            # auth cookie 并保持未登录，继续渲染登录页。
            # CookieManager can briefly retain a deleted qs_logged_out value
            # after OAuth redirects.  Treat it as authoritative only when the
            # current request cookie still carries the marker.
            try:
                _request_logout_marker = bool(st.context.cookies.get("qs_logged_out", ""))
            except Exception:
                _request_logout_marker = True
            if "qs_logged_out" in cookie_mgr and _request_logout_marker:
                try:
                    if "qs_auth" in cookie_mgr:
                        del cookie_mgr["qs_auth"]
                        cookie_mgr.save()
                except Exception:
                    pass
                # 不恢复登录（authenticated 保持 False）
            elif "qs_logged_out" in cookie_mgr:
                try:
                    del cookie_mgr["qs_logged_out"]
                    cookie_mgr.save()
                except Exception:
                    pass
                _try_cookie_login(cookie_mgr)
            else:
                _try_cookie_login(cookie_mgr)
        elif cookie_mgr is not None:
            # 【关键修复】CookieManager 存在但 iframe 尚未 ready（首次加载/刷新时常见）：
            # 不再静默跳过！退回 st.context.cookies 直接读 document.cookie，
            # 保证刷新后首屏就能恢复登录态，不再出现 "???" / "(未登录)"。
            _try_cookie_login()
        elif cookie_mgr is None:
            # 兜底：包不可用，退回旧逻辑
            _try_cookie_login()
    # 注：cookie_mgr 存在但 not ready 时，不读也不 stop，由组件回调自然触发下次重跑

    # 兜底①：新标签页场景。在「检验报告」列表点「编辑」会以 <a target="_blank">
    # 开新标签页；部分部署 / Streamlit 版本下新标签页首屏 st.context.cookies 读不到 qs_auth
    # cookie，导致此处判定未登录、直接渲染登录页（即「新建报告→点编辑→跳登录」）。
    # 编辑器链接本身携带已签名的 or_tk 查询参数，用它在新标签页可靠恢复登录态，
    # 不再依赖浏览器 cookie。
    if not _logged_out and not st.session_state.get("authenticated"):
        _try_query_token_login()

    # 兜底强化（彻底修复「刷新后变用户 / 影响编辑权限」）：
    # 若上面的会话恢复未能写回真名（如 st.context.cookies 偶发异常、token 解析异常），
    # 在页面主体与权限判断（编辑/所有者/数据隔离）执行之前，再直读 cookie 恢复一次。
    # 保证 st.session_state.user_name 在任何权限逻辑读取前已是真实姓名，而非空值或「用户」。
    _user_name_now = (st.session_state.get("user_name") or "").strip()
    if not _user_name_now or _user_name_now == "用户":
        try:
            from pages._utils import _recover_user_name_from_sidebar
            _recover_user_name_from_sidebar()
        except Exception as _e:
            import sys as _sys
            print(f"[AUTH] init_session 兜底恢复失败: {type(_e).__name__}: {str(_e)[:200]}",
                  file=_sys.stderr)

    # All QMS entry points require an authenticated identity.  Local development
    # is not an exception: it uses the same login gate as LAN and public access.
    if is_streamlit_cloud():
        # Streamlit Cloud 平台已处理认证，直接信任
        _streamlit_cloud_login()

    # 探测访问来源网络（内网 / 外网），供操作审计日志使用
    if not st.session_state.get("network_zone") or st.session_state.get("network_zone") == "未知":
        _capture_client_info()

    # 一致性收口（安全约束）：authenticated 为 True 但身份字段仍缺失时，
    # 先尝试最后一次补齐（查库/cookie），确实补不回才强制视为未登录。
    # 修改前：缺字段直接踢出 → 导致 CookieManager 时序问题放大为「刷新即掉登录」。
    if st.session_state.get("authenticated"):
        _nm = (st.session_state.get("user_name") or "").strip()
        _em = (st.session_state.get("user_email") or "").strip()
        if (not _nm or _nm == "用户") and not _em:
            # 真的什么都没有 → 强制未登录
            st.session_state.authenticated = False
            st.session_state.user_name = ""
            st.session_state.user_email = ""
            st.session_state.is_admin = False
        elif not _nm or _nm == "用户":
            # 有邮箱但缺姓名（token 可能是旧格式）→ 最后一次尝试补齐
            _lookup = _lookup_display_name(_em) if _em else ""
            if _lookup:
                st.session_state.user_name = _lookup
            elif _em:
                # 兜底：至少用邮箱前缀，不再显示 "???"
                st.session_state.user_name = _em.split("@")[0]


def _try_cookie_login(cookie_mgr=None):
    """从浏览器 cookie 恢复登录会话（6天有效期），携带用户姓名

    根治方案：优先用 streamlit-cookies-manager 可靠读取 document.cookie，
    取代偶发的 st.context.cookies（新标签页 / 刷新场景下后者会读不到）。
    cookie_mgr 为 None 时退回旧逻辑（st.context.cookies）。
    """
    try:
        if cookie_mgr is not None:
            auth_token = cookie_mgr.get("qs_auth", "")
        else:
            cookies = st.context.cookies
            auth_token = cookies.get("qs_auth", "")
        if auth_token:
            email, exp_ts, name = _decode_auth_token(auth_token)
            if email and exp_ts and time_module.time() < exp_ts:
                st.session_state.authenticated = True
                st.session_state.user_email = email
                # 优先用 cookie 携带的真名；旧格式 cookie 无名则尝试查库映射
                if name and name.strip():
                    st.session_state.user_name = name.strip()
                else:
                    # 旧 cookie 兜底：从 quality_users 表查显示名
                    display = _lookup_display_name(email)
                    st.session_state.user_name = display or email.split("@")[0]
                st.session_state.is_admin = is_admin(email)
                return
    except Exception as e:
        # 不再完全静默：记录到控制台以便排查（生产环境查看 Streamlit 日志）
        import sys as _sys
        print(f"[AUTH] _try_cookie_login 失败: {type(e).__name__}: {str(e)[:200]}",
              file=_sys.stderr)



def _try_query_token_login():
    """从编辑器深链携带的 or_tk 查询参数恢复登录态。

    解决：在「检验报告」列表点击「编辑」会以 <a target="_blank"> 开新标签页，
    部分部署 / Streamlit 版本下新标签页首屏 st.context.cookies 读不到 qs_auth cookie，
    导致 init_session 判定未登录、直接渲染登录页。
    我们的编辑器链接自身携带已签名的 or_tk（token 含 email|exp|name|sig，6 天过期），
    故用它在新标签页可靠恢复登录态，彻底解决「新建报告→点编辑→跳登录界面」。
    """
    try:
        tk = st.query_params.get("or_tk", "")
        if not tk:
            return
        email, exp_ts, name = _decode_auth_token(tk)
        if email and exp_ts and time_module.time() < exp_ts:
            st.session_state.authenticated = True
            st.session_state.user_email = email
            st.session_state.user_name = (name.strip() if name and name.strip() else email.split("@")[0])
            st.session_state.is_admin = is_admin(email)
            # 把 token 写回本标签页 cookie，避免该标签页后续任何操作再次丢失登录态
            try:
                _set_auth_cookie(email, name.strip() if name and name.strip() else "")
            except Exception:
                pass
            # 用完即焚：从 URL 移除 token，避免遗留在浏览器历史记录
            try:
                st.query_params.pop("or_tk", None)
            except Exception:
                pass
    except Exception as e:
        import sys as _sys
        print(f"[AUTH] _try_query_token_login 失败: {type(e).__name__}: {str(e)[:200]}",
              file=_sys.stderr)


def _lookup_display_name(email):
    """根据邮箱查找中文显示名（从 quality_users 名单：格式 '邮箱前缀+姓名'）"""
    try:
        from database import get_quality_users_list
        users = get_quality_users_list()
        if users:
            prefix = (email.split("@")[0] or "").strip().lower()
            if not prefix:
                return ""
            for u in users:
                s = str(u).strip() if u else ""
                if not s:
                    continue
                # quality_users 格式："邮箱前缀+中文姓名"（如 bruce.cheng程强）
                # 匹配规则：字符串以当前邮箱前缀开头，且后面跟着非 ASCII 字符（即中文姓名）
                sl = s.lower()
                if sl.startswith(prefix) and len(s) > len(prefix):
                    # 提取前缀后面的部分作为姓名
                    name_part = s[len(prefix):].strip()
                    # 确保提取到的是中文/非ASCII内容（不是另一个邮箱前缀）
                    if name_part and any(ord(c) > 127 for c in name_part):
                        return name_part
    except Exception:
        pass
    return ""


def _streamlit_cloud_login():
    """Streamlit Cloud 环境：平台已认证用户"""
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        email = (headers or {}).get("X-Streamlit-User", "user@sainstore.com")
    except Exception:
        email = "user@sainstore.com"
    st.session_state.authenticated = True
    st.session_state.user_email = email
    st.session_state.user_name = email.split("@")[0]
    st.session_state.is_admin = is_admin(email)
    _capture_client_info()


def _capture_client_info():
    """从请求上下文捕获客户端 IP 与网络区域，写入 session_state（供审计使用）"""

    def _determine_zone(raw_ip, host):
        """根据 IP 与 Host 判断内网/外网。"""
        # 优先用 X-Forwarded-For / X-Real-IP 的真实客户端 IP
        if raw_ip:
            import ipaddress as _ip
            try:
                return "内网" if _ip.ip_address(raw_ip.split(",")[0].strip()).is_private else "外网"
            except ValueError:
                pass
        # 回退：用 Host 域名判断
        if host:
            return "内网" if _is_private_network_host(host) else "外网"
        return "未知"

    # 已成功捕获过则跳过
    if st.session_state.get("client_ip"):
        return

    raw_ip = ""
    host = ""

    # 1) 优先使用 st.context（Streamlit 1.37+ 可靠来源）
    try:
        ctx = st.context
        hdrs = ctx.headers or {}
        # 代理场景：优先用 X-Forwarded-For / X-Real-IP 的真实客户端 IP
        raw_ip = (hdrs.get("X-Forwarded-For", "") or hdrs.get("X-Real-IP", "") or "").split(",")[0].strip()
        # 直连场景：用 context 的 peer IP
        if not raw_ip and ctx.ip_address:
            raw_ip = (ctx.ip_address or "").strip()
        host = (hdrs.get("X-Forwarded-Host", "") or hdrs.get("Host", "") or "").split(":")[0].strip().lower()
    except Exception:
        pass

    # 2) 回退：旧内部 API
    if not raw_ip and not host:
        try:
            from streamlit.web.server.websocket_headers import _get_websocket_headers
            _hdrs = _get_websocket_headers() or {}
            if _hdrs:
                raw_ip = (_hdrs.get("X-Forwarded-For", "") or _hdrs.get("X-Real-IP", "") or "").split(",")[0].strip()
                host = (_hdrs.get("X-Forwarded-Host", "") or _hdrs.get("Host", "") or "").split(":")[0].strip().lower()
        except Exception:
            pass

    # 3) 兜底：socket 检测本机 IP
    if not raw_ip:
        try:
            import socket
            raw_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            raw_ip = ""

    st.session_state.client_ip = raw_ip
    st.session_state.network_zone = _determine_zone(raw_ip, host)


def _set_auth_cookie(email, name=""):
    """设置登录 cookie（6天有效期），携带用户姓名以支持会话恢复。

    关键：必须用 CookieManager.set 写入，与读取同源。若改用 st.html 直接写
    document.cookie，CookieManager 前端 React state 不会感知，会缓存旧值，
    导致「退出后 CookieManager 仍读回旧 qs_auth 自动恢复登录」。
    CookieManager 不可用时退回 st.html 兜底。
    """
    exp_ts = int(time_module.time() + 6 * 24 * 3600)  # 6天
    token = _encode_auth_token(email, exp_ts, name)
    if CookieManager is None:
        st.html(
            f'<script>document.cookie = "qs_auth={token}; max-age={6 * 24 * 3600}; path=/; SameSite=Lax";</script>',
            unsafe_allow_javascript=True,
        )
        return
    try:
        cm = st.session_state.get("_cookie_mgr") or CookieManager()
        # 所有读写必须共用同一个组件实例。否则一次页面运行中同时挂载两个
        # CookieManager iframe，会触发重复组件/重复重跑，进而放大侧边栏控件的
        # duplicate-key 异常。
        st.session_state["_cookie_mgr"] = cm
        cm["qs_auth"] = token
        cm.save()
    except Exception as e:
        import sys as _sys
        print(f"[AUTH] CookieManager.set 失败，退回 st.html: {type(e).__name__}: {str(e)[:160]}",
              file=_sys.stderr)
        try:
            st.html(
                f'<script>document.cookie = "qs_auth={token}; max-age={6 * 24 * 3600}; path=/; SameSite=Lax";</script>',
                unsafe_allow_javascript=True,
            )
        except Exception:
            pass


def _clear_auth_cookie():
    """清除登录 cookie（与读取同源，确保前端 state 与 document.cookie 一致）"""
    if CookieManager is not None:
        try:
            # 退出时也复用 init_session 已挂载的实例，禁止额外创建第二个
            # CookieManager 组件。
            cm = st.session_state.get("_cookie_mgr") or CookieManager()
            st.session_state["_cookie_mgr"] = cm
            if "qs_auth" in cm:
                del cm["qs_auth"]
                cm.save()
        except Exception as e:
            import sys as _sys
            print(f"[AUTH] CookieManager.delete 失败: {type(e).__name__}: {str(e)[:160]}",
                  file=_sys.stderr)
    # 双保险：直接清 document.cookie（即使上面异常也尽量清）
    try:
        st.html('<script>document.cookie = "qs_auth=; max-age=0; path=/";</script>',
                unsafe_allow_javascript=True)
    except Exception:
        pass


def _encode_auth_token(email, exp_ts, name=""):
    """加密生成 auth token（携带 email|过期时间|姓名|签名，向后兼容旧格式）"""
    secret = _COOKIE_SECRET
    # 新格式：email|exp|name|sig（4 段）；name 为空时兼容旧格式 email|exp|sig（3 段）
    if name:
        payload = f"{email}|{exp_ts}|{name}"
        sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        return f"{payload}|{sig}"  # 4 段
    else:
        payload = f"{email}|{exp_ts}"
        sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        return f"{payload}|{sig}"  # 3 段（向后兼容）


def _decode_auth_token(token):
    """解密 auth token，返回 (email, exp_ts, name) 或 (None, None,"")"""
    try:
        parts = token.split("|")
        secret = _COOKIE_SECRET
        if len(parts) == 4:
            # 新格式：email|exp|name|sig
            email, exp_ts, name, sig = parts
            payload = f"{email}|{exp_ts}|{name}"
            expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
            if sig != expected:
                return None, None, ""
            return email, int(exp_ts), name
        elif len(parts) == 3:
            # 旧格式兼容：email|exp|sig（无姓名）
            email, exp_ts, sig = parts
            payload = f"{email}|{exp_ts}"
            expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
            if sig != expected:
                return None, None, ""
            return email, int(exp_ts), ""
        else:
            return None, None, ""
    except Exception:
        return None, None, ""


def exchange_code_for_token(code, redirect_uri):
    """用授权码换取 token，并获取用户信息"""
    config = get_oauth_config()
    if not config:
        return None, "未配置 Google OAuth 客户端密钥 (client_secret.json)"

    _sys = __import__('sys')
    # 记录请求参数（client_secret 仅打印前 4 位）
    print(f"[OAUTH] POST {GOOGLE_TOKEN_URL}"
          f"client_id={config.get('client_id','')[:20]}..."
          f"redirect_uri={redirect_uri}"
          f"code={code[:12]}...",
          file=_sys.stderr)

    # 交换 token
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)

    print(f"[OAUTH] token response status={token_resp.status_code} body={token_resp.text[:500]}",
          file=_sys.stderr)

    if not token_resp.ok:
        try:
            err_payload = token_resp.json()
            err_code = err_payload.get("error", "unknown")
            err_desc = err_payload.get("error_description", token_resp.text)
        except Exception:
            err_code = "unknown"
            err_desc = token_resp.text or "Bad Request"
        # 常见错误中文映射，便于用户自助排查
        friendly = {
            "invalid_grant": ("授权码已过期或已使用（请勿刷新回调页，请重新点击登录按钮）。"
                              f"当前回调地址为 {redirect_uri}，请确认与 Google Cloud Console 的「已获授权的重定向 URI」完全一致。"),
            "redirect_uri_mismatch": f"回调地址不匹配：当前为 {redirect_uri}",
            "invalid_client": "客户端密钥错误，请检查 client_secret.json",
            "invalid_request": "请求参数错误",
        }.get(err_code, err_desc)
        return None, f"Token 交换失败 [{err_code}]: {friendly}"

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return None, "未能获取 access_token"

    # 获取用户信息
    user_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )

    if not user_resp.ok:
        return None, "获取用户信息失败"

    user_info = user_resp.json()
    return user_info, None


def _truthy_env(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _get_request_host():
    """获取当前请求 host，供公网/本地模式判断复用"""
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers:
            host = headers.get("X-Forwarded-Host", "") or headers.get("Host", "")
            return host.strip().lower()
    except Exception:
        pass
    return ""


def _is_public_host(host):
    if not host:
        return False
    bare_host = host.split(":")[0].strip().lower()
    if bare_host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    try:
        # RFC1918 / loopback / link-local 地址属于内网，不应触发公网登录流程。
        return not ipaddress.ip_address(bare_host).is_private
    except ValueError:
        # 域名只有在明确不是本地网络域名时才按公网处理。
        return not (bare_host.endswith(".local") or bare_host.endswith(".lan"))


def _is_private_network_host(host):
    if not host:
        return False
    bare_host = host.split(":")[0].strip().lower()
    if bare_host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    try:
        return ipaddress.ip_address(bare_host).is_private
    except ValueError:
        return bare_host.endswith(".local") or bare_host.endswith(".lan")


def _use_lan_password_login():
    if not os.environ.get("LAN_ACCESS_PASSWORD", "").strip():
        return False
    if _truthy_env("FORCE_LAN_LOGIN"):
        return True
    return _is_private_network_host(_get_request_host())


def is_production():
    """判断是否在生产环境（Streamlit Cloud / 公网隧道 / 反向代理 / Windows 局域网服务器）"""
    if _truthy_env("FORCE_PRODUCTION"):
        return True
    if os.environ.get("PUBLIC_BASE_URL", "").strip():
        return True
    if os.environ.get("STREAMLIT_SHARING_MODE", ""):
        return True
    if _is_public_host(_get_request_host()):
        return True
    return False


def is_effectively_logged_in():
    """统一的「已登录」判定：authenticated 为真「且」身份已解析
    （姓名非空且非占位「用户」，或至少有邮箱）。

    用作全局访问闸门——未登录或仅显示「未登录」时返回 False，
    使入口只渲染登录页、完全不加载任何业务板块与操作。"""
    if not st.session_state.get("authenticated"):
        return False
    _nm = (st.session_state.get("user_name") or "").strip()
    _em = (st.session_state.get("user_email") or "").strip()
    return bool((_nm and _nm != "用户") or _em)


def is_streamlit_cloud():
    """判断是否在 Streamlit Cloud"""
    return bool(os.environ.get("STREAMLIT_SHARING_MODE", ""))


def _finish_login(email, name="", picture="", login_method="Google OAuth 登录"):
    """统一完成登录态写入、cookie 和日志"""
    final_email = (email or "").strip().lower()
    final_name = name or (final_email.split("@")[0] if final_email else "用户")
    st.session_state.authenticated = True
    st.session_state.user_email = final_email
    st.session_state.user_name = final_name
    st.session_state.user_picture = picture or ""
    st.session_state.is_admin = is_admin(final_email)
    st.session_state["_logged_out"] = False  # 主动登录即解除退出态（同会话内快速拦截复位）
    _capture_client_info()
    # 清除「已注销」持久标记，使后续正常刷新可恢复登录（跨 reload 也生效）
    try:
        _lcm = st.session_state.get("_cookie_mgr")
        if _lcm is not None and getattr(_lcm, "ready", lambda: False)() and "qs_logged_out" in _lcm:
            del _lcm["qs_logged_out"]
            _lcm.save()
    except Exception:
        pass
    _set_auth_cookie(final_email, final_name)
    log_activity(final_email, "登录成功", "login", login_method, "首页")


def _render_lan_login_form():
    """局域网共享登录：公司邮箱 + 共享访问密码。

    改为原生 HTML form POST 到 /api/lan-login，由 Starlette 服务端直接设置
    HTTP cookie，彻底解决 Streamlit 脚本内写 cookie 在公网/刷新场景下失效、
    导致每次刷新都退出的问题。
    """
    allowed_domain = os.environ.get("LAN_ALLOWED_DOMAIN", "sainstore.com").strip().lower()
    expected_password = os.environ.get("LAN_ACCESS_PASSWORD", "").strip()

    if not expected_password:
        st.warning("局域网访问密码尚未配置，请联系管理员或使用 Google 账号登录。")
        return

    # 显示服务端返回的错误（如密码错误）
    query_params = st.query_params
    if "lan_error" in query_params:
        st.error(query_params["lan_error"])
        try:
            st.query_params.pop("lan_error", None)
        except Exception:
            pass

    # 原生表单：提交后服务端 Set-Cookie 并重定向
    st.html(f"""
    <form id="lan-login-form" action="/api/lan-login" method="POST" style="text-align:left;">
        <input type="hidden" name="redirect" id="lan-redirect" value="/">
        <div style="margin-bottom:14px;">
            <label style="display:block;font-size:12.5px;color:#475569;margin-bottom:5px;font-weight:500;">公司邮箱</label>
            <input type="email" name="email" required placeholder="name@{allowed_domain}"
                style="width:100%;box-sizing:border-box;border-radius:10px;border:1.5px solid #e2e8f0;background:#fafbfc;font-size:14.5px;padding:12px 14px;outline:none;color:#0f172a;"
                onfocus="this.style.borderColor='#2563eb';this.style.background='#fff'" onblur="this.style.borderColor='#e2e8f0';this.style.background='#fafbfc'">
        </div>
        <div style="margin-bottom:18px;">
            <label style="display:block;font-size:12.5px;color:#475569;margin-bottom:5px;font-weight:500;">访问密码</label>
            <input type="password" name="password" required placeholder="请输入共享访问密码"
                style="width:100%;box-sizing:border-box;border-radius:10px;border:1.5px solid #e2e8f0;background:#fafbfc;font-size:14.5px;padding:12px 14px;outline:none;color:#0f172a;"
                onfocus="this.style.borderColor='#2563eb';this.style.background='#fff'" onblur="this.style.borderColor='#e2e8f0';this.style.background='#fafbfc'">
        </div>
        <button type="submit"
            style="width:100%;box-sizing:border-box;border-radius:10px;font-weight:700;font-size:15px;padding:12px;background:#2563eb;color:#fff;border:none;cursor:pointer;"
            onmouseover="this.style.background='#1d4ed8'" onmouseout="this.style.background='#2563eb'">
            进入系统
        </button>
    </form>
    <script>
        (function() {{
            var rd = document.getElementById('lan-redirect');
            if (rd) rd.value = window.location.pathname + window.location.search;
        }})();
    </script>
    """)


# ---- 管理面板 ----
def admin_panel():
    """管理员面板：管理授权用户（仅本地开发环境可见）"""
    config = load_auth_config()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 管理员面板")

    with st.sidebar.expander("授权用户管理", expanded=False):
        auth_list = config.setdefault("authorized_emails", [])
        admin_list = config.setdefault("admin_emails", [])
        all_emails = list(dict.fromkeys(auth_list + admin_list))  # 保序去重，合并展示
        st.caption(f"已授权登录 {len(auth_list)} 个 · 管理员（可审核）{len(admin_list)} 个")

        # 逐一显示账号，并标注权限 / 提供升降级与移除
        for email in all_emails:
            is_adm = email in admin_list
            col1, col2, col3 = st.columns([4, 1.3, 1])
            with col1:
                st.code(email, language=None)
            with col2:
                if is_adm:
                    st.caption("管理员")
                    if st.button("降", key=f"demo_{email}", help="降为普通用户（取消审核权限）"):
                        config["admin_emails"] = [e for e in admin_list if e != email]
                        save_auth_config(config)
                        st.rerun()
                else:
                    if st.button("升", key=f"promo_{email}", help="提升为管理员（可审核报告）"):
                        config["admin_emails"] = admin_list + [email]
                        save_auth_config(config)
                        st.rerun()
            with col3:
                if st.button("", key=f"del_{email}", help=f"移除 {email}"):
                    config["authorized_emails"] = [e for e in auth_list if e != email]
                    config["admin_emails"] = [e for e in admin_list if e != email]
                    save_auth_config(config)
                    st.rerun()

        # 新增授权（可选权限级别）
        st.markdown("---")
        new_email = st.text_input("添加账号邮箱", placeholder="name@sainstore.com", key="admin_add_email")
        new_role = st.selectbox(
            "权限级别",
            ["普通用户（仅登录）", "管理员（可审核报告）"],
            index=0,
            key="admin_add_role",
        )
        if st.button("添加授权", type="primary", width="stretch"):
            if new_email and "@" in new_email:
                em = new_email.lower().strip()
                if em in [e.lower() for e in auth_list]:
                    st.warning("该邮箱已在授权列表中")
                else:
                    config["authorized_emails"] = auth_list + [em]
                    if new_role.startswith("管理员"):
                        config["admin_emails"] = admin_list + [em]
                    save_auth_config(config)
                    st.success(f"已添加 {em}（{new_role}）")
                    st.rerun()
            else:
                st.error("请输入有效的邮箱地址")

        # 全局开关
        st.markdown("---")
        st.caption("危险操作")
        allow_all = st.toggle(
            "允许所有 Google 账号登录",
            value=config.get("allow_all_google", False),
            help="开启后任何 Google 账号都可以登录，无需逐一添加"
        )
        if allow_all != config.get("allow_all_google", False):
            config["allow_all_google"] = allow_all
            save_auth_config(config)
            st.rerun()

    with st.sidebar.expander("OAuth 配置状态", expanded=False):
        secrets = load_client_secrets()
        if secrets:
            st.success("client_secret.json 已配置 client_secret.json 已配置")
            web = secrets.get("web", secrets.get("installed", {}))
            st.caption(f"Client ID: {web.get('client_id', 'N/A')[:20]}...")
        else:
            st.error("未找到 client_secret.json 未找到 client_secret.json")
            st.caption(f"请将文件放置于: `{CLIENT_SECRETS_FILE}`")

        st.caption(f"Redirect URI: `{get_redirect_uri()}`")


# ---- 登录页面 ----
def _js_set_cookie_and_redirect(email, name="", redirect="/"):
    """用 JS 同步写入 qs_auth cookie 并立即跳转，避免 Streamlit rerun 导致状态丢失。"""
    exp_ts = int(time_module.time() + 6 * 24 * 3600)
    token = _encode_auth_token(email, exp_ts, name)
    max_age = 6 * 24 * 3600
    token_json = json.dumps(token)
    js = f'''<script>
    document.cookie = "qs_auth=" + encodeURIComponent({token_json}) + "; max-age={max_age}; path=/; SameSite=Lax";
    document.cookie = "qs_logged_out=; max-age=0; path=/";
    window.location.replace("{redirect}");
    </script>'''
    st.html(js, unsafe_allow_javascript=True)


def _handle_oauth_callback(query_params):
    """处理 Google OAuth 回调：完成登录或报错。

    放在 login_page 的 UI 渲染之前调用，避免回调过渡态出现两套 logo/标题。
    增加防重入：同一个授权码只交换一次，防止 Streamlit 组件重跑或浏览器重复请求
    导致 code 被用掉后第二次交换报 invalid_grant。

    关键修复：不再调用 st.query_params.clear() + st.rerun()。
    Streamlit 在 clear() 后会触发 rerun，可能把登录态/错误提示「吃掉」并重新渲染
    普通登录页，表现为点击登录后又回到登录界面。成功时改用 JS 同步写 cookie 并
    跳转；失败时保留当前页显示错误信息。
    """
    code = query_params["code"]
    state = query_params["state"]

    # 防重入：已处理过同一 code
    if st.session_state.get("_last_oauth_code") == code:
        print(f"[OAUTH] 重复回调，跳过已处理授权码: {code[:12]}...", file=__import__('sys').stderr)
        if st.session_state.get("authenticated"):
            # 已登录，直接跳转到主页（JS 跳转，不触发 rerun）
            _js_set_cookie_and_redirect(st.session_state.get("user_email", ""), st.session_state.get("user_name", ""))
        else:
            # 同一授权码被重复进入且尚未登录：多半是前一次 Streamlit 运行被中断。
            # 直接给出明确提示，避免用户只看到空白/登录页而困惑。
            st.error("登录处理被中断，请重新点击「Sign in with Google」按钮。 登录处理被中断，请重新点击「Sign in with Google」按钮。")
            _render_login_button()
        return
    st.session_state._last_oauth_code = code

    config = get_oauth_config()
    api_secret = config["client_secret"][:16] if config else ""
    expected_session = st.session_state.get("oauth_state", "")
    state_ok = _verify_oauth_state(state, api_secret) or (state == expected_session)
    print(f"[OAUTH] callback received code={code[:12]}... state={state[:12]}... state_ok={state_ok}"
          f"expected_session={expected_session[:12]}... redirect_uri={get_redirect_uri()}",
          file=__import__('sys').stderr)
    if not state_ok:
        st.error("OAuth 安全校验失败（state 不匹配或已过期），请重新点击登录。 OAuth 安全校验失败（state 不匹配或已过期），请重新点击登录。")
        _render_login_button()
        return

    # 交换 token
    redirect_uri = get_redirect_uri()
    print(f"[OAUTH] 开始交换 token，redirect_uri={redirect_uri}", file=__import__('sys').stderr)
    with st.spinner("Google 验证中..."):
        user_info, error = exchange_code_for_token(code, redirect_uri)

    if error:
        print(f"[OAUTH] 交换 token 失败: {error}", file=__import__('sys').stderr)
        st.error(f"{error}")
        st.info("提示：Google 授权码只能使用一次，回调后请勿刷新页面。如果失败，请直接点击下方按钮重新登录。 提示：Google 授权码只能使用一次，回调后请勿刷新页面。如果失败，请直接点击下方按钮重新登录。")
        _render_login_button()
        return

    email = user_info.get("email", "")
    name = user_info.get("name", email.split("@")[0] if email else "")
    picture = user_info.get("picture", "")

    if not is_authorized(email):
        st.error(f"""
        ### ⛔ 访问被拒绝

        您的 Google 账号 **{email}** 未被授权访问此系统。

        请联系管理员 **Bruce Cheng（程强）** 添加授权。
        """)
        _render_login_button()
        return

    # 登录成功
    st.session_state.authenticated = True
    st.session_state.user_email = email
    st.session_state.user_name = name
    st.session_state.user_picture = picture
    st.session_state.is_admin = is_admin(email)
    st.session_state["_logged_out"] = False  # 主动登录即解除退出态（与 _finish_login 保持一致）

    # 清除「已注销」持久标记，使后续正常刷新可恢复登录（跨 reload 也生效）
    # 否则登录后刷新会被 qs_logged_out 拦截踢回登录页（与局域网密码登录对称处理）
    try:
        _lcm = st.session_state.get("_cookie_mgr")
        if _lcm is not None and getattr(_lcm, "ready", lambda: False)() and "qs_logged_out" in _lcm:
            del _lcm["qs_logged_out"]
            _lcm.save()
    except Exception:
        pass

    # 设置 6 天有效期 cookie（携带真实姓名）
    _set_auth_cookie(email, name)

    # 记录登录日志
    log_activity(email, "登录成功", "login", f"Google OAuth 登录", "首页")

    # 用 JS 同步写 cookie 并立即跳转，避免 Streamlit rerun 把登录态吃掉
    st.success("登录成功，正在进入系统...")
    _js_set_cookie_and_redirect(email, name)


def _handle_oauth_error(query_params):
    """处理 Google OAuth 错误回调：仅显示错误与重试按钮，不渲染 logo。"""
    st.error(f"Google 登录被取消或失败: {query_params.get('error', 'unknown')} Google 登录被取消或失败: {query_params.get('error', 'unknown')}")
    _render_login_button()


def _render_lan_login_card():
    """局域网登录：单卡片一体化设计（品牌 + 表单合一）"""
    logo = _logo_data_uri()
    if logo:
        logo_html = f'<img src="{logo}" style="width:56px;height:56px;object-fit:contain;border-radius:12px;">'
    else:
        logo_html = '<div style="width:56px;height:56px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;font-size:24px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(37,99,235,.35);">Q</div>'

    st.markdown(f"""
    <div style="
        background:#fff;border-radius:20px;box-shadow:
        0 4px 6px -1px rgba(0,0,0,.07),0 10px 30px -5px rgba(0,0,0,.08);
        padding:40px 36px 32px;max-width:420px;margin:0 auto;text-align:center;
    ">
        <div style="margin-bottom:20px;">{logo_html}</div>
        <h1 style="font-size:22px;font-weight:800;color:#0f172a;margin:0 0 4px;
            letter-spacing:-.3px;">品质系统管理平台</h1>
        <p style="font-size:13px;color:#64748b;margin:0 0 28px;font-weight:400;">
            Quality System Management Platform</p>
    """, unsafe_allow_html=True)
    _render_lan_login_form()
    st.markdown(f"""
    <p style="font-size:11px;color:#94a3b8;margin-top:18px;text-align:center;">
        © 2026 SainStore Inc. · Developed by Bruce Cheng 程强</p>
    </div>
    """, unsafe_allow_html=True)


def login_page():
    """登录页面（Google OAuth / 局域网共享密码）—— 现代单卡片设计"""
    # 隐藏 Streamlit 默认侧边栏与顶部栏
    st.html("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    header[data-testid="stHeader"] { display: none !important; }
    .stApp > header { display: none !important; }
    .stApp { --sidebar-width: 0px !important; }

    /* ── 登录页背景：柔和渐变 ── */
    html, body, .stApp, section.main {
        background: linear-gradient(135deg, #f0f4ff 0%, #e8efff 40%, #f5f0fa 100%) !important;
        min-height: 100vh;
    }
    .block-container {
        padding-top: 10vh !important;
        max-width: 480px !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }

    /* ── 表单输入框美化 ── */
    div[data-testid="stForm"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="stForm"] > div {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }
    div[data-testid="stTextInput"] > div > div > input {
        border-radius: 10px !important;
        border: 1.5px solid #e2e8f0 !important;
        background: #fafbfc !important;
        font-size: 14.5px !important;
        padding: 12px 14px !important;
        transition: border-color .2s, box-shadow .2s !important;
    }
    div[data-testid="stTextInput"] > div > div > input:focus {
        border-color: #2563eb !important;
        box-shadow: 0 0 0 3px rgba(37,99,235,.12) !important;
        background: #fff !important;
    }
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        padding: 12px !important;
        margin-top: 4px !important;
        background: linear-gradient(135deg,#2563eb,#1d4ed8) !important;
        border: none !important;
        box-shadow: 0 3px 12px rgba(37,99,235,.28) !important;
        transition: transform .1s, box-shadow .15s !important;
    }
    div[data-testid="stFormSubmitButton"] > button:hover {
        box-shadow: 0 4px 18px rgba(37,99,235,.38) !important;
        transform: translateY(-1px) !important;
    }
    div[data-testid="stFormSubmitButton"] > button:active {
        transform: translateY(0) !important;
    }

    /* ── 错误/提示框居中圆角 ── */
    section.main .stAlert {
        max-width: 420px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        border-radius: 12px !important;
        font-size: 13.5px !important;
    }

    /* ── 密码显示切换按钮对齐 ── */
    div[data-testid="stTextInput"] button {
        top: 6px !important;
        right: 8px !important;
    }
    </style>
    """)

    query_params = st.query_params

    # 先处理 OAuth 回调/错误，避免在过渡态渲染 logo 造成视觉重复
    # 注意：code/state 回调现在由 Starlette 中间件（unified_app.py）处理并设置 cookie，
    # 正常情况下不会再进入这里；保留兜底逻辑以兼容旧入口或异常场景。
    if "code" in query_params and "state" in query_params:
        _handle_oauth_callback(query_params)
        return
    if "error" in query_params:
        _handle_oauth_error(query_params)
        return
    if "oauth_error" in query_params:
        st.error(f"{query_params['oauth_error']}")
        _render_login_button()
        return

    # ── 登录页：只显示当前环境实际可用的登录方式 ──
    # 未配置共享 LAN 密码时，不能渲染一个无法提交的密码卡片；
    # 直接使用已配置的 Google OAuth，确保本地也遵守同一登录闸门。
    if os.environ.get("LAN_ACCESS_PASSWORD", "").strip():
        _render_lan_login_card()
    else:
        _render_login_button()


def _get_oauth_state(api_secret):
    """生成 OAuth state，基于时间窗口防止 CSRF（兼容多实例）"""
    import time
    window = str(int(time.time() / 300))  # 5分钟窗口
    return hashlib.sha256(f"{api_secret}:{window}".encode()).hexdigest()[:32]

def _verify_oauth_state(state, api_secret):
    """验证 state（允许前后5分钟窗口）"""
    import time
    for offset in [-1, 0, 1]:
        window = str(int(time.time() / 300) + offset)
        expected = hashlib.sha256(f"{api_secret}:{window}".encode()).hexdigest()[:32]
        if state == expected:
            return True
    return False

# 官方 Google "G" 四色标志（用于登录按钮，避免低分辨率 favicon）
GOOGLE_G_SVG = """<svg class="qs-g-icon"width="18"height="18"viewBox="0 0 18 18"xmlns="http://www.w3.org/2000/svg"><path fill="#4285F4"d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/><path fill="#34A853"d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/><path fill="#FBBC05"d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z"/><path fill="#EA4335"d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95L3.97 7.28C4.68 5.16 6.66 3.58 9 3.58z"/></svg>"""


def _logo_data_uri():
    """读取 logo 文件并转为 data URI，便于在纯 HTML 卡片中嵌入（避免路径依赖）。"""
    import base64
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            ext = os.path.splitext(LOGO_PATH)[1].lower().lstrip(".")
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "svg": "image/svg+xml", "webp": "image/webp"}.get(ext, "image/png")
            with open(LOGO_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:image/{mime};base64,{b64}"
        except Exception:
            return None
    return None


def _render_login_button():
    """渲染 Google 登录按钮"""
    config = get_oauth_config()

    if not config:
        st.warning("### Google OAuth 未配置### Google OAuth 未配置")
        st.info(f"""
请按以下步骤配置：

1. 访问 [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. 创建 OAuth 2.0 客户端 ID（Web 应用类型）
3. 添加授权的重定向 URI: `{get_redirect_uri()}`
4. 下载 JSON 密钥文件
5. 将文件保存为 `data/client_secret.json`

**本地开发 OAuth 配置：**
```
JavaScript 来源: http://localhost:8501  
重定向 URI:      http://localhost:8501
```

> 部署公网后需要回来添加生产环境地址
        """)
        return

    # 生成 state 防止 CSRF
    api_secret = config["client_secret"][:16]
    oauth_state = _get_oauth_state(api_secret)
    st.session_state.oauth_state = oauth_state

    redirect_uri = get_redirect_uri()
    client_id = config["client_id"]
    print(f"[OAUTH] 构建登录链接 redirect_uri={redirect_uri} state={oauth_state[:12]}...",
          file=__import__('sys').stderr)

    # 构建 Google OAuth URL
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": oauth_state,
        "access_type": "offline",
        "prompt": "select_account",
    }

    param_str = "&".join([f"{k}={requests.utils.quote(v)}" for k, v in auth_params.items()])
    auth_url = f"{GOOGLE_AUTH_URL}?{param_str}"

    # 登录 UI：单卡片一体化设计（品牌 + OAuth 按钮合一）
    logo = _logo_data_uri()
    if logo:
        logo_html = f'<img src="{logo}" style="width:56px;height:56px;object-fit:contain;border-radius:12px;">'
    else:
        logo_html = '<div style="width:56px;height:56px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;font-size:24px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(37,99,235,.35);">Q</div>'

    st.markdown(f"""
    <div style="
        background:#fff;border-radius:20px;box-shadow:
        0 4px 6px -1px rgba(0,0,0,.07),0 10px 30px -5px rgba(0,0,0,.08);
        padding:40px 36px 32px;max-width:420px;margin:0 auto;text-align:center;
    ">
        <div style="margin-bottom:20px;">{logo_html}</div>
        <h1 style="font-size:22px;font-weight:800;color:#0f172a;margin:0 0 4px;
            letter-spacing:-.3px;">品质系统管理平台</h1>
        <p style="font-size:13px;color:#64748b;margin:0 0 24px;font-weight:400;">
            Quality System Management Platform</p>
        <div style="display:flex;align-items:center;gap:12px;color:#94a3b8;
            font-size:12px;margin:0 0 20px;">
            <span style="flex:1;height:1px;background:#e2e8f0;"></span>
            <span>使用以下方式登录</span>
            <span style="flex:1;height:1px;background:#e2e8f0;"></span>
        </div>
        <a href="{auth_url}" target="_self" style="
            display:inline-flex;align-items:center;justify-content:center;gap:10px;
            width:100%;box-sizing:border-box;
            background:#fff;color:#3c4043;
            border:1.5px solid #dadce0;border-radius:10px;
            padding:13px 20px;font-size:15px;font-weight:600;text-decoration:none;
            box-shadow:0 1px 3px rgba(60,64,67,.15);
            transition:box-shadow .2s,background .15s,transform .08s;
        ">
            {GOOGLE_G_SVG}
            <span>使用 Google 账号登录</span>
        </a>
        <p style="font-size:11.5px;color:#94a3b8;margin-top:14px;">
            点击按钮跳转至 Google 进行身份验证</p>
        <p style="font-size:11px;color:#cbd5e1;margin-top:18px;padding-top:16px;
            border-top:1px solid #f1f5f9;">
            © 2026 SainStore Inc. · Developed by Bruce Cheng 程强</p>
    </div>
    """, unsafe_allow_html=True)


# ---- 主应用 ----
def main_app():
    """主应用入口"""
    # 注：Logo 已由 _pages/_utils.py 的 render_sidebar() 在侧边栏顶部渲染，
    # 此处不再重复调用 st.logo()，避免页面出现“两套 Logo”。


    # 页面导航
    # 业务名称由页面正文和自定义导航显示；浏览器标签统一使用系统名称，
    # 避免 Streamlit 在页面切换/重连时在“品质工作台”和系统名之间跳变。
    browser_title = "品质系统管理平台"
    home_page = st.Page("pages/page_workbench.py", title=browser_title)
    usage_page = st.Page("pages/page_usage.py", title=browser_title)
    borrow_page = st.Page("pages/page_borrow.py", title=browser_title)
    equipment_page = st.Page("pages/page_equipment.py", title=browser_title)
    maintenance_page = st.Page("pages/page_maintenance.py", title=browser_title)
    inspection_page = st.Page("pages/page_reports.py", title=browser_title)
    sample_page = st.Page("pages/page_samples.py", title=browser_title)
    factory_page = st.Page("pages/page_factory_registration.py", title=browser_title)
    change_page = st.Page("pages/page_changes.py", title=browser_title)
    report_page = st.Page("pages/page_dashboard.py", title=browser_title)
    changelog_page = st.Page("pages/page_changelog.py", title=browser_title)
    about_page = st.Page("pages/page_about.py", title=browser_title)

    pages = {
        "首页": [home_page],
        "实验室管理": [
            usage_page,
            borrow_page,
            equipment_page,
            maintenance_page,
        ],
        "品质管理": [
            inspection_page,
            sample_page,
            factory_page,
            change_page,
            report_page,
        ],
        "关于": [
            changelog_page,
            about_page,
        ],
    }

    # 仅本地开发环境显示数据智能分析（公网不加载）
    if not is_production():
        analytics_pages = [
            st.Page(page_path, title=title)
            for page_path, title, icon in get_optional_analytics_pages()
        ]
        if analytics_pages:
            pages["数据智能分析"] = analytics_pages


    # 系统监控只对授权管理员开放，开发环境不再绕过账号权限。
    is_authorized_admin = bool(st.session_state.get("is_admin", False)) or is_admin_email(
        st.session_state.get("user_email", "")
    )
    if is_authorized_admin:
        monitor_page = st.Page("pages/page_monitor.py", title=browser_title)
        audit_page = st.Page("pages/page_audit.py", title=browser_title)
        recycle_page = st.Page("pages/page_recycle.py", title=browser_title)
        pages["系统监控"] = [monitor_page, audit_page, recycle_page]

    # 标记使用 st.navigation API（供 _utils.py 判断，避免重复渲染自定义导航）
    st.session_state["_using_navigation_api"] = True
    st.session_state["_nav_page_objects"] = {
        "main.py": home_page,
        "pages/page_workbench.py": home_page,
        "pages/page_usage.py": usage_page,
        "pages/page_borrow.py": borrow_page,
        "pages/page_equipment.py": equipment_page,
        "pages/page_maintenance.py": maintenance_page,
        "pages/page_reports.py": inspection_page,
        "pages/page_samples.py": sample_page,
        "pages/page_factory_registration.py": factory_page,
        "pages/page_changes.py": change_page,
        "pages/page_dashboard.py": report_page,
        "pages/page_changelog.py": changelog_page,
        "pages/page_about.py": about_page,
    }
    if is_authorized_admin:
        st.session_state["_nav_page_objects"]["pages/page_monitor.py"] = monitor_page
        st.session_state["_nav_page_objects"]["pages/page_audit.py"] = audit_page
        st.session_state["_nav_page_objects"]["pages/page_recycle.py"] = recycle_page

    pg = st.navigation(pages, position="hidden")
    pg.run()

    # 管理员面板：移至侧边栏最底部（默认折叠 + 与业务菜单间有分隔线；仅管理员可见，权限逻辑不变）
    if is_authorized_admin:
        admin_panel()

    # 记录页面访问（页面变化时记录一次）
    try:
        ctx = __import__('streamlit.runtime.scriptrunner.script_run_context', fromlist=['get_script_run_ctx']).get_script_run_ctx()
        current_page = ctx.page_script_hash if ctx else ''
        page_name = ctx.page_script_name if ctx else ''
    except Exception:
        current_page = ''
        page_name = ''

    if current_page and current_page != st.session_state.get("_last_page_hash", ""):
        st.session_state["_last_page_hash"] = current_page
        user = st.session_state.get("user_email", "unknown")
        # 从路径中提取页面名称，如 "lab_usage.py" → "使用登记"
        page_display = page_name.split('/')[-1].replace('.py', '') if page_name else '未知页面'
        log_activity(user, f"浏览页面", "page_view", f"访问 {page_display}", page_display)


# ==================== 入口（带稳定性保护） ====================
try:
    init_db()
    init_session()

    # 顶栏「退出登录」入口：?logout=1 清除登录态并回到登录页（不写任何业务数据）
    if "logout" in st.query_params:
        for _k in ["authenticated", "user_email", "user_name", "user_picture",
                   "is_admin", "oauth_state", "_login_checked", "_last_oauth_code"]:
            st.session_state.pop(_k, None)
        st.session_state["_logged_out"] = True
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()

    if is_effectively_logged_in():
        main_app()
    else:
        login_page()
except Exception as e:
    st.error(f"系统遇到意外错误，请刷新页面重试。")
    st.caption(f"错误详情（仅开发者可见）: {str(e)[:500]}")
    try:
        log_activity("system", f"系统错误: {str(e)[:200]}", "system", str(e)[:300], "")
    except Exception:
        pass
