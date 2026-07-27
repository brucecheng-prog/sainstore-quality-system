#!/usr/bin/env python3
"""
自动版本记录脚本
每次代码优化完成后由 WorkBuddy 自动调用，记录版本变动并递增版本号

用法: python auto_changelog.py "更新标题" "变动明细" [类别]
"""
import sqlite3
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'lab_manager.db')
VER_PATH = os.path.join(BASE_DIR, 'version.py')


def get_current_version():
    """读取当前版本号"""
    with open(VER_PATH, 'r') as f:
        for line in f:
            if line.startswith('VERSION'):
                return line.split('=')[1].strip().strip('"')
    return 'v1.0.0'


def auto_changelog(title, changes, category='优化'):
    """自动记录版本变动"""
    current_ver = get_current_version()

    # 递增版本号 (小版本号+1)
    parts = current_ver.lstrip('v').split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    new_ver = 'v' + '.'.join(parts)

    # 更新 version.py
    today = datetime.now().strftime('%Y-%m-%d')
    with open(VER_PATH, 'w') as f:
        f.write(f'VERSION = "{new_ver}"\n')
        f.write(f'BUILD_DATE = "{today}"\n')
        f.write(f'BUILD_TYPE = "Windows 局域网生产版本"\n')

    # 写入数据库
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO changelog (version, title, description, changes, category, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (new_ver, title, changes[:120] if changes else title, changes, category, 'WorkBuddy AI')
    )
    conn.commit()
    conn.close()

    print(f'✅ 版本已自动记录: {current_ver} → {new_ver}')
    print(f'   标题: {title}')
    print(f'   类别: {category}')
    print(f'   时间: {today}')
    return new_ver


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('用法: python auto_changelog.py "标题" "变动明细" [类别]')
        print('示例: python auto_changelog.py "首页UI改版" "企业级卡片设计\\nKPI优化\\n预警横幅" "优化"')
        sys.exit(1)

    title = sys.argv[1]
    changes = sys.argv[2]
    category = sys.argv[3] if len(sys.argv) > 3 else '优化'

    auto_changelog(title, changes, category)
