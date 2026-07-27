"""
品质系统管理平台 - 关于系统
"""

import streamlit as st
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pages._utils import render_sidebar, render_topbar
from version import VERSION, BUILD_DATE, BUILD_TYPE

st.set_page_config(page_title="品质系统管理平台", page_icon=None, layout="wide")

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "logo.png")

# 渲染侧边栏导航
st.session_state.current_page = "关于系统"
with st.sidebar:
    render_sidebar()
render_topbar("关于系统")



st.markdown("""
<div class="qms-page-header"><div>
  <div class="qms-eyebrow">SYSTEM INFORMATION</div>
  <h1>关于系统</h1>
  <p>版本、运行环境与系统能力说明</p>
</div></div>
""", unsafe_allow_html=True)

# 运行环境真实版本（动态获取，避免硬编码失真）
PY_VER = sys.version.split()[0]
try:
    ST_VER = st.__version__
except Exception:
    ST_VER = "未知"

col1, col2 = st.columns([1, 2])

with col1:
    st.markdown('<div class="qms-card">', unsafe_allow_html=True)
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=200)
    st.markdown("---")
    st.markdown("### SainStore 品质系统管理平台")
    st.markdown("*Quality System Management Platform*")
    st.markdown(f"**{VERSION} ({BUILD_TYPE})**")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="qms-card">', unsafe_allow_html=True)
    st.markdown(f"""
    ## 📋 系统信息

    | 项目 | 详情 |
    |------|------|
    | **系统名称** | 品质管理系统开发 |
    | **版本号** | {VERSION} |
    | **版本构建** | {BUILD_TYPE} |
    | **构建日期** | {BUILD_DATE} |
    | **运行环境** | Python {PY_VER} |
    | **Streamlit** | {ST_VER} |
    | **数据库** | SQLite 3 |
    | **开发者** | **Bruce Cheng 程强** |
    | **版权归属** | © 2026 **SainStore Inc.** 保留所有权利 |
    | **技术栈** | Python + Streamlit + SQLite + ECharts / Plotly |
    """)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

col_a, col_b, col_c = st.columns(3)

with col_a:
    st.markdown("### 功能模块")
    st.markdown("""
  - 实验室设备管理
  - 设备使用登记
  - 设备借用归还
  - 维护保养记录
  - 检验报告管理
  - 样品签样管理
  - 产品变更管理
  - 数据统计分析
    """)

with col_b:
    st.markdown("### 项目规范")
    st.markdown("""
    - 数据安全等级：内部
    - 部署环境：本地服务器
    - 更新频率：按需迭代
    - 代码仓库：WorkBuddy Project
    - 数据库：SQLite 3
    - 依赖管理：pip + venv
    """)

with col_c:
    st.markdown("### 联系方式")
    st.markdown("""
    - **开发**: Bruce Cheng 程强
    - **归属**: SainStore Inc.
    - **用途**: 品质管理内部系统
    """)

st.markdown("---")
st.caption(f"© 2026 SainStore Inc. | {VERSION} | Developed by Bruce Cheng 程强")
