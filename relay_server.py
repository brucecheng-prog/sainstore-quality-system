#!/usr/bin/env python3
"""
通知中继服务器 — 接收公网 (Windows 局域网服务器) 的推送请求, 立即通过品质系统钉钉应用发送。

部署方式:
  1. 本地运行: python3 relay_server.py
  2. 隧道暴露: cloudflared tunnel --url http://localhost:8765
  3. 将隧道 URL 写入 relay_url.txt, dingtalk_notify.py 自动读取

端点:
  POST /push   — 公网服务器提交推送请求 (立即发送或排入队列)
  GET  /pending — 查看待发送队列
  GET  /health  — 健康检查
"""

import json
import os
import threading
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dingtalk_app_client import send_work_notice

# ── 配置 ──
SCRIPT_DIR = Path(__file__).parent.absolute()
PENDING_DIR = SCRIPT_DIR / "data" / "pending_notify"
SENT_DIR = PENDING_DIR / "sent"
FAILED_DIR = PENDING_DIR / "failed"
PORT = 8765

# 隧道 URL (启动后 cloudflared 输出中自动更新)
TUNNEL_URL_FILE = SCRIPT_DIR / "data" / "relay_url.txt"


def ensure_dirs():
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    SENT_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)


def send_via_dws(user_id: str, title: str, text: str) -> tuple[bool, str]:
    """通过品质系统钉钉应用发送单聊工作通知。"""
    return send_work_notice(user_id, title, text)


def save_to_pending(payload: dict):
    """保存到待发送队列 (dws 不可用时的降级方案)"""
    ensure_dirs()
    fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    fpath = PENDING_DIR / fname
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return fname


class RelayHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def _json_response(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        """CORS preflight"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            # 健康检查
            pending_count = len(list(PENDING_DIR.glob("*.json"))) if PENDING_DIR.exists() else 0
            self._json_response(200, {
                "status": "ok",
                "pending": pending_count,
                "time": datetime.now().isoformat(),
            })

        elif path == "/pending":
            # 查看待发送队列
            ensure_dirs()
            files = sorted(PENDING_DIR.glob("*.json"))
            result = []
            for f in files:
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        payload = json.load(fp)
                    result.append({
                        "id": f.stem,
                        "submitter": payload.get("submitter", ""),
                        "title": payload.get("title", ""),
                        "n_users": len(payload.get("user_ids", [])),
                        "created_at": payload.get("created_at", ""),
                    })
                except Exception:
                    result.append({"id": f.stem, "error": "无法读取"})
            self._json_response(200, {"pending": result})

        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path != "/push":
            self._json_response(404, {"error": "not found"})
            return

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json_response(400, {"error": "empty body"})
            return

        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            self._json_response(400, {"error": f"invalid JSON: {e}"})
            return

        # 验证必要字段
        user_ids = payload.get("user_ids", [])
        title = payload.get("title", "")
        text = payload.get("text", "")
        submitter = payload.get("submitter", "")

        if not user_ids:
            self._json_response(400, {"error": "缺少 user_ids"})
            return

        # 记录创建时间
        if "created_at" not in payload:
            payload["created_at"] = datetime.now().isoformat()

        # 逐人发送
        results = []
        all_ok = True
        for uid in user_ids:
            ok, msg = send_via_dws(uid, title, text)
            results.append({"user_id": uid, "ok": ok, "message": msg})
            if not ok:
                all_ok = False

        if all_ok:
            # 全部成功 → 直接返回
            self._json_response(200, {
                "status": "sent",
                "submitter": submitter,
                "total": len(user_ids),
                "sent": len(user_ids),
                "results": results,
            })
        else:
            # 部分或全部失败 → 保存到队列作为降级
            fname = save_to_pending(payload)
            sent_count = sum(1 for r in results if r["ok"])
            failed_count = len(user_ids) - sent_count
            self._json_response(207, {
                "status": "partial" if sent_count > 0 else "queued",
                "file": fname,
                "total": len(user_ids),
                "sent": sent_count,
                "failed": failed_count,
                "results": results,
            })

    def log_message(self, format, *args):
        """自定义日志格式"""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {args[0]}")


def get_tunnel_url() -> str | None:
    """获取 cloudflared 隧道 URL"""
    if TUNNEL_URL_FILE.exists():
        content = TUNNEL_URL_FILE.read_text().strip()
        if content and content.startswith("http"):
            return content
    return None


def save_tunnel_url(url: str):
    """保存隧道 URL"""
    TUNNEL_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUNNEL_URL_FILE.write_text(url)


def main():
    ensure_dirs()

    print("=" * 50)
    print(" 📨 品质系统通知中继服务器")
    print(f"   端口: {PORT}")
    print(f"   待发送目录: {PENDING_DIR}")
    print()

    tunnel_url = get_tunnel_url()
    if tunnel_url:
        print(f" 🌐 公网地址: {tunnel_url}")
        print(f"   推送端点: {tunnel_url}/push")
    else:
        print(" ⚠️  暂无隧道 URL (启动 cloudflared 后自动生成)")
        print("   运行: cloudflared tunnel --url http://localhost:8765")
    print("=" * 50)

    server = HTTPServer(("0.0.0.0", PORT), RelayHandler)
    print(f"\n[服务器] 已启动, 监听 0.0.0.0:{PORT}")
    print("[服务器] 按 Ctrl+C 停止\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[服务器] 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
