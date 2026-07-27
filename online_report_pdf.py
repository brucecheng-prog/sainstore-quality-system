# -*- coding: utf-8 -*-
from __future__ import annotations
"""
online_report_pdf.py
====================
在线 QC 检验报告 —— 服务端正式 PDF 生成（Playwright 无头 Chromium）。

原理（复用已冻结模板，零改动其渲染逻辑）：
1. 用 Chromium 打开当前在线报告模板（file://）。
2. 页面 init() 后，注入报告 JSON：调用模板自带的 buildReport(data)，
   它会把只读报告渲染进 #reportView。
3. 模板的 @media print CSS 已经：隐藏 #formView / 工具栏 / 弹窗，
   仅显示 #reportView，并设定 @page A4 + 页边距。
4. page.pdf(prefer_css_page_size=True) 直接产出与"打印"完全一致的正式 PDF。

因此 PDF 外观 == 用户在浏览器里"打印/导出"看到的，完全对齐已定稿模板。

依赖：playwright（浏览器用系统已缓存的 chrome-headless-shell）。
"""

import os
import json
import sys
import base64
import copy
import mimetypes
import tempfile
import threading
from datetime import datetime

# 在线报告模板位置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_GENERIC_TEMPLATE_CANDIDATES = [
    os.path.join(_THIS_DIR, "_components", "online_report_v2", "index.html"),
]
_ORORO_TEMPLATE_CANDIDATES = [
    os.path.join(_THIS_DIR, "_components", "online_report_ororo", "index.html"),
]


def _resolve_template_path(data: dict | None = None) -> str:
    """按报告模板选择 HTML；未标记的历史报告保持通用模板。"""
    candidates = _ORORO_TEMPLATE_CANDIDATES if (data or {}).get("template_code") == "ororo" else _GENERIC_TEMPLATE_CANDIDATES
    for candidate in candidates:
        path = os.path.abspath(candidate)
        if os.path.exists(path):
            return path
    # 保留首选路径，方便错误信息清楚指向预期位置
    return os.path.abspath(candidates[0])


TEMPLATE_PATH = _resolve_template_path()

# 本地 PDF 输出目录
PDF_DIR = os.path.join(_THIS_DIR, "data", "online_reports")

# Playwright/Chromium startup is the slowest part of export. Keep one browser
# per worker thread and create a fresh context for each report.
_PDF_RUNTIME = threading.local()


def _safe_name(s: str) -> str:
    keep = "-_.() "
    s = "".join(c for c in (s or "") if c.isalnum() or c in keep or "\u4e00" <= c <= "\u9fff")
    return s.strip().replace(" ", "_") or "report"


