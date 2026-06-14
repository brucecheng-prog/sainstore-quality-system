"""
系统版本变动日志 - 记录每次优化和修改（仅本地开发可见）
"""

import streamlit as st
import pandas as pd
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from version import VERSION, BUILD_DATE, BUILD_TYPE
from database import init_db, get_changelogs, add_changelog

st.set_page_config(page_title="版本变动", page_icon="📝", layout="wide")

st.title("📝 系统版本变动日志")

# 版本号（统一来自 version.py）
st.caption(f"当前版本: **{VERSION}** ({BUILD_TYPE}) | 构建日期: {BUILD_DATE} | 开发者: Bruce Cheng (程强)")
st.caption("📏 版本规则: X.Y.Z → 大版本(架构变更)·小版本(功能优化)·修订(Bug修复)")

st.markdown("---")

# 显示变动记录
logs = get_changelogs()
if logs:
    for entry in logs:
        with st.expander(f"📌 {entry['version']} - {entry['title']} | {entry['created_at'][:10] if entry.get('created_at') else ''}"):
            st.markdown(f"**类别**: {entry.get('category', '优化')}")
            st.markdown(f"**描述**: {entry.get('description', '')}")
            if entry.get('changes'):
                st.markdown("**变动明细**:")
                for change in entry['changes'].split('\n'):
                    if change.strip():
                        st.markdown(f"- {change.strip()}")
            st.caption(f"记录时间: {entry.get('created_at', '')}")
else:
    st.info("暂无版本变动记录。首次初始化中...")

st.markdown("---")

# 手动添加变动记录（仅开发者）
with st.expander("➕ 新增版本记录", expanded=not logs):
    with st.form("changelog_form"):
        col1, col2 = st.columns([1, 2])
        with col1:
            ver = st.text_input("版本号", value=VERSION)
            cat = st.selectbox("类别", ["优化", "修复", "新增", "重构", "安全"])
        with col2:
            title = st.text_input("标题", placeholder="本次更新概述")
            desc = st.text_area("描述")
        changes = st.text_area("变动明细（一行一条）", placeholder="修改使用人员下拉框格式\n品牌改为下拉选项\n...")
        created_by = st.text_input("操作人", value="Bruce Cheng")

        if st.form_submit_button("💾 保存变动记录", type="primary"):
            if title:
                add_changelog(ver, title, desc, changes, cat, created_by)
                st.success("已保存!")
                st.rerun()
            else:
                st.error("标题不能为空")

# 自动初始化本次变动（仅当表为空时）
if not logs:
    add_changelog(
        VERSION,
        "系统全面优化 - 用户反馈修复",
        "根据实际使用反馈进行多项界面和数据优化",
        "\n".join([
            "使用登记：使用人员下拉框只显示名字，去掉部门括号",
            "使用登记：产品品牌改为下拉选项，来源为原始品牌名单",
            "借用归还：借用人下拉框只显示名字，去掉部门括号",
            "设备台账：页码移到表格上方显示",
            "维护记录：修复取消按钮无效问题",
            "维护记录：新增勾选删除/编辑功能",
            "检验报告：检验员改为品质人员下拉选择",
            "检验报告：BG去重优化（Kronos去重）",
            "检验报告：新增供应商字段",
            "数据看板：专业级数据展示设计",
            "系统监控：新增勾选框删除日志功能",
            "系统监控：新增版本变动日志页",
        ]),
        "优化",
        "Bruce Cheng"
    )
    st.rerun()
