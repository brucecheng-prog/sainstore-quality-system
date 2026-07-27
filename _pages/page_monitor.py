"""
活动日志 - 系统监控页面（仅本地开发可见）
追踪：登录记录、页面访问、数据修改、在线用户
"""

import streamlit as st
import pandas as pd
import os
import json
from pathlib import Path
import database as db
from database import (
    get_activity_logs, get_online_users, get_login_history,
    get_daily_stats, get_page_hotspots, delete_activities
)
from datetime import datetime
from config import BASE_DIR, DATA_DIR
from dingtalk_app_client import get_app_push_status
from nas_client import check_connection
from version import BUILD_DATE, VERSION

from pages._utils import render_sidebar, render_topbar, ui_table, ui_danger_button, ui_data_editor
from components.modal import confirm_dialog

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")

st.markdown("""
<div class="qms-page-header"><div>
  <div class="qms-eyebrow">SYSTEM HEALTH</div>
  <h1>系统活动监控</h1>
  <p>查看登录、页面访问、数据修改和在线用户状态</p>
</div></div>
""", unsafe_allow_html=True)
# 渲染侧边栏导航
st.session_state.current_page = "系统监控"
with st.sidebar:
    render_sidebar()
render_topbar("系统监控")

# F5：复用全站 is_admin 判定（与 main.py / page_reports.py 一致）
is_admin = st.session_state.get("is_admin", False)


@st.cache_data(ttl=30, show_spinner=False)
def _runtime_health_snapshot() -> dict:
    """只读运行状态；不回显路径、凭证或业务数据。"""
    snapshot = {
        "database_ok": False,
        "database_name": Path(str(getattr(db, "DB_PATH", ""))).name or "未识别",
        "nas_ok": False,
        "nas_message": "未检测",
        "dingtalk_configured": False,
        "environment": os.environ.get("QMS_ENVIRONMENT", "development"),
        "instance": os.environ.get("QMS_INSTANCE_NAME", "本机实例"),
        "port": os.environ.get("QMS_PORT", "8501"),
        "last_sync": "未发现同步记录",
        "last_system_event": "暂无系统事件",
    }

    try:
        conn = db.get_connection()
        conn.execute("SELECT 1")
        conn.close()
        snapshot["database_ok"] = True
    except Exception:
        pass

    try:
        snapshot["nas_ok"], snapshot["nas_message"] = check_connection()
    except Exception as exc:
        snapshot["nas_message"] = str(exc)

    try:
        snapshot["dingtalk_configured"] = bool(get_app_push_status(check_auth=False).get("configured"))
    except Exception:
        pass

    for sync_file in (Path(DATA_DIR) / "windows_sync_applied.json", Path(BASE_DIR) / ".last_mac_sync.json"):
        if not sync_file.exists():
            continue
        try:
            data = json.loads(sync_file.read_text(encoding="utf-8"))
            snapshot["last_sync"] = str(data.get("completed_at") or data.get("synced_at") or data.get("timestamp") or "已记录")
            break
        except (OSError, ValueError, TypeError):
            continue

    try:
        events = get_activity_logs(limit=1, category="system", hours=168)
        if events:
            latest = events[0]
            snapshot["last_system_event"] = f"{latest.get('created_at', '')} · {latest.get('action', '系统事件')}"
    except Exception:
        pass
    return snapshot


def _health_label(ok: bool, healthy: str, unhealthy: str) -> str:
    return f"🟢 {healthy}" if ok else f"🔴 {unhealthy}"


if is_admin:
    health = _runtime_health_snapshot()
    st.subheader("运行状态")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("运行实例", health["instance"])
    c1.caption(f"环境：{health['environment']}")
    c2.metric("版本", VERSION)
    c2.caption(f"构建：{BUILD_DATE} · 端口：{health['port']}")
    c3.metric("数据库", _health_label(health["database_ok"], "正常", "不可用"))
    c3.caption(health["database_name"])
    c4.metric("NAS / 钉钉", _health_label(health["nas_ok"], "NAS 正常", "NAS 异常"))
    c4.caption("钉钉已配置" if health["dingtalk_configured"] else "钉钉未配置")
    with st.expander("运行诊断详情", expanded=False):
        st.caption(f"最近代码同步：{health['last_sync']}")
        st.caption(f"NAS 检测：{health['nas_message']}")
        st.caption(f"最近系统事件：{health['last_system_event']}")




# 公网数据同步说明（历史功能，当前架构不需要）
st.info("""
 **系统架构说明**
- 当前部署架构：**Windows 局域网服务器**（内网 + 公网双网卡）
- 活动日志由服务器**直接记录、直接存储（直记直存）**，无需从外部系统同步
""")

# ---- Tab 导航 ----
tab1, tab2, tab3, tab4 = st.tabs(["实时日志", "在线用户", "访问统计", "热门页面"])

