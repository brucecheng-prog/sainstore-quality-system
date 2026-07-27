"""
实验室设备管理系统 - 使用登记页面
"""

import streamlit as st
import pandas as pd
import os, sys
from datetime import date, time, datetime, timedelta

# 确保 _pages 目录在 Python 路径中，以便导入 utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    init_db, get_equipment_for_select, get_users,
    borrow_equipment, get_active_borrows, get_equipment_schedule,
    update_usage_result, get_borrow_records,
    find_standards_for_equipment, get_all_test_standards, get_brand_list,
    add_user, add_equipment,
)
from pages._utils import creatable_select, creatable_selectbox, render_sidebar, render_topbar, ui_empty_state, ui_table

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# 渲染侧边栏导航
st.session_state.current_page = "使用登记"
with st.sidebar:
    render_sidebar()
render_topbar("使用登记")



st.title("设备使用登记")

# 显示当前占用情况
active = get_active_borrows()
if active:
    st.info(f"当前共有 **{len(active)}** 台设备正在使用/预约中，请在下方看板确认目标设备空闲后再登记。")

st.markdown("---")

equipment_options = get_equipment_for_select()
available_eq = [e for e in equipment_options if e['status'] == '可用']

if not available_eq:
    st.warning("当前没有可用设备，请等待他人归还后再登记使用。")

    # 即使没有可用设备，也显示占用情况
    st.subheader("当前设备占用状态")
    schedule = get_equipment_schedule()
    if schedule:
        for s in schedule:
            st.markdown(
                f"""<div style="border:1px solid var(--qs-line); border-left:4px solid var(--qs-danger);
                border-radius:8px; padding:10px; margin:4px 0;">
         <b>{s['equipment_name']}</b> <code>{s['serial_number']}</code> —
         {s['user_name']} | {s['borrow_date']}→{s['expected_return_date']}
                </div>""", unsafe_allow_html=True
            )
