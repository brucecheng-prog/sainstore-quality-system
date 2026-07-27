#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一入口：
- Streamlit 主系统继续跑在 8501
- 手机拍照页 / 报告列表页 / 照片 API 也挂到同一个 8501

这样二维码、钉钉入口、电脑端「获取链接 / 打开」全部只走 8501。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import socket
import time as time_module
import uuid
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib.metadata import version as pkg_version

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from streamlit.web.server.starlette import App

import database as db
import oauth_handler
import online_report_db as odb
from nas_client import check_connection, download_file, upload_file
from photo_api import (
    CAPTURE_CATS,
    TOKEN,
    CACHE_DIR,
    NAS_PHOTO_ROOT,
    _CAPTURE_ERR,
    _CAPTURE_SW,
    _CAPTURE_TMPL,
    _build_legacy_meta,
    _build_temp_meta,
    _escape_html,
    _ext_from_ct,
    _is_temp_key,
    _meta_text,
    _parse_multipart,
    _reports_page,
    _resolve_report,
    _save_local,
)


def _ensure_supported_streamlit() -> None:
    raw = pkg_version("streamlit")
    parts = tuple(int(p) for p in raw.split(".")[:2])
    if parts < (1, 59):
        raise RuntimeError(
            f"当前 Streamlit 版本过低: {raw}。"
            "统一 8501 入口要求 >= 1.59.0，请先在 Win 服务器虚拟环境升级 streamlit。"
        )


_ensure_supported_streamlit()


def _cors_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
    }
    if extra:
        headers.update(extra)
    return headers


def _allowed_origins() -> list[str]:
    """Return explicit browser origins approved for QMS APIs."""
    raw = os.environ.get(
        "QMS_ALLOWED_ORIGINS",
        "http://localhost:8501,http://192.168.61.16:8501,http://219.131.130.146:8501",
    )
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _request_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8501"
    return f"{proto}://{host}"


def _check_token(request: Request) -> bool:
    if not TOKEN:
        return True
    tok_url = request.query_params.get("token", "")
    tok_hdr = request.headers.get("x-photo-token", "")
    return tok_url == TOKEN or tok_hdr == TOKEN


def _parse_int(value: str | None) -> int | None:
    if value and str(value).isdigit():
        return int(value)
    return None


def _json(payload: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers=_cors_headers())


def _html(html: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=status_code, headers=_cors_headers())


def _is_dingtalk(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    return "dingtalk" in ua or "aliapp" in ua


async def reports_page(request: Request) -> HTMLResponse:
    return _html(_reports_page())


async def capture_page(request: Request) -> HTMLResponse:
    key = request.query_params.get("key", "")
    rid = _parse_int(request.query_params.get("rid"))
    no = request.query_params.get("no", "")
    by = request.query_params.get("by", "")
    cat = request.query_params.get("cat", "")
    mode = request.query_params.get("mode", "")
    legacy_label = request.query_params.get("label", "")

    if mode == "legacy" and not key:
        key = "tmp_old_" + re.sub(r"[^\\w\\u4e00-\\u9fff-]+", "-", legacy_label or "未命名旧品")[:48] + "_" + uuid.uuid4().hex[:8]

    meta = _resolve_report(key, rid, no)
    if not meta and _is_temp_key(key):
        meta = _build_legacy_meta(key, legacy_label) if mode == "legacy" or key.startswith("tmp_old_") else _build_temp_meta(key)
    if not meta:
        return _html(_CAPTURE_ERR, 404)

    rk = str(key or "").strip() if _is_temp_key(key) else ("r" + str(meta["id"]))
    html = (
        _CAPTURE_TMPL.replace("__KEY__", rk)
        .replace("__CATS__", json.dumps(CAPTURE_CATS, ensure_ascii=False))
        .replace("__TOKEN__", json.dumps(TOKEN))
        .replace("__META__", _escape_html(_meta_text(meta)))
        .replace("__PRESET__", json.dumps(cat))
        .replace("__BY__", _escape_html(by))
        .replace("__MODE__", _escape_html(mode))
    )
    return _html(html)


async def healthz(request: Request) -> JSONResponse:
    """Operational health check that never exposes credentials or business data."""
    db_ok = False
    try:
        conn = db.get_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return _json(
        {
            "ok": db_ok,
            "service": "qms",
            "environment": os.environ.get("QMS_ENVIRONMENT", "unspecified"),
            "instance": os.environ.get("QMS_INSTANCE_NAME", "unspecified"),
            "photo_token_configured": bool(TOKEN),
            "cookie_secret_configured": bool(os.environ.get("COOKIE_SECRET")),
            "allowed_origins": len(_allowed_origins()),
        },
        status_code=200 if db_ok else 503,
    )


async def capture_sw(request: Request) -> Response:
    return Response(
        _CAPTURE_SW,
        media_type="text/javascript; charset=utf-8",
        headers=_cors_headers(),
    )


async def api_reports(request: Request) -> JSONResponse:
    try:
        rp = None
        try:
            rp = db._resolve_remote_audit_db()
        except Exception:
            rp = None
        if rp:
            conn = sqlite3.connect(f"file:{rp}?mode=ro", uri=True, timeout=10)
        else:
            conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, report_no, product_name, supplier, status FROM online_reports ORDER BY id DESC LIMIT 200"
        ).fetchall()
        conn.close()
        reports = [dict(r) for r in rows]
    except Exception:
        reports = []
    return _json({"ok": True, "reports": reports})


