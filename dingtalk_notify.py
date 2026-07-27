"""
钉钉通知模块 - 精准单聊推送

通知链路：
  A. 检验员提交报告 → 单聊通知审核人 (Teddy)
  B. 审核结果 → 单聊通知检验员
  C. 变更登记 → 逐人单聊通知确认人（消息中标注提交人身份）

推送机制:
  - 默认使用品质系统钉钉应用 API 发送工作通知
  - 发送异常时，保存到 data/pending_notify/ 待发送队列
"""

import json
import os
import re
import socket
import shutil
import subprocess
from datetime import datetime

from dingtalk_app_client import send_work_notice

# ── 全量人员 userId 映射（从钉钉组织架构自动导出，按姓名查 userId）──
# 文件 dingtalk_org_users.json 由 dws 通讯录遍历生成，覆盖全公司在职人员，
# 这样即使 Windows 服务器未安装 dws，也能按姓名把通知推送给任何人。
ORG_USER_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dingtalk_org_users.json")
ORG_USER_MAP = {}
try:
    with open(ORG_USER_MAP_PATH, "r", encoding="utf-8") as _f:
        ORG_USER_MAP = json.load(_f)
except Exception:
    ORG_USER_MAP = {}

# ── 特殊别名（中英文/邮箱组合，便于登录名匹配；覆盖在 org 映射之上）──
KNOWN_USER_ALIASES = {
    "程强": "2710041006992911",
    "Bruce": "2710041006992911",
    "Bruce Cheng": "2710041006992911",
    "bruce.cheng": "2710041006992911",
    "bruce.cheng程强": "2710041006992911",
    "黎晓锋": "123601064739918694",
    "Teddy.li": "123601064739918694",
    "Teddy": "123601064739918694",
    "teddy.li黎晓锋": "123601064739918694",
    "韦梦婷": "16584727872459627",
    "haruna.wei": "16584727872459627",
    "haruna.wei韦梦婷": "16584727872459627",
    "韩亚南": "02375438603033323549",
    "amelia.han": "02375438603033323549",
    "amelia.han韩亚南": "02375438603033323549",
    "董献民": "3861015133510982",
    "Carl Dong": "3861015133510982",
    "carl.dong董献民": "3861015133510982",
    "袁毅洪": "011053664634465350",
    "joung.yuan": "011053664634465350",
    "joung.yuan袁毅洪": "011053664634465350",
    "徐胜涛": "285151223524560591",
    "colin.xu": "285151223524560591",
    "colin.xu徐胜涛": "285151223524560591",
    "宁小连": "030758392923278832",
    "lucy.ning": "030758392923278832",
    "lucy.ning宁小连": "030758392923278832",
    "黄海森": "160533316139954459",
    "ken.huang": "160533316139954459",
    "ken.huang黄海森": "160533316139954459",
    "潘杨阳": "03652501170528251427",
    "lainey.pan": "03652501170528251427",
    "lainey.pan潘杨阳": "03652501170528251427",
    "翟始福": "02293844486432202051",
    "fowler.zhai": "02293844486432202051",
    "fowler.zhai翟始福": "02293844486432202051",
    "吴嘉俊": "425757153121418517",
    "leo.wu": "425757153121418517",
    "leo.wu吴嘉俊": "425757153121418517",
    "陈文钊": "121632211535128644",
    "wenzel.chen": "121632211535128644",
    "wenzel.chen陈文钊": "121632211535128644",
}

# 合并：org 全量映射为底座，特殊别名覆盖其上
KNOWN_USERS = dict(ORG_USER_MAP)
KNOWN_USERS.update(KNOWN_USER_ALIASES)

DEFAULT_REVIEWER_ID = "123601064739918694"

PENDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pending_notify")
os.makedirs(PENDING_DIR, exist_ok=True)


def _guess_lan_url():
    """尽量推断当前服务器可访问的局域网地址。"""
    server_ip = os.environ.get("SERVER_IP", "").strip()
    if server_ip:
        return f"http://{server_ip}:8501"

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:8501"
    except Exception:
        pass

    return "http://localhost:8501"


def get_quality_system_url():
    """
    生成钉钉消息里使用的系统访问地址。
    优先级：
    1. QMS_ACCESS_URL
    2. PUBLIC_BASE_URL
    3. 自动猜测局域网地址
    4. localhost
    """
    for key in ("QMS_ACCESS_URL", "PUBLIC_BASE_URL"):
        value = os.environ.get(key, "").strip().rstrip("/")
        if value:
            return value
    return _guess_lan_url()