else:
    col_form, col_schedule = st.columns([5, 4])

    # ── 持久化已确认的设备和人员 ID ──
    if "usage_confirmed_eq_id" not in st.session_state:
        st.session_state.usage_confirmed_eq_id = None
    if "usage_confirmed_eq_name" not in st.session_state:
        st.session_state.usage_confirmed_eq_name = ""
    if "usage_confirmed_user_id" not in st.session_state:
        st.session_state.usage_confirmed_user_id = None
    if "usage_confirmed_user_name" not in st.session_state:
        st.session_state.usage_confirmed_user_name = ""

    with col_form:
        st.markdown("### 使用登记表")

        # ═══════════════════════════════════════════════════════
        # 设备选择（表单外部 — 即时响应，选中已有设备时隐藏输入框）
        # ═══════════════════════════════════════════════════════
        st.markdown("##### 选择设备")
        eq_val, is_new_eq = creatable_selectbox(
            "选择设备 *",
            options=[e['id'] for e in available_eq],
            key_prefix="usage_eq",
            format_func=lambda eid: (
                f"[{next((e['serial_number'] for e in available_eq if e['id']==eid), '')}]"
                f"{next((e['name'] for e in available_eq if e['id']==eid), '')}"
            ),
            default_value=st.session_state.usage_confirmed_eq_id,
        )

        # 手动添加设备 → 显示确认按钮
        final_eq_id = st.session_state.usage_confirmed_eq_id
        eq_name = st.session_state.usage_confirmed_eq_name

        if is_new_eq and eq_val:
            col_addeq_btn, _ = st.columns([1, 2])
            with col_addeq_btn:
                if st.button("确认添加设备", key="usage_eq_confirm", width="stretch", type="primary"):
                    ok_e, msg_e = add_equipment({'name': eq_val})
                    if ok_e:
                        refreshed = get_equipment_for_select()
                        matched = [e for e in refreshed if e['name'] == eq_val]
                        if matched:
                            st.session_state.usage_confirmed_eq_id = matched[0]['id']
                            st.session_state.usage_confirmed_eq_name = matched[0]['name']
                            # 清除 selectbox 状态以切换到新项
                            st.session_state.pop("usage_eq_sb", None)
                            st.session_state.pop("usage_eq_inp", None)
                            st.success(f"设备「{eq_val}」添加成功，已自动选中")
                            st.rerun()
                        else:
                            st.error("设备添加后无法获取ID，请刷新重试")
                    else:
                        st.error(f"设备添加失败：{msg_e}")

        if not is_new_eq and eq_val is not None:
            # 选中已有设备 → 同步确认
            selected_eq = next((e for e in available_eq if e['id'] == eq_val), {})
            final_eq_id = eq_val
            eq_name = selected_eq.get('name', '')
            st.session_state.usage_confirmed_eq_id = final_eq_id
            st.session_state.usage_confirmed_eq_name = eq_name

        # ── 显示已选设备 ──
        if final_eq_id:
            st.caption(f"当前设备：**{eq_name}** (ID: {final_eq_id})")

        st.divider()

        # ═══════════════════════════════════════════════════════
        # 使用人员选择（表单外部 — 即时响应）
        # ═══════════════════════════════════════════════════════
        st.markdown("##### 使用人员")
        users = get_users()
        user_val, is_new_user = creatable_selectbox(
            "使用人员 *",
            options=[u['id'] for u in users],
            key_prefix="usage_user",
            format_func=lambda uid: (
                f"{next((u['name'] for u in users if u['id']==uid), '')}"
            ),
            default_value=st.session_state.usage_confirmed_user_id,
        )

        # 手动添加人员 → 显示确认按钮
        final_user_id = st.session_state.usage_confirmed_user_id
        final_user_name = st.session_state.usage_confirmed_user_name

        if is_new_user and user_val:
            col_adduser_btn, _ = st.columns([1, 2])
            with col_adduser_btn:
                if st.button("确认添加人员", key="usage_user_confirm", width="stretch", type="primary"):
                    ok_u, msg_u = add_user({'name': user_val})
                    if ok_u:
                        refreshed = get_users()
                        matched = [u for u in refreshed if u['name'] == user_val]
                        if matched:
                            st.session_state.usage_confirmed_user_id = matched[0]['id']
                            st.session_state.usage_confirmed_user_name = matched[0]['name']
                            # 清除 selectbox 状态以切换到新项
                            st.session_state.pop("usage_user_sb", None)
                            st.session_state.pop("usage_user_inp", None)
                            st.success(f"人员「{user_val}」添加成功，已自动选中")
                            st.rerun()
                        else:
                            st.error("人员添加后无法获取ID，请刷新重试")
                    else:
                        st.error(f"人员添加失败：{msg_u}")

        if not is_new_user and user_val is not None:
            # 选中已有人员 → 同步确认
            selected_user = next((u for u in users if u['id'] == user_val), {})
            final_user_id = user_val
            final_user_name = selected_user.get('name', '')
            st.session_state.usage_confirmed_user_id = final_user_id
            st.session_state.usage_confirmed_user_name = final_user_name

        # ── 显示已选人员 ──
        if final_user_id:
            st.caption(f"当前人员：**{final_user_name}**")

        st.divider()

        # ═══════════════════════════════════════════════════════
        # 测试详情表单（仅含测试相关字段）
        # ═══════════════════════════════════════════════════════
        with st.form("usage_form", clear_on_submit=True):
            # --- 测试标准（自动推荐） ---
            recommended_standards = find_standards_for_equipment(eq_name)
            all_standards = get_all_test_standards()
            standard_options = recommended_standards + [s for s in all_standards if s not in recommended_standards]

            test_standard = creatable_select(
                "测试标准 *",
                options=standard_options,
                key="usage_std"
            )

            # --- 测试产品信息 ---
            st.markdown("##### 测试产品信息")
            brands = get_brand_list()
            c_brand, c_sku = st.columns(2)
            with c_brand:
                brand = creatable_select("产品品牌", options=[""] + brands, key="usage_brand")
            with c_sku:
                sku = st.text_input("产品SKU", placeholder="例如：TB-JXH-001",
                                    key='usage_sku')

            product_name = st.text_input("产品名称 *",
                                         placeholder="例如：TURBRO接线盒、PD5K蓝牙键盘",
                                         key='usage_product')

            # --- 测试项目描述 ---
            purpose = st.text_input("测试项目描述 *",
                                    placeholder="例如：按键寿命2万次验证、防水IPX5测试",
                                    key='usage_purpose')

            # --- 日期选择 ---
            c1, c2 = st.columns(2)
            with c1:
                borrow_date = st.date_input("开始日期 *", value=date.today(), key='usage_date')
            with c2:
                expected_return = st.date_input("预计完成日期 *",
                                                value=date.today() + timedelta(days=7),
                                                key='usage_return_date')

            # --- 时间选择 ---
            c3, c4 = st.columns(2)
            with c3:
                start_time = st.time_input("开始时间", value=time(9, 0), step=1800,
                                           help="选择测试开始的具体时间", key='usage_start_time')
            with c4:
                end_time = st.time_input("结束时间", value=time(17, 0), step=1800,
                                         help="选择测试预计结束的时间", key='usage_end_time')

            notes = st.text_area("备注", placeholder="其他补充说明...", key='usage_notes')

            submitted = st.form_submit_button("提交使用登记", type="primary", width="stretch")

        if submitted:
            # ── 前端校验 ──
            if not final_eq_id:
                st.error("请先选择设备并确认！")
            elif not final_user_id:
                st.error("请先选择使用人员并确认！")
            elif expected_return < borrow_date:
                st.error("预计完成日期不能早于开始日期！")
            elif not product_name:
                st.error("请填写产品名称！")
            elif end_time <= start_time:
                st.error("结束时间必须晚于开始时间！")
            else:
                ok, msg = borrow_equipment(
                    final_eq_id, final_user_id,
                    str(borrow_date), str(expected_return),
                    purpose, notes,
                    test_standard,
                    start_time.strftime('%H:%M'),
                    end_time.strftime('%H:%M'),
                    brand, sku, product_name
                )
                if ok:
                    # 清除确认状态
                    st.session_state.usage_confirmed_eq_id = None
                    st.session_state.usage_confirmed_eq_name = ""
                    st.session_state.usage_confirmed_user_id = None
                    st.session_state.usage_confirmed_user_name = ""
                    st.success(f"{msg}！")
                    st.rerun()
                else:
                    st.error(msg)

    with col_schedule:
        st.markdown("### 当前设备占用看板")

        schedule = get_equipment_schedule()
        if schedule:
            for s in schedule:
                # 产品信息
                product_info = ""
                if s.get('product_name'):
                    product_info = f"<b>{s['product_name']}</b>"
                    if s.get('brand') or s.get('sku'):
                        tags = []
                        if s.get('brand'): tags.append(s['brand'])
                        if s.get('sku'): tags.append(s['sku'])
                        product_info += f"| {' / '.join(tags)}"
                elif s.get('purpose'):
                    product_info = f"{s['purpose']}"

                # 时间段
                time_info = ""
                if s.get('test_start_time') and s.get('test_end_time'):
                    time_info = f"{s['test_start_time']} → {s['test_end_time']}"

                # 标准
                standard_tag = ""
                if s.get('test_standard'):
                    standard_tag = f"<br><small style='color:#888;'> {s['test_standard']}</small>"

                st.markdown(
                    f"""<div style="border:1px solid var(--qs-line); border-left:4px solid var(--qs-primary);
                    border-radius:6px; padding:8px 12px; margin:4px 0; background:var(--qs-success-bg);">
          <b> {s['equipment_name']}</b> <code style="font-size:11px;">{s['serial_number']}</code>
          <br><small> {s['user_name']} | {s['borrow_date']} → {s['expected_return_date']}{time_info}</small>
                    <br><small>{product_info}</small>{standard_tag}
                    </div>""",
                    unsafe_allow_html=True
                )
        else:
            st.success("所有设备均空闲，可随时登记使用。")

