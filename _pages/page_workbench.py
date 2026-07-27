"""统一品质工作台首页。

首页只负责汇总当前数据和跳转，不复制业务写入逻辑，避免原型页与正式页继续分叉。
"""
import base64
import os
from datetime import datetime

import streamlit as st

from config import get_logo_path
from database import (
    get_connection,
    get_dashboard_stats,
    get_change_stats,
    get_expiring_samples,
    get_inspection_dashboard_stats,
    get_recent_changes,
    get_recent_reports,
    get_sample_dashboard_stats,
    get_upcoming_maintenance,
)
from pages._utils import render_sidebar, render_topbar, ui_table


st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
st.session_state.current_page = "品质工作台"


def _safe_online_counts():
    result = {"草稿": 0, "待审核": 0, "已通过": 0, "已驳回": 0}
    conn = get_connection()
    try:
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM online_reports GROUP BY status"
        ).fetchall():
            result[row["status"]] = int(row["n"])
    except Exception:
        pass
    finally:
        conn.close()
    return result


# 工作台是实时决策面；短缓存避免跨页面操作后继续显示旧统计。
@st.cache_data(ttl=3, show_spinner=False)
def _load_data():
    return {
        "lab": get_dashboard_stats(),
        "sample": get_sample_dashboard_stats(),
        "change": get_change_stats(),
        "inspection": get_inspection_dashboard_stats(),
        "online": _safe_online_counts(),
        # The workbench is a triage surface, not the full inventory view.
        # Keep the preview short so the resource panel remains visible.
        "expiring": get_expiring_samples(30)[:5],
        "maintenance": get_upcoming_maintenance(30),
        "recent_reports": get_recent_reports(2),
        "recent_changes": get_recent_changes(2),
    }


def _go(path):
    if st.button("查看", key=f"go-{path}", width="content"):
        st.switch_page(path)


def _trend_values(end_value, n=7):
    """生成以 end_value 结尾的伪趋势数据（仅用于 sparkline 视觉，不替代真实统计）。"""
    if end_value <= 0:
        return [0] * n
    start = max(1, int(end_value * 0.55))
    return [start + int((end_value - start) * i / (n - 1)) for i in range(n)]


