# 模块职责清单

## 本文范围

本文仅回答“模块做什么”，不描述 API 字段、不描述数据库字段。

## 1. api

- `main.py`：创建 FastAPI 应用、生命周期与全局异常处理
- `api/routes.py`：路由入口与协议转换
- `api/sse.py`：SSE envelope 构建
- `api/requests.py`：请求模型与参数校验
- `api/dependencies.py`：依赖装配（容器）

## 2. app

- `app/ports/repositories.py`：端口定义
- `app/services/employee_service.py`：数字员工相关业务
- `app/services/settings_service.py`：配置相关业务
- `app/services/memory_file_service.py`：记忆文件业务
- `app/use_cases/chat_stream_use_case.py`：聊天用例
- `app/use_cases/flush_use_case.py`：刷盘用例
- `app/use_cases/memory_context.py`：上下文与刷盘核心编排
- `app/use_cases/memory_status_use_case.py`：状态查询用例

## 3. domain

- `domain/models.py`：领域模型
- `domain/window_policy.py`：预算计算
- `domain/prompt_composer.py`：提示词与裁剪逻辑
- `domain/tool_protocol.py`：工具事件协议处理

## 4. infra

- `infra/sqlite/repository.py`：SQLite 仓储适配器
- `infra/memory/storage_layout.py`：用户目录与路径安全
- `infra/memory/file_repository.py`：记忆文件仓储适配器
- `infra/llm/request_builder.py`：LLM 请求构建
- `infra/llm/tool_loop.py`：工具循环执行
- `infra/llm/openai_gateway.py`：OpenAI 兼容网关
- `infra/llm/tiktoken_counter.py`：token 计数适配器
- `infra/tools/tool_registry.py`：工具 schema 与参数解析
- `infra/tools/builtin_tools.py`：内置工具执行器
- `infra/tools/clock.py`：系统时间适配器

## 5. common

- `common/errors.py`：统一错误类型
- `common/response.py`：统一响应 envelope
- `common/ids.py`：user_id / employee_id / session_id 映射规则
- `common/time_utils.py`：时间工具

## 6. 扩展入口

1. 新模型网关：实现 `LLMGatewayPort`
2. 新存储后端：实现仓储端口并在 `api/dependencies.py` 切换装配
3. 新工具：在 `infra/tools` 注册 schema + 执行逻辑
