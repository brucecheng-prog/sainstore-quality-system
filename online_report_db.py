# -*- coding: utf-8 -*-
from __future__ import annotations
"""
online_report_db.py
====================
在线 QC 检验报告 —— 独立数据层。

设计原则（务必遵守，见踩坑日志）：
1. 与现有 `inspection_reports`（历史 17 份纸质/上传报告）**完全隔离**：
   本模块只读写全新表 `online_reports`，不触碰任何既有表结构与数据。
2. 复用 database.get_connection()（同一个 lab_manager.db，同一套 PRAGMA/审计环境），
   但不修改 database.py，回滚只需 DROP TABLE online_reports。
3. 一份报告 = 一整份模板 JSON（collect() 的产物）+ 状态机 + 审核字段 + PDF 路径。

状态机（中文，与既有系统风格一致）：
    草稿  --提交审核-->  待审核  --通过-->  已通过（触发生成正式 PDF）
                                \\--驳回-->  已驳回  --重新编辑-->  草稿
"""

import os
import re
import json
import sqlite3
import time
from datetime import datetime

# 复用主库连接（不修改 database.py）
from database import get_connection, _current_actor

# 在线报告 PDF 输出目录（本地回退，NAS 优先在 pdf 模块处理）
PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "online_reports")

STATUS_DRAFT = "草稿"
STATUS_PENDING = "待审核"
STATUS_APPROVED = "已通过"
STATUS_REJECTED = "已驳回"
ALL_STATUS = (STATUS_DRAFT, STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


# ==================== 初始化 ====================

def init_online_report_table():
    """幂等创建 online_reports 表；不影响任何既有表。"""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS online_reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_no     TEXT    UNIQUE,
                title         TEXT,
                product_name  TEXT,
                supplier      TEXT,
                inspector     TEXT,
                verdict       TEXT,
                status        TEXT    NOT NULL DEFAULT '草稿'
                              CHECK (status IN ('草稿','待审核','已通过','已驳回')),
                data_json     TEXT    NOT NULL,
                pdf_path      TEXT,
                nas_pdf_path  TEXT,
                nas_staging_path TEXT,
                reviewer      TEXT,
                review_comment TEXT,
                created_by    TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                submitted_at  TEXT,
                reviewed_at   TEXT
            )
            """
        )
        # 兼容已经存在的 online_reports 表，增量补齐 NAS 暂存字段。
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(online_reports)").fetchall()}
        if "nas_staging_path" not in columns:
            conn.execute("ALTER TABLE online_reports ADD COLUMN nas_staging_path TEXT")
        # 常用索引（状态筛选 / 时间排序）
        conn.execute("CREATE INDEX IF NOT EXISTS idx_online_reports_status ON online_reports(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_online_reports_created ON online_reports(created_at)")
        conn.commit()
    finally:
        conn.close()
    init_online_report_governance()
    os.makedirs(PDF_DIR, exist_ok=True)


# ==================== 工具 ====================

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def gen_report_no():
    """生成唯一报告编号：QC-YYYYMMDD-XXXX（当天顺序号，四位）。"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"QC-{today}-"
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT report_no FROM online_reports WHERE report_no LIKE ? ORDER BY report_no DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        if row and row["report_no"]:
            try:
                seq = int(str(row["report_no"]).split("-")[-1]) + 1
            except Exception:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"
    finally:
        conn.close()


def _summary_from_data(data: dict):
    """从模板 JSON 提取列表展示所需的摘要字段。"""
    data = data or {}
    basic = data.get("basic", {}) or {}
    concl = data.get("conclusion", {}) or {}
    product = basic.get("product") or basic.get("productEn") or ""
    # 优先使用用户自定义的报告名称，否则 fallback 到产品名
    custom_title = (basic.get("title") or "").strip()
    return {
        "title": custom_title if custom_title else (product or "未命名报告"),
        "product_name": product,
        "supplier": basic.get("supplier", ""),
        "inspector": basic.get("inspector", ""),
        "verdict": concl.get("verdict", ""),
    }


# ==================== 增改 ====================

