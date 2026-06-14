"""
品质系统管理平台 - 主入口 v2.0.0
Google OAuth 2.0 授权登录 | 本地开发免登录 | Cookie 持久化6天
"""

import streamlit as st
import streamlit.components.v1 as components
import os
import json
import hashlib
import secrets
import requests
import time as time_module
from datetime import datetime, timedelta
from database import log_activity

# Logo 路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
DATA_DIR = os.path.join(BASE_DIR, "data")
AUTH_FILE = os.path.join(DATA_DIR, "auth.json")
CLIENT_SECRETS_FILE = os.path.join(DATA_DIR, "client_secret.json")

# Google OAuth 端点
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# ---- 页面配置 ----
st.set_page_config(
    page_title="品质系统管理平台",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ---- 工具函数 ----
def get_redirect_uri():
    """
    自动检测 redirect_uri。
    优先级：环境变量 > streamlit server 配置 > 请求头检测 > localhost 默认
    """
    # 1. 环境变量（优先级最高）
    env_uri = os.environ.get("OAUTH_REDIRECT_URI")
    if env_uri:
        return env_uri

    # 2. 从 Streamlit server config 读取
    try:
        from streamlit.web.server.server_util import get_server_address
        server_addr = get_server_address()
        if server_addr:
            # 检查是否是默认地址，如果是则尝试从请求头获取真实域名
            pass
    except Exception:
        pass

    # 3. 从请求头检测（处理隧道/反向代理场景）
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers:
            # Cloudflare Tunnel / Ngrok 等会设置 X-Forwarded-Host
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
    HF Space: 从环境变量读取（Secrets）
    本地开发: 从文件读取（client_secret.json）
    """
    # 1. 优先：环境变量（HF Space Secrets）
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

    # 如果已经认证，直接返回
    if st.session_state.authenticated:
        return

    # 尝试从 cookie 恢复登录
    _try_cookie_login()

    # 本地开发环境：直接免登录
    if not is_production():
        _local_dev_auto_login()


def _try_cookie_login():
    """从浏览器 cookie 恢复登录会话（6天有效期）"""
    try:
        cookies = st.context.cookies
        auth_token = cookies.get("qs_auth", "")
        if auth_token:
            email, exp_ts = _decode_auth_token(auth_token)
            if email and exp_ts and time_module.time() < exp_ts:
                st.session_state.authenticated = True
                st.session_state.user_email = email
                st.session_state.user_name = email.split("@")[0]
                st.session_state.is_admin = is_admin(email)
                return
    except Exception:
        pass


def _local_dev_auto_login():
    """本地开发环境自动登录（开发者身份）"""
    dev_email = "bruce.cheng@sainstore.com"
    st.session_state.authenticated = True
    st.session_state.user_email = dev_email
    st.session_state.user_name = "Bruce Cheng (开发者)"
    st.session_state.is_admin = True


def _set_auth_cookie(email):
    """设置登录 cookie（6天有效期）"""
    exp_ts = int(time_module.time() + 6 * 24 * 3600)  # 6天
    token = _encode_auth_token(email, exp_ts)
    # 使用 JavaScript 设置 cookie
    js = f"""
    <script>
    document.cookie = "qs_auth={token}; max-age={6 * 24 * 3600}; path=/; SameSite=Lax";
    </script>
    """
    components.html(js, height=0)


def _clear_auth_cookie():
    """清除登录 cookie"""
    js = """
    <script>
    document.cookie = "qs_auth=; max-age=0; path=/";
    </script>
    """
    components.html(js, height=0)


def _encode_auth_token(email, exp_ts):
    """加密生成 auth token"""
    secret = os.environ.get("COOKIE_SECRET", "qs-platform-secret-key-2026")
    payload = f"{email}|{exp_ts}"
    sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
    return f"{payload}|{sig}"


def _decode_auth_token(token):
    """解密 auth token，返回 (email, exp_ts) 或 (None, None)"""
    try:
        parts = token.split("|")
        if len(parts) != 3:
            return None, None
        email, exp_ts, sig = parts
        secret = os.environ.get("COOKIE_SECRET", "qs-platform-secret-key-2026")
        payload = f"{email}|{exp_ts}"
        expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        if sig != expected:
            return None, None
        return email, int(exp_ts)
    except Exception:
        return None, None


def exchange_code_for_token(code, redirect_uri):
    """用授权码换取 token，并获取用户信息"""
    config = get_oauth_config()
    if not config:
        return None, "未配置 Google OAuth 客户端密钥 (client_secret.json)"

    # 交换 token
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)

    if not token_resp.ok:
        return None, f"Token 交换失败: {token_resp.json().get('error_description', token_resp.text)}"

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


def is_production():
    """判断是否在生产环境（HF Space）"""
    return bool(os.environ.get("SPACE_HOST", ""))


# ---- 管理面板 ----
def admin_panel():
    """管理员面板：管理授权用户（仅本地开发环境可见）"""
    config = load_auth_config()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ 管理员面板")

    with st.sidebar.expander("👥 授权用户管理", expanded=False):
        st.caption(f"当前已授权 {len(config.get('authorized_emails', []))} 个账号")

        # 逐一显示已授权用户
        for email in config.get("authorized_emails", []):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.code(email, language=None)
            with col2:
                if st.button("🗑️", key=f"del_{email}", help=f"移除 {email}"):
                    config["authorized_emails"].remove(email)
                    save_auth_config(config)
                    st.rerun()

        # 添加新用户
        new_email = st.text_input("添加 Google 邮箱", placeholder="user@gmail.com", key="admin_add_email")
        if st.button("➕ 添加授权", type="primary", use_container_width=True):
            if new_email and "@" in new_email:
                if new_email.lower() not in [e.lower() for e in config.get("authorized_emails", [])]:
                    config["authorized_emails"].append(new_email.lower())
                    save_auth_config(config)
                    st.success(f"已添加 {new_email}")
                    st.rerun()
                else:
                    st.warning("该邮箱已在列表中")
            else:
                st.error("请输入有效的邮箱地址")

        # 全局开关
        st.markdown("---")
        st.caption("⚠️ 危险操作")
        allow_all = st.toggle(
            "允许所有 Google 账号登录",
            value=config.get("allow_all_google", False),
            help="开启后任何 Google 账号都可以登录，无需逐一添加"
        )
        if allow_all != config.get("allow_all_google", False):
            config["allow_all_google"] = allow_all
            save_auth_config(config)
            st.rerun()

    with st.sidebar.expander("🔑 OAuth 配置状态", expanded=False):
        secrets = load_client_secrets()
        if secrets:
            st.success("✅ client_secret.json 已配置")
            web = secrets.get("web", secrets.get("installed", {}))
            st.caption(f"Client ID: {web.get('client_id', 'N/A')[:20]}...")
        else:
            st.error("❌ 未找到 client_secret.json")
            st.caption(f"请将文件放置于: `{CLIENT_SECRETS_FILE}`")

        st.caption(f"Redirect URI: `{get_redirect_uri()}`")


# ---- 登录页面 ----
def login_page():
    """Google OAuth 登录页面"""
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)

        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=180)
        else:
            st.markdown("# 🔬")

        st.markdown("## 品质系统管理平台")
        st.markdown("*Quality System Management Platform*")
        st.markdown("---")

        # ---- 检查是否是 OAuth 回调 ----
        query_params = st.query_params

        if "code" in query_params and "state" in query_params:
            code = query_params["code"]
            state = query_params["state"]

            config = get_oauth_config()
            api_secret = config["client_secret"][:16] if config else ""
            expected_session = st.session_state.get("oauth_state", "")
            if not _verify_oauth_state(state, api_secret) and state != expected_session:
                st.warning("🔄 正在重新验证...")
                st.query_params.clear()
                st.rerun()

            # 交换 token
            redirect_uri = get_redirect_uri()
            with st.spinner("🔐 Google 验证中..."):
                user_info, error = exchange_code_for_token(code, redirect_uri)

            if error:
                st.error(f"❌ 登录失败: {error}")
                st.query_params.clear()
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

            # 设置 6 天有效期 cookie
            _set_auth_cookie(email)

            # 记录登录日志
            log_activity(email, "登录成功", "login", f"Google OAuth 登录", "首页")

            # 清除 URL 参数
            st.query_params.clear()
            st.rerun()

        elif "error" in query_params:
            st.error(f"❌ Google 登录被取消或失败: {query_params.get('error', 'unknown')}")
            st.query_params.clear()
            _render_login_button()

        else:
            # 正常登录页面
            _render_login_button()

        st.markdown("---")
        st.caption("© 2026 SainStore Inc. | Developed by Bruce Cheng 程强")
        st.caption("使用 Google 账号登录，首次使用请联系管理员添加授权。")


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

def _render_login_button():
    """渲染 Google 登录按钮"""
    config = get_oauth_config()

    if not config:
        st.warning("### ⚠️ Google OAuth 未配置")
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

> 📌 部署公网后需要回来添加生产环境地址
        """)
        return

    # 生成 state 防止 CSRF
    api_secret = config["client_secret"][:16]
    oauth_state = _get_oauth_state(api_secret)
    st.session_state.oauth_state = oauth_state

    redirect_uri = get_redirect_uri()
    client_id = config["client_id"]

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

    # 登录 UI
    st.markdown("### 🔐 Google 账号登录")
    st.caption("请使用您的 Google 账号进行授权登录")

    st.markdown(f"""
    <div style="text-align: center; margin: 30px 0;">
        <a href="{auth_url}" target="_self"
           style="display: inline-flex; align-items: center; gap: 12px;
                  background: #ffffff; color: #3c4043; border: 1px solid #dadce0;
                  border-radius: 8px; padding: 14px 32px;
                  font-size: 16px; font-weight: 500; text-decoration: none;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                  transition: box-shadow 0.2s, transform 0.1s;">
            <img src="https://www.google.com/favicon.ico" width="20" height="20"
                 style="vertical-align: middle;">
            Sign in with Google
        </a>
    </div>
    <div style="text-align: center; font-size: 13px; color: #888; margin-top: 8px;">
        点击上方按钮，跳转至 Google 进行身份验证
    </div>
    """, unsafe_allow_html=True)


