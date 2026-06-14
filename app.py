"""
品质系统管理平台 - 首页数据看板
覆盖：实验室管理 · 品质管理 · 样品管理 · 变更管理
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from database import (
    init_db,
    get_dashboard_stats, get_status_distribution, get_category_distribution,
    get_recent_borrows, get_upcoming_maintenance, get_active_borrows,
    get_sample_dashboard_stats, get_sample_bg_distribution,
    get_change_dashboard_stats, get_change_bu_distribution,
    get_inspection_dashboard_stats, get_report_type_distribution,
    get_recent_reports, get_recent_changes, get_expiring_samples,
    get_report_daily_stats,
)

# 页面配置
st.set_page_config(
    page_title="品质系统管理平台",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

init_db()

# ---- 加载数据 ----
lab_stats = get_dashboard_stats()
sample_stats = get_sample_dashboard_stats()
change_stats = get_change_dashboard_stats()
inspection_stats = get_inspection_dashboard_stats()
report_daily = get_report_daily_stats()
active_borrows = get_active_borrows()
expiring_samples = get_expiring_samples(30)
upcoming_maintenance = get_upcoming_maintenance(30)

# ---- 侧边栏 ----
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/microscope.png", width=60)
    st.title("🔬 品质系统管理")

    st.markdown("---")
    st.markdown(f"📍 **设备总数**: {lab_stats['total']} 台")
    st.markdown(f"💰 **资产总值**: ¥{lab_stats['total_value']:,.0f}")
    st.markdown(f"👥 **人员**: {lab_stats['total_users']} 人")
    st.markdown("---")
    st.markdown(f"📄 **检验报告**: {inspection_stats['total']} 份")
    if inspection_stats['pending'] > 0:
        st.markdown(f"⏳ **待审核**: {inspection_stats['pending']} 份")
    st.markdown("---")
    st.markdown(f"📦 **样品库存**: {sample_stats['total']} 个")
    st.markdown(f"📝 **变更记录**: {change_stats['total']} 条")
    if sample_stats['near_expiry'] > 0:
        st.markdown(f"⚠️ **即将过期**: {sample_stats['near_expiry']} 个")
    st.markdown("---")
    st.caption("📌 使用左侧导航切换功能页面")
    st.caption(f"🕐 {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")

# ---- CSS 样式 ----
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px; padding: 16px 20px;
        color: white; margin: 4px 0;
    }
    .metric-card.green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .metric-card.blue { background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%); }
    .metric-card.orange { background: linear-gradient(135deg, #f2994a 0%, #f2c94c 100%); }
    .metric-card.red { background: linear-gradient(135deg, #eb5757 0%, #f2994a 100%); }
    .metric-card.purple { background: linear-gradient(135deg, #8E2DE2 0%, #4A00E0 100%); }
    .metric-card.teal { background: linear-gradient(135deg, #00b4db 0%, #0083b0 100%); }
    .metric-card .value { font-size: 30px; font-weight: 800; line-height: 1.1; }
    .metric-card .label { font-size: 13px; opacity: 0.9; margin-top: 4px; }
    .metric-card .sub { font-size: 11px; opacity: 0.75; }

    .section-title {
        font-size: 18px; font-weight: 700; color: #1a1a2e;
        border-left: 4px solid #667eea; padding-left: 12px; margin: 24px 0 12px 0;
    }

    .stat-badge {
        display: inline-block; padding: 2px 10px; border-radius: 10px;
        font-size: 12px; font-weight: 600;
    }
    .stat-badge.ok { background: #e6f7e6; color: #11998e; }
    .stat-badge.warn { background: #fff7e6; color: #d48806; }
    .stat-badge.danger { background: #fff1f0; color: #cf1322; }
    .stat-badge.info { background: #e6f7ff; color: #1890ff; }

    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.05);
        border-radius: 8px; padding: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ==================== 主内容区 ====================
st.title("📊 数据看板")
st.caption(f"📅 数据更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ｜ 覆盖：实验室管理 · 品质管理 · 样品管理 · 变更管理")

# ==================== 第一行：实验室概览指标 ====================
st.markdown('<div class="section-title">🔬 实验室概览</div>', unsafe_allow_html=True)

col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)

with col1:
    st.metric("设备总数", lab_stats['total'], delta=None, delta_color="off")
with col2:
    st.metric("✅ 可用", lab_stats['available'], delta=None, delta_color="off")
with col3:
    st.metric("📋 使用中", lab_stats['in_use'], delta=None, delta_color="off")
with col4:
    st.metric("📤 已借出", lab_stats['borrowed'], delta=None, delta_color="off")
with col5:
    st.metric("🔧 维修中", lab_stats['maintenance'], delta=None, delta_color="off")
with col6:
    st.metric("⚠️ 报废", lab_stats['scrapped'], delta=None, delta_color="off")
with col7:
    st.metric("💰 资产(万)", f"{lab_stats['total_value']/10000:.1f}万", delta=None, delta_color="off")
with col8:
    st.metric("👥 人员", lab_stats['total_users'], delta=None, delta_color="off")

# ==================== 第二行：品质管理概览指标 ====================
st.markdown('<div class="section-title">📄 品质管理概览</div>', unsafe_allow_html=True)

col_q1, col_q2, col_q3, col_q4, col_q5, col_q6, col_q7, col_q8 = st.columns(8)

with col_q1:
    st.metric("检验报告", inspection_stats['total'])
with col_q2:
    delta_str = f"{inspection_stats['this_month']} 本月" if inspection_stats['this_month'] > 0 else None
    st.metric("本月新增", inspection_stats['this_month'], delta=delta_str, delta_color="off")
with col_q3:
    st.metric("⏳ 待审核", inspection_stats['pending'], delta=f"{inspection_stats['pending']} 份" if inspection_stats['pending'] > 0 else None)
with col_q4:
    st.metric("✅ 已通过", inspection_stats['approved'])
with col_q5:
    st.metric("📦 样品总数", sample_stats['total'], delta=f"在库 {sample_stats['in_stock']}")
with col_q6:
    st.metric("📤 已出库", sample_stats['out_stock'])
with col_q7:
    st.metric("⚠️ 即将过期", sample_stats['near_expiry'], delta=f"{sample_stats['expired']} 已过期" if sample_stats['expired'] > 0 else None, delta_color="inverse")
with col_q8:
    st.metric("📝 变更总数", change_stats['total'], delta=f"本月 +{change_stats['this_month']}" if change_stats['this_month'] > 0 else None)

# ==================== 第三行：核心图表 (设备|样品|变更) ====================
st.markdown('<div class="section-title">📈 数据分析</div>', unsafe_allow_html=True)

col_left, col_mid, col_right = st.columns(3)

# --- 设备状态分布 ---
with col_left:
    st.subheader("🔬 设备状态分布")
    status_data = get_status_distribution()
    if status_data:
        df_status = pd.DataFrame(status_data)
        color_map = {'可用': '#52c41a', '借出': '#1890ff', '维修中': '#faad14', '报废': '#ff4d4f'}
        fig1 = px.pie(df_status, values='count', names='status',
                      color='status', color_discrete_map=color_map, hole=0.45)
        fig1.update_traces(textposition='inside', textinfo='percent+label')
        fig1.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                           showlegend=False,
                           annotations=[dict(text=f"{lab_stats['total']}台", x=0.5, y=0.5,
                                             font_size=20, showarrow=False)])
        st.plotly_chart(fig1, use_container_width=True)
    else:
        st.info("暂无设备数据")

# --- 样品 BG 分布 ---
with col_mid:
    st.subheader("📦 样品 BG 分布")
    sample_bg = get_sample_bg_distribution()
    if sample_bg:
        df_sbg = pd.DataFrame(sample_bg)
        colors = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#43e97b', '#fa709a']
        fig2 = px.pie(df_sbg, values='count', names='bg',
                      color='bg',
                      color_discrete_sequence=colors,
                      hole=0.45)
        fig2.update_traces(textposition='inside', textinfo='percent+label')
        fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                           showlegend=False,
                           annotations=[dict(text=f"{sample_stats['total']}个", x=0.5, y=0.5,
                                             font_size=20, showarrow=False)])
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("暂无样品数据")

# --- 变更 BU 分布 ---
with col_right:
    st.subheader("📝 变更 BU 分布")
    change_bu = get_change_bu_distribution()
    if change_bu:
        df_cbu = pd.DataFrame(change_bu)
        fig3 = px.bar(df_cbu, x='bu', y='count', text='count',
                      color='count', color_continuous_scale='Blues')
        fig3.update_traces(textposition='outside', textfont_size=11)
        fig3.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                           showlegend=False, xaxis_title=None, yaxis_title='数量',
                           coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("暂无变更数据")

# ==================== 第四行：设备分类 + 报告类型 ====================
col_l4, col_r4 = st.columns(2)

# --- 设备分类统计 ---
with col_l4:
    st.subheader("🔧 设备分类统计")
    cat_data = get_category_distribution()
    if cat_data:
        df_cat = pd.DataFrame(cat_data)
        fig4 = px.bar(df_cat, x='name', y='count', text='count',
                      color='count', color_continuous_scale='Viridis')
        fig4.update_traces(textposition='outside', textfont_size=12)
        fig4.update_layout(height=340, margin=dict(t=10, b=10, l=10, r=10),
                           showlegend=False, xaxis_title=None, yaxis_title='数量（台）',
                           coloraxis_showscale=False)
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("暂无分类数据")

# --- 报告类型分布 ---
with col_r4:
    st.subheader("📄 报告类型分布")
    report_types = get_report_type_distribution()
    if report_types:
        df_rt = pd.DataFrame(report_types)
        fig5 = px.bar(df_rt, x='type', y='count', text='count',
                      color='count', color_continuous_scale='Oranges')
        fig5.update_traces(textposition='outside', textfont_size=12)
        fig5.update_layout(height=340, margin=dict(t=10, b=10, l=10, r=10),
                           showlegend=False, xaxis_title=None, yaxis_title='数量',
                           coloraxis_showscale=False)
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("📭 暂无检验报告数据，上传报告后将在此显示统计")

# ==================== 第五行：预警区域 ====================
st.markdown('<div class="section-title">⚠️ 预警中心</div>', unsafe_allow_html=True)

col_w1, col_w2, col_w3 = st.columns(3)

# --- 样品到期预警 ---
with col_w1:
    st.subheader("📦 样品到期预警 (30天内)")
    if expiring_samples:
        for s in expiring_samples[:5]:
            days_left = (datetime.strptime(s['expiry_date'], '%Y-%m-%d') - datetime.now()).days
            badge_class = 'danger' if days_left <= 7 else 'warn'
            st.markdown(f"""
            <div style="border:1px solid #eee; border-radius:8px; padding:10px; margin:4px 0;
                        {'border-left:4px solid #cf1322;' if days_left <= 7 else 'border-left:4px solid #faad14;'}">
                <span class="stat-badge {badge_class}">{days_left}天</span>
                <strong>{s['sample_name'][:20]}</strong>
                <div style="font-size:12px; color:#888; margin-top:2px;">
                    {s['bg']} · SKU:{s['sku'][:15]} · 到期:{s['expiry_date']}
                </div>
            </div>
            """, unsafe_allow_html=True)
        if len(expiring_samples) > 5:
            st.caption(f"... 还有 {len(expiring_samples) - 5} 个样品即将到期")
    else:
        st.success("✅ 未来30天内无样品到期")

# --- 维护提醒 ---
with col_w2:
    st.subheader("🔧 即将到期的维护 (30天)")
    if upcoming_maintenance:
        df_up = pd.DataFrame(upcoming_maintenance)
        for _, row in df_up.head(5).iterrows():
            days = (datetime.strptime(row['next_maintenance_date'], '%Y-%m-%d') - datetime.now()).days
            badge_class = 'danger' if days <= 7 else 'warn'
            st.markdown(f"""
            <div style="border:1px solid #eee; border-radius:8px; padding:10px; margin:4px 0;
                        {'border-left:4px solid #cf1322;' if days <= 7 else 'border-left:4px solid #faad14;'}">
                <span class="stat-badge {badge_class}">{days}天</span>
                <strong>{row['equipment_name'][:20]}</strong>
                <div style="font-size:12px; color:#888; margin-top:2px;">
                    {row['maintenance_type']} · 下次:{row['next_maintenance_date']}
                </div>
            </div>
            """, unsafe_allow_html=True)
        if len(upcoming_maintenance) > 5:
            st.caption(f"... 还有 {len(upcoming_maintenance) - 5} 项维护即将到期")
    else:
        st.success("✅ 未来30天内无计划维护")

# --- 活跃告警 ---
with col_w3:
    st.subheader("🔔 异常概览")
    alert_count = (sample_stats['expired'] + sample_stats['near_expiry'] +
                   (1 if upcoming_maintenance else 0))
    if alert_count > 0:
        items = []
        if sample_stats['expired'] > 0:
            items.append(f"🔴 **{sample_stats['expired']} 个样品已过期**")
        if sample_stats['near_expiry'] > 0:
            items.append(f"🟡 **{sample_stats['near_expiry']} 个样品即将过期**")
        if upcoming_maintenance:
            items.append(f"🟡 **{len(upcoming_maintenance)} 项设备维护即将到期**")
        for item in items:
            st.markdown(f"""
            <div style="border:1px solid #eee; border-radius:8px; padding:10px; margin:4px 0;
                        border-left:4px solid #ff4d4f;">
                {item}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ 系统运行正常，无异常告警")

