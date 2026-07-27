#!/usr/bin/env python3
"""
保存 Windows 后台运行所需配置。
"""

from __future__ import annotations

import getpass

from windows_runtime import ensure_runtime_secrets, load_runtime_config, now_ts, save_runtime_config


def main() -> int:
    current = load_runtime_config()
    current_password = current.get("lan_access_password", "")

    print("品质系统后台启动配置")
    print("--------------------")
    if current_password:
        print("当前已存在访问密码配置。直接回车可保留原密码。")

    password = getpass.getpass("请输入同事访问密码: ").strip()
    if not password:
        if current_password:
            password = current_password
        else:
            print("访问密码不能为空。")
            return 1

    # 保留 NAS、钉钉等已由部署人员写入的运行凭据；此交互只更新局域网访问策略。
    next_config = dict(current)
    next_config.update(
        {
            "lan_access_password": password,
            "lan_allowed_domain": current.get("lan_allowed_domain", "sainstore.com"),
            "configured_at": now_ts(),
        }
    )
    config = save_runtime_config(next_config)

    config = ensure_runtime_secrets(config)
    print("")
    print("配置已保存。")
    print(f"允许域名: {config.get('lan_allowed_domain', 'sainstore.com')}")
    print("下一步建议：")
    print("1. 运行 install_windows_autostart.ps1 注册计划任务")
    print("2. 运行 start_windows_background.bat 先手动验证一次后台启动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
