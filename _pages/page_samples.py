"""
品质系统管理 - 样品管理
"""

import streamlit as st
import pandas as pd
import json
import importlib
from datetime import date
import database as database_module
from database import (
    init_db, get_samples, add_sample, update_sample, delete_sample,
    get_bg_list, get_brand_list, get_sample_bg_list,
    sample_outbound, sample_return, sample_return_by_record, get_outbound_records,
    get_connection, import_samples_from_workbook_file
)

from pages._utils import render_sidebar, render_topbar, render_import_export_buttons, ui_empty_state, ui_danger_button, ui_table, ui_data_editor
from components.modal import confirm_dialog

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# 渲染侧边栏导航
st.session_state.current_page = "样品管理"
with st.sidebar:
    render_sidebar()
render_topbar("样品管理")


st.title("样品管理")


def _sample_import_file_handler(uploaded_file, db_conn):
    summary = import_samples_from_workbook_file(uploaded_file, db_conn=db_conn)
    return True, {
        "message": summary["message"],
        "preview_df": summary["preview_df"],
        "warnings": summary["warnings"],
        "success": (
            f"自动清洗导入完成：新增 {summary['inserted']} 条，"
            f"更新 {summary['updated']} 条，跳过 {summary['skipped']} 条。"
        ),
    }


# 初始化 session state
for k, v in [('sp_page', 1), ('sp_edit_id', None), ('sp_selected', []), ('sp_out_id', None), ('sp_out_name', ''),
             ('sp_outb_toast', ''), ('sp_outb_err',
              ''), ('sp_batch_selected_ids', []),
             ('sp_batch_delete_confirm', []), ('sp_batch_scope', '手动选择')]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── 出库反馈提示（跨 rerun 持久化）──
if st.session_state.sp_outb_toast:
    st.toast(st.session_state.sp_outb_toast)
    st.session_state.sp_outb_toast = ''
if st.session_state.sp_outb_err:
    st.toast(st.session_state.sp_outb_err)
    st.session_state.sp_outb_err = ''

# ── Excel 导入 / 导出 / 模板下载（通用组件）──
conn = get_connection()
sample_template = pd.DataFrame(columns=[
    'bg', 'sku', 'sample_name', 'sign_date', 'supplier',
    'brand', 'notes', 'location', 'expiry_date'
])
render_import_export_buttons(
    conn,
    'samples',
    sample_template,
    key_prefix='sp_',
    import_file_handler=_sample_import_file_handler,
    import_help_text="可直接上传原始《签样记录》Excel，系统会自动遍历所有子表、清洗列名并合并录入。",
)
conn.close()

with st.expander(" 远程同步样品数据", expanded=False):
    st.caption("不在公司局域网时，用本地导出的同步包，在 Win 服务器网页这里导入即可。默认保留服务器现有的出库状态和库存。")

    database_sync = importlib.reload(database_module)
    build_sync_package = getattr(
    database_sync, "build_samples_sync_package", None)
    merge_sync_package = getattr(
    database_sync, "merge_samples_sync_package", None)

    if not build_sync_package or not merge_sync_package:
        st.warning("当前运行进程还没加载到远程同步能力，刷新页面后再试一次。")
    else:
        sync_payload = build_sync_package()
        sync_bytes = json.dumps(
    sync_payload,
    ensure_ascii=False,
     indent=2).encode("utf-8")
        sync_col1, sync_col2 = st.columns([1, 1])

        with sync_col1:
            st.download_button(
                "导出样品同步包",
                data=sync_bytes,
                file_name=f"samples_sync_{date.today().strftime('%Y%m%d')}.json",
                mime="application/json",
                width="stretch",
                key="sp_sync_export",
            )
            st.caption(f"当前同步包包含 {sync_payload['sample_count']} 条样品")

        with sync_col2:
            uploaded_sync = st.file_uploader(
                "上传样品同步包",
                type=["json"],
                key="sp_sync_import_file",
                label_visibility="collapsed",
            )

        if uploaded_sync is not None:
            try:
                import_payload = json.loads(
    uploaded_sync.getvalue().decode("utf-8"))
            except Exception as e:
                st.error(f"同步包解析失败：{e}")
                st.stop()

            incoming_count = len(
    import_payload.get(
        "samples",
        [])) if isinstance(
            import_payload,
             dict) else 0
            st.info(
                f"同步包时间：{import_payload.get('generated_at', '未知')} |"
                f"样品数：{incoming_count}"
            )

            if st.button("合并到当前服务器", type="primary", width="stretch",
                         key="sp_sync_import_confirm"):
                ok, msg, summary = merge_sync_package(import_payload)
                if ok:
                    st.success(msg)
                    if summary:
                        st.caption(
                            f"导入 {summary.get('incoming', 0)} 条 |"
                            f"新增 {summary.get('inserted', 0)} |"
                            f"更新 {summary.get('updated', 0)} |"
                            f"重复跳过 {summary.get('duplicate_keys', 0)}"
                        )
                    st.rerun()
                else:
                    st.error(msg)