def _photo_data_uri(photo_id: object) -> str | None:
    """把照片索引解析为 data URI，避免 file:// PDF 页面依赖网络 URL。"""
    try:
        pid = int(photo_id)
    except (TypeError, ValueError):
        return None

    try:
        import online_report_db as odb

        photo = odb.get_photo(pid)
    except Exception:
        photo = None
    if not photo or photo.get("deleted"):
        return None

    raw = None
    local_path = photo.get("local_path")
    if local_path and os.path.exists(local_path):
        try:
            with open(local_path, "rb") as fh:
                raw = fh.read()
        except OSError:
            raw = None

    # Win 端本地缓存缺失时，仍从 NAS 真源取回，保证导出不丢照片。
    if raw is None and photo.get("nas_path"):
        try:
            from nas_client import download_file

            raw, _ = download_file(photo["nas_path"])
        except Exception:
            raw = None
    if not raw:
        return None

    mime = mimetypes.guess_type(photo.get("filename") or "")[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _embed_photo_sources(data: dict) -> tuple[dict, int, int]:
    """复制报告数据，并把 galleries/defects 中的 photo_id 替换成内嵌图片。"""
    result = copy.deepcopy(data or {})
    total = embedded = 0

    # 旧品验货的现场照片只归档到 NAS，不能插入或导出到检验报告第 9 项。
    if (result.get("basic") or {}).get("productMode") == "old":
        for values in (result.get("galleries") or {}).values():
            total += len([item for item in values or [] if isinstance(item, dict) and item.get("photo_id") is not None])
        for defect in result.get("defects") or []:
            if isinstance(defect, dict):
                total += len([item for item in defect.get("photos") or [] if isinstance(item, dict) and item.get("photo_id") is not None])
                defect["photos"] = []
        result["galleries"] = {key: [] for key in (result.get("galleries") or {})}
        return result, total, 0

    def visit(items):
        nonlocal total, embedded
        for item in items or []:
            if not isinstance(item, dict):
                continue
            pid = item.get("photo_id")
            if pid is None:
                continue
            total += 1
            src = _photo_data_uri(pid)
            if src:
                item["src"] = src
                embedded += 1

    visit(item for values in (result.get("galleries") or {}).values() for item in values or [])
    for defect in result.get("defects") or []:
        if isinstance(defect, dict):
            visit(defect.get("photos"))
    return result, total, embedded


def is_pdf_available(data: dict | None = None):
    """检测 PDF 生成能力是否就绪（playwright + 可用浏览器）。返回 (bool, msg)。"""
    try:
        from playwright.sync_api import sync_playwright  # noqa
    except Exception as e:
        return False, f"playwright 未安装: {e}"
    template_path = _resolve_template_path(data)
    if not os.path.exists(template_path):
        return False, f"模板缺失: {template_path}"
    return True, "PDF 引擎就绪"


def _browser_launch_options() -> list[dict]:
    """
    返回按稳定性排序的浏览器启动方案。

    Windows 上优先使用 Playwright 的 Edge channel。直接把 msedge.exe
    作为 executable_path 启动时，部分 Edge 版本会在无头模式下立即退出，
    从而触发 ``Target page, context or browser has been closed``。
    """
    common = {
        "headless": True,
        "args": [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-features=msEdgeSidebarV2,Translate,MediaRouter",
            "--no-first-run",
            "--headless=new",
        ],
    }
    options: list[dict] = [dict(common)]

    env_path = os.environ.get("QMS_PDF_BROWSER", "").strip()
    if env_path and os.path.exists(env_path):
        options.insert(0, {**common, "executable_path": env_path})

    if os.name == "nt":
        edge_paths = [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        if any(os.path.exists(p) for p in edge_paths):
            options.insert(0, {**common, "channel": "msedge"})
        if any(os.path.exists(p) for p in chrome_paths):
            options.insert(0, {**common, "channel": "chrome"})
        # executable_path remains a final fallback for older Playwright builds.
        options.extend({**common, "executable_path": p} for p in edge_paths + chrome_paths if os.path.exists(p))
    elif sys.platform == "darwin":
        options.extend({**common, "executable_path": p} for p in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ] if os.path.exists(p))
    else:
        options.extend({**common, "executable_path": p} for p in [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
        ] if os.path.exists(p))

    # Preserve order while removing duplicate option dictionaries.
    unique = []
    seen = set()
    for item in options:
        key = repr(sorted((k, repr(v)) for k, v in item.items()))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _browser_launch_kwargs() -> dict:
    """Backward-compatible helper returning the first launch option."""
    return _browser_launch_options()[0]


def _get_pdf_browser(sync_playwright):
    """Reuse a headless browser within the current export worker thread."""
    runtime = getattr(_PDF_RUNTIME, "value", None)
    if runtime and runtime[1].is_connected():
        return runtime[1]

    playwright = sync_playwright().start()
    browser = None
    launch_errors = []
    for launch_kwargs in _browser_launch_options():
        try:
            browser = playwright.chromium.launch(**launch_kwargs)
            break
        except Exception as exc:
            launch_errors.append(f"{launch_kwargs}: {exc}")
    if browser is None:
        playwright.stop()
        raise RuntimeError("PDF 浏览器启动失败：" + " | ".join(launch_errors))
    _PDF_RUNTIME.value = (playwright, browser)
    return browser


def render_report_pdf(data: dict, out_path: str = None, report_no: str = None):
    """
    将一份报告 JSON 渲染为正式 PDF。

    :param data: 模板 collect() 产出的完整 JSON
    :param out_path: 目标 PDF 路径；None 则自动放入 data/online_reports/
    :param report_no: 报告编号（用于默认文件名）
    :return: (ok: bool, pdf_path_or_errmsg: str)
    """
    data = data or {}
    ok, msg = is_pdf_available(data)
    if not ok:
        return False, msg

    from playwright.sync_api import sync_playwright

    os.makedirs(PDF_DIR, exist_ok=True)
    if report_no is None:
        report_no = data.get("repno") or "report"

    data, photo_total, photo_embedded = _embed_photo_sources(data)
    template_path = _resolve_template_path(data)

    if not out_path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{_safe_name(report_no)}_{stamp}.pdf"
        out_path = os.path.join(PDF_DIR, fname)

    data_js = json.dumps(data, ensure_ascii=False)

    # ── 错误日志（写到 PDF 目录，方便 Win 服务器排查）──
    _log_path = os.path.join(PDF_DIR, 'pdf_render.log')
    def _log(msg):
        try:
            with open(_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception: pass
    _log(f"开始渲染 report_no={report_no} photo_total={photo_total}")

    def _teardown_runtime():
        """关闭并清空缓存的浏览器实例，避免复用已崩溃/断开的连接。"""
        rt = getattr(_PDF_RUNTIME, "value", None)
        if rt is not None:
            try:
                rt[0].stop()
            except Exception:
                pass
            _PDF_RUNTIME.value = None

    max_attempts = 2
    last_err = "PDF 生成失败：未知错误"
    for _attempt in range(1, max_attempts + 1):
        # 每次尝试前强制关闭可能已崩溃的浏览器，使用全新实例（解决“一次失败后持续 500”）
        _teardown_runtime()
        try:
            _log(f"第{_attempt}次: 启动浏览器...")
            browser = _get_pdf_browser(sync_playwright)
            context = browser.new_context()
            page = context.new_page()
            try:
                # file:// 加载冻结模板；等待 init() 执行完
                _log(f"第{_attempt}次: 加载模板 {template_path}")
                page.goto("file://" + template_path, wait_until="load", timeout=30000)
                # 注入数据并构建只读报告视图
                _log(f"第{_attempt}次: 注入数据 (data_js={len(data_js)}字节)")
                page.evaluate(
                    """(payload) => {
                        const data = JSON.parse(payload);
                        // 模板全局函数：buildReport(data) 直接从 JSON 渲染报告视图
                        if (typeof buildReport === 'function') { buildReport(data); }
                        // 确保报告视图可见（打印媒介下 CSS 亦会强制显示）
                        const fv = document.getElementById('formView');
                        if (fv) fv.style.display = 'block';
                        const rv = document.getElementById('reportView');
                        if (rv) rv.style.display = 'block';
                        // 通用模板把 reportView 放在 formView 内；Ororo 模板本身就是纸面布局，
                        // 不存在 reportView，不能套用通用模板的子元素隐藏规则。
                        let style = document.getElementById('pdfExportStyle');
                        if (!style) { style = document.createElement('style'); style.id = 'pdfExportStyle'; document.head.appendChild(style); }
                        style.textContent = data.template_code === 'ororo'
                          ? '@media print { .toolbar { display:none !important; } #formView { display:block !important; } }'
                          : '@media print { #formView { display:block !important; } #formView > *:not(#reportView) { display:none !important; } #reportView { display:block !important; } }';
                    }""",
                    data_js,
                )
                # Data-URI images are local; wait for decode instead of a fixed 700ms delay.
                page.evaluate("""async () => {
                    await Promise.all(Array.from(document.images).map(img => img.complete
                        ? Promise.resolve()
                        : new Promise(resolve => { img.addEventListener('load', resolve, {once:true}); img.addEventListener('error', resolve, {once:true}); })));
                }""")
                page.wait_for_timeout(80)
                # 用打印媒介 + CSS @page 尺寸/页边距 → 与浏览器"打印"完全一致
                _log(f"第{_attempt}次: 生成PDF到 {out_path}")
                page.emulate_media(media="print")
                page.pdf(
                    path=out_path,
                    prefer_css_page_size=True,   # 使用模板 @page A4 + 14mm 页边距
                    print_background=True,
                )
                _log(f"第{_attempt}次: PDF生成成功")
            finally:
                context.close()
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return True, out_path
                last_err = f"PDF 生成失败：输出文件为空（第 {_attempt} 次）"
                _log(f"第{_attempt}次: 输出文件为空")
                continue
        except Exception as e:
            last_err = f"PDF 生成异常（第 {_attempt} 次）: {e}"
            _log(f"第{_attempt}次: 异常 {type(e).__name__}: {e}")
            _teardown_runtime()
            continue
    return False, last_err


if __name__ == "__main__":
    # 自检：用最小数据生成一份 PDF
    ok, msg = is_pdf_available()
    print("能力检测:", ok, msg)
    if ok:
        sample = {
            "repno": "QC-SELFTEST-0001",
            "basic": {"product": "自检样品", "productEn": "Self Test",
                       "supplier": "测试供应商", "inspector": "系统自检"},
            "conclusion": {"verdict": "PASS", "conc": "自检通过"},
        }
        ok2, path = render_report_pdf(sample, report_no="QC-SELFTEST-0001")
        print("生成结果:", ok2, path)
