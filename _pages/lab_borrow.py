"""
实验室设备管理系统 - 借用归还（设备出库/归还）
"""

import streamlit as st
import pandas as pd
from datetime import date
from database import (
    init_db, get_equipment_for_select, get_users,
    checkout_equipment, return_equipment, get_borrow_records,
    add_user, update_user, delete_user, get_users as get_all_users
)

st.set_page_config(page_title="借用归还", page_icon="📤", layout="wide")
init_db()

for key, default in [('user_edit_id', None)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("📤 设备借用出库 & 归还")

tab1, tab2, tab3 = st.tabs(["📤 借用出库", "📥 归还入库", "📜 借用记录"])

# ==================== Tab 1: 借用出库 ====================
with tab1:
    st.subheader("📤 设备借用出库")
    st.caption("⚠️ 此功能用于设备物理借出实验室。内部测试预约请使用「使用登记」。")

    equipment_options = get_equipment_for_select()
    available_eq = [e for e in equipment_options if e['status'] == '可用']

    if not available_eq:
        st.warning("当前没有可借出的设备。")

    with st.form("checkout_form"):
        col1, col2 = st.columns(2)
        with col1:
            eq_id = st.selectbox(
                "选择设备 *",
                options=[e['id'] for e in available_eq] if available_eq else [0],
                format_func=lambda x: f"[{next((e['serial_number'] for e in available_eq if e['id']==x), '')}] {next((e['name'] for e in available_eq if e['id']==x), '')}" if available_eq else "— 无可借设备 —",
                key='co_eq'
            )

            all_users = get_all_users()
            user_id = st.selectbox(
                "借用人 *",
                options=[u['id'] for u in all_users],
                format_func=lambda x: next((u['name'] for u in all_users if u['id']==x), ''),
                key='co_user'
            )
        with col2:
            today = date.today()
            from datetime import timedelta
            co_date = st.date_input("借用日期 *", value=today, key='co_date')
            co_return = st.date_input("预计归还日期 *", value=today + timedelta(days=7), key='co_return')

        purpose = st.text_input("借用原因/用途", placeholder="例如：市场部展会展示", key='co_purpose')
        notes = st.text_area("备注", placeholder="其他说明...", key='co_notes')

        submitted = st.form_submit_button("✅ 确认出库", type="primary", use_container_width=True)

        if submitted:
            if not available_eq:
                st.error("没有可借出的设备！")
            elif co_return < co_date:
                st.error("预计归还日期不能早于借用日期！")
            else:
                ok, msg = checkout_equipment(eq_id, user_id, str(co_date), str(co_return), purpose, notes)
                if ok:
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.error(msg)

    # 当前借出列表
    st.markdown("---")
    st.subheader("📦 当前已出库设备")
    out_records, _ = get_borrow_records(status='已出库', per_page=50)
    if out_records:
        for r in out_records:
            st.markdown(
                f"""<div style="border:1px solid #faad14; border-left:4px solid #fa8c16;
                border-radius:6px; padding:8px 12px; margin:4px 0; background:#fffbe6;">
                <b>📦 {r['equipment_name']}</b> <code>{r['serial_number']}</code> —
                👤 {r['user_name']} | 📅 {r['borrow_date']} → {r['expected_return_date']}<br>
                <small>用途: {r['purpose'] or '无'}</small>
                </div>""", unsafe_allow_html=True)
    else:
        st.info("无已出库设备")

# ==================== Tab 2: 归还入库 ====================
with tab2:
    st.subheader("📥 归还入库")

    out_records, _ = get_borrow_records(status='已出库', per_page=50)
    all_borrowing, _ = get_borrow_records(status='借出中', per_page=50)

    to_return = out_records + all_borrowing

    if to_return:
        today_str = str(date.today())
        overdue_ids = [r['id'] for r in to_return
                       if r.get('expected_return_date') and r['expected_return_date'] < today_str]
        if overdue_ids:
            st.warning(f"⚠️ {len(overdue_ids)} 条记录已逾期，请及时归还！")

        for r in to_return:
            with st.container():
                is_overdue = r.get('expected_return_date') and r['expected_return_date'] < today_str
                border = "#ff4d4f" if is_overdue else "#52c41a"
                tag = " 🔴逾期" if is_overdue else ""
                type_tag = "📦 已出库" if r['status'] == '已出库' else "📋 使用中"

                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(
                        f"""<div style="border:1px solid {border}; border-radius:8px; padding:10px; margin:4px 0;">
                        <b>{r['equipment_name']}</b> <code>{r['serial_number']}</code>{tag} <small>{type_tag}</small><br>
                        <small>👤 {r['user_name']} | 📅 {r['borrow_date']} → {r['expected_return_date'] or '未设'}<br>
                        📦 {r.get('product_name') or r['purpose'] or '无'}</small>
                        </div>""", unsafe_allow_html=True)
                with c2:
                    rd = st.date_input("归还日期", value=date.today(),
                                       key=f"rd_{r['id']}", label_visibility="collapsed")
                    if st.button("📥 确认归还", key=f"ret_{r['id']}", use_container_width=True):
                        ok, msg = return_equipment(r['id'], str(rd))
                        st.success(msg) if ok else st.error(msg)
                        if ok: st.rerun()
    else:
        st.success("✅ 无需要归还的设备。")

# ==================== Tab 3: 借用记录 ====================
with tab3:
    st.subheader("📜 借用记录")

    col_f1, _ = st.columns([1, 2])
    with col_f1:
        rec_status = st.selectbox("状态筛选", ["全部", "借出中", "已出库", "已归还", "逾期"], key='hist_status')

    st_filter = rec_status if rec_status != "全部" else None
    records, total = get_borrow_records(status=st_filter, per_page=50)
    st.markdown(f"共 **{total}** 条记录")

    if records:
        df = pd.DataFrame(records)
        cols = ['equipment_name', 'serial_number', 'user_name',
                'borrow_date', 'expected_return_date', 'actual_return_date',
                'status', 'purpose']
        df_d = df[cols].copy()
        df_d.columns = ['设备', '编号', '借用人', '借用日期', '预计归还', '实际归还', '状态', '用途']

        def color_status(val):
            c = {'借出中': 'background-color: #d1ecf1',
                 '已出库': 'background-color: #fff3cd',
                 '已归还': 'background-color: #d4edda',
                 '逾期': 'background-color: #f8d7da'}
            return c.get(val, '')
        styled = df_d.style.map(color_status, subset=['状态'])
        st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

# ==================== 人员管理 ====================
with st.expander("👥 人员管理", expanded=False):
    user_editing = st.session_state.user_edit_id is not None
    with st.expander("编辑人员" if user_editing else "添加人员", expanded=user_editing):
        user_existing = {}
        if user_editing:
            for u in get_all_users():
                if u['id'] == st.session_state.user_edit_id:
                    user_existing = u; break
        with st.form("user_form"):
            c1, c2 = st.columns(2)
            with c1:
                u_name = st.text_input("姓名 *", value=user_existing.get('name', ''))
                u_dept = st.text_input("部门", value=user_existing.get('department', ''))
            with c2:
                u_phone = st.text_input("电话", value=user_existing.get('phone', ''))
                u_email = st.text_input("邮箱", value=user_existing.get('email', ''))
            u_role = st.selectbox("角色", ['普通用户', '管理员'],
                                  index=1 if user_existing.get('role') == '管理员' else 0)
            cb1, cb2 = st.columns(2)
            with cb1: sub = st.form_submit_button("✅ 保存", use_container_width=True, type="primary")
            with cb2: can = st.form_submit_button("❌ 取消", use_container_width=True)
        if sub:
            if not u_name: st.error("姓名不能为空！")
            else:
                d = {'name': u_name, 'department': u_dept, 'phone': u_phone, 'email': u_email, 'role': u_role}
                ok, msg = (update_user(st.session_state.user_edit_id, d) if user_editing else add_user(d))
                if ok: st.session_state.user_edit_id = None; st.success(msg); st.rerun()
                else: st.error(msg)
        if can: st.session_state.user_edit_id = None; st.rerun()
    for u in get_all_users():
        c1, c2, c3 = st.columns([4, 0.7, 0.7])
        with c1:
            badge = "🔑" if u['role'] == '管理员' else "👤"
            st.markdown(f"{badge} **{u['name']}** — {u['department']} | `{u['role']}`")
        with c2:
            if st.button("✏️", key=f"ue_{u['id']}"): st.session_state.user_edit_id = u['id']; st.rerun()
        with c3:
            if st.button("🗑️", key=f"ud_{u['id']}"):
                ok, msg = delete_user(u['id']); st.success(msg) if ok else st.error(msg)
                if ok: st.rerun()