# ==================== 第六行：当前使用中设备 ====================
st.markdown('<div class="section-title">🔬 当前使用中设备</div>', unsafe_allow_html=True)

if active_borrows:
    cols = st.columns(min(len(active_borrows), 4))
    for i, a in enumerate(active_borrows):
        with cols[i % 4]:
            time_str = ""
            if a.get('test_start_time') and a.get('test_end_time'):
                time_str = f" ⏰ {a['test_start_time']}→{a['test_end_time']}"
            standard_str = a.get('test_standard', '')
            if standard_str and len(standard_str) > 30:
                standard_str = standard_str[:30] + '...'

            st.markdown(f"""
            <div style="border:1px solid #1890ff; border-radius:10px; padding:12px;
                        background:linear-gradient(135deg, #e6f7ff, #f0f5ff); margin:4px 0;">
                <div style="font-size:18px; font-weight:bold; color:#003eb3;">
                    🔬 {a['equipment_name']}
                </div>
                <div style="font-size:12px; color:#666; margin-top:4px;">
                    <code>{a['serial_number']}</code>
                </div>
                <div style="font-size:13px; margin-top:6px; color:#555;">
                    👤 {a['user_name']}<br>
                    📦 {a.get('product_name') or a['purpose']}
                    {f"<br>🏷️ {a['brand']} / {a['sku']}" if a.get('brand') or a.get('sku') else ""}<br>
                    📅 {a['borrow_date']} → {a['expected_return_date']}{time_str}
                </div>
                <div style="font-size:11px; color:#999; margin-top:4px;">
                    📐 {standard_str}
                </div>
            </div>
            """, unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        if st.button("📋 查看使用详情", use_container_width=True, type="primary",
                     help="跳转到使用登记页面"):
            st.switch_page("_pages/lab_usage.py")
    with col_btn2:
        st.caption("点击按钮跳转至「使用登记」页面，查看占用详情。")
else:
    st.info("📭 当前无设备在使用中")

# ==================== 第七行：最近记录 ====================
st.markdown('<div class="section-title">📋 最近动态</div>', unsafe_allow_html=True)

col_r1, col_r2, col_r3 = st.columns(3)

# --- 最近使用记录 ---
with col_r1:
    st.subheader("🔬 最近使用记录")
    recent_borrows = get_recent_borrows(5)
    if recent_borrows:
        df_rb = pd.DataFrame(recent_borrows)
        df_rb['设备'] = df_rb['equipment_name']
        df_rb['使用人'] = df_rb['user_name']
        df_rb['日期'] = df_rb['borrow_date']
        df_rb['状态'] = df_rb['status']
        st.dataframe(
            df_rb[['设备', '使用人', '日期', '状态']],
            use_container_width=True, hide_index=True, height=220
        )
        if st.button("查看全部使用记录 →", key="btn_borrow"):
            st.switch_page("_pages/lab_usage.py")
    else:
        st.info("暂无使用记录")

# --- 最近检验报告 ---
with col_r2:
    st.subheader("📄 最近检验报告")
    recent_reports = get_recent_reports(5)
    if recent_reports:
        df_rr = pd.DataFrame(recent_reports)
        df_rr['类型'] = df_rr['report_type']
        df_rr['产品'] = df_rr['product_name']
        df_rr['检验员'] = df_rr['inspector']
        df_rr['状态'] = df_rr['status']
        st.dataframe(
            df_rr[['类型', '产品', '检验员', '状态']],
            use_container_width=True, hide_index=True, height=220
        )
        if st.button("查看全部报告 →", key="btn_report"):
            st.switch_page("_pages/qc_report.py")
    else:
        st.info("📭 暂无检验报告，上传报告后将在此显示")

# --- 最近变更记录 ---
with col_r3:
    st.subheader("📝 最近变更记录")
    recent_changes = get_recent_changes(5)
    if recent_changes:
        df_rc = pd.DataFrame(recent_changes)
        df_rc['BU'] = df_rc['bu']
        df_rc['变更内容'] = df_rc['change_reason'].apply(lambda x: x[:25] + '...' if len(str(x)) > 25 else str(x))
        df_rc['供应商'] = df_rc['supplier']
        st.dataframe(
            df_rc[['BU', '变更内容', '供应商']],
            use_container_width=True, hide_index=True, height=220
        )
        if st.button("查看全部变更 →", key="btn_change"):
            st.switch_page("_pages/qc_change.py")
    else:
        st.info("📭 暂无变更记录")

# ---- 底部 ----
st.markdown("---")
st.caption("💡 看板数据实时更新 ｜ 左侧导航分为五大板块：首页看板、实验室管理、品质管理、系统监控(开发版)、关于")
st.caption("© 2026 SainStore Inc. | Developed by Bruce Cheng 程强")
