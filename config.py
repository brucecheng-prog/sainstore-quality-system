"""
部署相关共享配置
统一处理路径、Logo 和可选本地分析页面，避免硬编码 Mac 路径。
"""

import os
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def get_logo_path():
    """按优先级返回可用 Logo 路径。"""
    candidates = [
        os.environ.get("COMPANY_LOGO_PATH", "").strip(),
        os.path.join(BASE_DIR, "logo.png"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def get_optional_analytics_pages():
    """返回当前机器上真实存在的附加分析页面。"""
    # 数据分析系统是独立产品。品质系统仅在部署时明确配置
    # LOCAL_ANALYTICS_DIR 才加载其页面，避免本机目录偶然存在时隐式串入。
    analytics_dir = os.environ.get("LOCAL_ANALYTICS_DIR", "").strip()
    if not analytics_dir:
        return []

    page_specs = [
        ("qic_summary.py", "数据汇总", "📈"),
        ("qic_sku.py", "SKU分析", "🔍"),
        ("qic_bg.py", "BG分析", "🏢"),
        ("qic_bu.py", "BU分析", "📂"),
        ("qic_brand.py", "品牌分析", "🏷️"),
        ("qic_supplier.py", "供应商分析", "🚚"),
        ("qic_pareto.py", "帕累托分析", "📐"),
        ("qic_search.py", "搜索中心", "🔎"),
        ("qic_export.py", "导出数据", "📤"),
    ]

    pages = []
    for filename, title, icon in page_specs:
        page_path = os.path.join(analytics_dir, filename)
        if os.path.exists(page_path):
            pages.append((page_path, title, icon))
    return pages


# ── 管理员角色（唯一来源）──
# 旧代码在多处硬编码 bruce.cheng@sainstore.com 来判断管理员，导致「角色」散落、
# 且无法跟随 data/auth.json 的 admin_emails 配置。现统一收口到本函数：
# - 优先读取 data/auth.json 的 admin_emails（生产环境由管理后台维护）；
# - 本地开发环境额外兜底授予开发者邮箱管理员权限，便于本地调试。
DEV_ADMIN_EMAIL = "bruce.cheng@sainstore.com"


def is_local_development() -> bool:
    """True only for the explicitly configured Mac developer runtime."""
    return (
        os.environ.get("QMS_ENVIRONMENT", "").strip().lower() == "development"
        and sys.platform == "darwin"
        and not os.environ.get("FORCE_PRODUCTION")
    )


def is_admin_email(email):
    """判断给定邮箱是否为管理员——角色判定的唯一来源。

    所有页面（含侧边栏导航可见性）都应调用本函数，不要在业务代码里再硬编码邮箱。
    """
    if not email:
        return False
    email = str(email).strip().lower()
    try:
        import json
        auth_path = os.path.join(DATA_DIR, "auth.json")
        if os.path.exists(auth_path):
            with open(auth_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if email in [e.lower() for e in cfg.get("admin_emails", [])]:
                return True
    except Exception:
        pass
    # 开发者便利权限只存在于明确的本机开发环境。生产或局域网入口
    # 必须由 auth.json 的管理员名单授权，不能因邮箱相同而自动提权。
    return is_local_development() and email == DEV_ADMIN_EMAIL.lower()
