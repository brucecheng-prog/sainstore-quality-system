"""
实验室设备管理系统 - 数据报表页面
"""

import streamlit as st
import pandas as pd
try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ModuleNotFoundError:
    px = None
    go = None
    PLOTLY_AVAILABLE = False
from datetime import date
from io import BytesIO
from pages._utils import render_sidebar, render_topbar, ui_empty_state, ui_table
from database import (
    init_db, get_dashboard_stats, get_status_distribution,
    get_category_distribution, get_borrow_stats, get_maintenance_cost_stats,
    get_all_equipment, get_all_borrow_records_export, get_all_maintenance_export,
    get_borrow_records, get_upcoming_maintenance, get_recent_borrows,
    get_factory_stats, get_factory_freq_by_month, get_factory_freq_by_type,
)

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")
init_db()

# 渲染侧边栏导航
st.session_state.current_page = "数据看板"
with st.sidebar:
    render_sidebar()
render_topbar("数据看板")



st.title("数据看板")

tab1, tab2 = st.tabs(["数据统计", "报表导出"])

# ==================== Tab 1: 数据统计 ====================
with tab1:
    stats = get_dashboard_stats()
    borrow_stats = get_borrow_stats()

    # 汇总卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🔧 设备总数", stats['total'])
    with col2:
        st.metric("💰 资产总值", f"¥{stats['total_value']:,.0f}")
    with col3:
        st.metric("🔄 总借用次数", borrow_stats['total'])
    with col4:
        st.metric("👥 实验室人数", stats['total_users'])

    st.markdown("---")

    # 借用月度趋势
    st.subheader("借用月度趋势")
    borrow_stats = get_borrow_stats()
    if borrow_stats.get('monthly'):
        df_monthly = pd.DataFrame(borrow_stats['monthly'])
        if PLOTLY_AVAILABLE:
            fig = px.line(
                df_monthly, x='month', y='count', markers=True,
                labels={'month': '月份', 'count': '借用次数'},
            )
            # 颜色取设计令牌 --qs-primary (#2563eb)，plotly 不支持 CSS 变量故用字面值
            fig.update_traces(line=dict(color='#2563eb', width=2), marker=dict(size=8))
            fig.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, width="stretch")
        else:
            st.bar_chart(df_monthly.set_index('month')['count'])
    else:
        ui_empty_state("暂无借用数据", "暂无可统计的借用记录，新增借用后将自动生成趋势")

    st.markdown("---")

    # 两列图
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("设备分类资产分布")
        cat_data = get_category_distribution()
        if cat_data:
            df_cat = pd.DataFrame(cat_data)
            if PLOTLY_AVAILABLE:
                fig = px.treemap(
                    df_cat, path=['name'], values='count',
                    color='total_value', color_continuous_scale='Blues',
                    labels={'name': '分类', 'count': '数量', 'total_value': '资产总值'},
                )
                fig.update_layout(height=380, margin=dict(t=20, b=20, l=20, r=20))
                st.plotly_chart(fig, width="stretch")
            else:
                ui_table(df_cat[['name', 'count', 'total_value']], hide_index=True, width="stretch")

    with col_r:
        st.subheader("维护费用趋势")
        cost_data = get_maintenance_cost_stats()
        if cost_data:
            df_cost = pd.DataFrame(cost_data)
            if PLOTLY_AVAILABLE:
                fig = px.bar(
                    df_cost, x='month', y='total_cost',
                    labels={'month': '月份', 'total_cost': '费用 (¥)'},
                    color='total_cost', color_continuous_scale='Oranges',
                )
                fig.update_layout(height=380, margin=dict(t=20, b=20, l=20, r=20), showlegend=False)
                st.plotly_chart(fig, width="stretch")
            else:
                ui_table(df_cost[['month', 'total_cost']], hide_index=True, width="stretch")
        else:
            ui_empty_state("暂无维护费用数据", "暂无可统计的维护费用记录")

    st.markdown("---")

    # 设备利用率
    st.subheader("设备借用频次排行 (Top 10)")
    recent = get_borrow_records(per_page=1000)
    if recent[0]:
        df_borrow = pd.DataFrame(recent[0])
        usage = df_borrow.groupby('equipment_name').size().reset_index(name='count')
        usage = usage.sort_values('count', ascending=False).head(10)
        if PLOTLY_AVAILABLE:
            fig = px.bar(
                usage, x='equipment_name', y='count',
                labels={'equipment_name': '设备', 'count': '借用次数'},
                color='count', color_continuous_scale='Viridis',
            )
            fig.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20), showlegend=False)
            st.plotly_chart(fig, width="stretch")
        else:
            st.bar_chart(usage.set_index('equipment_name')['count'])
    else:
        ui_empty_state("暂无借用数据", "暂无可统计的借用记录，新增借用后将自动生成趋势")

# ==================== Tab 2: 报表导出 ====================
    st.markdown("---")

    # ==================== 驻厂登记统计 ====================
    st.subheader("驻厂登记统计")
    fr_stats = get_factory_stats()
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.metric("🏭 驻厂登记总数", fr_stats['total'])
    with fc2:
        st.metric("✅ Pass", fr_stats['onsite'])
    with fc3:
        st.metric("❌ Fail", fr_stats['ended'])
    with fc4:
        st.metric("🚨 空跑次数", fr_stats['empty'])

    fcol_l, fcol_r = st.columns(2)
    with fcol_l:
        st.markdown("**驻厂月度趋势**")
        month_data = get_factory_freq_by_month()
        if month_data:
            df_m = pd.DataFrame(month_data)
            fig_m = px.line(
                df_m, x='month', y='count', markers=True,
                labels={'count': '驻厂次数', 'month': '月份'},
                color_discrete_sequence=['#ea580c'],
            )
            fig_m.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
            st.plotly_chart(fig_m, width="stretch")
        else:
            ui_empty_state("暂无驻厂数据", "新增驻厂登记后将自动生成趋势")

    with fcol_r:
        st.markdown("**按出差类型统计**")
        type_data = get_factory_freq_by_type()
        if type_data:
            df_t = pd.DataFrame(type_data)
            fig_t = px.bar(
                df_t, x='type', y='count',
                labels={'count': '次数', 'type': '出差类型'},
                color_discrete_sequence=['#7C3AED'],
            )
            fig_t.update_layout(margin=dict(l=20, r=20, t=10, b=20), height=320)
            st.plotly_chart(fig_t, width="stretch")
        else:
            ui_empty_state("暂无驻厂数据", "新增驻厂登记后将自动生成统计")

with tab2:
    st.subheader("数据导出")

    export_options = st.multiselect(
        "选择要导出的数据",
        ["设备台账", "借用记录", "维护记录", "保养计划"],
        default=["设备台账"]
    )

    if st.button("生成并下载报表", type="primary", width="stretch"):
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
            f"下载报表 ({today_str})",
            buffer.getvalue(),
            f"实验室报表_{today_str}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
        st.success("报表已生成，点击上方按钮下载！")

    st.markdown("---")
    st.markdown("""
  ** 导出说明：**
    - **设备台账**: 所有设备的基本信息、分类、价格等
    - **借用记录**: 完整的借用归还历史记录
    - **维护记录**: 所有维护保养的操作记录和费用
    - **保养计划**: 未来 90 天内计划的维护保养事项
    """)
