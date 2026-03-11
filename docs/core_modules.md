# 核心模块说明（多用户版）

## 1. `core/tools.py`

### 职责

- 定义工具调用 JSON Schema
- 管理用户记忆文件目录 `data/user/<user_id>/memory/`
- 执行记忆文件读写和时间查询工具

### 关键约束

- `user_id` 必须匹配：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
- 仅允许访问用户目录下 `.md` 文件
- 默认禁止工具写入 `系统提示词.md`
- 用户首次访问时自动初始化模板记忆文件

### 主要函数

- `ensure_memory_files_exist(user_id)`
- `list_memory_file_names(user_id)`
- `read_memory_file_impl(user_id=..., file_name=...)`
- `write_memory_file_impl(user_id=..., file_name=..., ...)`
- `reset_memory_to_initial_content(user_id)`
- `execute_tool_call(tool_name, arguments, user_id=...)`

## 2. `core/agent.py`

### 职责

- 调用 OpenAI 兼容 `chat/completions`
- 执行工具循环
- 记录并透传工具事件

### 关键变更

- `run_agent_with_tools` 新增 `user_id` 参数
- 工具调用执行时透传 `user_id` 到 `execute_tool_call`

### 主要对象

- `AgentRunResult`
- `run_agent_with_tools(user_id, messages, llm_config, max_tool_rounds, on_event=None, refresh_system_message=None)`

## 3. `core/db.py`

### 职责

- 初始化 SQLite 与索引
- 管理会话、消息、用户设置
- 提供消息分区查询、token 统计、会话状态更新

### 表结构

- `sessions`：`PRIMARY KEY(user_id, session_id)`
- `messages`：含 `(user_id, session_id)` 外键
- `app_settings`：`PRIMARY KEY(user_id)`

### 关键约束

- 所有读写都要求 `user_id`
- 会话隔离键为 `(user_id, session_id)`
- LLM 设置按用户隔离存储

## 4. `core/memory_manager.py`

### 职责

- 管理上下文分区与 token 预算
- 组装常驻区和对话区消息
- 执行自动/手动刷盘流程

### 关键变更

- 并发锁维度从 `session_id` 升级为 `(user_id, session_id)`
- 全部公开方法增加 `user_id`
- 记忆文件读写按 `user_id` 隔离

### 主要方法

- `process_chat(user_id, session_id, user_message, llm_config, max_tool_rounds, on_event=None)`
- `get_status(user_id, session_id, model="agent-advoo")`
- `try_start_manual_flush(user_id, session_id)`
- `flush_session_memory(user_id, session_id, llm_config, max_tool_rounds)`

## 5. `main.py`

### 职责

- FastAPI 路由入口
- SSE 事件输出
- 参数校验和错误转换

### 关键变更

- 所有业务接口显式要求 `user_id`（query 或 body）
- 聊天首帧 `meta` 返回 `user_id + session_id`
- 内存文件接口按需初始化用户目录
