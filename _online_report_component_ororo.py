# -*- coding: utf-8 -*-
"""Ororo 专用在线检验报告组件。

此组件只承载 Ororo 的横向 A4 模板；保存、审核、图片和权限仍复用
在线报告主流程，避免影响通用模板。
"""

import os

from streamlit.components.v1 import declare_component

_HERE = os.path.dirname(os.path.abspath(__file__))
_component = declare_component(
    "online_report_ororo_v1",
    path=os.path.join(_HERE, "_components", "online_report_ororo"),
)


def render_online_report_ororo(
    data=None,
    mode="edit",
    key="online_report_ororo",
    height=None,
    photo=None,
    locked=False,
    report_id=None,
    report_no=None,
):
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
