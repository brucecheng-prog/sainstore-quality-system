"""
实验室设备管理系统 - 维护记录页面
"""

import streamlit as st
import pandas as pd
from datetime import date
from pages._utils import render_sidebar, render_topbar, render_import_export_buttons, ui_empty_state, ui_table, ui_data_editor
from database import (
    init_db, get_maintenance_records, add_maintenance, update_maintenance,
    delete_maintenance, get_upcoming_maintenance, get_equipment_for_select,
    get_all_equipment
)

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# Session State
for key, default in [('mt_edit_id', None), ('mt_page', 1)]:
    if key not in st.session_state:
        st.session_state[key] = default

# 渲染侧边栏导航
st.session_state.current_page = "维护记录"
with st.sidebar:
    render_sidebar()
render_topbar("维护记录")



st.title("维护记录管理")

tab1, tab2, tab3 = st.tabs(["维护记录", "保养计划", "导入校验数据"])

# ==================== Tab 1: 维护记录 ====================
with tab1:
    # 添加/编辑表单
    mt_editing = st.session_state.mt_edit_id is not None

    with st.expander("编辑维护记录" if mt_editing else "添加维护记录", expanded=mt_editing):
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
                submitted = st.form_submit_button("保存", width="stretch", type="primary")

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
                if st.button("取消编辑", width="stretch", key="cancel_mt_edit"):
                    st.session_state.mt_edit_id = None
                    st.rerun()

    # 维护记录列表
    records, total = get_maintenance_records(page=1, per_page=5000)  # 加载全部供编辑
    st.caption(f"共 **{total}** 条维护记录")

    if records:
        df = pd.DataFrame(records)
        df_display = df[[
            'id', 'equipment_name', 'serial_number', 'maintenance_date',
            'maintenance_type', 'description', 'cost', 'technician',
            'next_maintenance_date', 'status'
        ]].copy()
        df_display.columns = [
            'id', '设备名称', '编号', '维护日期', '类型', '描述',
            '费用(¥)', '技术人员', '下次维护', '状态'
        ]

        # 类型转换：日期列 → datetime64，费用 → float64（兼容 DateColumn / NumberColumn）
        df_display['维护日期'] = pd.to_datetime(df_display['维护日期'], errors='coerce')
        df_display['下次维护'] = pd.to_datetime(df_display['下次维护'], errors='coerce')
        df_display['费用(¥)'] = pd.to_numeric(df_display['费用(¥)'], errors='coerce').fillna(0.0).astype(float)

        # 列配置：id/设备名/编号只读，其余可编辑
        col_cfg = {
            'id': st.column_config.NumberColumn(label='ID', disabled=True),
            '设备名称': st.column_config.TextColumn(label='设备名称', disabled=True),
            '编号': st.column_config.TextColumn(label='编号', disabled=True),
            '维护日期': st.column_config.DateColumn(label='维护日期'),
            '类型': st.column_config.SelectboxColumn(
                label='类型',
                options=['定期保养', '故障维修', '校准', '其他'],
            ),
            '费用(¥)': st.column_config.NumberColumn(label='费用(¥)', format='¥%.2f'),
            '技术人员': st.column_config.TextColumn(label='技术人员'),
            '下次维护': st.column_config.DateColumn(label='下次维护'),
            '描述': st.column_config.TextColumn(label='描述'),
            '状态': st.column_config.SelectboxColumn(
                label='状态',
                options=['已完成', '进行中', '计划中'],
            ),
        }

        editor_key = 'mt_editor'
        edited = ui_data_editor(
            df_display,
            key=editor_key,
            width="stretch",
            num_rows="dynamic",
            column_config=col_cfg,
            hide_index=True,
            height=min(len(df_display) * 38 + 38, 600),
            disabled=['id', '设备名称', '编号'],
        )

        # 按钮行
        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            if st.button("保存修改", key='mt_save', width="stretch", type="primary"):
                from database import get_connection as _gc
                session_data = st.session_state.get(editor_key, {})
                e_rows = session_data.get("edited_rows", {})
                d_rows = session_data.get("deleted_rows", [])
                a_rows = session_data.get("added_rows", [])

                conn = _gc()
                changes = False

                # Helper: 将 datetime 对象转为 YYYY-MM-DD 字符串
                def _format_date(v):
                    if hasattr(v, 'strftime'):
                        return v.strftime('%Y-%m-%d') if v is not None else ''
                    return v

                # 日期列名集合
                _date_cols = {'maintenance_date', 'next_maintenance_date'}

                try:
                    for row_idx_str, edits in e_rows.items():
                        row_idx = int(row_idx_str)
                        if row_idx >= len(df_display): continue
                        pk = int(df_display.iloc[row_idx]['id'])
                        col_map = {'维护日期': 'maintenance_date', '类型': 'maintenance_type',
                                   '描述': 'description', '费用(¥)': 'cost',
                                   '技术人员': 'technician', '下次维护': 'next_maintenance_date'}
                        db_edits = {}
                        for k, v in edits.items():
                            if k in ('id', '设备名称', '编号', '状态'):
                                continue
                            db_col = col_map.get(k, k)
                            db_edits[db_col] = _format_date(v) if db_col in _date_cols else v
                        if db_edits:
                            set_clause = ",".join([f'"{c}" = ?' for c in db_edits])
                            conn.execute(f'UPDATE maintenance_records SET {set_clause} WHERE id = ?',
                                         list(db_edits.values()) + [pk])
                    if e_rows:
                        changes = True
                        st.toast(f"已更新 {len(e_rows)} 处修改")
                    for added in a_rows:
                        if not any(v and str(v).strip() for v in added.values()):
                            continue
                        # 映射显示名 → DB 列名
                        col_map_add = {'维护日期': 'maintenance_date', '类型': 'maintenance_type',
                                       '描述': 'description', '费用(¥)': 'cost',
                                       '技术人员': 'technician', '下次维护': 'next_maintenance_date'}
                        db_add = {}
                        for k, v in added.items():
                            if k != 'id':
                                db_col = col_map_add.get(k, k)
                                db_add[db_col] = _format_date(v) if db_col in _date_cols else v
                        if db_add:
                            cols = list(db_add.keys())
                            vals = list(db_add.values())
                            conn.execute(
                                f'INSERT INTO maintenance_records ({", ".join(cols)}) VALUES ({", ".join(["?"]*len(cols))})',
                                vals
                            )
                    if a_rows: changes = True
                    for row_idx in sorted(d_rows, reverse=True):
                        if row_idx < len(df_display):
                            pk = int(df_display.iloc[row_idx]['id'])
                            conn.execute('DELETE FROM maintenance_records WHERE id = ?', (pk,))
                    if d_rows:
                        changes = True
                        st.toast(f"已删除 {len(d_rows)} 条")
                    conn.commit()
                except Exception as e:
                    st.error(f"操作失败: {e}")
                    conn.rollback()
                finally:
                    conn.close()
                if changes: st.rerun()
        with b2:
            if st.button("刷新", key='mt_refresh', width="stretch"):
                st.rerun()
        with b3:
            st.caption("双击编辑 | 勾选行 + Delete 删除 | 底部空行新增")

        # 导入导出
        mt_template = pd.DataFrame(columns=[
            'equipment_name', 'serial_number', 'maintenance_date',
            'maintenance_type', 'description', 'cost', 'technician',
            'next_maintenance_date', 'status'
        ])
        render_import_export_buttons(None, 'maintenance_records', mt_template, key_prefix='mt_')
    else:
        ui_empty_state("暂无维护记录", hint="完成设备保养或导入校验清单后，相关记录会显示在这里。")

