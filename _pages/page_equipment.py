"""
实验室设备管理系统 - 设备管理页面
"""

import streamlit as st
import pandas as pd
from pages._utils import render_sidebar, render_topbar, render_data_section, ui_danger_button
from components.modal import confirm_dialog
from database import (
    init_db, get_equipment, get_equipment_by_id, add_equipment, update_equipment,
    delete_equipment, get_categories, add_category, update_category, delete_category,
    import_equipment_batch, get_all_equipment, get_active_borrows
)
from io import BytesIO


def _safe_cell(v, maxlen=None):
    """将 None / NaN / 空串 / 'nan' / 'None' 统一显示为 '-'，避免设备台账出现 nan。"""
    try:
        if pd.isna(v):
            return '-'
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if s == '' or s.lower() in ('nan', 'none'):
        return '-'
    return s[:maxlen] if maxlen else s


st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# ---- 初始化 Session State ----
for key, default in [
    ('edit_eq_id', None), ('show_add_form', False),
    ('cat_edit_id', None), ('cat_show_add', False),
    ('eq_page', 1), ('search', ''), ('filter_cat', None), ('filter_status', None)
]:
    if key not in st.session_state:
        st.session_state[key] = default

# 渲染侧边栏导航
st.session_state.current_page = "设备台账"
with st.sidebar:
    render_sidebar()
render_topbar("设备台账")



st.title("设备管理")

tab1, tab2 = st.tabs(["设备台账", "设备分类"])