# 首次加载提示
samples_check, _ = get_samples(per_page=1)
if not samples_check:
    ui_empty_state("当前无样品记录", hint="可使用上方「导出 / 下载导入模板」按钮导入数据。")

bg_list = get_bg_list()
brand_list = get_brand_list()

# ==================== 编辑/出库表单（顶部，优先级高于tab） ====================
if st.session_state.sp_out_id:
    st.markdown("---")
    st.subheader(f"出库登记 — {st.session_state.sp_out_name}")
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
            if st.form_submit_button("确认出库", type="primary", width="stretch"):
                if not out_borrower:
                    st.error("领用人不能为空!")
                else:
                    ok, msg = sample_outbound(
                        st.session_state.sp_out_id, out_qty,
                        str(out_date), out_borrower, out_dept, out_reason, out_notes
                    )
                    if ok:
                        st.session_state.sp_outb_toast = f"出库成功！{st.session_state.sp_out_name} 已出库"
                        st.session_state.sp_out_id = None
                        st.rerun()
                    else:
                        st.session_state.sp_outb_err = f"出库失败：{msg}"
                        st.session_state.sp_out_id = None
                        st.rerun()
        with c2:
            if st.form_submit_button("取消", width="stretch"):
                st.session_state.sp_out_id = None
                st.rerun()
    st.stop()

if st.session_state.sp_edit_id is not None:
    from database import get_connection
    conn = get_connection()
    row = conn.execute("SELECT * FROM samples WHERE id=?",
                       (st.session_state.sp_edit_id,)).fetchone()
    conn.close()
    if row:
        edit_sp = dict(row)
        st.markdown("---")
        st.subheader(f"编辑样品 #{st.session_state.sp_edit_id}")

        with st.form("sample_edit_form"):
            c1, c2 = st.columns(2)
            with c1:
                sample_name = st.text_input(
                    "样品名称 *", value=edit_sp.get('sample_name', ''))
                bg_val = edit_sp.get('bg', '')
                bg_options = [""] + get_sample_bg_list()
                bg = st.selectbox(
    "BG (可选)",
    bg_options,
    index=bg_options.index(bg_val) if bg_val in bg_options else 0,
     format_func=lambda x: "（无）" if x == "" else x)
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
                brand = st.selectbox(
    "品牌",
    [""] +
    brand_list,
    index=(
        [""] +
         brand_list).index(brand_val) if brand_val in brand_list else 0)
                supplier = st.text_input(
    "供应商", value=edit_sp.get(
        'supplier', ''))
            with c4:
                location = st.text_input(
    "放置区域", value=edit_sp.get(
        'location', ''))
            notes = st.text_area("备注", value=edit_sp.get('notes', ''))
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.form_submit_button(
                    "保存修改", type="primary", width="stretch"):
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
                if st.form_submit_button("取消编辑", width="stretch"):
                    st.session_state.sp_edit_id = None
                    st.rerun()
    else:
        st.session_state.sp_edit_id = None
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["样品登记", "样品列表", "出库登记", "出库记录"])

