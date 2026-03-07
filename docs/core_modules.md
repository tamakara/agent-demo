# 核心模块说明

## 1. `core/tools.py`

### 职责

- 定义工具调用的 JSON Schema。
- 实现记忆文件的异步读写能力（`aiofiles`）。
- 提供当前时间查询工具（`get_current_time`）。
- 执行文件名和路径校验，阻止路径穿越。

### 关键约束

- 仅允许访问 `data/memory/*.md`。
- `write_memory_file` 默认禁止写入 `系统提示词.md`。
- `素材库记忆.md` 不做后端硬禁读写，由系统提示词规则约束“默认不主动调用”。
- 启动时会按需将代码内置初始内容写入 `data/memory/*.md`。

### 主要函数

- `read_memory_file_impl(file_name)`
- `write_memory_file_impl(file_name, content, mode, allow_system_prompt=False)`
- `reset_memory_to_initial_content()`
- `get_current_time_impl()`
- `execute_tool_call(tool_name, arguments)`
- `parse_tool_arguments(raw_arguments)`

## 2. `core/agent.py`

### 职责

- 使用 `httpx` 直连 `chat/completions` 接口。
- 执行原生工具调用循环。
- 收集工具事件，供 SSE 输出给前端。
- 提供最大轮次保护，防止工具循环失控。

### 关键约束

- 后端不维护全局 LLM 客户端。
- 每轮调用都使用请求体透传的 `llm_config`。
- 工具参数解析或执行失败时，返回中文错误结果并继续流程。

### 主要对象

- `AgentRunResult`
- `run_agent_with_tools(messages, llm_config, max_tool_rounds, on_event=None)`

## 3. `core/db.py`

### 职责

- 初始化并维护 SQLite 数据库。
- 管理 `sessions/messages/app_settings` 三张核心表。
- 提供分区查询、消息写入、token 统计等数据能力。
- 提供全局设置读写能力（LLM + 上下文总容量）。

### 关键约束

- 所有数据库访问通过异步锁串行化，避免并发竞争。
- `session_id` 是会话主键，用于多会话隔离。
- 全局设置存储在 `app_settings`，与 `session_id` 无关。

### 主要表结构

- `sessions(session_id, workbench_summary, is_flushing, created_at, updated_at)`
- `messages(id, session_id, role, content, zone, token_count, created_at)`
- `app_settings(setting_key, llm_model, llm_api_key, llm_base_url, llm_max_tool_rounds, context_total_token_limit, updated_at)`

## 4. `core/memory_manager.py`

### 职责

- 执行可配置总容量（默认 200K）的上下文分区策略。
- 组装常驻区内容（系统提示词、记忆文件、摘要、最近对话）。
- 管理聊天写入、状态计算和自动刷盘流程。

### 关键约束

- `系统提示词.md` 按“规则 + 工具定义”分段解析。
- 常驻区默认排除 `素材库记忆.md`。
- 刷盘中新增消息写入 `buffer` 分区。
- 刷盘完成后更新 `workbench_summary`，并按 token 预算保留最近原始对话到 `resident_recent`。

### 主要方法

- `process_chat(session_id, user_message, llm_config, max_tool_rounds)`
- `get_status(session_id, model="agent-advoo")`
- `try_start_manual_flush(session_id)`
- `flush_session_memory(session_id, llm_config, max_tool_rounds)`
