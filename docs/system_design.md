# 系统设计与分层

## 1. 文档目标

本文档聚焦系统静态设计，回答以下问题：

- 系统分层与依赖方向是什么
- 各模块职责如何划分
- 核心链路如何在各层流转
- 多用户隔离在架构层如何落地

不包含接口字段与协议细节（见 `api_and_streaming.md`），不包含 token 预算与刷盘细节（见 `state_and_persistence.md`）。

## 2. 设计目标

1. 结构解耦：业务规则不依赖框架、存储和具体模型 SDK。
2. 协议统一：HTTP 与 SSE 返回结构统一。
3. 可替换性：LLM 网关、存储、token 计数器、工具适配可独立替换。

## 3. 分层与依赖方向

```text
api -> app -> domain
       |      ^
       v      |
      ports <- infra

common: 可被所有层复用
```

规则：

1. `api` 仅做协议转换与参数校验，不写业务决策。
2. `app` 只依赖 `app/ports` 抽象，不依赖具体基础设施实现。
3. `domain` 只表达业务规则与模型，不直接访问外部系统。
4. `infra` 实现端口并接入 SQLite、文件系统、LLM、工具等外部能力。

## 4. 顶层包职责

- `api`：路由、请求模型、SSE 输出。
- `app`：用例编排、服务协作、事务边界。
- `domain`：提示词拼装、窗口策略、工具协议转换、领域模型。
- `infra`：仓储、网关、工具执行、目录布局。
- `common`：通用错误、响应模型、时间与 ID 辅助。

## 5. 模块职责映射

### 5.1 Chat

- 会话处理与流式回复
- 上下文预算与裁剪
- 工具循环与工具消息持久化
- 自动/手动刷盘与长期记忆更新

关键文件：

- `app/chat/services/memory_context_service.py`
- `app/chat/use_cases/chat_stream_use_case.py`
- `domain/prompt_composer.py`
- `domain/window_policy.py`
- `infra/llm/openai_gateway.py`

### 5.2 User

- 用户设置管理
- 员工创建、重置、删除
- 员工历史消息查询

关键文件：

- `app/user/services/settings_service.py`
- `app/user/services/employee_service.py`
- `api/routes_user.py`

### 5.3 Storage

- 用户目录树查询
- 文本文件读写删
- 图片预览与素材库上传

关键文件：

- `app/storage/services/memory_file_service.py`
- `api/routes_storage.py`
- `infra/memory/file_repository.py`

## 6. 核心链路（架构视角）

### 6.1 聊天主链路

1. `api/routes_chat.py` 接收 `POST /chat/stream`。
2. `app/chat/use_cases/chat_stream_use_case.py` 编排请求。
3. `app/chat/services/memory_context_service.py` 读取上下文并调用领域规则。
4. `infra/llm/openai_gateway.py` 执行模型调用与工具循环。
5. 结果通过 SSE envelope 回传前端。

### 6.2 刷盘链路

1. 达到阈值后会话标记 `is_flushing=true`。
2. 旧 `dialogue` 归档并更新长期记忆。
3. 刷盘期间 `buffer` 消息迁移到新 `dialogue`。
4. 结束后恢复 `is_flushing=false`。

## 7. 端口与适配器

`app/ports` 定义应用层所需能力，常用端口包括：

- `SessionRepositoryPort`
- `MessageRepositoryPort`
- `UserSettingsRepositoryPort`
- `MemoryFileRepositoryPort`
- `LLMGatewayPort`
- `TokenCounterPort`
- `ClockPort`
- `ToolSchemaProviderPort`

对应适配实现位于 `infra/*`，通过 `api/dependencies.py` 装配。

## 8. 多用户隔离（架构约束）

1. `user_id` 作为租户键贯穿会话、消息、设置和文件目录。
2. 会话锁粒度为 `(user_id, session_id)`，跨用户不互相阻塞。
3. 同一用户不同 `employee_id` 数据独立，不共享记忆文件。
4. 路由通过 query/body 传递 `user_id` 与 `employee_id`，不使用路径级租户前缀。

## 9. 演进规则

1. 新增外部依赖优先放到 `infra` 并实现端口，不在 `domain/app` 直接接 SDK。
2. 新增业务流程先在 `app/use_cases` 编排，再下沉共性逻辑到 `services` 或 `domain`。
3. 避免跨层捷径调用（如 `api` 直接访问 SQLite）。
