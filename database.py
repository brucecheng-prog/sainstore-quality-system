"""
实验室设备管理系统 - 数据库层（兼容门面 / facade）

实现已迁移至 db 包：核心代码位于 db/core.py。

本文件保留为门面，将 db.core 的全部命名（含下划线私有名）原样
镜像到 database 模块，确保既有调用方无需任何改动即可继续工作：
  - `from database import <name>`        （含 `_current_actor` 等私有名）继续可用
  - `import database as db`              （`db.<name>` 模块对象式访问）继续可用
  - `import database as database_module` 继续可用

后续如需按领域进一步拆分 db.core，可逐步将函数移入 db/ 下子模块，
本门面与所有调用方均不受影响。
"""
import sys

import db.core as _db_core

_module = sys.modules[__name__]
# 跳过模块自身的 dunder，其余（公有函数/变量、下划线私有名、顶层 import 的模块）
# 全部原样镜像，使 database 成为 db.core 的完全一致别名。
for _name in dir(_db_core):
    if _name in (
        "__name__", "__file__", "__doc__", "__package__",
        "__loader__", "__spec__", "__builtins__", "__cached__",
    ):
        continue
    setattr(_module, _name, getattr(_db_core, _name))
