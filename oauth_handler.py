#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google OAuth 回调服务端处理。

从 Streamlit 脚本中抽离出来，挂载在 Starlette 中间件里，在请求到达 Streamlit
App 之前完成 code→token 交换、用户信息获取和 cookie 设置，彻底解决 Streamlit
脚本重跑/重入导致的 OAuth 登录失败问题。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time as time_module
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests

# ---- 路径常量 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AUTH_FILE = os.path.join(DATA_DIR, "auth.json")
CLIENT_SECRETS_FILE = os.path.join(DATA_DIR, "client_secret.json")

# ---- Cookie / Token 签名密钥 ----
_COOKIE_SECRET = os.environ.get("COOKIE_SECRET")
if not _COOKIE_SECRET:
    _COOKIE_SECRET = secrets.token_urlsafe(32)

# ---- Google OAuth 端点 ----
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# 线程池，用于在中间件 async 环境中执行同步 requests
_oauth_executor = ThreadPoolExecutor(max_workers=4)


def get_redirect_uri():
    """自动检测 redirect_uri。"""
    env_uri = os.environ.get("OAUTH_REDIRECT_URI")
    if env_uri:
        return env_uri

    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base_url:
        return public_base_url

    return "http://localhost:8501"


def load_auth_config():
    """加载授权配置"""
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"authorized_emails": [], "admin_emails": [], "allow_all_google": False}


def is_authorized(email):
    """检查邮箱是否被授权"""
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


def load_client_secrets():
    """加载 Google OAuth 客户端密钥"""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return None
    with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_oauth_config():
    """获取 OAuth 配置"""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}

    secrets = load_client_secrets()
    if secrets:
        web = secrets.get("web", secrets.get("installed", {}))
        return {
            "client_id": web.get("client_id", ""),
            "client_secret": web.get("client_secret", ""),
        }
    return None


def _get_oauth_state(api_secret):
    """生成 OAuth state，基于时间窗口防止 CSRF"""
    window = str(int(time_module.time() / 300))  # 5分钟窗口
    return hashlib.sha256(f"{api_secret}:{window}".encode()).hexdigest()[:32]


def _verify_oauth_state(state, api_secret):
    """验证 state（允许前后5分钟窗口）"""
    for offset in [-1, 0, 1]:
        window = str(int(time_module.time() / 300) + offset)
        expected = hashlib.sha256(f"{api_secret}:{window}".encode()).hexdigest()[:32]
        if state == expected:
            return True
    return False


def _encode_auth_token(email, exp_ts, name=""):
    """加密生成 auth token"""
    secret = _COOKIE_SECRET
    if name:
        payload = f"{email}|{exp_ts}|{name}"
        sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        return f"{payload}|{sig}"
    else:
        payload = f"{email}|{exp_ts}"
        sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        return f"{payload}|{sig}"


def _decode_auth_token(token):
    """解密 auth token"""
    try:
        parts = token.split("|")
        secret = _COOKIE_SECRET
        if len(parts) == 4:
            email, exp_ts, name, sig = parts
            payload = f"{email}|{exp_ts}|{name}"
            expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
            if sig != expected:
                return None, None, ""
            return email, int(exp_ts), name
        elif len(parts) == 3:
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

    print(f"[OAUTH] POST {GOOGLE_TOKEN_URL} "
          f"client_id={config.get('client_id','')[:20]}... "
          f"redirect_uri={redirect_uri} code={code[:12]}...",
          file=__import__('sys').stderr)

    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)

    print(f"[OAUTH] token response status={token_resp.status_code} body={token_resp.text[:500]}",
          file=__import__('sys').stderr)

    if not token_resp.ok:
        try:
            err_payload = token_resp.json()
            err_code = err_payload.get("error", "unknown")
            err_desc = err_payload.get("error_description", token_resp.text)
        except Exception:
            err_code = "unknown"
            err_desc = token_resp.text or "Bad Request"
        friendly = {
            "invalid_grant": ("授权码已过期或已使用（请勿刷新回调页，请重新点击登录按钮）。"
                              f" 当前回调地址为 {redirect_uri}，请确认与 Google Cloud Console 的「已获授权的重定向 URI」完全一致。"),
            "redirect_uri_mismatch": f"回调地址不匹配：当前为 {redirect_uri}",
            "invalid_client": "客户端密钥错误，请检查 client_secret.json",
            "invalid_request": "请求参数错误",
        }.get(err_code, err_desc)
        return None, f"Token 交换失败 [{err_code}]: {friendly}"

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return None, "未能获取 access_token"

    user_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )

    if not user_resp.ok:
        return None, "获取用户信息失败"

    user_info = user_resp.json()
    return user_info, None


def _build_auth_cookie(email, name=""):
    """构建 qs_auth cookie 字符串"""
    exp_ts = int(time_module.time() + 6 * 24 * 3600)
    token = _encode_auth_token(email, exp_ts, name)
    max_age = 6 * 24 * 3600
    return f"qs_auth={token}; Max-Age={max_age}; Path=/; SameSite=Lax"


async def handle_oauth_callback(request):
    """处理 /?code=...&state=... 回调，成功/失败均返回 RedirectResponse。

    返回 None 表示不是 OAuth 回调（由后续中间件/应用处理）。
    """
    if request.url.path != "/":
        return None

    params = dict(request.query_params)
    code = params.get("code", "")
    state = params.get("state", "")
    if not code or not state:
        return None

    config = get_oauth_config()
    if not config:
        return _redirect_with_error("未配置 Google OAuth 客户端密钥")

    api_secret = config["client_secret"][:16]
    if not _verify_oauth_state(state, api_secret):
        return _redirect_with_error("OAuth 安全校验失败（state 不匹配或已过期）")

    redirect_uri = get_redirect_uri()

    loop = __import__('asyncio').get_event_loop()
    user_info, error = await loop.run_in_executor(
        _oauth_executor,
        exchange_code_for_token,
        code,
        redirect_uri,
    )

    if error:
        return _redirect_with_error(error)

    email = user_info.get("email", "")
    name = user_info.get("name", email.split("@")[0] if email else "")

    if not is_authorized(email):
        return _redirect_with_error(
            f"您的 Google 账号 {email} 未被授权访问此系统，请联系管理员 Bruce Cheng（程强）添加授权。"
        )

    # 登录成功：设置 cookie 并重定向到首页
    response = _redirect_with_error(None)
    exp_ts = int(time_module.time() + 6 * 24 * 3600)
    token = _encode_auth_token(email, exp_ts, name)
    max_age = 6 * 24 * 3600
    response.set_cookie(
        key="qs_auth",
        value=token,
        max_age=max_age,
        path="/",
        samesite="lax",
    )
    # 同时清除可能存在的 qs_logged_out
    response.set_cookie(
        key="qs_logged_out",
        value="",
        max_age=0,
        path="/",
        samesite="lax",
    )

    # 记录登录日志（ best effort ）
    try:
        import database as db
        db.log_activity(email, "登录成功", "login", "Google OAuth 登录", "首页")
    except Exception:
        pass

    return response


def _redirect_with_error(error_msg: str | None):
    """重定向到首页，可选携带 oauth_error 查询参数。"""
    import urllib.parse
    if error_msg:
        qs = urllib.parse.urlencode({"oauth_error": error_msg})
        url = f"/?{qs}"
    else:
        # Tell the Streamlit side that the server has completed a fresh OAuth
        # login.  It must discard any in-memory logout marker from a prior
        # explicit logout before checking the new qs_auth cookie.
        url = "/?oauth_login=1"
    from starlette.responses import RedirectResponse
    return RedirectResponse(url=url, status_code=302)
