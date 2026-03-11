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
- `session_id`（PK part）
- `workbench_summary`
- `is_flushing`
- `created_at`
- `updated_at`

主键：`(user_id, session_id)`

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
- `llm_max_tool_rounds`
- `context_total_token_limit`
- `updated_at`

## 2. 文件系统

用户目录：

`data/user/<user_id>/`

当前目录树：

```text
data/user/<user_id>/
├── employee/
│   └── 1/
│       ├── memory.md
│       ├── notebook/
│       │   ├── 素材库笔记.md
│       │   ├── 日程表.md
│       │   ├── 人格设定.md
│       │   └── 工作手册.md
│       ├── workspace/
│       └── skills/
├── brand_library/
└── skill_library/
```

结构语义：

- `employee/1`：当前运行态记忆主目录。
- `employee/1/memory.md`：压缩后的长期记忆主文件。
- `employee/1/notebook/*.md`：分类记忆笔记（素材库笔记、日程表、人格设定、工作手册）。
- `employee/1/workspace/`：初始为空；后续用于存放用户上传文件与从 `brand_library` 复制的素材。
- `employee/1/skills/`：初始为空；后续用于存放从 `skill_library` 复制的记忆文件。

接口可见记忆文件（`GET /memory/files`）来自 `employee/1`，逻辑文件名保持无路径形式：

- `memory.md`
- `人格设定.md`
- `日程表.md`
- `工作手册.md`
- `素材库笔记.md`

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

首次启动会自动：

1. 创建 `data/agent_state.db`
2. 初始化 `data/user/<user_id>/employee/1` 目录骨架
3. 补齐缺失的记忆模板文件（`employee/1`）

## 6. 兼容策略

当前版本不做旧目录与旧命名的自动迁移；历史数据需手动整理后再接入。