# ---- 主应用 ----
def main_app():
    """主应用入口"""
    # 侧边栏顶部显示 Logo
    if os.path.exists(LOGO_PATH):
        st.logo(LOGO_PATH, size="large")

    # 侧边栏用户信息
    with st.sidebar:
        user_pic = st.session_state.get("user_picture", "")
        user_name = st.session_state.get("user_name", "用户")
        user_email = st.session_state.get("user_email", "")

        if user_pic:
            col_a, col_b = st.columns([1, 3])
            with col_a:
                st.image(user_pic, width=40)
            with col_b:
                st.markdown(f"**{user_name}**")
                st.caption(user_email)
        else:
            st.markdown(f"👤 **{user_name}**")
            st.caption(user_email)

        st.markdown("---")

        # 退出登录
        if st.button("🚪 退出登录", use_container_width=True):
            email = st.session_state.get("user_email", "")
            log_activity(email, "退出登录", "login", "用户主动退出", "首页")
            _clear_auth_cookie()
            for key in ["authenticated", "user_email", "user_name",
                        "user_picture", "is_admin", "oauth_state", "_login_checked"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

        st.markdown("---")

    # 管理员面板
    # 管理员面板：仅本地开发环境显示
    if st.session_state.get("is_admin", False) and not is_production():
        admin_panel()

    # 页面导航
    pages = {
        "🏠 首页": [
            st.Page("app.py", title="数据看板", icon="📊"),
        ],
        "🔬 实验室管理": [
            st.Page("_pages/lab_usage.py", title="使用登记", icon="📋"),
            st.Page("_pages/lab_borrow.py", title="借用归还", icon="📤"),
            st.Page("_pages/lab_equipment.py", title="设备台账", icon="🔧"),
            st.Page("_pages/lab_maintenance.py", title="维护记录", icon="🔨"),
        ],
        "📄 品质管理": [
            st.Page("_pages/qc_report.py", title="检验报告", icon="📄"),
            st.Page("_pages/qc_sample.py", title="样品管理", icon="📦"),
            st.Page("_pages/qc_change.py", title="变更管理", icon="📝"),
        ],
        # 📊 数据智能分析（仅本地开发环境，公网不加载）
        "📊 数据智能分析": []  if is_production() else [
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_summary.py", title="数据汇总", icon="📈"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_sku.py", title="SKU分析", icon="🔍"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_bg.py", title="BG分析", icon="🏢"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_bu.py", title="BU分析", icon="📂"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_brand.py", title="品牌分析", icon="🏷️"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_supplier.py", title="供应商分析", icon="🚚"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_pareto.py", title="帕累托分析", icon="📐"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_search.py", title="搜索中心", icon="🔎"),
            st.Page("/Users/bruce/Desktop/Workbuddy_Bruce/品质系统_数据分析/dashboard/_pages/qic_export.py", title="导出数据", icon="📤"),
        ],
        "ℹ️ 关于": [
            st.Page("_pages/about.py", title="版本信息", icon="ℹ️"),
        ],
    }

    # 仅本地开发环境显示活动日志
    if not is_production():
        pages["📊 系统监控"] = [
            st.Page("_pages/log_viewer.py", title="活动日志", icon="📈"),
            st.Page("_pages/changelog.py", title="版本变动", icon="📝"),
        ]

    pg = st.navigation(pages)
    pg.run()

    # 记录页面访问（页面变化时记录一次）
    try:
        ctx = __import__('streamlit.runtime.scriptrunner.script_run_context', fromlist=['get_script_run_ctx']).get_script_run_ctx()
        current_page = ctx.page_script_hash if ctx else ''
    except Exception:
        current_page = ''

    if current_page and current_page != st.session_state.get("_last_page_hash", ""):
        st.session_state["_last_page_hash"] = current_page
        user = st.session_state.get("user_email", "unknown")
        log_activity(user, "浏览页面", "page_view", "", "")


# ==================== 入口（带稳定性保护） ====================
try:
    init_session()

    if st.session_state.authenticated:
        main_app()
    else:
        login_page()
except Exception as e:
    st.error(f"⚠️ 系统遇到意外错误，请刷新页面重试。")
    st.caption(f"错误详情（仅开发者可见）: {str(e)[:500]}")
    # 记录错误
    try:
        log_activity("system", f"系统错误: {str(e)[:200]}", "system", str(e)[:300], "")
    except Exception:
        pass