def create_draft(data: dict, created_by: str = ""):
    """新建草稿。返回 (id, report_no)。"""
    init_online_report_table()
    data = data or {}
    s = _summary_from_data(data)
    requested_report_no = (data.get("repno") or "").strip()
    auto_number = (not requested_report_no) or ("_" in requested_report_no)
    last_error = None
    for _ in range(5):
        report_no = gen_report_no() if auto_number else requested_report_no
        payload = dict(data)
        payload["repno"] = report_no
        now = _now()
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO online_reports
                    (report_no, title, product_name, supplier, inspector, verdict,
                     status, data_json, created_by, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    report_no, s["title"], s["product_name"], s["supplier"], s["inspector"],
                    s["verdict"], STATUS_DRAFT, json.dumps(payload, ensure_ascii=False),
                    created_by, now, now,
                ),
            )
            conn.commit()
            return cur.lastrowid, report_no
        except sqlite3.IntegrityError as exc:
            last_error = exc
            if not auto_number:
                raise
            time.sleep(0.05)
        finally:
            conn.close()
    raise last_error or sqlite3.IntegrityError("failed to allocate unique report_no")


def update_draft(rid: int, data: dict, force: bool = False):
    """更新报告内容。
    - 默认仅允许 草稿/已驳回/待审核 状态编辑；
    - force=True 时允许管理员覆盖「已通过」等锁定状态（须由上层先记版本快照+审计）。
    返回 True/False。"""
    data = data or {}
    s = _summary_from_data(data)
    conn = get_connection()
    try:
        row = conn.execute("SELECT status, report_no FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row:
            return False
        if (not force) and (row["status"] not in (STATUS_DRAFT, STATUS_REJECTED, STATUS_PENDING)):
            return False
        # 保持既有 report_no
        data["repno"] = row["report_no"]
        conn.execute(
            """
            UPDATE online_reports
               SET title=?, product_name=?, supplier=?, inspector=?, verdict=?,
                   data_json=?, updated_at=?
             WHERE id=?
            """,
            (
                s["title"], s["product_name"], s["supplier"], s["inspector"], s["verdict"],
                json.dumps(data, ensure_ascii=False), _now(), rid,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def submit_for_review(rid: int):
    """草稿/已驳回 → 待审核。返回 True/False。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] not in (STATUS_DRAFT, STATUS_REJECTED):
            return False
        conn.execute(
            "UPDATE online_reports SET status=?, submitted_at=?, updated_at=? WHERE id=?",
            (STATUS_PENDING, _now(), _now(), rid),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def approve_report(rid: int, reviewer: str = "", comment: str = ""):
    """待审核 → 已通过。返回 True/False（PDF 由上层在通过后调用生成）。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] != STATUS_PENDING:
            return False
        conn.execute(
            "UPDATE online_reports SET status=?, reviewer=?, review_comment=?, reviewed_at=?, updated_at=? WHERE id=?",
            (STATUS_APPROVED, reviewer, comment, _now(), _now(), rid),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reject_report(rid: int, reviewer: str = "", comment: str = ""):
    """待审核 → 已驳回。返回 True/False。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] != STATUS_PENDING:
            return False
        conn.execute(
            "UPDATE online_reports SET status=?, reviewer=?, review_comment=?, reviewed_at=?, updated_at=? WHERE id=?",
            (STATUS_REJECTED, reviewer, comment, _now(), _now(), rid),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reopen_to_draft(rid: int):
    """已驳回 → 草稿（允许重新编辑再提交）。返回 True/False。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row or row["status"] != STATUS_REJECTED:
            return False
        conn.execute(
            "UPDATE online_reports SET status=?, updated_at=? WHERE id=?",
            (STATUS_DRAFT, _now(), rid),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def set_pdf_path(rid: int, pdf_path: str, nas_pdf_path: str = None):
    """写入生成的 PDF 路径。"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE online_reports SET pdf_path=?, nas_pdf_path=?, updated_at=? WHERE id=?",
            (pdf_path, nas_pdf_path, _now(), rid),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def set_pdf_storage(rid: int, pdf_path: str = "", nas_staging_path: str = "",
                    nas_pdf_path: str = None):
    """保存在线报告 PDF 的本地路径、NAS 暂存路径和正式归档路径。"""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE online_reports
               SET pdf_path=?, nas_staging_path=?, nas_pdf_path=?, updated_at=?
               WHERE id=?""",
            (pdf_path or "", nas_staging_path or "", nas_pdf_path, _now(), rid),
        )
        conn.commit()
    finally:
        conn.close()


def delete_online_report(rid: int):
    """删除一份在线报告，并清理本地生成的正式 PDF（如有）。"""
    import os
    conn = get_connection()
    pdf_path = None
    try:
        row = conn.execute("SELECT pdf_path FROM online_reports WHERE id=?", (rid,)).fetchone()
        if row:
            pdf_path = row["pdf_path"]
        conn.execute("DELETE FROM online_reports WHERE id=?", (rid,))
        conn.commit()
    finally:
        conn.close()
    # 级联清理本地 PDF
    if pdf_path and os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except Exception:
            pass
    return True


# ==================== 查询 ====================

def _row_to_dict(row, with_data=False):
    d = dict(row)
    if with_data:
        try:
            d["data"] = json.loads(d.get("data_json") or "{}")
        except Exception:
            d["data"] = {}
    else:
        d.pop("data_json", None)
    return d


def list_online_reports(status: str = None, owner: str = None):
    """列表（不含 data_json，轻量）。可按状态筛选；owner 非空时仅返回该创建者的报告。"""
    init_online_report_table()
    conn = get_connection()
    try:
        if status and owner:
            rows = conn.execute(
                "SELECT * FROM online_reports WHERE status=? AND created_by=? ORDER BY id DESC", (status, owner)
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM online_reports WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        elif owner:
            rows = conn.execute(
                "SELECT * FROM online_reports WHERE created_by=? ORDER BY id DESC", (owner,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM online_reports ORDER BY id DESC"
            ).fetchall()
        return [_row_to_dict(r, with_data=False) for r in rows]
    finally:
        conn.close()


def get_online_report(rid: int, with_data: bool = True):
    """获取单份报告（默认含解析后的 data）。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM online_reports WHERE id=?", (rid,)).fetchone()
        if not row:
            return None
        return _row_to_dict(row, with_data=with_data)
    finally:
        conn.close()


def storage_key_for_report_key(report_key: str) -> str:
    """Return the human-readable report number for NAS folders when available."""
    key = str(report_key or "").strip()
    if key.startswith("tmp_old_"):
        # 独立旧品拍照不关联在线报告，但仍要有可检索、不会冲突的 NAS 目录。
        safe = re.sub(r'[\\/:*?"<>|]+', "-", key[8:]).strip(" .-")
        return "旧品-" + (safe or "未命名")
    if key.startswith("r") and key[1:].isdigit():
        report = get_online_report(int(key[1:]), with_data=False)
        if report and report.get("report_no"):
            return str(report["report_no"])
    return key or "unassigned"


def build_online_report_archive_filename(report: dict) -> str:
    """返回在线报告正式 PDF 文件名，也是照片一级文件夹名的唯一依据。"""
    report = report or {}
    data = report.get("data") or {}
    basic = data.get("basic", {}) or {}
    title_info = data.get("titleInfo", {}) or {}
    unsafe = r'[\\/:*?"<>|]+'
    # 优先使用检验员在报告基本信息中填写的报告名称。上传报告的文件名
    # 就是追溯主键，在线报告也必须沿用这条规则，不能重新拼出另一套名称。
    title = (basic.get("title") or title_info.get("title") or "").strip()
    if title:
        stem = os.path.splitext(title)[0].strip()
    else:
        parts = [
            title_info.get("brand") or basic.get("brand") or "",
            f"({basic.get('po')})" if basic.get("po") else "",
            basic.get("supplier") or report.get("supplier") or "",
            basic.get("product") or report.get("product_name") or "",
        ]
        cleaned = [re.sub(unsafe, "-", str(part).strip()) for part in parts if str(part).strip()]
        stem = "—".join(cleaned)
    date_short = re.sub(r"[^0-9]", "", str(basic.get("date") or ""))[:8]
    date_short = date_short or datetime.now().strftime("%Y%m%d")
    stem = re.sub(unsafe, "-", stem).strip(" .-") or str(report.get("report_no") or "在线检验报告")
    # 用户自定义名称已经含有日期/报告后缀时不重复追加，避免 PDF 名称漂移。
    if not re.search(r"(?:报告|检验|验货)\d{6,8}$", stem):
        stem = f"{stem}验货报告{date_short}"
    return f"{stem}.pdf"


def build_online_report_photo_folder_name(report: dict) -> str:
    """返回与报告文件同源的图片归档文件夹名。"""
    stem = os.path.splitext(build_online_report_archive_filename(report))[0]
    # 同事上传的目录命名为“报告主名 + 图片 + 日期”，报告主名来自文件名。
    m = re.search(r"(?:验货报告|检验报告)(\d{6,8})$", stem)
    if m:
        stem = f"{stem[:m.start()]}图片{m.group(1)}"
    elif re.search(r"(?:验货报告|检验报告)$", stem):
        stem = re.sub(r"(?:验货报告|检验报告)$", "图片", stem)
    else:
        stem = f"{stem}图片"
    return re.sub(r'[\\/:*?"<>|]+', "-", stem).strip(" .-")


def get_report_nas_photo_folder(report_key: str) -> str | None:
    """根据报告数据返回有意义的 NAS 照片文件夹路径前缀（不含 category）。

    返回格式与上传报告入口一致：
    /QA/验货相关文件/验货图片/{year}年/{brand}_{sku}_验货图片_{YYYYMMDD}

    参数:
        report_key: 报告键值 (如 "r42" 或 "tmp_xxx")
    返回:
        NAS 文件夹路径前缀字符串，或 None（无法解析时）
    """
    key = str(report_key or "").strip()
    if not key:
        return None

    # ── 尝试从数据库读取报告详情 ──
    report = None
    if key.startswith("r") and key[1:].isdigit():
        report = get_online_report(int(key[1:]), with_data=True)
    elif key.startswith("tmp_old_"):
        # 旧品独立拍照，无关联报告 → 用 storage_key 格式
        sk = storage_key_for_report_key(key)
        from nas_client import get_nas_routes
        return f"{get_nas_routes('其他', str(datetime.now().year))[1].rstrip('/')}/{sk}" if sk else None

    if not report:
        # 无数据库记录（未保存的新建草稿）→ 用 storage_key 兜底
        sk = storage_key_for_report_key(key)
        from nas_client import get_nas_routes
        return f"{get_nas_routes('其他', str(datetime.now().year))[1].rstrip('/')}/{sk}" if sk else None

    # ── 从 data_json 提取字段 ──
    data = report.get("data") or {}
    basic = data.get("basic", {}) or {}
    title_info = data.get("titleInfo", {}) or {}

    brand = (title_info.get("brand") or basic.get("brand") or "").strip()
    sku = (title_info.get("sku") or basic.get("sku") or "").strip()
    product = (basic.get("product") or "").strip()
    date_str = (basic.get("date") or "").strip()
    raw_type = str(
        basic.get("reportType")
        or basic.get("report_type")
        or basic.get("type")
        or ""
    )
    # 在线报告默认归入"来料检验"（QC检验报告的本质类型），而非"其他"。
    # 这样照片会落入 /QA/验货相关文件/验货图片/ 下，与用户预期一致。
    if "出货" in raw_type or "Final" in raw_type or "Loading" in raw_type:
        report_type = "出货检验"
    elif "驻厂" in raw_type or "Production" in raw_type:
        report_type = "驻厂验货"
    elif "来料" in raw_type or "Incoming" in raw_type:
        report_type = "来料检验"
    else:
        report_type = "来料检验"  # 在线报告兜底：默认来料检验，不走"其他"

    # 报告号作兜底标识
    report_no = report.get("report_no", "")

    # 至少需要产品名或品牌才能生成有意义名称
    if not product and not brand and not report_no:
        sk = storage_key_for_report_key(key)
        from nas_client import get_nas_routes
        return f"{get_nas_routes(report_type, str(datetime.now().year))[1].rstrip('/')}/{sk}" if sk else None

    # ── 解析年份 ──
    year = ""
    if date_str:
        try:
            year = date_str[:4]  # YYYY-MM-DD → YYYY
            datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            year = ""
    if not year:
        year = str(datetime.now().year)

    # ── 日期短格式 YYYYMMDD ──
    date_short = ""
    if date_str:
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            date_short = dt.strftime("%Y%m%d")
        except Exception:
            pass

    # 照片一级目录必须与正式 PDF 同名（仅去掉 .pdf），便于按报告一对一追溯。
    folder_name = build_online_report_photo_folder_name(report)

    # 防止过长（NAS FileStation 有路径长度限制）
    if len(folder_name) > 120:
        folder_name = folder_name[:117] + "..."

    # 最终不含尾部斜杠，调用方自行拼接 category
    from nas_client import get_nas_routes
    picture_base = get_nas_routes(report_type, year)[1].rstrip("/")
    return f"{picture_base}/{folder_name}"


def next_photo_seq(report_key: str) -> int:
    """按报告统一分配照片序号，避免不同类别产生同名文件。"""
    photos = list_photos(report_key=report_key)
    return max([int(p.get("seq") or 0) for p in photos] + [0]) + 1


def counts_by_status(owner: str = None):
    """各状态数量（用于 Tab 顶部小统计）。owner 非空时仅统计该创建者的报告。"""
    init_online_report_table()
    conn = get_connection()
    try:
        if owner:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM online_reports WHERE created_by=? GROUP BY status", (owner,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM online_reports GROUP BY status"
            ).fetchall()
        result = {s: 0 for s in ALL_STATUS}
        for r in rows:
            result[r["status"]] = r["n"]
        result["total"] = sum(result[s] for s in ALL_STATUS)
        return result
    finally:
        conn.close()


# ==================== 治理层（版本 / 审计 / 角色） ====================
# 与设计蓝图一致：审核后不可随意改 + 报告版本管理 + 操作日志 + 权限控制。
# 全部为新增表，不触碰 online_reports 既有结构与数据。

def init_online_report_governance():
    """幂等创建在线报告治理表。"""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS online_report_versions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id     INTEGER NOT NULL,
                version       INTEGER NOT NULL,
                snapshot_json TEXT,
                pdf_path      TEXT,
                changed_by    TEXT,
                change_reason TEXT,
                trigger       TEXT,
                created_at    TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orv_rid ON online_report_versions(report_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS online_report_audit (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT,
                actor       TEXT,
                action      TEXT,
                target_type TEXT,
                target_id   TEXT,
                detail      TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ora_tid ON online_report_audit(target_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS online_report_roles (
                user_name TEXT PRIMARY KEY,
                role      TEXT NOT NULL DEFAULT 'viewer'
            )
            """
        )
        # ── 照片索引表（NAS 唯一真源 + 本地缓存回退 + 软删除留痕）──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_photos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id     INTEGER,
                report_key    TEXT,
                category      TEXT    NOT NULL,
                defect_index  INTEGER,
                filename      TEXT,
                local_path    TEXT,
                nas_path      TEXT,
                sha256        TEXT,
                caption       TEXT,
                seq           INTEGER DEFAULT 0,
                deleted       INTEGER NOT NULL DEFAULT 0,
                deleted_by    TEXT,
                deleted_at    TEXT,
                created_by    TEXT,
                created_at    TEXT,
                archive_only INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rp_rid ON report_photos(report_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rp_key ON report_photos(report_key)")
        # 兼容旧库：追加 archive_only 列
        try:
            conn.execute("ALTER TABLE report_photos ADD COLUMN archive_only INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # 列已存在则忽略
        conn.commit()
    finally:
        conn.close()


def create_version(rid, data_json, pdf_path=None, changed_by="", change_reason="", trigger=""):
    """为报告创建一版快照，version 自动递增。返回 (id, version)。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS m FROM online_report_versions WHERE report_id=?",
            (rid,),
        ).fetchone()
        ver = (row["m"] if row else 0) + 1
        cur = conn.execute(
            """INSERT INTO online_report_versions
               (report_id, version, snapshot_json, pdf_path, changed_by, change_reason, trigger, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, ver, data_json, pdf_path, changed_by, change_reason, trigger, _now()),
        )
        conn.commit()
        return cur.lastrowid, ver
    finally:
        conn.close()


def list_versions(rid):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, version, changed_by, change_reason, trigger, created_at "
            "FROM online_report_versions WHERE report_id=? ORDER BY version DESC",
            (rid,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_version(vid):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM online_report_versions WHERE id=?", (vid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def restore_version(rid, vid, changed_by="", change_reason=""):
    """将报告 data_json 恢复到指定版本，并记一版新快照（trigger='restore'）。"""
    v = get_version(vid)
    if not v:
        return False
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE online_reports SET data_json=?, updated_at=? WHERE id=?",
            (v["snapshot_json"], _now(), rid),
        )
        conn.commit()
    finally:
        conn.close()
    create_version(rid, v["snapshot_json"], v.get("pdf_path"), changed_by,
                   change_reason or f"恢复至 v{v['version']}", "restore")
    add_audit(changed_by, "restore_version", "online_report", str(rid), f"恢复至版本 v{v['version']}")
    return True


# 在线报告操作 → 全局审计的动作中文映射（便于操作审计页/系统监控页阅读）
_ACTION_CN = {
    "create": "新建报告",
    "submit": "提交审核",
    "approve": "审核通过",
    "reject": "驳回",
    "delete": "删除报告",
    "force_edit": "强制编辑",
    "upload_photo": "上传照片",
    "delete_photo": "删除照片",
    "reconcile_missing_photo": "同步缺失照片",
    "restore_version": "恢复版本",
}


def add_audit(actor, action, target_type, target_id, detail=""):
    # 1) 始终写本模块私有审计表（报告详情页「📜 操作日志」使用）
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO online_report_audit (ts, actor, action, target_type, target_id, detail) "
            "VALUES (?,?,?,?,?,?)",
            (_now(), actor, action, target_type, str(target_id), detail),
        )
        conn.commit()
    finally:
        conn.close()
    # 2) 镜像到全局审计体系（操作审计页 operation_log + 系统监控页 activity_log）
    #    失败不影响主流程（如非 Streamlit 上下文取不到网络信息时静默跳过）
    _mirror_global_audit(actor, action, target_id, detail)


def _mirror_global_audit(actor, action, target_id, detail):
    """把在线报告操作同步进全局审计表，使「操作审计」与「系统监控」页可见。"""
    try:
        action_cn = _ACTION_CN.get(action, action)
        target_table = "online_reports"  # 统一表名，便于审计页筛选
        # 取操作人/网络/部署等元信息（Streamlit 请求上下文）
        try:
            meta = _current_actor()
            network = meta.get("network") or "未知"
            deployment = meta.get("deployment") or "未知"
            ip = meta.get("ip") or ""
        except Exception:
            network, deployment, ip = "未知", "未知", ""
        operator = actor or "匿名"
        rid = int(target_id) if str(target_id).isdigit() else -1
        # 写 operation_log（操作审计页）
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO operation_log
                   (operator, action, target_table, record_id, detail, network, deployment, ip_address)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (operator, action_cn, target_table, rid,
                 str(detail)[:500], network, deployment, ip),
            )
            conn.commit()
        finally:
            conn.close()
        # 写 activity_log（系统监控页，归为「数据修改」类）
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO activity_log
                   (user_email, user_name, action, category, detail, page)
                   VALUES (?,?,?,?,?,?)""",
                (operator, actor, action_cn, "data_edit",
                 f"在线报告#{target_id} {detail}"[:500], "在线报告"),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def list_audit(rid):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ts, actor, action, detail FROM online_report_audit "
            "WHERE target_id=? ORDER BY id DESC",
            (str(rid),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_role(user_name, is_admin=False):
    """返回角色。管理员会话直接 admin；无记录默认 uploader（避免锁死普通上传员）。"""
    if is_admin:
        return "admin"
    conn = get_connection()
    try:
        row = conn.execute("SELECT role FROM online_report_roles WHERE user_name=?", (user_name,)).fetchone()
        return row["role"] if row else "uploader"
    finally:
        conn.close()


def set_role(user_name, role):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO online_report_roles (user_name, role) VALUES (?,?)",
            (user_name, role),
        )
        conn.commit()
    finally:
        conn.close()


def list_roles():
    """列出所有显式分配的角色。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT user_name, role FROM online_report_roles ORDER BY role, user_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== 照片索引（NAS 唯一真源 + 软删除留痕） ====================

def add_photo(report_key, category, filename, local_path=None, nas_path=None,
              sha256=None, caption="", seq=0, defect_index=None,
              created_by="", report_id=None, archive_only=0):
    """写入一条照片索引，返回 photo_id。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO report_photos
               (report_id, report_key, category, defect_index, filename, local_path,
                nas_path, sha256, caption, seq, created_by, created_at, archive_only)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id, report_key, category, defect_index, filename, local_path,
             nas_path, sha256, caption, seq, created_by, _now(), int(archive_only)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def find_photo_by_sha(report_key, sha256):
    """按 report_key + sha256 查找未删除的已存在照片，用于上传幂等（防止重试/重复拍照产生重复）。"""
    if not sha256:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM report_photos WHERE report_key=? AND sha256=? AND deleted=0 ORDER BY id DESC LIMIT 1",
            (report_key, sha256),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def set_photo_nas_path(photo_id, nas_path):
    """补写某照片的 NAS 路径（用于去重命中但首次 NAS 上传失败时的回填）。"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE report_photos SET nas_path=? WHERE id=?",
            (nas_path, photo_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_photos(report_key=None, report_id=None, include_deleted=False):
    """列出照片。report_key 或 report_id 二选一；include_deleted 控制是否含软删除。"""
    conn = get_connection()
    try:
        sql = "SELECT * FROM report_photos WHERE "
        params = []
        if report_id is not None:
            sql += "report_id=? "; params.append(report_id)
        elif report_key is not None:
            sql += "report_key=? "; params.append(report_key)
        else:
            return []
        if not include_deleted:
            sql += "AND deleted=0 "
        sql += "ORDER BY category, seq, id"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_photo(photo_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM report_photos WHERE id=?", (photo_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def soft_delete_photo(photo_id, by=""):
    """软删除：标记 deleted=1 + 记录操作人/时间；同时在 NAS 与本地缓存删除实体文件。
    返回 (ok, msg)。"""
    ph = get_photo(photo_id)
    if not ph or ph.get("deleted"):
        return False, "照片不存在或已删除"
    warn = []
    np_ = ph.get("nas_path")
    if np_:
        try:
            from nas_client import delete_file
            if not delete_file(np_):
                return False, "NAS 删除未确认成功，已保留报告图片"
        except Exception as e:
            return False, f"NAS 删除失败，已保留报告图片：{e}"
    lp = ph.get("local_path")
    if lp and os.path.exists(lp):
        try:
            os.remove(lp)
        except Exception as e:
            warn.append(f"本地删除失败:{e}")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE report_photos SET deleted=1, deleted_by=?, deleted_at=? WHERE id=?",
            (by, _now(), photo_id),
        )
        conn.commit()
    finally:
        conn.close()
    add_audit(by, "delete_photo", "report_photo", str(photo_id),
              f"类别={ph.get('category')} 文件={ph.get('filename')}")
    msg = "已删除" + ("（" + "；".join(warn) + "）" if warn else "")
    return True, msg


def reconcile_missing_nas_photo(photo_id, by=""):
    """NAS 已确认不存在时，仅清理本地缓存并软删除数据库记录。

    与用户主动删除不同，这里不再调用 NAS 删除接口，避免因 NAS 已经删除
    而把“缺失照片”误判成删除失败，导致报告页面持续回填旧记录。
    """
    ph = get_photo(photo_id)
    if not ph or ph.get("deleted"):
        return False, "照片不存在或已删除"
    lp = ph.get("local_path")
    if lp and os.path.exists(lp):
        try:
            os.remove(lp)
        except Exception:
            pass
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE report_photos SET deleted=1, deleted_by=?, deleted_at=? WHERE id=?",
            (by or "system:nas_reconcile", _now(), photo_id),
        )
        conn.commit()
    finally:
        conn.close()
    add_audit(by or "system", "reconcile_missing_photo", "report_photo", str(photo_id),
              f"NAS 文件缺失，自动从报告移除：{ph.get('filename')}")
    return True, "已从报告移除"


def link_photos_by_key(report_key, report_id):
    """保存报告后，把上传阶段用 report_key 关联的照片归属到正式 report_id。
    archive_only 的照片（旧品存档）不关联到报告，不入 PDF。"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE report_photos SET report_id=? WHERE report_key=? AND report_id IS NULL AND (archive_only IS NULL OR archive_only=0)",
            (report_id, report_key),
        )
        conn.commit()
    finally:
        conn.close()


def get_photo_sha_list(report_id):
    """返回该报告所有（未删）照片的 sha256 列表，用于 PDF↔NAS 一致性校验。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT sha256 FROM report_photos WHERE report_id=? AND deleted=0 AND sha256 IS NOT NULL",
            (report_id,),
        ).fetchall()
        return [r["sha256"] for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    # 简单自检
    init_online_report_table()
    print("online_reports 表已就绪")
    print("状态统计:", counts_by_status())
