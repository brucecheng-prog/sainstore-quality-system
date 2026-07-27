"""
钉钉企业内部应用推送客户端。

默认使用品质系统应用凭证发送工作通知；如有需要，可通过环境变量覆盖。
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Tuple

import requests


ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
WORK_NOTICE_URL = "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2"

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}


def _get_app_key() -> str:
    return os.environ.get("DINGTALK_APP_KEY", "").strip()


def _get_app_secret() -> str:
    return os.environ.get("DINGTALK_APP_SECRET", "").strip()


def _get_agent_id() -> str:
    return os.environ.get("DINGTALK_AGENT_ID", "").strip()


def is_app_push_configured() -> bool:
    return bool(_get_app_key() and _get_app_secret() and _get_agent_id())


def get_app_push_status(check_auth: bool = False) -> dict[str, object]:
    """Return non-destructive diagnostics for the direct DingTalk app channel.

    ``dws`` is only used for optional person lookup elsewhere.  The actual
    notification path is this app client, so runtime health must report it
    separately instead of treating a missing ``dws`` executable as a global
    push outage.
    """
    status: dict[str, object] = {
        "configured": is_app_push_configured(),
        "auth_ok": None,
        "message": "",
    }
    if not status["configured"]:
        status["message"] = "未配置钉钉应用凭证"
        return status
    if not check_auth:
        status["message"] = "已配置钉钉应用推送"
        return status

    ok, value = get_access_token()
    status["auth_ok"] = ok
    status["message"] = "access_token 获取成功" if ok else value
    return status


def _clean_message_text(title: str, text: str) -> str:
    """把现有 markdown-ish 文本整理成钉钉文本消息。"""
    content = f"{title}\n\n{text or ''}".strip()
    content = re.sub(r"^##+\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\*\*(.*?)\*\*", r"\1", content)
    content = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", content)
    content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", content)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    if len(content) > 5000:
        content = f"{content[:4990].rstrip()}..."
    return content


def _request_access_token() -> Tuple[bool, str]:
    app_key = _get_app_key()
    app_secret = _get_app_secret()
    if not app_key or not app_secret:
        return False, "未配置钉钉应用凭证"

    try:
        response = requests.post(
            ACCESS_TOKEN_URL,
            json={"appKey": app_key, "appSecret": app_secret},
            timeout=20,
        )
        data = response.json()
    except requests.RequestException as exc:
        return False, f"获取 access_token 失败: {exc}"
    except ValueError:
        return False, f"获取 access_token 返回非法响应: HTTP {response.status_code}"

    access_token = data.get("accessToken") or data.get("access_token") or ""
    expire_in = data.get("expireIn") or data.get("expires_in") or 7200
    if response.ok and access_token:
        _TOKEN_CACHE["token"] = access_token
        _TOKEN_CACHE["expires_at"] = time.time() + max(int(expire_in) - 120, 60)
        return True, access_token

    code = data.get("code") or data.get("errcode") or response.status_code
    message = data.get("message") or data.get("errmsg") or "未知错误"
    return False, f"获取 access_token 失败: {code} {message}"


def get_access_token(force_refresh: bool = False) -> Tuple[bool, str]:
    if not force_refresh:
        cached_token = str(_TOKEN_CACHE.get("token") or "")
        cached_expire = float(_TOKEN_CACHE.get("expires_at") or 0.0)
        if cached_token and time.time() < cached_expire:
            return True, cached_token

    with _TOKEN_LOCK:
        if not force_refresh:
            cached_token = str(_TOKEN_CACHE.get("token") or "")
            cached_expire = float(_TOKEN_CACHE.get("expires_at") or 0.0)
            if cached_token and time.time() < cached_expire:
                return True, cached_token
        return _request_access_token()


def send_work_notice(user_id: str, title: str, text: str) -> Tuple[bool, str]:
    """以品质系统应用身份发送工作通知文本消息。"""
    if not user_id:
        return False, "未找到接收人userId"
    if not is_app_push_configured():
        return False, "未配置钉钉应用推送"

    ok, token_or_msg = get_access_token()
    if not ok:
        return False, token_or_msg

    content = _clean_message_text(title, text)
    payload = {
        "agent_id": int(_get_agent_id()),
        "userid_list": user_id,
        "to_all_user": False,
        "msg": {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        },
    }

    for attempt in range(2):
        try:
            response = requests.post(
                f"{WORK_NOTICE_URL}?access_token={token_or_msg}",
                json=payload,
                timeout=20,
            )
            data = response.json()
        except requests.RequestException as exc:
            return False, f"发送工作通知失败: {exc}"
        except ValueError:
            return False, f"发送工作通知返回非法响应: HTTP {response.status_code}"

        errcode = data.get("errcode", 0)
        errmsg = data.get("errmsg", "ok")
        if response.ok and errcode == 0:
            return True, "已通过品质系统应用推送"

        if attempt == 0 and errcode in {40014, 42001, 42002, 42007, 42009}:
            refreshed, token_or_msg = get_access_token(force_refresh=True)
            if refreshed:
                continue
            return False, token_or_msg

        return False, f"发送工作通知失败: {errcode} {errmsg}"

    return False, "发送工作通知失败: 未知错误"
