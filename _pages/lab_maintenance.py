"""
实验室设备管理系统 - 维护记录页面
"""

import streamlit as st
import pandas as pd
from datetime import date
from database import (
    init_db, get_maintenance_records, add_maintenance, update_maintenance,
    delete_maintenance, get_upcoming_maintenance, get_equipment_for_select,
    get_all_equipment
)

st.set_page_config(page_title="维护记录", page_icon="🔧", layout="wide")
init_db()

# Session State
for key, default in [('mt_edit_id', None), ('mt_page', 1)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("🔧 维护记录管理")

tab1, tab2 = st.tabs(["📝 维护记录", "📅 保养计划"])

# ==================== Tab 1: 维护记录 ====================
with tab1:
    # 添加/编辑表单
    mt_editing = st.session_state.mt_edit_id is not None

    with st.expander("✏️ 编辑维护记录" if mt_editing else "➕ 添加维护记录", expanded=mt_editing):
        mt_existing = {}
        if mt_editing:
            records, _ = get_maintenance_records(per_page=100)
            for r in records:
                if r['id'] == st.session_state.mt_edit_id:
                    mt_existing = r
                    break

        with st.form("maintenance_form"):
            # 设备选择
            eq_options = get_equipment_for_select()
            eq_map = {e['id']: f"[{e['serial_number']}] {e['name']}" for e in eq_options}
            default_eq = mt_existing.get('equipment_id', list(eq_map.keys())[0] if eq_map else None)
            eq_id = st.selectbox(
                "设备 *", list(eq_map.keys()),
                format_func=lambda x: eq_map[x],
                index=list(eq_map.keys()).index(default_eq) if default_eq in eq_map else 0
            )

            col1, col2, col3 = st.columns(3)
            with col1:
                mt_date = st.date_input(
                    "维护日期",
                    value=pd.to_datetime(mt_existing['maintenance_date']) if mt_existing.get('maintenance_date') else date.today()
                )
                mt_types = ['定期保养', '故障维修', '校准', '其他']
                default_type = mt_existing.get('maintenance_type', '定期保养')
                mt_type = st.selectbox(
                    "维护类型",
                    mt_types,
                    index=mt_types.index(default_type) if default_type in mt_types else 0
                )
            with col2:
                mt_cost = st.number_input("费用 (¥)", min_value=0.0, step=100.0,
                                          value=float(mt_existing.get('cost', 0)))
                mt_tech = st.text_input("技术人员", value=mt_existing.get('technician', ''))
            with col3:
                mt_statuses = ['已完成', '进行中', '计划中']
                default_mt_status = mt_existing.get('status', '已完成')
                mt_status = st.selectbox(
                    "状态",
                    mt_statuses,
                    index=mt_statuses.index(default_mt_status) if default_mt_status in mt_statuses else 0
                )
                next_date = None
                if mt_existing.get('next_maintenance_date'):
                    try:
                        next_date = pd.to_datetime(mt_existing['next_maintenance_date'])
                    except:
                        pass
                next_mt = st.date_input("下次维护日期", value=next_date)

            mt_desc = st.text_area("维护描述", value=mt_existing.get('description', ''))
            mt_notes = st.text_area("备注", value=mt_existing.get('notes', ''))

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submitted = st.form_submit_button("✅ 保存", use_container_width=True, type="primary")

        if submitted:
            data = {
                'equipment_id': eq_id,
                'maintenance_date': str(mt_date),
                'maintenance_type': mt_type,
                'description': mt_desc,
                'cost': mt_cost,
                'technician': mt_tech,
                'next_maintenance_date': str(next_mt) if next_mt else '',
                'status': mt_status,
                'notes': mt_notes
            }
            if mt_editing:
                ok, msg = update_maintenance(st.session_state.mt_edit_id, data)
            else:
                ok, msg = add_maintenance(data)
            if ok:
                st.success(msg)
                st.session_state.mt_edit_id = None
                st.rerun()
            else:
                st.error(msg)

        # 取消按钮在表单外部，直接重置
        if mt_editing:
            col_c1, col_c2 = st.columns([5, 1])
            with col_c2:
                if st.button("❌ 取消编辑", use_container_width=True, key="cancel_mt_edit"):
                    st.session_state.mt_edit_id = None
                    st.rerun()

    # 维护记录列表
    records, total = get_maintenance_records(page=st.session_state.mt_page, per_page=15)
    st.markdown(f"共 **{total}** 条维护记录")

    if records:
        # 勾选框批量操作
        selected_ids = []
        df = pd.DataFrame(records)
        df_display = df[[
            'equipment_name', 'serial_number', 'maintenance_date',
            'maintenance_type', 'description', 'cost', 'technician',
            'next_maintenance_date', 'status', 'id'
        ]].copy()
        df_display.columns = [
            '设备名称', '编号', '维护日期', '类型', '描述',
            '费用(¥)', '技术人员', '下次维护', '状态', 'id'
        ]

        def color_mt_status(val):
            colors = {'已完成': 'background-color: #d4edda', '进行中': 'background-color: #fff3cd',
                       '计划中': 'background-color: #d1ecf1'}
            return colors.get(val, '')

        styled = df_display.style.map(color_mt_status, subset=['状态'])
        st.dataframe(styled, use_container_width=True, hide_index=True, height=450,
                     column_config={'id': None})

        # 勾选 + 操作
        col_sel, col_btn1, col_btn2 = st.columns([3, 1, 1])
        mt_options = {r['id']: f"[{r['id']}] {r['equipment_name']} - {r['maintenance_date']} ({r['maintenance_type']})" for r in records}
        with col_sel:
            selected_mt = st.selectbox("选择维护记录", list(mt_options.keys()),
                                        format_func=lambda x: mt_options[x], key='sel_mt',
                                        label_visibility="collapsed")
        with col_btn1:
            if st.button("✏️ 编辑", use_container_width=True):
                st.session_state.mt_edit_id = selected_mt
                st.rerun()
        with col_btn2:
            if st.button("🗑️ 删除", use_container_width=True):
                ok, msg = delete_maintenance(selected_mt)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        # 分页
        total_pages = max(1, (total + 14) // 15)
        col_pg1, col_pg2, col_pg3 = st.columns([2, 1, 2])
        with col_pg2:
            pg = st.selectbox("页码", range(1, total_pages + 1),
                              index=st.session_state.mt_page - 1,
                              key='mt_page_sel', label_visibility="collapsed")
            if pg != st.session_state.mt_page:
                st.session_state.mt_page = pg
                st.rerun()
    else:
        st.info("暂无维护记录")

# ==================== Tab 2: 保养计划 ====================
with tab2:
    st.subheader("📅 保养计划")

    days = st.slider("查看未来天数内的保养计划", 7, 90, 30, key='mt_days')
    upcoming = get_upcoming_maintenance(days)

    if upcoming:
        st.markdown(f"未来 **{days}** 天内共有 **{len(upcoming)}** 条保养计划：")

        df_up = pd.DataFrame(upcoming)
        df_display = df_up[[
            'equipment_name', 'serial_number', 'maintenance_type',
            'next_maintenance_date', 'technician', 'notes'
        ]].copy()
        df_display.columns = ['设备名称', '编号', '类型', '下次维护', '技术人员', '备注']
        df_display = df_display.sort_values('下次维护')

        st.dataframe(df_display, use_container_width=True, hide_index=True, height=400)

        # 导出保养计划
        from io import BytesIO
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_display.to_excel(writer, index=False, sheet_name='保养计划')
        st.download_button(
            "📥 导出保养计划",
            buffer.getvalue(),
            f"保养计划_{date.today()}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    else:
        st.success(f"✅ 未来 {days} 天内无保养计划，设备状态良好！")