# ==================== Tab 1: 设备台账 ====================
with tab1:
    # ---- 搜索和筛选栏 ----
    col_s, col_c, col_st, col_b = st.columns([3, 2, 2, 1.5])
    with col_s:
        search = st.text_input("搜索", placeholder="设备名称 / 型号 / 编号",
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
        if st.button("添加设备", width="stretch", type="primary"):
            st.session_state.show_add_form = True
            st.session_state.edit_eq_id = None

    # ---- 添加/编辑表单 ----
    if st.session_state.show_add_form or st.session_state.edit_eq_id:
        st.markdown("---")
        editing = st.session_state.edit_eq_id is not None
        st.subheader("编辑设备" if editing else "添加新设备")

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
                submitted = st.form_submit_button("保存", width="stretch", type="primary")
            with col_btn2:
                cancelled = st.form_submit_button("取消", width="stretch")

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

    # ── 加载数据 ──
    equipment_list, total = get_equipment(
        search=st.session_state.search or '',
        category_id=st.session_state.filter_cat,
        status=st.session_state.filter_status,
        page=1, per_page=5000  # 加载全部数据供编辑
    )

    if equipment_list:
        # 获取使用中设备ID列表，标记为"占用"
        active_borrows = get_active_borrows()
        active_eq_ids = {b['equipment_id'] for b in active_borrows}

        df = pd.DataFrame(equipment_list)
        df['display_status'] = df.apply(
            lambda row: '占用' if row['id'] in active_eq_ids and row['status'] == '可用' else row['status'],
            axis=1
        )

        # ── 模式切换：表格视图 / 编辑视图 ──
        view_mode = st.pills(
            "视图模式",
            ["表格浏览", "行内编辑"],
            key="eq_view_mode",
            default="表格浏览",
        )

        if view_mode == "表格浏览":
            # ── 表格视图：每行带操作按钮，点击编辑弹出表单 ──
            # 选择展示列
            df_display = df[['id', 'name', 'model', 'serial_number', 'category_name',
                             'location', 'display_status', 'price', 'supplier']].copy()

            # 分页（可调行数）
            _eq_row_opts = [10, 15, 20, 50]
            _eq_def = st.session_state.get("equip_page_size", 15)
            _epc1, _epc2 = st.columns([1, 4])
            with _epc1:
                _epsz_sel = st.selectbox("每页行数", options=_eq_row_opts,
                    index=_eq_row_opts.index(_eq_def) if _eq_def in _eq_row_opts else 1,
                    key="eq_page_size_sel", label_visibility="collapsed")
            if st.session_state.get("eq_page_size_sel", 15) != st.session_state.get("equip_page_size", 15):
                old_psz = st.session_state.get("equip_page_size", 15)
                new_psz = st.session_state["eq_page_size_sel"]
                st.session_state["equip_page_size"] = new_psz
                # 调整当前页码避免越界
                current_idx = st.session_state.get('eq_table_page', 0)
                max_page = max(0, (len(df_display) - 1) // new_psz)
                st.session_state['eq_table_page'] = min(current_idx, max_page)
                st.rerun()

            page_size = st.session_state.get("equip_page_size", 15)
            eq_page_key = 'eq_table_page'
            if eq_page_key not in st.session_state:
                st.session_state[eq_page_key] = 0

            total_rows = len(df_display)
            total_pages = max(1, (total_rows + page_size - 1) // page_size)

            start = st.session_state[eq_page_key] * page_size
            end = min(start + page_size, total_rows)
            page_df = df_display.iloc[start:end].reset_index(drop=True)

            with _epc2:
                st.caption(f"共 **{total_rows}** 条 · 第 **{st.session_state[eq_page_key] + 1}/{total_pages}** 页")

            # 渲染表格，每行加编辑按钮
            cols_display = list(page_df.columns) + ['操作']
            header_html = (
                '<div style="display:table;width:100%;table-layout:fixed;">'
                '<div style="display:table-row;font-weight:600;background:#f8fafc;'
                'border-bottom:2px solid #e2e8f0;padding:8px 4px;font-size:13px;">'
            )
            col_widths = {'name': '14%', 'model': '10%', 'serial_number': '12%',
                          'category_name': '13%', 'location': '11%', 'display_status': '7%',
                          'price': '7%', 'supplier': '12%', '操作': '14%'}
            for c in cols_display:
                w = col_widths.get(c, '10%')
                label = {'name':'名称','model':'型号','serial_number':'编号',
                         'category_name':'分类','location':'位置','display_status':'状态',
                         'price':'价格(¥)','supplier':'供应商','操作':'操作'}.get(c, c)
                header_html += f'<div style="display:table-cell;width:{w};padding:6px 4px;">{label}</div>'
            header_html += '</div></div>'
            st.markdown(header_html, unsafe_allow_html=True)

            for idx, row in page_df.iterrows():
                row_eq_id = int(row['id'])
                with st.container():
                    rcol1, rcol2, rcol3, rcol4, rcol5, rcol6, rcol7, rcol8, rcol9 = st.columns(
                        [2.5, 1.8, 2.1, 2.3, 1.9, 1.2, 1.2, 2.1, 2.5]
                    )
                    with rcol1:
                        _n = _safe_cell(row['name'], 16)
                        _extra = '…' if len(str(row['name']).strip()) > 16 else ''
                        st.text(_n + _extra)
                    with rcol2:
                        _m = _safe_cell(row['model'], 10); st.text(_m)
                    with rcol3:
                        _s = _safe_cell(row['serial_number'], 12); st.text(_s)
                    with rcol4:
                        _c = _safe_cell(row['category_name'], 10); st.text(_c)
                    with rcol5:
                        _l = _safe_cell(row['location'], 9); st.text(_l)
                    with rcol6:
                        st.text(_safe_cell(row['display_status']))
                    with rcol7:
                        try:
                            p = float(row['price'])
                        except (ValueError, TypeError):
                            p = 0.0
                        if pd.isna(p):
                            p = 0.0
                        st.text(f'{p:.0f}' if p else '-')
                    with rcol8:
                        _sp = _safe_cell(row['supplier'], 9); st.text(_sp)
                    with rcol9:
                        bcol_e, bcol_d = st.columns(2)
                        with bcol_e:
                            if st.button("编辑", key=f"edit_row_{row_eq_id}", help="编辑此设备"):
                                st.session_state.edit_eq_id = row_eq_id
                                st.session_state.show_add_form = False
                                st.rerun()
                        with bcol_d:
                            if ui_danger_button("删除", key=f"del_row_{row_eq_id}", help="删除此设备"):
                                confirm_dialog(
                                    "确认删除设备",
                                    f"确定要删除设备 **{row['name']}** 吗？此操作不可撤销。",
                                    state_key="eq_del_confirm",
                                    state_value={"id": row_eq_id, "name": row['name']},
                                    confirm_label="确认删除",
                                    confirm_type="primary",
                                )
                    st.markdown('<div style="border-bottom:1px solid #f1f5f9;"></div>', unsafe_allow_html=True)

            # F3：删除设备二次确认后执行（循环外，避免误删末条后状态残留）
            if st.session_state.get("eq_del_confirm"):
                _del = st.session_state.eq_del_confirm
                st.session_state.eq_del_confirm = None
                ok, msg = delete_equipment(_del["id"])
                if ok:
                    st.success(f"已删除: {_del['name']}")
                    st.rerun()
                else:
                    st.error(msg)

            # 分页控件
            if total_pages > 1:
                pc1, pc2, pc3 = st.columns([1, 1, 1])
                with pc1:
                    if st.button("上一页", key="eq_tbl_prev",
                                 disabled=st.session_state[eq_page_key]==0):
                        st.session_state[eq_page_key] -= 1; st.rerun()
                with pc2:
                    pg_n = st.number_input("页码", min_value=1, max_value=total_pages,
                                            value=st.session_state[eq_page_key]+1,
                                            key="eq_tbl_pg", label_visibility="collapsed")
                    if pg_n != st.session_state[eq_page_key]+1:
                        st.session_state[eq_page_key]=pg_n-1; st.rerun()
                with pc3:
                    if st.button("下一页下一页", key="eq_tbl_next",
                                 disabled=st.session_state[eq_page_key]>=total_pages-1):
                        st.session_state[eq_page_key]+=1; st.rerun()

            st.caption("点击 编辑设备信息 | 删除设备 | 切换到「行内编辑」可批量修改")

        else:
            # ── 行内编辑模式：st.data_editor 批量编辑 ──
            # 选择展示列并重命名
            df_display = df[['id', 'name', 'model', 'serial_number', 'category_name',
                             'location', 'display_status', 'price', 'supplier', 'description']].copy()
            # 行内编辑模式：文本列 NaN 显示为空白，避免 'nan'
            _obj_cols = list(df_display.select_dtypes(include='object').columns)
            df_display = df_display.fillna({c: '' for c in _obj_cols})
            df_display.columns = ['id', 'name', 'model', 'serial_number', 'category_name',
                                  'location', 'display_status', 'price', 'supplier', 'description']

            # 导入模板（可导入的列 — 使用 DB 列名）
            template_df = pd.DataFrame(columns=[
                'name', 'model', 'serial_number', 'category_id', 'location',
                'status', 'purchase_date', 'price', 'supplier', 'warranty_expiry', 'description'
            ])

            # 显示列名 → DB列名映射
            col_name_map = {
                'display_status': 'status',
                'category_name': 'category_id',
            }

            render_data_section(
                df=df_display,
                table_name='equipment',
                db_conn=None,
                template_df=template_df,
                key_prefix='eq_',
                disabled_cols=['id', 'display_status', 'category_name'],
                hidden_cols=['id'],
                column_name_map=col_name_map,
                page_size=15,
                primary_key='id',
                allow_import_export=True,
                allow_edit=True,
            )
    else:
        st.info("暂无设备数据，点击「添加设备」开始录入。")

# ==================== Tab 2: 设备分类 ====================
with tab2:
    st.subheader("设备分类管理")

    # 添加/编辑分类
    col_form, _ = st.columns([2, 3])
    with col_form:
        cat_editing = st.session_state.cat_edit_id is not None
        st.markdown("编辑分类" if cat_editing else "添加分类")

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
            if st.button("保存", width="stretch"):
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
            if cat_editing and st.button("取消", width="stretch"):
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
                    st.markdown(f"**{c['name']}** ({eq_count} 台设备)")
                    st.caption(c['description'] or '无描述')
                with col_c2:
                    if st.button("编辑", key=f"cat_edit_{c['id']}"):
                        st.session_state.cat_edit_id = c['id']
                        st.rerun()
                with col_c3:
                    if ui_danger_button("删除", key=f"cat_del_{c['id']}"):
                        confirm_dialog(
                            "确认删除分类",
                            f"确定要删除分类 **{c['name']}** 吗？此操作不可撤销。",
                            state_key="cat_del_confirm",
                            state_value={"id": c['id'], "name": c['name']},
                            confirm_label="确认删除",
                            confirm_type="primary",
                        )
            # F3：删除分类二次确认后执行（循环外）
            if st.session_state.get("cat_del_confirm"):
                _cd = st.session_state.cat_del_confirm
                st.session_state.cat_del_confirm = None
                ok, msg = delete_category(_cd["id"])
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.info("暂无分类")
