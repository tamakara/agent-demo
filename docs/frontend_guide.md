# 前端接入指南

## 本文范围

本文只覆盖前端实现关注点：

- 模块拆分
- 请求封装
- SSE 解析
- 状态管理与错误处理

接口字段详见 `api_reference.md`，SSE 字段详见 `sse_protocol.md`。

## 1. 代码结构（已模块化）

- `static/app.js`：入口，仅负责初始化
- `static/js/state.js`：全局状态与路径工具
- `static/js/dom.js`：DOM 引用缓存
- `static/js/api_client.js`：统一请求封装
- `static/js/ui.js`：UI 渲染
- `static/js/logic.js`：业务流程编排

## 2. 路由与参数规则

### 2.1 user 模块

- `/user/settings`
- `/user/employees`
- `/user/employee-messages`

### 2.2 chat 模块

- `/chat/stream`
- `/chat/memory/*`

### 2.3 storage 模块

- `/storage/tree`
- `/storage/file-content`
- `/storage/file-preview`
- `/storage/file`
- `/storage/brand-library/upload`

参数约束：

1. `user_id`、`employee_id` 通过 query 或 body 传递
2. 文件路径统一走 query `path`
3. 上传接口使用 `multipart/form-data` 并通过 query 传 `user_id`

## 3. SSE 解析建议

1. 按 `data:` 行提取 JSON envelope
2. 读取 `type` 分发渲染：
   - `assistant_final`
   - `tool_call`
   - `tool_result`
   - `memory_status`
   - `error`
   - `done`
3. `done` 到达后恢复 UI 交互状态

## 4. 关键状态

- `userId`
- `employees`
- `activeEmployeeId`
- `files`
- `dataTree`
- `selectedFile`
- `isChatting`

## 5. 联调检查清单

1. 前端不再请求 `/users/{user_id}/...` 路径
2. 非流式接口统一走 envelope 解包
3. 用户切换与员工切换后视图正确隔离
4. 文件编辑、上传、删除与图片预览链路可用

