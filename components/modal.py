"""
通用二次确认弹窗组件
基于 Streamlit st.dialog，用于替代页内警告条式的删除确认，
避免误触且视觉层级更清晰。
"""

import streamlit as st


def confirm_dialog(
    title: str,
    message: str,
    state_key: str,
    state_value=True,
    cancel_label: str = "取消",
    confirm_label: str = "确认",
    confirm_type: str = "primary",
):
    """
    打开一个二次确认弹窗。

    参数：
    - title: 弹窗标题
    - message: 弹窗正文
    - state_key: 用于记录确认结果的 session_state 键名
    - state_value: 点击确认时写入 session_state[state_key] 的值（通常是记录 ID）
    - cancel_label / confirm_label: 两个按钮的文案
    - confirm_type: 确认按钮样式，默认 primary（删除/不可逆操作保持醒目）

    调用方在弹窗关闭后检查：
        if st.session_state.get(state_key):
            # 执行实际操作
            st.session_state[state_key] = None  # 重置
    """

    @st.dialog(title)
    def _dialog():
        st.write(message)
        c1, c2 = st.columns(2)
        with c1:
            if st.button(cancel_label, key=f"{state_key}_cancel", use_container_width=True):
                st.session_state[state_key] = False
                st.rerun()
        with c2:
            if st.button(
                confirm_label,
                key=f"{state_key}_confirm",
                type=confirm_type,
                use_container_width=True,
            ):
                st.session_state[state_key] = state_value
                st.rerun()

    _dialog()