with tab1:
    st.subheader("实时活动日志")

    col_f1, col_f2 = st.columns([1, 1])
    with col_f1:
        category_filter = st.selectbox("类型", ["全部", "登录", "页面访问", "数据修改", "系统"], key="log_cat")
    with col_f2:
        hours_filter = st.selectbox("时间范围", [1, 6, 12, 24, 48, 168], format_func=lambda x: f"{x}小时", index=3)

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
            '登录成功': '', '退出登录': '', '登录失败': '',
            '查看仪表盘': '', '查看使用登记': '', '查看借用归还': '',
            '查看设备台账': '', '查看维护记录': '', '查看检验报告': '',
            '查看样品管理': '', '查看变更管理': '', '查看活动日志': '',
        }

        ui_table(
            df[['时间', '用户', 'action', 'detail', 'page']].rename(
                columns={'action': '操作', 'detail': '详情', 'page': '页面'}
            ),
            width="stretch",
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
        with st.expander("批量删除日志", expanded=False):
            log_options = {r['id']: f"[{r['created_at']}] {r['user_name']} - {r['action']}" for r in logs}
            selected_logs = st.multiselect(
                "选择要删除的日志", options=list(log_options.keys()),
                format_func=lambda x: log_options[x]
            )
            if not is_admin:
                st.warning("需要管理员权限才能删除日志")
            else:
                if selected_logs and ui_danger_button("确认删除选中日志", key="monitor_del_logs_btn", type="primary"):
                    confirm_dialog(
                        "确认删除日志",
                        f"确定要删除选中的 **{len(selected_logs)}** 条日志吗？此操作不可撤销。",
                        state_key="monitor_del_logs_confirm",
                        state_value=selected_logs,
                        confirm_label="确认删除",
                        confirm_type="primary",
                    )
            # 二次确认后执行删除
            if st.session_state.get("monitor_del_logs_confirm"):
                _del_ids = st.session_state.monitor_del_logs_confirm
                st.session_state.monitor_del_logs_confirm = None
                ok, msg = delete_activities(_del_ids)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
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
                <div style="border:1px solid var(--qs-success); border-radius:10px; padding:14px;
                            background:var(--qs-success-bg); margin:6px 0;">
                    <div style="font-size:16px; font-weight:bold; color:var(--qs-success-hover);">
             {user['user_name']}
                    </div>
                    <div style="font-size:11px; color:var(--qs-sub); margin-top:4px;">
             {user['user_email']}
                    </div>
                    <div style="font-size:12px; margin-top:6px; color:var(--qs-sub);">
             最近活跃: {minutes_ago}<br>
             操作次数: {user['action_count']}
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
        ui_table(
            df_login[['时间', '用户', 'user_email']].rename(
                columns={'user_email': '邮箱'}
            ),
            width="stretch", hide_index=True, height=280
        )

with tab3:
    st.subheader("7天访问趋势")
    stats = get_daily_stats()
    if stats:
        df_stats = pd.DataFrame(stats)
        # 响应式统计卡网格：4 → 2 → 1 列自动回流
        su = int(df_stats['unique_users'].sum())
        sl = int(df_stats['logins'].sum())
        sp = int(df_stats['page_views'].sum())
        sd = int(df_stats['data_edits'].sum())
        st.markdown(f"""
        <div class="stat-grid">
            <div class="stat-card"><div class="stat-label">7日独立用户</div><div class="stat-value">{su}</div></div>
            <div class="stat-card"><div class="stat-label">7日登录次数</div><div class="stat-value">{sl}</div></div>
            <div class="stat-card"><div class="stat-label">7日页面浏览</div><div class="stat-value">{sp}</div></div>
            <div class="stat-card"><div class="stat-label">7日数据修改</div><div class="stat-value">{sd}</div></div>
        </div>
        """, unsafe_allow_html=True)

        # 统一日期和数值类型，避免空值/全零数据触发前端坐标范围警告。
        df_stats['日期'] = pd.to_datetime(df_stats['day'], errors='coerce')
        chart_cols = ['logins', 'page_views', 'data_edits', 'unique_users']
        df_stats[chart_cols] = df_stats[chart_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
        chart_df = df_stats.dropna(subset=['日期']).sort_values('日期')
        if not chart_df.empty and float(chart_df[chart_cols].to_numpy().sum()) > 0:
            # 当前 Streamlit 版本的原生折线图对日期索引存在空范围告警，
            # 这里保留同一份排序后的趋势数据，使用表格保证监控页稳定。
            ui_table(
                chart_df.set_index('日期')[chart_cols].rename(columns={
                    'logins': '登录', 'page_views': '浏览',
                    'data_edits': '修改', 'unique_users': '独立用户'
                }),
                width="stretch",
                height=300,
            )
        else:
            st.info("暂无可绘制的访问趋势数据")

        ui_table(
            df_stats[['日期', 'unique_users', 'logins', 'page_views', 'data_edits']].rename(
                columns={'unique_users': '独立用户', 'logins': '登录', 'page_views': '浏览', 'data_edits': '修改'}
            ),
            width="stretch", hide_index=True, height=250
        )
    else:
        st.info("暂无统计数据")

with tab4:
    st.subheader("最常访问的页面")
    hotspots = get_page_hotspots()
    if hotspots:
        df_hot = pd.DataFrame(hotspots)
        df_hot['页面名称'] = df_hot['page'].apply(lambda x: x or '首页')
        ui_table(
            df_hot[['页面名称', 'visit_count', 'unique_users']].rename(
                columns={'visit_count': '访问次数', 'unique_users': '访问人数'}
            ),
            width="stretch", hide_index=True, height=400
        )
    else:
        st.info("暂无页面访问数据")

    # 系统时间（放在第4个 Tab 内部，避免在其他 Tab 泄露）
    st.caption(f"系统时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 仅本地开发环境可见")
