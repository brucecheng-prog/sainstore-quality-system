# -*- coding: utf-8 -*-
"""
在线 QC 报告组件包装器 v3。

目的：
- 彻底绕开旧版 `_online_report_component.py` 及其历史 pyc 缓存；
- 强制使用 `_components/online_report_v2` 这份新模板；
- 组件名改为 `online_report_v3`，避免浏览器/Streamlit 继续复用旧 iframe 资源。
"""

import os
from streamlit.components.v1 import declare_component

_HERE = os.path.dirname(os.path.abspath(__file__))
_component = declare_component(
    "online_report_v3",
    path=os.path.join(_HERE, "_components", "online_report_v2"),
)


def render_online_report(data=None, mode="edit", key="online_report", height=None, photo=None, locked=False, report_id=None, report_no=None):
    args = {"data": data, "mode": mode, "locked": bool(locked)}
    if photo:
        args["photo"] = photo
    if report_id is not None:
        args["report_id"] = report_id
    if report_no:
        args["report_no"] = report_no
    default = {"type": None, "data": None}
    if height is not None:
        return _component(key=key, args=args, default=default, height=height)
    return _component(key=key, args=args, default=default)
