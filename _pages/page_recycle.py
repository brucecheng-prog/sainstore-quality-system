"""
误删找回（回收站）- 找回被误删的业务记录并一键还原

覆盖全部 12 个删除入口（设备/人员/样品/变更/维护/借用/报告/分类/版本/活动等）。
删除时自动把整行快照存入 deleted_records；本页可按表/关键词/时间筛选并一键还原。
"""

import io
import json
import streamlit as st
import pandas as pd
from datetime import date

from database import (
    get_deleted_records,
    restore_deleted_record,
    purge_deleted_records,
)
from pages._utils import render_sidebar, render_topbar, ui_table, ui_empty_state

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")

st.session_state.current_page = "误删找回"
with st.sidebar:
    render_sidebar()
render_topbar("误删找回")

# 权限门禁：仅管理员可用（还原会写生产库）
is_admin = st.session_state.get("is_admin", False)
if not is_admin:
    ui_empty_state("无权限", "误删找回页面仅对管理员开放")
    st.stop()

# 表英文 → 中文
TABLE_CN = {
    "categories": "设备分类",
    "equipment": "设备台账",
    "users": "用户管理",
    "maintenance_records": "维护记录",
    "samples": "样品管理",
    "change_records": "变更管理",
    "inspection_reports": "检验报告",
    "changelog": "版本记录",
    "activity_log": "活动日志",
    "borrow_records": "借用归还",
}

st.markdown("""
<div class="qms-page-header"><div>
  <div class="qms-eyebrow">DATA & RECOVERY</div>
  <h1>误删找回（回收站）</h1>
  <p>任何业务记录被删除前都会自动留存整行快照，可在此按表 / 关键词 / 时间筛选并一键还原</p>
</div></div>
""", unsafe_allow_html=True)

st.caption(
    "覆盖设备、人员、样品、变更、维护、借用、报告、分类、版本、活动等全部删除入口。"
    "还原优先按原始 ID 恢复（保住附件引用与关联关系）；原 ID 已被占用时会用新 ID 还原。"
    "注意：检验报告的删除会同时清理 NAS 物理文件，还原仅恢复数据库记录，附件需另行补传。"
)

# ---- 筛选区 ----
with st.container(border=True):
    st.markdown('<div class="qms-section-title" style="margin-top:0"><span>筛选条件</span><small>缩小回收站范围</small></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        tbl_options = ["全部"] + list(TABLE_CN.keys())
        tbl_sel = st.selectbox(
            "数据表", tbl_options,
            format_func=lambda v: "全部" if v == "全部" else TABLE_CN.get(v, v),
        )
    with c2:
        keyword = st.text_input("关键词", placeholder="按摘要/内容搜索，如 SKU、品牌")
    with c3:
        limit = st.number_input("最多显示条数", min_value=20, max_value=2000, value=300, step=20)
    d1, d2, d3 = st.columns(3)
    with d1:
        d_from = st.date_input("删除起始日期", value=None)
    with d2:
        d_to = st.date_input("删除结束日期", value=None)
    with d3:
        show_restored = st.checkbox("包含已还原记录", value=False)

tbl_val = "" if tbl_sel == "全部" else tbl_sel
dfrom = d_from.strftime("%Y-%m-%d") if isinstance(d_from, date) else ""
dto = d_to.strftime("%Y-%m-%d") if isinstance(d_to, date) else ""

records = get_deleted_records(
    source_table=tbl_val,
    include_restored=show_restored,
    keyword=keyword.strip(),
    date_from=dfrom,
    date_to=dto,
    limit=int(limit),
)

if not records:
    st.info("回收站暂无符合条件的记录。被删除的业务数据会自动出现在这里，可随时还原。")
    st.stop()

# ---- 概览指标 ----
pending = [r for r in records if not r.get("restored")]
done = [r for r in records if r.get("restored")]
m1, m2, m3 = st.columns(3)
m1.metric("🗑️ 可还原记录", len(pending))
m2.metric("✅ 已还原", len(done))
m3.metric("📦 当前视图总数", len(records))

st.markdown("---")

# ---- 可还原记录：逐条卡片 + 还原按钮 ----
st.markdown('<div class="qms-section-title"><span>可还原记录</span><small>点开查看完整内容后一键还原</small></div>', unsafe_allow_html=True)

if not pending:
    st.success("当前筛选下没有待还原的记录。")
else:
    for r in pending:
        tcn = TABLE_CN.get(r["source_table"], r["source_table"])
        title = f"【{tcn}】原ID {r['record_id']} · {r.get('summary','') or '(无摘要)'}"
        with st.expander(title[:90]):
            meta1, meta2, meta3 = st.columns(3)
            meta1.markdown(f"**删除人**：{r.get('deleted_by','') or '—'}")
            meta2.markdown(f"**来源网络**：{r.get('deleted_network','') or '—'}")
            meta3.markdown(f"**删除时间**：{r.get('deleted_at','') or '—'}")
            st.markdown(f"**部署环境**：{r.get('deleted_deployment','') or '—'}")

            # 展示整行内容
            try:
                data = json.loads(r.get("record_json") or "{}")
            except Exception:
                data = {}
            if data:
                df_detail = pd.DataFrame(
                    [{"字段": k, "值": ("" if v is None else str(v))} for k, v in data.items()]
                )
                ui_table(df_detail, width="stretch", height=min(360, 44 + 30 * len(df_detail)))
            else:
                st.warning("该记录快照内容为空。")

            btn_col, _ = st.columns([1, 3])
            with btn_col:
                if st.button("♻️ 还原此记录", key=f"restore_{r['id']}", type="primary"):
                    ok, msg = restore_deleted_record(r["id"])
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

# ---- 已还原历史 ----
if show_restored and done:
    st.markdown("---")
    st.markdown('<div class="qms-section-title"><span>已还原历史</span><small>仅供追溯</small></div>', unsafe_allow_html=True)
    dfd = pd.DataFrame(done)
    dfd = dfd.rename(columns={
        "source_table": "数据表", "record_id": "原ID", "summary": "摘要",
        "deleted_by": "删除人", "deleted_at": "删除时间",
        "restored_by": "还原人", "restored_at": "还原时间",
    })
    dfd["数据表"] = dfd["数据表"].map(lambda v: TABLE_CN.get(v, v))
    show_cols = ["数据表", "原ID", "摘要", "删除人", "删除时间", "还原人", "还原时间"]
    show_cols = [c for c in show_cols if c in dfd.columns]
    ui_table(dfd[show_cols], width="stretch", height=360)

# ---- 导出 + 清理 ----
st.markdown("---")
col_e1, col_e2 = st.columns(2)
with col_e1:
    exp = pd.DataFrame(records)
    if not exp.empty:
        csv = exp.to_csv(index=False).encode("utf-8-sig")
        st.download_button("导出当前视图 CSV", csv, "recycle_bin.csv", "text/csv")

with col_e2:
    with st.popover("🧹 清理回收站"):
        st.caption("清理不会影响已还原到业务表中的数据，仅移除回收站的快照。")
        pd_date = st.date_input("清理此日期之前删除的记录", value=None, key="purge_date")
        only_done = st.checkbox("仅清理已还原的快照", value=True, key="purge_only_restored")
        if st.button("确认清理", type="secondary"):
            before = pd_date.strftime("%Y-%m-%d") if isinstance(pd_date, date) else ""
            n = purge_deleted_records(before_date=before, only_restored=only_done)
            st.success(f"已清理 {n} 条回收站快照")
            st.rerun()
