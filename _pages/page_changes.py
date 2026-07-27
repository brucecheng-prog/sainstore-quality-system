"""
品质系统管理 - 变更管理
"""

import streamlit as st
import pandas as pd
import os, sys, json
from datetime import date, datetime
from database import (
    init_db, get_changes, add_change, update_change, update_change_attachments, delete_change,
    import_changes_from_excel, import_changes_dataframe,
    bulk_delete_changes, cleanup_duplicate_changes,
    get_bu_list, get_brand_list, get_users, get_rd_teams, parse_sku_list
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pages._utils import render_sidebar, render_topbar, render_import_export_buttons, ui_empty_state, ui_table, ui_data_editor
from dingtalk_notify import notify_change_submitted
from database import log_activity

# NAS 上传模块：不在页面加载阶段探测，避免切换菜单时阻塞页面。
NAS_AVAILABLE = False
try:
    from nas_client import check_connection as nas_check_conn, upload_file as nas_upload, create_folder as nas_mkdir
    # 具体上传时再连接 NAS；页面入口不再等待网络握手。
    NAS_AVAILABLE = True
except Exception:
    NAS_AVAILABLE = False
    _nas_msg = "导入失败"

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# 渲染侧边栏导航
st.session_state.current_page = "变更管理"
with st.sidebar:
    render_sidebar()
render_topbar("变更管理")



st.title("变更管理")

# 导入数据（始终可用）
with st.expander("从Excel导入变更数据", expanded=False):
    st.caption("上传产品变更汇总表，自动解析并更新/新增变更记录")
    col_i1, col_i2 = st.columns([3, 1])
    with col_i1:
        uploaded_change = st.file_uploader("选择Excel文件", type=['xlsx', 'xls'], key="ch_import", label_visibility="collapsed")
    with col_i2:
        if uploaded_change and st.button("开始导入", width="stretch", type="primary"):
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                tmp.write(uploaded_change.getbuffer())
                tmp_path = tmp.name
            count, msg = import_changes_from_excel(tmp_path)
            os.unlink(tmp_path)
            if count > 0:
                st.success(f"导入成功：{count} 条记录")
            else:
                st.warning(msg)
            st.rerun()

# 首次加载自动导入提示
changes_check, _ = get_changes(per_page=1)
if not changes_check:
    ui_empty_state("当前无变更记录", "可点击上方「 从Excel导入变更数据」上传汇总表，或手动新增一条变更")

tab1, tab2 = st.tabs(["登记变更", "变更记录"])

bu_list = get_bu_list()
brand_list = get_brand_list()
rd_teams = get_rd_teams()
users = get_users()

# ==================== Tab 1: 登记变更 ====================
with tab1:
    st.subheader("产品变更登记")

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

        # 品质负责人多选 + 手动添加
        quality_person_names = [f"{u['name']}" for u in users]
        st.markdown("**待确认人 / 推送对象 \\***")
        st.caption("这里选择的是接收通知、后续要去验货确认的人，不代表已经确认。")
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            confirm_persons = st.multiselect(
                "选择已有人员",
                quality_person_names,
                help="可多选已有的品质负责人",
                label_visibility="collapsed",
            )
        with col_q2:
            manual_confirm = st.text_input(
                "手动添加人员",
                placeholder="输入姓名，多人用逗号分隔",
                label_visibility="visible",
            )

        # 合并：已有选择 + 手动输入
        manual_list = [p.strip() for p in manual_confirm.split(',') if p.strip()] if manual_confirm else []
        all_confirm_persons = list(dict.fromkeys(confirm_persons + manual_list))  # 去重保序
        notify_person = ','.join(all_confirm_persons)

        uploaded_files = st.file_uploader("上传相关文件（支持多选、压缩包、表格）",
                                          type=["pdf", "doc", "docx", "xls", "xlsx", "csv", "png", "jpg", "jpeg", "zip", "rar", "7z"],
                                          accept_multiple_files=True,
                                          help="可多选上传变更通知、图纸、压缩包，以及 xls/xlsx/csv 格式表格。")

        submitted = st.form_submit_button("提交变更登记", type="primary", width="stretch")

    if submitted:
        if not bu or not brand or not change_reason or not notify_person:
            st.error("BU、品牌、变更内容和品质负责人不能为空！")
        else:
            # ── 1) 先写 DB 记录（附件留空），拿到新 id ──
            # 关键修复：保证「无 DB 记录就绝不会产生 NAS 孤儿文件」这一不变量。
            # 旧流程先上传附件再写 DB，DB 写入失败时会出现「文件在 NAS、记录在 DB 缺失」。
            ok, msg, new_id = add_change({
                'bu': bu, 'brand': brand, 'sku': sku,
                'change_reason': change_reason,
                'supplier': supplier,
                'rd_team': rd_team,
                'attachments': '',   # 先留空，上传成功后再回写
                'change_date': str(change_date),
                'notify_person': notify_person,
                'confirm_date': '',
                'confirm_person': '',
                'overall_status': '待确认',
            })
            if not ok:
                st.error(msg)
            else:
                # ── 2) DB 已落库，再上传附件（失败也不丢记录，仅提示）──
                filenames = []
                storage_label = "本地"
                upload_count = 0
                upload_failed = False
                if uploaded_files:
                    for uploaded_file in uploaded_files:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        fname = f"{timestamp}_{uploaded_file.name}"
                        file_content = uploaded_file.getbuffer()
                        year = str(change_date.year)
                        nas_folder = f"/QA/变更管理/{year}年"

                        saved_path = ""
                        # 优先上传到 NAS，失败则回退本地
                        if NAS_AVAILABLE:
                            try:
                                nas_mkdir("/QA/变更管理", f"{year}年")
                                up_ok, nas_path = nas_upload(nas_folder, fname, file_content)
                                if up_ok:
                                    saved_path = nas_path
                                    storage_label = "NAS"
                            except Exception:
                                pass

                        # NAS 不可用或上传失败 → 本地回退
                        if not saved_path:
                            upload_dir = os.path.join(os.path.dirname(os.path.dirname(
                                os.path.abspath(__file__))), "data", "changes")
                            os.makedirs(upload_dir, exist_ok=True)
                            saved_path = os.path.join(upload_dir, fname)
                            with open(saved_path, "wb") as f:
                                f.write(file_content)

                        filenames.append(fname)
                        upload_count += 1

                    # ── 3) 回写附件列表到刚创建的记录（单字段更新，不触碰其他列）──
                    upd_ok, _upd_msg = update_change_attachments(
                        new_id, ";".join(filenames))
                    if not upd_ok:
                        upload_failed = True

                # ── 4) 成功提示 + 钉钉通知（记录已在，附件是否完整都可见）──
                if upload_count > 1:
                    st.success(f"变更记录已保存（已上传 {upload_count} 个文件 | 存储：{storage_label}）！变更信息已推送至 {notify_person}。")
                elif upload_count == 1:
                    st.success(f"变更记录已保存（存储：{storage_label}）！变更信息已推送至 {notify_person}。")
                else:
                    st.success(f"{msg}！变更信息已推送至 {notify_person}。")
                if upload_failed:
                    st.warning("附件回写失败，记录已保存但附件可能不完整，请稍后在「编辑」中补充。")
                log_activity(notify_person, "提交变更登记", "data_edit", f"BU:{bu} 品牌:{brand}", "变更管理")
                # 钉钉通知（机器人推送 + 标注提交人身份）
                submitter_name = st.session_state.get('user_name', '')
                push_ok, push_msg = notify_change_submitted(
                    bu, brand, sku, change_reason, notify_person,
                    submitter=submitter_name
                )
                if push_ok:
                    st.info(f" 钉钉推送：{push_msg}")
                else:
                    st.warning(f"钉钉推送异常：{push_msg}")
                st.rerun()

# ==================== Tab 2: 变更记录 ====================
with tab2:
    st.subheader("变更记录")

    if 'ch_page' not in st.session_state:
        st.session_state.ch_page = 1
    if 'ch_edit_id' not in st.session_state:
        st.session_state.ch_edit_id = None

    # 三列搜索
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        search_sku = st.text_input("SKU搜索", placeholder="输入SKU关键词", key='ch_sku')
    with col_s2:
        search_content = st.text_input("变更内容搜索", placeholder="变更原因关键词", key='ch_content')
    with col_s3:
        search_supplier = st.text_input("供应商搜索", placeholder="供应商关键词", key='ch_supplier')

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
    if st.session_state.ch_page > total_pages:
        st.session_state.ch_page = total_pages

    col_pg1, col_pg2 = st.columns([5, 1])
    with col_pg2:
        pg = st.selectbox("页码", range(1, total_pages + 1),
                          index=st.session_state.ch_page - 1,
                          key='ch_page_sel', label_visibility="collapsed")
        if pg != st.session_state.ch_page:
            st.session_state.ch_page = pg
            st.rerun()

    st.markdown(f"共 **{total}** 条变更记录 (第 {st.session_state.ch_page}/{total_pages} 页)")

    # 导入导出
    ch_template = pd.DataFrame(columns=[
        'bu', 'brand', 'sku', 'supplier', 'change_reason',
        'change_date', 'notify_person', 'confirm_person', 'confirm_date'
    ])
    render_import_export_buttons(
        None,
        'change_records',
        ch_template,
        key_prefix='ch_',
        import_handler=import_changes_dataframe,
        import_help_text="模板导入会按 BU + 品牌 + SKU + 变更原因 + 变更日期 覆盖更新，避免重复追加。",
    )

    if changes:
        filtered_changes, _ = get_changes(
            search_sku=search_sku,
            search_content=search_content,
            search_supplier=search_supplier,
            bu=filter_bu if filter_bu != "全部" else "",
            brand=filter_brand if filter_brand != "全部" else "",
            page=1,
            per_page=max(total, 1)
        )

        df = pd.DataFrame(changes)
        cols = ['id', 'bu', 'brand', 'sku', 'supplier', 'change_reason', 'change_date',
                'overall_status', 'notify_person', 'confirm_date', 'confirm_person']
        df_d = df[[c for c in cols if c in df.columns]].copy()
        rename = {'id': 'ID', 'bu': 'BU', 'brand': '品牌', 'sku': 'SKU', 'supplier': '供应商',
                  'change_reason': '变更原因及内容', 'change_date': '变更日期',
                  'overall_status': '确认状态', 'notify_person': '待确认人',
                  'confirm_date': '确认日期', 'confirm_person': '确认人'}
        df_d.rename(columns={k: v for k, v in rename.items() if k in df_d.columns}, inplace=True)

        if '变更原因及内容' in df_d.columns:
            df_d['变更原因及内容'] = df_d['变更原因及内容'].apply(
                lambda x: x[:80] + '...' if isinstance(x, str) and len(x) > 80 else x)

        # 确认状态颜色映射
        def color_overall_status(val):
            c = {'全部确认': 'background-color: #d4edda; color: #155724',
                 '部分确认': 'background-color: #fff3cd; color: #856404',
                 '待确认': 'background-color: #f8d7da; color: #721c24'}
            return c.get(val, '')
        styled = df_d.style.map(color_overall_status, subset=['确认状态'])

        # ── 每页显示行数选择器 ──
        _row_opts = [10, 20, 50, 100]
        _def_r = st.session_state.get("change_page_size", 20)
        _c_ps1, _c_ps2 = st.columns([1, 4])
        with _c_ps1:
            _ps = st.selectbox("每页行数", options=_row_opts,
                index=_row_opts.index(_def_r) if _def_r in _row_opts else 1,
                key="ch_page_size_sel", label_visibility="collapsed")
        if st.session_state.get("ch_page_size_sel", 20) != st.session_state.get("change_page_size", 20):
            st.session_state["change_page_size"] = st.session_state["ch_page_size_sel"]
            st.rerun()
        _ch_psz = st.session_state.get("change_page_size", 20)
        _ch_disp = min(_ch_psz, len(df_d))
        with _c_ps2:
            st.caption(f"共 **{len(df_d)}** 条 · 显示 **{_ch_disp}** 行")

        # 点击行即可选中 → 自动回显下方编辑表单（动态高度）
        event = ui_table(
            styled, width="stretch", hide_index=True,
            height=min(40 * _ch_disp + 48, 800),
            column_config={'ID': None},
            on_select="rerun",
            selection_mode="single-row",
            key="change_table"
        )

        # 持久化选中行 ID
        if event and event.get("selection", {}).get("rows"):
            selected_row_idx = event["selection"]["rows"][0]
            selected_id = changes[selected_row_idx]['id']
            if selected_id != st.session_state.get("ch_edit_id"):
                st.session_state.ch_edit_id = selected_id
        elif event and not event.get("selection", {}).get("rows"):
            # 用户再次点击同一行取消选中
            pass

        with st.expander(f"批量操作（当前筛选结果 {total} 条）", expanded=False):
            bulk_options = {
                row['id']: f"[{row['id']}] {row.get('brand', '')} | {row.get('sku', '')} | {str(row.get('change_reason', ''))[:40]}"
                for row in filtered_changes
            }
            selected_bulk_changes = st.multiselect(
                "选择要删除的变更记录",
                options=list(bulk_options.keys()),
                format_func=lambda x: bulk_options[x],
                key='bulk_change_delete_ids',
                placeholder="可按当前搜索条件筛选后多选删除",
            )

            bulk_col1, bulk_col2 = st.columns(2)
            with bulk_col1:
                if st.button(
                    f"删除选中 {len(selected_bulk_changes)} 条",
                    type="primary",
                    width="stretch",
                    disabled=not selected_bulk_changes,
                    key="bulk_change_delete_btn"
                ):
                    ok, msg = bulk_delete_changes(selected_bulk_changes)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            with bulk_col2:
                if st.button("清理系统中的重复记录", width="stretch", key="cleanup_duplicate_changes_btn"):
                    ok, msg = cleanup_duplicate_changes()
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        # 删除按钮
        ch_options = {r['id']: f"[{r['id']}] {r.get('sku','')} - {r.get('brand','')} ({str(r.get('change_reason',''))[:30]})" for r in changes}
        col_d1, col_d2 = st.columns([4, 1])
        with col_d1:
            selected_ch = st.selectbox("或下拉选择", list(ch_options.keys()),
                                       format_func=lambda x: ch_options[x],
                                       key='sel_ch', label_visibility="collapsed")
        with col_d2:
            if st.button("删除", width="stretch"):
                ok, msg = delete_change(selected_ch)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
    else:
        ui_empty_state("暂无变更记录", "该分类下还没有变更记录")

    # 编辑区域
    if st.session_state.ch_edit_id:
        st.markdown("---")
        st.subheader(f"编辑变更记录 #{st.session_state.ch_edit_id}")
        edit_data = next((r for r in changes if r['id'] == st.session_state.ch_edit_id), {})

        # ── 基础信息编辑 ──
        with st.form("change_edit_base"):
            c1, c2 = st.columns(2)
            with c1:
                e_bu = st.selectbox("BU *", bu_list,
                    index=bu_list.index(edit_data.get('bu','')) if edit_data.get('bu') in bu_list else 0)
                e_brand = st.selectbox("品牌 *", brand_list,
                    index=brand_list.index(edit_data.get('brand','')) if edit_data.get('brand') in brand_list else 0)
            with c2:
                e_sku = st.text_input("SKU", value=edit_data.get('sku', ''))
                e_supplier = st.text_input("供应商", value=edit_data.get('supplier', ''))
            e_reason = st.text_area("变更原因及内容 *", value=edit_data.get('change_reason', ''))
            e_notify_person = st.text_input("待确认人 / 推送对象", value=edit_data.get('notify_person', ''),
                                            help="这里只是接收通知、后续要去验货确认的人，不代表已经确认。")

            c3, c4 = st.columns(2)
            with c3:
                base_saved = st.form_submit_button("保存基础信息", width="stretch")
            with c4:
                base_cancel = st.form_submit_button("取消编辑", width="stretch")

        if base_saved:
            ok, msg = update_change(st.session_state.ch_edit_id, {
                'bu': e_bu, 'brand': e_brand, 'sku': e_sku, 'supplier': e_supplier,
                'change_reason': e_reason, 'change_date': edit_data.get('change_date', ''),
                'notify_person': e_notify_person,
                'confirm_person': edit_data.get('confirm_person', ''),
                'confirm_date': edit_data.get('confirm_date', ''),
                'rd_team': edit_data.get('rd_team', ''),
                'sku_confirm_status': edit_data.get('sku_confirm_status', '{}'),
                'overall_status': edit_data.get('overall_status', '待确认'),
            })
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        if base_cancel:
            st.session_state.ch_edit_id = None
            st.rerun()

        # ── SKU 逐项确认区域 ──
        sku_str = edit_data.get('sku', '')
        sku_list = parse_sku_list(sku_str)

        # 解析供应商列表
        import re as re_module
        supplier_str = edit_data.get('supplier', '')
        suppliers = []
        if supplier_str and supplier_str.strip():
            # 按常见分隔符拆分供应商
            parts = re_module.split(r'[,，;；/、\n\r\t]+', supplier_str.strip())
            suppliers = [p.strip() for p in parts if p.strip()]

        if not sku_list:
            st.info("该记录未填写 SKU 或 SKU 格式无法解析，暂不支持逐项确认。请在基础信息中填写 SKU（多个以逗号/顿号分隔）。")
        else:
            st.markdown("---")
            st.subheader("SKU 逐项确认")

            # 读取已有确认状态 JSON
            try:
                confirm_dict = json.loads(edit_data.get('sku_confirm_status', '{}'))
            except (json.JSONDecodeError, TypeError):
                confirm_dict = {}

            current_user = st.session_state.get('user_name', '')
            today_str = date.today().isoformat()

            # ── 判断是否为旧格式（向后兼容）──
            is_legacy_format = False
            if confirm_dict:
                first_val = next(iter(confirm_dict.values()), None)
                if isinstance(first_val, dict) and 'status' in first_val and not any(
                    isinstance(v, dict) and 'status' in v for v in (first_val.values() if isinstance(first_val, dict) else [])
                ):
                    is_legacy_format = True

            # ── 构建 SKU × 供应商 确认表 ──
            df_rows = []
            for sku in sku_list:
                sku_info = confirm_dict.get(sku, {})

                if is_legacy_format:
                    # 旧格式：{"SKU": {"status": bool, "confirmer": "name", "date": "date"}}
                    # 迁移时自动分配到第一个供应商，或标记为「通用」
                    checked = sku_info.get('status', False) if isinstance(sku_info, dict) else False
                    if suppliers:
                        for sup in suppliers:
                            # 旧格式：对第一个供应商设为已确认，其余待确认
                            s_checked = checked if sup == suppliers[0] else False
                            df_rows.append({
                                'SKU': sku,
                                '供应商': sup,
                                '是否已变更': bool(s_checked),
                                '确认人': sku_info.get('confirmer', '') if s_checked and isinstance(sku_info, dict) else '',
                                '确认日期': sku_info.get('date', '') if s_checked and isinstance(sku_info, dict) else '',
                            })
                    else:
                        df_rows.append({
                            'SKU': sku,
                            '供应商': '通用',
                            '是否已变更': bool(checked),
                            '确认人': sku_info.get('confirmer', '') if checked and isinstance(sku_info, dict) else '',
                            '确认日期': sku_info.get('date', '') if checked and isinstance(sku_info, dict) else '',
                        })
                else:
                    # 新格式：{"SKU": {"供应商A": {"status": bool, ...}, "供应商B": {...}}}
                    if suppliers:
                        for sup in suppliers:
                            sup_info = sku_info.get(sup, {}) if isinstance(sku_info, dict) else {}
                            sup_checked = sup_info.get('status', False) if isinstance(sup_info, dict) else False
                            df_rows.append({
                                'SKU': sku,
                                '供应商': sup,
                                '是否已变更': bool(sup_checked),
                                '确认人': sup_info.get('confirmer', '') if isinstance(sup_info, dict) and sup_checked else '',
                                '确认日期': sup_info.get('date', '') if isinstance(sup_info, dict) and sup_checked else '',
                            })
                    else:
                        # 无供应商信息：单行确认
                        sup_checked = sku_info.get('status', False) if isinstance(sku_info, dict) and 'status' in sku_info and not isinstance(sku_info.get('status', None), dict) else False
                        df_rows.append({
                            'SKU': sku,
                            '供应商': '通用',
                            '是否已变更': bool(sup_checked),
                            '确认人': sku_info.get('confirmer', '') if isinstance(sku_info, dict) and sup_checked else '',
                            '确认日期': sku_info.get('date', '') if isinstance(sku_info, dict) and sup_checked else '',
                        })

            df_confirm = pd.DataFrame(df_rows)

            has_supplier_col = suppliers and len(suppliers) > 0
            total_items = len(df_rows)
            if has_supplier_col:
                st.caption(f"共 **{len(sku_list)}** 个 SKU，**{len(suppliers)}** 家供应商（共 {total_items} 项确认），勾选即确认该 SKU-供应商已完成变更切换")
            else:
                st.caption(f"共 **{len(sku_list)}** 个 SKU，勾选即确认该 SKU 已完成变更切换")

            # st.data_editor — 用户交互
            if has_supplier_col:
                col_config = {
                    'SKU': st.column_config.TextColumn('SKU', disabled=True, width='medium'),
                    '供应商': st.column_config.TextColumn('供应商', disabled=True, width='medium'),
                    '是否已变更': st.column_config.CheckboxColumn('是否已变更', width='small'),
                    '确认人': st.column_config.TextColumn('确认人', disabled=True, width='small'),
                    '确认日期': st.column_config.TextColumn('确认日期', disabled=True, width='small'),
                }
            else:
                col_config = {
                    'SKU': st.column_config.TextColumn('SKU', disabled=True, width='medium'),
                    '供应商': st.column_config.TextColumn('供应商', disabled=True, width='small'),
                    '是否已变更': st.column_config.CheckboxColumn('是否已变更', width='small'),
                    '确认人': st.column_config.TextColumn('确认人', disabled=True, width='small'),
                    '确认日期': st.column_config.TextColumn('确认日期', disabled=True, width='small'),
                }

            edited_df = ui_data_editor(
                df_confirm,
                width="stretch",
                hide_index=True,
                num_rows="fixed",
                column_config=col_config,
                key=f"sku_confirm_{st.session_state.ch_edit_id}"
            )

            # auto-fill: 勾选 → 自动填入当前用户 + 当天日期；取消勾选 → 清空
            data_changed = False
            for i in range(len(edited_df)):
                if edited_df.at[i, '是否已变更'] and not edited_df.at[i, '确认人']:
                    edited_df.at[i, '确认人'] = current_user
                    edited_df.at[i, '确认日期'] = today_str
                    data_changed = True
                elif not edited_df.at[i, '是否已变更'] and edited_df.at[i, '确认人']:
                    edited_df.at[i, '确认人'] = ''
                    edited_df.at[i, '确认日期'] = ''
                    data_changed = True

            if data_changed:
                st.info(f"确认人已自动填入：**{current_user}** | 确认日期：**{today_str}**")
                ui_data_editor(
                    edited_df,
                    width="stretch",
                    hide_index=True,
                    num_rows="fixed",
                    column_config=col_config,
                    key=f"sku_confirm_filled_{st.session_state.ch_edit_id}"
                )

            # 计算当前确认进度
            total_items = len(edited_df)
            confirmed_count = edited_df['是否已变更'].sum()
            if confirmed_count == total_items:
                progress_label = '全部确认'
                progress_color = 'green'
            elif confirmed_count > 0:
                progress_label = '部分确认'
                progress_color = 'orange'
            else:
                progress_label = '待确认'
                progress_color = 'gray'

            st.markdown(
                f"**确认进度**: {confirmed_count}/{total_items} 项 —"
                f":{progress_color}[{progress_label}]"
            )

            # 保存确认状态按钮
            col_s1, col_s2 = st.columns([1, 3])
            with col_s1:
                if st.button("保存确认状态", type="primary", width="stretch",
                             key=f"save_confirm_{st.session_state.ch_edit_id}"):
                    # 构建 new confirm JSON
                    new_confirm = {}
                    all_confirmed = True
                    any_confirmed = False
                    for _, row in edited_df.iterrows():
                        sku = row['SKU']
                        sup = row['供应商']
                        status = bool(row['是否已变更'])

                        if sku not in new_confirm:
                            new_confirm[sku] = {}

                        new_confirm[sku][sup] = {
                            'status': status,
                            'confirmer': row['确认人'] if status else '',
                            'date': row['确认日期'] if status else '',
                        }
                        if status:
                            any_confirmed = True
                        else:
                            all_confirmed = False

                    if all_confirmed and any_confirmed:
                        overall = '全部确认'
                    elif any_confirmed:
                        overall = '部分确认'
                    else:
                        overall = '待确认'

                    # 同步更新 confirm_person/confirm_date（取最新确认的项）
                    latest_confirmer = ''
                    latest_date = ''
                    for _, row in edited_df.iterrows():
                        if row['是否已变更'] and row['确认人']:
                            latest_confirmer = row['确认人']
                            latest_date = row['确认日期']

                    update_data = {
                        'bu': edit_data.get('bu', ''),
                        'brand': edit_data.get('brand', ''),
                        'sku': edit_data.get('sku', ''),
                        'supplier': edit_data.get('supplier', ''),
                        'change_reason': edit_data.get('change_reason', ''),
                        'attachments': edit_data.get('attachments', ''),
                        'change_date': edit_data.get('change_date', ''),
                        'notify_person': edit_data.get('notify_person', ''),
                        'confirm_person': latest_confirmer,
                        'confirm_date': latest_date,
                        'rd_team': edit_data.get('rd_team', ''),
                        'sku_confirm_status': json.dumps(new_confirm, ensure_ascii=False),
                        'overall_status': overall,
                    }

                    ok, msg = update_change(st.session_state.ch_edit_id, update_data)
                    if ok:
                        st.success(f"SKU 确认状态已保存！当前状态：{overall}（{confirmed_count}/{total_items}）")
                        log_activity(current_user, "更新SKU确认状态", "data_edit",
                                    f"变更#{st.session_state.ch_edit_id} → {overall} ({confirmed_count}/{total_items})", "变更管理")
                        st.rerun()
                    else:
                        st.error(msg)
