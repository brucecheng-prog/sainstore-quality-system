"""
品质系统管理 - 变更管理
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from database import (
    init_db, get_changes, add_change, update_change, delete_change,
    import_changes_from_excel,
    get_bu_list, get_brand_list, get_users, get_rd_teams
)

st.set_page_config(page_title="变更管理", page_icon="📝", layout="wide")
init_db()

st.title("📝 变更管理")

# 自动导入
changes_check, _ = get_changes(per_page=1)
if not changes_check:
    if st.button("📥 从产品变更汇总表导入数据", use_container_width=True, type="primary"):
        count, msg = import_changes_from_excel()
        st.success(f"✅ 导入了 {count} 条变更记录！")
        st.rerun()

tab1, tab2 = st.tabs(["📝 登记变更", "📋 变更记录"])

bu_list = get_bu_list()
brand_list = get_brand_list()
rd_teams = get_rd_teams()
users = get_users()

# ==================== Tab 1: 登记变更 ====================
with tab1:
    st.subheader("📝 产品变更登记")

    with st.form("change_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            bu = st.selectbox("BU *", [""] + bu_list)
            brand = st.selectbox("品牌 *", [""] + brand_list)
        with col2:
            sku = st.text_input("SKU", placeholder="例如：101-63-KK-RC")
            rd_team = st.selectbox("研发小组", [""] + rd_teams)

        col1, col2 = st.columns(2)
        with col1:
            supplier = st.text_input("供应商", placeholder="变更供应商名称")
        with col2:
            change_date = st.date_input("变更日期", value=date.today())

        change_reason = st.text_area("变更原因及内容 *", placeholder="详细描述变更原因和变更内容...")

        col1, col2 = st.columns(2)
        with col1:
            uploaded_file = st.file_uploader("上传相关文件", type=["pdf", "docx", "xlsx", "png", "jpg"],
                                             help="可上传变更通知、图纸等")
        with col2:
            confirm_person = st.selectbox(
                "推送给品质负责人 *",
                [""] + [f"{u['name']}" for u in users],
                help="选择要通知的品质负责人"
            )

        submitted = st.form_submit_button("✅ 提交变更登记", type="primary", use_container_width=True)

    if submitted:
        if not bu or not brand or not change_reason or not confirm_person:
            st.error("BU、品牌、变更内容和品质负责人不能为空！")
        else:
            file_path = ""
            filename = ""
            if uploaded_file:
                import os
                upload_dir = os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), "data", "changes")
                os.makedirs(upload_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{uploaded_file.name}"
                file_path = os.path.join(upload_dir, filename)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

            ok, msg = add_change({
                'bu': bu, 'brand': brand, 'sku': sku,
                'change_reason': change_reason,
                'supplier': supplier,
                'rd_team': rd_team,
                'attachments': filename,
                'change_date': str(change_date),
                'confirm_date': str(date.today()),
                'confirm_person': confirm_person
            })
            if ok:
                st.success(f"✅ {msg}！变更信息已推送至 {confirm_person}。")
                st.rerun()
            else:
                st.error(msg)

# ==================== Tab 2: 变更记录 ====================
with tab2:
    st.subheader("📋 变更记录")

    if 'ch_page' not in st.session_state:
        st.session_state.ch_page = 1
    if 'ch_edit_id' not in st.session_state:
        st.session_state.ch_edit_id = None

    # 三列搜索
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        search_sku = st.text_input("🔍 SKU搜索", placeholder="输入SKU关键词", key='ch_sku')
    with col_s2:
        search_content = st.text_input("🔍 变更内容搜索", placeholder="变更原因关键词", key='ch_content')
    with col_s3:
        search_supplier = st.text_input("🔍 供应商搜索", placeholder="供应商关键词", key='ch_supplier')

    # BU/品牌筛选
    col1, col2 = st.columns(2)
    with col1:
        filter_bu = st.selectbox("BU筛选", ["全部"] + bu_list, key='ch_bu')
    with col2:
        filter_brand = st.selectbox("品牌筛选", ["全部"] + brand_list, key='ch_brand')

    changes, total = get_changes(
        search_sku=search_sku,
        search_content=search_content,
        search_supplier=search_supplier,
        bu=filter_bu if filter_bu != "全部" else "",
        brand=filter_brand if filter_brand != "全部" else "",
        page=st.session_state.ch_page,
        per_page=20
    )

    # 分页
    total_pages = max(1, (total + 19) // 20)
    col_pg1, col_pg2, col_pg3 = st.columns([2, 1, 2])
    with col_pg2:
        pg = st.selectbox("页码", range(1, total_pages + 1),
                          index=st.session_state.ch_page - 1,
                          key='ch_page_sel', label_visibility="collapsed")
        if pg != st.session_state.ch_page:
            st.session_state.ch_page = pg
            st.rerun()

    st.markdown(f"共 **{total}** 条变更记录 (第 {st.session_state.ch_page}/{total_pages} 页)")

    if changes:
        df = pd.DataFrame(changes)
        cols = ['id', 'bu', 'brand', 'sku', 'supplier', 'change_reason', 'change_date',
                'confirm_date', 'confirm_person']
        df_d = df[[c for c in cols if c in df.columns]].copy()
        rename = {'id': 'ID', 'bu': 'BU', 'brand': '品牌', 'sku': 'SKU', 'supplier': '供应商',
                  'change_reason': '变更原因', 'change_date': '变更日期',
                  'confirm_date': '确认日期', 'confirm_person': '确认人'}
        df_d.rename(columns={k: v for k, v in rename.items() if k in df_d.columns}, inplace=True)

        if '变更原因' in df_d.columns:
            df_d['变更原因'] = df_d['变更原因'].apply(
                lambda x: x[:100] + '...' if isinstance(x, str) and len(x) > 100 else x)

        st.dataframe(df_d, use_container_width=True, hide_index=True, height=450,
                     column_config={'ID': None})

        # 编辑/删除操作
        ch_options = {r['id']: f"[{r['id']}] {r.get('sku','')} - {r.get('brand','')} ({str(r.get('change_reason',''))[:30]})" for r in changes}
        col_sel, col_btn1, col_btn2 = st.columns([3, 1, 1])
        with col_sel:
            selected_ch = st.selectbox("选择记录", list(ch_options.keys()),
                                       format_func=lambda x: ch_options[x],
                                       key='sel_ch', label_visibility="collapsed")
        with col_btn1:
            if st.button("✏️ 编辑", use_container_width=True):
                st.session_state.ch_edit_id = selected_ch
                st.rerun()
        with col_btn2:
            if st.button("🗑️ 删除", use_container_width=True):
                ok, msg = delete_change(selected_ch)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
    else:
        st.info("暂无变更记录")

    # 编辑弹窗
    if st.session_state.ch_edit_id:
        st.markdown("---")
        st.subheader(f"✏️ 编辑变更记录 #{st.session_state.ch_edit_id}")
        # 从当前页查找记录
        edit_data = next((r for r in changes if r['id'] == st.session_state.ch_edit_id), {})
        with st.form("change_edit_form"):
            c1, c2 = st.columns(2)
            with c1:
                e_bu = st.selectbox("BU *", bu_list, index=bu_list.index(edit_data.get('bu','')) if edit_data.get('bu') in bu_list else 0)
                e_brand = st.selectbox("品牌 *", brand_list, index=brand_list.index(edit_data.get('brand','')) if edit_data.get('brand') in brand_list else 0)
            with c2:
                e_sku = st.text_input("SKU", value=edit_data.get('sku', ''))
                e_supplier = st.text_input("供应商", value=edit_data.get('supplier', ''))
            e_reason = st.text_area("变更原因及内容 *", value=edit_data.get('change_reason', ''))
            c3, c4 = st.columns(2)
            with c3:
                e_submitted = st.form_submit_button("✅ 保存修改", type="primary", use_container_width=True)
            with c4:
                e_cancel = st.form_submit_button("❌ 取消编辑", use_container_width=True)
        if e_submitted:
            ok, msg = update_change(st.session_state.ch_edit_id, {
                'bu': e_bu, 'brand': e_brand, 'sku': e_sku, 'supplier': e_supplier,
                'change_reason': e_reason, 'change_date': edit_data.get('change_date', ''),
                'rd_team': edit_data.get('rd_team', '')
            })
            if ok: st.success(msg); st.session_state.ch_edit_id = None; st.rerun()
            else: st.error(msg)
        if e_cancel:
            st.session_state.ch_edit_id = None
            st.rerun()
