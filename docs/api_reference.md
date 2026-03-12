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

`employee_id` 校验：正整数字符串（`1`、`2`、`3` ...）

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

### 3.1 数字员工

#### `GET /employees`

Query:

- `user_id` 必填

Data:

- `employees[]`

`employees[]` 字段：

- `user_id`
- `employee_id`
- `session_id`（格式：`employee-{employee_id}`）
- `is_flushing`
- `created_at`
- `updated_at`
- `message_count`

#### `POST /employees`

Body:

```json
{
  "user_id": "alice"
}
```

说明：

- 自动创建下一个员工编号（例如已有 `1` 则创建 `2`）

Data:

- `created`
- `employee`

#### `GET /employee-messages`

Query:

- `user_id` 必填
- `employee_id` 可选（默认 `1`）
- `limit` 可选（`1..5000`）

Data:

- `user_id`
- `employee_id`
- `session_id`
- `messages[]`

### 3.2 聊天

#### `POST /chat/stream`

Body:

```json
{
  "user_id": "alice",
  "employee_id": "1",
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
- `tokenizer_model`（`gemini-3-flash` / `gemini-3.1-pro`）

#### `PUT /settings`

Body:

```json
{
  "user_id": "alice",
  "model": "agent-advoo",
  "api_key": "sk-...",
  "base_url": "http://model-gateway.test.api.dotai.internal/v1",
  "max_tool_rounds": 6,
  "total_token_limit": 200000,
  "tokenizer_model": "gemini-3-flash"
}
```

### 3.4 记忆

#### `GET /memory/files`

Query:

- `user_id` 必填
- `employee_id` 可选（默认 `1`）

Data:

- `employee_id`
- `session_id`
- `data_dir`：员工数据目录绝对路径
- `tree[]`：目录树（`path` + `is_dir`）
- `files[]`：可编辑记忆文件（`file_name`、`relative_path`、`content`）

#### `PUT /memory/files/{file_name}`

Query:

- `user_id` 必填
- `employee_id` 可选（默认 `1`）

Path:

- `file_name`：逻辑文件名（例如 `memory.md`、`人格设定.md`）

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
- `employee_id` 可选（默认 `1`）

说明：

- 仅重置 `employee/<employee_id>` 下的记忆模板 Markdown 文件
- `workspace/`、`skills/`、`brand_library/`、`skill_library/` 不会被清空

#### `GET /memory/status`

Query:

- `user_id` 必填
- `employee_id` 可选（默认 `1`）
- `model` 可选

#### `POST /memory/flush`

Body:

```json
{
  "user_id": "alice",
  "employee_id": "1",
  "max_tool_rounds": 6
}
```

## 4. 错误码

- `validation_error`
- `not_found`
- `http_error`
- `internal_error`

## 5. 兼容说明

旧路径 `/sessions` 与 `/session-messages` 已废弃。