# ==================== Tab 2: 保养计划 ====================
with tab2:
    st.subheader("保养计划")

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

        ui_table(df_display, width="stretch", hide_index=True, height=400)

        # 导出保养计划
        from io import BytesIO
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_display.to_excel(writer, index=False, sheet_name='保养计划')
        st.download_button(
            "导出保养计划",
            buffer.getvalue(),
            f"保养计划_{date.today()}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
    else:
        st.success(f"未来 {days} 天内无保养计划，设备状态良好！")

# ==================== Tab 3: 导入校验数据 ====================
with tab3:
    st.subheader("导入设备校验清单")
    st.caption("上传设备校验清单Excel文件，自动解析校验日期并导入维护记录。支持 .xlsx / .xls 格式。")

    # 模板说明
    with st.expander("Excel模板格式说明", expanded=False):
        st.markdown("""
        **Excel 表头列名要求（以下任一组均支持）：**
        - `设备编号` / `设备名称` — 用于匹配系统中的设备
        - `校验日期` — 校验执行的日期（必填）
        - `校验类型` — 如「校准」「定期保养」等（可选，默认「校准」）
        - `下次校验日期` — 下次校验计划日期（可选）
        - `校验结果` / `状态` — 如「已完成」「计划中」（可选，默认「已完成」）
        - `技术人员` — 执行校验的技术人员（可选）
        - `费用` — 校验费用（可选）
        - `备注` — 其他备注信息（可选）

    > 设备编号/名称为空时，该行将被跳过。
        """)

    uploaded_cal = st.file_uploader("选择设备校验清单Excel文件", type=['xlsx', 'xls'], key="cal_import")

    if uploaded_cal:
        import io
        from datetime import datetime as dt_module

        # 预览上传的数据
        try:
            raw_df = pd.read_excel(uploaded_cal)
            st.markdown(f"识别到 **{len(raw_df)}** 行数据，列名: {list(raw_df.columns)}")
            ui_table(raw_df.head(10), width="stretch", hide_index=True)
        except Exception as e:
            st.error(f"无法读取Excel文件: {e}")
            raw_df = None

        if raw_df is not None:
            col_preview, col_import = st.columns([3, 1])
            with col_import:
                if st.button("开始导入", type="primary", width="stretch", key="cal_import_btn"):
                    # 列名映射（大小写不敏感、去空格）
                    cols_normalized = {str(c).strip().lower(): str(c) for c in raw_df.columns}

                    def find_col(*aliases):
                        for a in aliases:
                            key = a.strip().lower()
                            if key in cols_normalized:
                                return cols_normalized[key]
                        return None

                    eq_col = find_col('设备编号', '设备名称', '设备', 'equipment', '编号', 'serial')
                    date_col = find_col('校验日期', '校验时间', '日期', 'date', 'calibration_date')
                    type_col = find_col('校验类型', '类型', 'type', 'maintenance_type')
                    next_col = find_col('下次校验日期', '下次校验', '下次维护日期', 'next_date')
                    status_col = find_col('校验结果', '结果', '状态', 'status', 'result')
                    tech_col = find_col('技术人员', '技术员', 'technician', '校验人员')
                    cost_col = find_col('费用', 'cost', 'price', '金额')
                    notes_col = find_col('备注', 'notes', '描述', '说明', 'memo')

                    if not date_col:
                        st.error("未找到「校验日期」列，请检查表头！")
                    else:
                        # 获取设备列表用于匹配
                        eq_options = get_equipment_for_select()
                        eq_name_map = {}  # serial_number or name -> id
                        for e in eq_options:
                            sn = str(e.get('serial_number', '')).strip()
                            nm = str(e.get('name', '')).strip()
                            if sn:
                                eq_name_map[sn.lower()] = e['id']
                            if nm:
                                eq_name_map[nm.lower()] = e['id']

                        success_count = 0
                        skip_count = 0
                        error_list = []

                        with st.status(f"正在导入数据...", expanded=True) as status_ctx:
                            for idx, row in raw_df.iterrows():
                                # 匹配设备
                                eq_id = None
                                eq_display = ''
                                if eq_col:
                                    eq_val = str(row.get(eq_col, '')).strip()
                                    eq_display = eq_val
                                    if eq_val.lower() in eq_name_map:
                                        eq_id = eq_name_map[eq_val.lower()]
                                    else:
                                        # 模糊匹配：尝试部分匹配
                                        for key, eid in eq_name_map.items():
                                            if eq_val.lower() in key or key in eq_val.lower():
                                                eq_id = eid
                                                break

                                if not eq_id:
                                    skip_count += 1
                                    st.write(f"行{idx+2}: 未匹配到设备「{eq_display}」— 已跳过")
                                    continue

                                # 日期处理
                                date_val = row.get(date_col)
                                if pd.isna(date_val) or str(date_val).strip() == '':
                                    skip_count += 1
                                    st.write(f"行{idx+2}: 校验日期为空 — 已跳过")
                                    continue

                                try:
                                    parsed_date = pd.to_datetime(date_val)
                                    mt_date = parsed_date.strftime('%Y-%m-%d')
                                except:
                                    skip_count += 1
                                    st.write(f"行{idx+2}: 无法解析日期「{date_val}」— 已跳过")
                                    continue

                                # 类型
                                mt_type = '校准'
                                if type_col:
                                    type_val = str(row.get(type_col, '')).strip()
                                    if type_val and type_val != 'nan':
                                        valid_types = ['定期保养', '故障维修', '校准', '其他']
                                        if type_val in valid_types:
                                            mt_type = type_val
                                        else:
                                            mt_type = '其他'

                                # 下次校验日期
                                next_date = ''
                                if next_col:
                                    next_val = row.get(next_col)
                                    if not pd.isna(next_val) and str(next_val).strip() != '':
                                        try:
                                            next_date = pd.to_datetime(next_val).strftime('%Y-%m-%d')
                                        except:
                                            pass

                                # 状态
                                mt_status = '已完成'
                                if status_col:
                                    status_val = str(row.get(status_col, '')).strip()
                                    if status_val in ['已完成', '进行中', '计划中']:
                                        mt_status = status_val
                                    elif '进行' in status_val:
                                        mt_status = '进行中'
                                    elif '计划' in status_val:
                                        mt_status = '计划中'

                                # 技术人员
                                technician = ''
                                if tech_col:
                                    tech_val = str(row.get(tech_col, '')).strip()
                                    if tech_val and tech_val != 'nan':
                                        technician = tech_val

                                # 费用
                                cost = 0.0
                                if cost_col:
                                    try:
                                        cost_val = row.get(cost_col)
                                        if not pd.isna(cost_val):
                                            cost = float(cost_val)
                                    except:
                                        pass

                                # 备注
                                notes = ''
                                if notes_col:
                                    notes_val = str(row.get(notes_col, '')).strip()
                                    if notes_val and notes_val != 'nan':
                                        notes = notes_val

                                # 导入
                                data = {
                                    'equipment_id': eq_id,
                                    'maintenance_date': mt_date,
                                    'maintenance_type': mt_type,
                                    'description': f'批量导入 — {eq_display} 校验',
                                    'cost': cost,
                                    'technician': technician,
                                    'next_maintenance_date': next_date,
                                    'status': mt_status,
                                    'notes': notes,
                                }
                                ok, msg = add_maintenance(data)
                                if ok:
                                    success_count += 1
                                else:
                                    error_list.append(f"行{idx+2}: {msg}")

                            if error_list:
                                for err in error_list:
                                    st.write(f"{err}")

                            st.write(f"---")
                            st.write(f"**导入完成**: 成功 {success_count} 条, 跳过 {skip_count} 条, 失败 {len(error_list)} 条")
                            status_ctx.update(label="导入完成！", state="complete")

                        if success_count > 0:
                            st.toast(f"成功导入 {success_count} 条校验记录！")
                            st.rerun()
                        else:
                            st.info(" 请上传设备校验清单 Excel 文件，支持 .xlsx / .xls 格式")
