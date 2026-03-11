# 架构总览

## 本文范围

本文仅覆盖：

- 系统目标
- 顶层组件关系
- 核心运行链路

本文不覆盖：

- API 字段（见 `api_reference.md`）
- SSE 事件细节（见 `sse_protocol.md`）
- 数据表字段（见 `data_model.md`）

## 1. 目标

项目目标是实现可扩展的多用户记忆智能体服务，强调：

1. 结构解耦（业务逻辑不依赖框架与具体存储）
2. 协议统一（JSON/SSE 统一 envelope）
3. 可替换性（LLM、存储、token 计数器均可替换）

## 2. 顶层包结构

- `api`：HTTP/SSE 对外协议层
- `app`：应用编排层
- `domain`：领域规则层
- `infra`：基础设施适配层
- `common`：跨层通用能力

## 3. 关键设计原则

1. Presentation 不写核心业务，只做协议转换
2. Application 只依赖端口接口，不依赖具体实现
3. Domain 不依赖 FastAPI、SQLite、OpenAI SDK
4. Infrastructure 负责接入外部系统并实现端口

## 4. 主流程（聊天）

1. `api/routes.py` 接收请求并校验
2. `app/use_cases/chat_stream_use_case.py` 编排处理
3. `app/use_cases/memory_context.py` 调用 domain 规则组装上下文
4. `infra/llm/openai_gateway.py` 执行模型与工具循环
5. 结果通过统一 SSE envelope 返回给前端

## 5. 刷盘流程（自动/手动）

1. 达到阈值后标记 `is_flushing=true`
2. 归档 `dialogue/tool` 并更新长期记忆
3. 回填 `resident_recent`、更新摘要
4. 结束后恢复 `is_flushing=false`
