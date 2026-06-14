"""
实验室设备管理系统 - 使用登记页面
"""

import streamlit as st
import pandas as pd
from datetime import date, time, datetime, timedelta
from database import (
    init_db, get_equipment_for_select, get_users,
    borrow_equipment, get_active_borrows, get_equipment_schedule,
    find_standards_for_equipment, get_all_test_standards, get_brand_list
)

st.set_page_config(page_title="使用登记", page_icon="📋", layout="wide")
init_db()

st.title("📋 设备使用登记")

# 显示当前占用情况
active = get_active_borrows()
if active:
    st.info(f"📌 当前共有 **{len(active)}** 台设备正在使用/预约中，请在下方看板确认目标设备空闲后再登记。")

st.markdown("---")

equipment_options = get_equipment_for_select()
available_eq = [e for e in equipment_options if e['status'] == '可用']

if not available_eq:
    st.warning("⚠️ 当前没有可用设备，请等待他人归还后再登记使用。")

    # 即使没有可用设备，也显示占用情况
    st.subheader("📅 当前设备占用状态")
    schedule = get_equipment_schedule()
    if schedule:
        for s in schedule:
            st.markdown(
                f"""<div style="border:1px solid #d9d9d9; border-left:4px solid #ff4d4f;
                border-radius:8px; padding:10px; margin:4px 0;">
                🔒 <b>{s['equipment_name']}</b> <code>{s['serial_number']}</code> —
                👤 {s['user_name']} | 📅 {s['borrow_date']}→{s['expected_return_date']}
                </div>""", unsafe_allow_html=True
            )
else:
    col_form, col_schedule = st.columns([5, 4])

    with col_form:
        st.markdown("### 📝 使用登记表")

        with st.form("usage_form", clear_on_submit=True):
            # --- 设备选择 ---
            eq_id = st.selectbox(
                "选择设备 *",
                options=[e['id'] for e in available_eq],
                format_func=lambda x: f"[{next((e['serial_number'] for e in available_eq if e['id']==x), '')}] {next((e['name'] for e in available_eq if e['id']==x), '')}",
                key='usage_eq'
            )

            # 获取选中设备的信息用于标准推荐
            selected_eq = next((e for e in available_eq if e['id'] == eq_id), {})
            eq_name = selected_eq.get('name', '')

            # --- 测试标准（自动推荐） ---
            recommended_standards = find_standards_for_equipment(eq_name)
            all_standards = get_all_test_standards()

            # 把推荐标准放在最前面
            standard_options = recommended_standards + [s for s in all_standards if s not in recommended_standards]
            default_idx = 0 if recommended_standards else None

            test_standard = st.selectbox(
                "测试标准 *",
                options=standard_options,
                index=default_idx if recommended_standards else 0,
                help="根据设备类型自动推荐，也可手动选择",
                key='usage_standard'
            )

            # --- 使用人员 ---
            users = get_users()
            user_id = st.selectbox(
                "使用人员 *",
                options=[u['id'] for u in users],
                format_func=lambda x: next((u['name'] for u in users if u['id']==x), ''),
                key='usage_user'
            )

            # --- 测试产品信息 ---
            st.markdown("##### 📦 测试产品信息")
            brands = get_brand_list()
            c_brand, c_sku = st.columns(2)
            with c_brand:
                brand = st.selectbox("产品品牌",
                                     options=[""] + brands,
                                     format_func=lambda x: "请选择品牌" if x == "" else x,
                                     key='usage_brand')
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

            submitted = st.form_submit_button("✅ 提交使用登记", type="primary", use_container_width=True)

        if submitted:
            if expected_return < borrow_date:
                st.error("预计完成日期不能早于开始日期！")
            elif not product_name:
                st.error("请填写产品名称！")
            elif end_time <= start_time:
                st.error("结束时间必须晚于开始时间！")
            else:
                ok, msg = borrow_equipment(
                    eq_id, user_id,
                    str(borrow_date), str(expected_return),
                    purpose, notes,
                    test_standard,
                    start_time.strftime('%H:%M'),
                    end_time.strftime('%H:%M'),
                    brand, sku, product_name
                )
                if ok:
                    st.success(f"✅ {msg}！")
                    st.rerun()
                else:
                    st.error(msg)

    with col_schedule:
        st.markdown("### 📅 当前设备占用看板")

        schedule = get_equipment_schedule()
        if schedule:
            for s in schedule:
                # 产品信息
                product_info = ""
                if s.get('product_name'):
                    product_info = f"📦 <b>{s['product_name']}</b>"
                    if s.get('brand') or s.get('sku'):
                        tags = []
                        if s.get('brand'): tags.append(s['brand'])
                        if s.get('sku'): tags.append(s['sku'])
                        product_info += f" | 🏷️ {' / '.join(tags)}"
                elif s.get('purpose'):
                    product_info = f"📦 {s['purpose']}"

                # 时间段
                time_info = ""
                if s.get('test_start_time') and s.get('test_end_time'):
                    time_info = f" ⏰ {s['test_start_time']} → {s['test_end_time']}"

                # 标准
                standard_tag = ""
                if s.get('test_standard'):
                    standard_tag = f"<br><small style='color:#888;'>📐 {s['test_standard']}</small>"

                st.markdown(
                    f"""<div style="border:1px solid #ddd; border-left:4px solid #1890ff;
                    border-radius:6px; padding:8px 12px; margin:4px 0; background:#f6ffed;">
                    <b>🔬 {s['equipment_name']}</b> <code style="font-size:11px;">{s['serial_number']}</code>
                    <br><small>👤 {s['user_name']} | 📅 {s['borrow_date']} → {s['expected_return_date']}{time_info}</small>
                    <br><small>{product_info}</small>{standard_tag}
                    </div>""",
                    unsafe_allow_html=True
                )
        else:
            st.success("✅ 所有设备均空闲，可随时登记使用。")

# 历史记录折叠区
with st.expander("📜 最近使用记录", expanded=False):
    from database import get_borrow_records
    records, total = get_borrow_records(per_page=10)
    if records:
        df = pd.DataFrame(records)
        df_d = df[['equipment_name', 'user_name', 'product_name', 'brand', 'sku',
                    'borrow_date', 'expected_return_date',
                    'test_standard', 'status']].copy()
        df_d.columns = ['设备', '使用人', '产品名称', '品牌', 'SKU',
                         '开始日期', '预计完成', '测试标准', '状态']
        st.dataframe(df_d, use_container_width=True, hide_index=True)
    else:
        st.info("暂无记录")
