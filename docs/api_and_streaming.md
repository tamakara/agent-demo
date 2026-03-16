# API 与流式协议

## 1. 文档目标

本文档集中描述对外通信契约：

- HTTP 路由与请求参数
- 统一响应 envelope
- `POST /chat/stream` 的 SSE 协议

不包含内部架构与分层设计（见 `system_design.md`），不包含持久化与窗口预算细节（见 `state_and_persistence.md`）。

## 2. 全局约束

1. 路由无统一前缀（不使用 `/api`、`/v1`）。
2. 路由按模块前缀组织：`/user/*`、`/chat/*`、`/storage/*`。
3. `user_id`、`employee_id` 通过 query 或 body 传递。

统一成功响应：

```json
{
  "request_id": "...",
  "ts": "2026-03-15T12:00:00.000000Z",
  "data": {}
}
```

统一失败响应：

```json
{
  "request_id": "...",
  "ts": "2026-03-15T12:00:00.000000Z",
  "error": {
    "code": "validation_error",
    "message": "...",
    "details": {}
  }
}
```

## 3. HTTP 路由清单

### 3.1 User

- `GET /user/settings?user_id=...`
- `PUT /user/settings`
- `GET /user/employees?user_id=...`
- `POST /user/employees`
- `POST /user/employees/{employee_id}/reset?user_id=...`
- `DELETE /user/employees/{employee_id}?user_id=...`
- `GET /user/employee-messages?user_id=...&employee_id=...&limit=50`

`PUT /user/settings` 请求体示例：

```json
{
  "user_id": "alice",
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "total_token_limit": 200000,
  "tokenizer_model": "kimi-k2.5"
}
```

### 3.2 Chat

- `POST /chat/stream`
- `GET /chat/memory/status?user_id=...&employee_id=...`
- `POST /chat/memory/flush`

`POST /chat/stream` 请求体示例：

```json
{
  "user_id": "alice",
  "employee_id": "1",
  "message": "你好"
}
```

### 3.3 Storage

- `GET /storage/tree?user_id=...`
- `GET /storage/file-content?user_id=...&path=...`
- `PUT /storage/file-content?user_id=...&path=...`
- `GET /storage/file-preview?user_id=...&path=...`
- `DELETE /storage/file?user_id=...&path=...`
- `POST /storage/brand-library/upload?user_id=...`（`multipart/form-data`）

`PUT /storage/file-content` 请求体示例：

```json
{
  "content": "...",
  "mode": "overwrite"
}
```

## 4. SSE 协议（`POST /chat/stream`）

响应头：

- `Content-Type: text/event-stream`

每条事件格式：

```text
event: message
data: { ...json envelope... }
```

其中 `event` 固定为 `message`。

### 4.1 Envelope 结构

```json
{
  "type": "meta",
  "seq": 1,
  "request_id": "...",
  "ts": "2026-03-11T15:20:00.000000Z",
  "employee_id": "1",
  "session_id": "employee-1",
  "payload": {}
}
```

字段说明：

- `type`：业务事件类型
- `seq`：单请求内自增序号
- `request_id`：请求标识
- `ts`：UTC 时间戳
- `employee_id`：当前员工编号
- `session_id`：当前会话 ID
- `payload`：事件负载

### 4.2 事件类型

- `meta`
- `tool_call`
- `tool_result`
- `assistant_final`
- `memory_status`
- `done`
- `error`

常见顺序：

1. `meta`
2. `tool_call`（可多次）
3. `tool_result`（可多次）
4. `assistant_final`
5. `memory_status`
6. `done`

异常时通常为：`error` -> `done`。

## 5. 前端消费建议

1. 按 `\n\n` 分帧读取流。
2. 提取 `data:` 行并解析 JSON。
3. 按 `type` 分发渲染，未知类型忽略。
4. 收到 `done` 后恢复输入状态。

## 6. 常见错误场景

- 工具调用参数不匹配 schema。
- 上游模型请求失败或超时。
- 刷盘期间 `buffer` 超限，拒绝新消息。