async def api_translate(request: Request) -> JSONResponse:
    """Best-effort server-side Chinese -> English translation for uncommon phrases."""
    text = (request.query_params.get("q") or "").strip()
    if not text:
        return _json({"ok": False, "translated": "", "msg": "empty text"}, 400)
    try:
        query = urllib.parse.urlencode({
            "client": "gtx", "sl": "zh-CN", "tl": "en", "dt": "t", "q": text,
        })
        url = "https://translate.googleapis.com/translate_a/single?" + query
        with urllib.request.urlopen(url, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        translated = "".join(
            str(item[0]) for item in (payload[0] or [])
            if isinstance(item, list) and item and item[0]
        ).strip()
        if translated:
            return _json({"ok": True, "translated": translated})
    except Exception:
        pass
    return _json({"ok": False, "translated": "", "msg": "translation service unavailable"}, 503)


async def api_photo_list(request: Request) -> JSONResponse:
    if not _check_token(request):
        return _json({"ok": False, "msg": "token 无效"}, 403)
    rk = request.query_params.get("report_key", "")
    photos = odb.list_photos(report_key=rk) if rk else []
    base = _request_base(request)
    out = [
        {
            "id": p["id"],
            "category": p["category"],
            "defect_index": p["defect_index"],
            "caption": p["caption"],
            "archive_only": int(p.get("archive_only") or 0),
            "url": f"{base}/api/photo/{p['id']}",
        }
        for p in photos
    ]
    return _json({"ok": True, "photos": out})


async def api_photo_consistency(request: Request) -> JSONResponse:
    if not _check_token(request):
        return _json({"ok": False, "msg": "token 无效"}, 403)
    rk = request.query_params.get("report_key", "")
    reconcile = request.query_params.get("reconcile", "0") == "1"
    photos = odb.list_photos(report_key=rk) if rk else []
    issues: list[str] = []
    reconciled: list[int] = []
    try:
        from nas_client import check_connection, list_files
    except Exception:
        check_connection = None
        list_files = None

    # 只有确认 NAS 当前可连通时才允许自动清理，避免临时断网把整份报告图片误删。
    if reconcile and check_connection:
        available, detail = check_connection()
        if not available:
            return _json({"ok": False, "transient": True, "msg": f"NAS 暂不可用，未执行自动清理：{detail}"}, 503)

    for p in photos:
        nas_path = p.get("nas_path")
        if not nas_path:
            issues.append(f"照片#{p['id']}（{p.get('category')}）尚未上传到 NAS")
            continue
        if list_files:
            try:
                folder = os.path.dirname(nas_path)
                name = os.path.basename(nas_path)
                lst = list_files(folder)
                names = [f.get("name") for f in lst] if isinstance(lst, list) else []
                if name not in names:
                    issues.append(f"照片#{p['id']}（{p.get('category')}）NAS 文件缺失：{name}")
                    if reconcile:
                        ok, _ = odb.reconcile_missing_nas_photo(p["id"], by="system:nas_reconcile")
                        if ok:
                            reconciled.append(int(p["id"]))
            except Exception as exc:
                issues.append(f"照片#{p['id']} NAS 校验异常：{exc}")

    return _json(
        {
            "ok": True,
            "consistent": len(issues) == 0,
            "issues": issues,
            "total": len(photos),
            "reconciled": reconciled,
        }
    )


def _photo_file_response(local_path: str | None, nas_path: str | None) -> Response:
    data = None
    ctype = "image/jpeg"
    if local_path and os.path.exists(local_path):
        with open(local_path, "rb") as fh:
            data = fh.read()
        ctype = mimetypes.guess_type(local_path)[0] or "image/jpeg"
    elif nas_path:
        try:
            data, _ = download_file(nas_path)
        except Exception:
            data = None
    if data is None:
        return Response(status_code=404, headers=_cors_headers())
    return Response(
        data,
        media_type=ctype,
        headers=_cors_headers({"Cache-Control": "public, max-age=3600"}),
    )


async def api_photo_item(request: Request) -> Response:
    pid = _parse_int(request.path_params.get("pid"))
    if pid is None:
        return _json({"ok": False, "msg": "bad id"}, 400)

    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())

    if request.method == "GET":
        ph = odb.get_photo(pid)
        if not ph or ph.get("deleted"):
            return _json({"ok": False, "msg": "不存在或已删除"}, 404)
        return _photo_file_response(ph.get("local_path"), ph.get("nas_path"))

    if request.method == "DELETE":
        if not _check_token(request):
            return _json({"ok": False, "msg": "token 无效"}, 403)
        by = request.query_params.get("by", "")
        ok, msg = odb.soft_delete_photo(pid, by=by)
        return _json({"ok": ok, "msg": msg}, 200 if ok else 400)

    return _json({"ok": False, "msg": "not found"}, 404)


