# 前端接入与状态管理

## 1. 文档目标

本文档描述前端如何对接后端能力，聚焦：

- 前端模块拆分
- API 调用约束
- SSE 解析与渲染分发
- 状态管理与联调检查

接口字段以 `api_and_streaming.md` 为准。

## 2. 前端代码结构

- `static/app.js`：入口初始化
- `static/js/state.js`：全局状态与路径辅助
- `static/js/dom.js`：DOM 缓存与元素查找
- `static/js/api_client.js`：HTTP 请求封装
- `static/js/ui.js`：UI 渲染
- `static/js/logic.js`：业务流程编排

## 3. 路由使用约束

1. 不使用 `/{user_id}` 风格路径。
2. `user_id`、`employee_id` 通过 query/body 传递。
3. 文件操作统一使用 query `path`。
4. 上传接口使用 `multipart/form-data`。

常用接口：

- User：`/user/settings`、`/user/employees`、`/user/employee-messages`
- Chat：`/chat/stream`、`/chat/memory/status`、`/chat/memory/flush`
- Storage：`/storage/tree`、`/storage/file-content`、`/storage/file-preview`、`/storage/file`、`/storage/brand-library/upload`

## 4. SSE 解析策略

1. 按 `\n\n` 分帧。
2. 取每帧中的 `data:` 行并解析 JSON。
3. 按 `type` 分发渲染：
   - `assistant_final`
   - `tool_call`
   - `tool_result`
   - `memory_status`
   - `error`
   - `done`
4. 收到 `done` 后恢复可输入状态。

## 5. 推荐前端状态

- `userId`
- `employees`
- `activeEmployeeId`
- `files`
- `dataTree`
- `selectedFile`
- `isChatting`

建议：

1. 用户切换时重置员工上下文与文件树。
2. 员工切换时重载聊天历史和记忆文件。
3. 流式阶段锁定输入框，`done/error` 后解锁。

## 6. 联调检查清单

1. 非流式接口统一按 envelope 解包。
2. `chat/stream` 可正确处理 `tool_call/tool_result` 事件。
3. 用户与员工切换后，消息与文件视图隔离。
4. 文件编辑、上传、删除、预览链路完整可用。
