# 接口参考文档

## 1. `GET /api/sessions`

返回 SQLite 中已存在的会话列表，按最近更新时间倒序排列。

### 响应示例

```json
{
  "sessions": [
    {
      "session_id": "session-20260307-160012-a1b2c3",
      "is_flushing": false,
      "created_at": "2026-03-07 16:00:12",
      "updated_at": "2026-03-07 16:10:45",
      "message_count": 12
    }
  ]
}
```

## 2. `POST /api/sessions`

创建新会话并写入 SQLite，会返回新会话信息。

### 请求体

```json
{
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
    "session_id": "session-20260307-160012-a1b2c3",
    "is_flushing": false,
    "created_at": "2026-03-07 16:00:12",
    "updated_at": "2026-03-07 16:00:12",
    "message_count": 0
  }
}
```

## 2.1 `GET /api/session-messages`

按时间顺序读取指定会话在 SQLite 中的历史消息，用于前端切换 session 后回放聊天记录。

### 查询参数

- `session_id`：会话 ID（必填）
- `limit`：最大返回条数（默认 `500`，范围 `1..5000`）

### 响应示例

```json
{
  "session_id": "session-20260307-160012-a1b2c3",
  "messages": [
    {
      "id": 1,
      "session_id": "session-20260307-160012-a1b2c3",
      "role": "user",
      "content": "你好",
      "zone": "dialogue",
      "created_at": "2026-03-07 16:00:20"
    },
    {
      "id": 2,
      "session_id": "session-20260307-160012-a1b2c3",
      "role": "assistant",
      "content": "你好，我在。",
      "zone": "dialogue",
      "created_at": "2026-03-07 16:00:22"
    }
  ]
}
```

## 3. `GET /api/settings`

读取全局设置（来源：SQLite `app_settings` 表）。

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

## 4. `PUT /api/settings`

更新全局设置并写入 SQLite。

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

说明：

1. `max_tool_rounds` 限制范围为 `1..20`。
2. `base_url` 为空时可传 `null`，后端会使用默认值。
3. `total_token_limit` 限制范围为 `20000..2000000`，默认 `200000`。

## 5. `POST /api/chat`

### 请求体

```json
{
  "message": "你好",
  "session_id": "default",
  "max_tool_rounds": 6,
  "llm_config": {
    "model": "agent-advoo",
    "api_key": "sk-...",
    "base_url": "http://model-gateway.test.api.dotai.internal/v1"
  }
}
```

### `llm_config.base_url` 填写建议

`base_url` 适用于 OpenAI 官方与 OpenAI 兼容服务，推荐格式如下：

1. OpenAI 官方：`https://api.openai.com/v1`
2. 兼容服务：`https://你的服务域名/v1`

后端会做以下兼容处理：

1. 如果传入 `https://.../v1/chat/completions`，会自动规范化到 `https://.../v1`。
2. 如果只传域名（如 `https://api.example.com`），会自动补成 `https://api.example.com/v1`。
3. 如果为空，则默认使用 `http://model-gateway.test.api.dotai.internal/v1`。

注意：

1. 必须使用完整的 `http://` 或 `https://` 地址。
2. `base_url` 的规则同样适用于 `POST /api/memory/flush` 中的 `llm_config`。

### 响应

- `Content-Type: text/event-stream`
- 事件类型：
  - `meta`
  - `tool_call`
  - `tool_result`
  - `assistant_final`
  - `memory_status`
  - `done`
  - `error`（异常时）

### `assistant_final` 示例

```json
{
  "content": "这是模型最终回答",
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200
  }
}
```

## 6. `GET /api/memory/status`

### 查询参数

- `session_id`（默认：`default`）
- `model`（默认：`agent-advoo`，用于选择 token 编码器）

### 响应示例

```json
{
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

## 7. `GET /api/memory/files`

### 响应示例

```json
{
  "files": [
    { "file_name": "人格记忆.md", "content": "..." },
    { "file_name": "系统提示词.md", "content": "..." }
  ]
}
```

## 8. `PUT /api/memory/files/{file_name}`

用于人工编辑记忆文件（包含 `系统提示词.md`）。

### 路径参数

- `file_name`：目标 `.md` 文件名

### 请求体

```json
{
  "content": "新的内容",
  "mode": "overwrite"
}
```

`mode` 可选值：

- `overwrite`：覆盖写入
- `append`：追加写入

### 响应示例

```json
{
  "ok": true,
  "file_name": "系统提示词.md",
  "content": "..."
}
```

## 8.1 `POST /api/memory/reset`

清空 `data/memory` 目录并使用后端内置初始内容全量覆盖重建。

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

## 9. `POST /api/memory/flush`

### 请求体

```json
{
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
  "session_id": "default",
  "is_flushing": true
}
```

## 错误码说明

- `400`：参数非法、文件名非法或权限策略不允许
- `404`：目标记忆文件不存在
- `500`：服务内部错误
