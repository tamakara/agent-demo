# 数据模型与持久化

## 本文范围

本文只描述数据落盘：

- SQLite 表结构
- 文件系统目录结构
- 关键字段语义

## 1. SQLite

默认路径：`data/agent_state.db`

### 1.1 `sessions`

字段：

- `user_id`（PK part）
- `session_id`（PK part，格式 `employee-{employee_id}`）
- `workbench_summary`
- `is_flushing`
- `created_at`
- `updated_at`

主键：`(user_id, session_id)`

说明：

- 当前版本将 `session_id` 作为数字员工的绑定会话 ID。
- 例如：员工 `1` -> `session_id=employee-1`。

### 1.2 `messages`

字段：

- `id`
- `user_id`
- `session_id`
- `role`
- `content`
- `zone`
- `token_count`
- `created_at`

外键：`(user_id, session_id) -> sessions`

### 1.3 `app_settings`

字段：

- `user_id`（PK）
- `llm_model`
- `llm_api_key`
- `llm_base_url`
- `llm_max_tool_rounds`（固定为 `64`，不再在 UI 配置）
- `context_total_token_limit`
- `tokenizer_model`（默认 `kimi-k2.5`）
- `updated_at`

## 2. 文件系统

用户目录：

`data/user/<user_id>/`

目录树（示例：两个员工）：

```text
data/user/<user_id>/
├── employee/
│   ├── 1/
│   │   ├── memory.md
│   │   ├── notebook/
│   │   │   ├── file.md
│   │   │   ├── schedule.md
│   │   │   ├── soul.md
│   │   │   └── workbook.md
│   │   ├── workspace/
│   │   └── skills/
│   └── 2/
│       ├── memory.md
│       ├── notebook/
│       ├── workspace/
│       └── skills/
├── brand_library/
└── skill_library/
```

结构语义：

- `employee/<employee_id>`：单个数字员工的数据根目录。
- `employee/<employee_id>/memory.md`：该员工的压缩长期记忆主文件。
- `employee/<employee_id>/notebook/*.md`：该员工的分类记忆笔记。
- `employee/<employee_id>/workspace/`：员工工作空间目录。
- `employee/<employee_id>/skills/`：员工技能文件目录。

接口可见记忆文件（`GET /memory/files`）按用户维度聚合，返回所有员工目录下的记忆文件：

- `employee/1/memory.md`
- `employee/1/notebook/soul.md`
- `employee/2/memory.md`
- `employee/2/notebook/schedule.md`

## 3. 分区语义（messages.zone）

- `dialogue`：常规对话区
- `tool`：工具事件区
- `buffer`：刷盘期间缓冲区
- `resident_recent`：刷盘后保留的最近对话

## 4. token 预算字段

预算由 `context_total_token_limit` 推导：

- system prompt + memory：10%
- summary：1%
- recent raw：9%
- dialogue/tool/buffer：其余预算

## 5. 数据初始化

首次访问某个 `user_id` 时会自动：

1. 创建 `data/agent_state.db`（若不存在）
2. 创建默认员工 `employee/1` 并绑定 `session_id=employee-1`
3. 初始化 `employee/1` 目录骨架与记忆模板文件

创建新员工时会自动初始化对应 `employee/<employee_id>` 目录与模板文件。

## 6. 兼容策略

当前版本不做旧会话 ID 到员工模型的自动迁移；历史数据需手动整理后再接入。
