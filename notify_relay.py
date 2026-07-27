#!/usr/bin/env python3
"""
本地通知中继 — 处理公网降级的待发送推送请求

功能：
  1. 读取 data/pending_notify/ 目录下的待发送 JSON 文件
  2. 通过品质系统钉钉应用逐人发送
  3. 发送成功后移动文件到 data/pending_notify/sent/
  4. 发送失败的文件保留原处，记录错误

使用方式：
  python notify_relay.py                    # 处理本地待发送
  python notify_relay.py --watch            # 持续监控模式（每60秒）

WorkBuddy 自动化：
  - 定时运行（建议每 5 分钟）
  - prompt: "cd 实验室 && python3 notify_relay.py"
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import shutil

from dingtalk_app_client import send_work_notice

# 配置
SCRIPT_DIR = Path(__file__).parent.absolute()
PENDING_DIR = SCRIPT_DIR / "data" / "pending_notify"
SENT_DIR = PENDING_DIR / "sent"
FAILED_DIR = PENDING_DIR / "failed"
MAX_AGE_HOURS = 24  # 超过此时间的推送丢弃


def ensure_dirs():
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    SENT_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)


def send_to_user(user_id, title, text):
    """通过品质系统钉钉应用发送单聊工作通知。"""
    return send_work_notice(user_id, title, text)


def send_pending_notification(payload):
    """发送单条待处理通知（逐人发送）。"""
    user_ids = payload.get("user_ids", [])
    title = payload.get("title", "品质系统通知")
    text = payload.get("text", "")

    if not user_ids:
        return 0, len(user_ids), "无接收人"

    success = 0
    fails = []
    for uid in user_ids:
        ok, msg = send_to_user(uid, title, text)
        if ok:
            success += 1
        else:
            fails.append(f"uid:{uid}({msg})")

    return success, len(user_ids) - success, "; ".join(fails) if fails else ""


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds}秒前"
    elif seconds < 3600:
        return f"{seconds // 60}分钟前"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}小时{mins}分钟前"


def process_pending():
    """处理本地待发送文件"""
    ensure_dirs()

    json_files = sorted(PENDING_DIR.glob("*.json"))
    if not json_files:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 无待发送推送")
        return

    total = len(json_files)
    success = 0
    fail = 0
    skip = 0

    for f in json_files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  ⚠️  跳过损坏文件: {f.name} ({e})")
            shutil.move(str(f), str(FAILED_DIR / f.name))
            skip += 1
            continue

        # 检查创建时间，超过 MAX_AGE_HOURS 的丢弃
        created_str = payload.get("created_at", "")
        if created_str:
            try:
                created_at = datetime.fromisoformat(created_str)
                age_hours = (datetime.now() - created_at).total_seconds() / 3600
                if age_hours > MAX_AGE_HOURS:
                    print(f"  ⏭️  跳过过期推送: {f.name} ({format_duration(age_hours * 3600)})")
                    shutil.move(str(f), str(FAILED_DIR / f.name))
                    skip += 1
                    continue
            except ValueError:
                pass

        # 发送
        ok_count, fail_count, err_msg = send_pending_notification(payload)
        submitter = payload.get("submitter", "")
        title = payload.get("title", "")
        prefix = f"[{submitter}] " if submitter else ""
        n_users = len(payload.get("user_ids", []))

        if fail_count == 0:
            print(f"  ✅ {prefix}{title}: {ok_count}/{n_users} 人")
            shutil.move(str(f), str(SENT_DIR / f.name))
            success += 1
        elif ok_count > 0:
            print(f"  ⚠️  {prefix}{title}: {ok_count}/{n_users} 人（部分失败: {err_msg}）")
            shutil.move(str(f), str(SENT_DIR / f.name))
            success += 1
        else:
            print(f"  ❌ {prefix}{title}: 全部失败 ({err_msg})")
            fail += 1

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 处理完成: "
          f"成功 {success}, 失败 {fail}, 跳过 {skip} (共 {total})")


def watch_mode(interval=60):
    """持续监控模式"""
    print(f"🔍 开始监控 {PENDING_DIR}，间隔 {interval} 秒...")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 按 Ctrl+C 停止\n")
    try:
        while True:
            process_pending()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n👋 已停止监控")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        interval = 60
        for i, arg in enumerate(sys.argv):
            if arg == "--interval" and i + 1 < len(sys.argv):
                try:
                    interval = int(sys.argv[i + 1])
                except ValueError:
                    pass
        watch_mode(interval)
    else:
        process_pending()
