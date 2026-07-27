"""
品质系统管理 - 驻厂登记（品质日常管理）
全员可编辑：登记 / 列表 / 修改 / 删除（删除进入回收站可找回）/ 导入 / 导出。
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date

import database as database_module
from database import (
    init_db, get_factory_registrations,
    add_factory_registration, update_factory_registration,
    delete_factory_registration,
    get_factory_stats, get_factory_freq_by_staff,
    get_factory_freq_by_factory, get_factory_freq_by_month,
    get_factory_freq_by_type, get_connection,
)

from pages._utils import (
    render_sidebar, render_topbar, render_import_export_buttons,
    ui_empty_state, ui_data_editor,
)

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

st.session_state.current_page = "驻厂登记"
with st.sidebar:
    render_sidebar()
render_topbar("驻厂登记")

st.title("驻厂登记")

# 字段顺序（与数据库列一致）
TEMPLATE_COLS = [
    'register_date', 'factory_name', 'onsite_staff', 'trip_type',
    'trip_days', 'po_no', 'sku', 'product_project', 'is_empty_run',
    'is_recheck', 'is_delay', 'delay_days', 'return_reason',
    'inspection_result', 'purpose', 'notes',
]
DISPLAY_COLS = ['id'] + TEMPLATE_COLS
TYPE_OPTS = ["验货", "测试", "异常处理", "审厂", "品质会议", "试产跟线", "其他"]


def _fr_import_handler(import_df, db_conn=None):
    """导入处理器：按模板列逐行写入，缺失工厂名称的行跳过。"""
    inserted = 0
    for _, row in import_df.iterrows():
        data = {}
        for c in TEMPLATE_COLS:
            v = row.get(c, '')
            if c in ('trip_days', 'delay_days'):
                try:
                    v = int(v) if v not in (None, '', 'nan') else 0
                except Exception:
                    v = 0
            else:
                v = '' if v is None else str(v).strip()
            data[c] = v
        if not data.get('factory_name', '').strip():
            continue
        add_factory_registration(data)
        inserted += 1
    return inserted, f"已导入 {inserted} 条驻厂登记"


# ==================== 导入 / 导出 / 模板下载 ====================
conn = get_connection()
fr_template = pd.DataFrame(columns=TEMPLATE_COLS)
render_import_export_buttons(
    conn,
    'factory_registrations',
    fr_template,
    key_prefix='fr_',
    import_handler=_fr_import_handler,
    import_help_text="请使用上方「下载导入模板」获取标准格式，按模板填写后上传。"
    "PO 单号 / SKU / 驻厂人员支持一行一个（多行）。",
)
conn.close()

# 首次加载提示
_fr_check, _ = get_factory_registrations(per_page=1)
if not _fr_check:
    ui_empty_state(
        "当前无驻厂登记记录",
        hint="可在上方「下载导入模板」批量导入，或使用下方「驻厂登记」Tab 逐条登记。",
    )

tab1, tab2 = st.tabs(["驻厂登记", "数据记录"])

# ==================== Tab 1: 登记 ====================
with tab1:
    st.subheader("驻厂登记")
    with st.form("fr_form", clear_on_submit=True):
        # ── 第 1 行：日期 / 工厂 / 出差类型 ──
        r1, r2, r3 = st.columns(3)
        with r1:
            register_date = st.date_input(
                "登记日期 *", value=date.today(), key='fr_register_date')
        with r2:
            factory_name = st.text_input(
                "工厂名称 *", key='fr_factory',
                placeholder="例如：东莞XX工厂")
        with r3:
            trip_type = st.selectbox(
                "出差类型", TYPE_OPTS, key='fr_trip_type')

        # ── 第 2 行：驻厂人员 / PO / SKU（多行）──
        s1, s2, s3 = st.columns(3)
        with s1:
            onsite_staff = st.text_area(
                "驻厂人员（多人换行）", key='fr_staff',
                height=68, placeholder="张三\n李四")
        with s2:
            po_no = st.text_area(
                "PO 单号（多个换行）", key='fr_po',
                height=68, placeholder="PO123\nPO456")
        with s3:
            sku = st.text_area(
                "SKU（多个换行）", key='fr_sku',
                height=68, placeholder="SKU-A\nSKU-B")

        # ── 第 3 行：产品 / 天数 / 验货结果 ──
        t1, t2, t3 = st.columns(3)
        with t1:
            product_project = st.text_input(
                "产品/项目", key='fr_product')
        with t2:
            trip_days = st.number_input(
                "出差天数", min_value=0, value=0, step=1,
                key='fr_trip_days')
        with t3:
            inspection_result = st.selectbox(
                "验货结果", ["Pass", "Fail", "待定"],
                key='fr_inspection_result')

        # ── 第 4 行：执行情况（不变）──
        e1, e2, e3 = st.columns(3)
        with e1:
            is_empty_run = st.selectbox(
                "是否空跑", ["否", "是"], key='fr_empty')
        with e2:
            is_recheck = st.selectbox(
                "是否复检", ["否", "是"], key='fr_recheck')
        with e3:
            is_delay = st.selectbox(
                "是否交期延误", ["否", "是"], key='fr_delay')

        # ── 条件字段 + 底部文本（全宽）──
        delay_days = 0
        if is_delay == "是":
            delay_days = st.number_input(
                "延误天数", min_value=0, value=0, step=1,
                key='fr_delay_days')

        return_reason = st.text_input("退货原因", key='fr_return')
        purpose = st.text_area("驻厂目的", key='fr_purpose', height=60)
        notes = st.text_area("备注", key='fr_notes', height=60)

        if st.form_submit_button("提交登记", type="primary", width="stretch"):
            if not factory_name.strip():
                st.error("工厂名称不能为空！")
            else:
                ok, msg = add_factory_registration({
                    'register_date': str(register_date),
                    'factory_name': factory_name.strip(),
                    'onsite_staff': onsite_staff.strip(),
                    'trip_type': trip_type,
                    'trip_days': int(trip_days),
                    'po_no': po_no.strip(),
                    'sku': sku.strip(),
                    'product_project': product_project.strip(),
                    'is_empty_run': is_empty_run,
                    'is_recheck': is_recheck,
                    'is_delay': is_delay,
                    'delay_days': int(delay_days),
                    'return_reason': return_reason.strip(),
                    'inspection_result': inspection_result,
                    'purpose': purpose.strip(),
                    'notes': notes.strip(),
                })
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

# ==================== Tab 2: 数据记录 ====================
with tab2:
    st.subheader("数据记录")

    # 实时统计卡片
    stats = get_factory_stats()
    total = stats.get('total', 0)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("📋 总登记数", f"{total} 条")
    with m2:
        st.metric("✅ Pass", f"{stats.get('onsite', 0)} 条")
    with m3:
        st.metric("❌ Fail", f"{stats.get('ended', 0)} 条")
    with m4:
        st.metric("⚠️ 空跑 / 复检 / 延误",
                   f"{stats.get('empty', 0)} / {stats.get('recheck', 0)} / {stats.get('delay', 0)}")

    # 搜索与筛选
    _fc = get_connection()
    _factories = [r[0] for r in _fc.execute(
        "SELECT DISTINCT factory_name FROM factory_registrations "
        "WHERE factory_name<>'' ORDER BY factory_name").fetchall()]
    _fc.close()

    c1, c2, c3, c4 = st.columns([2.4, 1.4, 1.4, 1.4])
    with c1:
        search = st.text_input(
            "搜索", placeholder="工厂/人员/PO/SKU",
            label_visibility="collapsed")
    with c2:
        factory_filter = st.selectbox(
            "工厂", ["全部"] + _factories, label_visibility="collapsed")
    with c3:
        inspection_result_filter = st.selectbox(
            "验货结果", ["全部", "Pass", "Fail", "待定"], label_visibility="collapsed")
    with c4:
        type_filter = st.selectbox(
            "出差类型", ["全部"] + TYPE_OPTS, label_visibility="collapsed")

    q1, q2, q3 = st.columns(3)
    with q1:
        only_empty = st.checkbox("仅看空跑")
    with q2:
        only_recheck = st.checkbox("仅看复检")
    with q3:
        only_delay = st.checkbox("仅看延误")

    rows, total = get_factory_registrations(
        search=search,
        factory=factory_filter if factory_filter != "全部" else '',
        inspection_result=inspection_result_filter if inspection_result_filter != "全部" else '',
        trip_type=type_filter if type_filter != "全部" else '',
    )
    if only_empty:
        rows = [r for r in rows if r.get('is_empty_run') == '是']
    if only_recheck:
        rows = [r for r in rows if r.get('is_recheck') == '是']
    if only_delay:
        rows = [r for r in rows if r.get('is_delay') == '是']

    if rows:
        data = []
        for r in rows:
            data.append({c: r.get(c, '') for c in DISPLAY_COLS})
        df_fr = pd.DataFrame(data)

        col_config = {
            'id': st.column_config.Column(label='ID', disabled=True),
            'trip_days': st.column_config.NumberColumn(label='天数', disabled=False),
            'delay_days': st.column_config.NumberColumn(label='延误天', disabled=False),
        }
        _disp = min(50, len(df_fr))
        editor_key = 'fr_editor'
        edited = ui_data_editor(
            df_fr,
            key=editor_key,
            width="stretch",
            num_rows="dynamic",
            column_config=col_config,
            column_order=DISPLAY_COLS,
            hide_index=True,
            height=min(38 * _disp + 40, 760),
        )

        b1, b2 = st.columns([1, 3])
        with b1:
            if st.button("保存修改", key='fr_save_btn', width="stretch", type="primary"):
                try:
                    changes = False
                    session_data = st.session_state.get(editor_key, {})
                    edited_rows = session_data.get("edited_rows", {})
                    deleted_rows = session_data.get("deleted_rows", [])
                    added_rows = session_data.get("added_rows", [])

                    if edited_rows:
                        for ridx_str, edits in edited_rows.items():
                            ridx = int(ridx_str)
                            if ridx >= len(df_fr):
                                continue
                            pk = int(df_fr.iloc[ridx]['id'])
                            clean = {c: v for c, v in edits.items() if c != 'id'}
                            for ic in ('trip_days', 'delay_days'):
                                if ic in clean:
                                    try:
                                        clean[ic] = int(clean[ic])
                                    except Exception:
                                        clean[ic] = 0
                            update_factory_registration(pk, clean)
                        changes = True
                        st.toast(f"已更新 {len(edited_rows)} 处修改")

                    if added_rows:
                        for added in added_rows:
                            if not any(str(v).strip() for v in added.values()):
                                continue
                            clean = {k: v for k, v in added.items() if k != 'id'}
                            for ic in ('trip_days', 'delay_days'):
                                if ic in clean:
                                    try:
                                        clean[ic] = int(clean[ic])
                                    except Exception:
                                        clean[ic] = 0
                            if not clean.get('factory_name', '').strip():
                                continue
                            add_factory_registration(clean)
                        changes = True
                        st.toast(f"已新增 {len(added_rows)} 条")

                    if deleted_rows:
                        for ridx in sorted(deleted_rows, reverse=True):
                            if ridx < len(df_fr):
                                pk = int(df_fr.iloc[ridx]['id'])
                                delete_factory_registration(pk)
                        changes = True
                        st.toast(f"已删除 {len(deleted_rows)} 条（进入回收站）")

                    if changes:
                        st.rerun()
                except Exception as e:
                    st.error(f"操作失败：{e}")
        with b2:
            st.caption("双击单元格编辑 | 勾选行 + Delete 删除（可于『误删找回』还原）| 底部空行新增")

        # ==================== 出差频次统计 ====================
        st.markdown("---")
        st.subheader("出差频次统计")

        # 异常指标监控
        st.markdown("**异常指标监控**")
        a1, a2, a3 = st.columns(3)
        _den = total if total else 1
        with a1:
            st.metric("空跑率", f"{stats.get('empty',0)/_den*100:.1f}%")
        with a2:
            st.metric("复检率", f"{stats.get('recheck',0)/_den*100:.1f}%")
        with a3:
            st.metric("交期延误率", f"{stats.get('delay',0)/_den*100:.1f}%")

        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**按人员统计（次数 / 累计天数）**")
            staff_data = get_factory_freq_by_staff()
            if staff_data:
                df_staff = pd.DataFrame(staff_data)
                fig_staff = px.bar(
                    df_staff, x='staff', y='count',
                    hover_data=['days'],
                    labels={'count': '驻厂次数', 'staff': '人员', 'days': '累计天数'},
                    color_discrete_sequence=['#2563eb'],
                )
                fig_staff.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
                st.plotly_chart(fig_staff, use_container_width=True)
            else:
                ui_empty_state("暂无人员数据")

        with g2:
            st.markdown("**按工厂统计（被驻厂次数）**")
            factory_data = get_factory_freq_by_factory()
            if factory_data:
                df_factory = pd.DataFrame(factory_data)
                fig_factory = px.bar(
                    df_factory, x='factory', y='count',
                    labels={'count': '次数', 'factory': '工厂'},
                    color_discrete_sequence=['#16a34a'],
                )
                fig_factory.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
                st.plotly_chart(fig_factory, use_container_width=True)
            else:
                ui_empty_state("暂无工厂数据")

        g3, g4 = st.columns(2)
        with g3:
            st.markdown("**按月趋势（驻厂次数）**")
            month_data = get_factory_freq_by_month()
            if month_data:
                df_month = pd.DataFrame(month_data)
                fig_month = px.line(
                    df_month, x='month', y='count', markers=True,
                    labels={'count': '次数', 'month': '月份'},
                    color_discrete_sequence=['#ea580c'],
                )
                fig_month.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
                st.plotly_chart(fig_month, use_container_width=True)
            else:
                ui_empty_state("暂无月度数据")

        with g4:
            st.markdown("**按出差类型统计**")
            type_data = get_factory_freq_by_type()
            if type_data:
                df_type = pd.DataFrame(type_data)
                fig_type = px.bar(
                    df_type, x='type', y='count',
                    labels={'count': '次数', 'type': '出差类型'},
                    color_discrete_sequence=['#7C3AED'],
                )
                fig_type.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
                st.plotly_chart(fig_type, use_container_width=True)
            else:
                ui_empty_state("暂无类型数据")
    else:
        ui_empty_state("暂无符合条件的驻厂登记记录", hint="尝试调整搜索关键词或筛选条件。")
