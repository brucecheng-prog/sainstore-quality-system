"""一次性初始化数据库：确保全部表（含 operation_log 审计表）已创建。

设计要点：
- 必须在「服务停止、数据库无锁」时运行，才能可靠写入。
- 由 `一键安装看门狗.bat` 在停服后、起服前调用。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database


def main() -> int:
    try:
        database.init_db()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] init_db 失败: {repr(exc)}")
        return 1
    try:
        import sqlite3
        con = sqlite3.connect(database.DB_PATH)
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='operation_log'"
        )
        ok = bool(cur.fetchone())
        con.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] 校验失败: {repr(exc)}")
        return 1
    if ok:
        print("[OK] operation_log 审计表已确保存在")
        return 0
    print("[ERR] operation_log 表仍未创建")
    return 1


if __name__ == "__main__":
    sys.exit(main())
