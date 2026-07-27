"""
实验室设备管理系统 - 借用归还（设备出库/归还）
"""

import streamlit as st
import pandas as pd
import html as _html
from datetime import date, datetime, timedelta
from pages._utils import creatable_selectbox, render_sidebar, render_topbar, render_import_export_buttons, ui_status_badge, ui_empty_state
from components.modal import confirm_dialog
from database import (
    init_db, get_equipment_for_select, get_users,
    checkout_equipment, return_equipment, get_borrow_records,
    add_user, add_equipment, update_user, delete_user, get_users as get_all_users,
    update_borrow_record, delete_borrow_record,
)

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

for key, default in [
    ('user_edit_id', None), ('borrow_edit_id', None), ('borrow_del_confirm', None),
    ('user_del_confirm', None),
    ('borrow_confirmed_eq_id', None), ('borrow_confirmed_eq_name', ''),
    ('borrow_confirmed_user_id', None), ('borrow_confirmed_user_name', ''),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# F1：复用全站 is_admin 判定（与 main.py / page_reports.py 一致）
is_admin = st.session_state.get("is_admin", False)

# 渲染侧边栏导航
st.session_state.current_page = "借用归还"
with st.sidebar:
    render_sidebar()
render_topbar("借用归还")



st.title("设备借用出库 & 归还")

tab1, tab2, tab3 = st.tabs(["借用出库", "归还入库", "借用记录"])

# ==================== Tab 1: 借用出库 ====================
with tab1:
    st.subheader("设备借用出库")
    st.caption("此功能用于设备物理借出实验室。内部测试预约请使用「使用登记」。")

    equipment_options = get_equipment_for_select()
    available_eq = [e for e in equipment_options if e['status'] == '可用']

    if not available_eq:
        st.warning("当前没有可借出的设备。")

    # ═══════════════════════════════════════════════════════════
    # 设备选择（表单外部 — 即时响应）
    # ═══════════════════════════════════════════════════════════
    st.markdown("##### 选择设备")
    eq_val, is_new_eq = creatable_selectbox(
        "选择设备 *",
        options=[e['id'] for e in available_eq] if available_eq else [],
        key_prefix="co_eq",
        format_func=lambda x: (
            f"[{next((e['serial_number'] for e in available_eq if e['id']==x), '')}]"
            f"{next((e['name'] for e in available_eq if e['id']==x), '')}"
        ) if available_eq else "",
        default_value=st.session_state.borrow_confirmed_eq_id,
    )

    final_eq_id = st.session_state.borrow_confirmed_eq_id
    eq_name = st.session_state.borrow_confirmed_eq_name

    # 手动添加设备 → 确认按钮
    if is_new_eq and eq_val:
        col_addeq_btn, _ = st.columns([1, 2])
        with col_addeq_btn:
            if st.button("确认添加设备", key="borrow_eq_confirm", width="stretch", type="primary"):
                ok_e, msg_e = add_equipment({'name': eq_val})
                if ok_e:
                    refreshed = get_equipment_for_select()
                    matched = [e for e in refreshed if e['name'] == eq_val]
                    if matched:
                        st.session_state.borrow_confirmed_eq_id = matched[0]['id']
                        st.session_state.borrow_confirmed_eq_name = matched[0]['name']
                        st.session_state.pop("co_eq_sb", None)
                        st.session_state.pop("co_eq_inp", None)
                        st.success(f"设备「{eq_val}」添加成功，已自动选中")
                        st.rerun()
                    else:
                        st.error("设备添加后无法获取ID，请刷新重试")
                else:
                    st.error(f"设备添加失败：{msg_e}")

    if not is_new_eq and eq_val is not None:
        selected_eq = next((e for e in available_eq if e['id'] == eq_val), {})
        final_eq_id = eq_val
        eq_name = selected_eq.get('name', '')
        st.session_state.borrow_confirmed_eq_id = final_eq_id
        st.session_state.borrow_confirmed_eq_name = eq_name

    if final_eq_id:
        st.caption(f"当前设备：**{eq_name}** (ID: {final_eq_id})")

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # 借用人选择（表单外部 — 即时响应）
    # ═══════════════════════════════════════════════════════════
    st.markdown("##### 借用人")
    all_users = get_all_users()
    user_val, is_new_user = creatable_selectbox(
        "借用人 *",
        options=[u['id'] for u in all_users],
        key_prefix="co_user",
        format_func=lambda x: (
            f"{next((u['name'] for u in all_users if u['id']==x), '')}"
        ),
        default_value=st.session_state.borrow_confirmed_user_id,
    )

    final_user_id = st.session_state.borrow_confirmed_user_id
    final_user_name = st.session_state.borrow_confirmed_user_name

    # 手动添加人员 → 确认按钮
    if is_new_user and user_val:
        col_adduser_btn, _ = st.columns([1, 2])
        with col_adduser_btn:
            if st.button("确认添加人员", key="borrow_user_confirm", width="stretch", type="primary"):
                ok_u, msg_u = add_user({'name': user_val})
                if ok_u:
                    refreshed = get_all_users()
                    matched = [u for u in refreshed if u['name'] == user_val]
                    if matched:
                        st.session_state.borrow_confirmed_user_id = matched[0]['id']
                        st.session_state.borrow_confirmed_user_name = matched[0]['name']
                        st.session_state.pop("co_user_sb", None)
                        st.session_state.pop("co_user_inp", None)
                        st.success(f"人员「{user_val}」添加成功，已自动选中")
                        st.rerun()
                    else:
                        st.error("人员添加后无法获取ID，请刷新重试")
                else:
                    st.error(f"人员添加失败：{msg_u}")

    if not is_new_user and user_val is not None:
        selected_user = next((u for u in all_users if u['id'] == user_val), {})
        final_user_id = user_val
        final_user_name = selected_user.get('name', '')
        st.session_state.borrow_confirmed_user_id = final_user_id
        st.session_state.borrow_confirmed_user_name = final_user_name

    if final_user_id:
        st.caption(f"当前借用人：**{final_user_name}**")

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # 出库详情表单（仅含日期/用途/备注）
    # ═══════════════════════════════════════════════════════════
    with st.form("checkout_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            co_date = st.date_input("借用日期 *", value=date.today(), key='co_date')
        with col2:
            co_return = st.date_input("预计归还日期 *",
                                      value=date.today() + timedelta(days=7),
                                      key='co_return')

        purpose = st.text_input("借用原因/用途", placeholder="例如：市场部展会展示", key='co_purpose')
        notes = st.text_area("备注", placeholder="其他说明...", key='co_notes')

        submitted = st.form_submit_button("确认出库", type="primary", width="stretch")

        if submitted:
            if not available_eq and not final_eq_id:
                st.error("没有可借出的设备！")
            elif co_return < co_date:
                st.error("预计归还日期不能早于借用日期！")
            elif not final_eq_id:
                st.error("请先选择设备并确认！")
            elif not final_user_id:
                st.error("请先选择借用人并确认！")
            else:
                ok, msg = checkout_equipment(final_eq_id, final_user_id, str(co_date), str(co_return), purpose, notes)
                if ok:
                    # 清除确认状态
                    st.session_state.borrow_confirmed_eq_id = None
                    st.session_state.borrow_confirmed_eq_name = ""
                    st.session_state.borrow_confirmed_user_id = None
                    st.session_state.borrow_confirmed_user_name = ""
                    st.success(f"{msg}")
                    st.rerun()
                else:
                    st.error(msg)

    # 当前借出列表
    st.markdown("---")
    st.subheader("当前已出库设备")
    out_records, _ = get_borrow_records(status='已出库', per_page=50)
    if out_records:
        for r in out_records:
            st.markdown(
                f"""<div style="border:1px solid var(--qs-warning-border); border-left:4px solid var(--qs-warning);
                border-radius:6px; padding:8px 12px; margin:4px 0; background:var(--qs-warning-bg);">
        <b> {r['equipment_name']}</b> <code>{r['serial_number']}</code> —
         {r['user_name']} | {r['borrow_date']} → {r['expected_return_date']}<br>
                <small>用途: {r['purpose'] or '无'}</small>
                </div>""", unsafe_allow_html=True)
    else:
        ui_empty_state("无已出库设备", hint="设备借出出库后，这里会显示对应的出库记录。")

# ==================== Tab 2: 归还入库 ====================
with tab2:
    st.subheader("归还入库")

    out_records, _ = get_borrow_records(status='已出库', per_page=50)
    all_borrowing, _ = get_borrow_records(status='借出中', per_page=50)

    to_return = out_records + all_borrowing

    if to_return:
        today_str = str(date.today())
        overdue_ids = [r['id'] for r in to_return
                       if r.get('expected_return_date') and r['expected_return_date'] < today_str]
        if overdue_ids:
            st.warning(f"{len(overdue_ids)} 条记录已逾期，请及时归还！")

        for r in to_return:
            with st.container():
                is_overdue = r.get('expected_return_date') and r['expected_return_date'] < today_str
                border = "var(--qs-danger)" if is_overdue else "var(--qs-success)"
                tag = "逾期" if is_overdue else ""
                is_usage_rt = r.get('record_type') == 'usage'
                type_tag = "实验室使用" if is_usage_rt else "外借出库"
                type_border = "var(--qs-primary)" if is_usage_rt else "var(--qs-warning)"

                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(
                        f"""<div style="border:1px solid {border}; border-left:4px solid {type_border}; border-radius:8px; padding:10px; margin:4px 0;">
                        <b>{r['equipment_name']}</b> <code>{r['serial_number']}</code>{tag} <small>{type_tag}</small><br>
            <small> {r['user_name']} | {r['borrow_date']} → {r['expected_return_date'] or '未设'}<br>
             {r.get('product_name') or r['purpose'] or '无'}</small>
                        </div>""", unsafe_allow_html=True)
                with c2:
                    rd = st.date_input("归还日期", value=date.today(),
                                       key=f"rd_{r['id']}", label_visibility="collapsed")
                    if st.button("确认归还", key=f"ret_{r['id']}", width="stretch"):
                        ok, msg = return_equipment(r['id'], str(rd))
                        st.success(msg) if ok else st.error(msg)
                        if ok: st.rerun()
    else:
        st.success("无需要归还的设备。")

# ==================== Tab 3: 借用记录 ====================
with tab3:
    st.subheader("借用记录")

    col_f1, col_f2, _ = st.columns([1, 1, 2])
    with col_f1:
        rec_status = st.selectbox("状态筛选", ["全部", "借出中/使用中", "已出库", "已归还", "逾期"],
                                  key='hist_status')
    with col_f2:
        rec_type = st.selectbox("类型筛选", ["全部", "实验室内使用", "外借出库"],
                                key='hist_type')

    st_filter = rec_status if rec_status != "全部" else None
    records, total = get_borrow_records(status=st_filter, per_page=200)

    # 类型筛选（客户端过滤）
    if rec_type == "实验室内使用":
        records = [r for r in records if r.get('record_type') == 'usage']
        total = len(records)
    elif rec_type == "外借出库":
        records = [r for r in records if r.get('record_type') == 'borrow']
        total = len(records)

    st.markdown(f"共 **{total}** 条记录")

    # 导入导出
    br_template = pd.DataFrame(columns=[
        'equipment_id', 'user_id',
        'borrow_date', 'expected_return_date', 'actual_return_date',
        'purpose', 'notes', 'status', 'record_type'
    ])
    render_import_export_buttons(None, 'borrow_records', br_template, key_prefix='br_')

    if records:
        # 编辑弹窗逻辑
        edit_rec = None
        if st.session_state.borrow_edit_id is not None:
            for r in records:
                if r['id'] == st.session_state.borrow_edit_id:
                    edit_rec = r
                    break

        if edit_rec:
            st.markdown("---")
            st.markdown(f"### 编辑记录 #{edit_rec['id']}")

            # ═══════════════════════════════════════════════════════
            # 使用人选择（表单外部 — 即时响应）
            # ═══════════════════════════════════════════════════════
            st.markdown("##### 使用/借用人")
            all_users_edit = get_all_users()
            edit_user_val, is_new_edit_user = creatable_selectbox(
                "使用/借用人",
                options=[u['id'] for u in all_users_edit],
                key_prefix="eb_user",
                format_func=lambda x: (
                    f"{next((u['name'] for u in all_users_edit if u['id']==x), '')}"
                ),
                default_value=edit_rec['user_id'],
            )

            # 确定最终 user_id
            if edit_user_val is not None:
                edit_user_val_for_db = edit_user_val
            else:
                edit_user_val_for_db = edit_rec['user_id']

            # 手动添加人员 → 确认按钮
            if is_new_edit_user and edit_user_val:
                col_edit_user_btn, _ = st.columns([1, 2])
                with col_edit_user_btn:
                    if st.button("确认添加人员", key="eb_user_confirm", width="stretch", type="primary"):
                        ok_u, msg_u = add_user({'name': edit_user_val})
                        if ok_u:
                            refreshed = get_all_users()
                            matched = [u for u in refreshed if u['name'] == edit_user_val]
                            if matched:
                                edit_user_val_for_db = matched[0]['id']
                                st.session_state.pop("eb_user_sb", None)
                                st.session_state.pop("eb_user_inp", None)
                                st.success(f"人员「{edit_user_val}」添加成功，已自动选中")
                                st.rerun()
                            else:
                                st.error("人员添加后无法获取ID，请刷新重试")
                        else:
                            st.error(f"人员添加失败：{msg_u}")

            st.divider()

            # ═══════════════════════════════════════════════════════
            # 编辑表单（仅含日期/状态/用途/备注）
            # ═══════════════════════════════════════════════════════
            with st.form("edit_borrow_form"):
                c1, c2 = st.columns(2)
                with c1:
                    edit_borrow_date = st.date_input("开始日期",
                                                     value=datetime.strptime(edit_rec.get('borrow_date', str(date.today())),
                                                                             '%Y-%m-%d').date(), key='eb_bd')
                with c2:
                    edit_status = st.selectbox("状态",
                                               ["借出中", "已出库", "已归还"],
                                               index=["借出中", "已出库", "已归还"].index(edit_rec['status'])
                                               if edit_rec['status'] in ["借出中", "已出库", "已归还"] else 0,
                                               key='eb_status')
                    edit_return = st.date_input("预计归还",
                                                value=datetime.strptime(edit_rec.get('expected_return_date', str(date.today() + timedelta(7))),
                                                                        '%Y-%m-%d').date(), key='eb_rd')
                edit_purpose = st.text_input("用途/项目",
                                             value=edit_rec.get('purpose') or '', key='eb_purpose')
                edit_notes = st.text_area("备注",
                                          value=edit_rec.get('notes') or '', key='eb_notes')

                cb1, cb2 = st.columns(2)
                with cb1:
                    sub_edit = st.form_submit_button("保存修改", type="primary", width="stretch")
                with cb2:
                    can_edit = st.form_submit_button("取消", width="stretch")

            if sub_edit:
                updates = {
                    'user_id': edit_user_val_for_db,
                    'borrow_date': str(edit_borrow_date),
                    'expected_return_date': str(edit_return),
                    'status': edit_status,
                    'purpose': edit_purpose,
                    'notes': edit_notes,
                }
                ok, msg = update_borrow_record(edit_rec['id'], updates)
                st.session_state.borrow_edit_id = None
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
            if can_edit:
                st.session_state.borrow_edit_id = None
                st.rerun()

        # 二次确认弹窗触发后执行删除
        if st.session_state.borrow_del_confirm:
            del_rec_id = st.session_state.borrow_del_confirm
            st.session_state.borrow_del_confirm = None
            ok, msg = delete_borrow_record(del_rec_id)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()

        # 记录表格
        for r in records:
            # 区分记录类型
            is_usage = r.get('record_type') == 'usage'
            type_badge = "实验室使用" if is_usage else "外借出库"
            # usage 记录的状态显示为「使用中」以区别于借出
            display_status = "使用中" if (is_usage and r['status'] == '借出中') else r['status']
            # 类型与状态徽标（对齐全站设计令牌 .qms-status）
            status_variant = {
                "借出中": "pending", "使用中": "pending",
                "已出库": "neutral", "已归还": "approved", "逾期": "risk",
            }.get(r['status'], "neutral")
            type_badge_html = ui_status_badge(type_badge, "neutral")
            status_badge_html = ui_status_badge(display_status, status_variant)
            # 左侧强调色：实验室使用=品牌蓝，外借出库=警告橙
            accent = "var(--qs-primary)" if is_usage else "var(--qs-warning)"

            with st.container():
                # F17 修复：原先用缩进的多行 f-string 传给 st.markdown，
                # 缩进 + 数据里的 </div> 被 markdown 当成代码块（stMarkdownPre），
                # 导致模板自己的 </div> 以纯文本泄露。改为无缩进拼接字符串，
                # 并对用户数据字段做 html.escape，避免数据里的标签破坏结构。
                _line2 = (f"{_html.escape(str(r['user_name']))} | "
                          f"{_html.escape(str(r['borrow_date']))} → "
                          f"{_html.escape(str(r.get('expected_return_date', '未设')))}")
                if r.get('actual_return_date'):
                    _line2 += f" | {_html.escape(str(r['actual_return_date']))}"
                if r.get('purpose'):
                    _line2 += f" | {_html.escape(str(r['purpose']))}"
                _card = (
                    '<div style="border:1px solid var(--qms-line); border-left:4px solid ' + accent +
                    '; border-radius:var(--qms-radius-sm); padding:10px 14px; margin:4px 0; background:var(--qms-surface);">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                    '<span><strong>' + _html.escape(str(r['equipment_name'])) +
                    '</strong> <code style="font-size:11px;margin-left:6px;">' + _html.escape(str(r['serial_number'])) + '</code></span>'
                    '<span style="display:flex;gap:6px;">' + type_badge_html + status_badge_html + '</span>'
                    '</div>'
                    '<div style="font-size:12px;color:var(--qms-muted);">' + _line2 + '</div>'
                    '</div>'
                )
                st.markdown(_card, unsafe_allow_html=True)

                # 操作按钮
                col_btn1, col_btn2, _ = st.columns([0.5, 0.5, 5])
                with col_btn1:
                    st.button("编辑", key=f"bre_{r['id']}",
                              on_click=lambda rid=r['id']: st.session_state.update({'borrow_edit_id': rid}),
                              help="编辑这条记录")
                with col_btn2:
                    if st.button("删除", key=f"brd_{r['id']}", help="删除这条记录"):
                        confirm_dialog(
                            "确认删除借用记录",
                            f"确定要删除记录 **#{r['id']}**（{r['equipment_name']}）吗？此操作不可撤销。",
                            state_key="borrow_del_confirm",
                            state_value=r['id'],
                            confirm_label="确认删除",
                            confirm_type="primary",
                        )
    else:
        ui_empty_state("暂无记录", hint="借用或归还操作完成后的记录会显示在这里。")

# ==================== 人员管理 ====================
if is_admin:
    with st.expander("人员管理", expanded=False):
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
                with cb1: sub = st.form_submit_button("保存", width="stretch", type="primary")
                with cb2: can = st.form_submit_button("取消", width="stretch")
            if sub:
                # F1(b)：DB 层兜底——非管理员拒绝写入
                if not is_admin:
                    st.error("无权限：仅管理员可管理用户")
                    st.rerun()
                elif not u_name:
                    st.error("姓名不能为空！")
                else:
                    d = {'name': u_name, 'department': u_dept, 'phone': u_phone, 'email': u_email, 'role': u_role}
                    ok, msg = (update_user(st.session_state.user_edit_id, d) if user_editing else add_user(d))
                    if ok: st.session_state.user_edit_id = None; st.success(msg); st.rerun()
                    else: st.error(msg)
            if can: st.session_state.user_edit_id = None; st.rerun()
        for u in get_all_users():
            c1, c2, c3 = st.columns([4, 0.7, 0.7])
            with c1:
                st.markdown(f"**{u['name']}** — {u['department']}")
            with c2:
                if st.button("编辑", key=f"ue_{u['id']}"): st.session_state.user_edit_id = u['id']; st.rerun()
            with c3:
                if st.button("删除", key=f"ud_{u['id']}"):
                    confirm_dialog(
                        "确认删除人员",
                        f"确定要删除用户 **{u['name']}** 吗？此操作不可撤销。",
                        state_key="user_del_confirm",
                        state_value=u['id'],
                        confirm_label="确认删除",
                        confirm_type="primary",
                    )

        # 人员删除二次确认后执行
        if st.session_state.user_del_confirm:
            # F1(b)：DB 层兜底——非管理员拒绝删除
            if not is_admin:
                st.error("无权限：仅管理员可删除用户")
                st.session_state.user_del_confirm = None
            else:
                del_user_id = st.session_state.user_del_confirm
                st.session_state.user_del_confirm = None
                ok, msg = delete_user(del_user_id)
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()
else:
    ui_empty_state("无权限", "需要管理员权限")
