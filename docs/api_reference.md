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

#### `POST /employees/{employee_id}/reset`

用途：

- 重置指定员工，效果等同“删除该员工后用同编号重建”。
- 会清空该员工会话消息与 `employee/{employee_id}` 目录数据（包含记忆文件、`workspace/`、`skills/` 等）。

Query:

- `user_id` 必填

Path:

- `employee_id` 必填

Data:

- `ok`
- `employee`：重建后的员工条目
- `employees[]`：当前员工列表
- `files[]`：重建后记忆文件
- `tree[]`：最新目录树

#### `DELETE /employees/{employee_id}`

用途：

- 删除指定员工（会话消息与 `employee/{employee_id}` 目录数据）。

Query:

- `user_id` 必填

Path:

- `employee_id` 必填

Data:

- `deleted`（`true`）
- `employee`：被删除的员工条目
- `employees[]`：删除后的员工列表

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
  "message": "你好"
}
```

说明：

- 返回 `text/event-stream`
- SSE 事件包详见 `sse_protocol.md`
- 工具轮次固定为 `64`，不再支持外部配置

### 3.3 配置

#### `GET /settings`

Query:

- `user_id` 必填

Data:

- `model`
- `api_key`
- `base_url`
- `max_tool_rounds`（固定返回 `64`）
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
  "total_token_limit": 200000,
  "tokenizer_model": "gemini-3-flash"
}
```

说明：

- `max_tool_rounds` 已固定为 `64`，`PUT /settings` 不再支持修改该值

### 3.4 记忆

#### `GET /memory/files`

Query:

- `user_id` 必填

Data:

- `data_dir`：用户数据目录绝对路径
- `tree[]`：用户级目录树（`path` + `is_dir`），`employee` 下会展开全部员工目录，例如 `/employee/1/`、`/employee/2/`；目录下一层文件按实际文件类型返回（含文本/图片及其他类型）
- `files[]`：可编辑记忆文件（`employee_id`、`file_name`、`relative_path`、`content`），`relative_path` 形如 `employee/1/notebook/人格设定.md`

#### `GET /memory/file-preview`

用途：

- 预览员工数据目录中的图片文件（用于前端目录点击后的图片展示）。

Query:

- `user_id` 必填
- `path` 必填（来自 `tree.path`，例如 `/employee/1/workspace/a.png`）

响应：

- 直接返回图片文件流（`image/png`、`image/jpeg`、`image/webp` 等），
  不使用统一 JSON envelope。

#### `GET /memory/file-content`

用途：

- 读取目录树中指定文本文件内容（支持 `.md` / `.txt`，用于前端文本编辑器加载）。

Query:

- `user_id` 必填
- `path` 必填（来自 `tree.path`，例如 `/employee/1/notebook/人格设定.md` 或 `/skill_library/demo.txt`）

Data:

- `path`
- `content`

#### `PUT /memory/file-content`

用途：

- 按目录树路径保存文本文件内容（仅 `.md` / `.txt`）。

Query:

- `user_id` 必填
- `path` 必填（来自 `tree.path`）

Body:

```json
{
  "content": "新的内容",
  "mode": "overwrite"
}
```

#### `DELETE /memory/file`

用途：

- 按目录树路径删除选中文件（文件列表展示层会同步刷新）。

Query:

- `user_id` 必填
- `path` 必填（来自 `tree.path`）

限制：

- 仅允许删除 `/brand_library` 与 `/skill_library` 下的文件。
- `/employee/...` 下文件不允许删除。

Data:

- `deleted`（`true`）
- `path`

#### `POST /memory/brand-library/upload`

用途：

- 上传单个或多个文件到用户级素材目录 `/brand_library`。

Query:

- `user_id` 必填

Body（`multipart/form-data`）:

- `files`：可重复字段，支持单文件或多文件上传

说明：

- 若上传文件名与现有文件重复，系统会自动改名为 `name(1).ext`、`name(2).ext` ...（不会覆盖同名文件）

Data:

- `count`：成功写入文件数
- `uploaded[]`
  - `file_name`：实际落盘文件名
  - `original_file_name`：原始上传文件名
  - `renamed`：是否发生自动重命名
  - `name_conflicted`：是否命中重名冲突
  - `path`：目录树路径（例如 `/brand_library/logo.png`）
  - `size`：文件字节数

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

- 仅重置 `employee/<employee_id>/memory.md` 与 `employee/<employee_id>/notebook/**.md`
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
  "employee_id": "1"
}
```

## 4. 错误码

- `validation_error`
- `not_found`
- `http_error`
- `internal_error`
