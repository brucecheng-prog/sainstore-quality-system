"""
品质系统管理 - 样品管理
"""

import streamlit as st
import pandas as pd
from datetime import date
from database import (
    init_db, get_samples, add_sample, update_sample, delete_sample,
    import_samples_from_excel,
    get_bg_list, get_brand_list, get_sample_bg_list,
    sample_outbound, sample_return, get_outbound_records
)

st.set_page_config(page_title="样品管理", page_icon="📦", layout="wide")
init_db()

st.title("📦 样品管理")

# 初始化 session state
for k, v in [('sp_page', 1), ('sp_edit_id', None), ('sp_selected', []), ('sp_out_id', None), ('sp_out_name', '')]:
    if k not in st.session_state:
        st.session_state[k] = v

# 自动导入
samples_check, _ = get_samples(per_page=1)
if not samples_check:
    if st.button("📥 从签样记录导入数据", use_container_width=True, type="primary"):
        count, msg = import_samples_from_excel()
        st.success(f"✅ 导入了 {count} 条样品记录！")
        st.rerun()

bg_list = get_bg_list()
brand_list = get_brand_list()

# ==================== 编辑/出库表单（顶部，优先级高于tab） ====================
if st.session_state.sp_out_id:
    st.markdown("---")
    st.subheader(f"📤 出库登记 — {st.session_state.sp_out_name}")
    with st.form("outbound_form"):
        c1, c2 = st.columns(2)
        with c1:
            out_qty = st.number_input("出库数量", min_value=1, value=1)
            out_date = st.date_input("出库日期", value=date.today())
        with c2:
            out_borrower = st.text_input("领用人 *", placeholder="领用人姓名")
            out_dept = st.text_input("领用部门", placeholder="例如：品质部")
        out_reason = st.selectbox("出库原因", ["检测", "借用", "报废", "归还厂商", "其他"])
        out_notes = st.text_area("备注")
        c1, c2 = st.columns(2)
        with c1:
            if st.form_submit_button("✅ 确认出库", type="primary", use_container_width=True):
                if not out_borrower:
                    st.error("领用人不能为空!")
                else:
                    ok, msg = sample_outbound(
                        st.session_state.sp_out_id, out_qty,
                        str(out_date), out_borrower, out_dept, out_reason, out_notes
                    )
                    if ok:
                        st.success(msg)
                        st.session_state.sp_out_id = None
                        st.rerun()
                    else:
                        st.error(msg)
        with c2:
            if st.form_submit_button("❌ 取消", use_container_width=True):
                st.session_state.sp_out_id = None
                st.rerun()
    st.stop()

if st.session_state.sp_edit_id is not None:
    from database import get_connection
    conn = get_connection()
    row = conn.execute("SELECT * FROM samples WHERE id=?", (st.session_state.sp_edit_id,)).fetchone()
    conn.close()
    if row:
        edit_sp = dict(row)
        st.markdown("---")
        st.subheader(f"✏️ 编辑样品 #{st.session_state.sp_edit_id}")

        with st.form("sample_edit_form"):
            c1, c2 = st.columns(2)
            with c1:
                sample_name = st.text_input("样品名称 *", value=edit_sp.get('sample_name', ''))
                bg_val = edit_sp.get('bg', '')
                bg = st.selectbox("BG", get_sample_bg_list(), index=get_sample_bg_list().index(bg_val) if bg_val in get_sample_bg_list() else 0)
            with c2:
                sku = st.text_input("SKU", value=edit_sp.get('sku', ''))
                sign_val = edit_sp.get('sign_date', '')
                if sign_val:
                    try: sign_val = pd.to_datetime(sign_val.replace('.', '-'))
                    except: sign_val = date.today()
                else:
                    sign_val = date.today()
                sign_date = st.date_input("签样日期", value=sign_val)
            c3, c4 = st.columns(2)
            with c3:
                brand_val = edit_sp.get('brand', '')
                brand = st.selectbox("品牌", [""] + brand_list, index=([""]+brand_list).index(brand_val) if brand_val in brand_list else 0)
                supplier = st.text_input("供应商", value=edit_sp.get('supplier', ''))
            with c4:
                location = st.text_input("放置区域", value=edit_sp.get('location', ''))
            notes = st.text_area("备注", value=edit_sp.get('notes', ''))
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.form_submit_button("✅ 保存修改", type="primary", use_container_width=True):
                    if not sample_name:
                        st.error("样品名称不能为空!")
                    else:
                        ok, msg = update_sample(st.session_state.sp_edit_id, {
                            'bg': bg, 'sku': sku, 'sample_name': sample_name,
                            'sign_date': str(sign_date) if sign_date else '',
                            'supplier': supplier, 'brand': brand,
                            'notes': notes, 'location': location
                        })
                        if ok:
                            st.success(msg)
                            st.session_state.sp_edit_id = None
                            st.rerun()
                        else:
                            st.error(msg)
            with col_cancel:
                if st.form_submit_button("❌ 取消编辑", use_container_width=True):
                    st.session_state.sp_edit_id = None
                    st.rerun()
    else:
        st.session_state.sp_edit_id = None
    st.stop()

