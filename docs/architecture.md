# 架构设计说明（多用户版）

## 1. 项目目标

`agent-demo` 现在采用“无鉴权、强隔离”的多用户设计：

- 用户通过 `user_id` 唯一标识（不做身份认证）
- 所有会话、消息、记忆文件、设置都按 `user_id` 隔离
- 前端进入页面后必须先输入 `user_id`
- 不兼容旧数据库结构，不做迁移

## 2. 隔离模型

### 2.1 数据库隔离

- `sessions` 使用复合主键：`(user_id, session_id)`
- `messages` 通过 `(user_id, session_id)` 外键绑定会话
- `app_settings` 以 `user_id` 为主键，保存每个用户独立配置

结论：同一个 `session_id` 在不同 `user_id` 下互不冲突。

### 2.2 文件隔离

记忆文件目录改为：

`data/memory/<user_id>/*.md`

每个用户首次访问时自动初始化模板文件，互不共享。

### 2.3 运行时隔离

`MemoryManager` 的并发锁维度改为 `(user_id, session_id)`，避免不同用户同名会话相互影响。

## 3. 上下文窗口分区

- 总窗口：`total_token_limit`（默认 `200000`）
- 系统提示词与记忆文件：`10%`
- 最近对话：`10%`（摘要 `1%` + 原始最近对话 `9%`）
- 对话区（含工具与缓冲）：`80%`
- 刷盘期间新增消息进入 `buffer`

该策略按用户会话独立执行。

## 4. 刷盘流程（每用户每会话）

触发条件：`total_tokens >= total_token_limit` 且当前会话不在刷盘中。

步骤：

1. `is_flushing = true`
2. 提取该 `user_id + session_id` 的 `dialogue/tool` 记录
3. 调用模型执行归档
4. 允许模型工具写入该用户目录下记忆文件
5. 更新工作台摘要
6. 清理会话消息并回填 `resident_recent`
7. `is_flushing = false`

## 5. 持久化结构

- 数据库：`data/agent_state.db`
- 记忆目录：`data/memory/<user_id>/`

核心表：

- `sessions(user_id, session_id, workbench_summary, is_flushing, created_at, updated_at)`
- `messages(id, user_id, session_id, role, content, zone, token_count, created_at)`
- `app_settings(user_id, llm_model, llm_api_key, llm_base_url, llm_max_tool_rounds, context_total_token_limit, updated_at)`

## 6. SSE 协议

`POST /api/chat` 使用 `text/event-stream`，首个 `meta` 事件包含：

- `user_id`
- `session_id`
- `model`
- `max_tool_rounds`

常见事件顺序：

1. `meta`
2. `tool_call`（可多次）
3. `tool_result`（可多次）
4. `assistant_final`
5. `memory_status`
6. `done`

## 7. 不兼容说明

本版本直接切换为多用户 schema，不兼容旧版单用户数据结构：

- 不做数据迁移脚本
- 旧 `sessions/messages/app_settings` 数据不会自动映射
- 推荐清理旧 `data/agent_state.db` 后启动
