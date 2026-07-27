"""
操作审计 - 追踪同事在内网 / 外网对业务数据的增删改操作
"""

import io
import streamlit as st
import pandas as pd
from datetime import date

from database import get_operation_logs, get_audit_source
from pages._utils import render_sidebar, render_topbar, ui_table, ui_empty_state

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")

# 渲染共享侧边栏导航（与其他页面一致）
st.session_state.current_page = "操作审计"
with st.sidebar:
    render_sidebar()
render_topbar("操作审计")

# F5 权限门禁：操作审计仅对管理员开放
is_admin = st.session_state.get("is_admin", False)
if not is_admin:
    ui_empty_state("无权限", "操作审计页面仅对管理员开放")
    st.stop()


st.markdown("""
<div class="qms-page-header"><div>
  <div class="qms-eyebrow">DATA & AUDIT</div>
  <h1>操作审计日志</h1>
  <p>追踪业务数据的新增、修改、删除与审核动作，保留操作者、来源网络和时间证据</p>
</div></div>
""", unsafe_allow_html=True)

# 数据源徽章：本机生产库 / 实时直连 Win 生产库 / 回退本地库
_src = get_audit_source()
if _src == "production":
    st.success(
        "本机生产数据库（实时）—— 当前运行在 Win 生产服务器，读取的即是生产库，数据最新",
        icon=None,
    )
elif _src == "remote":
    st.success(
        "实时数据源：直连 Win 生产库（只读）—— 同事操作即时可见，无需手动同步",
        icon=None,
    )
else:
    st.info(
        "当前读取本地库（未检测到 Win 生产库连接，已自动回退本地）",
        icon=None,
    )

st.caption(
    "记录同事在 Win 生产服务器上对业务数据（报告 / 设备 / 样品 / 借用 / 变更 / 维护 / 人员）"
    "的增删改操作，并区分【内网】与【外网】来源。Mac 本地默认实时直连 Win 生产库只读，"
    "打开即最新；若 Win 不可达则自动回退本地库。"
)

# ---- 筛选区（紧凑卡片）----
with st.container(border=True):
    st.markdown('<div class="qms-section-title" style="margin-top:0"><span>筛选条件</span><small>按时间、操作者和数据表缩小范围</small></div>', unsafe_allow_html=True)
    # 第一行：操作人 / 关键词 / 开始日期
    c1, c2, c3 = st.columns(3)
    with c1:
        operator = st.text_input("操作人", placeholder="留空 = 全部")
    with c2:
        action = st.text_input("动作关键词", placeholder="如 新增 / 删除 / 审核")
    with c3:
        d_from = st.date_input("开始日期", value=None)
    # 第二行：来源网络 / 数据表 / 结束日期 / 最大条数
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        network = st.selectbox("来源网络", ["全部", "内网", "外网"])
    with d2:
        target_table = st.selectbox(
            "数据表",
            ["全部", "online_reports", "inspection_reports", "equipment", "samples", "borrow_records",
             "change_records", "maintenance_records", "users", "sample_outbound"],
        )
    with d3:
        d_to = st.date_input("结束日期", value=None)
    with d4:
        limit = st.number_input("最多显示条数", min_value=50, max_value=5000, value=500, step=50)

net_val = "" if network == "全部" else network
tbl_val = "" if target_table == "全部" else target_table
dfrom = d_from.strftime("%Y-%m-%d") if isinstance(d_from, date) else ""
dto = d_to.strftime("%Y-%m-%d") if isinstance(d_to, date) else ""

logs = get_operation_logs(
    limit=int(limit),
    operator=operator.strip(),
    network=net_val,
    action=action.strip(),
    target_table=tbl_val,
    date_from=dfrom,
    date_to=dto,
)

if not logs:
    st.info("暂无符合条件的操作记录。同事在 Win 服务器上的增删改操作会出现在这里。")
else:
    df = pd.DataFrame(logs)
    df = df.rename(columns={
        "created_at": "时间", "operator": "操作人", "action": "动作",
        "target_table": "数据表", "record_id": "记录ID", "network": "来源网络",
        "deployment": "部署", "detail": "详情", "ip_address": "IP",
    })
    show_cols = ["时间", "操作人", "动作", "数据表", "记录ID", "来源网络", "部署", "详情", "IP"]
    df = df[show_cols]

    def net_badge(v):
        if v == "内网":
            return "内网"
        if v == "外网":
            return "外网"
        return f"{v}"
    df["来源网络"] = df["来源网络"].map(net_badge)

    # 数据表名：英文 → 中文映射
    TABLE_CN = {
        "online_reports": "在线报告",
        "inspection_reports": "检验报告",
        "equipment": "设备台账",
        "samples": "样品管理",
        "borrow_records": "借用归还",
        "change_records": "变更管理",
        "maintenance_records": "维护记录",
        "users": "用户管理",
        "sample_outbound": "样品出库",
    }
    df["数据表"] = df["数据表"].map(lambda v: TABLE_CN.get(v, v))

    # 空值美化：详情/IP 为空时显示 —
    df["详情"] = df["详情"].fillna("—").replace("", "—")
    df["IP"] = df["IP"].fillna("—").replace("", "—")

    # ---- 概览指标 ----
    m1, m2, m3 = st.columns(3)
    m1.metric("🔍 总操作数", len(df))
    m2.metric("🏠 内网操作", int((df["来源网络"].str.contains("内网")).sum()))
    m3.metric("🌐 外网操作", int((df["来源网络"].str.contains("外网")).sum()))

    st.markdown(f"**共 {len(df)} 条记录**")
    ui_table(df, width="stretch", height=520)

    # ---- 导出 ----
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("导出 CSV", csv, "operation_audit.csv", "text/csv")
    with col_e2:
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            st.download_button(
                "导出 Excel",
                buf.getvalue(),
                "operation_audit.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.warning(f"Excel 导出不可用：{e}")
