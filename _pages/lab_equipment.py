"""
实验室设备管理系统 - 设备管理页面
"""

import streamlit as st
import pandas as pd
from database import (
    init_db, get_equipment, get_equipment_by_id, add_equipment, update_equipment,
    delete_equipment, get_categories, add_category, update_category, delete_category,
    import_equipment_batch, get_all_equipment, get_active_borrows
)
from io import BytesIO

st.set_page_config(page_title="设备管理", page_icon="📋", layout="wide")
init_db()

# ---- 初始化 Session State ----
for key, default in [
    ('edit_eq_id', None), ('show_add_form', False),
    ('cat_edit_id', None), ('cat_show_add', False),
    ('eq_page', 1), ('search', ''), ('filter_cat', None), ('filter_status', None)
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("📋 设备管理")

tab1, tab2 = st.tabs(["📦 设备台账", "🏷️ 设备分类"])

# ==================== Tab 1: 设备台账 ====================
with tab1:
    # ---- 搜索和筛选栏 ----
    col_s, col_c, col_st, col_b = st.columns([3, 2, 2, 1.5])
    with col_s:
        search = st.text_input("🔍 搜索", placeholder="设备名称 / 型号 / 编号",
                               key='eq_search', value=st.session_state.search,
                               on_change=lambda: st.session_state.update(search=st.session_state.eq_search))
    with col_c:
        categories = get_categories()
        cat_options = {0: "全部分类"}
        cat_options.update({c['id']: c['name'] for c in categories})
        filter_cat = st.selectbox("分类", options=list(cat_options.keys()),
                                   format_func=lambda x: cat_options[x],
                                   key='eq_filter_cat', index=0 if not st.session_state.filter_cat
                                   else list(cat_options.keys()).index(st.session_state.filter_cat))
        st.session_state.filter_cat = filter_cat if filter_cat != 0 else None
    with col_st:
        status_options = ["全部", "可用", "借出", "维修中", "报废"]
        filter_status = st.selectbox("状态", status_options, key='eq_filter_status')
        st.session_state.filter_status = filter_status if filter_status != "全部" else None
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ 添加设备", use_container_width=True, type="primary"):
            st.session_state.show_add_form = True
            st.session_state.edit_eq_id = None

    # ---- 添加/编辑表单 ----
    if st.session_state.show_add_form or st.session_state.edit_eq_id:
        st.markdown("---")
        editing = st.session_state.edit_eq_id is not None
        st.subheader("✏️ 编辑设备" if editing else "➕ 添加新设备")

        existing = get_equipment_by_id(st.session_state.edit_eq_id) if editing else {}

        with st.form("equipment_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("设备名称 *", value=existing.get('name', ''))
                model = st.text_input("型号", value=existing.get('model', ''))
                serial = st.text_input("设备编号", value=existing.get('serial_number', ''))
                cat_list = get_categories()
                cat_map = {c['id']: c['name'] for c in cat_list}
                cat_ids = [0] + [c['id'] for c in cat_list]
                cat_labels = {0: "请选择分类"}
                cat_labels.update({c['id']: c['name'] for c in cat_list})
                default_cat = existing.get('category_id', 0) or 0
                cat_idx = cat_ids.index(default_cat) if default_cat in cat_ids else 0
                category_id = st.selectbox("设备分类", cat_ids, format_func=lambda x: cat_labels[x],
                                           index=cat_idx)
            with col2:
                location = st.text_input("存放位置", value=existing.get('location', ''))
                status_list = ['可用', '借出', '维修中', '报废']
                default_status = existing.get('status', '可用')
                status_idx = status_list.index(default_status) if default_status in status_list else 0
                status = st.selectbox("状态", status_list, index=status_idx)
                purchase_date = st.date_input("购置日期", value=pd.to_datetime(existing.get('purchase_date')) if existing.get('purchase_date') else None)
                price = st.number_input("购置价格 (¥)", min_value=0.0, step=100.0,
                                        value=float(existing.get('price', 0)))
                supplier = st.text_input("供应商", value=existing.get('supplier', ''))
                warranty = st.date_input("保修截止日", value=pd.to_datetime(existing.get('warranty_expiry')) if existing.get('warranty_expiry') else None)

            description = st.text_area("备注说明", value=existing.get('description', ''))

            col_btn1, col_btn2, _ = st.columns([1, 1, 4])
            with col_btn1:
                submitted = st.form_submit_button("✅ 保存", use_container_width=True, type="primary")
            with col_btn2:
                cancelled = st.form_submit_button("❌ 取消", use_container_width=True)

        if submitted:
            if not name:
                st.error("设备名称不能为空！")
            else:
                data = {
                    'name': name, 'model': model, 'serial_number': serial,
                    'category_id': category_id if category_id != 0 else None,
                    'location': location, 'status': status,
                    'purchase_date': str(purchase_date) if purchase_date else '',
                    'price': price, 'supplier': supplier,
                    'warranty_expiry': str(warranty) if warranty else '',
                    'description': description
                }
                if editing:
                    ok, msg = update_equipment(st.session_state.edit_eq_id, data)
                else:
                    ok, msg = add_equipment(data)
                if ok:
                    st.success(msg)
                    st.session_state.show_add_form = False
                    st.session_state.edit_eq_id = None
                    st.rerun()
                else:
                    st.error(msg)

        if cancelled:
            st.session_state.show_add_form = False
            st.session_state.edit_eq_id = None
            st.rerun()

    # ---- 设备列表 ----
    equipment_list, total = get_equipment(
        search=st.session_state.search or '',
        category_id=st.session_state.filter_cat,
        status=st.session_state.filter_status,
        page=st.session_state.eq_page,
        per_page=15
    )

    st.markdown(f"共 **{total}** 台设备")

    # 分页放在表格上方
    total_pages = max(1, (total + 14) // 15)
    if total > 15:
        col_pg1, col_pg2, col_pg3 = st.columns([3, 1, 3])
        with col_pg2:
            pg = st.selectbox("页码", range(1, total_pages + 1),
                              index=st.session_state.eq_page - 1, key='eq_page_sel')
            if pg != st.session_state.eq_page:
                st.session_state.eq_page = pg
                st.rerun()

    if equipment_list:
        # 获取使用中设备ID列表，标记为"占用"
        active_borrows = get_active_borrows()
        active_eq_ids = {b['equipment_id'] for b in active_borrows}

        df = pd.DataFrame(equipment_list)
        # 开发中使用中的设备状态改为"占用"
        df['display_status'] = df.apply(
            lambda row: '占用' if row['id'] in active_eq_ids and row['status'] == '可用' else row['status'],
            axis=1
        )

        df_display = df[['id', 'name', 'model', 'serial_number', 'category_name',
                          'location', 'display_status', 'price']].copy()
        df_display.columns = ['ID', '设备名称', '型号', '编号', '分类', '位置', '状态', '价格(¥)']

        # 状态着色
        def color_status(val):
            colors = {'可用': 'background-color: #d4edda; color: #155724',
                       '占用': 'background-color: #d1ecf1; color: #0c5460',
                       '借出': 'background-color: #fff3cd; color: #856404',
                       '维修中': 'background-color: #fff3cd; color: #856404',
                       '报废': 'background-color: #f8d7da; color: #721c24'}
            return colors.get(val, '')

        styled = df_display.style.map(color_status, subset=['状态'])

        st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

        # 操作按钮
        st.markdown("---")
        st.caption("💡 点击下方按钮对选中设备进行操作（先点击表格中的行选中设备）")

        col_op1, col_op2, col_op3, col_op4, col_op5 = st.columns(5)

        # 设备选择
        eq_options = {e['id']: f"[{e['id']}] {e['name']} ({e.get('serial_number', '')})" for e in equipment_list}
        selected_eq = st.selectbox("选择设备", options=list(eq_options.keys()),
                                    format_func=lambda x: eq_options[x],
                                    key='selected_equipment')

        with col_op1:
            if st.button("✏️ 编辑", use_container_width=True):
                st.session_state.edit_eq_id = selected_eq
                st.session_state.show_add_form = True
                st.rerun()
        with col_op2:
            if st.button("🗑️ 删除", use_container_width=True):
                ok, msg = delete_equipment(selected_eq)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        with col_op3:
            if st.button("🔄 查看详情", use_container_width=True):
                eq = get_equipment_by_id(selected_eq)
                if eq:
                    with st.expander(f"📋 {eq['name']} - 详细信息", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**名称**: {eq['name']}")
                            st.markdown(f"**型号**: {eq['model'] or '-'}")
                            st.markdown(f"**编号**: {eq['serial_number'] or '-'}")
                            st.markdown(f"**分类**: {eq['category_name'] or '-'}")
                            st.markdown(f"**位置**: {eq['location'] or '-'}")
                        with col_b:
                            st.markdown(f"**状态**: {eq['status']}")
                            st.markdown(f"**购置日期**: {eq['purchase_date'] or '-'}")
                            st.markdown(f"**价格**: ¥{eq['price']:,.2f}")
                            st.markdown(f"**供应商**: {eq['supplier'] or '-'}")
                            st.markdown(f"**保修截止**: {eq['warranty_expiry'] or '-'}")
                        st.markdown(f"**备注**: {eq['description'] or '-'}")

        # 导入导出
        st.markdown("---")
        col_ie1, col_ie2 = st.columns(2)
        with col_ie1:
            st.markdown("**📥 导入设备 (CSV)**")
            uploaded = st.file_uploader("上传 CSV 文件", type=['csv'], key='eq_import',
                                         label_visibility="collapsed")
            if uploaded:
                try:
                    df_import = pd.read_csv(uploaded)
                    records = df_import.to_dict('records')
                    success, errors = import_equipment_batch(records)
                    st.success(f"成功导入 {success} 条记录")
                    if errors:
                        st.warning(f"失败 {len(errors)} 条: {'; '.join(errors[:3])}")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败: {e}")

        with col_ie2:
            st.markdown("**📤 导出设备**")
            all_eq = get_all_equipment()
            if all_eq:
                df_export = pd.DataFrame(all_eq)
                df_export = df_export.rename(columns={
                    'name': '设备名称', 'model': '型号', 'serial_number': '设备编号',
                    'category_name': '分类', 'location': '位置', 'status': '状态',
                    'purchase_date': '购置日期', 'price': '价格', 'supplier': '供应商',
                    'warranty_expiry': '保修截止', 'description': '备注'
                })
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='设备台账')
                st.download_button(
                    "📥 下载 Excel", buffer.getvalue(),
                    "设备台账.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
    else:
        st.info("暂无设备数据，点击「添加设备」开始录入。")

# ==================== Tab 2: 设备分类 ====================
with tab2:
    st.subheader("🏷️ 设备分类管理")

    # 添加/编辑分类
    col_form, _ = st.columns([2, 3])
    with col_form:
        cat_editing = st.session_state.cat_edit_id is not None
        st.markdown("✏️ 编辑分类" if cat_editing else "➕ 添加分类")

        cat_existing = {}
        if cat_editing:
            for c in get_categories():
                if c['id'] == st.session_state.cat_edit_id:
                    cat_existing = c
                    break

        cat_name = st.text_input("分类名称", value=cat_existing.get('name', ''), key='cat_name')
        cat_desc = st.text_area("描述", value=cat_existing.get('description', ''), key='cat_desc')

        col_cb1, col_cb2 = st.columns(2)
        with col_cb1:
            if st.button("💾 保存", use_container_width=True):
                if not cat_name:
                    st.error("分类名称不能为空")
                elif cat_editing:
                    ok, msg = update_category(st.session_state.cat_edit_id, cat_name, cat_desc)
                    if ok:
                        st.success(msg)
                        st.session_state.cat_edit_id = None
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    ok, msg = add_category(cat_name, cat_desc)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        with col_cb2:
            if cat_editing and st.button("❌ 取消", use_container_width=True):
                st.session_state.cat_edit_id = None
                st.rerun()

    st.markdown("---")

    # 分类列表
    cats = get_categories()
    if cats:
        for c in cats:
            eq_count = sum(1 for e in get_all_equipment() if e.get('category_id') == c['id'])
            with st.container():
                col_c1, col_c2, col_c3 = st.columns([3, 1, 1])
                with col_c1:
                    st.markdown(f"**{c['name']}**  ({eq_count} 台设备)")
                    st.caption(c['description'] or '无描述')
                with col_c2:
                    if st.button("✏️", key=f"cat_edit_{c['id']}"):
                        st.session_state.cat_edit_id = c['id']
                        st.rerun()
                with col_c3:
                    if st.button("🗑️", key=f"cat_del_{c['id']}"):
                        ok, msg = delete_category(c['id'])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
    else:
        st.info("暂无分类")