def _normalize_identity_text(value):
    """统一清洗姓名/邮箱/英文工号，便于做审核权限匹配。"""
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _identity_aliases(value):
    """为一个身份字符串生成可比对的别名集合。"""
    aliases = set()
    raw = (value or "").strip()
    if not raw:
        return aliases

    aliases.add(_normalize_identity_text(raw))

    if "@" in raw:
        aliases.add(_normalize_identity_text(raw.split("@", 1)[0]))

    chinese_only = re.sub(r"[^一-鿿\u4e00-\u9fff]+", "", raw)
    if chinese_only:
        aliases.add(_normalize_identity_text(chinese_only))

    english_only = re.sub(r"[^a-zA-Z.]+", "", raw).strip(".")
    if english_only:
        aliases.add(_normalize_identity_text(english_only))

    return {alias for alias in aliases if alias}


def _dws_command():
    """Resolve the optional dws executable without making it mandatory."""
    configured = os.environ.get("DWS_BIN", "").strip()
    if configured:
        path = os.path.expandvars(os.path.expanduser(configured))
        if os.path.isfile(path):
            return path
    return shutil.which("dws")


def _get_user_id(name):
    """通过姓名获取钉钉 userId（支持精确匹配、模糊匹配、中文提取回退）"""
    if not name:
        return None

    if name in KNOWN_USERS:
        return KNOWN_USERS[name]

    for key, value in KNOWN_USERS.items():
        if key in name or name in key:
            KNOWN_USERS[name] = value
            return value

    search_keywords = [name]
    if re.search(r"[a-zA-Z]", name) and re.search(r"[\u4e00-\u9fff]", name):
        chinese_only = re.sub(r"[^一-鿿\u4e00-\u9fff]+", "", name)
        if chinese_only and chinese_only != name:
            search_keywords.append(chinese_only)
        english_only = re.sub(r"[^a-zA-Z.]+", "", name).strip(".")
        if english_only and english_only not in search_keywords:
            search_keywords.append(english_only)

    for keyword in search_keywords:
        dws_bin = _dws_command()
        if not dws_bin:
            break
        try:
            result = subprocess.run(
                [dws_bin, "aisearch", "person", "--keyword", keyword, "--dimension", "name", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(result.stdout)
            records = data.get("result", [])
            if records:
                user_id = records[0]["meta"].get("staffId", "")
                if user_id:
                    KNOWN_USERS[name] = user_id
                    return user_id
        except Exception:
            continue
    return None


def is_same_user(expected, *candidates):
    """判断 reviewer 与当前登录用户是否为同一人。"""
    if not expected:
        return False

    expected_id = _get_user_id(expected)
    expected_aliases = _identity_aliases(expected)

    if expected_id:
        for known_name, known_id in KNOWN_USERS.items():
            if known_id == expected_id:
                expected_aliases.update(_identity_aliases(known_name))

    for candidate in candidates:
        if not candidate:
            continue

        candidate_id = _get_user_id(candidate)
        if expected_id and candidate_id and expected_id == candidate_id:
            return True

        candidate_aliases = _identity_aliases(candidate)
        if expected_aliases & candidate_aliases:
            return True

    return False


def _send_direct(user_id, title, text):
    """以品质系统应用身份发送钉钉工作通知。"""
    return send_work_notice(user_id, title, text)


def _send_to_users(user_ids, title, text):
    """逐人发送单聊消息。dws chat message send 仅支持单个 --user。"""
    if not user_ids:
        return 0, [], "接收人列表为空"

    success = 0
    fails = []
    for user_id in user_ids:
        ok, msg = _send_direct(user_id, title, text)
        if ok:
            success += 1
        else:
            fails.append(f"uid:{user_id}({msg})")

    return success, fails, ""


def _save_pending_notification(user_ids, title, text, submitter=""):
    """dws CLI 不可用时，将推送请求保存到本地待发送队列"""
    import uuid

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    filepath = os.path.join(PENDING_DIR, filename)
    payload = {
        "created_at": datetime.now().isoformat(),
        "submitter": submitter,
        "user_ids": user_ids,
        "title": title,
        "text": text,
    }
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return filepath
    except Exception as exc:
        print(f"[dingtalk_notify] 无法写入待发送文件: {exc}", flush=True)
        return None


def notify_change_submitted(bu, brand, sku, change_reason, confirm_person, submitter=""):
    """变更登记提交 → 逐人单聊通知确认人（支持多人，逗号分隔）"""
    if not confirm_person:
        return False, "未指定确认人"

    quality_system_url = get_quality_system_url()
    person_names = [person.strip() for person in confirm_person.split(",") if person.strip()]

    title = "品质系统 - 新变更登记"
    text = f"""## 📝 新变更登记 - 待确认

**提交人**: {submitter or '系统'}
**BU**: {bu}
**品牌**: {brand}
**SKU**: {sku or '无'}
**变更内容**: {change_reason[:120]}{'...' if len(change_reason) > 120 else ''}
**提交时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

请在品质系统中查看详情。
👉 [品质系统]({quality_system_url})"""

    found_ids = []
    id_to_name = {}
    fail_list = []
    for person_name in person_names:
        user_id = _get_user_id(person_name)
        if user_id:
            found_ids.append(user_id)
            id_to_name[user_id] = person_name
        else:
            fail_list.append(f"{person_name}(未找到钉钉账号)")

    if not found_ids:
        return False, f"通知失败: {', '.join(fail_list) or '无有效接收人'}"

    success_count, send_fails, err = _send_to_users(found_ids, title, text)

    if success_count == 0 and send_fails:
        saved = _save_pending_notification(found_ids, title, text, submitter)
        if saved:
            result_msg = f"📨 已保存推送请求（{len(found_ids)}人，待稍后重试）"
        else:
            result_msg = "📨 推送请求已排队（写入失败，请注意检查）"
        if fail_list:
            result_msg += f"\n⚠️ 以下人员未识别: {', '.join(fail_list)}"
        return True, result_msg

    if success_count > 0:
        success_names = [id_to_name.get(user_id, user_id) for user_id in found_ids[:success_count]]
        result_msg = f"已通知 {', '.join(success_names[:5])}"
        if success_count > 5:
            result_msg += f" 等{success_count}人"
        if send_fails or fail_list:
            all_fails = send_fails + fail_list
            result_msg += f"\n⚠️ 以下人员通知异常: {', '.join(all_fails[:3])}"
            if len(all_fails) > 3:
                result_msg += f" 等{len(all_fails)}人"
        return True, result_msg

    all_fails = send_fails + fail_list
    return False, f"全部通知失败: {', '.join(all_fails[:3]) or '未知错误'}"


def notify_report_submitted(report_id, product_name, report_type, inspector):
    """检验报告提交 → 单聊通知审核人 (Teddy)"""
    reviewer_id = DEFAULT_REVIEWER_ID
    quality_system_url = get_quality_system_url()
    title = "品质系统 - 新检验报告待审核"
    text = f"""## 📄 新检验报告 - 待审核

**产品名称**: {product_name}
**报告类型**: {report_type}
**检验员**: {inspector}
**提交时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

👉 [品质系统]({quality_system_url})"""

    ok, msg = _send_direct(reviewer_id, title, text)
    if not ok:
        _save_pending_notification([reviewer_id], title, text, inspector)
        return False, f"{msg}；已写入待重试队列"
    return ok, msg


def notify_report_approved(report_id, product_name, inspector):
    """审核通过 → 单聊通知检验员"""
    user_id = _get_user_id(inspector)
    if not user_id:
        return False, f"未找到检验员 {inspector} 的钉钉账号"

    quality_system_url = get_quality_system_url()
    title = "品质系统 - 报告审核通过 ✅"
    text = f"""## ✅ 检验报告已通过

**产品名称**: {product_name}
**审核结果**: 已通过
**审核时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

报告已归档至 NAS。

👉 [品质系统]({quality_system_url})"""

    ok, msg = _send_direct(user_id, title, text)
    if not ok:
        _save_pending_notification([user_id], title, text, inspector)
        return False, f"{msg}；已写入待重试队列"
    return ok, msg


def notify_report_rejected(report_id, product_name, inspector, reason=""):
    """审核不通过 → 单聊通知检验员"""
    user_id = _get_user_id(inspector)
    if not user_id:
        return False, f"未找到检验员 {inspector} 的钉钉账号"

    quality_system_url = get_quality_system_url()
    reason_line = f"\n**驳回原因**: {reason}" if reason else ""
    title = "品质系统 - 报告审核不通过 ❌"
    text = f"""## ❌ 检验报告未通过

**产品名称**: {product_name}{reason_line}
**审核时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}

👉 [品质系统]({quality_system_url})"""

    ok, msg = _send_direct(user_id, title, text)
    if not ok:
        _save_pending_notification([user_id], title, text, inspector)
        return False, f"{msg}；已写入待重试队列"
    return ok, msg