# ==================== Tab 1: 登记 ====================
with tab1:
    st.subheader("样品登记")
    with st.form("sample_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            s_name = st.text_input(
    "样品名称 *",
    placeholder="例如：B22A 红色",
     key='new_name')
            s_bg = st.selectbox(
    "BG (可选)",
    [""] + get_sample_bg_list(),
    key='new_bg',
     format_func=lambda x: "（无）" if x == "" else x)
        with c2:
            s_sku = st.text_input(
    "SKU", placeholder="例如：ABT-05-B22A", key='new_sku')
            s_date = st.date_input("签样日期", value=date.today(), key='new_date')
        c3, c4 = st.columns(2)
        with c3:
            s_brand = st.selectbox("品牌", [""] + brand_list, key='new_brand')
            s_supplier = st.text_input("供应商", key='new_supplier')
        with c4:
            s_location = st.text_input(
    "放置区域", placeholder="QA样品室1", key='new_location')
        s_notes = st.text_area("备注", key='new_notes')
        if st.form_submit_button("提交登记", type="primary", width="stretch"):
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
    st.subheader("样品列表")

    import datetime as dt
    today = dt.date.today()

    # 搜索和筛选（紧凑排版）
    c1, c2, c3, c4 = st.columns([2.5, 1.5, 1.5, 1.5])
    with c1:
        search = st.text_input(
    "搜索",
    placeholder="样品名称/SKU/供应商",
     label_visibility="collapsed")
    with c2:
        filter_bg = st.selectbox(
    "BG筛选",
    ["全部"] + get_sample_bg_list(),
     label_visibility="collapsed")
    with c3:
        filter_status = st.selectbox(
            "状态筛选", ["全部", "正常", "临期(30天)", "已过期"], label_visibility="collapsed")
    with c4:
        filter_instock = st.selectbox(
            "在库筛选", ["全部", "在库", "已出库"], label_visibility="collapsed")

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
        if filter_status == "正常" and status != '正常': continue
        if filter_status == "临期(30天)" and status != '临期': continue
        if filter_status == "已过期" and status != '已过期': continue
        if filter_instock == "在库" and r.get('out_status', '在库') != '在库': continue
        if filter_instock == "已出库" and r.get('out_status', '在库') == '在库': continue
        filtered_all.append((r, expiry, status))

    filtered_total = len(filtered_all)

    if filtered_total:
        # 构建 DataFrame
        rows = []
        for r, expiry, status in filtered_all:
            rows.append({
                'id': r['id'],
                'sample_name': r.get('sample_name', ''),
                'sku': r.get('sku', ''),
                'bg': r.get('bg', ''),
                'brand': r.get('brand', ''),
                'supplier': r.get('supplier', ''),
                'sign_date': r.get('sign_date', ''),
                'expiry_date': expiry if expiry else '',
                'status': status,
                'stock_qty': r.get('stock_qty', 1),
                'out_status': r.get('out_status', '在库'),
                'location': r.get('location', ''),
                'notes': r.get('notes', ''),
            })

        df_sp = pd.DataFrame(rows)

        # ── 实时业务统计看板（基于 out_status + stock_qty 实时计算）──
        in_stock_count = sum(1 for r in rows if r['out_status'] == '在库')
        out_stock_count = sum(1 for r in rows if r['out_status'] == '已出库')
        total_count = len(rows)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("🧪 总样品档案", f"{total_count} 项")
        with m2:
            st.metric("✅ 当前在库可用", f"{in_stock_count} 项")
        with m3:
            st.metric("⏳ 已出库未还", f"{out_stock_count} 项")
        with m4:
            active_filter = []
            if filter_status != "全部":
                active_filter.append(filter_status)
            if filter_instock != "全部":
                active_filter.append(filter_instock)
            filter_tag = "、".join(active_filter) if active_filter else "无"
            st.metric("🔍 当前筛选", filter_tag)

        # 列配置
        col_config = {
            'id': st.column_config.Column(label='ID', disabled=True),
            'status': st.column_config.Column(label='状态', disabled=True),
            'expiry_date': st.column_config.Column(label='到期日期', disabled=True),
            'out_status': st.column_config.Column(label='在库', disabled=True),
        }

        # ── 每页显示行数选择器 ──
        _sp_row_opts = [10, 20, 50, 100]
        _sp_def = st.session_state.get("sample_page_size", 20)
        _spc1, _spc2 = st.columns([1, 4])
        with _spc1:
            _spsz = st.selectbox("每页行数", options=_sp_row_opts,
                                 index=_sp_row_opts.index(
                                     _sp_def) if _sp_def in _sp_row_opts else 1,
                                 key="sp_page_size_sel", label_visibility="collapsed")
        if st.session_state.get("sp_page_size_sel", 20) != st.session_state.get(
            "sample_page_size", 20):
            st.session_state["sample_page_size"] = st.session_state["sp_page_size_sel"]
            st.rerun()
        _sp_psz = st.session_state.get("sample_page_size", 20)
        _sp_disp = min(_sp_psz, len(df_sp))
        with _spc2:
            st.caption(f"共 **{len(df_sp)}** 条 · 显示 **{_sp_disp}** 行")

        # 可编辑表格（带删除支持，动态高度）
        editor_key = 'sp_editor'
        edited = ui_data_editor(
            df_sp,
            key=editor_key,
            width="stretch",
            num_rows="dynamic",
            column_config=col_config,
            column_order=['sample_name', 'sku', 'bg', 'brand', 'supplier',
                          'stock_qty', 'sign_date', 'expiry_date', 'status', 'out_status',
                          'location', 'notes'],
            hide_index=True,
            height=min(40 * _sp_disp + 48, 800),
            disabled=['id', 'status', 'expiry_date', 'out_status'],
        )

        # 操作按钮行
        ob1, ob2, ob3 = st.columns([1, 1, 2])

        with ob1:
            if st.button("保存修改", key='sp_save_btn',
                         width="stretch", type="primary"):
                session_data = st.session_state.get(editor_key, {})
                edited_rows = session_data.get("edited_rows", {})
                deleted_rows = session_data.get("deleted_rows", [])
                added_rows = session_data.get("added_rows", [])

                conn2 = get_connection()
                changes = False
                try:
                    if edited_rows:
                        for row_idx_str, edits in edited_rows.items():
                            row_idx = int(row_idx_str)
                            if row_idx >= len(df_sp):
                                continue
                            pk = int(df_sp.iloc[row_idx]['id'])
                            set_clause = ",".join(
                                [f'"{c}" = ?' for c in edits if c != 'id'])
                            vals = [
    v for c, v in edits.items() if c != 'id'] + [pk]
                            if vals:
                                conn2.execute(
    f'UPDATE samples SET {set_clause} WHERE id = ?', vals)
                        changes = True
                        st.toast(f"已更新 {len(edited_rows)} 处修改")
                    if added_rows:
                        for added in added_rows:
                            if not any(v and str(v).strip()
                                       for v in added.values()):
                                continue
                            # 过滤掉 id 和计算列 status（非 DB 列）
                            clean = {
    k: v for k, v in added.items() if k not in (
        'id', 'status')}
                            cols = list(clean.keys())
                            vals = list(clean.values())
                            conn2.execute(
                                f'INSERT INTO samples ({", ".join(cols)}) VALUES ({", ".join(["?"]*len(cols))})',
                                vals
                            )
                        changes = True
                        st.toast(f"已新增 {len(added_rows)} 条")
                    if deleted_rows:
                        for row_idx in sorted(deleted_rows, reverse=True):
                            if row_idx < len(df_sp):
                                pk = int(df_sp.iloc[row_idx]['id'])
                                conn2.execute(
    'DELETE FROM samples WHERE id = ?', (pk,))
                        changes = True
                        st.toast(f"已删除 {len(deleted_rows)} 条")
                    conn2.commit()
                except Exception as e:
                    st.error(f"操作失败: {e}")
                    conn2.rollback()
                finally:
                    conn2.close()
                if changes:
                    st.rerun()

        with ob2:
            if st.button("刷新", key='sp_refresh_btn', width="stretch"):
                st.rerun()

        with ob3:
            st.caption("双击单元格编辑 | 勾选行 + Delete 删除 | 底部空行新增")

        # 样品档案批量编辑 / 删除
        with st.expander(" 批量编辑 / 删除样品档案", expanded=False):
            sample_options = {int(r['id']): f"[{r['id']}] {r['sample_name'] or '未命名'} ({r['sku'] or '无SKU'})"
                              for r in rows}
            current_ids = list(sample_options.keys())
            st.caption("选择后可统一修改 BG、品牌、供应商、放置区域、备注、签样日期、库存数，或批量删除样品档案。")

            scope_all_label = f"当前筛选结果全部（{len(current_ids)}项）"
            scope_options = ["手动选择", scope_all_label]
            if st.session_state.sp_batch_scope not in scope_options:
                st.session_state.sp_batch_scope = "手动选择"

                sel_tools = st.columns([1.4, 1, 2.6])
                with sel_tools[0]:
                    batch_scope = st.selectbox(
                        "处理范围",
                        scope_options,
                        key="sp_batch_scope",
                        label_visibility="collapsed",
                    )
                with sel_tools[1]:
                    if batch_scope == "手动选择" and st.button("清空手动选择", key="sp_batch_clear",
                                                           width="stretch"):
                        st.session_state.sp_batch_selected_ids = []
                        st.session_state.sp_batch_delete_confirm = []
                        st.rerun()

                if batch_scope == scope_all_label:
                    selected_ids = current_ids
                    st.info(f"将处理当前筛选结果中的全部 {len(selected_ids)} 个样品。")
                else:
                    selected_ids = st.multiselect(
                        "选择样品",
                        options=current_ids,
                        format_func=lambda sid: sample_options.get(
                            int(sid), str(sid)),
                        key="sp_batch_selected_ids",
                        placeholder="选择要批量处理的样品",
                    )
                    selected_ids = [
        int(sid) for sid in selected_ids if int(sid) in sample_options]

                if selected_ids:
                    st.info(f"已选择 {len(selected_ids)} 个样品")
                    batch_tab_edit, batch_tab_delete = st.tabs(["批量编辑", "批量删除"])

                    with batch_tab_edit:
                        st.caption("仅会更新已勾选的字段；未勾选字段保持原值。")
                        e1, e2, e3 = st.columns(3)
                        with e1:
                            apply_bg = st.checkbox(
        "修改 BG", key="sp_batch_apply_bg")
                            batch_bg = st.selectbox(
                                "BG",
                                [""] + get_sample_bg_list(),
                                key="sp_batch_bg",
                                disabled=not apply_bg,
                                format_func=lambda x: "（清空）" if x == "" else x,
                            )
                            apply_supplier = st.checkbox(
        "修改供应商", key="sp_batch_apply_supplier")
                            batch_supplier = st.text_input(
        "供应商", key="sp_batch_supplier", disabled=not apply_supplier)
                        with e2:
                            apply_brand = st.checkbox(
        "修改品牌", key="sp_batch_apply_brand")
                            batch_brand = st.selectbox(
                                "品牌",
                                [""] + brand_list,
                                key="sp_batch_brand",
                                disabled=not apply_brand,
                                format_func=lambda x: "（清空）" if x == "" else x,
                            )
                            apply_location = st.checkbox(
        "修改放置区域", key="sp_batch_apply_location")
                            batch_location = st.text_input(
        "放置区域", key="sp_batch_location", disabled=not apply_location)
                        with e3:
                            apply_sign_date = st.checkbox(
        "修改签样日期", key="sp_batch_apply_sign_date")
                            batch_sign_date = st.date_input("签样日期", value=date.today(), key="sp_batch_sign_date",
                                                            disabled=not apply_sign_date)
                            apply_stock_qty = st.checkbox(
        "修改库存数", key="sp_batch_apply_stock_qty")
                            batch_stock_qty = st.number_input("库存数", min_value=0, step=1, value=1,
                                                              key="sp_batch_stock_qty",
                                                              disabled=not apply_stock_qty)

                        apply_notes = st.checkbox(
        "修改备注", key="sp_batch_apply_notes")
                        batch_notes = st.text_area(
        "备注", key="sp_batch_notes", disabled=not apply_notes)

                        updates = {}
                        if apply_bg:
                            updates['bg'] = batch_bg
                        if apply_supplier:
                            updates['supplier'] = batch_supplier
                        if apply_brand:
                            updates['brand'] = batch_brand
                        if apply_location:
                            updates['location'] = batch_location
                        if apply_sign_date:
                            updates['sign_date'] = str(
                                batch_sign_date) if batch_sign_date else ''
                        if apply_stock_qty:
                            updates['stock_qty'] = int(batch_stock_qty)
                            updates['out_status'] = '已出库' if int(
                                batch_stock_qty) <= 0 else '在库'
                        if apply_notes:
                            updates['notes'] = batch_notes

                        if st.button("应用到选中样品", key="sp_batch_apply_edit",
                                     type="primary", width="stretch"):
                            if not updates:
                                st.warning("请先勾选至少一个要修改的字段。")
                            else:
                                conn_batch = get_connection()
                                try:
                                    set_clause = ",".join(
                                        [f'"{col}" = ?' for col in updates])
                                    values = list(updates.values())
                                    placeholders = ",".join(
                                        ["?"] * len(selected_ids))
                                    conn_batch.execute(
                                        f'UPDATE samples SET {set_clause} WHERE id IN ({placeholders})',
                                        values + selected_ids,
                                    )
                                    conn_batch.commit()
                                    st.success(f"已更新 {len(selected_ids)} 个样品")
                                    st.rerun()
                                except Exception as e:
                                    conn_batch.rollback()
                                    st.error(f"批量编辑失败：{e}")
                                finally:
                                    conn_batch.close()

                    with batch_tab_delete:
                        st.warning("批量删除会同时移除这些样品对应的出库记录，操作不可撤销。")
                        preview_names = [sample_options[sid]
                            for sid in selected_ids[:8]]
                        st.write("将删除：")
                        st.write("；".join(preview_names) +
         ("..." if len(selected_ids) > 8 else ""))

                        confirm_ids = [
        int(sid) for sid in st.session_state.get(
            "sp_batch_delete_confirm", [])]
                        if confirm_ids != selected_ids:
                            if st.button("批量删除选中样品", key="sp_batch_delete_prepare",
                                         width="stretch"):
                                st.session_state.sp_batch_delete_confirm = selected_ids
                                st.rerun()
                        else:
                            st.warning(f"将删除选中的 {len(selected_ids)} 个样品档案及其出库记录，此操作不可撤销。")
                            if ui_danger_button("确认删除", key="sp_batch_delete_confirm_btn",
                                                 type="primary", use_container_width=True):
                                confirm_dialog(
                                    "确认批量删除样品",
                                    f"确定要删除选中的 **{len(selected_ids)}** 个样品档案吗？此操作不可撤销。",
                                    state_key="sp_batch_delete_do",
                                    state_value=selected_ids,
                                    confirm_label="确认删除",
                                    confirm_type="primary",
                                )
                            if st.button("取消删除", key="sp_batch_delete_cancel",
                                         use_container_width=True):
                                st.session_state.sp_batch_delete_confirm = []
                                st.rerun()
                        # F3：二次确认后执行批量删除（与 else 同级，循环外）
                        if st.session_state.get("sp_batch_delete_do"):
                            _del_ids = st.session_state.sp_batch_delete_do
                            st.session_state.sp_batch_delete_do = None
                            conn_batch = get_connection()
                            try:
                                placeholders = ",".join(
                                    ["?"] * len(_del_ids))
                                conn_batch.execute(
                                    f"DELETE FROM sample_outbound WHERE sample_id IN ({placeholders})",
                                    _del_ids,
                                )
                                conn_batch.execute(
                                    f"DELETE FROM samples WHERE id IN ({placeholders})",
                                    _del_ids,
                                )
                                conn_batch.commit()
                                st.session_state.sp_batch_selected_ids = []
                                st.session_state.sp_batch_delete_confirm = []
                                st.success(f"已删除 {len(_del_ids)} 个样品")
                                st.rerun()
                            except Exception as e:
                                conn_batch.rollback()
                                st.error(f"批量删除失败：{e}")
                            finally:
                                conn_batch.close()
                else:
                    st.caption("请先选择要处理的样品。")

            # 出库/归还快捷操作区
            with st.expander("批量操作（出库 / 归还）", expanded=False):
                col_so1, col_so2 = st.columns(2)
                with col_so1:
                    # 选择在库样品
                    in_stock_opts = [(idx, f"[{r['id']}] {r['sample_name']} ({r['sku']})")
                                     for idx, r in enumerate(rows) if r['out_status'] == '在库']
                    if in_stock_opts:
                        out_borrower = st.text_input("批量领用人 *", key="sp_out_borrower",
                                                     placeholder="必须填写领用人")
                        out_reason = st.selectbox("批量出库原因", ["检测", "借用", "报废", "归还厂商", "其他"],
                                                  key="sp_out_reason")
                        out_selected = st.multiselect(
                            "选择出库样品",
                            options=[idx for idx, _ in in_stock_opts],
                            format_func=lambda i: next(
        (l for j, l in in_stock_opts if j == i), ''),
                            key='sp_out_multiselect'
                        )
                        if out_selected and st.button(
                            "确认出库", key='sp_out_exec', width="stretch"):
                            if not out_borrower.strip():
                                st.error("批量出库必须填写领用人")
                                st.stop()
                            done = 0
                            for idx in out_selected:
                                try:
                                    ok, _ = sample_outbound(
                                        int(rows[idx]['id']), 1, str(date.today()),
                                        out_borrower.strip(), '', out_reason, '')
                                    if ok: done += 1
                                except: pass
                            if done:
                                st.success(f"已出库 {done} 个样品")
                                st.rerun()
                    else:
                        st.caption("没有在库样品")
                with col_so2:
                    out_stock_opts = [(idx, f"[{r['id']}] {r['sample_name']} ({r['sku']})")
                                      for idx, r in enumerate(rows) if r['out_status'] == '已出库']
                    if out_stock_opts:
                        ret_selected = st.multiselect(
                            "选择归还样品",
                            options=[idx for idx, _ in out_stock_opts],
                            format_func=lambda i: next(
        (l for j, l in out_stock_opts if j == i), ''),
                            key='sp_ret_multiselect'
                        )
                        if ret_selected and st.button(
                            "确认归还", key='sp_ret_exec', width="stretch"):
                            done = 0
                            for idx in ret_selected:
                                try:
                                    sample_return(int(rows[idx]['id']))
                                    done += 1
                                except: pass
                            if done:
                                st.success(f"已归还 {done} 个样品")
                                st.rerun()
                    else:
                        st.caption("没有已出库样品")

    else:
        ui_empty_state("暂无符合条件的样品记录", hint="尝试调整搜索关键词或筛选条件。")

