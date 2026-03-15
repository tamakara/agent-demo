# HTTP API 参考

## 本文范围

本文仅覆盖 HTTP 接口：

- 路径
- 参数位置
- 请求体
- 响应要点

SSE 事件协议请看 `sse_protocol.md`。

## 1. 全局规则

1. 路由无前缀（不使用 `/api`、`/v1`）
2. 路由按模块前缀组织：
   - `user`：`/user/...`
   - `chat`：`/chat/...`
   - `storage`：`/storage/...`
3. `user_id`、`employee_id` 不固定在路径中，通过 query 或 body 传递

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

## 2. User 模块

### 2.1 用户设置

- `GET /user/settings?user_id=alice`
- `PUT /user/settings`

`PUT /user/settings` 请求体：

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

### 2.2 员工管理

- `GET /user/employees?user_id=alice`
- `POST /user/employees`
- `POST /user/employees/{employee_id}/reset?user_id=alice`
- `DELETE /user/employees/{employee_id}?user_id=alice`
- `GET /user/employee-messages?user_id=alice&employee_id=1&limit=50`

`POST /user/employees` 请求体：

```json
{
  "user_id": "alice"
}
```

## 3. Chat 模块

### 3.1 流式对话

- `POST /chat/stream`

请求体：

```json
{
  "user_id": "alice",
  "employee_id": "1",
  "message": "你好"
}
```

返回：`text/event-stream`（详见 `sse_protocol.md`）。

### 3.2 记忆能力

- `GET /chat/memory/status?user_id=alice&employee_id=1`
- `POST /chat/memory/flush`

`POST /chat/memory/flush` 请求体：

```json
{
  "user_id": "alice",
  "employee_id": "1"
}
```

## 4. Storage 模块

- `GET /storage/tree?user_id=alice`
- `GET /storage/file-content?user_id=alice&path=/employee/1/notebook/soul.md`
- `PUT /storage/file-content?user_id=alice&path=/employee/1/notebook/soul.md`
- `GET /storage/file-preview?user_id=alice&path=/employee/1/workspace/a.png`
- `DELETE /storage/file?user_id=alice&path=/brand_library/logo.png`
- `POST /storage/brand-library/upload?user_id=alice`（`multipart/form-data`）

`PUT /storage/file-content` 请求体：

```json
{
  "content": "...",
  "mode": "overwrite"
}
```

## 5. 兼容说明

旧的 `/users/{user_id}/...` 样式路由已替换为模块前缀路由。
