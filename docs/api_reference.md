# HTTP API 参考

## 本文范围

本文仅覆盖 HTTP 接口：

- 路径
- 参数
- 请求体
- 响应字段
- 错误格式

SSE 事件协议请看 `sse_protocol.md`。

## 1. 全局规则

1. 路由无前缀（不使用 `/api`、`/v1`）
2. 查询接口使用 `query user_id`
3. 写接口优先使用 `body user_id`
4. `PUT /memory/files/{file_name}` 与 `POST /memory/reset` 使用 `query user_id`

`user_id` 校验：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`

## 2. 统一响应

### 2.1 成功

```json
{
  "request_id": "...",
  "ts": "2026-03-11T15:20:00.000000Z",
  "data": {}
}
```

### 2.2 失败

```json
{
  "request_id": "...",
  "ts": "2026-03-11T15:20:00.000000Z",
  "error": {
    "code": "validation_error",
    "message": "...",
    "details": {}
  }
}
```

## 3. 接口列表

### 3.1 会话

#### `GET /sessions`

Query:

- `user_id` 必填

Data:

- `sessions[]`

#### `POST /sessions`

Body:

```json
{
  "user_id": "alice",
  "session_id": ""
}
```

Data:

- `created`
- `session`

#### `GET /session-messages`

Query:

- `user_id` 必填
- `session_id` 必填
- `limit` 可选（`1..5000`）

Data:

- `user_id`
- `session_id`
- `messages[]`

### 3.2 聊天

#### `POST /chat/stream`

Body:

```json
{
  "user_id": "alice",
  "session_id": "default",
  "message": "你好",
  "max_tool_rounds": 6
}
```

说明：

- 返回 `text/event-stream`
- SSE 事件包详见 `sse_protocol.md`

### 3.3 配置

#### `GET /settings`

Query:

- `user_id` 必填

Data:

- `model`
- `api_key`
- `base_url`
- `max_tool_rounds`
- `total_token_limit`

#### `PUT /settings`

Body:

```json
{
  "user_id": "alice",
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "max_tool_rounds": 6,
  "total_token_limit": 200000
}
```

### 3.4 记忆

#### `GET /memory/files`

Query:

- `user_id` 必填

#### `PUT /memory/files/{file_name}`

Query:

- `user_id` 必填

Body:

```json
{
  "content": "新的内容",
  "mode": "overwrite"
}
```

#### `POST /memory/reset`

Query:

- `user_id` 必填

#### `GET /memory/status`

Query:

- `user_id` 必填
- `session_id` 可选（默认 `default`）
- `model` 可选

#### `POST /memory/flush`

Body:

```json
{
  "user_id": "alice",
  "session_id": "default",
  "max_tool_rounds": 6
}
```

## 4. 错误码

- `validation_error`
- `not_found`
- `http_error`
- `internal_error`

## 5. 兼容说明

旧路径 `/api/*` 与 `/v1/*` 已废弃。