async def api_photo_upload(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())

    if not _check_token(request):
        return _json({"ok": False, "msg": "token 无效"}, 403)

    ctype = request.headers.get("content-type", "")
    if "multipart/form-data" not in ctype:
        return _json({"ok": False, "msg": "需 multipart/form-data"}, 400)

    boundary = ctype.split("boundary=")[-1].strip().strip('"')
    body = await request.body()
    parts = _parse_multipart(body, boundary)

    fields: dict[str, str] = {}
    file_part = None
    for name, filename, pctype, content in parts:
        if name == "file" and filename:
            file_part = (filename, pctype, content)
        else:
            fields[name] = content.decode("utf-8", "replace")

    if not file_part:
        return _json({"ok": False, "msg": "缺少文件"}, 400)

    fname, fctype, fdata = file_part
    report_key = fields.get("report_key", "")
    category = fields.get("category", "other")
    defect_index = _parse_int(fields.get("defect_index"))
    # 由服务端统一分配全报告序号，避免不同照片类别各自从 1 开始而覆盖文件。
    seq = odb.next_photo_seq(report_key)
    caption = fields.get("caption", "")
    created_by = fields.get("created_by", "")

    # ── 检测旧品模式：旧品非缺陷照片仅存档 NAS，不进入报告 PDF ──
    _archive_only = 0
    _mode_param = (fields.get("mode", "") or "").strip().lower()
    if report_key.startswith("r"):
        try:
            _rid_int = int(report_key[1:])
            _or = odb.get_online_report(_rid_int)
            if _or:
                _d = json.loads(_or.get("data_json", "{}") or "{}") if isinstance(_or.get("data_json"), str) else (_or.get("data_json") or {})
                _basic = _d.get("basic", {}) or {}
                if str(_basic.get("productMode", "") or "").lower() in ("old", "旧品"):
                    # 缺陷照片仍然入报告；其余仅存档
                    if category not in ("defect",):
                        _archive_only = 1
        except Exception:
            pass
    # mode 请求参数兜底（二维码已编码产品模式，即使报告尚未保存也能正确判定）
    if not _archive_only and _mode_param == "old" and category not in ("defect",):
        _archive_only = 1

    if not report_key:
        return _json({"ok": False, "msg": "缺少 report_key"}, 400)

    ext = os.path.splitext(fname)[1].lower() or _ext_from_ct(fctype)
    storage_key = odb.storage_key_for_report_key(report_key)
    nas_folder = odb.get_report_nas_photo_folder(report_key)
    if not nas_folder:
        nas_folder = f"{NAS_PHOTO_ROOT}/{storage_key}"
    folder_name = os.path.basename(nas_folder.rstrip("/")) or storage_key
    safe_name = f"{folder_name}_{seq:02d}{ext}".replace("/", "_")
    local_path = _save_local(safe_name, fdata)

    import hashlib

    sha = hashlib.sha256(fdata).hexdigest()
    nas_path = None
    try:
        ok_nas, _ = check_connection()
        if ok_nas:
            ok_up, uploaded_path = upload_file(nas_folder, safe_name, fdata)
            if ok_up:
                nas_path = uploaded_path
    except Exception:
        nas_path = None

    # ── 幂等去重：同一报告内相同 sha256 的照片只保留一条，避免重试/重复拍照产生重复 ──
    _existing = odb.find_photo_by_sha(report_key, sha)
    if _existing:
        _pid = _existing["id"]
        if nas_path and not _existing.get("nas_path"):
            try:
                odb.set_photo_nas_path(_pid, nas_path)
            except Exception:
                pass
        return _json(
            {
                "ok": True,
                "photo_id": _pid,
                "url": f"{_request_base(request)}/api/photo/{_pid}",
                "nas": bool(nas_path or _existing.get("nas_path")),
                "dup": True,
            }
        )

    pid = odb.add_photo(
        report_key=report_key,
        category=category,
        filename=safe_name,
        local_path=local_path,
        nas_path=nas_path,
        sha256=sha,
        caption=caption,
        seq=seq,
        defect_index=defect_index,
        created_by=created_by,
        archive_only=_archive_only,
    )
    odb.add_audit(
        created_by or "system",
        "upload_photo",
        "report_photo",
        str(pid),
        f"类别={category} 文件={safe_name} NAS={'是' if nas_path else '否'}",
    )
    return _json(
        {
            "ok": True,
            "photo_id": pid,
            "url": f"{_request_base(request)}/api/photo/{pid}",
            "nas": bool(nas_path),
        }
    )


