# Token 计算与刷盘机制（两层消息模型）

## 本文范围

本文回答：

- 员工会话窗口预算如何切分
- `messages` 的两层语义（生命周期分区 + 消息类型）
- `/chat/stream` 调用时 token 如何计数与裁剪
- 刷盘期间与刷盘完成后的消息迁移规则

本文不覆盖：

- 接口字段定义（见 `api_reference.md`）
- SSE 协议细节（见 `sse_protocol.md`）

## 1. 两套口径

项目同时保留两条 token 口径：

1. 本地记账 token（用于预算、裁剪、刷盘触发）
2. 模型 `usage`（用于观测，不参与预算决策）

关键点：

- 触发刷盘、前端状态面板、窗口裁剪均基于“本地记账 token”。
- `assistant_final.usage` 不参与 `memory_status.total_tokens` 计算。

## 2. 会话预算（固定 100%）

`domain/window_policy.py` 采用固定比例：

- `system_prompt_limit` = `10%`
- `summary_limit` = `1%`
- `recent_raw_limit` = `9%`
- `recent_total_limit` = `summary + recent_raw`（10%）
- `resident_limit` = `system + recent_total`（20%）
- `dialogue_limit` = `total - resident_limit`（80%）
- `flush_trigger` = `total_limit`

另外：

- `buffer_limit = dialogue_limit`
- `buffer` 不属于固定 100%，仅在刷盘期间临时启用

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

## 3. 两层消息模型

### 3.1 生命周期分区（`zone`）

- `dialogue`：主对话区
- `buffer`：刷盘期间新增消息区
- `resident_recent`：刷盘后保留的近期连续对话

### 3.2 消息类型（`message_kind`）

- `chat`：普通 user/assistant 消息
- `tool_call`：工具调用事件
- `tool_result`：工具结果事件

设计要点：

- `zone` 只表示“消息处于哪个生命周期阶段”。
- 工具事件不再占用独立 `zone`，而是通过 `message_kind` 区分。

## 4. 单次聊天调用计数流程

1. 写入用户消息：
- 非刷盘：写入 `zone=dialogue, message_kind=chat`
- 刷盘中：写入 `zone=buffer, message_kind=chat`（先检查 `buffer_limit`）

2. 组装 LLM 输入：
- `resident_recent` 按 `recent_raw_limit` 裁剪
- active 消息从 `zone in {dialogue, buffer}` 读取并按 `dialogue_limit` 裁剪
- active 内通过 `message_kind` 将工具事件恢复为 OpenAI `tool_calls` / `tool` 协议消息

3. 工具事件持久化：
- `tool_call -> message_kind=tool_call`
- `tool_result -> message_kind=tool_result`
- 生命周期分区跟随当前会话状态（`dialogue` 或 `buffer`）

4. 写入最终 assistant 文本：
- `message_kind=chat`
- 分区同上（`dialogue` 或 `buffer`）

5. 汇总状态：

```text
resident_tokens = resident_static_tokens + resident_recent_tokens
dialogue_tokens = SUM(zone='dialogue')
buffer_tokens   = SUM(zone='buffer')
total_tokens    = resident_tokens + dialogue_tokens + buffer_tokens
```

6. 自动刷盘触发：

- 仅当 `is_flushing=false` 且 `total_tokens >= flush_trigger` 时标记刷盘。

## 5. 刷盘生命周期

### 5.1 刷盘期间

- 旧 `dialogue` 保持不变（作为归档对象）
- 新增消息进入 `buffer`
- LLM 调用时上下文来自 `dialogue + buffer`（仍受 `dialogue_limit` 裁剪）
- 若 `buffer` 超过 `buffer_limit`，拒绝新消息

### 5.2 刷盘完成（当前实现）

1. 读取旧 `dialogue`，生成归档摘要并回写长期记忆
2. 从旧 `dialogue` 摘取近期 `chat` 消息，回填 `resident_recent`
3. 收集 `buffer` 全量消息
4. 清空会话消息
5. 将 `buffer` 消息迁移到新的 `dialogue`
6. 更新摘要并设置 `is_flushing=false`

效果：

- 旧 `dialogue` 被归档并摘取到 `resident_recent`
- 刷盘期间新增内容（原 `buffer`）成为新的主对话区

## 6. 快速排障

当 token 行为不符合预期时，建议顺序检查：

1. `app_settings.context_total_token_limit`
2. `memory_status.thresholds`
3. `messages` 中 `zone/message_kind/token_count` 分布
4. `is_flushing` 状态与 `buffer` 是否超过上限

SQL 示例：

```sql
SELECT zone, message_kind, COALESCE(SUM(token_count), 0) AS total_tokens
FROM messages
WHERE user_id = ? AND session_id = ?
GROUP BY zone, message_kind;
```