def _sparkline_svg(values, color, uid, width=92, height=34):
    """轻量 SVG sparkline（带渐变填充）。uid 用于区分同页多个渐变定义。"""
    if not values or all(v == 0 for v in values):
        return f'<svg class="wb-spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="opacity:.25"><line x1="0" y1="{height/2}" x2="{width}" y2="{height/2}" stroke="{color}" stroke-width="2" stroke-linecap="round"/></svg>'
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        max_v += 1
    pad = 4
    h_eff = height - 2 * pad
    pts = []
    n = len(values)
    step = (width - 2 * pad) / (n - 1) if n > 1 else 0
    for i, v in enumerate(values):
        x = pad + i * step
        y = pad + h_eff - (v - min_v) / (max_v - min_v) * h_eff
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = "".join(pts)
    area = f"M {pts[0]}" + "".join(f"L {p}" for p in pts) + f"L {width-pad},{height-pad} L {pad},{height-pad} Z"
    return (
        f'<svg class="wb-spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<defs><linearGradient id="sparkGrad{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.22"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#sparkGrad{uid})"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


data = _load_data()
lab = data["lab"]
sample = data["sample"]
change = data["change"]
inspection = data["inspection"]
online = data["online"]

with st.sidebar:
    render_sidebar(
        lab_stats=lab,
        inspection_stats=inspection,
        sample_stats=sample,
    )

render_topbar("品质工作台")

st.markdown(
    """
    <style>
    :root{--wb-ink:var(--qs-ink);--wb-muted:var(--qs-sub);--wb-line:var(--qs-line);--wb-bg:var(--qs-bg-soft);--wb-blue:var(--qs-primary);--wb-green:var(--qs-success);--wb-amber:var(--qs-warning);--wb-red:var(--qs-danger)}
    .wb-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}
    .wb-eyebrow{font-size:12px;color:var(--wb-blue);font-weight:800;letter-spacing:1.35px}
    .wb-top h1{margin:8px 0 9px;font-size:36px;line-height:1.1;letter-spacing:-1px;color:var(--wb-ink)}
    .wb-top p{margin:0;color:var(--wb-muted);font-size:14px}
    .wb-card{background:var(--qs-white);border:1px solid var(--qs-line);border-radius:16px;padding:20px;box-shadow:0 12px 30px rgba(19,42,70,.08),0 2px 5px rgba(19,42,70,.04);height:100%;min-height:126px}
    .wb-label{font-size:14px;color:var(--wb-muted);display:flex;justify-content:space-between}.wb-value{font-size:32px;font-weight:800;line-height:1.1;margin:0;color:var(--wb-ink)}.wb-hint{font-size:12px;color:var(--wb-muted);margin-top:4px}.wb-metric-row{display:flex;justify-content:space-between;align-items:flex-end;margin-top:10px;gap:10px}.wb-metric-text{flex:1;min-width:0}.wb-spark{width:92px;height:34px;flex:0 0 auto}
    .wb-section{font-size:17px;font-weight:750;color:var(--wb-ink);margin:26px 0 12px}
    .wb-panel{background:var(--qs-white);border:1px solid var(--qs-line);border-radius:18px;padding:20px;box-shadow:0 14px 34px rgba(19,42,70,.08),0 2px 6px rgba(19,42,70,.04);height:100%}
    .wb-panel h2{font-size:18px;margin:0 0 3px;color:var(--wb-ink)}.wb-panel small{color:var(--wb-muted);font-size:13px}
    .wb-row{border:1px solid var(--qs-line);border-radius:10px;padding:13px 14px;margin:9px 0;background:var(--qs-neutral-bg)}.wb-row strong{display:block;font-size:14px;color:var(--wb-ink)}.wb-row span{font-size:13px;color:var(--wb-muted)}
    .wb-pill{display:inline-block;border-radius:99px;padding:4px 8px;font-size:11px;font-weight:650}.wb-red{color:var(--wb-red);background:var(--qs-danger-bg)}.wb-amber{color:var(--wb-amber);background:var(--qs-warning-bg)}.wb-blue{color:var(--wb-blue);background:var(--qms-blue-soft)}.wb-green{color:var(--wb-green);background:var(--qs-success-bg)}
    .wb-flow{display:flex;align-items:center;margin:22px 0 15px}.wb-step{flex:1;text-align:center;position:relative}.wb-step:not(:last-child):after{content:'';position:absolute;top:13px;left:58%;width:84%;height:2px;background:var(--qs-line)}.wb-dot{position:relative;z-index:1;width:27px;height:27px;margin:auto;border-radius:50%;background:#dce5f1;color:var(--qs-sub);display:grid;place-items:center;font-size:12px;font-weight:700}.wb-step.done .wb-dot{background:var(--wb-green);color:#fff}.wb-step.current .wb-dot{background:var(--wb-blue);color:#fff;box-shadow:0 0 0 5px var(--qms-blue-soft)}.wb-step label{display:block;margin-top:7px;font-size:11px;color:var(--wb-muted)}
    .wb-queue{border:1px solid var(--qs-line);border-radius:11px;padding:14px 15px;margin:7px 0;background:#fbfcfe;min-height:64px}.wb-queue:hover{border-color:var(--qs-border-hover);background:var(--qms-blue-soft)}.wb-queue-date{font-size:13px;color:var(--wb-muted);line-height:1.4;padding-top:14px}.wb-queue-title{font-weight:750;color:var(--wb-ink);font-size:14px}.wb-queue-detail{font-size:13px;color:var(--wb-muted);margin-top:4px}.wb-queue-action{padding-top:17px}
    .wb-flow{margin-top:24px}.wb-flow .wb-step label{font-size:12px;color:var(--wb-ink)}
    .wb-review-action button{width:100% !important;max-width:none !important;height:42px !important;font-size:15px !important;font-weight:700 !important}
    [data-testid="stHorizontalBlock"]{gap:16px !important}
    div[data-testid="stMetric"]{background:var(--qs-white);border:1px solid var(--qs-line);border-radius:14px;padding:15px 17px;box-shadow:0 10px 24px rgba(19,42,70,.07)}
    .wb-section{margin-top:28px;margin-bottom:12px}
    section[data-testid="stSidebar"] .qms-datasource-card + div button{min-height:38px !important;border-radius:9px !important;font-weight:700 !important}
    @media (max-width: 1100px){.wb-top h1{font-size:32px}.wb-card{padding:16px}.wb-value{font-size:30px}}
    </style>
    """,
    unsafe_allow_html=True,
)

head, actions = st.columns([3.7, 1.3], gap="large")
with head:
    st.markdown(
        '<div class="wb-top"><div><div class="wb-eyebrow">QUALITY OPERATIONS</div><h1>品质工作台</h1><p>今天需要处理的品质任务、风险和实验室资源状态</p></div></div>',
        unsafe_allow_html=True,
    )
with actions:
    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    action_cols = st.columns(2, gap="small")
    with action_cols[0]:
        with st.popover("筛选", width="content"):
            st.caption("工作台筛选")
            st.selectbox("风险范围", ["全部", "仅显示待处理", "仅显示逾期"], key="wb-risk-filter")
            st.selectbox("报告范围", ["全部报告", "在线报告", "历史报告"], key="wb-report-filter")
    with action_cols[1]:
        if st.button("＋ 新建报告", type="primary", width="stretch", key="wb-new-report"):
            # 直接打开「检验报告 → 在线报告」，避免用户再手动找 Tab。
            st.query_params.update({"tab": "online", "new": "1"})
            st.switch_page("pages/page_reports.py")

cols = st.columns(4)
metrics = [
    ("待我审核", inspection["pending"] + online["待审核"], f"历史报告 {inspection['pending']} · 在线 QC {online['待审核']}", "var(--wb-blue)"),
    ("变更管理", change["total"], f"已确认 {change['confirmed']} · 未确认 {change['unconfirmed']}", "var(--wb-amber)"),
    ("样品风险", sample["expired"] + sample["near_expiry"], f"过期 {sample['expired']} · 30 天内到期 {sample['near_expiry']}", "var(--wb-red)"),
    ("实验室设备", lab["total"], f"可用 {lab['available']} · 使用中 {lab['in_use']} · 维修 {lab['maintenance']}", "var(--wb-green)"),
]
for idx, (col, (label, value, hint, color)) in enumerate(zip(cols, metrics)):
    with col:
        spark = _sparkline_svg(_trend_values(value), color, uid=f"m{idx}")
        st.markdown(f'<div class="wb-card"><div class="wb-label">{label}<span>↗</span></div><div class="wb-metric-row"><div class="wb-metric-text"><div class="wb-value" style="color:{color}">{value:,}</div><div class="wb-hint">{hint}</div></div>{spark}</div></div>', unsafe_allow_html=True)

left, right = st.columns([1.38, .92], gap="large")
with left:
    st.markdown('<div class="wb-panel"><h2>今日处理队列</h2><small>按紧急程度排序</small>', unsafe_allow_html=True)
    recent = data["recent_reports"][0] if data["recent_reports"] else {}
    sample_row = data["expiring"][0] if data["expiring"] else {}
    change_row = data["recent_changes"][0] if data["recent_changes"] else {}
    queue = [
        ("10:30", "今天", "出货检验报告", f"产品：{recent.get('product_name') or '待选择'} · 检验员：{recent.get('inspector') or '待分配'}", "待审核", "wb-blue", "pages/page_reports.py", "处理"),
        ("09:45", "今天", "在线报告与 PDF 纸档", f"在线报告草稿 {online['草稿']} 份 · PDF 生成后可打印给工厂签字", "待提交", "wb-amber", "pages/page_reports.py", "提交审核"),
        ("逾期", "样品风险", sample_row.get("sample_name") or "样品到期风险", f"SKU：{sample_row.get('sku') or '-'} · {sample['expired']} 个已过期，{sample['near_expiry']} 个即将到期", "样品风险", "wb-red", "pages/page_samples.py", "处理"),
        ("待确认", f"{change['unconfirmed']}条", "产品变更确认", f"最近记录：{change_row.get('brand') or '产品变更'} · 待确认记录 {change['unconfirmed']} 条", "待确认", "wb-red", "pages/page_changes.py", "查看"),
    ]
    for idx, (date_label, date_sub, title, detail, tag, tag_class, target, action) in enumerate(queue):
        q_date, q_body, q_tag, q_action = st.columns([.55, 2.7, .75, .75], gap="small")
        with q_date:
            st.markdown(f'<div class="wb-queue-date">{date_label}<br>{date_sub}</div>', unsafe_allow_html=True)
        with q_body:
            st.markdown(f'<div class="wb-queue"><div class="wb-queue-title">{title}</div><div class="wb-queue-detail">{detail}</div></div>', unsafe_allow_html=True)
        with q_tag:
            st.markdown(f'<div style="padding-top:12px"><span class="wb-pill {tag_class}">{tag}</span></div>', unsafe_allow_html=True)
        with q_action:
            st.markdown('<div class="wb-queue-action">', unsafe_allow_html=True)
            if st.button(action, key=f"wb-queue-{idx}", width="content"):
                st.switch_page(target)
            st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="wb-panel"><h2>检验报告流程</h2><small>纸质 PDF 在检验完成后生成，审核只负责归档</small><div class="wb-flow"><div class="wb-step done"><div class="wb-dot">1</div><label>填写在线报告</label></div><div class="wb-step done"><div class="wb-dot">2</div><label>生成 PDF 纸档</label></div><div class="wb-step current"><div class="wb-dot">3</div><label>主管审核</label></div><div class="wb-step"><div class="wb-dot">4</div><label>通过并归档</label></div></div>', unsafe_allow_html=True)
    pending_total = inspection["pending"] + online["待审核"]
    st.markdown(
        f'<div class="wb-row"><strong>草稿报告</strong><span>{online["草稿"]} 份</span></div>'
        f'<div class="wb-row"><strong>待主管审核</strong><span>{pending_total} 份（上传 {inspection["pending"]} · 在线 {online["待审核"]}）</span></div>'
        f'<div class="wb-row"><strong>已归档</strong><span>在线 {online["已通过"]} 份</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="wb-review-action">', unsafe_allow_html=True)
    if st.button("进入审核队列", type="primary", width="stretch", key="wb-review-queue"):
        st.switch_page("pages/page_reports.py")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="wb-section">样品到期风险</div>', unsafe_allow_html=True)
if data["expiring"]:
    table = [{"样品": row.get("sample_name") or "未命名样品", "SKU": row.get("sku") or "-", "到期日期": row.get("expiry_date") or "-", "状态": "已出库" if row.get("out_status") == "已出库" else ("已过期" if row.get("expiry_date", "") < datetime.now().strftime("%Y-%m-%d") else "即将到期")} for row in data["expiring"]]
    ui_table(table, width="stretch", hide_index=True)
else:
    st.success("当前没有 30 天内到期的在库样品")

st.markdown('<div class="wb-section">实验室资源</div>', unsafe_allow_html=True)
r1, r2, r3, r4 = st.columns(4)
with r1:
    with st.container(border=True):
        st.metric("📈 设备可用率", f"{round(lab['available'] / lab['total'] * 100) if lab['total'] else 0}%", f"{lab['available']} / {lab['total']} 台")
with r2:
    with st.container(border=True):
        st.metric("🔄 当前借用", lab["active_borrows"])
with r3:
    with st.container(border=True):
        st.metric("🔧 维护提醒", len(data["maintenance"]))
with r4:
    with st.container(border=True):
        st.metric("⚠️ 逾期归还", 0)

st.caption("统一工作台 · 数据来自当前本地运行库 · 业务页面均从左侧导航进入")
