# 会话状态、持久化与 Token 预算

## 1. 文档目标

本文档统一描述运行时状态与落盘规则，覆盖：

- SQLite 与文件系统持久化模型
- 会话消息两层语义（`zone` + `message_kind`）
- 窗口预算与 token 计算口径
- 刷盘状态机与消息迁移

## 2. 持久化模型

### 2.1 SQLite

默认路径：`data/agent_state.db`

#### `sessions`

- 主键：`(user_id, session_id)`
- 关键字段：`workbench_summary`、`is_flushing`、`created_at`、`updated_at`
- 约定：`session_id` 格式为 `employee-{employee_id}`

#### `messages`

- 字段：`id`、`user_id`、`session_id`、`role`、`message_kind`、`content`、`zone`、`token_count`、`created_at`
- 外键：`(user_id, session_id) -> sessions`

#### `app_settings`

- 主键：`user_id`
- 关键字段：`llm_model`、`llm_api_key`、`llm_base_url`、`context_total_token_limit`、`tokenizer_model`
- `llm_max_tool_rounds` 固定为 `64`

### 2.2 文件系统

用户根目录：`data/user/<user_id>/`

目录结构示意：

```text
data/user/<user_id>/
├── employee/
│   ├── <employee_id>/
│   │   ├── memory.md
│   │   ├── notebook/
│   │   │   ├── file.md
│   │   │   ├── schedule.md
│   │   │   ├── soul.md
│   │   │   └── workbook.md
│   │   ├── workspace/
│   │   └── skills/
├── brand_library/
└── skill_library/
```

语义：

- `memory.md`：压缩长期记忆主文件
- `notebook/*.md`：分类记忆文件
- `workspace/`：员工工作区
- `brand_library/`：用户品牌素材库

## 3. 两层消息模型

### 3.1 生命周期分区（`zone`）

- `dialogue`：主对话区
- `buffer`：刷盘期间新增消息缓冲区
- `resident_recent`：刷盘后保留的近期连续对话

### 3.2 消息类型（`message_kind`）

- `chat`：普通 user/assistant 文本
- `tool_call`：工具调用事件
- `tool_result`：工具结果事件

约束：

1. `zone` 只表示生命周期位置。
2. `message_kind` 只表示消息类别。
3. 工具消息不占独立 `zone`，由 `message_kind` 区分。

## 4. Token 口径与预算

### 4.1 两套口径

1. 本地记账 token：用于预算、裁剪、刷盘触发（决策口径）。
2. 模型 `usage`：用于观测，不参与预算决策。

### 4.2 固定窗口预算

基于 `context_total_token_limit`（且最小归一化为 `20000`）：

- `system_prompt_limit` = 10%
- `summary_limit` = 1%
- `recent_raw_limit` = 9%
- `dialogue_limit` = 剩余 80%
- `buffer_limit` = `dialogue_limit`（仅刷盘期间启用）
- `flush_trigger` = `total_limit`

公式：

```text
normalized_total = max(20000, total_token_limit)
system_prompt_limit = floor(normalized_total * 10%)
summary_limit       = floor(normalized_total * 1%)
recent_raw_limit    = floor(normalized_total * 9%)
resident_limit      = system_prompt_limit + summary_limit + recent_raw_limit
dialogue_limit      = normalized_total - resident_limit
buffer_limit        = dialogue_limit
flush_trigger       = normalized_total
```

### 4.3 单次聊天计数摘要

1. 写入用户消息到 `dialogue` 或 `buffer`（取决于 `is_flushing`）。
2. 组装输入时：
   - `resident_recent` 按 `recent_raw_limit` 裁剪
   - active 消息从 `dialogue + buffer` 读取并按 `dialogue_limit` 裁剪
3. 工具事件按 `tool_call/tool_result` 持久化并参与 active 区计数。
4. 汇总：

```text
resident_tokens = resident_static_tokens + resident_recent_tokens
dialogue_tokens = SUM(zone='dialogue')
buffer_tokens   = SUM(zone='buffer')
total_tokens    = resident_tokens + dialogue_tokens + buffer_tokens
```

## 5. 刷盘状态机

状态转移：

- Idle -> Flushing：`total_tokens >= flush_trigger`
- Flushing -> Idle：刷盘任务完成

刷盘期间规则：

1. 旧 `dialogue` 保持不变，作为归档对象。
2. 新增消息进入 `buffer`。
3. LLM 上下文来自 `dialogue + buffer`（受 `dialogue_limit` 限制）。
4. `buffer > buffer_limit` 时拒绝新消息。

刷盘完成顺序：

1. 归档旧 `dialogue` 并更新长期记忆。
2. 从旧 `dialogue` 抽取近期 `chat` 写入 `resident_recent`。
3. 收集 `buffer` 消息。
4. 清空会话消息。
5. 将 `buffer` 迁移为新的 `dialogue`。
6. 设置 `is_flushing=false`。

## 6. 多租户隔离要点

1. `user_id` 是所有状态与数据的租户键。
2. 隔离对象：`sessions/messages/app_settings` + 文件目录。
3. 会话锁按 `(user_id, session_id)` 分片，跨用户不互锁。

`user_id` 校验规则：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`

## 7. 快速排障

当 token/刷盘行为异常，建议按顺序检查：

1. `app_settings.context_total_token_limit`
2. `memory_status.thresholds`
3. `messages` 的 `zone/message_kind/token_count` 分布
4. `sessions.is_flushing` 与 `buffer` 增长情况

SQL 示例：

```sql
SELECT zone, message_kind, COALESCE(SUM(token_count), 0) AS total_tokens
FROM messages
WHERE user_id = ? AND session_id = ?
GROUP BY zone, message_kind;
```