# ==================== Tab 3: 出库登记 ====================
with tab3:
    st.subheader("样品出库登记")
    all_samples, _ = get_samples(per_page=2000)
    in_stock_samples = [
    s for s in all_samples if s.get(
        'out_status', '在库') == '在库']

    if in_stock_samples:
        # 搜索过滤（保持搜索状态）
        if 'outbound_search_term' not in st.session_state:
            st.session_state.outbound_search_term = ''
        search_term = st.text_input("搜索样品 (名称/SKU) 搜索样品 (名称/SKU)", value=st.session_state.outbound_search_term,
                                    placeholder="输入关键词过滤...", key="outbound_search_input")
        st.session_state.outbound_search_term = search_term

        filtered_samples = in_stock_samples
        if search_term:
            filtered_samples = [s for s in in_stock_samples
                                if search_term.lower() in (s.get('sample_name', '') + s.get('sku', '')).lower()]
            st.caption(
                f"匹配 {len(filtered_samples)} / {len(in_stock_samples)} 个样品")

        if filtered_samples:
            sample_opts = {
    s['id']: f"[{s.get('bg','')}] {s.get('sample_name','')} ({s.get('sku','')})" for s in filtered_samples}
            col_o1, col_o2 = st.columns(2)
            with col_o1:
                out_sample_id = st.selectbox("选择样品 *", list(sample_opts.keys()),
                                             format_func=lambda x: sample_opts[x], key="ob_sel")
                out_quantity = st.number_input(
    "出库数量", min_value=1, value=1, key="ob_qty")
            with col_o2:
                out_receiver = st.text_input(
    "领用人 *", placeholder="领用人姓名", key="ob_recv")
                out_date = st.date_input(
    "出库日期", value=date.today(), key="ob_date")
            out_purpose = st.text_area(
    "用途说明", placeholder="出库原因及用途...", key="ob_purpose")
            out_notes = st.text_input(
    "备注", placeholder="其他备注信息", key="ob_notes")

            if st.button("确认出库", type="primary",
                         width="stretch", key="ob_submit"):
                if not out_receiver:
                    st.error("领用人不能为空！")
                elif not out_sample_id:
                    st.error("请选择样品！")
                else:
                    ok, msg = sample_outbound(sample_id=out_sample_id, borrower=out_receiver,
                                              out_date=str(out_date), reason=out_purpose,
                                              qty=out_quantity, notes=out_notes)
                    if ok:
                        st.session_state.sp_outb_toast = f"出库成功！样品已出库，领用人：{out_receiver}"
                        st.rerun()
                    else:
                        st.session_state.sp_outb_err = f"出库失败：{msg}"
                        st.rerun()
        else:
            st.warning("无匹配样品，请调整搜索关键词")
    else:
        ui_empty_state("当前无在库样品可供出库", hint="样品归还入库后即可在此出库。")

