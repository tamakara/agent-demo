# 前端接入指南

## 本文范围

本文只覆盖前端实现关注点：

- 请求封装
- SSE 解析
- 状态管理
- 错误处理

接口字段详见 `api_reference.md`，SSE 字段详见 `sse_protocol.md`。

## 1. 请求封装建议

建议封装：

- `apiGet(path, query)`
- `apiPost(path, body)`
- `apiPut(path, body)`
- `parseEnvelope(response)`

统一解包逻辑：

1. 先解析 JSON
2. 优先处理 `error`
3. 成功返回 `data`

## 2. user_id / employee_id 传递规则

- 查询接口：query `user_id`
- 员工相关查询同时传 `employee_id`
- 写接口：body `user_id`
- 特例：`PUT /memory/files/{file_name}` 与 `POST /memory/reset` 继续 query 传 `user_id`、`employee_id`

## 3. SSE 解析建议

1. 按 `\n\n` 切分事件块
2. 提取 `data:` 行并 JSON 解析
3. 读取 `envelope.type` 进行分发

建议分发器：

- `meta` -> 系统信息
- `tool_call` / `tool_result` -> 工具日志
- `assistant_final` -> 助手消息
- `memory_status` -> token 面板更新
- `error` -> 错误面板
- `done` -> 收尾状态复位

## 4. 页面状态建议

最小状态：

- `userId`
- `employees`
- `activeEmployeeId`
- `activeSessionId`
- `files`
- `dataTree`
- `activeFile`
- `isChatRunning`

## 5. 交互建议

1. 页面加载先要求输入 `user_id`
2. 用户切换时重置员工、文件和聊天视图
3. 首次进入用户上下文自动保障 1 号员工可用
4. 聊天发送时禁用重复提交
5. 流结束（`done`）后统一刷新员工列表与 memory 状态

## 6. 错误展示建议

- 网络错误：展示摘要 + 技术详情
- envelope 错误：优先展示 `error.message`
- SSE `error`：写入聊天区并结束当前流

## 7. 联调检查清单

1. 前端不再请求 `/sessions` 与 `/session-messages`
2. 所有非流式接口都经过 envelope 解包
3. SSE 处理不依赖 `eventName`，仅依赖 `type`
4. 用户切换与员工切换后数据视图正确隔离
