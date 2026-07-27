# 品质系统 · 新增功能板块架构约定（RULES）

> 本文件为项目级硬约束，所有新增功能板块必须遵守。由用户在 2026-07-26 明确要求。

## 一、技术选型规则

| 场景 | 实现方式 |
|------|----------|
| ① 预览 / 演示 | 单页 HTML（手写 CSS+JS，双击即开，不依赖框架） |
| ② 正式系统 · 普通模块 | **Streamlit**（复用现有 `pages/` 结构、`db/core.py` 数据层） |
| ③ 报告类 / 特殊交互 | **HTML 组件**（复杂报告、专用交互用 `components/` + HTML 渲染） |

## 二、所有模块共用的共享服务（统一规范，禁止各模块各写一套）

1. **CSS 设计规范** — 统一令牌在 `assets/tokens.css`（变量前缀 `--qs-*`），所有页面/组件引用同一套，保证视觉一致。
2. **权限** — 统一在 `main.py`（`auth.json` 白名单 + Google OAuth + cookie），新模块不单独做权限。
3. **保存** — 统一数据层 `db/core.py`（SQLite `data/lab_manager.db`），新模块在此建表 + CRUD，禁止另起存储。
4. **图片服务** — 统一图片上传/存储组件（抽自 `qc_report.py` 的 `UPLOAD_DIR`），新模块调用公共层，不写死在模块内。
5. **归档服务（软删/回收站）** — 删除走 `@recoverable("表名")` 装饰器，整行快照进 `deleted_records` 表，可在全局「误删找回」还原；禁止物理硬删业务数据。

## 三、新增普通模块（规则②）标准流程

1. 在 `db/core.py` 的 `init_db()` 建表（含 `created_at` 等通用字段）；
2. 写 CRUD + 统计函数（对齐 `page_samples.py` 现有范式）；
3. 在 `pages/` 新建 `page_xxx.py`，双 Tab / 表单 / 列表 / 图表复用 `pages/_utils.py` 的公共组件；
4. 在 `_pages/_utils.py` 的 `NAV_ITEMS`「品质日常管理」组追加，并在 `main.py` 注册；
5. 本地用 `实验室/venv`（Python 3.11）验证：建表、增删改查、统计、软删进回收站、导入导出。

## 四、已知现状（2026-07-26 核查）

- ✅ 权限、保存 已统一，新模块直接复用
- ✅ 归档/回收站（`deleted_records` + `@recoverable`）已存在
- ✅ CSS 设计令牌 `assets/tokens.css` 已存在
- ⚠️ 图片服务需从 `qc_report.py` 抽成 `_shared/image_service.py` 公共层
