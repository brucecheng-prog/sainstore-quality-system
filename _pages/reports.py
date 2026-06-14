"""
实验室设备管理系统 - 数据报表页面
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
from io import BytesIO
from database import (
    init_db, get_dashboard_stats, get_status_distribution,
    get_category_distribution, get_borrow_stats, get_maintenance_cost_stats,
    get_all_equipment, get_all_borrow_records_export, get_all_maintenance_export,
    get_borrow_records, get_upcoming_maintenance, get_recent_borrows
)

st.set_page_config(page_title="数据报表", page_icon="📊", layout="wide")
init_db()

st.title("📊 数据报表")

tab1, tab2 = st.tabs(["📈 数据统计", "📥 报表导出"])

# ==================== Tab 1: 数据统计 ====================
with tab1:
    stats = get_dashboard_stats()

    # 汇总卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("设备总数", stats['total'])
    with col2:
        st.metric("资产总值", f"¥{stats['total_value']:,.0f}")
    with col3:
        st.metric("总借用次数", stats['active_borrows'])
    with col4:
        st.metric("实验室人数", stats['total_users'])

    st.markdown("---")

    # 借用月度趋势
    st.subheader("📊 借用月度趋势")
    borrow_stats = get_borrow_stats()
    if borrow_stats.get('monthly'):
        df_monthly = pd.DataFrame(borrow_stats['monthly'])
        fig = px.line(
            df_monthly, x='month', y='count', markers=True,
            labels={'month': '月份', 'count': '借用次数'},
        )
        fig.update_traces(line=dict(color='#1890ff', width=2), marker=dict(size=8))
        fig.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无借用数据")

    st.markdown("---")

    # 两列图
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("📦 设备分类资产分布")
        cat_data = get_category_distribution()
        if cat_data:
            df_cat = pd.DataFrame(cat_data)
            fig = px.treemap(
                df_cat, path=['name'], values='count',
                color='total_value', color_continuous_scale='Blues',
                labels={'name': '分类', 'count': '数量', 'total_value': '资产总值'},
            )
            fig.update_layout(height=380, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("🔧 维护费用趋势")
        cost_data = get_maintenance_cost_stats()
        if cost_data:
            df_cost = pd.DataFrame(cost_data)
            fig = px.bar(
                df_cost, x='month', y='total_cost',
                labels={'month': '月份', 'total_cost': '费用 (¥)'},
                color='total_cost', color_continuous_scale='Oranges',
            )
            fig.update_layout(height=380, margin=dict(t=20, b=20, l=20, r=20), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无维护费用数据")

    st.markdown("---")

    # 设备利用率
    st.subheader("📊 设备借用频次排行 (Top 10)")
    recent = get_borrow_records(per_page=1000)
    if recent[0]:
        df_borrow = pd.DataFrame(recent[0])
        usage = df_borrow.groupby('equipment_name').size().reset_index(name='count')
        usage = usage.sort_values('count', ascending=False).head(10)
        fig = px.bar(
            usage, x='equipment_name', y='count',
            labels={'equipment_name': '设备', 'count': '借用次数'},
            color='count', color_continuous_scale='Viridis',
        )
        fig.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无借用数据")

# ==================== Tab 2: 报表导出 ====================
with tab2:
    st.subheader("📥 数据导出")

    export_options = st.multiselect(
        "选择要导出的数据",
        ["设备台账", "借用记录", "维护记录", "保养计划"],
        default=["设备台账"]
    )

    if st.button("📥 生成并下载报表", type="primary", use_container_width=True):
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            if "设备台账" in export_options:
                eq_data = get_all_equipment()
                if eq_data:
                    df_eq = pd.DataFrame(eq_data)
                    df_eq = df_eq.rename(columns={
                        'name': '设备名称', 'model': '型号', 'serial_number': '设备编号',
                        'category_name': '分类', 'location': '位置', 'status': '状态',
                        'purchase_date': '购置日期', 'price': '价格', 'supplier': '供应商',
                        'warranty_expiry': '保修截止', 'description': '备注'
                    })
                    cols = [c for c in ['设备名称', '型号', '设备编号', '分类', '位置', '状态',
                                         '购置日期', '价格', '供应商', '保修截止', '备注'] if c in df_eq.columns]
                    df_eq[cols].to_excel(writer, index=False, sheet_name='设备台账')

            if "借用记录" in export_options:
                br = get_all_borrow_records_export()
                if br:
                    pd.DataFrame(br).to_excel(writer, index=False, sheet_name='借用记录')

            if "维护记录" in export_options:
                mt = get_all_maintenance_export()
                if mt:
                    pd.DataFrame(mt).to_excel(writer, index=False, sheet_name='维护记录')

            if "保养计划" in export_options:
                up = get_upcoming_maintenance(90)
                if up:
                    df_up = pd.DataFrame(up)
                    df_up = df_up.rename(columns={
                        'equipment_name': '设备名称', 'serial_number': '编号',
                        'maintenance_type': '类型', 'next_maintenance_date': '下次维护',
                        'technician': '技术人员', 'notes': '备注'
                    })
                    cols = [c for c in ['设备名称', '编号', '类型', '下次维护', '技术人员', '备注'] if c in df_up.columns]
                    df_up[cols].to_excel(writer, index=False, sheet_name='保养计划')

        today_str = date.today().isoformat()
        st.download_button(
            f"📥 下载报表 ({today_str})",
            buffer.getvalue(),
            f"实验室报表_{today_str}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        st.success("报表已生成，点击上方按钮下载！")

    st.markdown("---")
    st.markdown("""
    **📋 导出说明：**
    - **设备台账**: 所有设备的基本信息、分类、价格等
    - **借用记录**: 完整的借用归还历史记录
    - **维护记录**: 所有维护保养的操作记录和费用
    - **保养计划**: 未来 90 天内计划的维护保养事项
    """)
