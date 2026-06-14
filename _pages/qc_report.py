"""
品质系统管理 - 检验报告上传
"""

import streamlit as st
import pandas as pd
import os
from datetime import date, datetime
from database import (
    init_db, add_inspection_report, get_inspection_reports,
    get_report_daily_stats, get_bg_list, get_bu_list, get_brand_list, get_quality_users_list
)

st.set_page_config(page_title="检验报告", page_icon="📄", layout="wide")
init_db()

st.title("📄 检验报告管理")

tab1, tab2, tab3 = st.tabs(["📤 上传报告", "📋 报告列表", "📊 每日统计"])

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "reports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
IMAGE_DIR = os.path.join(UPLOAD_DIR, "images")
os.makedirs(IMAGE_DIR, exist_ok=True)

# ==================== Tab 1: 上传 ====================
with tab1:
    st.subheader("📤 上传检验报告")
    st.caption("支持 PDF、Word 文件及图片上传。提交后将自动推送至主管审核。")

    bg_list = get_bg_list()
    bu_list = get_bu_list()
    brand_list = get_brand_list()
    quality_users = get_quality_users_list()

    with st.form("report_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            inspector = st.selectbox("检验员 *",
                    options=quality_users if quality_users else [""],
                    format_func=lambda x: x)
            bg = st.selectbox("BG", [""] + bg_list)
        with col2:
            report_type = st.selectbox("报告类型", ["来料检验", "过程检验", "出货检验", "可靠性测试", "其他"])
            bu = st.selectbox("BU", [""] + bu_list)

        col1, col2 = st.columns(2)
        with col1:
            brand = st.selectbox("品牌", [""] + brand_list)
        with col2:
            sku = st.text_input("SKU", placeholder="例如：101-63-KK-RC")

        product_name = st.text_input("产品名称 *", placeholder="检验产品名称")

        col_sup, col_empty = st.columns(2)
        with col_sup:
            supplier = st.text_input("供应商", placeholder="例如：深圳XX电子有限公司")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            report_file = st.file_uploader("上传报告文件", type=["pdf", "docx", "doc"],
                                           help="支持 PDF/Word 格式")
        with col_f2:
            images = st.file_uploader("上传检验图片", type=["png", "jpg", "jpeg"],
                                      accept_multiple_files=True, help="可多选图片")

        notes = st.text_area("备注说明")

        submitted = st.form_submit_button("✅ 提交报告", type="primary", use_container_width=True)

    if submitted:
        if not inspector or not product_name:
            st.error("检验员和产品名称不能为空！")
        else:
            # 保存文件
            filename = ""
            file_path = ""
            if report_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{report_file.name}"
                file_path = os.path.join(UPLOAD_DIR, filename)
                with open(file_path, "wb") as f:
                    f.write(report_file.getbuffer())

            # 保存图片
            image_paths = []
            if images:
                for img in images:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    img_name = f"{timestamp}_{img.name}"
                    img_path = os.path.join(IMAGE_DIR, img_name)
                    with open(img_path, "wb") as f:
                        f.write(img.getbuffer())
                    image_paths.append(img_path)

            ok, msg = add_inspection_report({
                'report_type': report_type,
                'inspector': inspector,
                'product_name': product_name,
                'bg': bg, 'bu': bu, 'brand': brand, 'sku': sku,
                'supplier': supplier,
                'filename': filename,
                'file_path': file_path,
                'image_paths': '|'.join(image_paths),
                'status': '待审核',
                'reviewer': 'teddy.li黎晓锋'
            })
            if ok:
                st.success(f"✅ {msg}！将推送至主管 teddy.li黎晓锋 审核。")
                st.rerun()
            else:
                st.error(msg)

# ==================== Tab 2: 报告列表 ====================
with tab2:
    st.subheader("📋 检验报告列表")

    col_f1, _ = st.columns([1, 2])
    with col_f1:
        filter_status = st.selectbox("状态筛选", ["全部", "待审核", "已通过", "已驳回"], key='report_status')

    st_filter = filter_status if filter_status != "全部" else None
    reports, total = get_inspection_reports(status=st_filter, per_page=50)

    st.markdown(f"共 **{total}** 份报告")

    if reports:
        df = pd.DataFrame(reports)
        cols = ['report_type', 'inspector', 'product_name', 'brand', 'sku',
                'filename', 'status', 'reviewer', 'created_at']
        df_d = df[[c for c in cols if c in df.columns]].copy()
        rename = {'report_type': '报告类型', 'inspector': '检验员', 'product_name': '产品名称',
                  'brand': '品牌', 'sku': 'SKU', 'filename': '文件',
                  'status': '状态', 'reviewer': '审核人', 'created_at': '提交时间'}
        df_d.rename(columns={k: v for k, v in rename.items() if k in df_d.columns}, inplace=True)

        def color_status(val):
            c = {'待审核': 'background-color: #fff3cd', '已通过': 'background-color: #d4edda',
                 '已驳回': 'background-color: #f8d7da'}
            return c.get(val, '')
        styled = df_d.style.map(color_status, subset=['状态'])
        st.dataframe(styled, use_container_width=True, hide_index=True, height=500)
    else:
        st.info("暂无报告")

# ==================== Tab 3: 每日统计 ====================
with tab3:
    st.subheader("📊 每日报告统计")
    stats = get_report_daily_stats()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("今日提交", stats['total'])
    with col2:
        st.metric("待审核", stats['pending'])
    with col3:
        st.metric("已通过", stats['approved'])

    st.caption(f"🕐 {date.today()} 统计数据")