async def api_export_pdf(request: Request) -> Response:
    """在线报告导出PDF（直通API，绕开Streamlit组件值机制，解决公网/内网setComponentValue不生效问题）。"""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())

    try:
        raw = await request.body()
        payload = json.loads(raw) if raw else {}
    except Exception:
        return _json({"ok": False, "msg": "无效JSON"}, 400)

    data = payload.get("data") or {}
    rid = payload.get("report_id")
    # 从 query_params 兜底（兼容GET测试）
    if not rid:
        rid = _parse_int(request.query_params.get("rid"))

    import online_report_pdf as opdf

    # 0. 检查 PDF 引擎
    ok, msg = opdf.is_pdf_available()
    if not ok:
        return _json({"ok": False, "msg": f"PDF引擎未就绪: {msg}"}, 503)

    # 1. 确保 draft 记录存在，拿到 report_no
    report_no = payload.get("report_no") or data.get("repno")
    if not rid or not report_no:
        # 尝试从 session_data 中推断——无则报错要求前端先保存草稿
        return _json({"ok": False, "msg": "缺少报告ID或编号，请先保存草稿"}, 400)

    # 2. 如果有数据就更新 draft
    if data and rid:
        try:
            odb.update_draft(rid, data)
        except Exception:
            pass  # 更新失败不阻断导出

    # 3. 生成 PDF（Playwright 同步 API 不能在 asyncio 循环内调用，必须丢到线程池）
    data["repno"] = report_no
    data["_draft_export"] = True

    def _gen_pdf():
        return opdf.render_report_pdf(data, report_no=report_no)

    try:
        loop = __import__("asyncio").get_running_loop()
        pdf_ok, pdf_result = await loop.run_in_executor(ThreadPoolExecutor(max_workers=1), _gen_pdf)
    except RuntimeError:
        # 不在 asyncio 循环中（如测试），直接调用
        pdf_ok, pdf_result = _gen_pdf()
    except Exception as gen_exc:
        import traceback as _tb
        _detail = str(gen_exc) or type(gen_exc).__name__
        _log_path = os.path.join(getattr(opdf, 'PDF_DIR', 'data'), 'pdf_error.log')
        try:
            with open(_log_path, 'a', encoding='utf-8') as _lf:
                _lf.write(f"[{datetime.now().isoformat()}] PDF_GEN_EXCEPTION: {_detail}\n{_tb.format_exc()}\n---\n")
        except Exception: pass
        return _json({"ok": False, "msg": f"PDF生成异常: {_detail}"}, 500)

    if not pdf_ok:
        return _json({"ok": False, "msg": f"PDF生成失败: {pdf_result}"}, 500)

    # 4. 返回 PDF 文件下载
    import os as _os
    pdf_path = pdf_result  # 成功时 path 是文件路径
    _send_log_path = os.path.join(getattr(opdf, 'PDF_DIR', 'data'), 'pdf_render.log')
    def _slog(msg):
        try:
            with open(_send_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] SEND: {msg}\n")
        except Exception: pass

    if _os.path.exists(pdf_path):
        _slog(f"文件存在: {pdf_path} ({_os.path.getsize(pdf_path)} bytes)")
        # 用报告名称作为文件名（优先），无则回退到编号
        _basic = (data.get("basic") or {}) if isinstance(data, dict) else {}
        _title = str(_basic.get("title") or "").strip()
        import re as _re
        if _title:
            _safe = _re.sub(r'[\\/:*?"<>|]+', "-", _title)[:80].strip(" .-") or report_no
            fname = f"{_safe}.pdf"
        else:
            fname = f"DRAFT_{report_no}.pdf"
        # HTTP 头只支持 Latin-1，中文文件名必须编码（RFC 5987）
        import urllib.parse as _up
        if all(ord(c) < 128 for c in fname):
            _disp = f'attachment; filename="{fname}"'
        else:
            _disp = f"attachment; filename=\"{report_no}.pdf\"; filename*={_up.quote(fname.encode('utf-8'), safe='')}"
        _slog(f"文件名: {fname}")
        try:
            with open(pdf_path, "rb") as fh:
                pdf_bytes = fh.read()
            _slog(f"读取到 {len(pdf_bytes)} bytes")
            from starlette.responses import Response
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers=_cors_headers({
                    "Content-Disposition": _disp,
                    "Content-Length": str(len(pdf_bytes)),
                }),
            )
        except Exception as send_err:
            _slog(f"发送异常: {type(send_err).__name__}: {send_err}")
            import traceback as _tb2
            _slog(_tb2.format_exc())
            return _json({"ok": False, "msg": f"PDF文件发送失败: {send_err}"}, 500)

    _slog("文件不存在")
    return _json({"ok": False, "msg": "PDF文件不存在"}, 500)