# ==================== Tab 4: 出库记录 ====================
with tab4:
    st.subheader(" 样品出库记录")

    # 初始化归还反馈状态
    if 'return_toast_ok' not in st.session_state:
        st.session_state.return_toast_ok = ''
        if 'return_toast_err' not in st.session_state:
            st.session_state.return_toast_err = ''

        if st.session_state.return_toast_ok:
            st.toast(st.session_state.return_toast_ok)
            st.session_state.return_toast_ok = ''
        if st.session_state.return_toast_err:
            st.toast(st.session_state.return_toast_err)
            st.session_state.return_toast_err = ''

    out_records = get_outbound_records(limit=300)
    if out_records:
        # 构建展示 DataFrame
        df_out = pd.DataFrame(out_records)
        # 确保关键列存在
        for col in ['sample_name', 'sku', 'bg', 'qty', 'out_date', 'borrower',
                    'department', 'reason', 'notes', 'is_returned', 'return_date']:
            if col not in df_out.columns:
                df_out[col] = '' if col != 'is_returned' else 0

        # ⚠️ int64 不能 int() 转换，确保 is_returned 为原生 Python int
        df_out['is_returned'] = df_out['is_returned'].apply(lambda x: int(x) if x else 0)

        total_all = len(df_out)
        returned_count = int(df_out['is_returned'].sum())
        unreturned_count = total_all - returned_count

        # 仅展示未归还的出库记录
        df_out = df_out[df_out['is_returned'] == 0]

        show_cols = ['sample_name', 'sku', 'bg', 'qty', 'out_date', 'borrower',
                     'department', 'reason', 'notes']

        df_display = df_out[show_cols].copy()

        st.caption(f"**{unreturned_count}** 条未归还 | 共 {total_all} 条（含 {returned_count} 条已归还）")

        # ── 一键归还提示 ──
        st.info("点击下方「一键归还」勾选框即可归还，系统会自动恢复库存并记录归还日期。")

        # ── 列配置 ──
        col_config = {
            'sample_name': st.column_config.TextColumn('样品名称', disabled=True),
            'sku': st.column_config.TextColumn('SKU', disabled=True),
            'bg': st.column_config.TextColumn('BG', disabled=True),
            'qty': st.column_config.NumberColumn('数量', disabled=True),
            'out_date': st.column_config.TextColumn('出库日期', disabled=True),
            'borrower': st.column_config.TextColumn('领用人', disabled=True),
            'department': st.column_config.TextColumn('部门', disabled=True),
            'reason': st.column_config.TextColumn('原因', disabled=True),
            'notes': st.column_config.TextColumn('备注', disabled=True),
        }

        editor_key = 'outbound_editor'
        ui_table(
            df_display,
            width="stretch",
            column_config=col_config,
            column_order=show_cols,
            hide_index=True,
            height=min(len(df_display) * 38 + 38, 600),
        )

        # ── 一键归还：每行一个 checkbox ──
        st.markdown("---")
        st.subheader("一键归还")

        if len(df_out) > 0:
            # 用 id 作为选项值，sample_name+sku 作为 label
            return_options = {}
            for _, row in df_out.iterrows():
                label = f"[{row['id']}] {row.get('sample_name','')} ({row.get('sku','')}) — 出库 {int(row['qty'])}件 — {row.get('out_date','')}"
                return_options[str(int(row['id']))] = label

            selected_returns = st.multiselect(
                "选择要归还的出库记录（可多选）",
                options=list(return_options.keys()),
                format_func=lambda x: return_options[x],
                help="勾选后点击下方「确认归还」按钮",
                key='return_selection'
            )

            if selected_returns:
                if st.button("确认归还", key='sp_ret_batch', width="stretch", type="primary"):
                    ok_count = 0
                    for rid_str in selected_returns:
                        ok, msg = sample_return_by_record(int(rid_str))
                        if ok:
                            ok_count += 1
                    if ok_count > 0:
                        st.session_state.return_toast_ok = f"已归还 {ok_count} 条记录"
                        st.rerun()
                    else:
                        st.session_state.return_toast_err = "归还失败，请检查记录状态"
                        st.rerun()
    else:
        ui_empty_state("暂无出库记录", hint="样品出库后，对应的出库与归还记录会显示在这里。")
