# API 与流式协议

## 1. 文档目标

本文档描述当前对外通信契约：

- REST 资源路由
- 统一 JSON 响应 envelope
- 聊天 SSE 协议

## 2. 全局约束

1. 路由无统一前缀（不使用 `/api`、`/v1`）。
2. 路由按资源组织，以 `/users/{user_id}` 为租户入口。
3. 成功与失败响应均使用统一 envelope。

成功响应示例：

```json
{
  "request_id": "...",
  "ts": "2026-03-20T12:00:00.000000Z",
  "data": {}
}
```

失败响应示例：

```json
{
  "request_id": "...",
  "ts": "2026-03-20T12:00:00.000000Z",
  "error": {
    "code": "validation_error",
    "message": "...",
    "details": {}
  }
}
```

## 3. REST 路由

### 3.1 员工与设置

- `GET /users/{user_id}/employees`
- `POST /users/{user_id}/employees`
- `DELETE /users/{user_id}/employees/{employee_id}`
- `POST /users/{user_id}/employees/{employee_id}/reset`
- `GET /users/{user_id}/employees/{employee_id}/messages?limit=500`
- `GET /users/{user_id}/settings`
- `PUT /users/{user_id}/settings`

`PUT /users/{user_id}/settings` body：

```json
{
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "total_token_limit": 200000,
  "tokenizer_model": "kimi-k2.5"
}
```

### 3.2 文件管理

- `GET /users/{user_id}/files/tree`
- `GET /users/{user_id}/files/content?path=...`
- `PUT /users/{user_id}/files/content?path=...`
- `DELETE /users/{user_id}/files/content?path=...`
- `GET /users/{user_id}/files/preview?path=...`
- `POST /users/{user_id}/files/brand-library`（`multipart/form-data`）

`PUT /users/{user_id}/files/content` body：

```json
{
  "content": "...",
  "mode": "overwrite"
}
```

### 3.3 聊天与压缩

- `POST /users/{user_id}/employees/{employee_id}/sessions/{session_id}/messages/stream`
- `GET /users/{user_id}/employees/{employee_id}/sessions/{session_id}/memory`
- `POST /users/{user_id}/employees/{employee_id}/sessions/{session_id}/compressions`

`POST .../messages/stream` body：

```json
{
  "message": "你好"
}
```

## 4. SSE 协议（聊天流）

响应头：

- `Content-Type: text/event-stream`

每帧格式：

```text
event: message
data: { ...json envelope... }
```

### 4.1 SSE Envelope

```json
{
  "type": "meta",
  "seq": 1,
  "request_id": "...",
  "ts": "2026-03-20T12:00:00.000000Z",
  "employee_id": "1",
  "session_id": "employee-1",
  "payload": {}
}
```

字段含义：

- `type`：业务事件类型
- `seq`：单请求内递增序号
- `request_id`：请求追踪 ID
- `ts`：UTC 时间戳
- `employee_id`：员工编号
- `session_id`：会话 ID
- `payload`：事件载荷

### 4.2 事件类型

- `meta`
- `tool_request`
- `tool_response`
- `llm_request`
- `llm_response`
- `llm_error`
- `state_refresh`
- `assistant_final`
- `memory_status`
- `system_event`
- `error`
- `done`

常见顺序：

1. `meta`
2. `tool_request/tool_response`（可多次）
3. `assistant_final`
4. `memory_status`
5. `done`

异常场景：通常为 `error -> done`。

## 5. 前端消费建议

1. 按 `\n\n` 分帧读取。
2. 提取 `data:` 并解析 JSON。
3. 按 `type` 分发渲染，未知类型可忽略。
4. 收到 `done` 后结束本次会话流。