# 结果反馈
if active:
    with st.expander("使用结果反馈", expanded=False):
        st.caption("为使用完毕的设备标记测试结果")
        usage_opt = {a['id']: f"{a['equipment_name']} — {a['user_name']} ({a.get('borrow_date','')})" for a in active}
        col_r1, col_r2 = st.columns([3, 1])
        with col_r1:
            feedback_id = st.selectbox("选择记录", list(usage_opt.keys()),
                                       format_func=lambda x: usage_opt[x],
                                       key="feedback_select", label_visibility="collapsed")
        with col_r2:
            feedback_result = st.selectbox("测试结果", ["OK", "NG", "待定"], key="feedback_result")
        if st.button("保存结果", width="stretch", type="primary"):
            ok, msg = update_usage_result(feedback_id, feedback_result)
            if ok:
                st.success(f"已标记为 {feedback_result}")
                st.rerun()
            else:
                st.error(msg)

# 历史记录折叠区
with st.expander("最近使用记录", expanded=False):
    from database import get_borrow_records
    records, total = get_borrow_records(per_page=10)
    if records:
        df = pd.DataFrame(records)
        df_d = df[['equipment_name', 'user_name', 'product_name', 'brand', 'sku',
                    'borrow_date', 'expected_return_date',
                    'test_standard', 'status']].copy()
        df_d.columns = ['设备', '使用人', '产品名称', '品牌', 'SKU',
                         '开始日期', '预计完成', '测试标准', '状态']
        # ── 每页行数选择器 ──
        _u_opts = [10, 20, 50, 100]
        _u_def = st.session_state.get("usage_page_size", 20)
        _uc1, _uc2 = st.columns([1, 4])
        with _uc1:
            _upsz = st.selectbox("每页行数", options=_u_opts,
                index=_u_opts.index(_u_def) if _u_def in _u_opts else 1,
                key="u_page_size_sel", label_visibility="collapsed")
        if st.session_state.get("u_page_size_sel", 20) != st.session_state.get("usage_page_size", 20):
            st.session_state["usage_page_size"] = st.session_state["u_page_size_sel"]
            st.rerun()
        _u_psz = st.session_state.get("usage_page_size", 20)
        with _uc2:
            st.caption(f"共 **{len(df_d)}** 条 · 显示 **{min(_u_psz, len(df_d))}** 行")
        # 只显示前 N 行（Streamlit dataframe 不支持原生分页，用高度控制）
        _u_show = df_d.head(_u_psz)
        ui_table(_u_show, width="stretch", hide_index=True,
                     height=min(40 * min(_u_psz, len(df_d)) + 48, 800))
    else:
        ui_empty_state("暂无记录", hint="使用登记或预约完成后，相关记录会显示在这里。")