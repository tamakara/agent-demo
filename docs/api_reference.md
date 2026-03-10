# 接口参考文档（多用户版）

## 总则

1. `user_id` 是唯一用户标识，必填。  
2. 不做鉴权，后端按 `user_id` 直接隔离数据。  
3. 同名 `session_id` 可在不同用户下并存。  

`user_id` 规则：

- 允许：字母、数字、`.`、`_`、`-`
- 长度：1 到 64
- 必须以字母或数字开头

---

## 1. `GET /api/sessions`

按用户返回会话列表（最近更新时间倒序）。

### 查询参数

- `user_id`（必填）

### 响应示例

```json
{
  "sessions": [
    {
      "user_id": "alice",
      "session_id": "session-20260310-101530-a1b2c3",
      "is_flushing": false,
      "created_at": "2026-03-10 10:15:30",
      "updated_at": "2026-03-10 10:16:20",
      "message_count": 4
    }
  ]
}
```

---

## 2. `POST /api/sessions`

创建用户会话。

### 请求体

```json
{
  "user_id": "alice",
  "session_id": ""
}
```

说明：

1. `session_id` 可为空。
2. 为空时后端自动生成：`session-时间戳-随机后缀`。

### 响应示例

```json
{
  "created": true,
  "session": {
    "user_id": "alice",
    "session_id": "session-20260310-101530-a1b2c3",
    "is_flushing": false,
    "created_at": "2026-03-10 10:15:30",
    "updated_at": "2026-03-10 10:15:30",
    "message_count": 0
  }
}
```

---

## 3. `GET /api/session-messages`

按时间顺序读取某用户某会话历史消息。

### 查询参数

- `user_id`（必填）
- `session_id`（必填）
- `limit`（可选，默认 `500`，范围 `1..5000`）

### 响应示例

```json
{
  "user_id": "alice",
  "session_id": "session-20260310-101530-a1b2c3",
  "messages": [
    {
      "id": 1,
      "user_id": "alice",
      "session_id": "session-20260310-101530-a1b2c3",
      "role": "user",
      "content": "你好",
      "zone": "dialogue",
      "created_at": "2026-03-10 10:15:35"
    }
  ]
}
```

---

## 4. `GET /api/settings`

读取用户级 LLM 与上下文设置。

### 查询参数

- `user_id`（必填）

### 响应示例

```json
{
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "max_tool_rounds": 6,
  "total_token_limit": 200000
}
```

---

## 5. `PUT /api/settings`

更新用户级 LLM 与上下文设置。

### 查询参数

- `user_id`（必填）

### 请求体

```json
{
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "max_tool_rounds": 6,
  "total_token_limit": 200000
}
```

约束：

1. `max_tool_rounds` 范围 `1..20`
2. `total_token_limit` 范围 `20000..2000000`
3. `base_url` 传 `null` 时回退默认值

---

## 6. `POST /api/chat`

发起流式聊天（SSE）。

### 请求体

```json
{
  "user_id": "alice",
  "session_id": "session-20260310-101530-a1b2c3",
  "message": "帮我记录偏好：以后回答简洁一些",
  "max_tool_rounds": 6,
  "llm_config": {
    "model": "agent-advoo",
    "api_key": "sk-...",
    "base_url": "http://model-gateway.test.api.dotai.internal/v1"
  }
}
```

### 响应

- `Content-Type: text/event-stream`
- 事件类型：`meta` / `tool_call` / `tool_result` / `assistant_final` / `memory_status` / `done` / `error`

首个 `meta` 事件包含 `user_id` 和 `session_id`。

---

## 7. `GET /api/memory/status`

读取用户会话上下文窗口状态。

### 查询参数

- `user_id`（必填）
- `session_id`（可选，默认 `default`）
- `model`（可选，默认 `agent-advoo`）

### 响应示例

```json
{
  "user_id": "alice",
  "session_id": "default",
  "total_tokens": 25312,
  "resident_tokens": 11442,
  "dialogue_tokens": 13455,
  "buffer_tokens": 415,
  "is_flushing": false,
  "thresholds": {
    "system_prompt_limit": 20000,
    "summary_limit": 2000,
    "recent_raw_limit": 18000,
    "recent_total_limit": 20000,
    "resident_limit": 40000,
    "dialogue_limit": 160000,
    "total_limit": 200000,
    "flush_trigger": 200000
  }
}
```

---

## 8. `GET /api/memory/files`

读取用户记忆文件列表与内容。

### 查询参数

- `user_id`（必填）

### 响应示例

```json
{
  "files": [
    { "file_name": "人格记忆.md", "content": "..." },
    { "file_name": "系统提示词.md", "content": "..." }
  ]
}
```

---

## 9. `PUT /api/memory/files/{file_name}`

人工编辑用户记忆文件（包含 `系统提示词.md`）。

### 查询参数

- `user_id`（必填）

### 请求体

```json
{
  "content": "新的内容",
  "mode": "overwrite"
}
```

`mode` 可选值：`overwrite` / `append`

---

## 10. `POST /api/memory/reset`

重置用户记忆目录（清空后按模板重建）。

### 查询参数

- `user_id`（必填）

### 响应示例

```json
{
  "ok": true,
  "restored_files": ["系统提示词.md", "通用记忆.md"],
  "files": [
    { "file_name": "系统提示词.md", "content": "..." },
    { "file_name": "通用记忆.md", "content": "..." }
  ]
}
```

---

## 11. `POST /api/memory/flush`

手动触发用户会话刷盘。

### 请求体

```json
{
  "user_id": "alice",
  "session_id": "default",
  "max_tool_rounds": 6,
  "llm_config": {
    "model": "agent-advoo",
    "api_key": "sk-...",
    "base_url": "http://model-gateway.test.api.dotai.internal/v1"
  }
}
```

### 响应示例

```json
{
  "accepted": true,
  "user_id": "alice",
  "session_id": "default",
  "is_flushing": true
}
```

---

## 错误码

- `400`：参数非法（例如 `user_id` / 文件名非法）
- `404`：目标记忆文件不存在
- `500`：服务内部错误