def _lookup_display_name_lan(email: str) -> str:
    """根据邮箱前缀查找中文显示名（复用 quality_users 名单）。"""
    try:
        users = db.get_quality_users_list()
        if not users:
            return ""
        prefix = (email.split("@")[0] or "").strip().lower()
        if not prefix:
            return ""
        for u in users:
            s = str(u).strip() if u else ""
            if not s:
                continue
            sl = s.lower()
            if sl.startswith(prefix) and len(s) > len(prefix):
                name_part = s[len(prefix):].strip()
                if name_part and any(ord(c) > 127 for c in name_part):
                    return name_part
    except Exception:
        pass
    return ""


async def api_lan_login(request: Request) -> Response:
    """局域网共享密码登录：在 Starlette 层直接设置 HTTP cookie。

    原因：Streamlit 脚本内通过 CookieManager / st.html 写 cookie 在公网 HTTP
    部署下组件经常 CookiesNotReady，且紧跟 st.rerun() 时 JS 来不及执行，
    导致刷新后丢失登录态。改为服务端 Set-Cookie 后，刷新即可从请求头恢复。
    """
    import urllib.parse

    try:
        form = await request.form()
        email = (form.get("email") or "").strip().lower()
        password = (form.get("password") or "").strip()
        redirect = (form.get("redirect") or "/").strip()
    except Exception as exc:
        return _json({"ok": False, "msg": f"表单解析失败: {exc}"}, 400)

    if not redirect.startswith("/"):
        redirect = "/"

    allowed_domain = (os.environ.get("LAN_ALLOWED_DOMAIN") or "sainstore.com").strip().lower()
    expected_password = os.environ.get("LAN_ACCESS_PASSWORD", "").strip()

    error = None
    if not email or "@" not in email:
        error = "请输入有效的公司邮箱。"
    elif allowed_domain and not email.endswith("@" + allowed_domain) and not oauth_handler.is_authorized(email):
        error = f"仅允许 `{allowed_domain}` 公司邮箱访问。"
    elif not expected_password:
        error = "局域网访问密码尚未配置，请联系管理员。"
    elif not password:
        error = "请输入访问密码。"
    elif password != expected_password:
        error = "访问密码不正确。"

    if error:
        return RedirectResponse(
            url=f"/?lan_error={urllib.parse.quote(error)}",
            status_code=302,
        )

    # 解析显示名：token 中携带 ASCII 安全的邮箱前缀（避免 Set-Cookie 编码问题），
    # 中文显示名由 _try_cookie_login 从 quality_users 表二次查库补齐。
    _final_name = (email.split("@")[0] or "").strip()

    exp_ts = int(time_module.time() + 6 * 24 * 3600)
    token = oauth_handler._encode_auth_token(email, exp_ts, name=_final_name)
    max_age = 6 * 24 * 3600

    response = RedirectResponse(url=redirect, status_code=302)
    response.set_cookie(key="qs_auth", value=token, max_age=max_age, path="/", samesite="lax")
    # 清除可能存在的已注销标记
    response.set_cookie(key="qs_logged_out", value="", max_age=0, path="/", samesite="lax")

    # 记录登录日志（best effort）
    try:
        db.log_activity(email, "登录成功", "login", "局域网共享密码登录", "首页")
    except Exception:
        pass

    return response


