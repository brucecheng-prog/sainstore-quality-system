"""
活动日志 - 系统监控页面（仅本地开发可见）
追踪：登录记录、页面访问、数据修改、在线用户
"""

import streamlit as st
import pandas as pd
from database import (
    get_activity_logs, get_online_users, get_login_history,
    get_daily_stats, get_page_hotspots, delete_activities
)
from datetime import datetime

st.set_page_config(page_title="活动日志", page_icon="📊", layout="wide")

st.title("📊 系统活动监控")

# ---- Tab 导航 ----
tab1, tab2, tab3, tab4 = st.tabs(["📋 实时日志", "👥 在线用户", "📈 访问统计", "🔥 热门页面"])

with tab1:
    st.subheader("实时活动日志")

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        category_filter = st.selectbox("类型", ["全部", "登录", "页面访问", "数据修改", "系统"], key="log_cat")
    with col_f2:
        hours_filter = st.selectbox("时间范围", [1, 6, 12, 24, 48, 168], format_func=lambda x: f"{x}小时", index=3)
    with col_f3:
        st.caption("")

    cat_map = {"登录": "login", "页面访问": "page_view", "数据修改": "data_edit", "系统": "system"}
    logs = get_activity_logs(
        limit=300,
        category=cat_map.get(category_filter, ''),
        hours=hours_filter
    )

    if logs:
        df = pd.DataFrame(logs)
        df['时间'] = df['created_at']
        df['用户'] = df['user_email'].apply(lambda x: x.split('@')[0] if '@' in x else x)

        # 操作图标映射
        action_icons = {
            '登录成功': '🔑', '退出登录': '🚪', '登录失败': '❌',
            '查看仪表盘': '📊', '查看使用登记': '📋', '查看借用归还': '📤',
            '查看设备台账': '🔧', '查看维护记录': '🔨', '查看检验报告': '📄',
            '查看样品管理': '📦', '查看变更管理': '📝', '查看活动日志': '📈',
        }

        st.dataframe(
            df[['时间', '用户', 'action', 'detail', 'page']].rename(
                columns={'action': '操作', 'detail': '详情', 'page': '页面'}
            ),
            use_container_width=True,
            hide_index=True,
            height=600,
            column_config={
                '时间': st.column_config.TextColumn(width='small'),
                '用户': st.column_config.TextColumn(width='small'),
                '操作': st.column_config.TextColumn(width='small'),
                '详情': st.column_config.TextColumn(width='medium'),
                '页面': st.column_config.TextColumn(width='medium'),
            }
        )

        # 批量删除
        with st.expander("🗑️ 批量删除日志", expanded=False):
            log_options = {r['id']: f"[{r['created_at']}] {r['user_name']} - {r['action']}" for r in logs}
            selected_logs = st.multiselect(
                "选择要删除的日志", options=list(log_options.keys()),
                format_func=lambda x: log_options[x]
            )
            if selected_logs and st.button("🗑️ 确认删除选中日志", type="primary"):
                ok, msg = delete_activities(selected_logs)
                if ok:
                    st.success(msg)
                    st.rerun()
    else:
        st.info("暂无活动记录")

with tab2:
    st.subheader("当前在线用户")
    online = get_online_users(minutes=15)
    if online:
        cols = st.columns(min(len(online), 4))
        for i, user in enumerate(online):
            with cols[i % 4]:
                minutes_ago = user.get('last_active', '')
                st.markdown(f"""
                <div style="border:1px solid #52c41a; border-radius:10px; padding:14px;
                            background:linear-gradient(135deg, #f6ffed, #f0fff0); margin:6px 0;">
                    <div style="font-size:16px; font-weight:bold; color:#389e0d;">
                        🟢 {user['user_name']}
                    </div>
                    <div style="font-size:11px; color:#666; margin-top:4px;">
                        📧 {user['user_email']}
                    </div>
                    <div style="font-size:12px; margin-top:6px; color:#555;">
                        📍 最近活跃: {minutes_ago}<br>
                        📊 操作次数: {user['action_count']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("当前无在线用户（15分钟内无活动）")

    st.markdown("---")
    st.subheader("最近登录记录")
    logins = get_login_history(limit=15)
    if logins:
        df_login = pd.DataFrame(logins)
        df_login['时间'] = df_login['created_at']
        df_login['用户'] = df_login['user_name']
        st.dataframe(
            df_login[['时间', '用户', 'user_email']].rename(
                columns={'user_email': '邮箱'}
            ),
            use_container_width=True, hide_index=True, height=280
        )

with tab3:
    st.subheader("7天访问趋势")
    stats = get_daily_stats()
    if stats:
        df_stats = pd.DataFrame(stats)
        cols = st.columns(4)
        cols[0].metric("7日独立用户", df_stats['unique_users'].sum())
        cols[1].metric("7日登录次数", df_stats['logins'].sum())
        cols[2].metric("7日页面浏览", df_stats['page_views'].sum())
        cols[3].metric("7日数据修改", df_stats['data_edits'].sum())

        # 折线图
        df_stats['日期'] = df_stats['day']
        st.line_chart(
            df_stats.set_index('日期')[['logins', 'page_views', 'data_edits', 'unique_users']],
            height=300, use_container_width=True
        )

        st.dataframe(
            df_stats[['日期', 'unique_users', 'logins', 'page_views', 'data_edits']].rename(
                columns={'unique_users': '独立用户', 'logins': '登录', 'page_views': '浏览', 'data_edits': '修改'}
            ),
            use_container_width=True, hide_index=True, height=250
        )
    else:
        st.info("暂无统计数据")

with tab4:
    st.subheader("最常访问的页面")
    hotspots = get_page_hotspots()
    if hotspots:
        df_hot = pd.DataFrame(hotspots)
        df_hot['页面名称'] = df_hot['page'].apply(lambda x: x or '首页')
        st.dataframe(
            df_hot[['页面名称', 'visit_count', 'unique_users']].rename(
                columns={'visit_count': '访问次数', 'unique_users': '访问人数'}
            ),
            use_container_width=True, hide_index=True, height=400
        )
    else:
        st.info("暂无页面访问数据")

st.caption(f"🕐 系统时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 仅本地开发环境可见")
