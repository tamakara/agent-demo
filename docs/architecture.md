# 架构设计说明

## 1. 项目目标

`agent-demo` 用于验证一个具备 **可配置上下文窗口**（默认 200K）的 AI 记忆架构，核心能力包括：

- 常驻区与对话区的分层管理
- 工具调用驱动的记忆读写
- token 上限触发的异步刷盘
- 基于 `session_id` 的多会话隔离
- 无 `.env` 的后端无状态调用
- 仅依赖 OpenAI 兼容 API（`chat/completions`）

## 2. 上下文窗口分区

- 总窗口：`total_token_limit`（默认 `200000`，可在设置页配置）
- 系统提示词与记忆文件：`10%`
- 最近对话：`10%`（其中摘要 `1%` + 原始最近对话 `9%`）
- 对话区（含工具与缓冲）：`80%`
- 降级缓冲区：刷盘期间的临时消息区

### 2.1 常驻区组成

1. 固定系统前导说明（含预算信息）
2. `data/memory/系统提示词.md`（结构化为“规则 + 工具定义”）
3. 其他可用记忆文件
4. 工作台摘要（`workbench_summary`，按 1% token 预算裁剪）
5. 最近原始对话（`resident_recent`，按 9% token 动态回收）

### 2.2 对话区组成

- 会话中的用户与助手消息（`zone=dialogue`）
- 工具调用与工具结果（`zone=tool`）

### 2.3 缓冲区组成

- 刷盘进行中产生的新消息（`zone=buffer`）

## 3. 关键策略

1. 后端不从环境变量读取模型配置；LLM 配置（含 `api key`）以全局单例持久化到 SQLite。
2. `系统提示词.md` 仅允许人工接口更新，工具调用写入会被拒绝。

## 4. 异步刷盘流程

触发条件：`total_tokens >= total_token_limit` 且会话当前未处于刷盘中。

执行步骤：

1. 将会话状态设置为 `is_flushing = true`
2. 提取对话区与工具日志
3. 注入“记忆整理专员”归档指令并调用模型
4. 允许模型使用 `write_memory_file` 写入记忆文件
5. 输出纯文本“工作台摘要”
6. 清理 `dialogue/buffer/tool`
7. 按 9% token 预算回填 `resident_recent`，下一条超限则停止追加
8. 更新 `workbench_summary` 并将 `is_flushing` 置回 `false`

## 5. 持久化设计

- 数据库：`data/agent_state.db`
- 表：
  - `sessions`：会话状态与摘要
  - `messages`：消息内容、分区、角色、token 数
- 前端通过 `GET /api/sessions` 与 `POST /api/sessions` 管理会话列表，新增会话会立即持久化到 SQLite。

## 6. SSE 事件协议

`POST /api/chat` 采用 `text/event-stream`，事件顺序如下：

1. `meta`
2. `tool_call`（可多次）
3. `tool_result`（可多次）
4. `assistant_final`
5. `memory_status`
6. `done`

异常时会发送 `error` 事件并结束响应流。