CUSTOM_ROUTES = [
    Route("/healthz", healthz, methods=["GET"]),
    Route("/reports", reports_page, methods=["GET"]),
    Route("/capture", capture_page, methods=["GET"]),
    Route("/capture-sw.js", capture_sw, methods=["GET"]),
    Route("/api/lan-login", api_lan_login, methods=["POST"]),
    Route("/api/reports", api_reports, methods=["GET"]),
    Route("/api/translate", api_translate, methods=["GET"]),
    Route("/api/photo/list", api_photo_list, methods=["GET"]),
    Route("/api/photo/consistency", api_photo_consistency, methods=["GET"]),
    Route("/api/photo/upload", api_photo_upload, methods=["POST", "OPTIONS"]),
    Route("/api/photo/{pid:int}", api_photo_item, methods=["GET", "DELETE", "OPTIONS"]),
    Route("/api/export-pdf", api_export_pdf, methods=["POST", "OPTIONS"]),
]
STREAMLIT_APP = App("main.py")
app = Starlette(
    routes=[
        *CUSTOM_ROUTES,
        Mount("/", app=STREAMLIT_APP),
    ]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Photo-Token"],
)

class OAuthCallbackMiddleware(BaseHTTPMiddleware):
    """在 Streamlit App 之前拦截 Google OAuth 回调，避免 Streamlit 脚本重跑/重入。"""
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/":
            try:
                response = await oauth_handler.handle_oauth_callback(request)
                if response is not None:
                    return response
            except Exception as exc:
                import sys
                print(f"[OAUTH] 中间件处理回调异常: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
                return oauth_handler._redirect_with_error(f"登录处理异常: {exc}")
        return await call_next(request)


class DingTalkRootRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/" and _is_dingtalk(request):
            return RedirectResponse(url="/reports", status_code=302, headers=_cors_headers())
        return await call_next(request)


# OAuth 回调中间件必须最先注册，确保在 Streamlit App 之前处理 /?code=&state=
app.add_middleware(OAuthCallbackMiddleware)
app.add_middleware(DingTalkRootRedirectMiddleware)


def _server_address() -> str:
    return os.environ.get("SERVER_ADDRESS", "0.0.0.0")


def _server_port() -> int:
    raw = os.environ.get("SERVER_PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    return 8501


def _public_base() -> str:
    base = (os.environ.get("PUBLIC_BASE_URL", "") or os.environ.get("QMS_ACCESS_URL", "")).strip().rstrip("/")
    if base:
        return base
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
    except Exception:
        ip = "localhost"
    return f"http://{ip}:{_server_port()}"


if __name__ == "__main__":
    odb.init_online_report_table()
    print(f"QMS unified server starting on http://{_server_address()}:{_server_port()}")
    print(f"Unified access base: {_public_base()}")
    uvicorn.run(
        app,
        host=_server_address(),
        port=_server_port(),
        log_level="info",
    )