tab1, tab2, tab3 = st.tabs(["📋 样品登记", "📊 样品列表", "📤 出库记录"])

# ==================== Tab 1: 登记 ====================
with tab1:
    st.subheader("📝 样品登记")
    with st.form("sample_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            s_name = st.text_input("样品名称 *", placeholder="例如：B22A 红色", key='new_name')
            s_bg = st.selectbox("BG", get_sample_bg_list(), key='new_bg')
        with c2:
            s_sku = st.text_input("SKU", placeholder="例如：ABT-05-B22A", key='new_sku')
            s_date = st.date_input("签样日期", value=date.today(), key='new_date')
        c3, c4 = st.columns(2)
        with c3:
            s_brand = st.selectbox("品牌", [""] + brand_list, key='new_brand')
            s_supplier = st.text_input("供应商", key='new_supplier')
        with c4:
            s_location = st.text_input("放置区域", placeholder="QA样品室1", key='new_location')
        s_notes = st.text_area("备注", key='new_notes')
        if st.form_submit_button("✅ 提交登记", type="primary", use_container_width=True):
            if not s_name:
                st.error("样品名称不能为空！")
            else:
                ok, msg = add_sample({
                    'bg': s_bg, 'sku': s_sku, 'sample_name': s_name,
                    'sign_date': str(s_date) if s_date else '',
                    'supplier': s_supplier, 'brand': s_brand,
                    'notes': s_notes, 'location': s_location
                })
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

# ==================== Tab 2: 样品列表 ====================
with tab2:
    st.subheader("📊 样品列表")

    import datetime as dt
    today = dt.date.today()

    # 搜索和筛选（紧凑排版）
    c1, c2, c3, c4 = st.columns([2.5, 1.5, 1.5, 1.5])
    with c1:
        search = st.text_input("🔍 搜索", placeholder="样品名称/SKU/供应商", label_visibility="collapsed")
    with c2:
        filter_bg = st.selectbox("BG筛选", ["全部"] + get_sample_bg_list(), label_visibility="collapsed")
    with c3:
        filter_status = st.selectbox("状态筛选", ["全部", "🟢 正常", "🟡 临期(30天)", "🔴 已过期"], label_visibility="collapsed")
    with c4:
        filter_instock = st.selectbox("在库筛选", ["全部", "✅ 在库", "已出库"], label_visibility="collapsed")

    # 先获取所有样品（最多5000条）用于状态筛选
    all_samples, total = get_samples(
        search=search,
        bg=filter_bg if filter_bg != "全部" else "",
        page=1,
        per_page=5000
    )

    # 状态筛选（先筛选再分页）
    filtered_all = []
    for r in all_samples:
        sign = str(r.get('sign_date', '')).replace('.', '-')
        expiry_raw = str(r.get('expiry_date', ''))
        expiry = expiry_raw if expiry_raw else ''
        if not expiry and sign and sign != 'None':
            try:
                if len(sign) == 7: sign += '-01'
                d = dt.datetime.strptime(sign[:10], '%Y-%m-%d').date()
                expiry = (d + dt.timedelta(days=365)).strftime('%Y-%m-%d')
            except: pass
        status = '正常'
        try:
            if expiry:
                edate = dt.datetime.strptime(expiry, '%Y-%m-%d').date()
                if edate < today:
                    status = '已过期'
                elif (edate - today).days <= 30:
                    status = '临期'
        except: pass
        if filter_status == "🟢 正常" and status != '正常': continue
        if filter_status == "🟡 临期(30天)" and status != '临期': continue
        if filter_status == "🔴 已过期" and status != '已过期': continue
        if filter_instock == "✅ 在库" and r.get('out_status', '在库') != '在库': continue
        if filter_instock == "已出库" and r.get('out_status', '在库') == '在库': continue
        filtered_all.append((r, expiry, status))

    filtered_total = len(filtered_all)
    total_pages = max(1, (filtered_total + 99) // 100)
    start = (st.session_state.sp_page - 1) * 100
    filtered = filtered_all[start:start+100]

    # 分页
    c_pg1, c_pg2, c_pg3 = st.columns([2, 1, 2])
    with c_pg2:
        pg = st.selectbox("页码", range(1, total_pages + 1),
                          index=st.session_state.sp_page - 1 if total_pages else 0,
                          key='sp_page_sel', label_visibility="collapsed")
        if pg != st.session_state.sp_page:
            st.session_state.sp_page = pg
            st.rerun()

    # 导出按钮
    c_exp = st.container()
    with c_exp:
        if st.button("📥 导出当前筛选结果CSV", use_container_width=True):
            df_export = pd.DataFrame([{'BG':r['bg'],'SKU':r['sku'],'样品名称':r['sample_name'],
                                       '签样日期':r['sign_date'],'供应商':r['supplier'],
                                       '放置区域':r['location'],'备注':r['notes']} for r,_,_ in filtered_all])
            csv = df_export.to_csv(index=False).encode('utf-8-sig')
            st.download_button("下载 samples.csv", csv, "samples_export.csv", "text/csv",
                               use_container_width=True)

    status_label = f"（已筛选 {filter_status}）" if filter_status != "全部" else ""
    st.markdown(f"共 **{filtered_total}** 条记录 {status_label} (第 {st.session_state.sp_page}/{total_pages} 页)")

    if filtered:
        # 重建选中列表
        selected_now = []
        # 批量删除按钮
        if st.session_state.get('sp_selected'):
            st.warning(f"已选中 **{len(st.session_state.sp_selected)}** 条记录 — 👇 勾选完成后点击删除")
            col_del1, col_del2 = st.columns([1, 3])
            with col_del1:
                if st.button("🗑️ 确认批量删除", type="primary", use_container_width=True):
                    for sid in st.session_state.sp_selected:
                        delete_sample(sid)
                    st.success(f"已删除 {len(st.session_state.sp_selected)} 条记录")
                    st.session_state.sp_selected = []
                    st.rerun()
        else:
            st.caption("☑ 勾选左侧方框，选中后可批量删除")

        # 表头
        h_chk, h1, h2, h3, h4, h5, h6, h7, h8, h9 = st.columns([0.4, 1.6, 1.2, 0.8, 1, 1, 1, 0.6, 0.6, 0.6])
        h_chk.markdown("**☑**")
        for col, label in [(h1, "样品名称"), (h2, "SKU"), (h3, "BG"), (h4, "供应商"),
                            (h5, "到期日期"), (h6, "状态"), (h7, "在库"), (h8, ""), (h9, "")]:
            col.markdown(f"**{label}**")
        st.markdown("---")

        for r, expiry, status in filtered:
            status_label = {'正常': '🟢 正常', '临期': '🟡 临期', '已过期': '🔴 已过期'}.get(status, '🟢 正常')
            scolor = {'正常': '#28a745', '临期': '#ffc107', '已过期': '#dc3545'}.get(status, '#28a745')
            out_status = r.get('out_status', '在库')
            out_color = '#dc3545' if out_status == '已出库' else '#28a745'

            chk, v1, v2, v3, v4, v5, v6, v7, v8, v9 = st.columns([0.4, 1.6, 1.2, 0.8, 1, 1, 1, 0.6, 0.6, 0.6])
            with chk:
                checked = st.checkbox("", key=f"spck_{r['id']}", label_visibility="collapsed")
                if checked:
                    selected_now.append(r['id'])

            with v1: st.markdown(f"{r.get('sample_name','')[:25]}")
            with v2: st.caption((r.get('sku','') or '-')[:15])
            with v3: st.caption((r.get('bg','') or '-')[:10])
            with v4: st.caption((r.get('supplier','') or '-')[:12])
            with v5: st.caption(expiry[:10] if expiry else '-')
            with v6: st.markdown(f"<span style='color:{scolor};font-weight:bold'>{status_label}</span>", unsafe_allow_html=True)
            with v7: st.markdown(f"<span style='color:{out_color};font-weight:bold'>{out_status}</span>", unsafe_allow_html=True)
            with v8:
                if out_status == '已出库':
                    if st.button("↩️", key=f"ret_{r['id']}", help="归还"):
                        sample_return(r['id'])
                        st.success("已归还")
                        st.rerun()
                else:
                    if st.button("📤", key=f"out_{r['id']}", help="出库"):
                        st.session_state.sp_out_id = r['id']
                        st.session_state.sp_out_name = r.get('sample_name','')
                        st.rerun()
            with v9:
                if st.button("✏️", key=f"e_{r['id']}", help="编辑"):
                    st.session_state.sp_edit_id = r['id']
                    st.rerun()

        # 同步选中列表
        st.session_state.sp_selected = selected_now
    else:
        st.info("暂无样品记录")

# ==================== Tab 3: 出库记录 ====================
with tab3:
    st.subheader("📤 样品出库记录")
    out_records = get_outbound_records(limit=200)
    if out_records:
        df_out = pd.DataFrame(out_records)
        cols = ['sample_name', 'sku', 'bg', 'qty', 'out_date', 'borrower', 'department', 'reason', 'notes']
        df_show = df_out[[c for c in cols if c in df_out.columns]].copy()
        df_show.columns = ['样品名称', 'SKU', 'BG', '数量', '出库日期', '领用人', '部门', '原因', '备注']
        st.markdown(f"共 **{len(out_records)}** 条出库记录")
        st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
    else:
        st.info("暂无出库记录")
